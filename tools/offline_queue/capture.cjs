'use strict';

// Closed-browser recovery only. A native LevelDB engine is opened exclusively on
// a disposable clone; the selected browser database is opened only O_RDONLY.
const fs = require('node:fs/promises');
const {constants} = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const ORIGIN = 'https://finance.marichev.pro';
const ORIGIN_PREFIX = Buffer.from('_' + ORIGIN + '\0', 'utf8');
const FINANCIAL_KEYS = Object.freeze([
  'marichevy_state_v10', 'marichevy_state_v10_corrupt_v1',
  'marichevy_state_v10_cloud_base_v1', 'marichevy_state_v10_cloud_conflict_v1',
  'marichevy_pending_v10', 'marichevy_pending_v10_corrupt_v1',
  'marichevy_state_backup_v44', 'marichevy_state_backup_v44_corrupt_v1',
  'marichevy_pre_import_backup_v73', 'marichevy_pre_import_backup_v73_corrupt_v1'
]);
const ALLOWED_KEYS = new Set(FINANCIAL_KEYS);
const SOURCE_FILE = /^(?:CURRENT|MANIFEST-\d+|\d+\.(?:log|ldb|sst))$/;
const LIMITS = Object.freeze({sourceBytes: 512 * 1024 * 1024, fileBytes: 256 * 1024 * 1024,
  sourceFiles: 4096, captureBytes: 32 * 1024 * 1024});
const OPEN_OPTIONS = Object.freeze({
  createIfMissing: false, errorIfExists: false,
  keyEncoding: 'buffer', valueEncoding: 'buffer'
});
const READ_OPTIONS = Object.freeze({
  keyEncoding: 'buffer', valueEncoding: 'buffer',
  fillCache: false
});
const SAFE_CODES = new Set([
  'invalid-arguments', 'private-output-required', 'source-layout-unsupported',
  'unsupported-sqlite-storage', 'source-unsafe', 'source-incomplete',
  'source-changed', 'source-read-failed', 'source-guard-failed',
  'browser-not-closed', 'source-lock-unavailable', 'windows-required',
  'engine-unavailable', 'engine-checksums-unverified', 'integrity-validation-failed', 'database-read-failed',
  'source-size-limit', 'capture-size-limit',
  'invalid-storage-encoding', 'duplicate-financial-key', 'no-financial-keys',
  'clone-cleanup-failed', 'capture-write-failed', 'capture-failed'
]);

class CaptureError extends Error {
  constructor(code) {
    const safe = SAFE_CODES.has(code) ? code : 'capture-failed';
    super(safe);
    this.name = 'CaptureError';
    this.code = safe;
  }
}
const fail = code => { throw new CaptureError(code); };
const safeError = (error, fallback = 'capture-failed') => error instanceof CaptureError
  ? error : new CaptureError(SAFE_CODES.has(error?.code) ? error.code : fallback);
const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function isFinancialKey(key) {
  return typeof key === 'string' && (ALLOWED_KEYS.has(key) ||
    /^marichevy_state_v10_cloud_conflict_v1_archive_[A-Za-z0-9_-]+$/.test(key));
}

function asBuffer(bytes) {
  if (Buffer.isBuffer(bytes)) return bytes;
  if (bytes instanceof Uint8Array) return Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  fail('invalid-storage-encoding');
}

// Chromium's storage string format is one byte followed by Latin-1 (1) or
// UTF-16LE (0). Node strings retain lone UTF-16 surrogates without replacement.
function decodeScriptString(encoded) {
  const bytes = asBuffer(encoded);
  if (!bytes.length) fail('invalid-storage-encoding');
  if (bytes[0] === 1) return bytes.subarray(1).toString('latin1');
  if (bytes[0] === 0 && (bytes.length - 1) % 2 === 0) return bytes.subarray(1).toString('utf16le');
  fail('invalid-storage-encoding');
}

function decodeFinancialKey(encodedKey) {
  const bytes = asBuffer(encodedKey);
  // Do not decode a different origin, Chromium metadata or a foreign namespace.
  if (bytes.length < ORIGIN_PREFIX.length || !bytes.subarray(0, ORIGIN_PREFIX.length).equals(ORIGIN_PREFIX)) return null;
  const key = decodeScriptString(bytes.subarray(ORIGIN_PREFIX.length));
  return isFinancialKey(key) ? key : null;
}

function prefixUpperBound(prefix) {
  const result = Buffer.from(asBuffer(prefix));
  for (let index = result.length - 1; index >= 0; index--) {
    if (result[index] !== 255) { result[index]++; return result.subarray(0, index + 1); }
  }
  fail('invalid-arguments');
}

function recordFromRaw(key, raw) {
  if (!isFinancialKey(key) || typeof raw !== 'string') fail('invalid-arguments');
  const utf8 = Buffer.from(raw, 'utf8'), utf16 = Buffer.from(raw, 'utf16le');
  return {key, raw, utf16_code_units: raw.length, utf8_bytes: utf8.length,
    sha256_utf8: sha256(utf8), sha256_utf16le: sha256(utf16)};
}

function within(parent, child) {
  const relative = path.relative(parent, child);
  return relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative));
}

async function directory(realPath, code) {
  const stat = await fs.lstat(realPath);
  if (!stat.isDirectory() || stat.isSymbolicLink()) fail(code);
  return fs.realpath(realPath);
}

async function exists(filename) {
  try { await fs.lstat(filename); return true; }
  catch (error) { if (error.code === 'ENOENT') return false; throw error; }
}

function identity(stat) {
  return [stat.dev, stat.ino, stat.size, stat.mtimeNs, stat.ctimeNs].map(String).join(':');
}

async function sourceNames(sourceDir) {
  const entries = await fs.readdir(sourceDir, {withFileTypes: true});
  const files = entries.filter(entry => SOURCE_FILE.test(entry.name));
  if (files.some(entry => !entry.isFile() || entry.isSymbolicLink())) fail('source-unsafe');
  const names = files.map(entry => entry.name).sort();
  if (names.length > LIMITS.sourceFiles) fail('source-size-limit');
  if (!names.includes('CURRENT') || !names.some(name => /^MANIFEST-\d+$/.test(name))) fail('source-incomplete');
  return names;
}

async function hashFile(filename, copyTo = null) {
  const source = await fs.lstat(filename, {bigint: true});
  if (!source.isFile() || source.isSymbolicLink()) fail('source-unsafe');
  if (source.size > BigInt(LIMITS.fileBytes)) fail('source-size-limit');
  const readFlags = constants.O_RDONLY | (constants.O_NOFOLLOW || 0);
  let input, output;
  try {
    input = await fs.open(filename, readFlags);
    const opened = await input.stat({bigint: true});
    if (!opened.isFile() || identity(opened) !== identity(source)) fail('source-changed');
    if (copyTo) output = await fs.open(copyTo, 'wx', 0o600);
    const digest = crypto.createHash('sha256'), buffer = Buffer.allocUnsafe(1024 * 1024);
    for (;;) {
      const {bytesRead} = await input.read(buffer, 0, buffer.length, null);
      if (!bytesRead) break;
      const part = buffer.subarray(0, bytesRead); digest.update(part);
      if (output) {
        let written = 0;
        while (written < bytesRead) {
          const result = await output.write(part, written, bytesRead - written, null);
          if (!result.bytesWritten) fail('source-read-failed');
          written += result.bytesWritten;
        }
      }
    }
    const after = await input.stat({bigint: true});
    if (identity(after) !== identity(opened)) fail('source-changed');
    if (output) await output.sync();
    return {identity: identity(after), sha256: digest.digest('hex')};
  } finally {
    if (output) await output.close();
    if (input) await input.close();
  }
}

async function snapshot(sourceDir, copyDir = null) {
  const names = await sourceNames(sourceDir), files = new Map();
  let total = 0n;
  for (const name of names) total += (await fs.lstat(path.join(sourceDir, name), {bigint:true})).size;
  if (total > BigInt(LIMITS.sourceBytes)) fail('source-size-limit');
  for (const name of names) files.set(name, await hashFile(path.join(sourceDir, name), copyDir && path.join(copyDir, name)));
  const current = await fs.readFile(path.join(copyDir || sourceDir, 'CURRENT'));
  if (!/^MANIFEST-\d+\n$/.test(current.toString('ascii')) || current.some(byte => byte > 127)) fail('source-incomplete');
  if (!files.has(current.toString('ascii').trim())) fail('source-incomplete');
  return {names, files};
}

function sameSnapshot(left, right) {
  return JSON.stringify(left.names) === JSON.stringify(right.names) &&
    left.names.every(name => left.files.get(name).sha256 === right.files.get(name).sha256 &&
      left.files.get(name).identity === right.files.get(name).identity);
}

async function defaultPrivateTemp(outputDir, prefix) {
  const target = await fs.mkdtemp(path.join(outputDir, prefix));
  await fs.chmod(target, 0o700);
  return target;
}

async function recordsFromPrivateClone(cloneDir, openDatabase, proof) {
  // The pinned engine resolves the live manifest/WAL/tombstones. Its API ignores
  // optional checksum flags, so every clone must pass the separate physical
  // CRC/batch/table validator before the native engine may open it.
  if (typeof openDatabase !== 'function') fail('engine-unavailable');
  if (!proof || proof.validated !== true || proof.strictChecksums !== true ||
      proof.format !== 'leveldb-integrity-v1' || proof.checksumSource !== 'external-crc32c-preflight') fail('engine-checksums-unverified');
  let database, iterator, failure = null;
  const records = [], seen = new Set();
  let serializedBytes = 0;
  try {
    database = await openDatabase(cloneDir, {...OPEN_OPTIONS}, proof);
    if (!database || typeof database.open !== 'function' || typeof database.keys !== 'function' ||
        typeof database.get !== 'function' || typeof database.close !== 'function') fail('engine-unavailable');
    await database.open({...OPEN_OPTIONS});
    iterator = database.keys({...READ_OPTIONS, gte: Buffer.from(ORIGIN_PREFIX), lt: prefixUpperBound(ORIGIN_PREFIX)});
    for await (const encodedKey of iterator) {
      const key = decodeFinancialKey(encodedKey);
      if (key === null) continue;
      if (seen.has(key)) fail('duplicate-financial-key');
      // Values of session keys and other keys never reach get() or a decoder.
      const encodedValue = await database.get(encodedKey, {...READ_OPTIONS});
      if (encodedValue.length > LIMITS.captureBytes) fail('capture-size-limit');
      const raw = decodeScriptString(encodedValue);
      const record = recordFromRaw(key, raw);
      // Bound the escaped JSON too, before constructing the complete wrapper.
      serializedBytes += Buffer.byteLength(JSON.stringify(record), 'utf8') + 256;
      if (serializedBytes > LIMITS.captureBytes) fail('capture-size-limit');
      records.push(record); seen.add(key);
    }
  } catch (error) { failure = safeError(error, 'database-read-failed'); }
  finally {
    if (iterator?.close) try { await iterator.close(); } catch (_) { failure ||= new CaptureError('database-read-failed'); }
    if (database) try { await database.close(); } catch (_) { failure ||= new CaptureError('database-read-failed'); }
  }
  if (failure) throw failure;
  if (!records.length) fail('no-financial-keys');
  return records.sort((left, right) => left.key < right.key ? -1 : left.key > right.key ? 1 : 0);
}

async function captureProfile(options = {}) {
  const {sourceDir, outputDir, withSourceLock, openDatabase, validateClone, makePrivateTemp = defaultPrivateTemp, now = () => new Date()} = options;
  if (typeof sourceDir !== 'string' || typeof outputDir !== 'string' || typeof withSourceLock !== 'function' ||
      typeof makePrivateTemp !== 'function' || typeof now !== 'function') fail('invalid-arguments');
  if (typeof openDatabase !== 'function') fail('engine-unavailable');
  if (typeof validateClone !== 'function') fail('engine-checksums-unverified');
  const sourcePath = path.resolve(sourceDir);
  if (path.basename(sourcePath).toLowerCase() !== 'leveldb' ||
      path.basename(path.dirname(sourcePath)).toLowerCase() !== 'local storage') fail('source-layout-unsupported');
  let outputPath, cloneRoot = null, cloneDir = null, records, failure = null, sourceReal = null, copyFinished = false;
  try {
    outputPath = await directory(path.resolve(outputDir), 'private-output-required');
    await withSourceLock(sourcePath, async () => {
      if (copyFinished || cloneRoot) fail('source-guard-failed');
      sourceReal = await directory(sourcePath, 'source-unsafe');
      if (within(sourceReal, outputPath) || within(outputPath, sourceReal)) fail('private-output-required');
      const sqlite = path.resolve(sourceReal, '..', '..', 'LocalStorage');
      if (await exists(sqlite) || await exists(sqlite + '-wal')) fail('unsupported-sqlite-storage');
      cloneRoot = path.resolve(await makePrivateTemp(outputPath, 'private-queue-clone-'));
      if (cloneRoot === outputPath || !within(outputPath, cloneRoot) || within(sourceReal, cloneRoot) || within(cloneRoot, sourceReal)) fail('private-output-required');
      const cloneReal = await directory(cloneRoot, 'private-output-required');
      if (cloneReal !== cloneRoot) fail('private-output-required');
      cloneDir = path.join(cloneRoot, 'leveldb'); await fs.mkdir(cloneDir, {mode: 0o700});
      const copied = await snapshot(sourceReal, cloneDir);
      for (const name of copied.names) if ((await hashFile(path.join(cloneDir, name))).sha256 !== copied.files.get(name).sha256) fail('source-changed');
      const after = await snapshot(sourceReal);
      if (!sameSnapshot(copied, after)) fail('source-changed');
      // The marker is outside the engine directory and contains no source data.
      await fs.writeFile(path.join(cloneRoot, '.disposable-clone'), 'closed-browser-file-copy\n', {flag: 'wx', mode: 0o600});
      copyFinished = true;
    });
    if (!copyFinished || !cloneDir || !sourceReal || path.resolve(cloneDir) === sourceReal) fail('source-guard-failed');
    let proof;
    try { proof = await validateClone(cloneDir); }
    catch (_) { fail('integrity-validation-failed'); }
    records = await recordsFromPrivateClone(cloneDir, openDatabase, proof);
  } catch (error) { failure = safeError(error, 'source-read-failed'); }
  finally {
    // No capture is created until every private database clone is removed.
    if (cloneRoot) {
      try {
        if (!outputPath || cloneRoot === outputPath || !within(outputPath, cloneRoot)) fail('clone-cleanup-failed');
        await fs.rm(cloneRoot, {recursive: true, force: true});
        if (await exists(cloneRoot)) fail('clone-cleanup-failed');
      } catch (_) { failure = new CaptureError('clone-cleanup-failed'); }
    }
  }
  if (failure) throw failure;
  let artifact = null, file = null, ownedFile = false;
  try {
    const capturedAt = now().toISOString();
    const capture = {
      format: 'marichevy-local-queue-capture-v1',
      purpose: 'PRIVATE-read-only-local-recovery-capture-not-an-application-import',
      origin: ORIGIN, captured_at_device_utc: capturedAt,
      device_clock_verified: false, key_count: records.length,
      session_included: false, storage_modified: false,
      capture_method: 'closed-browser-file-copy', memory_state_included: false, records
    };
    const serialized = JSON.stringify(capture, null, 2) + '\n';
    if (Buffer.byteLength(serialized,'utf8') > LIMITS.captureBytes) fail('capture-size-limit');
    artifact = path.join(outputPath, 'marichevy-local-queue-PRIVATE-' + capturedAt.replace(/[^0-9]/g, '') + '-' + crypto.randomBytes(8).toString('hex') + '.json');
    file = await fs.open(artifact, 'wx', 0o600);
    ownedFile = true;
    await file.writeFile(serialized, 'utf8'); await file.sync(); await file.close(); file = null;
    return {outcome: 'captured', output_path: artifact};
  } catch (error) {
    if (file) try { await file.close(); } catch (_) {}
    if (artifact && ownedFile) try { await fs.rm(artifact, {force: true}); } catch (_) {}
    throw safeError(error,'capture-write-failed');
  }
}

module.exports = Object.freeze({
  ORIGIN, FINANCIAL_KEYS, OPEN_OPTIONS, READ_OPTIONS, LIMITS, CaptureError,
  isFinancialKey, decodeScriptString, decodeFinancialKey, prefixUpperBound,
  recordFromRaw, captureProfile
});

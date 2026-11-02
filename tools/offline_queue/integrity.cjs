'use strict';

// External integrity preflight for a DISPOSABLE PRIVATE CLONE, before native
// LevelDB recovery. classic-level's prebuild does not enforce the requested
// checksum/paranoid options. This module supplies that proof independently.
// No browser key/value strings are decoded, logged, repaired or written here.
const fs = require('node:fs/promises');
const {constants} = require('node:fs');
const path = require('node:path');

const LIMITS = Object.freeze({
  totalBytes: 512 * 1024 * 1024,
  fileBytes: 256 * 1024 * 1024,
  files: 4096,
  blockBytes: 64 * 1024 * 1024,
  metadataBytes: 128 * 1024 * 1024,
  records: 1000000,
  entries: 1000000
});
const CODES = new Set(['integrity-unsafe-clone', 'integrity-limit', 'integrity-current',
  'integrity-manifest', 'integrity-log', 'integrity-checksum', 'integrity-write-batch',
  'integrity-table', 'integrity-compression', 'integrity-metadata', 'integrity-read']);
class IntegrityError extends Error {
  constructor(code) {
    const safe = CODES.has(code) ? code : 'integrity-read';
    super(safe); this.name = 'IntegrityError'; this.code = safe;
  }
}
const fail = code => { throw new IntegrityError(code); };
const MAX_SEQUENCE = (1n << 56n) - 1n;
const TABLE_MAGIC = 0xdb4775248b80fb57n;
const FILE_NAME = /^(?:CURRENT|LOCK|LOG(?:\.old)?|MANIFEST-\d+|\d+\.(?:log|ldb|sst|dbtmp))$/;
const CRC_TABLE = new Uint32Array(256);
for (let i = 0; i < 256; i++) {
  let crc = i;
  for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0x82f63b78 : 0);
  CRC_TABLE[i] = crc >>> 0;
}
function maskedCRC(parts) {
  let crc = 0xffffffff;
  for (const part of parts) for (let i = 0; i < part.length; i++)
    crc = (CRC_TABLE[(crc ^ part[i]) & 255] ^ (crc >>> 8)) >>> 0;
  crc = (~crc) >>> 0;
  return (((crc >>> 15) | (crc << 17)) + 0xa282ead8) >>> 0;
}
function zero(bytes) {
  for (const value of bytes) if (value !== 0) return false;
  return true;
}
function identity(stat) {
  return [stat.dev, stat.ino, stat.size, stat.mtimeNs, stat.ctimeNs].map(String).join(':');
}
class Cursor {
  constructor(bytes, code, end = bytes.length) {
    this.bytes = bytes; this.code = code; this.at = 0; this.end = end;
  }
  varint(bits = 64) {
    let value = 0n;
    const maximum = Math.ceil(bits / 7);
    for (let index = 0; index < maximum; index++) {
      if (this.at >= this.end) fail(this.code);
      const byte = this.bytes[this.at++];
      value |= BigInt(byte & 127) << BigInt(index * 7);
      if (!(byte & 128)) {
        if (value >= (1n << BigInt(bits))) fail(this.code);
        return value;
      }
    }
    fail(this.code);
  }
  number(maximum, bits = 32) {
    const value = this.varint(bits);
    if (value > BigInt(maximum)) fail(this.code);
    return Number(value);
  }
  slice() {
    const length = this.number(LIMITS.blockBytes);
    if (length > this.end - this.at) fail(this.code);
    const result = this.bytes.subarray(this.at, this.at + length);
    this.at += length; return result;
  }
}

// The physical log format is shared by MANIFEST and WAL. Padding is allowed
// only in the <7 remaining bytes of a 32KiB physical block, and must be zero.
function physicalRecords(bytes, code, callback) {
  let at = 0, fragments = null, fragmentBytes = 0, count = 0, physical = 0;
  while (at < bytes.length) {
    const physicalEnd = (Math.floor(at / 32768) + 1) * 32768;
    const end = Math.min(bytes.length, physicalEnd);
    if (physicalEnd - at < 7) {
      if (end !== physicalEnd) fail(code); // An incomplete trailer is torn too.
      if (!zero(bytes.subarray(at, end))) fail(code);
      at = end; continue;
    }
    if (end - at < 7) fail(code); // Even a zero-filled partial header is torn.
    const expected = bytes.readUInt32LE(at), length = bytes.readUInt16LE(at + 4), type = bytes[at + 6];
    if (++physical > LIMITS.records) fail('integrity-limit');
    if (type < 1 || type > 4 || length > end - at - 7) fail(code);
    const payload = bytes.subarray(at + 7, at + 7 + length);
    if (maskedCRC([bytes.subarray(at + 6, at + 7), payload]) !== expected) fail('integrity-checksum');
    at += 7 + length;
    if (type === 1) {
      if (fragments !== null) fail(code);
      if (++count > LIMITS.records) fail('integrity-limit');
      callback(payload);
    } else if (type === 2) {
      if (fragments !== null) fail(code);
      fragments = [payload]; fragmentBytes = payload.length;
    } else {
      if (fragments === null) fail(code);
      fragments.push(payload); fragmentBytes += payload.length;
      if (fragmentBytes > LIMITS.blockBytes) fail('integrity-limit');
      if (type === 4) {
        if (++count > LIMITS.records) fail('integrity-limit');
        callback(Buffer.concat(fragments, fragmentBytes));
        fragments = null; fragmentBytes = 0;
      }
    }
  }
  if (fragments !== null) fail(code);
  return count;
}

function internalKey(key, code) {
  if (key.length < 8 || (key.readBigUInt64LE(key.length - 8) & 255n) > 1n) fail(code);
}
function manifestState(bytes) {
  const state = {comparator: null, log: null, previousLog: 0n, nextFile: null, sequence: null, tables: new Map()};
  let tags = 0;
  state.records = physicalRecords(bytes, 'integrity-manifest', record => {
    const cursor = new Cursor(record, 'integrity-manifest'), removed = [], added = [];
    while (cursor.at < cursor.end) {
      if (++tags > LIMITS.entries) fail('integrity-limit');
      const tag = cursor.number(255);
      if (tag === 1) {
        const comparator = cursor.slice();
        if (!comparator.equals(Buffer.from('leveldb.BytewiseComparator'))) fail('integrity-manifest');
        state.comparator = 'leveldb.BytewiseComparator';
      } else if (tag === 2) state.log = cursor.varint();
      else if (tag === 3) state.nextFile = cursor.varint();
      else if (tag === 4) {
        state.sequence = cursor.varint();
        if (state.sequence > MAX_SEQUENCE) fail('integrity-manifest');
      } else if (tag === 5) {
        cursor.number(6); internalKey(cursor.slice(), 'integrity-manifest');
      } else if (tag === 6) {
        if (removed.length >= LIMITS.files) fail('integrity-limit');
        removed.push({level: cursor.number(6), number: cursor.varint()});
      }
      else if (tag === 7) {
        if (added.length >= LIMITS.files) fail('integrity-limit');
        const level = cursor.number(6), number = cursor.varint(), size = cursor.varint();
        const smallest = cursor.slice(), largest = cursor.slice();
        internalKey(smallest, 'integrity-manifest'); internalKey(largest, 'integrity-manifest');
        if (number === 0n || size < 48n || size > BigInt(LIMITS.fileBytes)) fail('integrity-manifest');
        added.push({level, number, size: Number(size)});
      } else if (tag === 9) state.previousLog = cursor.varint();
      else fail('integrity-manifest');
    }
    // VersionSet applies all deletions before additions within an edit.
    for (const item of removed) {
      const old = state.tables.get(String(item.number));
      if (old?.level === item.level) state.tables.delete(String(item.number));
    }
    for (const item of added) {
      if (state.tables.has(String(item.number))) fail('integrity-manifest');
      state.tables.set(String(item.number), item);
      if (state.tables.size > LIMITS.files) fail('integrity-limit');
    }
  });
  if (!state.records || !state.comparator || state.log === null || state.nextFile === null ||
      state.nextFile === 0n || state.sequence === null) fail('integrity-manifest');
  return state;
}

function writeBatch(bytes) {
  if (bytes.length < 12) fail('integrity-write-batch');
  const sequence = bytes.readBigUInt64LE(0), count = bytes.readUInt32LE(8);
  if (count > LIMITS.entries || sequence > MAX_SEQUENCE ||
      (count === 0 && sequence === 0n) ||
      (count && sequence + BigInt(count - 1) > MAX_SEQUENCE)) fail('integrity-write-batch');
  const cursor = new Cursor(bytes, 'integrity-write-batch'); cursor.at = 12;
  for (let index = 0; index < count; index++) {
    if (cursor.at >= cursor.end) fail('integrity-write-batch');
    const operation = bytes[cursor.at++];
    cursor.slice(); // Raw user key bytes only; never decode a storage key.
    if (operation === 1) cursor.slice(); // Raw value bytes only; never decode.
    else if (operation !== 0) fail('integrity-write-batch');
  }
  if (cursor.at !== cursor.end) fail('integrity-write-batch');
}

function blockHandle(cursor, maximum) {
  const offset = cursor.number(maximum, 64), size = cursor.number(maximum, 64);
  if (!size || offset > maximum || size + 5 > maximum - offset) fail('integrity-table');
  return {offset, size};
}

// Parse restart metadata and lengths, not application data. Callers use this
// only for index/metaindex blocks, whose values are encoded block handles.
function entries(bytes, callback, budget) {
  if (bytes.length < 8) fail('integrity-metadata');
  const count = bytes.readUInt32LE(bytes.length - 4);
  if (!count || count > LIMITS.entries || count > Math.floor((bytes.length - 4) / 4)) fail('integrity-metadata');
  const end = bytes.length - 4 - count * 4, restarts = [];
  for (let index = 0; index < count; index++) {
    const offset = bytes.readUInt32LE(end + index * 4);
    if ((index === 0 && offset !== 0) || offset > end ||
        (index && offset <= restarts[index - 1]) || (end > 0 && offset === end)) fail('integrity-metadata');
    restarts.push(offset);
  }
  if (end === 0) { if (count !== 1) fail('integrity-metadata'); return; }
  const cursor = new Cursor(bytes, 'integrity-metadata', end);
  let key = Buffer.alloc(0), restart = 0, total = 0;
  while (cursor.at < end) {
    const position = cursor.at;
    if (restart < restarts.length && restarts[restart] < position) fail('integrity-metadata');
    const isRestart = restarts[restart] === position;
    const shared = cursor.number(key.length), extra = cursor.number(LIMITS.blockBytes), length = cursor.number(LIMITS.blockBytes);
    if ((isRestart && shared !== 0) || extra + length > end - cursor.at || shared + extra > LIMITS.blockBytes) fail('integrity-metadata');
    // Prefix-compressed metadata must not amplify a small block into unbounded
    // copying of a long prior key. This budget is shared across every table.
    budget.keys += shared + extra;
    if (budget.keys > LIMITS.metadataBytes) fail('integrity-limit');
    if (shared !== key.length || extra !== 0)
      key = Buffer.concat([key.subarray(0, shared), bytes.subarray(cursor.at, cursor.at + extra)], shared + extra);
    cursor.at += extra;
    const value = bytes.subarray(cursor.at, cursor.at + length); cursor.at += length;
    if (++total > LIMITS.entries) fail('integrity-limit');
    callback(key, value);
    if (isRestart) restart++;
  }
  if (cursor.at !== end || restart !== restarts.length) fail('integrity-metadata');
}

function snappyLength(bytes) {
  const cursor = new Cursor(bytes, 'integrity-compression');
  const length = cursor.number(LIMITS.blockBytes);
  return length;
}

function validateTable(bytes, budget) {
  if (bytes.length < 48 || bytes.readBigUInt64LE(bytes.length - 8) !== TABLE_MAGIC) fail('integrity-table');
  const footerStart = bytes.length - 48, footer = new Cursor(bytes.subarray(footerStart), 'integrity-table', 40);
  const meta = blockHandle(footer, footerStart), index = blockHandle(footer, footerStart);
  if (!zero(footer.bytes.subarray(footer.at, 40)) || meta.offset >= index.offset) fail('integrity-table');
  const visited = new Map(), ranges = [];
  function block(handle, expand) {
    const id = handle.offset + ':' + handle.size;
    const old = visited.get(id);
    if (old) { if (expand && !old.expanded) fail('integrity-table'); return old.data; }
    const end = handle.offset + handle.size;
    ranges.push({start: handle.offset, end: end + 5});
    if (ranges.length > LIMITS.entries) fail('integrity-limit');
    // Even malformed overlapping handles cannot amplify CRC work beyond the
    // total input budget. Check overlaps with one sorted pass afterwards.
    budget.checked += handle.size + 5;
    if (budget.checked > LIMITS.totalBytes) fail('integrity-limit');
    const type = bytes[end], payload = bytes.subarray(handle.offset, end);
    if (maskedCRC([bytes.subarray(handle.offset, end + 1)]) !== bytes.readUInt32LE(end + 1)) fail('integrity-checksum');
    if (type !== 0 && type !== 1) fail('integrity-compression');
    const expandedLength = type === 1 ? snappyLength(payload) : payload.length;
    if (expandedLength > LIMITS.blockBytes) fail('integrity-limit');
    let data = payload;
    if (expand) {
      budget.expanded += expandedLength;
      if (budget.expanded > LIMITS.metadataBytes) fail('integrity-limit');
      if (type === 1) {
        try { data = Buffer.from(require('snappyjs').uncompress(payload)); }
        catch (_) { fail('integrity-compression'); }
        if (data.length !== expandedLength) fail('integrity-compression');
      }
    }
    visited.set(id, {expanded: expand, data}); return data;
  }
  const metaBytes = block(meta, true), indexBytes = block(index, true);
  let lastDataEnd = 0;
  entries(indexBytes, (key, value) => {
    internalKey(key, 'integrity-metadata');
    const cursor = new Cursor(value, 'integrity-table'), handle = blockHandle(cursor, footerStart);
    if (cursor.at !== cursor.end || handle.offset < lastDataEnd || handle.offset + handle.size + 5 > meta.offset) fail('integrity-table');
    lastDataEnd = handle.offset + handle.size + 5;
    block(handle, false); // CRC compressed application block; do not unpack its values.
  }, budget);
  entries(metaBytes, (key, value) => {
    if (key.length <= 7 || !key.subarray(0, 7).equals(Buffer.from('filter.')) ||
        key.length > 256 || [...key].some(byte => byte < 32 || byte > 126)) fail('integrity-metadata');
    const cursor = new Cursor(value, 'integrity-table'), handle = blockHandle(cursor, footerStart);
    if (cursor.at !== cursor.end || handle.offset < lastDataEnd || handle.offset + handle.size + 5 > meta.offset) fail('integrity-table');
    block(handle, false); // Bloom-filter layout is not a restart-entry block.
  }, budget);
  ranges.sort((left, right) => left.start - right.start);
  for (let index = 1; index < ranges.length; index++)
    if (ranges[index].start < ranges[index - 1].end) fail('integrity-table');
}

async function validateClone(cloneDir) {
  try {
    if (typeof cloneDir !== 'string' || !cloneDir) fail('integrity-unsafe-clone');
    const directory = path.resolve(cloneDir), root = await fs.lstat(directory);
    if (!root.isDirectory() || root.isSymbolicLink()) fail('integrity-unsafe-clone');
    async function listNames() {
      const result = [];
      for await (const entry of await fs.opendir(directory)) {
        if (result.length >= LIMITS.files) fail('integrity-limit');
        result.push(entry.name);
      }
      return result;
    }
    const names = await listNames();
    if (!names.length) fail('integrity-limit');
    const files = new Map(); let inventoryBytes = 0;
    for (const name of names) {
      if (!FILE_NAME.test(name)) fail('integrity-unsafe-clone');
      const stat = await fs.lstat(path.join(directory, name), {bigint: true});
      if (!stat.isFile() || stat.isSymbolicLink()) fail('integrity-unsafe-clone');
      if (stat.size > BigInt(LIMITS.fileBytes)) fail('integrity-limit');
      inventoryBytes += Number(stat.size);
      if (inventoryBytes > LIMITS.totalBytes) fail('integrity-limit');
      files.set(name, {size: Number(stat.size), identity: identity(stat)});
    }
    const checked = new Set(); let bytesValidated = 0;
    async function read(name) {
      const expected = files.get(name); if (!expected) fail('integrity-read');
      if (name === 'CURRENT' && expected.size > 64) fail('integrity-current');
      const input = await fs.open(path.join(directory, name), constants.O_RDONLY | (constants.O_NOFOLLOW || 0));
      try {
        const before = await input.stat({bigint: true});
        if (!before.isFile() || identity(before) !== expected.identity) fail('integrity-unsafe-clone');
        // A changing file must not grow an unbounded readFile allocation.
        const bytes = Buffer.allocUnsafe(expected.size);
        let position = 0;
        while (position < bytes.length) {
          const result = await input.read(bytes, position, Math.min(1024 * 1024, bytes.length - position), position);
          if (!result.bytesRead) fail('integrity-unsafe-clone');
          position += result.bytesRead;
        }
        const extra = await input.read(Buffer.alloc(1), 0, 1, position);
        if (extra.bytesRead || identity(await input.stat({bigint: true})) !== expected.identity) fail('integrity-unsafe-clone');
        if (!checked.has(name)) { checked.add(name); bytesValidated += bytes.length; }
        return bytes;
      } finally { await input.close(); }
    }
    const current = await read('CURRENT');
    if (current.length > 64 || current.some(byte => byte > 127) || !/^MANIFEST-\d+\n$/.test(current.toString('ascii'))) fail('integrity-current');
    const manifest = current.toString('ascii').slice(0, -1);
    const state = manifestState(await read(manifest));
    const numeric = new Map();
    for (const name of names) {
      const match = /^(\d+)\.(log|ldb|sst)$/.exec(name);
      if (match) {
        const key = String(BigInt(match[1])) + ':' + (match[2] === 'log' ? 'log' : 'table');
        if (numeric.has(key)) fail('integrity-manifest');
        numeric.set(key, name);
      }
    }
    const budget = {expanded: 0, keys: 0, checked: 0};
    for (const item of state.tables.values()) {
      const name = numeric.get(String(item.number) + ':table');
      if (!name || files.get(name).size !== item.size) fail('integrity-manifest');
      validateTable(await read(name), budget);
    }
    let walFilesValidated = 0;
    if (state.log && !numeric.has(String(state.log) + ':log')) fail('integrity-manifest');
    if (state.previousLog && !numeric.has(String(state.previousLog) + ':log')) fail('integrity-manifest');
    for (const [key, name] of numeric) {
      if (!key.endsWith(':log')) continue;
      const number = BigInt(key.slice(0, -4));
      // Match VersionSet recovery: also validate newer logs not yet manifested.
      if (number >= state.log || number === state.previousLog) {
        physicalRecords(await read(name), 'integrity-log', writeBatch); walFilesValidated++;
      }
    }
    if (JSON.stringify((await listNames()).sort()) !== JSON.stringify(names.slice().sort())) fail('integrity-unsafe-clone');
    for (const [name, expected] of files) {
      const stat = await fs.lstat(path.join(directory, name), {bigint: true});
      if (!stat.isFile() || stat.isSymbolicLink() || identity(stat) !== expected.identity) fail('integrity-unsafe-clone');
    }
    return Object.freeze({validated: true, format: 'leveldb-integrity-v1', strictChecksums: true,
      checksumSource: 'external-crc32c-preflight', filesValidated: checked.size, bytesValidated,
      tablesValidated: state.tables.size, walFilesValidated, manifestRecordsValidated: state.records});
  } catch (error) {
    if (error instanceof IntegrityError) throw error;
    throw new IntegrityError('integrity-read');
  }
}

module.exports = {validateClone, IntegrityError, LIMITS};

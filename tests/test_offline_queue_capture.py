"""Linux-only synthetic LevelDB acceptance of the closed-browser capture core.

No real browser profile, production data, or private backup directory is read.
Install the pinned helper dependencies first; OFFLINE_QUEUE_NODE_MODULES can
point at their node_modules directory. The development fixture defaults to
/tmp/v95-offline-work/node_modules. These tests do not establish Windows FFI or
real-device acceptance; those have a separate test suite.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMMON = r'''
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const fsSync = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {ClassicLevel} = require('classic-level');
const core = require(process.env.OFFLINE_CAPTURE_CORE);
const integrity = require(process.env.OFFLINE_CAPTURE_INTEGRITY);
const STATE = 'marichevy_state_v10';
const PENDING = 'marichevy_pending_v10';
const SESSION = 'marichevy_session_v10';
const SECRET = 'SYNTHETIC_AUTH_TOKEN_NEVER_CAPTURE_8c1551';
const FOREIGN = 'SYNTHETIC_OTHER_ORIGIN_NEVER_CAPTURE_928ab3';
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const codeUnits = text => Array.from({length:text.length}, (_, i) => text.charCodeAt(i));
const enc = (text, format = 1) => Buffer.concat([Buffer.from([format]),
  Buffer.from(text, format === 1 ? 'latin1' : 'utf16le')]);
const key = (text, origin = core.ORIGIN, format = 1) => Buffer.concat([
  Buffer.from('_' + origin + '\0'), enc(text, format)]);
let stage = 'setup', root, sourceDir, outputDir, guardDepth = 0;
let factoryCalls = 0, validationCalls = 0, closeCalls = 0, events = [], fetched = [];
const successfulProofs = new Map();

async function filesAt(dir) {
  const result = {};
  async function walk(current, prefix) {
    for (const entry of (await fs.readdir(current, {withFileTypes:true})).sort((a,b) => a.name.localeCompare(b.name))) {
      const filename = path.join(current, entry.name), relative = prefix + entry.name;
      if (entry.isSymbolicLink()) result[relative] = 'symlink:' + await fs.readlink(filename);
      else if (entry.isDirectory()) await walk(filename, relative + '/');
      else result[relative] = sha(await fs.readFile(filename));
    }
  }
  await walk(dir, '');
  return result;
}

async function seed(entries = [[key(STATE), enc('{"entries":[],"synthetic":true}')]], compact = false) {
  await fs.mkdir(sourceDir, {recursive:true, mode:0o700});
  const database = new ClassicLevel(sourceDir, {keyEncoding:'buffer', valueEncoding:'buffer', compression:true});
  await database.open();
  try {
    await database.batch(entries.map(([k,v]) => ({type:'put', key:k, value:v})), {sync:true});
    if (compact) await database.compactRange(Buffer.from([0]), Buffer.from([255]));
  } finally { await database.close(); }
}

async function guard(dir, callback) {
  assert.equal(path.resolve(dir), path.resolve(sourceDir));
  assert.equal(guardDepth, 0);
  events.push('guard-enter'); guardDepth++;
  try { return await callback(); }
  finally { guardDepth--; events.push('guard-exit'); }
}

async function validateClone(clone) {
  validationCalls++; events.push('validate');
  assert.equal(guardDepth, 0);
  assert.notEqual(path.resolve(clone), path.resolve(sourceDir));
  assert.equal(await fs.readFile(path.join(path.dirname(clone), '.disposable-clone'), 'utf8'), 'closed-browser-file-copy\n');
  const proof = await integrity.validateClone(clone);
  assert.equal(proof.validated, true);
  assert.equal(proof.strictChecksums, true);
  assert.equal(proof.checksumSource, 'external-crc32c-preflight');
  successfulProofs.set(clone, proof);
  return proof;
}

async function openDatabase(clone, options, proof) {
  factoryCalls++; events.push('engine');
  assert.equal(guardDepth, 0);
  assert.equal(successfulProofs.get(clone), proof);
  assert.equal(options.createIfMissing, false);
  assert.equal(options.keyEncoding, 'buffer');
  assert.equal(options.valueEncoding, 'buffer');
  assert.notEqual(path.resolve(clone), path.resolve(sourceDir));
  assert.ok(path.relative(outputDir, clone).startsWith('private-queue-clone-'));
  const database = new ClassicLevel(clone, options);
  const read = database.get.bind(database), close = database.close.bind(database);
  database.get = async function (encoded, opts) {
    const decoded = core.decodeFinancialKey(encoded);
    assert.ok(decoded && core.isFinancialKey(decoded));
    assert.notEqual(decoded, SESSION);
    fetched.push(decoded);
    return read(encoded, opts);
  };
  database.close = async function () { closeCalls++; return close(); };
  return database;
}

function options(overrides = {}) {
  return {sourceDir, outputDir, withSourceLock:guard, openDatabase, validateClone,
    now:() => new Date('2026-01-02T03:04:05.006Z'), ...overrides};
}

async function noOutput() {
  assert.deepEqual(await fs.readdir(outputDir), []);
}

async function failure(overrides = {}, expected = null) {
  let caught;
  try { await core.captureProfile(options(overrides)); }
  catch (error) { caught = error; }
  assert.ok(caught instanceof core.CaptureError);
  assert.match(caught.code, /^[a-z][a-z-]+$/);
  assert.equal(caught.message, caught.code);
  assert.ok(!caught.message.includes(SECRET));
  assert.ok(!caught.message.includes(FOREIGN));
  if (expected) assert.equal(caught.code, expected);
  await noOutput();
  return caught;
}

async function run() {
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'offline-queue-SYNTHETIC-'));
  sourceDir = path.join(root, 'fixture-profile', 'Local Storage', 'leveldb');
  outputDir = path.join(root, 'PRIVATE-output');
  await fs.mkdir(outputDir, {mode:0o700});
  try {
'''
END = r'''
    process.stdout.write(JSON.stringify({ok:true}) + '\n');
  } finally { await fs.rm(root, {recursive:true, force:true}); }
}
run().catch(error => {
  // Even a failed synthetic assertion must not print raw financial values.
  process.stderr.write('synthetic-case-failed stage=' + stage + ' type=' +
    (error?.name || 'Error') + ' code=' + (error?.code || 'none') + '\n');
  process.exitCode = 1;
});
'''


@unittest.skipUnless(sys.platform.startswith('linux'), 'Synthetic host integration is Linux-only; Windows FFI has separate tests')
class OfflineQueueSyntheticCapture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')
        if not cls.node:
            raise unittest.SkipTest('Node is required for synthetic offline capture tests')
        cls.env = os.environ.copy()
        modules = cls.env.get('OFFLINE_QUEUE_NODE_MODULES', '/tmp/v95-offline-work/node_modules')
        cls.env['NODE_PATH'] = modules + (os.pathsep + cls.env['NODE_PATH'] if cls.env.get('NODE_PATH') else '')
        cls.env['OFFLINE_CAPTURE_CORE'] = str(ROOT / 'tools/offline_queue/capture.cjs')
        cls.env['OFFLINE_CAPTURE_INTEGRITY'] = str(ROOT / 'tools/offline_queue/integrity.cjs')
        probe = subprocess.run([cls.node, '-e',
            'if(require("classic-level/package.json").version!=="3.0.0")process.exit(2);require("snappyjs")'],
            env=cls.env, capture_output=True, timeout=10)
        if probe.returncode:
            raise unittest.SkipTest('Pinned classic-level 3.0.0 and snappyjs helper dependencies are required')

    def run_case(self, body, timeout=60):
        result = subprocess.run([self.node, '-e', COMMON + body + END], env=self.env,
                                capture_output=True, text=True, timeout=timeout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(json.loads(result.stdout), {'ok': True})

    def test_actual_chromium_closed_profile_exact_raw_without_sessions(self):
        # The browser/profile is newly created and entirely fictional. Every
        # page request is fulfilled locally: no live bank/owner session is used.
        import tempfile
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory(prefix='offline-queue-CHROMIUM-SYNTHETIC-') as profile:
            raw = '{ "entries":[], "note":"Учебный профиль 😀", "exact":9007199254740993 }\n'
            conflict = '{broken: "не изменять"}\ud800'
            requests = []
            with sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(
                    profile, executable_path='/usr/bin/chromium', headless=True,
                    args=['--disable-background-networking', '--disable-component-update'])
                def fulfill(route):
                    requests.append(route.request.url)
                    route.fulfill(status=200, content_type='text/html', body='<!doctype html><title>Synthetic storage fixture</title>')
                context.route('**/*', fulfill)
                page = context.pages[0]
                page.goto('https://finance.marichev.pro/')
                page.evaluate("""([raw,conflict])=>{
                    localStorage.setItem('marichevy_state_v10',raw);
                    localStorage.setItem('marichevy_state_v10_cloud_conflict_v1',conflict);
                    localStorage.setItem('marichevy_pending_v10','OLD-DELETED');
                    localStorage.removeItem('marichevy_pending_v10');
                    localStorage.setItem('marichevy_session_v10','SYNTHETIC_CHROMIUM_SESSION_MUST_NOT_EXPORT');
                }""", [raw,conflict])
                page.goto('https://other.example.invalid/')
                page.evaluate("localStorage.setItem('marichevy_state_v10','SYNTHETIC_FOREIGN_MUST_NOT_EXPORT')")
                context.close()
            self.assertEqual(len(requests), 2)
            source = Path(profile) / 'Default' / 'Local Storage' / 'leveldb'
            self.assertTrue((source / 'CURRENT').is_file())
            self.run_case("""
    stage='actual-chromium-fixture';
    sourceDir=""" + json.dumps(str(source)) + r""";
    const before=await filesAt(sourceDir);
    const capture=await core.captureProfile(options());
    const text=await fs.readFile(capture.output_path,'utf8');
    const value=JSON.parse(text), records=new Map(value.records.map(item=>[item.key,item.raw]));
    assert.equal(records.size,2);
    assert.equal(records.get(STATE),""" + json.dumps(raw) + r""");
    assert.equal(records.get(STATE+'_cloud_conflict_v1'),""" + json.dumps(conflict) + r""");
    assert(!text.includes('SYNTHETIC_CHROMIUM_SESSION'));
    assert(!text.includes('SYNTHETIC_FOREIGN'));
    assert(!text.includes('OLD-DELETED'));
    assert.deepEqual(await filesAt(sourceDir),before);
    assert.equal(validationCalls,1);assert.equal(factoryCalls,1);
    """)

    def test_real_leveldb_exact_raw_encodings_privacy_and_source_unchanged(self):
        self.run_case(r'''
    stage = 'raw-fixture';
    const raw = new Map([
      [STATE, '{ "entries":[{"amount":1250.50,"kopecks":125050,"unknown":90071992547409931234567890.0001}], "literal":"keep whitespace" }\r\n'],
      [PENDING, '[\r\n {"amount":0.01,"unknownLiteral":123456789012345678901234567890}\r\n]'],
      [STATE + '_corrupt_v1', '\ufeff{broken\u0000raw café ÿ'],
      ['marichevy_state_backup_v44', 'UTF16: чай 😀 lone-high:\ud800 lone-low:\udfff end'],
      [STATE + '_cloud_conflict_v1_archive_synthetic_01', 'archived-conflict untouched raw'],
      [STATE + '_cloud_base_v1', 'Latin1 café ÿ\u00a0preserved'],
    ]);
    for (const name of core.FINANCIAL_KEYS) if (!raw.has(name)) raw.set(name, 'synthetic preserved:' + name);
    const entries = [...raw].map(([name,value], i) => [key(name, core.ORIGIN, i % 2), enc(value, i === 2 || i === 3 ? 0 : 1)]);
    entries.push([key(SESSION), enc(SECRET)]);
    entries.push([key('nonfinancial-setting'), Buffer.from([255, 1, 2, 3])]);
    entries.push([key(STATE, 'https://other.example.invalid'), enc(FOREIGN)]);
    entries.push([key(STATE, core.ORIGIN + '.example.invalid'), enc(FOREIGN)]);
    entries.push([Buffer.from('META:' + core.ORIGIN), enc(FOREIGN)]);
    await seed(entries);
    const before = await filesAt(sourceDir);
    stage = 'raw-capture';
    const result = await core.captureProfile(options());
    assert.equal(result.outcome, 'captured');
    assert.deepEqual(await filesAt(sourceDir), before);
    assert.deepEqual(events, ['guard-enter','guard-exit','validate','engine']);
    assert.equal(validationCalls, 1); assert.equal(factoryCalls, 1); assert.equal(closeCalls, 1);
    const text = await fs.readFile(result.output_path, 'utf8'), capture = JSON.parse(text);
    assert.ok(!text.includes(SECRET)); assert.ok(!text.includes(FOREIGN));
    assert.equal(capture.session_included, false); assert.equal(capture.storage_modified, false);
    assert.equal(capture.memory_state_included, false); assert.equal(capture.device_clock_verified, false);
    assert.equal(capture.origin, core.ORIGIN);
    assert.equal(capture.capture_method, 'closed-browser-file-copy');
    assert.equal(capture.key_count, raw.size);
    assert.deepEqual(fetched.sort(), [...raw.keys()].sort());
    for (const record of capture.records) {
      const expected = raw.get(record.key);
      assert.deepEqual(codeUnits(record.raw), codeUnits(expected));
      assert.equal(record.utf16_code_units, expected.length);
      assert.equal(record.utf8_bytes, Buffer.byteLength(expected, 'utf8'));
      assert.equal(record.sha256_utf8, sha(Buffer.from(expected, 'utf8')));
      assert.equal(record.sha256_utf16le, sha(Buffer.from(expected, 'utf16le')));
    }
    assert.equal((await fs.stat(result.output_path)).mode & 0o777, 0o600);
    assert.equal((await fs.stat(outputDir)).mode & 0o777, 0o700);
    assert.deepEqual(await fs.readdir(outputDir), [path.basename(result.output_path)]);
''')

    def test_native_tombstones_compaction_and_old_orphans_never_resurrect(self):
        self.run_case(r'''
    stage = 'tombstone-fixture';
    await fs.mkdir(sourceDir, {recursive:true, mode:0o700});
    const database = new ClassicLevel(sourceDir, {keyEncoding:'buffer', valueEncoding:'buffer'});
    await database.open();
    await database.put(key(STATE), enc('old-state'), {sync:true});
    await database.put(key('marichevy_state_backup_v44'), enc('DELETED_FINANCIAL_VALUE_MUST_NOT_RETURN'), {sync:true});
    const logs = (await fs.readdir(sourceDir)).filter(name => /^\d+\.log$/.test(name));
    const oldLogs = await Promise.all(logs.map(async name => [name, await fs.readFile(path.join(sourceDir,name))]));
    await database.compactRange(Buffer.from([0]), Buffer.from([255]));
    const oldTables = (await fs.readdir(sourceDir)).filter(name => /\.(ldb|sst)$/.test(name));
    assert.ok(oldTables.length > 0);
    const orphanTable = await fs.readFile(path.join(sourceDir, oldTables[0]));
    await database.del(key('marichevy_state_backup_v44'), {sync:true});
    await database.put(key(STATE), enc('latest-state-kopecks:125050'), {sync:true});
    await database.compactRange(Buffer.from([0]), Buffer.from([255]));
    await database.close();
    await fs.writeFile(path.join(sourceDir,'999999.ldb'), orphanTable);
    for (const [name,bytes] of oldLogs) {
      try { await fs.writeFile(path.join(sourceDir,name),bytes,{flag:'wx'}); }
      catch (error) { if (error.code !== 'EEXIST') throw error; }
    }
    const before = await filesAt(sourceDir);
    stage = 'tombstone-capture';
    const result = await core.captureProfile(options());
    const capture = JSON.parse(await fs.readFile(result.output_path,'utf8'));
    assert.deepEqual(capture.records.map(item => [item.key,item.raw]), [[STATE,'latest-state-kopecks:125050']]);
    assert.deepEqual(await filesAt(sourceDir),before);
    assert.equal(factoryCalls,1); assert.equal(closeCalls,1);
''')

    def test_active_wal_corruption_is_rejected_before_native_factory(self):
        self.run_case(r'''
    stage = 'wal-fixture';
    await seed();
    const candidates = (await fs.readdir(sourceDir)).filter(name => /^\d+\.log$/.test(name));
    let target;
    for (const name of candidates) if ((await fs.stat(path.join(sourceDir,name))).size > 7) target = name;
    assert.ok(target);
    const filename = path.join(sourceDir,target), bytes = await fs.readFile(filename);
    bytes[0] ^= 1; await fs.writeFile(filename,bytes);
    const before = await filesAt(sourceDir);
    stage = 'wal-rejection';
    await failure({}, 'integrity-validation-failed');
    assert.equal(validationCalls,1); assert.equal(factoryCalls,0); assert.equal(closeCalls,0);
    assert.deepEqual(await filesAt(sourceDir),before);
''')

    def test_active_sst_corruption_is_rejected_before_native_factory(self):
        self.run_case(r'''
    stage = 'table-fixture';
    await seed([[key(STATE),enc('synthetic compressed table '.repeat(20000))]], true);
    const tables = (await fs.readdir(sourceDir)).filter(name => /\.(ldb|sst)$/.test(name));
    assert.ok(tables.length > 0);
    const filename = path.join(sourceDir,tables[0]), bytes = await fs.readFile(filename);
    assert.ok(bytes.length > 64); bytes[8] ^= 1; await fs.writeFile(filename,bytes);
    const before = await filesAt(sourceDir);
    stage = 'table-rejection';
    await failure({}, 'integrity-validation-failed');
    assert.equal(validationCalls,1); assert.equal(factoryCalls,0);
    assert.deepEqual(await filesAt(sourceDir),before);
''')

    def test_every_run_requires_external_validation_before_engine(self):
        self.run_case(r'''
    stage = 'proof-fixture'; await seed();
    openDatabase.strictChecksums = true; // Ignored legacy flag cannot authorize an engine.
    await failure({validateClone:undefined}, 'engine-checksums-unverified');
    await failure({validateClone:async () => ({strictChecksums:true})}, 'engine-checksums-unverified');
    assert.equal(factoryCalls,0);
    stage = 'proof-per-run';
    const before = await filesAt(sourceDir);
    for (let i=0;i<2;i++) {
      const result = await core.captureProfile(options());
      await fs.unlink(result.output_path);
    }
    assert.equal(validationCalls,2); assert.equal(factoryCalls,2); assert.equal(closeCalls,2);
    assert.deepEqual(await filesAt(sourceDir),before); await noOutput();
''')

    def test_lock_sqlite_symlink_and_untrusted_guard_fail_without_output(self):
        self.run_case(r'''
    stage = 'guard-fixture'; await seed();
    const before = await filesAt(sourceDir);
    await failure({withSourceLock:async () => { const e = new Error(SECRET); e.code='source-lock-unavailable'; throw e; }}, 'source-lock-unavailable');
    await failure({withSourceLock:async () => {}}, 'source-guard-failed');
    await failure({withSourceLock:async (_dir,callback) => {await callback(); await callback();}}, 'source-guard-failed');
    assert.equal(factoryCalls,0); assert.equal(validationCalls,0);
    for (const name of ['LocalStorage','LocalStorage-wal']) {
      const sqlite = path.join(root,'fixture-profile',name); await fs.writeFile(sqlite,'synthetic sqlite marker');
      await failure({},'unsupported-sqlite-storage'); await fs.unlink(sqlite);
    }
    stage = 'symlink-source';
    const current = path.join(sourceDir,'CURRENT'), saved = await fs.readFile(current);
    const target = path.join(root,'synthetic-current'); await fs.writeFile(target,saved);
    await fs.unlink(current); await fs.symlink(target,current);
    await failure({},'source-unsafe');
    assert.equal(factoryCalls,0); assert.equal(validationCalls,0);
    await fs.unlink(current); await fs.writeFile(current,saved);
    assert.deepEqual(await filesAt(sourceDir),before);
''')

    def test_current_mutation_during_copy_is_detected_before_validation(self):
        self.run_case(r'''
    stage = 'mutation-fixture'; await seed();
    const nativeOpen = fs.open; let mutated = false;
    fs.open = async function (filename,flags,...rest) {
      const handle = await nativeOpen(filename,flags,...rest);
      if (filename === path.join(sourceDir,'CURRENT') && typeof flags === 'number') {
        const nativeRead = handle.read.bind(handle);
        handle.read = async (...args) => {
          const result = await nativeRead(...args);
          if (!mutated && result.bytesRead) {
            mutated = true;
            await fs.writeFile(path.join(sourceDir,'CURRENT'),'MANIFEST-999999\n');
          }
          return result;
        };
      }
      return handle;
    };
    stage = 'mutation-rejection';
    try { await failure({},'source-changed'); }
    finally { fs.open = nativeOpen; }
    assert.equal(mutated,true); assert.equal(factoryCalls,0); assert.equal(validationCalls,0);
''')

    def test_capture_limit_applies_to_single_value_and_aggregate_json(self):
        self.run_case(r'''
    stage = 'oversize-value';
    await seed([[key(STATE),enc('x'.repeat(32*1024*1024+1))]]);
    const before = await filesAt(sourceDir);
    await failure({},'capture-size-limit');
    assert.equal(factoryCalls,1); assert.equal(closeCalls,1);
    assert.deepEqual(await filesAt(sourceDir),before);
    await fs.rm(sourceDir,{recursive:true,force:true});
    stage = 'oversize-aggregate';
    await seed([[key(STATE),enc('a'.repeat(17*1024*1024))],
                [key(PENDING),enc('b'.repeat(17*1024*1024))]]);
    const aggregateBefore = await filesAt(sourceDir);
    await failure({},'capture-size-limit');
    assert.equal(factoryCalls,2); assert.equal(closeCalls,2);
    assert.deepEqual(await filesAt(sourceDir),aggregateBefore);
''', timeout=120)

    def test_bad_encoding_duplicate_keys_and_engine_failure_close_clone_and_redact(self):
        self.run_case(r'''
    stage = 'invalid-value'; await seed([[key(STATE),Buffer.from([255,1,2])]]);
    await failure({},'invalid-storage-encoding');
    assert.equal(closeCalls,1);
    await fs.rm(sourceDir,{recursive:true,force:true});
    stage = 'odd-utf16-value'; await seed([[key(STATE),Buffer.from([0,65])]]);
    await failure({},'invalid-storage-encoding'); assert.equal(closeCalls,2);
    await fs.rm(sourceDir,{recursive:true,force:true});
    stage = 'duplicate-key';
    await seed([[key(STATE,core.ORIGIN,0),enc('first')],[key(STATE,core.ORIGIN,1),enc('second')]]);
    await failure({},'duplicate-financial-key'); assert.equal(closeCalls,3);
    await fs.rm(sourceDir,{recursive:true,force:true});
    stage = 'session-only'; await seed([[key(SESSION),enc(SECRET)]]);
    await failure({},'no-financial-keys'); assert.equal(closeCalls,4);
    await fs.rm(sourceDir,{recursive:true,force:true}); await seed();
    stage = 'engine-read-error';
    await failure({openDatabase:async (...args) => {
      const database = await openDatabase(...args);
      database.get = async () => { throw new Error(SECRET + ' synthetic financial amount 125050'); };
      return database;
    }},'database-read-failed');
    assert.equal(closeCalls,5);
''')


if __name__ == '__main__':
    unittest.main()

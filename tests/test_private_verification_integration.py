"""Seven real selected files through comparison and an actual PostgreSQL restore.

Only the native Darwin chooser/private-directory creator and platform identity
are substituted. The worker's root-directory UID is normalized to Darwin's
root-owned '/'; selected files, descriptors, copies, hashes and modes are real.
PGlite construction/close are observed while calling the actual implementation;
no fake readback, restored-file copy or engine result is supplied. Every row and
filename is deliberately fictional. Native Mac acceptance is not claimed.
"""
import copy
import csv
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "tools/private_verify/mac-main.cjs"
sys.path.insert(0, str(ROOT / "tools"))
import restore_private_backup as oracle_restore
import verify_private_backup as oracle
import test_private_backup_verifier as fixtures

PROJECT = "kqndxecziamypdjpxhyq"
MARKER = "FICTIONAL_INTEGRATION_FILE_HISTORY_MUST_NOT_APPEAR"
EXACT = "123456789012345678901234567890.123456789"

RUNNER = r"""
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs/promises');
const syncFs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const Module=require('node:module'),originalLoad=Module._load;
const input=JSON.parse(syncFs.readFileSync(0,'utf8'));
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const observations={created:0,closed:false,callbacks:0,networkAttempts:0,closureObserved:[]};
global.fetch=()=>{observations.networkAttempts++;throw new Error('fictional-network-not-allowed');};
// Observe the real engine, without modifying SQL or returned data.
Module._load=function(name,parent,isMain){
  const actual=Reflect.apply(originalLoad,this,[name,parent,isMain]);
  if(name==='./pglite/index.cjs')return {PGlite:{create:async(...args)=>{
    observations.created++;
    const database=await actual.PGlite.create(...args);
    const close=database.close.bind(database);
    database.close=async()=>{await close();assert.equal(database.closed,true);
      observations.closed=true;};
    return database;
  }}};
  return actual;
};
const api=require(process.argv[1]),core=require(path.join(path.dirname(process.argv[1]),'core.cjs'));
const decoder=require(path.join(path.dirname(process.argv[1]),'owner-export.cjs'));
const adapter=require(path.join(path.dirname(process.argv[1]),'local-restore.cjs'));
let choice=0,created,restoreCalls=0;const lines=[];
function rootStat(stat){return {...stat,uid:0n,isFile:()=>stat.isFile(),
  isDirectory:()=>stat.isDirectory(),isSymbolicLink:()=>stat.isSymbolicLink()};}
const io={...fs,async lstat(filename,options){const stat=await fs.lstat(filename,options);
  return filename==='/'?rootStat(stat):stat;}};
const workflow=api._createWorkflowForTests({fs:io,platform:'darwin',arch:'arm64',
  uid:()=>process.getuid(),euid:()=>process.geteuid(),log:line=>lines.push(line),
  execFile:async(executable,args,options)=>{
    assert.equal(executable,'/usr/bin/osascript');assert.equal(args[0],'-e');assert.equal(args[2],'--');
    assert.equal(options.encoding,'utf8');
    if(choice===0){choice++;assert.equal(args[1],api._scriptsForTests.attest);
      return {stdout:'scope-confirmed\n',stderr:''};}
    assert.equal(args[1],api._scriptsForTests.choose);
    assert.equal(args[3],api.INPUT_SLOTS[choice-1].prompt);
    const filename=input.files[choice++-1];assert.equal(typeof filename,'string');
    return {stdout:filename+'\n',stderr:''};
  },
  load:filename=>{
    if(filename.endsWith('/app/macos.cjs'))return {async createPrivateDirectory(parent,prefix){
      assert.equal(parent,input.oldRoot);assert.equal(prefix,'PRIVATE-verification-');
      created=await fs.mkdtemp(path.join(parent,prefix));await fs.chmod(created,0o700);return created;
    }};
    return require(filename);
  }});
function stable(stat){return [stat.dev,stat.ino,stat.mode,stat.uid,stat.gid,stat.nlink,
  stat.size,stat.mtimeNs,stat.ctimeNs].map(value=>value.toString()).join(':');}
(async()=>{
  const originals=await Promise.all(input.files.map(async filename=>({
    bytes:await fs.readFile(filename),identity:stable(await fs.stat(filename,{bigint:true}))})));
  const result=await workflow.main({oldBundleRoot:input.oldRoot,addonRoot:path.dirname(process.argv[1]),
    restore:async options=>{
      restoreCalls++;assert.equal(options.project,api.FIXED_PROJECT);
      const source=decoder.decodeOwnerExport(originals[0].bytes);
      assert.equal(options.backupJson,source.backupJson);
      assert(core.equal(options.server,core.parse(source.backupJson)));
      return adapter.restore({...options,writePrivateArtifact:async(name,bytes)=>{
        // The actual engine must have been closed before the first output.
        assert.equal(observations.closed,true);observations.callbacks++;
        observations.closureObserved.push(name);
        await options.writePrivateArtifact(name,bytes);
        assert.equal(hash(await fs.readFile(path.join(created,name))),hash(bytes));
      }});
    }});
  assert.equal(choice,8);assert.equal(restoreCalls,1);
  assert.equal(observations.created,1);assert.equal(observations.closed,true);
  assert.equal(observations.callbacks,2);assert.equal(observations.networkAttempts,0);
  assert.deepEqual(observations.closureObserved,
    ['server-restored-PRIVATE.json','server-restore-receipt-PRIVATE.json']);
  assert.equal(result,input.mode==='matching'?0:2);
  const expectedIssues=input.mode==='matching'?[]:
    input.mode==='unknown-field'?['device-export-diverges','divergent-active-values']:
    input.mode==='pending'?['pending-acknowledgement-required']:['conflict-packets'];
  const outcome=input.mode==='matching'?'passed':'review_required';
  const report=JSON.parse(await fs.readFile(path.join(created,'verification-report.json'),'utf8'));
  assert.equal(report.outcome,outcome);assert.deepEqual(report.issues,expectedIssues);
  assert.equal(report.restore_execution_verified,true);assert.equal(report.release_authorized,false);
  assert.deepEqual(report.restore,{outcome:'passed',restore_execution_verified:true});
  assert.equal(report.source_files.length,7);
  assert.equal(report.counts.devices,3);
  const expectedNames=[];
  for(let index=0;index<input.files.length;index++){
    const current=await fs.readFile(input.files[index]);
    assert.equal(hash(current),hash(originals[index].bytes));
    assert.equal(stable(await fs.stat(input.files[index],{bigint:true})),originals[index].identity);
    const name=api.INPUT_SLOTS[index].slot+(index===0?'.bin':'.json');expectedNames.push(name);
    const copied=await fs.readFile(path.join(created,name));
    assert.equal(hash(copied),hash(current));
    assert.equal(report.source_files[index].sha256,hash(current));
    assert.equal(report.source_files[index].bytes,current.length);
  }
  expectedNames.push('server-restored-PRIVATE.json','server-restore-receipt-PRIVATE.json','verification-report.json');
  assert.deepEqual((await fs.readdir(created)).sort(),expectedNames.sort());
  assert.equal((await fs.stat(created)).mode&0o777,0o700);
  for(const name of expectedNames)assert.equal((await fs.stat(path.join(created,name))).mode&0o777,0o600);
  const source=decoder.decodeOwnerExport(originals[0].bytes),sourceWrapper=core.parse(source.backupJson);
  const restoredBytes=await fs.readFile(path.join(created,'server-restored-PRIVATE.json'));
  const restored=core.parse(restoredBytes),receipt=JSON.parse(await fs.readFile(path.join(created,'server-restore-receipt-PRIVATE.json'),'utf8'));
  const sourceTables=core.snapshot(sourceWrapper,api.FIXED_PROJECT,sourceWrapper.configured_household).tables;
  const restoredTables=core.snapshot(restored,api.FIXED_PROJECT,sourceWrapper.configured_household).tables;
  for(const table of ['households','household_members','family_state','family_chore_deliveries']){
    assert.equal(sourceTables[table].length,restoredTables[table].length);
    assert(core.equal(sourceTables[table],restoredTables[table]));
  }
  assert.equal(receipt.source_file_sha256,hash(Buffer.from(source.backupJson,'utf8')));
  assert.equal(receipt.source_digest_scope,'decoded-backup-json-utf8');
  assert.equal(receipt.source_snapshot_json_sha256,sourceWrapper.snapshot_json_sha256);
  assert.equal(receipt.readback_file_sha256,hash(restoredBytes));
  assert.equal(restored.source_backup_sha256,receipt.source_file_sha256);
  // The original downloaded CSV and decoded wrapper have intentionally distinct
  // hashes, linked by the actual decoder result, not a copied source readback.
  assert.notEqual(report.source_files[0].sha256,receipt.source_file_sha256);
  assert.equal(receipt.restore_execution_verified,true);assert.equal(receipt.release_authorized,false);
  for(const flag of ['four_table_roundtrip_verified','local_clone_rls_verified',
    'migration_rehearsal_preserved_original_columns','migration_rehearsal_local_cas_verified',
    'foreign_keys_and_not_null_restored','minimal_auth_user_stubs_only'])assert.equal(receipt[flag],true);
  for(const flag of ['network_used','production_changed','original_files_modified',
    'supabase_auth_restored','supabase_platform_restored','release_authorized'])assert.equal(receipt[flag],false);
  assert.deepEqual(lines,[
    'Этап: загрузка системного модуля',
    'Этап: выбор семи копий',
    'Этап: проверка выбранных файлов',
    'Этап: сравнение копий',
    'Этап: локальная проверка восстановления',
    'Результат: '+outcome,
    'Коды: '+(expectedIssues.length?expectedIssues.join(', '):'none'),
    'Частные копии и отчёт сохранены в новой папке PRIVATE-verification-… рядом с помощником.',
    'В чат сообщи только результат и коды.']);
  for(const text of [input.marker,input.oldRoot,sourceWrapper.configured_household,
    sourceWrapper.snapshot_json_sha256,receipt.source_file_sha256,
    ...input.files,...sourceTables.household_members.map(row=>row.user_id)])
    assert(!lines.join('\n').includes(text));
  // Only fixed success metadata leaves this test process. Artifacts and counts
  // stay in the synthetic private directory for independent Python inspection.
  process.stdout.write(JSON.stringify({outcome:'passed',case:input.mode,native_mac_tested:false}));
})().catch(()=>{process.stderr.write('fictional-integration-check-failed\n');process.exitCode=1;});
"""


class PrivateVerificationIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("Node is required")

    def fixture(self, root, mode):
        old = root / "old-helper"
        old.mkdir(mode=0o700)
        selected = root / "selected"
        selected.mkdir(mode=0o700)
        state = fixtures.state()
        state["futureExact"] = "FICTIONAL_EXACT_NUMBER_LITERAL"
        state["futureText"] = "\\.\nDROP TABLE public.households CASCADE; -- ' ; \\\t"
        state["settings"]["__proto__"] = {"retained": True, "marker": MARKER}
        state["settings"]["hasOwnProperty"] = [False, None, MARKER]
        state_raw = json.dumps(state, ensure_ascii=True).replace('"FICTIONAL_EXACT_NUMBER_LITERAL"', EXACT)
        tables = fixtures.tables(state)
        tables["family_chore_deliveries"][0]["telegram_message_id"] = 9007199254740993
        for rows in tables.values():
            for row in rows:
                for name in ("created_at", "updated_at", "last_attempt_at", "sent_at"):
                    if isinstance(row.get(name), str) and row[name].endswith("Z"):
                        row[name] = row[name][:-1] + "+00:00"
        snapshot_raw = json.dumps(tables, ensure_ascii=True).replace('"FICTIONAL_EXACT_NUMBER_LITERAL"', EXACT)
        wrapper = {"format":"marichevy-private-server-backup-v1", "project_ref":PROJECT,
            "configured_household":fixtures.HOUSE, "configured_household_count":1,
            "database_timezone":"UTC", "database_role":"postgres", "database_name":"fictional",
            "transaction_read_only":"off", "export_method":"sql-editor-select-v1", "read_only":True,
            "captured_at_utc":"2026-10-27T00:00:00.000000Z", "query_sha256":"0"*64,
            "snapshot_json":snapshot_raw, "snapshot_json_sha256":hashlib.sha256(snapshot_raw.encode()).hexdigest()}
        wrapper_raw = json.dumps(wrapper, ensure_ascii=True, indent=2) + "\n"
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(["backup_json"])
        writer.writerow([wrapper_raw])
        raw_capture = fixtures.captured({oracle.STATE:state_raw})
        values = [b"\xef\xbb\xbf" + stream.getvalue().encode(), state_raw.encode(),
                  json.dumps(raw_capture).encode(), state_raw.encode(), json.dumps(raw_capture).encode(),
                  state_raw.encode(), json.dumps(raw_capture).encode()]
        if mode == "unknown-field":
            # Only one unknown field differs; no financial totals changed.
            changed = state_raw.replace('"futureExact":', '"unknownDeviceOnly":{"keep":true},"futureExact":', 1)
            values[5] = changed.encode()
        if mode == "pending":
            values[6] = json.dumps(fixtures.captured({oracle.STATE:state_raw, oracle.PENDING:state_raw})).encode()
        if mode == "conflict":
            packet = json.dumps({"household":fixtures.HOUSE,"local":{"future":MARKER},"cloud":{"future":"other"}})
            values[4] = json.dumps(fixtures.captured({oracle.STATE:state_raw, oracle.CONFLICT:packet})).encode()
        files = []
        for index, content in enumerate(values):
            filename = selected / f"{MARKER}-{index}.{'csv' if index == 0 else 'json'}"
            filename.write_bytes(content)
            filename.chmod(0o600)
            files.append(filename)
        return old, files, values, wrapper_raw

    def run_case(self, mode):
        with tempfile.TemporaryDirectory(prefix=".fictional-integration-", dir=ROOT) as temporary:
            root = Path(temporary)
            old, files, originals, wrapper_raw = self.fixture(root, mode)
            payload = {"mode":mode,"oldRoot":str(old),"files":[str(path) for path in files],"marker":MARKER}
            env = os.environ.copy()
            env.pop("NODE_OPTIONS", None)
            env.pop("NODE_PATH", None)
            result = subprocess.run([self.node,"--no-global-search-paths","--max-old-space-size=512", "-e",RUNNER,str(ENTRY)],
                input=json.dumps(payload), text=True, capture_output=True, env=env, cwd=ROOT, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            self.assertEqual(json.loads(result.stdout), {"outcome":"passed","case":mode,"native_mac_tested":False})
            for private in (MARKER, fixtures.MARKER, fixtures.HOUSE, fixtures.USER, str(root)):
                self.assertNotIn(private, result.stdout + result.stderr)
            output = list(old.iterdir())
            self.assertEqual(len(output), 1)
            folder = output[0]
            self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
            for filename, original in zip(files, originals):
                self.assertEqual(filename.read_bytes(), original)
            # An independent Decimal-based oracle checks every restored table,
            # unknown nested field and number, not the Node report's flags alone.
            source = oracle.parse(wrapper_raw.encode())
            restored = oracle.parse((folder / "server-restored-PRIVATE.json").read_bytes())
            source_tables, _, _ = oracle.snapshot(source, PROJECT, fixtures.HOUSE)
            restored_tables, restored_state, _ = oracle.snapshot(restored, PROJECT, fixtures.HOUSE)
            self.assertTrue(oracle_restore.compare_rows(source_tables, restored_tables))
            self.assertEqual(restored_state["futureExact"], Decimal(EXACT))
            self.assertEqual(restored_tables["family_chore_deliveries"][0]["telegram_message_id"], Decimal(9007199254740993))
            self.assertEqual(restored_state["settings"]["__proto__"], {"retained":True,"marker":MARKER})
            self.assertEqual(restored_state["settings"]["hasOwnProperty"], [False,None,MARKER])
            receipt = json.loads((folder / "server-restore-receipt-PRIVATE.json").read_bytes())
            self.assertEqual(receipt["source_file_sha256"], hashlib.sha256(wrapper_raw.encode()).hexdigest())
            report = json.loads((folder / "verification-report.json").read_bytes())
            self.assertTrue(report["restore_execution_verified"])
            self.assertFalse(report["release_authorized"])
            if mode == "pending":
                self.assertEqual(report["counts"]["pending_values"], 1)
                self.assertEqual(report["counts"]["divergent_active_values"], 0)
            if mode == "conflict":
                self.assertEqual(report["counts"]["conflict_packets"], 1)

    def test_actual_csv_seven_file_workflow_restores_same_four_tables_after_close(self):
        self.run_case("matching")

    def test_unknown_device_field_remains_review_despite_actual_restore_success(self):
        self.run_case("unknown-field")

    def test_matching_pending_still_requires_acknowledgement_after_actual_restore(self):
        self.run_case("pending")

    def test_preserved_conflict_packet_still_requires_review_after_actual_restore(self):
        self.run_case("conflict")


if __name__ == "__main__":
    unittest.main()

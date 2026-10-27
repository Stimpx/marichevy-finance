"""Real offline PostgreSQL WASM restore; every row in this suite is fictional."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import restore_private_backup as oracle_restore
import verify_private_backup as oracle
import test_private_backup_verifier as fixtures

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tools/private_verify/local-restore.cjs"
NODE = r"""
'use strict';
const fs=require('node:fs'),Module=require('node:module');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const load=Module._load;let closed=false,created=0,networkAttempts=0,artifactBeforeClose=false;
const records=[];
global.fetch=()=>{networkAttempts++;throw new Error('FIXTURE_NETWORK_CALL_MUST_NOT_RUN')};
Module._load=function(name,parent,isMain){
 const value=load.apply(this,arguments);
 if(name==='./pglite/index.cjs'){
  if(input.networkDuringLoad)global.fetch('https://fictional.invalid');
  return {PGlite:{create:async(...args)=>{
   created++;const db=await value.PGlite.create(...args),close=db.close.bind(db),query=db.query.bind(db);
   db.close=async()=>{await close();closed=true;if(input.failClose)throw new Error('FICTIONAL_PRIVATE_CLOSE_DETAIL')};
   if(input.alterReadback)db.query=async(sql,params,options)=>{
    const result=await query(sql,params,options);
    if(sql.includes('AS snapshot_for_test'))return result;
    if(result.rows.length===1&&typeof result.rows[0].jsonb_build_object==='string')
     result.rows[0].jsonb_build_object=result.rows[0].jsonb_build_object.replace('PRIVATE_HISTORY_MUST_NOT_APPEAR','FICTIONAL_TAMPERED_READBACK');
    return result;
   };
   return db;
  }}};
 }
 return value;
};
const core=require(input.core),adapter=require(input.module);
(async()=>{
 const options={backupJson:input.backupJson,server:core.parse(input.backupJson),
  project:input.project,household:input.household,
  writePrivateArtifact:async(name,bytes)=>{
   if(!closed)artifactBeforeClose=true;
   if(input.failArtifact)throw new Error('FICTIONAL_PRIVATE_FILE_DETAIL');
   records.push({name,base64:Buffer.from(bytes).toString('base64')});
  }};
 if(input.serverMismatch)options.server.read_only=false;
 if(input.noWriter)delete options.writePrivateArtifact;
 try{
  const result=await adapter.restore(options);
  console.log(JSON.stringify({result,records,closed,created,networkAttempts,artifactBeforeClose,
    publicApi:Object.keys(adapter)}));
 }catch(error){console.log(JSON.stringify({error:{name:error.name,code:error.code,message:error.message},
  records,closed,created,networkAttempts,artifactBeforeClose}));}
})().catch(()=>{console.log(JSON.stringify({fatal:'fixture-driver-failed'}));process.exitCode=1});
"""


def wrapper(tables=None, timezone="UTC"):
    tables = copy.deepcopy(tables or fixtures.tables(fixtures.state()))
    offset = "+03:00" if timezone == "Europe/Moscow" else "+00:00"
    for rows in tables.values():
        for row in rows:
            for name in ("created_at", "updated_at", "last_attempt_at", "sent_at"):
                if isinstance(row.get(name), str) and row[name].endswith("Z"):
                    row[name] = row[name][:-1] + offset
    raw = json.dumps(tables, ensure_ascii=True)
    value = fixtures.snapshot(fixtures.state())
    value.update(snapshot_json=raw, snapshot_json_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                 database_timezone=timezone)
    return value


class PrivateLocalRestore(unittest.TestCase):
    def test_trusted_sql_sources_are_exact_reviewed_restore_and_migrations(self):
        source = json.loads((MODULE.parent / "sql-sources.json").read_text())
        for name in ("SCHEMA", "BOOTSTRAP_SQL", "INSERT_SQL", "READBACK_SQL"):
            self.assertEqual(source[name], getattr(oracle_restore, name))
        for name in ("001_family_state_cas.sql", "002_restrict_table_capabilities.sql", "003_bound_membership_lookup.sql"):
            self.assertEqual(source[name], (ROOT / "server" / name).read_text())

    def run_adapter(self, value=None, *, backup_json=None, module=MODULE, **flags):
        value = value or wrapper()
        payload = {"module": str(module), "core": str(module.parent / "core.cjs"),
                   "backupJson": backup_json if backup_json is not None else json.dumps(value),
                   "project": fixtures.PROJECT, "household": fixtures.HOUSE, **flags}
        completed = subprocess.run(["node", "--max-old-space-size=512", "-e", NODE],
                                   input=json.dumps(payload), text=True, capture_output=True,
                                   timeout=90, cwd=ROOT)
        self.assertEqual(completed.returncode, 0, completed.stderr[-1000:])
        self.assertFalse(completed.stderr.strip(), "engine must not leak raw diagnostics")
        self.assertEqual(len(completed.stdout.splitlines()), 1)
        return json.loads(completed.stdout)

    def decoded_artifacts(self, result):
        import base64
        return {item["name"]: base64.b64decode(item["base64"]) for item in result["records"]}

    def assert_fixed_failure(self, result, code, *, engine_created=None):
        self.assertEqual(result["error"], {"name": "LocalRestoreError", "code": code, "message": code})
        self.assertEqual(result["records"], [])
        if engine_created is not None:
            self.assertEqual(result["created"], engine_created)
        serialized = json.dumps(result)
        for text in (fixtures.MARKER, fixtures.USER, fixtures.HOUSE, "FICTIONAL_PRIVATE"):
            self.assertNotIn(text, serialized)

    def test_real_four_table_restore_exact_unknown_numbers_hashes_and_closed_artifacts(self):
        value = wrapper()
        tables = json.loads(value["snapshot_json"])
        tables["family_state"][0]["data"]["futureExact"] = "EXACT_NUMBER_PLACEHOLDER"
        tables["family_state"][0]["data"]["settings"]["__proto__"] = {"keep": True}
        raw = json.dumps(tables).replace('"EXACT_NUMBER_PLACEHOLDER"', '123456789012345678901234567890.123456789')
        value.update(snapshot_json=raw, snapshot_json_sha256=hashlib.sha256(raw.encode()).hexdigest())
        source_text = json.dumps(value)
        result = self.run_adapter(value, backup_json=source_text)
        self.assertEqual(result["result"]["outcome"], "passed")
        self.assertTrue(result["result"]["restore_execution_verified"])
        self.assertFalse(result["result"]["release_authorized"])
        self.assertTrue(result["closed"])
        self.assertFalse(result["artifactBeforeClose"])
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["networkAttempts"], 0)
        self.assertEqual(result["publicApi"], ["restore", "LocalRestoreError", "MAX_FILE"])
        artifacts = self.decoded_artifacts(result)
        self.assertEqual(set(artifacts), {"server-restored-PRIVATE.json", "server-restore-receipt-PRIVATE.json"})
        restored = oracle.parse(artifacts["server-restored-PRIVATE.json"])
        self.assertTrue(oracle_restore.compare_rows(oracle.parse(raw), oracle.parse(restored["snapshot_json"])))
        receipt = json.loads(artifacts["server-restore-receipt-PRIVATE.json"])
        self.assertEqual(receipt["source_file_sha256"], hashlib.sha256(source_text.encode()).hexdigest())
        self.assertEqual(receipt["readback_file_sha256"], hashlib.sha256(artifacts["server-restored-PRIVATE.json"]).hexdigest())
        for flag in ("four_table_roundtrip_verified", "local_clone_rls_verified", "migration_rehearsal_preserved_original_columns",
                     "migration_rehearsal_local_cas_verified", "minimal_auth_user_stubs_only"):
            self.assertTrue(receipt[flag])
        for flag in ("network_used", "production_changed", "original_files_modified", "supabase_auth_restored",
                     "supabase_platform_restored", "source_unknown_delivery_checks_reproduced", "release_authorized"):
            self.assertFalse(receipt[flag])
        for private in (fixtures.HOUSE, fixtures.USER, fixtures.MARKER, receipt["source_file_sha256"]):
            self.assertNotIn(private, json.dumps(result["result"]))

    def test_non_utc_timestamps_sql_metacharacters_and_large_delivery_integer(self):
        tables = fixtures.tables(fixtures.state())
        tables["family_state"][0]["data"]["futureText"] = "\\.\nDROP TABLE public.households CASCADE; -- ' ; \\\t"
        tables["family_chore_deliveries"][0]["telegram_message_id"] = 9007199254740993
        value = wrapper(tables, "Europe/Moscow")
        result = self.run_adapter(value)
        self.assertEqual(result["result"]["outcome"], "passed")
        artifact = self.decoded_artifacts(result)["server-restored-PRIVATE.json"]
        restored = oracle.parse(artifact)
        self.assertEqual(restored["database_timezone"], "Europe/Moscow")
        self.assertTrue(oracle_restore.compare_rows(oracle.parse(value["snapshot_json"]), oracle.parse(restored["snapshot_json"])))

    def test_physical_restore_preserves_existing_review_issue_without_authorizing_release(self):
        tables = fixtures.tables(fixtures.state())
        tables["family_state"][0]["data"]["entries"][0]["amount"] = "12.345"
        result = self.run_adapter(wrapper(tables))
        self.assertEqual(result["result"]["outcome"], "passed")
        self.assertFalse(result["result"]["release_authorized"])
        receipt = json.loads(self.decoded_artifacts(result)["server-restore-receipt-PRIVATE.json"])
        self.assertEqual(receipt["outcome_scope"], "four-app-table-restore-only")
        self.assertEqual(receipt["source_digest_scope"], "decoded-backup-json-utf8")
        self.assertTrue(receipt["app_data_review_required"])
        self.assertGreater(receipt["app_health_counts"]["invalid_cent_values"], 0)

    def test_independent_readback_tampering_cannot_pass(self):
        result = self.run_adapter(alterReadback=True)
        self.assert_fixed_failure(result, "local-restore-rows-differ", engine_created=1)
        self.assertTrue(result["closed"])

    def test_unknown_outer_columns_wrong_types_scope_and_bad_hash_refuse_before_engine(self):
        cases = []
        for mutate, code in ((lambda t: t["households"][0].update(extra=1), "local-restore-unknown-columns"),
                             (lambda t: t["family_chore_deliveries"][0].update(attempts="1"), "local-restore-invalid-column-type"),
                             (lambda t: t["family_state"][0].update(household_id=fixtures.OTHER), "local-restore-invalid-input")):
            tables = fixtures.tables(fixtures.state()); mutate(tables); cases.append((wrapper(tables), code))
        bad_hash = wrapper(); bad_hash["snapshot_json"] += " "; cases.append((bad_hash, "local-restore-invalid-input"))
        bad_timezone = wrapper(); bad_timezone["database_timezone"] = "UTC';DROP TABLE x;--"; cases.append((bad_timezone, "local-restore-timezone-invalid"))
        for value, code in cases:
            with self.subTest(code=code):
                self.assert_fixed_failure(self.run_adapter(value), code, engine_created=0)

    def test_duplicate_nested_json_keys_and_source_mismatch_refuse_before_engine(self):
        value = wrapper(); raw = value["snapshot_json"].replace('"settings": {', '"settings": {"duplicate":1,"duplicate":2,', 1)
        value.update(snapshot_json=raw, snapshot_json_sha256=hashlib.sha256(raw.encode()).hexdigest())
        self.assert_fixed_failure(self.run_adapter(value), "local-restore-invalid-input", engine_created=0)
        self.assert_fixed_failure(self.run_adapter(serverMismatch=True), "local-restore-source-mismatch", engine_created=0)

    def test_missing_artifact_writer_and_numeric_expansion_limit_refuse_before_engine(self):
        self.assert_fixed_failure(self.run_adapter(noWriter=True), "local-restore-invalid-input", engine_created=0)
        value = wrapper(); raw = value["snapshot_json"].replace('"futureCollection":', '"futureHuge":1e1000,"futureCollection":', 1)
        value.update(snapshot_json=raw, snapshot_json_sha256=hashlib.sha256(raw.encode()).hexdigest())
        self.assert_fixed_failure(self.run_adapter(value), "local-restore-resource-limit", engine_created=0)

    def test_engine_network_attempt_is_blocked_and_no_artifacts_saved(self):
        result = self.run_adapter(networkDuringLoad=True)
        self.assert_fixed_failure(result, "local-restore-network-forbidden", engine_created=0)
        self.assertEqual(result["networkAttempts"], 0, "outer fetch must never be called")

    def test_close_and_artifact_failures_never_claim_success_or_leak(self):
        result = self.run_adapter(failClose=True)
        self.assert_fixed_failure(result, "local-restore-close-failed", engine_created=1)
        result = self.run_adapter(failArtifact=True)
        self.assert_fixed_failure(result, "local-restore-artifact-failed", engine_created=1)
        self.assertTrue(result["closed"])

    def test_asset_tampering_refuses_before_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for name in ("local-restore.cjs", "core.cjs", "sql-sources.json"):
                shutil.copyfile(MODULE.parent / name, folder / name)
            shutil.copytree(MODULE.parent / "pglite", folder / "pglite")
            with (folder / "pglite/index.cjs").open("ab") as stream:
                stream.write(b"\nthrow new Error('FICTIONAL_UNTRUSTED_CODE');\n")
            self.assert_fixed_failure(self.run_adapter(module=folder / "local-restore.cjs"), "local-restore-asset-integrity", engine_created=0)


if __name__ == "__main__":
    unittest.main()

"""Offline PG semantics; explicit template1 fixture derivative, production guard intact.

The pinned PGlite backend fixes current_database() to template1. The unmodified
production artifact must refuse it. Remaining cases change ONLY that one expected
database literal for the fictional engine, never the checked production file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = r"""
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const crypto=require('node:crypto'),request=JSON.parse(fs.readFileSync(0,'utf8'));
const root=process.argv[1],assets=path.join(root,'tools/private_verify');
globalThis.fetch=()=>{throw Error('NETWORK_FORBIDDEN')};
const {PGlite}=require(path.join(assets,'pglite/index.cjs'));
const sources=JSON.parse(fs.readFileSync(path.join(assets,'sql-sources.json'),'utf8'));
const HOUSE='11111111-1111-4111-8111-111111111111';
const OTHER='22222222-2222-4222-8222-222222222222';
const USER='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const raw='{"number":9007199254740993,"fraction":12.340000000000001,"unknown":{"preserve":[false,null,"FICTIONAL_PRIVATE_DATA"]}}';
const digest=s=>crypto.createHash('sha256').update(s,'utf8').digest('hex');
(async()=>{
 let db;
 try{
  db=await PGlite.create('memory://',{debug:0,initialMemory:256*1024*1024,
   wasmModule:await WebAssembly.compile(fs.readFileSync(path.join(assets,'pglite/pglite.wasm'))),
   fsBundle:new Blob([fs.readFileSync(path.join(assets,'pglite/pglite.data'))])});
  await db.exec(sources.BOOTSTRAP_SQL);
  await db.query('INSERT INTO auth.users(id) VALUES($1::uuid)',[USER]);
  await db.query("INSERT INTO public.households VALUES($1::uuid,'Fictional','2000-01-01Z')",[HOUSE]);
  await db.query("INSERT INTO public.household_members VALUES($1::uuid,$2::uuid,'owner','2000-01-01Z')",[HOUSE,USER]);
  await db.query("INSERT INTO public.family_state VALUES($1::uuid,$2::jsonb,'2001-02-03T04:05:06.123456Z',$3::uuid)",[HOUSE,raw,USER]);
  if(request.change)await db.exec(request.change);
  const original=fs.readFileSync(path.join(root,'preview/server-before-update-backup-v95.sql'),'utf8');
  const guard="pg_catalog.current_database() = 'postgres'";
  assert.equal(original.split(guard).length,2);
  const sql=request.exact ? original : original.replace(guard,"pg_catalog.current_database() = 'template1'");
  const state=async()=>{
   const rows=(await db.query("SELECT (SELECT jsonb_agg(to_jsonb(f))::text FROM public.family_state f) AS rows, (SELECT jsonb_agg(jsonb_build_array(attname,atttypid,attnotnull))::text FROM pg_attribute WHERE attrelid='public.family_state'::regclass AND attnum>0 AND NOT attisdropped) AS columns, (SELECT count(*)::text FROM pg_trigger WHERE tgrelid='public.family_state'::regclass) AS triggers")).rows;
   return digest(JSON.stringify(rows));
  };
  const before=await state();let output,errorCode=null;
  try{output=await db.query(sql);}catch(error){errorCode=error.code;}
  assert.equal(await state(),before);
  if(request.reject){
   assert.equal(errorCode,'22012');
   process.stdout.write(JSON.stringify({outcome:'passed',atomic_refusal:true,unchanged:true}));return;
  }
  assert.equal(errorCode,null);assert.equal(output.rows.length,1);
  assert.deepEqual(Object.keys(output.rows[0]),['backup_json']);
  const wrapper=JSON.parse(output.rows[0].backup_json);
  const old=JSON.parse((await db.query(fs.readFileSync(path.join(assets,'owner-export.sql'),'utf8'))).rows[0].backup_json);
  assert.equal(wrapper.snapshot_json,old.snapshot_json);
  assert.equal(wrapper.snapshot_json_sha256,digest(wrapper.snapshot_json));
  assert.equal(wrapper.snapshot_json_sha256,old.snapshot_json_sha256);
  assert.equal(wrapper.format,'marichevy-private-server-backup-v1');
  assert.equal(wrapper.read_only,true);assert.equal(wrapper.database_name,'template1');
  assert.equal(wrapper.database_role,'postgres');assert.equal(wrapper.configured_household,HOUSE);
  assert.equal(wrapper.configured_household_count,1);
  const plan=wrapper.activation_checkpoint;
  assert.deepEqual(Object.keys(plan).sort(),['activation_sql_sha256','expected_data_sha256','expected_database','expected_revision','format','household_id']);
  assert.equal(plan.format,'marichevy-sync-activation-plan-v1');
  assert.equal(plan.activation_sql_sha256,digest(fs.readFileSync(path.join(root,'server/activate_household_api.sql'),'utf8')));
  assert.equal(plan.expected_database,'template1');assert.equal(plan.household_id,HOUSE);
  assert.equal(plan.expected_revision,0);
  const data=(await db.query('SELECT data::text AS raw FROM public.family_state')).rows[0].raw;
  assert.equal(plan.expected_data_sha256,digest(data));
  assert(wrapper.snapshot_json.includes('9007199254740993'));
  assert(wrapper.snapshot_json.includes('12.340000000000001'));
  assert(wrapper.snapshot_json.includes('FICTIONAL_PRIVATE_DATA'));
  assert.equal(await state(),before);
  process.stdout.write(JSON.stringify({outcome:'passed',same_snapshot:true,postgres_hash:true,numeric_precision_preserved:true,unchanged:true,production_changed:false,fixture_database_guard_only:true}));
 }finally{if(db){await db.close();assert.equal(db.closed,true);}}
})().catch(()=>{process.stderr.write('fictional-checkpoint-test-failed\n');process.exitCode=1;});
"""


class OwnerActivationCheckpointSql(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("Node is required for real offline PostgreSQL")

    def run_engine(self, *, change="", reject=False, exact=False):
        environment = os.environ.copy()
        environment.pop("NODE_OPTIONS", None)
        environment.pop("NODE_PATH", None)
        result = subprocess.run(
            [self.node, "--no-global-search-paths", "-e", DRIVER, str(ROOT)],
            input=json.dumps({"change": change, "reject": reject, "exact": exact}),
            capture_output=True, text=True, timeout=60, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("FICTIONAL_PRIVATE_DATA", result.stdout)
        output = json.loads(result.stdout)
        self.assertEqual(output["outcome"], "passed")
        self.assertTrue(output["unchanged"])
        return output

    def test_original_snapshot_exact_and_pg_hash_preserves_opaque_numeric_precision(self):
        result = self.run_engine()
        self.assertTrue(result["same_snapshot"])
        self.assertTrue(result["postgres_hash"])
        self.assertTrue(result["numeric_precision_preserved"])
        self.assertFalse(result["production_changed"])
        self.assertTrue(result["fixture_database_guard_only"])

    def test_unmodified_production_guard_refuses_pglite_template1_database(self):
        self.assertTrue(self.run_engine(exact=True, reject=True)["atomic_refusal"])

    def test_extra_missing_or_changed_original_columns_refuse_without_mutation(self):
        for change in (
            "ALTER TABLE public.family_state ADD COLUMN sync_revision bigint NOT NULL DEFAULT 0;",
            "ALTER TABLE public.family_state DROP COLUMN updated_by;",
            "ALTER TABLE public.family_state ALTER COLUMN updated_at DROP NOT NULL;",
        ):
            with self.subTest(change=change):
                self.assertTrue(self.run_engine(change=change, reject=True)["atomic_refusal"])

    def test_preexisting_cas_guard_or_user_trigger_refuse_without_mutation(self):
        for change in (
            "CREATE FUNCTION public.family_state_cas() RETURNS integer LANGUAGE sql AS $$SELECT 1$$;",
            "CREATE FUNCTION public.family_state_sync_guard() RETURNS integer LANGUAGE sql AS $$SELECT 1$$;",
            "CREATE FUNCTION public.fixture_trigger() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RETURN NEW; END$$; CREATE TRIGGER fixture BEFORE UPDATE ON public.family_state FOR EACH ROW EXECUTE FUNCTION public.fixture_trigger();",
        ):
            with self.subTest(change=change):
                self.assertTrue(self.run_engine(change=change, reject=True)["atomic_refusal"])

    def test_missing_rls_wrong_owner_and_wrong_primary_key_refuse_without_mutation(self):
        for change in (
            "ALTER TABLE public.family_state DISABLE ROW LEVEL SECURITY;",
            "ALTER TABLE public.family_state OWNER TO authenticated;",
            "ALTER TABLE public.family_state DROP CONSTRAINT family_state_pkey; ALTER TABLE public.family_state ADD PRIMARY KEY(household_id,updated_at);",
        ):
            with self.subTest(change=change):
                self.assertTrue(self.run_engine(change=change, reject=True)["atomic_refusal"])

    def test_ambiguous_household_scope_refuses_without_mutation(self):
        change = "INSERT INTO public.households VALUES('22222222-2222-4222-8222-222222222222','Other fictional','2000-01-01Z');"
        self.assertTrue(self.run_engine(change=change, reject=True)["atomic_refusal"])


if __name__ == "__main__":
    unittest.main()

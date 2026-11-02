"""Offline PG pause semantics with a fictional pg_cron stand-in.

PGlite has no native pg_cron C extension and fixes its database to template1.
The exact production SQL must refuse that database. Other cases change only
the one database guard literal in a test copy and model cron.alter_job in SQL.
This proves transactional guards and receipts, not native extension acceptance.
Restricted-role cases additionally adapt the one current_user guard literal to
a fictional SELECT-only operator. A SECURITY DEFINER SQL stand-in models the
native C function's internal write boundary; it does not claim the real C
function is declared SECURITY DEFINER (the production catalog says it is not).
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
const digest=s=>crypto.createHash('sha256').update(s,'utf8').digest('hex');
const marker='FICTIONAL_CREDENTIAL_MUST_NOT_APPEAR';
(async()=>{
 let db;
 try{
  db=await PGlite.create('memory://',{debug:0,initialMemory:256*1024*1024,
   wasmModule:await WebAssembly.compile(fs.readFileSync(path.join(assets,'pglite/pglite.wasm'))),
   fsBundle:new Blob([fs.readFileSync(path.join(assets,'pglite/pglite.data'))])});
  await db.exec(`CREATE SCHEMA cron; CREATE SCHEMA net;
   CREATE TABLE cron.job(jobid bigint PRIMARY KEY,schedule text,command text,nodename text,
    nodeport integer,database text,username text,active boolean,jobname text);
   ALTER TABLE cron.job ENABLE ROW LEVEL SECURITY;
   CREATE TABLE cron.job_run_details(jobid bigint,end_time timestamptz);
   ALTER TABLE cron.job_run_details ENABLE ROW LEVEL SECURITY;
   CREATE TABLE net.http_request_queue(id bigint,url text);
   CREATE TABLE public.fictional_history(id integer PRIMARY KEY,data jsonb);
   INSERT INTO public.fictional_history VALUES(1,'{"large":9007199254740993,"amount":12.3400001}');`);
  const command="SELECT net.http_post(url := 'https://kqndxecziamypdjpxhyq.supabase.co/functions/v1/family-reminders', headers := '{\"Authorization\":\""+marker+"\"}'::jsonb);";
  await db.query("INSERT INTO cron.job VALUES(1,'* * * * *',$1,'localhost',5432,current_database(),'postgres',true,'fictional-reminders')",[command]);
  let mutation='UPDATE cron.job SET active=COALESCE($6,cron.job.active) WHERE jobid=$1;';
  if(request.mode==='noop')mutation='PERFORM 1;';
  if(request.mode==='tamper')mutation="UPDATE cron.job SET active=$6,schedule='0 0 * * *' WHERE jobid=$1;";
  await db.exec(`CREATE FUNCTION cron.alter_job(job_id bigint,schedule text DEFAULT NULL,
   command text DEFAULT NULL,database text DEFAULT NULL,username text DEFAULT NULL,
   active boolean DEFAULT NULL) RETURNS void LANGUAGE plpgsql AS $mock$ BEGIN ${mutation} END $mock$;`);
  if(request.restricted){
   await db.exec(`CREATE ROLE fixture_cron_owner NOLOGIN NOSUPERUSER;
    CREATE ROLE fixture_operator NOLOGIN NOSUPERUSER NOINHERIT BYPASSRLS;
    ALTER SCHEMA cron OWNER TO fixture_cron_owner;
    ALTER SCHEMA net OWNER TO fixture_cron_owner;
    ALTER TABLE cron.job OWNER TO fixture_cron_owner;
    ALTER TABLE cron.job_run_details OWNER TO fixture_cron_owner;
    ALTER TABLE net.http_request_queue OWNER TO fixture_cron_owner;
    ALTER FUNCTION cron.alter_job(bigint,text,text,text,text,boolean) OWNER TO fixture_cron_owner;
    ALTER FUNCTION cron.alter_job(bigint,text,text,text,text,boolean) SECURITY DEFINER;
    ALTER FUNCTION cron.alter_job(bigint,text,text,text,text,boolean) SET search_path=pg_catalog,cron;
    REVOKE ALL ON cron.job,cron.job_run_details,net.http_request_queue FROM PUBLIC,fixture_operator;
    GRANT USAGE ON SCHEMA cron,net TO fixture_operator;
    GRANT SELECT ON cron.job,cron.job_run_details,net.http_request_queue,public.fictional_history TO fixture_operator;
    REVOKE ALL ON FUNCTION cron.alter_job(bigint,text,text,text,text,boolean) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION cron.alter_job(bigint,text,text,text,text,boolean) TO fixture_operator;
    UPDATE cron.job SET username='fixture_operator';`);
  }
  let savedHash=null;
  if(request.resume){
   await db.exec('UPDATE cron.job SET active=false;');
   savedHash=(await db.query("SELECT encode(sha256(convert_to((to_jsonb(j)-'active')::text,'UTF8')),'hex') AS hash FROM cron.job j WHERE jobid=1")).rows[0].hash;
  }
  if(request.change)await db.exec(request.change);
  const original=fs.readFileSync(path.join(root,request.resume?'preview/resume-family-reminders-v95.sql':'preview/pause-family-reminders-v95.sql'),'utf8');
  const guard="current_database() <> 'postgres'";
  assert.equal(original.split(guard).length,2);
  let sql=request.exact?original:original.replace(guard,"current_database() <> 'template1'");
  if(request.restricted){
   const roleGuard="current_user <> 'postgres'";
   assert.equal(sql.split(roleGuard).length,2);
   sql=sql.replace(roleGuard,"current_user <> 'fixture_operator'");
   await db.exec('SET ROLE fixture_operator;');
   assert.equal((await db.query("SELECT current_user AS actor,rolsuper AS superuser FROM pg_roles WHERE rolname=current_user")).rows[0].superuser,false);
   const access=async()=> (await db.query("SELECT has_table_privilege('cron.job','SELECT') AS read,has_table_privilege('cron.job','UPDATE') AS write,has_function_privilege('cron.alter_job(bigint,text,text,text,text,boolean)','EXECUTE') AS execute,row_security_active('cron.job') AS filtered")).rows[0];
   const permissions=await access();
   assert.deepEqual(permissions,{read:true,write:false,execute:true,filtered:false});
   assert.equal((await db.query('SELECT count(*)::text AS n FROM cron.job')).rows[0].n,'1');
   for(const denied of ['SELECT * FROM cron.job WHERE jobid=1 FOR UPDATE','UPDATE cron.job SET active=active WHERE jobid=1']){
    let code=null;try{await db.query(denied);}catch(error){code=error.code;}assert.equal(code,'42501');
   }
   request.permissions=permissions;
  }
  if(request.resume&&!request.unfilled){
   assert.equal(sql.split('REPLACE_WITH_SAVED_RESUME_CONFIG_SHA256').length,2);
   sql=sql.replace('REPLACE_WITH_SAVED_RESUME_CONFIG_SHA256',savedHash);
  }
  const read=async()=>({jobs:(await db.query("SELECT to_jsonb(j)::text AS raw FROM cron.job j ORDER BY jobid")).rows,
   history:(await db.query("SELECT data::text AS raw FROM public.fictional_history ORDER BY id")).rows});
  // A caller's failed prior transaction is cleared by the SQL under test.
  // Read the independent before-state first, before constructing that failure.
  const before=await read();
  if(request.aborted){await db.exec('BEGIN;');try{await db.query('SELECT * FROM cron.job WHERE jobid=1 FOR UPDATE');}catch(error){assert.equal(error.code,'42501');}}
  let results,error=null;
  try{results=await db.exec(sql);}catch(e){error=e;await db.exec('ROLLBACK');}
  const after=await read();
  if(request.restricted){
   const actualPermissions=(await db.query("SELECT has_table_privilege('cron.job','SELECT') AS read,has_table_privilege('cron.job','UPDATE') AS write,has_function_privilege('cron.alter_job(bigint,text,text,text,text,boolean)','EXECUTE') AS execute,row_security_active('cron.job') AS filtered")).rows[0];
   assert.deepEqual(actualPermissions,request.permissions);
   let code=null;try{await db.query('UPDATE cron.job SET active=active WHERE jobid=1');}catch(error){code=error.code;}assert.equal(code,'42501');
  }
  if(request.reject){
   assert(error);assert.equal(error.code,'P0001');
   assert.equal(error.message,request.reject);
   assert.deepEqual(after,before);
   process.stdout.write(JSON.stringify({outcome:'passed',atomic_refusal:true,history_unchanged:true}));return;
  }
  assert.equal(error,null);
  assert.equal(results[results.length-1].rows.length,1);
  const receipt=results[results.length-1].rows[0];
  assert.equal(String(receipt.jobid),'1');assert.equal(receipt.active,!!request.resume);
  if(!request.resume){
   assert.equal(receipt.runs_unfiltered,true);assert.equal(String(receipt.runs_unfinished),'0');
   assert.equal(String(receipt.queued_reminder_requests),request.queued?'1':'0');
  }
  const old=JSON.parse(before.jobs[0].raw),next=JSON.parse(after.jobs[0].raw);
  assert.equal(old.active,!request.resume);assert.equal(next.active,!!request.resume);
  delete old.active;delete next.active;assert.deepEqual(next,old);
  assert.deepEqual(after.history,before.history);
  const actual=(await db.query("SELECT encode(sha256(convert_to((to_jsonb(j)-'active')::text,'UTF8')),'hex') AS hash FROM cron.job j WHERE jobid=1")).rows[0].hash;
  if(request.resume)assert.equal(savedHash,actual);
  else assert.equal(receipt.resume_config_sha256,actual);
  assert(!JSON.stringify(receipt).includes(marker));
  process.stdout.write(JSON.stringify({outcome:'passed',only_active_changed:true,last_result_receipt:true,
   history_unchanged:true,configuration_anchor_verified:true,production_changed:false,native_pg_cron_tested:false}));
 }finally{if(db){await db.close();assert.equal(db.closed,true);}}
})().catch(()=>{process.stderr.write('fictional-cron-pause-test-failed\n');process.exitCode=1;});
"""


class CronCutoverPause(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("Node is required for offline PostgreSQL")

    def run_engine(self, **request):
        environment = os.environ.copy()
        environment.pop("NODE_OPTIONS", None)
        environment.pop("NODE_PATH", None)
        result = subprocess.run(
            [self.node, "--no-global-search-paths", "-e", DRIVER, str(ROOT)],
            input=json.dumps(request), capture_output=True, text=True,
            timeout=60, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("FICTIONAL_CREDENTIAL", result.stdout)
        output = json.loads(result.stdout)
        self.assertEqual(output["outcome"], "passed")
        self.assertTrue(output["history_unchanged"])
        return output

    def test_pause_only_active_and_final_receipt_binds_config(self):
        result = self.run_engine()
        self.assertTrue(result["only_active_changed"])
        self.assertTrue(result["last_result_receipt"])
        self.assertTrue(result["configuration_anchor_verified"])
        self.assertFalse(result["production_changed"])
        self.assertFalse(result["native_pg_cron_tested"])

    def test_exact_artifact_refuses_engine_database(self):
        self.run_engine(exact=True, reject="cutover-cron-identity-mismatch")

    def test_wrong_job_target_inactive_and_scope_refuse_atomically(self):
        for change in (
            "UPDATE cron.job SET jobid=2;",
            "UPDATE cron.job SET command='SELECT 1';",
            "UPDATE cron.job SET active=false;",
            "INSERT INTO cron.job SELECT 2,schedule,command,nodename,nodeport,database,username,active,'other' FROM cron.job;",
            "UPDATE cron.job SET database='other';",
        ):
            with self.subTest(change=change):
                self.run_engine(change=change, reject="cutover-cron-job-mismatch")

    def test_alter_job_noop_and_config_tampering_roll_back(self):
        for mode in ("noop", "tamper"):
            with self.subTest(mode=mode):
                self.run_engine(mode=mode, reject="cutover-cron-pause-unverified")

    def test_queued_http_requests_are_visible_in_receipt(self):
        self.run_engine(queued=True, change="INSERT INTO net.http_request_queue VALUES(1,'https://kqndxecziamypdjpxhyq.supabase.co/functions/v1/family-reminders?fictional=1');")

    def test_resume_saved_config_anchor_changes_only_active(self):
        result = self.run_engine(resume=True)
        self.assertTrue(result["only_active_changed"])
        self.assertTrue(result["last_result_receipt"])
        self.assertTrue(result["configuration_anchor_verified"])

    def test_resume_changed_config_refuses_saved_anchor_atomically(self):
        self.run_engine(resume=True, change="UPDATE cron.job SET command=command || ' ';",
                        reject="cutover-cron-resume-mismatch")

    def test_resume_unfilled_template_refuses(self):
        self.run_engine(resume=True, unfilled=True,
                        reject="cutover-cron-identity-or-receipt-mismatch")

    def test_select_only_operator_pauses_without_granting_update_or_row_lock(self):
        result = self.run_engine(restricted=True, aborted=True)
        self.assertTrue(result["only_active_changed"])

    def test_select_only_operator_resumes_saved_config_without_granting_update(self):
        result = self.run_engine(restricted=True, resume=True)
        self.assertTrue(result["only_active_changed"])

    def test_select_only_operator_tampering_rolls_back_without_acl_change(self):
        self.run_engine(restricted=True, mode="tamper",
                        reject="cutover-cron-pause-unverified")


if __name__ == "__main__":
    unittest.main()

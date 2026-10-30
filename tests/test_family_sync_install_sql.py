"""Exact migration sequence and final grid on fictional offline PostgreSQL."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    '001_family_state_cas.sql': 'a97333d25d903cd013e53973bd5756602756aa0c127effb46814a685e948a7c8',
    '002_restrict_table_capabilities.sql': '2dcc99d29923fae4627201c923327a5ccb07fbd205abf144b8e121e6424d8fb7',
    '003_bound_membership_lookup.sql': '34ee3b3fcae3e5e5b7c7672d17bda3d332d9dea04031e459a493d7ed058e7ea3',
}
DRIVER = r"""
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=process.argv[1],assets=path.join(root,'tools/private_verify');
globalThis.fetch=()=>{throw Error('NETWORK_FORBIDDEN')};
const {PGlite}=require(path.join(assets,'pglite/index.cjs'));
const source=JSON.parse(fs.readFileSync(path.join(assets,'sql-sources.json'),'utf8'));
(async()=>{
 let db;
 try{
  db=await PGlite.create('memory://',{debug:0,initialMemory:256*1024*1024,
    wasmModule:await WebAssembly.compile(fs.readFileSync(path.join(assets,'pglite/pglite.wasm'))),
    fsBundle:new Blob([fs.readFileSync(path.join(assets,'pglite/pglite.data'))])});
  await db.exec(source.BOOTSTRAP_SQL);
  const house='11111111-1111-4111-8111-111111111111',user='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  await db.query('INSERT INTO auth.users(id) VALUES($1::uuid)',[user]);
  await db.query("INSERT INTO public.households VALUES($1::uuid,'Fictional','2000-01-01Z')",[house]);
  await db.query("INSERT INTO public.household_members VALUES($1::uuid,$2::uuid,'owner','2000-01-01Z')",[house,user]);
  await db.query("INSERT INTO public.family_state VALUES($1::uuid,$2::jsonb,'2001-02-03T04:05:06.123456Z',$3::uuid)",
    [house,'{"unknown":{"keep":9007199254740993,"amount":12.340000000000001,"private":"FICTIONAL_ONLY"}}',user]);
  await db.query("INSERT INTO public.family_chore_deliveries(household_id,chore_id,due_date,chat_id,status,attempts,created_at) VALUES($1::uuid,'fictional','2000-01-01','fictional','pending',0,'2000-01-01Z')",[house]);
  const snapshot=async()=>{
   const state=(await db.query("SELECT jsonb_build_object('household_id',household_id,'data',data,'updated_at',updated_at,'updated_by',updated_by)::text AS raw FROM public.family_state ORDER BY household_id")).rows;
   const others=[];
   for(const name of ['households','household_members','family_chore_deliveries'])
    others.push((await db.query('SELECT to_jsonb(t)::text AS raw FROM public.'+name+' t ORDER BY to_jsonb(t)::text')).rows);
   const security=(await db.query("SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,p.polname,pg_get_expr(p.polqual,p.polrelid) AS qual,pg_get_expr(p.polwithcheck,p.polrelid) AS chk,p.polroles::text FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_policy p ON p.polrelid=c.oid WHERE n.nspname='public' AND c.relkind='r' ORDER BY c.relname,p.polname")).rows;
   const roles=(await db.query("SELECT rolname,rolsuper,rolbypassrls,rolinherit,rolcanlogin FROM pg_roles WHERE rolname IN('anon','authenticated','service_role') ORDER BY rolname")).rows;
   return {state,others,security,roles};
  };
  const before=await snapshot();
  const sql=fs.readFileSync(path.join(root,'preview/install-family-sync-v95.sql'),'utf8');
  const results=await db.exec(sql),last=results.at(-1).rows;
  assert.equal(last.length,1);
  assert.deepEqual(Object.keys(last[0]).sort(),['schema_ready','cas_ready','table_permissions_ready','membership_ready','activation_pending','ready'].sort());
  assert(Object.values(last[0]).every(value=>value===true));
  assert.deepEqual(await snapshot(),before);
  assert(before.state[0].raw.includes('9007199254740993'));
  assert(before.state[0].raw.includes('12.340000000000001'));
  const sync=(await db.query('SELECT sync_protocol::text AS protocol,sync_revision::text AS revision,last_request_id FROM public.family_state')).rows;
  assert.deepEqual(sync,[{protocol:'1',revision:'0',last_request_id:null}]);
  // The final check must derive its answer from privileges, not constants.
  const tail=sql.slice(sql.indexOf('-- Actual readiness metadata only;'));
  await db.exec('GRANT TRUNCATE ON public.family_state TO anon;');
  const changed=(await db.query(tail)).rows[0];
  assert.equal(changed.table_permissions_ready,false);assert.equal(changed.ready,false);
  process.stdout.write(JSON.stringify({outcome:'passed',exact_migrations_executed:true,
   full_original_rows_preserved:true,numeric_precision_preserved:true,rls_policies_roles_preserved:true,
   final_actual_readiness:true,protocol_activation_pending:true,production_changed:false}));
 }finally{if(db)await db.close();}
})().catch(()=>{process.stderr.write('fictional-install-test-failed\n');process.exitCode=1;});
"""


class FamilySyncInstallSql(unittest.TestCase):
    def test_exact_pinned_migrations_embedded_once_in_order(self):
        artifact = (ROOT / 'preview/install-family-sync-v95.sql').read_bytes()
        offset = -1
        for name, expected in PINS.items():
            body = (ROOT / 'server' / name).read_bytes()
            self.assertEqual(hashlib.sha256(body).hexdigest(), expected)
            self.assertEqual(artifact.count(body), 1)
            current = artifact.index(body)
            self.assertGreater(current, offset)
            offset = current

    def test_actual_offline_pg_preserves_rows_and_returns_readiness_without_activation(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node required for real offline PostgreSQL')
        environment = os.environ.copy()
        environment.pop('NODE_OPTIONS', None)
        environment.pop('NODE_PATH', None)
        result = subprocess.run([node, '--no-global-search-paths', '-e', DRIVER, str(ROOT)],
                                capture_output=True, text=True, env=environment, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertNotIn('FICTIONAL_ONLY', result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report['outcome'], 'passed')
        self.assertTrue(report['full_original_rows_preserved'])
        self.assertTrue(report['numeric_precision_preserved'])
        self.assertTrue(report['protocol_activation_pending'])
        self.assertFalse(report['production_changed'])


if __name__ == '__main__':
    unittest.main()

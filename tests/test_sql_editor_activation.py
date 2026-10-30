"""Private script preparation and real offline PG17 execution, fictional only."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sql_editor_builder", ROOT / "tools/build_sql_editor_activation.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
HOUSE = "11111111-1111-4111-8111-111111111111"
MARKER = "FICTIONAL_PRIVATE_PARAMETER_MUST_NOT_APPEAR"

DRIVER = r"""
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const crypto=require('node:crypto'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const root=process.argv[1],asset=path.join(root,'tools/private_verify');
globalThis.fetch=()=>{throw Error('NETWORK_FORBIDDEN')};
const {PGlite}=require(path.join(asset,'pglite/index.cjs'));
const sources=JSON.parse(fs.readFileSync(path.join(asset,'sql-sources.json'),'utf8'));
const HOUSE='11111111-1111-4111-8111-111111111111';
const OTHER='22222222-2222-4222-8222-222222222222';
const USER='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const raw='{"entries":[{"id":"fictional","amount":12.3400}],"settings":{"opaque":"FICTIONAL_PRIVATE_PARAMETER_MUST_NOT_APPEAR"},"future":{"keep":[true,null,0.0001]}}';
(async()=>{
 let db;
 try {
  db=await PGlite.create('memory://',{debug:0,initialMemory:256*1024*1024,
    wasmModule:await WebAssembly.compile(fs.readFileSync(path.join(asset,'pglite/pglite.wasm'))),
    fsBundle:new Blob([fs.readFileSync(path.join(asset,'pglite/pglite.data'))])});
  await db.exec(sources.BOOTSTRAP_SQL);
  await db.query("INSERT INTO auth.users(id) VALUES($1::uuid)",[USER]);
  for(const house of [HOUSE,OTHER]){
   await db.query("INSERT INTO public.households VALUES($1::uuid,'Fictional','2000-01-01Z')",[house]);
   await db.query("INSERT INTO public.household_members VALUES($1::uuid,$2::uuid,'owner','2000-01-01Z')",[house,USER]);
   await db.query("INSERT INTO public.family_state VALUES($1::uuid,$2::jsonb,'2001-02-03T04:05:06.123456Z',$3::uuid)",[house,raw,USER]);
  }
  for(const name of ['001_family_state_cas.sql','002_restrict_table_capabilities.sql','003_bound_membership_lookup.sql'])
    await db.exec(fs.readFileSync(path.join(root,'server',name),'utf8'));
  const meta=(await db.query("SELECT current_database() AS database,encode(sha256(convert_to(data::text,'UTF8')),'hex') AS data_hash FROM public.family_state WHERE household_id=$1::uuid",[HOUSE])).rows[0];
  if(input.mode==='describe'){process.stdout.write(JSON.stringify(meta));return;}
  if(input.mode==='literal'){
   const row=(await db.query('SELECT '+input.literal+' AS value')).rows[0];
   assert.equal(row.value,input.expected);
   process.stdout.write(JSON.stringify({literal_roundtrip:true}));return;
  }
  const read=async()=> (await db.query("SELECT household_id::text,data::text AS data,updated_at::text,updated_by::text,sync_revision::text,sync_protocol::text,last_request_id::text FROM public.family_state ORDER BY household_id")).rows;
  const before=await read();let execution,errorCode=null;
  try{execution=await db.exec(input.activation);}catch(error){errorCode=error.code;}
  const after=await read();
  const hash=value=>crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
  const source=rows=>rows.map(({sync_revision,sync_protocol,last_request_id,...row})=>row);
  const pending=(await db.query("SELECT name FROM pg_prepared_statements WHERE name LIKE 'marichevy_activation_%'")).rows;
  if(input.success){
   assert.equal(errorCode,null);
   const final=execution[execution.length-1];
   assert.equal(final.rows.length,1);
   assert.deepEqual(Object.keys(final.rows[0]).sort(),['activation_revision','verified']);
   assert.equal(String(final.rows[0].verified),'1');
   assert.equal(String(final.rows[0].activation_revision),'1');
   assert.equal(hash(source(before)),hash(source(after)));
   assert.equal(pending.length,1);
   const target=after.find(row=>row.household_id===HOUSE),other=after.find(row=>row.household_id===OTHER);
   assert.equal(target.sync_protocol,'2');assert.equal(target.sync_revision,'1');
   assert.equal(target.last_request_id,null);
   assert.equal(other.sync_protocol,'1');assert.equal(other.sync_revision,'0');
  }else{
   assert.equal(errorCode,'22012');
   assert.deepEqual(after,before);
  }
  if(pending.length){await db.exec(input.cleanup);}
  assert.equal((await db.query("SELECT count(*)::text AS n FROM pg_prepared_statements WHERE name LIKE 'marichevy_activation_%'")).rows[0].n,'0');
  process.stdout.write(JSON.stringify({outcome:'passed',case:input.success?'activation-receipt-last':'atomic-refusal',
    receipt_columns_visible:input.success,source_unchanged:true,cleanup_separate:true,production_changed:false}));
 } finally {if(db){await db.close();assert.equal(db.closed,true);}}
})().catch(()=>{process.stderr.write('fictional-sql-editor-test-failed\n');process.exitCode=1;});
"""


class SqlEditorActivation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("Node is required for real PostgreSQL WASM")
        cls.fixture_metadata = cls.run_engine({"mode": "describe"})

    @classmethod
    def run_engine(cls, payload):
        environment = os.environ.copy()
        environment.pop("NODE_OPTIONS", None)
        environment.pop("NODE_PATH", None)
        result = subprocess.run([cls.node, "--no-global-search-paths", "-e", DRIVER, str(ROOT)],
                                input=json.dumps(payload), capture_output=True, text=True,
                                timeout=60, env=environment)
        if result.returncode or result.stderr:
            raise AssertionError("Fictional PostgreSQL execution failed: " + result.stderr[-300:])
        if MARKER in result.stdout:
            raise AssertionError("Fixture data leaked")
        return json.loads(result.stdout)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fictional-sql-editor-")
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.inputs = self.root / "private-inputs"
        self.inputs.mkdir(mode=0o700)
        self.plan_file = self.inputs / "verified-plan.json"
        self.plan = {"format": BUILDER.FORMAT, "activation_sql_sha256": BUILDER.SQL_SHA256,
                     "expected_database": self.fixture_metadata["database"], "household_id": HOUSE,
                     "expected_revision": 0, "expected_data_sha256": self.fixture_metadata["data_hash"]}
        self.write_plan(self.plan)
        self.output = self.root / "prepared"

    def tearDown(self):
        self.temp.cleanup()

    def write_plan(self, value):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.plan_file.write_bytes(raw)
        self.plan_file.chmod(0o600)

    def prepare(self):
        return BUILDER.prepare(plan_path=self.plan_file, output_dir=self.output)

    def assert_failure(self, expected=None):
        with self.assertRaises(BUILDER.PreparationError) as raised:
            self.prepare()
        if expected:
            self.assertEqual(raised.exception.code, expected)
        self.assertNotIn(MARKER, str(raised.exception))

    def scripts(self):
        return {name: (self.output / name).read_text() for name in ("activation.sql", "cleanup.sql")}

    def test_exact_pinned_body_private_modes_receipt_last_and_no_existing_overwrite(self):
        before = self.plan_file.read_bytes()
        result = self.prepare()
        self.assertEqual(result, {"outcome": "prepared-not-executed", "activation_executed": False,
                                 "activation_receipt_created": False, "production_changed": False})
        self.assertEqual(self.plan_file.read_bytes(), before)
        self.assertEqual({p.name for p in self.output.iterdir()}, set(BUILDER.OUTPUT_NAMES))
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
        for file in self.output.iterdir():
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(file.stat().st_nlink, 1)
        scripts = self.scripts()
        self.assertIn((ROOT / "server/activate_household_api.sql").read_text().rstrip(),
                      scripts["activation.sql"])
        self.assertRegex(scripts["activation.sql"].strip().splitlines()[-1],
                         r"^EXECUTE marichevy_activation_[a-f0-9]{24}\(")
        self.assertNotIn("DEALLOCATE", scripts["activation.sql"])
        self.assertRegex(scripts["cleanup.sql"].strip().splitlines()[-1],
                         r"^DEALLOCATE marichevy_activation_[a-f0-9]{24};$")
        manifest = json.loads((self.output / "build-manifest.json").read_text())
        self.assertFalse(manifest["activation_executed"])
        self.assertFalse(manifest["activation_receipt_created"])
        for name, proof in manifest["files"].items():
            contents = (self.output / name).read_bytes()
            self.assertEqual(proof, {"bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()})
        self.assert_failure("activation-private-output-invalid")
        self.assertEqual(self.plan_file.read_bytes(), before)

    def test_plans_reject_duplicates_float_bool_bounds_extra_keys_and_invalid_scope(self):
        cases = [
            json.dumps(self.plan).replace('"expected_revision": 0', '"expected_revision": 0, "expected_revision": 0').encode(),
            json.dumps(self.plan).replace('"expected_revision": 0', '"expected_revision": 0.0').encode(),
            {**self.plan, "expected_revision": True}, {**self.plan, "expected_revision": -1},
            {**self.plan, "expected_revision": 9223372036854775807},
            {**self.plan, "expected_data_sha256": "Z" * 64},
            {**self.plan, "household_id": "00000000-0000-0000-0000-000000000000"},
            {**self.plan, "household_id": HOUSE.upper()}, {**self.plan, "format": "wrong"},
            {**self.plan, "expected_database": "x" * 64},
            {**self.plan, "expected_database": "bad\nname"}, {**self.plan, "expected_database": "bad\0name"},
            {**self.plan, "expected_database": "bad\u0085name"},
            {**self.plan, "expected_database": "bad\u2028name"},
            {**self.plan, "expected_database": "\ud800"},
            {**self.plan, "unexpected": MARKER}, {**self.plan, "activation_sql_sha256": "0" * 64},
        ]
        # HOUSE contains digits only; use an actual letter-bearing UUID for case rejection.
        cases[7] = {**self.plan, "household_id": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"}
        for value in cases:
            with self.subTest(case=cases.index(value)):
                self.write_plan(value)
                self.assert_failure()
                self.assertFalse(self.output.exists())
        self.write_plan(b'{"format":\xff}')
        self.assert_failure("activation-plan-invalid")
        self.write_plan(b" " * (BUILDER.MAX_PLAN + 1))
        self.assert_failure("activation-private-input-invalid")

    def test_private_input_and_output_links_permissions_and_checkout_are_rejected(self):
        self.plan_file.chmod(0o644)
        self.assert_failure("activation-private-input-invalid")
        self.plan_file.chmod(0o600)
        self.inputs.chmod(0o755)
        self.assert_failure("activation-private-input-invalid")
        self.inputs.chmod(0o700)
        sibling = self.inputs / "hardlink.json"
        os.link(self.plan_file, sibling)
        self.assert_failure("activation-private-input-invalid")
        sibling.unlink()
        raw = self.plan_file.read_bytes()
        self.plan_file.unlink()
        self.plan_file.symlink_to(self.inputs / "actual.json")
        (self.inputs / "actual.json").write_bytes(raw)
        (self.inputs / "actual.json").chmod(0o600)
        self.assert_failure("activation-private-input-invalid")
        self.plan_file.unlink()
        self.write_plan(raw)
        alias = self.root / "alias"
        alias.symlink_to(self.inputs, target_is_directory=True)
        with self.assertRaises(BUILDER.PreparationError):
            BUILDER.prepare(plan_path=alias / self.plan_file.name, output_dir=self.output)
        with self.assertRaises(BUILDER.PreparationError):
            BUILDER.prepare(plan_path=ROOT / "never-read-private-plan.json", output_dir=self.output)
        with self.assertRaises(BUILDER.PreparationError):
            BUILDER.prepare(plan_path=self.plan_file, output_dir=ROOT / "never-create-private-output")
        self.output.symlink_to(self.inputs, target_is_directory=True)
        self.assert_failure("activation-private-output-invalid")

    def test_tampered_fixed_sql_is_refused_before_output_creation(self):
        fake_root = self.root / "fixture-repo"
        (fake_root / "server").mkdir(parents=True)
        (fake_root / "server/activate_household_api.sql").write_text(
            (ROOT / "server/activate_household_api.sql").read_text() + "\nSELECT 'tampered';\n")
        with patch.object(BUILDER, "ROOT", fake_root):
            self.assert_failure("activation-sql-artifact-invalid")
        self.assertFalse(self.output.exists())

    def test_random_prepared_names_are_independent_and_cleanup_is_not_global(self):
        self.prepare()
        first = self.scripts()["cleanup.sql"]
        second_dir = self.root / "another-prepared"
        BUILDER.prepare(plan_path=self.plan_file, output_dir=second_dir)
        second = (second_dir / "cleanup.sql").read_text()
        self.assertNotEqual(first, second)
        self.assertNotIn("DEALLOCATE ALL", first + second)

    def test_cli_returns_only_fixed_codes_on_success_invalid_plan_and_bad_arguments(self):
        self.plan["expected_database"] = MARKER
        self.write_plan(self.plan)
        command = ["python", str(ROOT / "tools/build_sql_editor_activation.py"),
                   "--plan", str(self.plan_file), "--output-dir", str(self.output)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "Result: prepared-not-executed\nCodes: none\n")
        self.assertEqual(result.stderr, "")
        self.write_plan({**self.plan, "expected_revision": MARKER})
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "Result: failed\nCodes: activation-plan-invalid\n")
        self.assertEqual(result.stderr, "")
        result = subprocess.run(command + ["--arbitrary-sql", MARKER], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "Result: failed\nCodes: activation-arguments-invalid\n")
        self.assertNotIn(MARKER, result.stdout + result.stderr)

    def test_actual_postgres_last_grid_result_is_activation_receipt_and_cleanup_is_separate(self):
        self.prepare()
        result = self.run_engine({"mode": "apply", **self.scripts(), "activation": self.scripts()["activation.sql"],
                                  "cleanup": self.scripts()["cleanup.sql"], "success": True})
        self.assertEqual(result["case"], "activation-receipt-last")
        self.assertTrue(result["receipt_columns_visible"])
        self.assertTrue(result["source_unchanged"])
        self.assertTrue(result["cleanup_separate"])
        self.assertFalse(result["production_changed"])

    def test_actual_postgres_stale_revision_refuses_without_changing_data_or_metadata(self):
        self.plan["expected_revision"] = 999
        self.write_plan(self.plan)
        self.prepare()
        scripts = self.scripts()
        result = self.run_engine({"mode": "apply", "activation": scripts["activation.sql"],
                                  "cleanup": scripts["cleanup.sql"], "success": False})
        self.assertEqual(result["case"], "atomic-refusal")
        self.assertTrue(result["source_unchanged"])

    def test_actual_postgres_quotes_backslash_and_unicode_database_literals_do_not_inject(self):
        value = "fictional'\\数据库; SELECT pg_sleep(1); --"
        self.assertTrue(len(value.encode()) <= 63)
        result = self.run_engine({"mode": "literal", "literal": BUILDER.literal(value), "expected": value})
        self.assertTrue(result["literal_roundtrip"])
        self.plan["expected_database"] = value
        self.write_plan(self.plan)
        self.prepare()
        scripts = self.scripts()
        result = self.run_engine({"mode": "apply", "activation": scripts["activation.sql"],
                                  "cleanup": scripts["cleanup.sql"], "success": False})
        self.assertEqual(result["case"], "atomic-refusal")


if __name__ == "__main__":
    unittest.main()

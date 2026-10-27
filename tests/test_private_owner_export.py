"""Owner-local export framing and an isolated fictional PostgreSQL SELECT.

These tests never read bank captures or contact Supabase. The cached PostgreSQL
image runs without network/ports and every test row is synthetic.
"""
import csv
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_sync_database as database

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import export_private_server_backup as worker_export
import verify_private_backup as verifier

SQL = (ROOT / "tools/private_verify/owner-export.sql").read_text()
DECODER = ROOT / "tools/private_verify/owner-export.cjs"
PROJECT = worker_export.PROJECT_REF
HOUSE, USER, OTHER = database.HOUSE, database.USER, database.OTHER
MARKER = "FICTIONAL_OWNER_EXPORT_MARKER"
RAW_STATE = '''{"entries":[],"goals":[],"birthdays":[],"boardItems":[],
"chores":[],"installments":[],"settings":{"unicode":"учебное😀"},
"deletedEntries":{"old":"2001-01-01"},
"future":{"precise":123456789012345678901234567890.123456789,
"trailing":12.3400,"unknown":[null,true,"FICTIONAL_OWNER_EXPORT_MARKER"]}}'''


def decode(raw):
    # Reading fd0 is test transport only; the module itself has no FS/network.
    script = r"""const raw=require('node:fs').readFileSync(0);
const mod=require(process.argv[1]);
JSON.parse=()=>{throw new Error('JSON.parse forbidden in decoder');};
try { process.stdout.write(JSON.stringify(mod.decodeOwnerExport(raw))); }
catch(error) { process.stdout.write(JSON.stringify({error:error.code,
  message:error.message,name:error.name})); process.exitCode=2; }"""
    result = subprocess.run(["node", "-e", script, str(DECODER)], input=raw,
                            capture_output=True, timeout=10)
    if result.stderr:
        raise AssertionError("Unexpected decoder stderr")
    return result.returncode, json.loads(result.stdout)


def as_csv(value, *, header="backup_json", newline="\r\n"):
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator=newline)
    writer.writerow([header])
    writer.writerow([value])
    return out.getvalue().encode("utf-8")


class OwnerExportDecoder(unittest.TestCase):
    def test_json_and_csv_preserve_all_wrapper_bytes_without_numeric_parsing(self):
        # JSON duplicate keys and huge numbers must reach the strict core as
        # unchanged text. The decoder intentionally does not validate JSON.
        wrapper = ('{\n"snapshot_json":"\\\"учебное😀\\\"",'
                   '"number":123456789012345678901234567890.123456789,'
                   '"duplicate":1,"duplicate":2}\n')
        for raw, kind in [(wrapper.encode(), "json"),
                          (as_csv(wrapper), "csv"),
                          (b"\xef\xbb\xbf" + as_csv(wrapper, newline="\n"), "csv"),
                          (b"\xef\xbb\xbf" + wrapper.encode(), "json")]:
            with self.subTest(kind=kind, bom=raw.startswith(b"\xef\xbb\xbf")):
                code, answer = decode(raw)
                self.assertEqual(code, 0)
                self.assertEqual(answer, {"format":"marichevy-owner-export-decoded-v1",
                    "inputFormat":kind, "backupJson":wrapper})

    def test_csv_accepts_single_column_quoted_header_multiline_and_no_final_newline(self):
        wrapper = '{"text":"line1\\nline2,\\\"quoted\\\""}\r\n'
        raw = as_csv(wrapper).rstrip(b"\r\n")
        raw = raw.replace(b"backup_json", b'"backup_json"', 1)
        code, answer = decode(raw)
        self.assertEqual(code, 0)
        self.assertEqual(answer["backupJson"], wrapper)

    def test_csv_shape_header_and_grammar_refuse_fixed_errors(self):
        cases = [
            (b"backup_json\n", "owner-export-csv-shape"),
            (b"backup_json\n{}\n{}", "owner-export-csv-shape"),
            (b"backup_json\n{}\n\n", "owner-export-csv-shape"),
            (b"backup_json,extra\n{},x", "owner-export-csv-shape"),
            (b"backup_json\n{},", "owner-export-csv-shape"),
            (b"wrong\n{}", "owner-export-csv-header"),
            (b" backup_json\n{}", "owner-export-csv-header"),
            (b'backup_json\n"unterminated', "owner-export-csv-invalid"),
            (b'backup_json\n"{}"x', "owner-export-csv-invalid"),
            (b'backup_json\ninvalid"quote', "owner-export-csv-invalid"),
            (b"backup_json\r{}", "owner-export-csv-invalid"),
            (b'backup_json\n""', "owner-export-empty"),
            (b'backup_json\n" \r\n "', "owner-export-empty"),
            (b"", "owner-export-empty"),
            (b" \r\n", "owner-export-empty"),
            (b"\xff", "owner-export-invalid-utf8"),
            (b"\xef\xbb\xbf\xef\xbb\xbf{}", "owner-export-invalid-utf8"),
        ]
        for raw, expected in cases:
            with self.subTest(expected=expected, raw=raw):
                code, answer = decode(raw)
                self.assertEqual(code, 2)
                self.assertEqual(answer, {"error":expected, "message":expected,
                    "name":"OwnerExportError"})

    def test_type_size_and_error_messages_do_not_echo_private_input(self):
        script = r"""const m=require(process.argv[1]);const answers=[];
for(const value of ['FICTIONAL_OWNER_EXPORT_MARKER',null,{},new Uint16Array(1),
new Uint8Array(m.MAX_FILE+1)]){try{m.decodeOwnerExport(value);answers.push('bad');}
catch(e){answers.push({code:e.code,message:e.message,name:e.name});}}
process.stdout.write(JSON.stringify(answers));"""
        result = subprocess.run(["node", "-e", script, str(DECODER)],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertNotIn(MARKER, result.stdout)
        answers = json.loads(result.stdout)
        self.assertEqual([r["code"] for r in answers],
            ["owner-export-input-type"] * 4 + ["owner-export-size-limit"])
        self.assertTrue(all(r["message"] == r["code"] for r in answers))

    def test_import_does_not_open_files_or_network(self):
        script = r"""const Module=require('node:module');const load=Module._load;
const forbidden=new Set(['fs','node:fs','fs/promises','node:fs/promises','net',
'node:net','http','node:http','https','node:https','child_process','node:child_process']);
Module._load=function(name,...args){if(forbidden.has(name))throw new Error('io import');
return Reflect.apply(load,this,[name,...args]);};
const m=require(process.argv[1]);if(!Object.isFrozen(m))throw new Error('unfrozen');
process.stdout.write('passed');"""
        result = subprocess.run(["node", "-e", script, str(DECODER)],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "passed", ""))


class OwnerExportPostgreSQL(unittest.TestCase):
    docker = classmethod(database.SyncDatabaseTests.docker.__func__)
    sql = classmethod(database.SyncDatabaseTests.sql.__func__)
    setUpClass = classmethod(database.SyncDatabaseTests.setUpClass.__func__)

    def setUp(self):
        self.sql("""DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;
CREATE TABLE public.households(id uuid PRIMARY KEY,name text,created_at timestamptz);
CREATE TABLE public.family_state(household_id uuid PRIMARY KEY,data jsonb NOT NULL,
  updated_at timestamptz,updated_by uuid,future_extension numeric);
CREATE TABLE public.household_members(household_id uuid,user_id uuid,role text,
  created_at timestamptz,PRIMARY KEY(household_id,user_id));
CREATE TABLE public.family_chore_deliveries(household_id uuid,chore_id text,
  due_date date,chat_id text,status text,attempts integer,last_attempt_at timestamptz,
  sent_at timestamptz,telegram_message_id bigint,last_error text,created_at timestamptz,
  PRIMARY KEY(household_id,chore_id,due_date,chat_id));
""" + f"""INSERT INTO public.households VALUES
  ('{HOUSE}','{MARKER}','2001-02-03T04:05:06.123456Z');
INSERT INTO public.family_state VALUES ('{HOUSE}',{database.literal(RAW_STATE)}::jsonb,
  '2001-02-03T04:05:06.123456Z','{USER}',12345678901234567890.123456789);
INSERT INTO public.household_members VALUES ('{HOUSE}','{USER}','owner','2001-01-01Z');
INSERT INTO public.family_chore_deliveries VALUES ('{HOUSE}','fixture-chore',
  '2026-10-27','fixture-chat','fixture-status',1,NULL,NULL,1234567890123456789,NULL,
  '2001-01-01Z');""")

    def wrapper(self, prefix=""):
        return json.loads(self.sql(prefix + SQL), parse_float=Decimal)

    def test_single_read_only_select_preserves_exact_worker_snapshot_and_all_columns(self):
        before = self.sql("SELECT to_jsonb(s)::text FROM public.family_state s;")
        wrapper = self.wrapper("BEGIN READ ONLY;\n")
        self.assertEqual(wrapper["format"], "marichevy-private-server-backup-v1")
        self.assertIs(wrapper["read_only"], True)
        self.assertEqual(wrapper["project_ref"], PROJECT)
        self.assertEqual(wrapper["configured_household"], HOUSE)
        self.assertEqual(wrapper["configured_household_count"], 1)
        self.assertEqual(wrapper["database_role"], "postgres")
        self.assertEqual(wrapper["transaction_read_only"], "on")
        self.assertEqual(wrapper["database_name"], "sync_fictional")
        self.assertEqual(wrapper["export_method"], "sql-editor-select-v1")
        self.assertRegex(wrapper["captured_at_utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")
        raw = wrapper["snapshot_json"]
        self.assertEqual(wrapper["snapshot_json_sha256"], hashlib.sha256(raw.encode()).hexdigest())
        self.assertIn("123456789012345678901234567890.123456789", raw)
        self.assertIn("12.3400", raw)
        self.assertIn("12345678901234567890.123456789", raw)
        self.assertEqual(self.sql("SELECT to_jsonb(s)::text FROM public.family_state s;"), before)
        query = worker_export.SNAPSHOT_SQL.replace("$1", database.literal(HOUSE))
        worker_raw, timezone = self.sql(query).rsplit("|", 1)
        self.assertEqual(raw, worker_raw)
        self.assertEqual(wrapper["database_timezone"], timezone)
        # The existing exact-number verifier accepts the exported wrapper;
        # its independent scope arguments must come from the reviewed target.
        validated = verifier.parse(json.dumps(wrapper).encode())
        tables, _, _ = verifier.snapshot(validated, PROJECT, HOUSE)
        self.assertEqual(tables["family_state"][0]["future_extension"], Decimal("12345678901234567890.123456789"))

    def test_actual_query_hash_and_timezone_are_evidence_not_fixed_labels(self):
        a = self.wrapper("SET TIME ZONE 'Europe/Moscow';\n")
        b = self.wrapper("SET TIME ZONE 'UTC';\n")
        self.assertEqual(a["database_timezone"], "Europe/Moscow")
        self.assertEqual(b["database_timezone"], "UTC")
        self.assertIn("+03:00", a["snapshot_json"])
        self.assertNotEqual(a["snapshot_json_sha256"], b["snapshot_json_sha256"])
        self.assertRegex(a["query_sha256"], "^[a-f0-9]{64}$")
        # Adding an innocuous comment changes actual received SQL and its hash.
        changed = json.loads(self.sql(SQL.replace("WITH scope", "/* fixture-query-identity */\nWITH scope", 1)))
        self.assertNotEqual(b["query_sha256"], changed["query_sha256"])
        self.assertEqual(b["snapshot_json"], changed["snapshot_json"])
        exact = self.docker("exec", "-i", self.container, "psql", "-X", "-qAt",
            "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "sync_fictional", "-c", SQL)
        self.assertEqual(json.loads(exact.stdout)["query_sha256"], hashlib.sha256(SQL.encode()).hexdigest())

    def test_csv_download_roundtrip_of_actual_postgres_text_preserves_snapshot_hash(self):
        wrapper_text = self.sql(SQL)
        code, decoded = decode(as_csv(wrapper_text))
        self.assertEqual(code, 0)
        self.assertEqual(decoded["backupJson"], wrapper_text)
        wrapper = json.loads(decoded["backupJson"])
        self.assertEqual(wrapper["snapshot_json_sha256"],
            hashlib.sha256(wrapper["snapshot_json"].encode()).hexdigest())

    def assert_scope_refusal(self, mutation):
        self.sql(mutation)
        before = self.sql("SELECT jsonb_agg(to_jsonb(s)) FROM public.family_state s;")
        result = self.sql("\\set VERBOSITY verbose\n" + SQL, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("22012", result.stderr)
        self.assertEqual(self.sql("SELECT jsonb_agg(to_jsonb(s)) FROM public.family_state s;"), before)

    def test_ambiguous_missing_or_foreign_rows_refuse_without_selecting_first_family(self):
        mutations = [
            "DELETE FROM public.households;",
            f"INSERT INTO public.households VALUES ('{OTHER}','other',now());",
            "DELETE FROM public.family_state;",
            f"INSERT INTO public.family_state(household_id,data) VALUES ('{OTHER}','{{}}');",
            "DELETE FROM public.household_members;",
            f"INSERT INTO public.household_members VALUES ('{OTHER}','{USER}','owner',now());",
            f"UPDATE public.household_members SET household_id='{OTHER}';",
            "ALTER TABLE public.household_members DROP CONSTRAINT household_members_pkey;"
            "ALTER TABLE public.household_members ALTER COLUMN household_id DROP NOT NULL;"
            "UPDATE public.household_members SET household_id=NULL;",
            f"UPDATE public.family_chore_deliveries SET household_id='{OTHER}';",
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.setUp()
                self.assert_scope_refusal(mutation)

    def test_empty_delivery_and_multiple_same_family_members_are_allowed(self):
        self.sql("DELETE FROM public.family_chore_deliveries;" +
                 f"INSERT INTO public.household_members VALUES ('{HOUSE}','{OTHER}','member',now());")
        tables = json.loads(self.wrapper()["snapshot_json"])
        self.assertEqual(tables["family_chore_deliveries"], [])
        self.assertEqual(len(tables["household_members"]), 2)

    def test_nonpostgres_role_cannot_hide_other_families_with_rls(self):
        self.sql(f"INSERT INTO public.households VALUES ('{OTHER}','other',now());"
                 "GRANT USAGE ON SCHEMA public TO authenticated;"
                 "GRANT SELECT ON ALL TABLES IN SCHEMA public TO authenticated;")
        self.sql("ALTER TABLE public.households ENABLE ROW LEVEL SECURITY;"
                 f"CREATE POLICY fixture_hide_other ON public.households TO authenticated USING(id='{HOUSE}');")
        self.assertEqual(self.sql("SET ROLE authenticated; SELECT count(*) FROM public.households;"), "1")
        result = self.sql("\\set VERBOSITY verbose\nSET ROLE authenticated;\n" + SQL, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("22012", result.stderr)


if __name__ == "__main__":
    unittest.main()

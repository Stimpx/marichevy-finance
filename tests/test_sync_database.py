"""Real PostgreSQL contract tests; fictional DB, no ports/network/app credentials."""
import concurrent.futures
import copy
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "postgres:16-alpine@sha256:f4610795587492cd4fb887c2dc3de301b813278bb6f616992061141b5f15ac36"
HOUSE = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
USER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OUTSIDER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
FIXTURE = {
    "entries": [{"id": "entry", "unknown": {"raw": "keep"}}],
    "goals": [{"id": "goal"}], "birthdays": [{"id": "date"}],
    "boardItems": [{"id": "board"}], "chores": [{"id": "chore"}],
    "installments": [{"id": "installment", "parts": [{"paid": False}]}],
    "intelligence": {"budgets": [{"id": "budget"}], "recurring": [{"id": "recurring"}],
                     "accounts": [{"id": "account"}],
                     "deleted": {"budgets": {"old": 1}, "recurring": {"old": 2}, "accounts": {"old": 3}}},
    "deletedEntries": {"old": 4}, "deletedGoals": {"old": 5}, "deletedBirthdays": {"old": 6},
    "deletedBoardItems": {"old": 7}, "deletedChores": {"old": 8}, "deletedInstallments": {"old": 9},
    "settings": {"unknown": "preserve"}, "futureCollection": [{"nested": [None, True, 42, "ñ"]}],
}


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


class SyncDatabaseTests(unittest.TestCase):
    @classmethod
    def docker(cls, *args, sql=None, check=True):
        env = os.environ.copy()
        for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
            env.pop(key, None)
        return subprocess.run(["docker", "--host=unix:///var/run/docker.sock", *args],
                              input=sql, text=True, capture_output=True, env=env,
                              check=check, timeout=45)

    @classmethod
    def setUpClass(cls):
        cls.docker("image", "inspect", IMAGE)
        cls.container = "marichevy-sync-test-" + uuid.uuid4().hex[:12]
        cls.docker("run", "--detach", "--rm", "--pull=never", "--network=none",
                   "--name", cls.container, "--tmpfs", "/var/lib/postgresql/data",
                   "-e", "POSTGRES_HOST_AUTH_METHOD=trust", IMAGE)
        cls.addClassCleanup(lambda: cls.docker("rm", "--force", cls.container, check=False))
        # The image starts a socket-only temporary server while initializing.
        # Wait for the final TCP-listening server, not that transient readiness.
        for _ in range(100):
            ready = cls.docker("exec", cls.container, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", check=False)
            if ready.returncode == 0:
                break
            time.sleep(.1)
        else:
            raise RuntimeError("Local PostgreSQL did not become ready")
        cls.sql("CREATE DATABASE sync_fictional; CREATE ROLE authenticated; CREATE ROLE anon;", database="postgres")

    @classmethod
    def sql(cls, query, check=True, variables=(), database="sync_fictional"):
        command = ["exec", "-i", cls.container, "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
                   "-U", "postgres", "-d", database]
        for name, value in variables:
            command.extend(("-v", f"{name}={value}"))
        result = cls.docker(*command, sql=query, check=False)
        if check and result.returncode:
            raise AssertionError(result.stderr)
        return result if not check else result.stdout.strip()

    @classmethod
    def as_user(cls, query, user=USER, check=True, role="authenticated"):
        return cls.sql(f"SET ROLE {role}; SET request.jwt.claim.sub = {literal(user)};\n" + query, check=check)

    def setUp(self):
        self.sql("""
DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;
DROP SCHEMA IF EXISTS auth CASCADE; CREATE SCHEMA auth;
GRANT USAGE ON SCHEMA public, auth TO authenticated, anon;
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
  $$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
CREATE TABLE public.membership(household_id uuid, user_id uuid);
GRANT SELECT ON public.membership TO authenticated;
CREATE TABLE public.family_state(household_id uuid PRIMARY KEY, data jsonb NOT NULL,
  updated_at timestamptz DEFAULT now(), updated_by uuid);
ALTER TABLE public.family_state ENABLE ROW LEVEL SECURITY;
CREATE POLICY household_members ON public.family_state TO authenticated
  USING (EXISTS (SELECT FROM public.membership m WHERE m.household_id = family_state.household_id AND m.user_id = auth.uid()))
  WITH CHECK (EXISTS (SELECT FROM public.membership m WHERE m.household_id = family_state.household_id AND m.user_id = auth.uid()));
GRANT SELECT, INSERT, UPDATE, DELETE ON public.family_state TO authenticated;
""" + f"INSERT INTO public.membership VALUES ('{HOUSE}','{USER}'), ('{OTHER}','{OUTSIDER}');"
            + f"INSERT INTO public.family_state(household_id,data) VALUES ('{HOUSE}',{literal(json.dumps(FIXTURE))}::jsonb), ('{OTHER}','{{}}');")
        self.sql((ROOT / "server/001_family_state_cas.sql").read_text())

    def activate(self):
        self.sql(f"UPDATE public.family_state SET sync_protocol=2 WHERE household_id='{HOUSE}';")
        return self.snapshot()["revision"]

    def snapshot(self):
        return json.loads(self.sql(f"SELECT jsonb_build_object('data',data,'revision',sync_revision,'protocol',sync_protocol,'request_id',last_request_id,'updated_by',updated_by) FROM public.family_state WHERE household_id='{HOUSE}';"))

    @classmethod
    def cas(cls, revision, data, request=None, house=HOUSE, user=USER):
        request = request or str(uuid.uuid4())
        return json.loads(cls.as_user(f"SELECT public.family_state_cas('{house}',{revision},{literal(json.dumps(data))}::jsonb,'{request}');", user=user))

    def test_01_migration_preserves_data_and_rls(self):
        self.assertEqual(self.snapshot()["data"], FIXTURE)
        self.assertEqual(self.snapshot()["revision"], 0)
        self.assertEqual(self.snapshot()["protocol"], 1)
        self.assertEqual(self.sql("SELECT count(*) FROM pg_policies WHERE tablename='family_state' AND policyname='household_members';"), "1")
        self.assertEqual(self.sql("SELECT relrowsecurity FROM pg_class WHERE oid='public.family_state'::regclass;"), "t")

    def test_02_protocol_one_requires_upgrade(self):
        self.assertEqual(self.cas(0, FIXTURE)["status"], "upgrade_required")
        self.assertEqual(self.snapshot()["revision"], 0)

    def test_03_legacy_protocol_one_compatible_revision_server_owned(self):
        self.as_user(f"UPDATE public.family_state SET data='{{\"legacy\":true}}', sync_revision=900, updated_by='{OUTSIDER}',last_request_id='{OUTSIDER}' WHERE household_id='{HOUSE}';")
        row = self.snapshot()
        self.assertEqual((row["revision"], row["updated_by"], row["request_id"]), (1, USER, None))

    def test_04_sequential_conflict_then_retry_preserves_both_writers(self):
        revision = self.activate()
        a = copy.deepcopy(FIXTURE); a["entries"].append({"id": "writer-a"})
        b = copy.deepcopy(FIXTURE); b["goals"].append({"id": "writer-b"})
        ack = self.cas(revision, a)
        self.assertEqual(ack["status"], "written")
        conflict = self.cas(revision, b)
        self.assertEqual(conflict["status"], "conflict")
        self.assertEqual(conflict["data"], a)
        merged = conflict["data"]; merged["goals"] = b["goals"]
        self.assertEqual(self.cas(conflict["revision"], merged)["status"], "written")
        self.assertEqual(self.snapshot()["data"], merged)
        self.assertEqual(self.snapshot()["updated_by"], USER)

    def test_05_concurrent_same_revision_has_one_winner(self):
        revision = self.activate()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda n: self.cas(revision, {"writer": n}), (1, 2)))
        self.assertCountEqual([r["status"] for r in results], ["written", "conflict"])
        self.assertEqual(self.snapshot()["revision"], revision + 1)

    def test_06_retry_is_idempotent(self):
        revision = self.activate(); request = str(uuid.uuid4())
        ack = self.cas(revision, FIXTURE, request)
        self.assertEqual(self.cas(revision, FIXTURE, request), ack)
        self.assertEqual(self.snapshot()["revision"], revision + 1)
        self.assertEqual(self.cas(revision + 1, {"changed": True}, request)["status"], "conflict")

    def test_07_legacy_update_upsert_delete_and_downgrade_blocked(self):
        self.activate(); before = self.snapshot()
        queries = [f"UPDATE public.family_state SET data='{{}}' WHERE household_id='{HOUSE}';",
                   f"INSERT INTO public.family_state(household_id,data) VALUES ('{HOUSE}','{{}}') ON CONFLICT(household_id) DO UPDATE SET data=excluded.data;",
                   f"DELETE FROM public.family_state WHERE household_id='{HOUSE}';",
                   f"UPDATE public.family_state SET sync_protocol=1 WHERE household_id='{HOUSE}';"]
        for query in queries:
            with self.subTest(query=query):
                result = self.as_user("\\set VERBOSITY verbose\n" + query, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("PT409", result.stderr)
                self.assertIn("upgrade_required", result.stderr)
                self.assertEqual(self.snapshot(), before)

    def test_08_cross_household_read_write_and_rpc_denied(self):
        self.activate(); before = self.snapshot()
        self.assertEqual(self.as_user(f"SELECT count(*) FROM public.family_state WHERE household_id='{HOUSE}';", user=OUTSIDER), "0")
        self.as_user(f"UPDATE public.family_state SET data='{{}}' WHERE household_id='{HOUSE}';", user=OUTSIDER)
        self.assertEqual(self.cas(1, {}, user=OUTSIDER), {"status": "not_found", "revision": None, "protocol": None, "data": None, "request_id": None})
        result = self.as_user(f"INSERT INTO public.family_state(household_id,data) VALUES ('{HOUSE}','{{}}');", user=OUTSIDER, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_09_anon_cannot_execute(self):
        result = self.as_user(f"SELECT public.family_state_cas('{HOUSE}',0,'{{}}','{USER}');", role="anon", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("permission denied for function family_state_cas", result.stderr)

    def test_10_activation_and_rollback_templates_keep_json(self):
        variables = [("expected_database", "sync_fictional"), ("household_id", HOUSE), ("expected_revision", "0"), ("confirmation", "ACTIVATE_REVIEWED_HOUSEHOLD")]
        self.sql((ROOT / "server/activate_household.sql").read_text(), variables=variables)
        self.assertEqual(self.snapshot()["data"], FIXTURE)
        self.assertEqual((self.snapshot()["protocol"], self.snapshot()["revision"]), (2, 1))
        variables[-2:] = [("expected_revision", "1"), ("confirmation", "DISABLE_SYNC_REVIEWED_HOUSEHOLD")]
        self.sql((ROOT / "server/rollback_household.sql").read_text(), variables=variables)
        self.assertEqual(self.snapshot()["data"], FIXTURE)
        self.assertEqual((self.snapshot()["protocol"], self.snapshot()["revision"]), (1, 2))
        self.assertEqual(self.cas(2, FIXTURE)["status"], "upgrade_required")

    def test_11_operator_template_wrong_database_or_revision_refused(self):
        before = self.snapshot()
        for database, revision in (("production_not_allowed", "0"), ("sync_fictional", "99")):
            result = self.sql((ROOT / "server/activate_household.sql").read_text(), check=False,
                variables=[("expected_database", database), ("household_id", HOUSE), ("expected_revision", revision), ("confirmation", "ACTIVATE_REVIEWED_HOUSEHOLD")])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.snapshot(), before)

    def test_12_all_collections_unknown_json_roundtrip(self):
        revision = self.activate()
        ack = self.cas(revision, FIXTURE)
        self.assertEqual(ack["data"], FIXTURE)
        self.assertEqual(self.snapshot()["data"], FIXTURE)

    def test_13_marker_cleared_after_rpc(self):
        self.activate()
        result = self.as_user(f"BEGIN; SELECT public.family_state_cas('{HOUSE}',1,'{{}}','{USER}'); UPDATE public.family_state SET data='{{\"unsafe\":true}}' WHERE household_id='{HOUSE}'; COMMIT;", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("upgrade_required", result.stderr)
        self.assertEqual(self.snapshot()["data"], FIXTURE)

    def test_14_migration_fails_closed_on_unknown_schema(self):
        self.sql("DROP TRIGGER family_state_sync_guard ON public.family_state; DROP FUNCTION public.family_state_cas(uuid,bigint,jsonb,uuid); DROP FUNCTION public.family_state_sync_guard(); ALTER TABLE public.family_state DROP COLUMN sync_revision, DROP COLUMN sync_protocol, DROP COLUMN last_request_id; ALTER TABLE public.family_state ADD COLUMN unexpected text;")
        result = self.sql((ROOT / "server/001_family_state_cas.sql").read_text(), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported family_state columns/types", result.stderr)
        self.assertEqual(self.sql("SELECT count(*) FROM information_schema.columns WHERE table_name='family_state' AND column_name='sync_revision';"), "0")

    def test_15_rpc_is_invoker_and_null_identity_denied(self):
        self.assertEqual(self.sql("SELECT prosecdef FROM pg_proc WHERE oid='public.family_state_cas(uuid,bigint,jsonb,uuid)'::regprocedure;"), "f")
        result = self.as_user(f"SELECT public.family_state_cas('{HOUSE}',0,'{{}}','{USER}');", user="", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Authenticated user required", result.stderr)


if __name__ == "__main__":
    unittest.main()

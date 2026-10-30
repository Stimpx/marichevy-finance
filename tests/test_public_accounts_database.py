"""Public account contracts on networkless, disposable PostgreSQL only.

The small auth stand-in makes identity and confirmation changes explicit. These
tests establish SQL authorization and races; they do not contact Supabase or
claim that hosted Auth, SMTP, or PostgREST has been configured.
"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import unittest
import uuid

import test_sync_database as database

ROOT = Path(__file__).resolve().parents[1]
USER = database.USER
OUTSIDER = database.OUTSIDER
EDITOR = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
VIEWER = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
UNVERIFIED = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
INVITEE = "ffffffff-ffff-4fff-8fff-ffffffffffff"
UNKNOWN = "99999999-9999-4999-8999-999999999999"
EMAILS = {
    USER: "owner@example.invalid", OUTSIDER: "other@example.invalid",
    EDITOR: "editor@example.invalid", VIEWER: "viewer@example.invalid",
    UNVERIFIED: "unverified@example.invalid", INVITEE: "invitee@example.invalid",
}
TABLES = ("households", "members", "family_state", "invitations", "mail_jobs")


def arg(value):
    if value is None:
        return "NULL"
    if isinstance(value, (dict, list)):
        return database.literal(json.dumps(value)) + "::jsonb"
    if isinstance(value, int):
        return str(value)
    return database.literal(value)


class PublicAccountsDatabase(unittest.TestCase):
    docker = classmethod(database.SyncDatabaseTests.docker.__func__)
    sql = classmethod(database.SyncDatabaseTests.sql.__func__)

    @classmethod
    def setUpClass(cls):
        database.SyncDatabaseTests.setUpClass.__func__(cls)
        cls.sql("CREATE ROLE service_role;", database="postgres")

    @classmethod
    def as_user(cls, query, user=USER, check=True, role="authenticated", email=None):
        claims = {"sub": user, "role": role, "email": email or EMAILS.get(user, "missing@example.invalid")}
        return database.SyncDatabaseTests.as_user.__func__(cls,
            "SET request.jwt.claim.role = " + database.literal(role) + ";\n"
            + "SET request.jwt.claim.email = " + database.literal(claims["email"]) + ";\n"
            + "SET request.jwt.claims = " + database.literal(json.dumps(claims)) + ";\n" + query,
            user=user, check=check, role=role)

    @classmethod
    def rpc(cls, name, *args, user=USER, check=True, role="authenticated", email=None):
        result = cls.as_user("SELECT public.finance_" + name + "(" + ",".join(arg(a) for a in args) + ");",
                             user=user, check=check, role=role, email=email)
        return json.loads(result) if check and result else result

    def setUp(self):
        # All destructive setup is restricted to the harness's local DB.
        self.sql("""
DROP SCHEMA IF EXISTS finance_app CASCADE;
DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;
DROP SCHEMA IF EXISTS auth CASCADE; CREATE SCHEMA auth;
GRANT USAGE ON SCHEMA public,auth TO authenticated,anon,service_role;
CREATE TABLE auth.users(id uuid PRIMARY KEY,email text UNIQUE,email_confirmed_at timestamptz);
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
  $$ SELECT nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
CREATE FUNCTION auth.role() RETURNS text LANGUAGE sql STABLE AS
  $$ SELECT nullif(current_setting('request.jwt.claim.role',true),'') $$;
CREATE TABLE public.households(id uuid PRIMARY KEY,name text);
CREATE TABLE public.household_members(household_id uuid,user_id uuid,role text);
CREATE TABLE public.family_state(household_id uuid PRIMARY KEY,data jsonb);
ALTER TABLE public.family_state ENABLE ROW LEVEL SECURITY;
CREATE POLICY legacy_fixture ON public.family_state TO authenticated USING (false);
INSERT INTO public.households VALUES ('11111111-1111-4111-8111-111111111111','legacy personal fixture');
INSERT INTO public.household_members VALUES
  ('11111111-1111-4111-8111-111111111111','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','member');
INSERT INTO public.family_state VALUES
  ('11111111-1111-4111-8111-111111111111','{"entries":[{"id":"legacy-private","amount":9876}],"birthdays":[{"name":"legacy-only"}]}');
"""
            + "\n".join("INSERT INTO auth.users VALUES (" + arg(user) + "," + arg(email)
                        + "," + ("NULL" if user == UNVERIFIED else "now()") + ");"
                        for user, email in EMAILS.items()))
        self.legacy = self.sql("SELECT jsonb_agg(to_jsonb(f)) FROM public.family_state f;")
        self.sql((ROOT / "server/004_public_accounts.sql").read_text())
        self.house = self.rpc("create_household", "Fictional family A", "UTC", str(uuid.uuid4()))["id"]
        self.other = self.rpc("create_household", "Fictional family B", "Europe/Paris", str(uuid.uuid4()), user=OUTSIDER)["id"]
        self.sql(f"INSERT INTO finance_app.members(household_id,user_id,role) VALUES ('{self.house}','{EDITOR}','editor'),('{self.house}','{VIEWER}','viewer');")

    def denied(self, name, *args, user=USER, role="authenticated", email=None):
        result = self.rpc(name, *args, user=user, check=False, role=role, email=email)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def state(self, house=None, user=USER):
        return self.rpc("read_state", house or self.house, user=user)[0]

    def cas(self, data, revision=0, request=None, user=USER, house=None, check=True):
        return self.rpc("state_cas", house or self.house, revision, data,
                        request or str(uuid.uuid4()), user=user, check=check)

    def invite(self, email=None, role="viewer", request=None, token=None):
        token = token or uuid.uuid4().hex + uuid.uuid4().hex
        request = request or str(uuid.uuid4())
        digest = hashlib.sha256(token.encode()).hexdigest()
        row = self.rpc("create_invite", self.house, email or EMAILS[INVITEE], role, request, digest)
        return row, token, request

    def test_new_family_is_blank_free_and_legacy_fixture_is_unchanged(self):
        row = self.rpc("get_household", self.house)
        self.assertEqual((row["role"], row["plan"], row["name"], row["timezone"]),
                         ("owner", "free", "Fictional family A", "UTC"))
        self.assertEqual([person["name"] for person in row["settings"]["people"]], ["Общее"])
        self.assertEqual([category["name"] for category in row["settings"]["categories"]],
                         ["Продукты", "Кафе", "Транспорт", "Дом", "Здоровье", "Дети", "Подписки", "Прочее"])
        ids = [item["id"] for values in row["settings"].values() for item in values]
        self.assertEqual(len(ids), len(set(ids)))
        for item in ids:
            self.assertEqual(str(uuid.UUID(item)), item)
        state = self.state()
        self.assertEqual(state["sync_protocol"], 2)
        self.assertEqual(state["sync_revision"], 0)
        self.assertEqual(state["data"].get("settings"), {})
        for key in ("entries", "birthdays", "goals", "boardItems", "chores", "installments"):
            self.assertEqual(state["data"].get(key, []), [])
        self.assertNotIn("legacy-private", json.dumps(state))
        self.assertNotIn("legacy-only", json.dumps(state))
        self.assertEqual(self.sql("SELECT jsonb_agg(to_jsonb(f)) FROM public.family_state f;"), self.legacy)
        self.assertEqual(self.sql("SELECT count(*) FROM pg_policies WHERE schemaname='public' AND policyname='legacy_fixture';"), "1")

    def test_every_new_table_has_rls_and_clients_have_no_direct_table_access(self):
        self.assertEqual(self.sql("SELECT bool_and(relrowsecurity) FROM pg_class WHERE relnamespace='finance_app'::regnamespace AND relkind='r';"), "t")
        for table in TABLES:
            with self.subTest(table=table):
                self.assertEqual(self.sql(f"SELECT relrowsecurity FROM pg_class WHERE oid='finance_app.{table}'::regclass;"), "t")
                for role in ("authenticated", "anon"):
                    self.assertEqual(self.sql(f"SELECT has_table_privilege('{role}','finance_app.{table}','SELECT,INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER,REFERENCES');"), "f")
                    result = self.as_user(f"SELECT * FROM finance_app.{table};", role=role, check=False)
                    self.assertNotEqual(result.returncode, 0)

    def test_rls_still_blocks_direct_access_if_table_grants_are_accidentally_added(self):
        self.sql("GRANT USAGE ON SCHEMA finance_app TO authenticated; GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA finance_app TO authenticated;")
        for table in TABLES:
            with self.subTest(table=table):
                self.assertEqual(self.as_user(f"SELECT count(*) FROM finance_app.{table};", user=VIEWER), "0")
        self.as_user(f"UPDATE finance_app.family_state SET data='{{\"unexpected\":true}}' WHERE household_id='{self.house}';", user=VIEWER)
        insert = self.as_user(f"INSERT INTO finance_app.members(household_id,user_id,role) VALUES ('{self.house}','{INVITEE}','owner');", user=VIEWER, check=False)
        self.assertNotEqual(insert.returncode, 0)
        self.assertEqual(self.state()["sync_revision"], 0)

    def test_create_retry_is_idempotent_and_separate_requests_create_separate_families(self):
        request = str(uuid.uuid4())
        a = self.rpc("create_household", "Idempotent", "UTC", request)
        b = self.rpc("create_household", "Idempotent", "UTC", request)
        self.assertEqual(a, b)
        self.assertEqual(self.sql(f"SELECT count(*) FROM finance_app.households WHERE id='{a['id']}';"), "1")
        other = self.rpc("create_household", "Idempotent", "UTC", str(uuid.uuid4()))
        self.assertNotEqual(a["id"], other["id"])

    def test_concurrent_create_retry_creates_one_owner_and_state(self):
        request = str(uuid.uuid4())
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(lambda _: self.rpc("create_household", "Concurrent", "UTC", request), (1, 2)))
        self.assertEqual(rows[0]["id"], rows[1]["id"])
        house = rows[0]["id"]
        self.assertEqual(self.sql(f"SELECT count(*) FROM finance_app.members WHERE household_id='{house}' AND role='owner';"), "1")
        self.assertEqual(self.sql(f"SELECT count(*) FROM finance_app.family_state WHERE household_id='{house}';"), "1")

    def test_two_families_are_isolated_and_revocation_ignores_stale_jwt_role(self):
        self.assertEqual([h["id"] for h in self.rpc("list_households", user=OUTSIDER)], [self.other])
        self.denied("read_state", self.house, user=OUTSIDER)
        self.denied("get_household", self.house, user=OUTSIDER)
        self.denied("list_members", self.house, user=OUTSIDER)
        self.denied("list_invites", self.house, user=OUTSIDER)
        denied = self.cas({"entries": [{"id": "foreign"}]}, user=OUTSIDER, check=False)
        if denied.returncode == 0:
            self.assertEqual(json.loads(denied.stdout)["status"], "not_found")
        self.rpc("remove_member", self.house, EDITOR)
        self.denied("read_state", self.house, user=EDITOR)
        self.denied("get_household", self.house, user=EDITOR)
        self.assertEqual(self.rpc("list_households", user=EDITOR), [])

    def test_viewer_reads_but_cannot_write_finance_settings_members_or_invites(self):
        self.assertEqual(self.state(user=VIEWER)["household_id"], self.house)
        for name, args in (
            ("state_cas", (self.house, 0, {"entries": []}, str(uuid.uuid4()))),
            ("update_settings", (self.house, "Changed", "UTC", [], [], str(uuid.uuid4()))),
            ("set_member_role", (self.house, EDITOR, "viewer")),
            ("remove_member", (self.house, EDITOR)),
            ("create_invite", (self.house, EMAILS[INVITEE], "viewer", str(uuid.uuid4()), "a" * 64)),
            ("list_invites", (self.house,)),
        ):
            with self.subTest(name=name):
                self.denied(name, *args, user=VIEWER)
        for table in TABLES:
            result = self.as_user(f"DELETE FROM finance_app.{table};", user=VIEWER, check=False)
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state()["sync_revision"], 0)

    def test_editor_can_cas_but_cannot_manage_family(self):
        data = {"entries": [{"id": "editor-write", "amount": 12}], "unknown": {"preserve": True}}
        self.assertEqual(self.cas(data, user=EDITOR)["status"], "written")
        self.assertEqual(self.state()["data"], data)
        self.denied("update_settings", self.house, "Changed", "UTC", [], [], str(uuid.uuid4()), user=EDITOR)
        self.denied("set_member_role", self.house, VIEWER, "editor", user=EDITOR)
        self.denied("remove_member", self.house, VIEWER, user=EDITOR)

    def test_confirmation_is_current_for_every_route_not_claimed_in_jwt(self):
        self.sql(f"UPDATE auth.users SET email_confirmed_at=NULL WHERE id='{USER}';")
        operations = (
            ("list_households", ()), ("get_household", (self.house,)),
            ("create_household", ("Blocked", "UTC", str(uuid.uuid4()))),
            ("read_state", (self.house,)),
            ("state_cas", (self.house, 0, {}, str(uuid.uuid4()))),
            ("list_members", (self.house,)), ("list_invites", (self.house,)),
            ("update_settings", (self.house, "Blocked", "UTC", [], [], str(uuid.uuid4()))),
            ("set_member_role", (self.house, VIEWER, "editor")),
            ("remove_member", (self.house, VIEWER)),
            ("create_invite", (self.house, EMAILS[INVITEE], "viewer", str(uuid.uuid4()), "a" * 64)),
            ("accept_invite", ("a" * 64,)),
            ("revoke_invite", (self.house, str(uuid.uuid4()))),
        )
        for name, args in operations:
            with self.subTest(name=name):
                self.denied(name, *args)
        self.assertEqual(self.sql(f"SELECT count(*) FROM finance_app.members WHERE household_id='{self.house}';"), "3")

    def test_anon_missing_unknown_and_unverified_identities_cannot_start(self):
        for user, role in ((USER, "anon"), ("", "authenticated"), (UNKNOWN, "authenticated"), (UNVERIFIED, "authenticated")):
            with self.subTest(user=user, role=role):
                self.denied("list_households", user=user, role=role)
                self.denied("create_household", "No", "UTC", str(uuid.uuid4()), user=user, role=role)
        # An authenticated-looking claim cannot grant an anonymous SQL role RPC access.
        result = self.as_user("SET request.jwt.claim.role='authenticated'; SELECT public.finance_list_households();",
                              role="anon", check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_cas_retry_conflict_and_simultaneous_writers_preserve_protocol_contract(self):
        request = str(uuid.uuid4())
        data = {"entries": [{"id": "first"}], "future": {"raw": [None, True, 42]}}
        ack = self.cas(data, request=request)
        self.assertEqual(ack["status"], "written")
        self.assertEqual(ack["revision"], 1)
        self.assertEqual(ack["protocol"], 2)
        self.assertEqual(self.cas(data, request=request), ack)
        conflict = self.cas({"entries": [{"id": "stale"}]})
        self.assertEqual((conflict["status"], conflict["data"]), ("conflict", data))
        self.assertEqual(self.cas({"different": True}, revision=1, request=request)["status"], "conflict")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(lambda n: self.cas({"writer": n}, revision=1), (1, 2)))
        self.assertCountEqual([r["status"] for r in rows], ["written", "conflict"])
        self.assertEqual(self.state()["sync_revision"], 2)

    def test_owner_can_update_settings_and_cannot_grant_owner_through_member_api(self):
        state_before = self.state()
        request = str(uuid.uuid4())
        args = (self.house, "New family label", "Europe/Paris", ["Alex"], ["Food"], request)
        self.rpc("update_settings", *args)
        row = self.rpc("get_household", self.house)
        self.assertEqual((row["name"], row["timezone"]), ("New family label", "Europe/Paris"))
        self.assertEqual(row["settings"], {"people": ["Alex"], "categories": ["Food"]})
        self.assertEqual(row["plan"], "free")
        self.assertEqual(self.state(), state_before)
        self.rpc("set_member_role", self.house, VIEWER, "editor")
        self.assertEqual(self.sql(f"SELECT role FROM finance_app.members WHERE household_id='{self.house}' AND user_id='{VIEWER}';"), "editor")
        self.denied("set_member_role", self.house, VIEWER, "owner")
        self.denied("set_member_role", self.house, VIEWER, "member")
        self.denied("set_member_role", self.house, USER, "viewer")
        self.denied("remove_member", self.house, USER)

    def test_catalog_objects_keep_stable_ids_and_validate_names_archive_and_duplicates(self):
        person_id, category_id = str(uuid.uuid4()), str(uuid.uuid4())
        people = [{"id": person_id, "name": "Fictional person", "archived": False}]
        categories = [{"id": category_id, "name": "Food", "archived": False}]
        self.rpc("update_settings", self.house, "Catalog family", "UTC", people, categories, str(uuid.uuid4()))
        categories[0]["name"] = "Groceries"
        result = self.rpc("update_settings", self.house, "Catalog family", "UTC", people, categories, str(uuid.uuid4()))
        self.assertEqual(result["settings"]["categories"][0]["id"], category_id)
        for invalid in ([{"id": "bad", "name": "Food"}],
                        [{"id": category_id, "name": ""}],
                        [{"id": category_id, "name": "Food", "archived": "false"}],
                        [{"id": category_id, "name": "Food"}, {"id": category_id, "name": "Other"}],
                        [{"id": category_id, "name": "Food"}, {"id": str(uuid.uuid4()), "name": "food"}]):
            with self.subTest(invalid=invalid):
                self.denied("update_settings", self.house, "Catalog family", "UTC", people, invalid, str(uuid.uuid4()))
        categories[0]["archived"] = True
        categories.append({"id": str(uuid.uuid4()), "name": "Groceries", "archived": False})
        self.rpc("update_settings", self.house, "Catalog family", "UTC", people, categories, str(uuid.uuid4()))

    def test_cas_allows_financial_settings_but_cannot_activate_pro(self):
        before = self.state()
        metadata_settings = self.rpc("get_household", self.house)["settings"]
        for user in (USER, EDITOR):
            for data in ({"settings": {"plan": "pro"}}, {"settings": {"pro": True}},
                         {"settings": {"entitlement": "pro"}}, {"settings": {"entitlements": ["pro"]}},
                         {"plan": "pro"}, {"pro": True}, {"entitlement": "pro"}, {"entitlements": ["pro"]}):
                with self.subTest(user=user, data=data):
                    self.denied("state_cas", self.house, 0, data, str(uuid.uuid4()), user=user)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.rpc("get_household", self.house)["plan"], "free")
        financial = {"settings": {"currency": "RUB", "future": {"opaque": [1, True]}}, "entries": []}
        self.assertEqual(self.cas(financial, user=EDITOR)["status"], "written")
        self.assertEqual(self.state()["data"], financial)
        self.assertEqual(self.rpc("get_household", self.house)["settings"], metadata_settings)

    def test_cas_direct_rpc_document_limit_is_atomic(self):
        before = self.state()
        self.denied("state_cas", self.house, 0, {"large": "x" * 1000000}, str(uuid.uuid4()), user=EDITOR)
        self.assertEqual(self.state(), before)

    def test_family_creation_budget_does_not_break_idempotent_retry(self):
        request = str(uuid.uuid4())
        first = self.rpc("create_household", "Budgeted family", "UTC", request)
        for _ in range(3):
            self.rpc("create_household", "Budgeted family", "UTC", str(uuid.uuid4()))
        self.denied("create_household", "Budget exceeded", "UTC", str(uuid.uuid4()))
        self.assertEqual(self.rpc("create_household", "Budgeted family", "UTC", request)["id"], first["id"])

    def test_invite_is_hash_only_bound_to_verified_current_email_and_single_use(self):
        invite, token, _ = self.invite(role="editor")
        self.assertEqual(invite["status"], "pending")
        stored = self.sql(f"SELECT row_to_json(i) FROM finance_app.invitations i WHERE id='{invite['id']}';")
        self.assertNotIn(token, stored)
        self.assertIn(hashlib.sha256(token.encode()).hexdigest(), stored)
        lifetime = float(self.sql(f"SELECT extract(epoch FROM expires_at-created_at) FROM finance_app.invitations WHERE id='{invite['id']}';"))
        self.assertAlmostEqual(lifetime, 72 * 60 * 60, delta=1)
        self.denied("accept_invite", token, user=OUTSIDER, email=EMAILS[INVITEE])
        self.sql(f"UPDATE auth.users SET email_confirmed_at=NULL WHERE id='{INVITEE}';")
        self.denied("accept_invite", token, user=INVITEE)
        self.sql(f"UPDATE auth.users SET email_confirmed_at=now() WHERE id='{INVITEE}';")
        self.rpc("accept_invite", token, user=INVITEE)
        self.assertEqual(self.rpc("get_household", self.house, user=INVITEE)["role"], "editor")
        self.rpc("remove_member", self.house, INVITEE)
        # Replay may return an acknowledgement or fail, but cannot recreate access.
        self.rpc("accept_invite", token, user=INVITEE, check=False)
        self.assertEqual(self.rpc("list_households", user=INVITEE), [])
        self.assertEqual(self.sql(f"SELECT count(*) FROM finance_app.members WHERE household_id='{self.house}' AND user_id='{INVITEE}';"), "0")

    def test_stale_jwt_email_does_not_accept_and_normalization_preserves_plus_tags(self):
        invite, token, _ = self.invite(email=EMAILS[INVITEE].upper())
        self.sql(f"UPDATE auth.users SET email='changed@example.invalid' WHERE id='{INVITEE}';")
        self.denied("accept_invite", token, user=INVITEE, email=EMAILS[INVITEE])
        self.sql(f"UPDATE auth.users SET email='invitee+tag@example.invalid' WHERE id='{INVITEE}';")
        self.denied("accept_invite", token, user=INVITEE, email=EMAILS[INVITEE])
        self.sql(f"UPDATE auth.users SET email='{EMAILS[INVITEE]}' WHERE id='{INVITEE}';")
        self.rpc("accept_invite", token, user=INVITEE, email="stale@example.invalid")
        self.assertEqual(self.rpc("get_household", self.house, user=INVITEE)["role"], "viewer")

    def test_invite_creation_retry_is_idempotent_and_rejects_owner_role(self):
        invite, token, request = self.invite()
        same = self.rpc("create_invite", self.house, EMAILS[INVITEE], "viewer", request,
                        hashlib.sha256(token.encode()).hexdigest())
        self.assertEqual(same["id"], invite["id"])
        self.assertEqual(self.sql(f"SELECT count(*) FROM finance_app.invitations WHERE household_id='{self.house}';"), "1")
        self.assertEqual(self.sql("SELECT count(*) FROM finance_app.mail_jobs;"), "1")
        self.denied("create_invite", self.house, EMAILS[INVITEE], "owner", str(uuid.uuid4()), "a" * 64)
        self.denied("create_invite", self.house, EMAILS[INVITEE], "member", str(uuid.uuid4()), "a" * 64)

    def test_invite_recipient_and_actor_caps_span_households(self):
        second = self.rpc("create_household", "Fictional family C", "UTC", str(uuid.uuid4()))["id"]
        for number in range(5):
            self.invite(email="budgeted@example.invalid", token=f"{number:064x}")
        self.denied("create_invite", second, "budgeted@example.invalid", "viewer", str(uuid.uuid4()), "f" * 64)
        # Distinct recipients cannot bypass the actor budget by switching families.
        self.sql(f"""INSERT INTO finance_app.invitations(household_id,email,role,created_by,request_id,token_hash)
            SELECT '{self.house}', 'recipient-'||n||'@example.invalid','viewer','{USER}',gen_random_uuid(),
              encode(sha256(convert_to(n::text,'UTF8')),'hex') FROM generate_series(1,25) n;""")
        self.denied("create_invite", second, "another@example.invalid", "viewer", str(uuid.uuid4()), "e" * 64)

    def test_removing_member_revokes_all_previously_pending_invitations_for_address(self):
        accepted, first_token, _ = self.invite()
        pending, second_token, _ = self.invite(role="editor")
        self.rpc("accept_invite", first_token, user=INVITEE)
        self.rpc("remove_member", self.house, INVITEE)
        self.denied("accept_invite", second_token, user=INVITEE)
        self.assertEqual(self.sql(f"SELECT status FROM finance_app.invitations WHERE id='{pending['id']}';"), "revoked")
        self.assertEqual(self.sql(f"SELECT status FROM finance_app.mail_jobs WHERE invite_id='{pending['id']}';"), "cancelled")
        self.assertEqual(self.rpc("list_households", user=INVITEE), [])

    def test_mail_worker_leases_are_exclusive_scoped_and_acknowledged_by_lease(self):
        invite, token, request = self.invite()
        worker = str(uuid.uuid4())
        self.denied("claim_mail_jobs", worker, 10)
        self.denied("claim_mail_jobs", worker, 10, role="anon")
        jobs = self.rpc("claim_mail_jobs", worker, 10, role="service_role", user="")
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job["household_id"], self.house)
        self.assertEqual(job["email"], EMAILS[INVITEE])
        self.assertEqual(job["token_hash"], hashlib.sha256(token.encode()).hexdigest())
        encoded = json.dumps(job)
        self.assertNotIn(token, encoded)
        for forbidden in ("data", "entries", "financial_state"):
            self.assertNotIn(forbidden, job)
        self.assertEqual(self.rpc("claim_mail_jobs", str(uuid.uuid4()), 10, role="service_role", user=""), [])
        stale = self.rpc("finish_mail_job", job["job_id"], str(uuid.uuid4()), True, None,
                         role="service_role", user="")
        self.assertEqual(stale["status"], "stale")
        self.denied("finish_mail_job", job["job_id"], job["lease_id"], True, None)
        finished = self.rpc("finish_mail_job", job["job_id"], job["lease_id"], True, None,
                            role="service_role", user="")
        self.assertEqual(finished["status"], "sent")
        self.assertEqual(self.rpc("claim_mail_jobs", str(uuid.uuid4()), 10, role="service_role", user=""), [])

    def test_worker_reclaims_expired_leases_and_limits_delivery_attempts(self):
        self.invite()
        first = self.rpc("claim_mail_jobs", str(uuid.uuid4()), 10, role="service_role", user="")[0]
        self.sql(f"UPDATE finance_app.mail_jobs SET lease_until=now()-interval '1 second' WHERE id='{first['job_id']}';")
        second = self.rpc("claim_mail_jobs", str(uuid.uuid4()), 10, role="service_role", user="")[0]
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertNotEqual(first["lease_id"], second["lease_id"])
        stale = self.rpc("finish_mail_job", first["job_id"], first["lease_id"], True, None,
                         role="service_role", user="")
        self.assertEqual(stale["status"], "stale")
        current = second
        for attempt in range(2, 6):
            result = self.rpc("finish_mail_job", current["job_id"], current["lease_id"], False, "provider_unavailable",
                              role="service_role", user="")
            self.assertEqual(result["status"], "failed" if attempt == 5 else "retry")
            if attempt < 5:
                self.sql(f"UPDATE finance_app.mail_jobs SET available_at=now()-interval '1 second' WHERE id='{current['job_id']}';")
                current = self.rpc("claim_mail_jobs", str(uuid.uuid4()), 10, role="service_role", user="")[0]
        self.assertEqual(self.rpc("claim_mail_jobs", str(uuid.uuid4()), 10, role="service_role", user=""), [])
        self.assertEqual(self.sql(f"SELECT attempts FROM finance_app.mail_jobs WHERE id='{first['job_id']}';"), "5")

    def test_worker_does_not_deliver_revoked_invitation_or_store_raw_provider_errors(self):
        invite, token, request = self.invite()
        job = self.rpc("claim_mail_jobs", str(uuid.uuid4()), 10, role="service_role", user="")[0]
        rejected = self.rpc("finish_mail_job", job["job_id"], job["lease_id"], False,
                            "SMTP failure for invitee@example.invalid token=" + token,
                            role="service_role", user="", check=False)
        self.assertNotEqual(rejected.returncode, 0)
        self.rpc("revoke_invite", self.house, invite["id"])
        stale = self.rpc("finish_mail_job", job["job_id"], job["lease_id"], True, None,
                         role="service_role", user="")
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(self.rpc("claim_mail_jobs", str(uuid.uuid4()), 10, role="service_role", user=""), [])
        stored = self.sql("SELECT jsonb_agg(to_jsonb(j)) FROM finance_app.mail_jobs j;")
        self.assertNotIn(token, stored)
        self.assertNotIn(EMAILS[INVITEE], stored)

    def test_accepting_invitation_does_not_upgrade_existing_member(self):
        invite, token, _ = self.invite(email=EMAILS[VIEWER], role="editor")
        self.rpc("accept_invite", token, user=VIEWER)
        self.assertEqual(self.rpc("get_household", self.house, user=VIEWER)["role"], "viewer")
        self.assertEqual(self.sql(f"SELECT count(*) FROM finance_app.members WHERE household_id='{self.house}' AND user_id='{VIEWER}';"), "1")

    def test_expired_revoked_invites_and_no_longer_owner_inviter_cannot_be_accepted(self):
        first, first_token, _ = self.invite()
        self.sql(f"UPDATE finance_app.invitations SET expires_at=now()-interval '1 second' WHERE id='{first['id']}';")
        self.denied("accept_invite", first_token, user=INVITEE)
        second, second_token, _ = self.invite()
        self.rpc("revoke_invite", self.house, second["id"])
        self.denied("accept_invite", second_token, user=INVITEE)
        third, third_token, _ = self.invite()
        self.sql(f"UPDATE finance_app.members SET role='owner' WHERE household_id='{self.house}' AND user_id='{EDITOR}';")
        self.rpc("set_member_role", self.house, USER, "editor", user=EDITOR)
        self.denied("accept_invite", third_token, user=INVITEE)
        self.assertEqual(self.rpc("list_households", user=INVITEE), [])

    def test_concurrent_accept_has_one_membership_and_replay_cannot_restore_revocation(self):
        invite, token, _ = self.invite(role="editor")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(lambda _: self.rpc("accept_invite", token, user=INVITEE, check=False), (1, 2)))
        self.assertTrue(any(r.returncode == 0 for r in rows))
        self.assertEqual(self.sql(f"SELECT count(*) FROM finance_app.members WHERE household_id='{self.house}' AND user_id='{INVITEE}';"), "1")
        self.rpc("remove_member", self.house, INVITEE)
        self.rpc("accept_invite", token, user=INVITEE, check=False)
        self.denied("read_state", self.house, user=INVITEE)

    def test_accept_revoke_race_is_atomic(self):
        invite, token, _ = self.invite()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.rpc, "accept_invite", token, user=INVITEE, check=False),
                       pool.submit(self.rpc, "revoke_invite", self.house, invite["id"], check=False)]
            results = [f.result() for f in futures]
        self.assertTrue(any(r.returncode == 0 for r in results))
        count = self.sql(f"SELECT count(*) FROM finance_app.members WHERE household_id='{self.house}' AND user_id='{INVITEE}';")
        status = self.sql(f"SELECT status FROM finance_app.invitations WHERE id='{invite['id']}';")
        self.assertIn((status, count), (("accepted", "1"), ("revoked", "0")))

    def test_concurrent_owner_removal_cannot_remove_last_owner(self):
        self.sql(f"UPDATE finance_app.members SET role='owner' WHERE household_id='{self.house}' AND user_id='{EDITOR}';")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.rpc, "remove_member", self.house, EDITOR, user=USER, check=False),
                       pool.submit(self.rpc, "remove_member", self.house, USER, user=EDITOR, check=False)]
            results = [f.result() for f in futures]
        self.assertEqual(sum(r.returncode == 0 for r in results), 1)
        self.assertEqual(self.sql(f"SELECT count(*) FROM finance_app.members WHERE household_id='{self.house}' AND role='owner';"), "1")

    def test_concurrent_owner_demotion_cannot_demote_last_owner(self):
        self.sql(f"UPDATE finance_app.members SET role='owner' WHERE household_id='{self.house}' AND user_id='{EDITOR}';")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.rpc, "set_member_role", self.house, EDITOR, "viewer", user=USER, check=False),
                       pool.submit(self.rpc, "set_member_role", self.house, USER, "viewer", user=EDITOR, check=False)]
            results = [f.result() for f in futures]
        self.assertEqual(sum(r.returncode == 0 for r in results), 1)
        self.assertEqual(self.sql(f"SELECT count(*) FROM finance_app.members WHERE household_id='{self.house}' AND role='owner';"), "1")


if __name__ == "__main__":
    unittest.main()

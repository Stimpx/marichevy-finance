"""Production-catalog-shaped permission reproductions, local fictional DB only.

No production connections/rows are used. auth.uid() is a local stand-in; the
membership function models the separately reviewed production SELECT EXISTS.
These tests establish PostgreSQL behavior, not reachable PostgREST endpoints.
"""
import json
from pathlib import Path
import unittest

import test_sync_database as database

ROOT = Path(__file__).resolve().parents[1]
HOUSE, OTHER = database.HOUSE, database.OTHER
USER, OUTSIDER = database.USER, database.OUTSIDER
PARTNER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
REQUEST = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
HARDENING = (ROOT / "server/002_restrict_table_capabilities.sql").read_text()
BOUND_LOOKUP = (ROOT / "server/003_bound_membership_lookup.sql").read_text()
TABLES = ("family_state", "households", "household_members", "family_chore_deliveries")


class ProductionPermissions(unittest.TestCase):
    docker = classmethod(database.SyncDatabaseTests.docker.__func__)
    sql = classmethod(database.SyncDatabaseTests.sql.__func__)

    @classmethod
    def as_user(cls, query, user=USER, check=True, role="authenticated"):
        return database.SyncDatabaseTests.as_user.__func__(cls,
            f"SET request.jwt.claim.role = {database.literal(role)};\n" + query,
            user=user, check=check, role=role)

    @classmethod
    def setUpClass(cls):
        database.SyncDatabaseTests.setUpClass.__func__(cls)
        cls.sql("CREATE ROLE service_role BYPASSRLS; CREATE ROLE permission_fixture_inherited;", database="postgres")

    def setUp(self):
        # Every DROP/TRUNCATE in this module targets the private, networkless,
        # disposable sync_fictional DB created by the shared test helper.
        self.sql("""
DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;
DROP SCHEMA IF EXISTS auth CASCADE; CREATE SCHEMA auth;
REVOKE permission_fixture_inherited FROM anon, authenticated;
GRANT USAGE ON SCHEMA public, auth TO authenticated, anon, service_role;
CREATE TABLE auth.users(id uuid PRIMARY KEY);
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
  $$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
CREATE FUNCTION auth.role() RETURNS text LANGUAGE sql STABLE AS
  $$ SELECT nullif(current_setting('request.jwt.claim.role', true), '') $$;
CREATE TABLE public.households (
  id uuid PRIMARY KEY, name text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE public.household_members (
  household_id uuid NOT NULL REFERENCES public.households(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'member', created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(household_id,user_id));
CREATE TABLE public.family_state (
  household_id uuid PRIMARY KEY REFERENCES public.households(id) ON DELETE CASCADE,
  data jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by uuid REFERENCES auth.users(id));
CREATE TABLE public.family_chore_deliveries (
  household_id uuid NOT NULL, chore_id text NOT NULL, due_date date NOT NULL,
  chat_id text NOT NULL, status text NOT NULL DEFAULT 'fixture-pending',
  attempts integer NOT NULL DEFAULT 0, last_attempt_at timestamptz,
  sent_at timestamptz, telegram_message_id bigint, last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(household_id,chore_id,due_date,chat_id));
-- Local recreation of separately reviewed SELECT EXISTS metadata; the hosted
-- auth.uid() implementation/platform role graph are not reproduced here.
CREATE FUNCTION public.is_household_member(p_household_id uuid, p_user_id uuid)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = public
AS $$ SELECT EXISTS (SELECT 1 FROM public.household_members hm
  WHERE hm.household_id = p_household_id AND hm.user_id = p_user_id); $$;
ALTER TABLE public.family_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.household_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.households ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.family_chore_deliveries ENABLE ROW LEVEL SECURITY;
CREATE POLICY "members can insert family state" ON public.family_state
  FOR INSERT TO authenticated
  WITH CHECK (public.is_household_member(household_id, auth.uid()));
CREATE POLICY "members can read family state" ON public.family_state
  FOR SELECT TO authenticated
  USING (public.is_household_member(household_id, auth.uid()));
CREATE POLICY "members can update family state" ON public.family_state
  FOR UPDATE TO authenticated
  USING (public.is_household_member(household_id, auth.uid()))
  WITH CHECK (public.is_household_member(household_id, auth.uid()));
CREATE POLICY "members can view family members" ON public.household_members
  FOR SELECT TO authenticated
  USING (public.is_household_member(household_id, auth.uid()));
CREATE POLICY "members can view their households" ON public.households
  FOR SELECT TO authenticated USING (public.is_household_member(id, auth.uid()));
GRANT SELECT, INSERT, UPDATE, DELETE ON public.family_state,
  public.household_members, public.households TO authenticated;
GRANT TRUNCATE, TRIGGER ON public.family_state, public.household_members,
  public.households TO anon, authenticated;
GRANT SELECT ON public.family_state TO service_role;
GRANT SELECT, INSERT, UPDATE ON public.family_chore_deliveries TO service_role;
GRANT TRUNCATE, TRIGGER ON public.family_state, public.household_members,
  public.households, public.family_chore_deliveries TO service_role;
""" + f"""
INSERT INTO auth.users VALUES ('{USER}'), ('{PARTNER}'), ('{OUTSIDER}');
INSERT INTO public.households(id,name) VALUES ('{HOUSE}','fictional-one'),
  ('{OTHER}','fictional-two');
INSERT INTO public.household_members(household_id,user_id) VALUES
  ('{HOUSE}','{USER}'), ('{HOUSE}','{PARTNER}'), ('{OTHER}','{OUTSIDER}');
INSERT INTO public.family_state(household_id,data) VALUES
  ('{HOUSE}','{{"fixture":"one","unknown":{{"preserve":[1,null,true]}}}}'),
  ('{OTHER}','{{"fixture":"two"}}');
INSERT INTO public.family_chore_deliveries(household_id,chore_id,due_date,chat_id)
  VALUES ('{HOUSE}','fictional-chore','2026-10-23','fictional-chat');
""")

    def migrate_and_activate(self):
        self.sql((ROOT / "server/001_family_state_cas.sql").read_text())
        self.sql("UPDATE public.family_state SET sync_protocol=2;")

    def contents(self):
        return self.sql("SELECT jsonb_agg(data ORDER BY household_id) FROM public.family_state;")

    def all_rows(self):
        return {table: self.sql(f"SELECT jsonb_agg(to_jsonb(r) ORDER BY to_jsonb(r)::text) FROM public.{table} r;") for table in TABLES}

    def retained_metadata(self):
        return self.sql("""
SELECT jsonb_build_object(
  'policies',(SELECT jsonb_agg(to_jsonb(p) ORDER BY tablename,policyname)
    FROM pg_policies p WHERE schemaname='public'),
  'constraints',(SELECT jsonb_agg(pg_get_constraintdef(oid) ORDER BY conrelid,conname)
    FROM pg_constraint WHERE connamespace='public'::regnamespace),
  'crud',(SELECT jsonb_agg(jsonb_build_array(r,t,p,has_table_privilege(r,'public.'||t,p))
    ORDER BY r,t,p) FROM unnest(ARRAY['anon','authenticated','service_role']) r,
      unnest(ARRAY['family_state','households','household_members','family_chore_deliveries']) t,
      unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) p),
  'service_capabilities',(SELECT jsonb_agg(jsonb_build_array(t,p,has_table_privilege('service_role','public.'||t,p))
    ORDER BY t,p) FROM unnest(ARRAY['family_state','households','household_members','family_chore_deliveries']) t,
      unnest(ARRAY['TRUNCATE','TRIGGER']) p),
  'rls',(SELECT jsonb_agg(jsonb_build_array(relname,relrowsecurity,relforcerowsecurity)
    ORDER BY relname) FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r'));
""")

    def cas(self, user=USER, house=HOUSE):
        return json.loads(self.as_user(
            f"SELECT public.family_state_cas('{house}',1,'{{\"fixture\":\"changed\"}}','{REQUEST}');",
            user=user))

    def lookup_metadata(self):
        return self.sql("SELECT jsonb_build_array(prosrc,proconfig,proacl,proargnames,provolatile,prosecdef,pg_get_userbyid(proowner)) FROM pg_proc WHERE oid='public.is_household_member(uuid,uuid)'::regprocedure;")

    def probe(self, house, user_id, *, user=USER, role="authenticated", check=True):
        return self.as_user(f"SELECT public.is_household_member('{house}',{database.literal(user_id)}::uuid);",
                            user=user, role=role, check=check)

    def test_cas_migration_accepts_not_null_and_foreign_keys_without_replacing_json(self):
        before = self.contents()
        self.migrate_and_activate()
        self.assertEqual(self.contents(), before)
        self.assertEqual(self.sql("SELECT count(*) FROM pg_constraint WHERE conrelid='public.family_state'::regclass AND contype='f';"), "2")
        self.assertEqual(self.sql("SELECT attnotnull FROM pg_attribute WHERE attrelid='public.family_state'::regclass AND attname='updated_at';"), "t")
        self.assertEqual(self.cas(user=PARTNER)["status"], "written")
        self.assertEqual(self.cas(user=OUTSIDER)["status"], "not_found")
        self.assertEqual(self.sql(f"SELECT updated_by FROM public.family_state WHERE household_id='{HOUSE}';"), PARTNER)
        self.assertEqual(self.as_user("SELECT count(*) FROM public.household_members;"), "2")

    def test_production_shaped_delete_has_no_policy_and_cannot_reach_row_guard(self):
        self.migrate_and_activate()
        before = self.contents()
        # Unlike an ALL-policy fixture, the production catalog has no DELETE
        # policy: no visible DELETE rows, so there is no PT409 row-trigger error.
        self.assertEqual(self.as_user(f"DELETE FROM public.family_state WHERE household_id='{HOUSE}' RETURNING household_id;"), "")
        self.assertEqual(self.contents(), before)

    def test_broad_membership_dml_grants_do_not_allow_self_enrollment_or_mutation(self):
        before = self.sql("SELECT jsonb_agg(to_jsonb(m) ORDER BY household_id,user_id) FROM public.household_members m;")
        denied = self.as_user(f"INSERT INTO public.household_members(household_id,user_id) VALUES ('{OTHER}','{USER}');", check=False)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("row-level security", denied.stderr)
        self.assertEqual(self.as_user("UPDATE public.household_members SET role='owner' RETURNING user_id;"), "")
        self.assertEqual(self.as_user("DELETE FROM public.household_members RETURNING user_id;"), "")
        self.assertEqual(self.sql("SELECT jsonb_agg(to_jsonb(m) ORDER BY household_id,user_id) FROM public.household_members m;"), before)

    def test_capability_only_migration_does_not_remove_boolean_membership_oracle(self):
        probe = f"SELECT public.is_household_member('{OTHER}','{OUTSIDER}');"
        self.assertEqual(self.as_user(probe, role="anon"), "t")
        self.assertEqual(self.as_user(probe), "t")
        self.assertEqual(self.as_user(f"SELECT household_id FROM public.family_state WHERE household_id='{OTHER}';"), "")
        self.sql(HARDENING)
        # 002 deliberately does not rewrite an existing helper/its callers.
        self.assertEqual(self.as_user(probe, role="anon"), "t")

    def test_anon_sql_truncate_bypasses_select_denial_rls_and_active_cas_row_guard(self):
        self.migrate_and_activate()
        denied = self.as_user("SELECT * FROM public.family_state;", role="anon", check=False)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("permission denied", denied.stderr)
        # This is direct SQL in a disposable DB, never an HTTP/prod operation.
        self.as_user("TRUNCATE public.family_state;", role="anon")
        self.assertEqual(self.sql("SELECT count(*) FROM public.family_state;"), "0")

    def test_authenticated_sql_truncate_cascade_erases_other_families_too(self):
        self.migrate_and_activate()
        self.assertEqual(self.as_user("SELECT count(*) FROM public.households;"), "1")
        self.as_user("TRUNCATE public.households CASCADE;")
        self.assertEqual(self.sql("SELECT (SELECT count(*) FROM public.households) + (SELECT count(*) FROM public.household_members) + (SELECT count(*) FROM public.family_state);"), "0")

    def test_hardening_removes_direct_and_public_ddl_grants_preserves_cas_and_json(self):
        self.migrate_and_activate()
        # PUBLIC inheritance must also be removed, even if grants in the observed
        # snapshot are direct. This covers future/default privilege drift.
        self.sql("GRANT TRUNCATE, TRIGGER ON public.family_state, public.household_members, public.households, public.family_chore_deliveries TO PUBLIC;")
        before = self.all_rows()
        metadata = self.retained_metadata()
        self.sql(HARDENING)
        self.sql(HARDENING)  # Safe repeat requires no reset or data replacement.
        for role in ("anon", "authenticated"):
            for table in TABLES:
                with self.subTest(role=role, table=table):
                    denied = self.as_user(f"TRUNCATE public.{table} CASCADE;", role=role, check=False)
                    self.assertNotEqual(denied.returncode, 0)
                    self.assertIn("permission denied", denied.stderr)
                    self.assertEqual(self.sql(f"SELECT has_table_privilege('{role}','public.{table}','TRUNCATE') OR has_table_privilege('{role}','public.{table}','TRIGGER');"), "f")
        self.assertEqual(self.all_rows(), before)
        self.assertEqual(self.retained_metadata(), metadata)
        self.assertEqual(self.cas(user=PARTNER)["status"], "written")
        self.assertEqual(self.cas(user=OUTSIDER)["status"], "not_found")
        self.as_user("UPDATE public.family_chore_deliveries SET attempts=attempts+1;", role="service_role")
        self.assertEqual(self.as_user("SELECT attempts FROM public.family_chore_deliveries;", role="service_role"), "1")
        self.as_user(f"INSERT INTO public.family_chore_deliveries(household_id,chore_id,due_date,chat_id) VALUES ('{OTHER}','fictional-second','2026-10-23','fictional-chat');", role="service_role")
        self.assertEqual(self.as_user("SELECT count(*) FROM public.family_chore_deliveries;", role="service_role"), "2")

    def test_hardening_rolls_back_all_revokes_if_inherited_capability_remains(self):
        self.sql("GRANT TRUNCATE ON public.family_state TO permission_fixture_inherited; GRANT permission_fixture_inherited TO anon;")
        before = self.all_rows()
        result = self.sql(HARDENING, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("review inherited privileges", result.stderr)
        self.assertEqual(self.all_rows(), before)
        # A later table's direct rights would already have been revoked without
        # transaction rollback; verify the whole operation was atomic.
        self.assertEqual(self.sql("SELECT has_table_privilege('authenticated','public.households','TRIGGER');"), "t")

    def test_hardening_denies_actual_trigger_ddl_after_removing_table_capability(self):
        self.sql("CREATE FUNCTION public.permission_fixture_noop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;")
        create = "CREATE TRIGGER permission_fixture_noop BEFORE UPDATE ON public.households FOR EACH ROW EXECUTE FUNCTION public.permission_fixture_noop();"
        self.as_user(create, role="anon")
        self.sql("DROP TRIGGER permission_fixture_noop ON public.households;")
        self.sql(HARDENING)
        for role in ("anon", "authenticated"):
            denied = self.as_user(create, role=role, check=False)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("permission denied for table households", denied.stderr)

    def test_hardening_refuses_changed_rls_before_altering_any_grant(self):
        self.sql("ALTER TABLE public.household_members DISABLE ROW LEVEL SECURITY;")
        before = self.all_rows()
        result = self.sql(HARDENING, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("with RLS enabled", result.stderr)
        self.assertEqual(self.all_rows(), before)
        self.assertEqual(self.sql("SELECT has_table_privilege('anon','public.family_state','TRUNCATE');"), "t")

    def test_hardening_requires_owner_and_all_four_observed_tables(self):
        denied = self.as_user(HARDENING, check=False)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("Expected postgres table owner", denied.stderr)
        self.sql("DROP TABLE public.family_chore_deliveries;")
        result = self.sql(HARDENING, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("family_chore_deliveries", result.stderr)
        self.assertEqual(self.sql("SELECT has_table_privilege('anon','public.family_state','TRUNCATE');"), "t")

    def test_hardening_refuses_unexpected_table_owner(self):
        self.sql("ALTER TABLE public.households OWNER TO authenticated;")
        before = self.all_rows()
        result = self.sql(HARDENING, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("owned by postgres", result.stderr)
        self.assertEqual(self.all_rows(), before)
        self.assertEqual(self.sql("SELECT has_table_privilege('anon','public.family_state','TRUNCATE');"), "t")

    def test_bound_lookup_keeps_policy_reads_cas_and_service_role_without_uid(self):
        self.migrate_and_activate()
        self.sql(HARDENING)
        self.sql(BOUND_LOOKUP)
        self.assertEqual(self.probe(HOUSE, USER), "t")
        self.assertEqual(self.probe(OTHER, USER), "f")
        self.assertEqual(self.probe(HOUSE, PARTNER), "f")
        self.assertEqual(self.probe(OTHER, OUTSIDER), "f")
        self.assertEqual(self.probe(HOUSE, USER, user=""), "f")
        self.assertEqual(self.probe(HOUSE, USER, user="", role="service_role"), "t")
        self.assertEqual(self.probe(OTHER, OUTSIDER, user="", role="service_role"), "t")
        self.assertEqual(self.probe(OTHER, USER, user="", role="service_role"), "f")
        denied = self.probe(HOUSE, USER, user="", role="anon", check=False)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("permission denied for function is_household_member", denied.stderr)
        self.assertEqual(self.as_user("SELECT household_id FROM public.family_state;"), HOUSE)
        self.assertEqual(self.as_user("SELECT count(*) FROM public.household_members;"), "2")
        self.assertEqual(self.as_user("SELECT id FROM public.households;"), HOUSE)
        self.assertEqual(self.as_user("SELECT household_id FROM public.family_state;", user=OUTSIDER), OTHER)
        self.assertEqual(self.cas(user=PARTNER)["status"], "written")
        self.assertEqual(self.cas(user=OUTSIDER)["status"], "not_found")

    def test_bound_lookup_repeat_preserves_rows_revisions_policies_and_other_grants(self):
        self.migrate_and_activate()
        self.sql(HARDENING)
        before = self.all_rows()
        metadata = self.retained_metadata()
        self.sql(BOUND_LOOKUP)
        helper = self.lookup_metadata()
        self.sql(BOUND_LOOKUP)
        self.assertEqual(self.lookup_metadata(), helper)
        self.assertEqual(self.all_rows(), before)
        self.assertEqual(self.retained_metadata(), metadata)
        self.assertEqual(self.sql("SELECT jsonb_build_array(prosecdef,provolatile,pg_get_userbyid(proowner),proconfig,proargnames) FROM pg_proc WHERE oid='public.is_household_member(uuid,uuid)'::regprocedure;"),
                         '[true, "v", "postgres", ["search_path=pg_catalog, public"], ["p_household_id", "p_user_id"]]')

    def test_bound_lookup_unrecognized_source_fails_without_partial_acl_change(self):
        self.sql("CREATE OR REPLACE FUNCTION public.is_household_member(p_household_id uuid,p_user_id uuid) RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=public AS $$ SELECT true; $$;")
        before = self.lookup_metadata()
        rows = self.all_rows()
        result = self.sql(BOUND_LOOKUP, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source/search_path differs", result.stderr)
        self.assertEqual(self.lookup_metadata(), before)
        self.assertEqual(self.all_rows(), rows)

    def test_bound_lookup_unknown_overload_or_policy_fails_closed(self):
        self.sql("CREATE FUNCTION public.is_household_member(uuid) RETURNS boolean LANGUAGE sql AS $$ SELECT true $$;")
        before = self.lookup_metadata()
        result = self.sql(BOUND_LOOKUP, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reviewed membership lookup overload", result.stderr)
        self.assertEqual(self.lookup_metadata(), before)
        self.sql("DROP FUNCTION public.is_household_member(uuid); CREATE POLICY unexpected_policy ON public.family_state FOR SELECT TO authenticated USING (true);")
        result = self.sql(BOUND_LOOKUP, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("five-policy catalog", result.stderr)
        self.assertEqual(self.lookup_metadata(), before)

    def test_bound_lookup_unsupported_security_attributes_fail_closed(self):
        alterations = [("STABLE", "VOLATILE"), ("SECURITY INVOKER", "SECURITY DEFINER"),
                       ("SET search_path=pg_catalog,public", "SET search_path=public")]
        for change, restore in alterations:
            with self.subTest(change=change):
                self.sql("ALTER FUNCTION public.is_household_member(uuid,uuid) " + change + ";")
                before = self.lookup_metadata()
                result = self.sql(BOUND_LOOKUP, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.lookup_metadata(), before)
                self.sql("ALTER FUNCTION public.is_household_member(uuid,uuid) " + restore + ";")

    def test_bound_lookup_inherited_anonymous_execute_rolls_back_source_and_grants(self):
        self.sql("GRANT EXECUTE ON FUNCTION public.is_household_member(uuid,uuid) TO permission_fixture_inherited; GRANT permission_fixture_inherited TO anon;")
        before = self.lookup_metadata()
        rows = self.all_rows()
        result = self.sql(BOUND_LOOKUP, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("review inherited privileges", result.stderr)
        self.assertEqual(self.lookup_metadata(), before)
        self.assertEqual(self.all_rows(), rows)
        self.assertEqual(self.probe(OTHER, OUTSIDER, role="anon"), "t")


if __name__ == "__main__":
    unittest.main()

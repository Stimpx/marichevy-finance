"""New staging bootstrap guards/RLS against disposable local PostgreSQL only.

The delivered SQL does not mock Supabase auth. This test database creates a tiny
local auth stand-in explicitly; no hosted API or real credentials are involved.
"""
from pathlib import Path
import unittest

import test_sync_database as database

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'iqpoxphtvtogjowruufe'
HOUSE = database.HOUSE
OTHER = database.OTHER
USER = database.USER
OUTSIDER = database.OUTSIDER
PARTNER = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
BOOTSTRAP = (ROOT / 'server/staging_fixture.sql').read_text()


class StagingFixture(unittest.TestCase):
    docker = classmethod(database.SyncDatabaseTests.docker.__func__)
    sql = classmethod(database.SyncDatabaseTests.sql.__func__)
    as_user = classmethod(database.SyncDatabaseTests.as_user.__func__)

    @classmethod
    def setUpClass(cls):
        database.SyncDatabaseTests.setUpClass.__func__(cls)

    def setUp(self):
        # Destructive commands belong only to this already isolated test DB.
        self.sql('''
DROP SCHEMA IF EXISTS marichevy_staging CASCADE;
DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;
DROP SCHEMA IF EXISTS auth CASCADE; CREATE SCHEMA auth;
GRANT USAGE ON SCHEMA auth TO authenticated, anon;
CREATE TABLE auth.users (id uuid PRIMARY KEY);
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
  $$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
''')

    def bootstrap(self, project=PROJECT, check=True):
        return self.sql("BEGIN; SET LOCAL marichevy.staging_project_ref = '" + project + "';\n" + BOOTSTRAP + "\nCOMMIT;", check=check)

    def seed(self):
        self.sql(f"""
INSERT INTO auth.users VALUES ('{USER}'), ('{PARTNER}'), ('{OUTSIDER}');
INSERT INTO public.staging_membership VALUES
  ('{HOUSE}', '{USER}'), ('{HOUSE}', '{PARTNER}'), ('{OTHER}', '{OUTSIDER}');
INSERT INTO public.family_state (household_id, data) VALUES
  ('{HOUSE}', '{{"fixture":"one","entries":[]}}'),
  ('{OTHER}', '{{"fixture":"two","entries":[]}}');
""")

    def test_missing_or_wrong_project_guard_creates_nothing(self):
        for query in ["BEGIN;" + BOOTSTRAP + "COMMIT;", "BEGIN; SET LOCAL marichevy.staging_project_ref = 'wrong';\n" + BOOTSTRAP + "COMMIT;"]:
            result = self.sql(query, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('identity guard', result.stderr)
            self.assertEqual(self.sql("SELECT to_regclass('public.family_state') IS NULL;"), 't')
            self.assertEqual(self.sql("SELECT to_regnamespace('marichevy_staging') IS NULL;"), 't')

    def test_existing_table_data_are_preserved_and_bootstrap_refuses(self):
        self.sql("CREATE TABLE public.keep_me (value text); INSERT INTO public.keep_me VALUES ('unchanged');")
        result = self.bootstrap(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('empty public schema', result.stderr)
        self.assertEqual(self.sql('SELECT value FROM public.keep_me;'), 'unchanged')
        self.assertEqual(self.sql("SELECT to_regclass('public.family_state') IS NULL;"), 't')

    def test_second_application_refuses_without_replacing_rows(self):
        self.bootstrap(); self.seed()
        before = self.sql('SELECT jsonb_agg(to_jsonb(f) ORDER BY household_id) FROM public.family_state f;')
        result = self.bootstrap(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already exists', result.stderr)
        self.assertEqual(self.sql('SELECT jsonb_agg(to_jsonb(f) ORDER BY household_id) FROM public.family_state f;'), before)

    def test_two_members_share_only_their_household_and_cannot_mutate_membership(self):
        self.bootstrap(); self.seed()
        for user in (USER, PARTNER):
            self.assertEqual(self.as_user('SELECT household_id FROM public.family_state;', user=user), HOUSE)
            self.assertEqual(self.as_user('SELECT user_id FROM public.staging_membership;', user=user), user)
            self.assertEqual(self.as_user(f"UPDATE public.family_state SET data='{{\"own\":true}}' WHERE household_id='{HOUSE}' RETURNING household_id;", user=user), HOUSE)
            self.assertEqual(self.as_user(f"UPDATE public.family_state SET data='{{}}' WHERE household_id='{OTHER}' RETURNING household_id;", user=user), '')
            denied = self.as_user(f"INSERT INTO public.staging_membership VALUES ('{OTHER}','{user}');", user=user, check=False)
            self.assertNotEqual(denied.returncode, 0)
            denied = self.as_user(f"UPDATE public.staging_membership SET household_id='{OTHER}';", user=user, check=False)
            self.assertNotEqual(denied.returncode, 0)
        self.assertEqual(self.as_user('SELECT household_id FROM public.family_state;', user=OUTSIDER), OTHER)
        denied = self.as_user(f"INSERT INTO public.family_state(household_id,data) VALUES ('33333333-3333-4333-8333-333333333333','{{}}');", check=False)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('row-level security', denied.stderr)

    def test_anon_cannot_read_or_write_fixture_tables(self):
        self.bootstrap(); self.seed()
        for query in ['SELECT * FROM public.family_state;', 'SELECT * FROM public.staging_membership;',
                      "UPDATE public.family_state SET data='{}';", 'SELECT * FROM marichevy_staging.fixture_registry;']:
            result = self.as_user(query, role='anon', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('permission denied', result.stderr)

    def test_existing_cas_migration_accepts_fixture_and_retains_isolation(self):
        self.bootstrap(); self.seed()
        before = self.sql('SELECT jsonb_agg(data ORDER BY household_id) FROM public.family_state;')
        self.sql((ROOT / 'server/001_family_state_cas.sql').read_text())
        self.assertEqual(self.sql('SELECT jsonb_agg(data ORDER BY household_id) FROM public.family_state;'), before)
        self.sql('UPDATE public.family_state SET sync_protocol=2;')
        request = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
        self.assertIn('"status": "written"', self.as_user(f"SELECT public.family_state_cas('{HOUSE}',1,'{{\"fixture\":\"one\",\"changed\":true}}','{request}');"))
        self.assertIn('"status": "not_found"', self.as_user(f"SELECT public.family_state_cas('{OTHER}',1,'{{}}','{request}');"))
        self.assertEqual(self.as_user('SELECT household_id FROM public.family_state;', user=OUTSIDER), OTHER)


if __name__ == '__main__':
    unittest.main()

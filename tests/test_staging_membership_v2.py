"""Production-shaped membership evolution on a disposable local PostgreSQL.

Auth is explicitly a small local stand-in. These checks never contact Supabase,
read real family data, or establish hosted PostgREST readiness.
"""
import concurrent.futures
import json
from pathlib import Path
import unittest

import test_sync_database as database

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'iqpoxphtvtogjowruufe'
HOUSE, OTHER = database.HOUSE, database.OTHER
USER, OUTSIDER = database.USER, database.OUTSIDER
PARTNER = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
RUN = '1234567890abcdef1234567890abcdef'
BOOTSTRAP = (ROOT / 'server/staging_fixture.sql').read_text()
EVOLUTION = (ROOT / 'server/staging_membership_v2.sql').read_text()


class StagingMembershipV2(unittest.TestCase):
    docker = classmethod(database.SyncDatabaseTests.docker.__func__)
    sql = classmethod(database.SyncDatabaseTests.sql.__func__)
    as_user = classmethod(database.SyncDatabaseTests.as_user.__func__)

    @classmethod
    def setUpClass(cls):
        database.SyncDatabaseTests.setUpClass.__func__(cls)
        cls.sql('CREATE ROLE service_role;')

    def setUp(self):
        # Destructive setup belongs only to this isolated local database.
        self.sql('''
DROP SCHEMA IF EXISTS marichevy_staging CASCADE;
DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;
DROP SCHEMA IF EXISTS auth CASCADE; CREATE SCHEMA auth;
GRANT USAGE ON SCHEMA public,auth TO authenticated,anon,service_role;
CREATE TABLE auth.users(id uuid PRIMARY KEY,email text UNIQUE,raw_app_meta_data jsonb);
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
  $$ SELECT nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
''')
        self.sql("BEGIN;SET LOCAL marichevy.staging_project_ref='" + PROJECT + "';\n" + BOOTSTRAP + '\nCOMMIT;')
        for index, user in enumerate((USER, PARTNER, OUTSIDER)):
            self.sql("INSERT INTO auth.users VALUES (" + database.literal(user) + ','
                     + database.literal('stage-' + RUN + '-' + str(index) + '@example.invalid')
                     + ',' + database.literal(json.dumps({'marichevy_staging_run': RUN})) + ');')
        self.sql(f"""
INSERT INTO public.staging_membership VALUES
  ('{HOUSE}','{USER}'),('{HOUSE}','{PARTNER}'),('{OTHER}','{OUTSIDER}');
INSERT INTO public.family_state(household_id,data) VALUES
  ('{HOUSE}','{{"entries":[{{"id":"fictional-one","amount":1250.50}}],"opaque":{{"preserve":[null,true,42]}}}}'),
  ('{OTHER}','{{"entries":[],"fixture":"second"}}');
""")
        self.sql((ROOT / 'server/001_family_state_cas.sql').read_text())
        self.sql('UPDATE public.family_state SET sync_protocol=2;')

    def evolve(self, project=PROJECT, check=True):
        return self.sql("BEGIN;SET LOCAL marichevy.staging_project_ref=" + database.literal(project)
                        + ';\n' + EVOLUTION + '\nCOMMIT;', check=check)

    def snapshot(self):
        return self.sql('SELECT jsonb_agg(to_jsonb(f) ORDER BY household_id) FROM public.family_state f;')

    def marker(self):
        return self.sql('SELECT fixture_version FROM marichevy_staging.fixture_registry;')

    def assert_not_evolved(self, before):
        self.assertEqual(self.marker(), '1')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.sql("SELECT to_regclass('public.households') IS NULL;"), 't')

    def test_evolution_preserves_every_family_column_and_all_auth_rows(self):
        before = self.snapshot()
        auth_before = self.sql('SELECT jsonb_agg(to_jsonb(u) ORDER BY id) FROM auth.users u;')
        self.evolve()
        self.assertEqual(self.marker(), '2')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.sql('SELECT jsonb_agg(to_jsonb(u) ORDER BY id) FROM auth.users u;'), auth_before)
        self.assertEqual(self.sql('SELECT count(*) FROM public.households;'), '2')
        self.assertEqual(self.sql('SELECT count(*) FROM public.household_members;'), '3')
        self.assertEqual(self.sql('SELECT count(*) FROM public.family_chore_deliveries;'), '0')
        self.assertEqual(self.sql("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r';"), '5')
        self.assertEqual(self.sql("SELECT prosecdef AND provolatile='v' AND proconfig=ARRAY['search_path=public'] FROM pg_proc WHERE oid='public.is_household_member(uuid,uuid)'::regprocedure;"), 't')

    def test_wrong_identity_or_repeat_refuses_without_replacing_snapshots(self):
        before = self.snapshot()
        result = self.evolve(project='wrong', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('identity guard', result.stderr)
        self.assert_not_evolved(before)
        self.evolve()
        result = self.evolve(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.marker(), '2')
        self.assertEqual(self.snapshot(), before)

    def test_unknown_public_schema_refuses_and_keeps_existing_data(self):
        self.sql("CREATE TABLE public.unknown_fixture(value text); INSERT INTO public.unknown_fixture VALUES('keep');")
        before = self.snapshot()
        result = self.evolve(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unexpected public relations', result.stderr)
        self.assert_not_evolved(before)
        self.assertEqual(self.sql('SELECT value FROM public.unknown_fixture;'), 'keep')

    def test_unknown_marker_trigger_refuses_without_invoking_it(self):
        self.sql('''CREATE FUNCTION marichevy_staging.unexpected_marker_trigger()
          RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'UNEXPECTED_TRIGGER_MUST_NOT_RUN'; END $$;
          CREATE TRIGGER unexpected_marker_trigger BEFORE UPDATE ON marichevy_staging.fixture_registry
          FOR EACH ROW EXECUTE FUNCTION marichevy_staging.unexpected_marker_trigger();''')
        before = self.snapshot()
        result = self.evolve(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unexpected fixture provenance', result.stderr)
        self.assertNotIn('UNEXPECTED_TRIGGER_MUST_NOT_RUN', result.stderr)
        self.assert_not_evolved(before)

    def test_unknown_auth_account_or_mismatched_run_refuses_before_ddl(self):
        before = self.snapshot()
        for change in [f"UPDATE auth.users SET email='real-person@example.test' WHERE id='{USER}';",
                       f"UPDATE auth.users SET raw_app_meta_data='{{}}' WHERE id='{USER}';",
                       f"UPDATE auth.users SET raw_app_meta_data=jsonb_build_object('marichevy_staging_run',repeat('a',32)) WHERE id='{USER}';"]:
            self.sql(change)
            result = self.evolve(check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Unknown authentication accounts', result.stderr)
            self.assert_not_evolved(before)
            self.sql("UPDATE auth.users SET email=" + database.literal('stage-' + RUN + '-0@example.invalid')
                     + ',raw_app_meta_data=' + database.literal(json.dumps({'marichevy_staging_run': RUN}))
                     + f" WHERE id='{USER}';")

    def test_unknown_family_shape_or_distribution_refuses_without_touching_rows(self):
        self.sql("ALTER TABLE public.family_state ADD COLUMN unknown text DEFAULT 'keep';")
        before = self.snapshot()
        result = self.evolve(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('reviewed v1 CAS schema', result.stderr)
        self.assert_not_evolved(before)
        self.sql('ALTER TABLE public.family_state DROP COLUMN unknown;')
        self.sql(f"DELETE FROM public.staging_membership WHERE user_id='{PARTNER}';")
        before = self.snapshot()
        result = self.evolve(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('two known fictional families', result.stderr)
        self.assert_not_evolved(before)

    def test_both_members_read_only_their_family_and_cannot_change_membership(self):
        self.evolve()
        for user, house, visible_members in [(USER,HOUSE,2),(PARTNER,HOUSE,2),(OUTSIDER,OTHER,1)]:
            self.assertEqual(self.as_user('SELECT household_id FROM public.family_state;', user=user), house)
            self.assertEqual(self.as_user('SELECT id FROM public.households;', user=user), house)
            self.assertEqual(self.as_user('SELECT count(*) FROM public.household_members;', user=user), str(visible_members))
            denied = self.as_user(f"INSERT INTO public.household_members(household_id,user_id) VALUES('{OTHER}','{USER}');", user=user, check=False)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn('row-level security', denied.stderr)
            self.assertEqual(self.as_user("UPDATE public.household_members SET role='owner' RETURNING user_id;",user=user), '')
            self.assertEqual(self.as_user('DELETE FROM public.household_members RETURNING user_id;',user=user), '')
            self.assertEqual(self.as_user("UPDATE public.households SET name='unauthorized' RETURNING id;",user=user), '')
            self.assertEqual(self.as_user('DELETE FROM public.households RETURNING id;',user=user), '')
        for table in ('family_state','household_members','households','family_chore_deliveries'):
            denied = self.as_user('SELECT * FROM public.' + table + ';', role='anon', check=False)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn('permission denied', denied.stderr)

    def test_realistic_foreign_keys_and_notnull_reject_invalid_admin_rows(self):
        self.evolve()
        before = self.snapshot()
        for query in [f"UPDATE public.family_state SET household_id='33333333-3333-4333-8333-333333333333' WHERE household_id='{HOUSE}';",
                      f"UPDATE public.family_state SET updated_by='dddddddd-dddd-4ddd-8ddd-dddddddddddd' WHERE household_id='{HOUSE}';",
                      f"UPDATE public.family_state SET updated_at=NULL WHERE household_id='{HOUSE}';"]:
            result = self.sql(query, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.sql("SELECT count(*) FROM pg_constraint WHERE conrelid='public.family_state'::regclass AND contype='f';"), '2')
        self.assertEqual(self.sql("SELECT count(*) FROM pg_constraint WHERE conrelid='public.household_members'::regclass AND contype='f';"), '2')

    def test_concurrent_cas_and_foreign_rejection_use_production_shaped_rls(self):
        self.evolve()
        before = json.loads(self.snapshot())
        own = next(row for row in before if row['household_id']==HOUSE)
        def cas(user, request, amount):
            return json.loads(self.as_user(f"SELECT public.family_state_cas('{HOUSE}',{own['sync_revision']},'{{\"entries\":[{{\"id\":\"fixture\",\"amount\":{amount}}}]}}','{request}');", user=user))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            answers = list(pool.map(lambda args: cas(*args), [
                (USER,'dddddddd-dddd-4ddd-8ddd-dddddddddddd',1250.5),
                (PARTNER,'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',3000)]))
        self.assertCountEqual([answer['status'] for answer in answers], ['written','conflict'])
        denied = cas(OUTSIDER,'ffffffff-ffff-4fff-8fff-ffffffffffff',1)
        self.assertEqual(denied['status'], 'not_found')
        current = json.loads(self.snapshot())
        own_after = next(row for row in current if row['household_id']==HOUSE)
        self.assertEqual(own_after['sync_revision'],own['sync_revision']+1)
        self.assertIn(own_after['updated_by'],(USER,PARTNER))
        self.assertEqual(next(row for row in current if row['household_id']==OTHER),
                         next(row for row in before if row['household_id']==OTHER))
        # Actual production has no DELETE policy: zero rows, independent of the CAS trigger.
        self.assertEqual(self.as_user(f"DELETE FROM public.family_state WHERE household_id='{HOUSE}' RETURNING household_id;"),'')


if __name__ == '__main__':
    unittest.main()

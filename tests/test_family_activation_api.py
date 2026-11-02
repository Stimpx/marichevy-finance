"""Prepared activation statement against isolated, fictional PostgreSQL only.

The shared harness uses a pinned image, network=none and tmpfs, with no ports,
application credentials or production connection string. PREPARE/EXECUTE binds
the four typed parameters in PostgreSQL; no psql-variable SQL substitution is used.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import unittest

import test_production_permissions as permissions
import test_sync_database as database


ROOT = Path(__file__).resolve().parents[1]
ACTIVATION = (ROOT / 'server/activate_household_api.sql').read_text()
HOUSE, OTHER = database.HOUSE, database.OTHER
USER, OUTSIDER = database.USER, database.OUTSIDER
MISSING = '33333333-3333-4333-8333-333333333333'
RAW_FIXTURE = '''{"entries":[{"id":"fictional","amount":12.3400}],
  "future":{"opaque":[null,true,0.0001],"unicode":"учебное"},
  "deletedEntries":{"old":"2001-01-01"},"settings":{"unknown":"keep"}}'''


class FamilyActivationApiTests(unittest.TestCase):
    docker = classmethod(database.SyncDatabaseTests.docker.__func__)
    sql = classmethod(database.SyncDatabaseTests.sql.__func__)
    as_user = classmethod(permissions.ProductionPermissions.as_user.__func__)

    @classmethod
    def setUpClass(cls):
        permissions.ProductionPermissions.setUpClass.__func__(cls)
        cls.sql('CREATE ROLE supabase_admin BYPASSRLS;', database='postgres')

    def setUp(self):
        permissions.ProductionPermissions.setUp(self)
        self.sql(f"""UPDATE public.family_state SET
          data={database.literal(RAW_FIXTURE)}::jsonb,
          updated_at='2001-02-03T04:05:06.123456Z',updated_by='{USER}'
          WHERE household_id='{HOUSE}';""")
        for name in ('001_family_state_cas.sql', '002_restrict_table_capabilities.sql',
                     '003_bound_membership_lookup.sql'):
            self.sql((ROOT / 'server' / name).read_text())

    def rows(self):
        return permissions.ProductionPermissions.all_rows(self)

    def source_rows(self):
        rows = self.rows()
        rows['family_state'] = self.sql("""SELECT jsonb_agg(
          to_jsonb(s)-ARRAY['sync_revision','sync_protocol','last_request_id']::text[]
          ORDER BY s.household_id) FROM public.family_state s;""")
        return rows

    def metadata(self):
        return json.loads(self.sql(f"""SELECT jsonb_build_object(
          'revision',sync_revision,'protocol',sync_protocol,
          'request_id',last_request_id,'updated_at',updated_at,'updated_by',updated_by)
          FROM public.family_state WHERE household_id='{HOUSE}';"""))

    def data_hash(self):
        return self.sql(f"""SELECT encode(sha256(convert_to(data::text,'UTF8')),'hex')
          FROM public.family_state WHERE household_id='{HOUSE}';""")

    def parameters(self, **overrides):
        values = {'database': 'sync_fictional', 'household': HOUSE,
                  'revision': self.metadata()['revision'], 'data_hash': self.data_hash()}
        values.update(overrides)
        return tuple(values[key] for key in ('database', 'household', 'revision', 'data_hash'))

    def execute(self, parameters=None, *, prefix='', check=True):
        values = self.parameters() if parameters is None else parameters
        arguments = ','.join('NULL' if value is None else database.literal(value) for value in values)
        # This prepares the exact standalone artifact and binds typed values on
        # execution, as a parameterized Management API statement must do.
        query = ('\\set VERBOSITY verbose\n' + prefix + '\n'
                 + 'PREPARE family_activation_api(text,uuid,bigint,text) AS\n'
                 + ACTIVATION + '\nEXECUTE family_activation_api(' + arguments + ');\n')
        return self.sql(query, check=check)

    def assert_refused_without_changes(self, parameters, *, prefix='', sqlstate='22012'):
        before = self.rows()
        result = self.execute(parameters, prefix=prefix, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(sqlstate, result.stderr)
        self.assertEqual(self.rows(), before)

    def test_correct_activation_preserves_exact_source_and_other_household(self):
        before_source = self.source_rows()
        before_meta = self.metadata()
        answer = self.execute()
        self.assertEqual(answer, '1|' + str(before_meta['revision'] + 1))
        after = self.metadata()
        self.assertEqual((after['protocol'], after['revision'], after['request_id']),
                         (2, before_meta['revision'] + 1, None))
        self.assertEqual(after['updated_at'], before_meta['updated_at'])
        self.assertEqual(after['updated_by'], before_meta['updated_by'])
        self.assertEqual(self.source_rows(), before_source)

    def test_generic_prepared_plan_accepts_valid_runtime_invariant(self):
        before = self.source_rows()
        self.assertEqual(self.execute(prefix='SET plan_cache_mode=force_generic_plan;'), '1|1')
        self.assertEqual(self.source_rows(), before)

    def test_nullable_updated_by_is_preserved(self):
        self.sql(f"UPDATE public.family_state SET updated_by=NULL WHERE household_id='{HOUSE}';")
        before = self.source_rows()
        revision = self.metadata()['revision']
        self.assertEqual(self.execute(), '1|' + str(revision + 1))
        self.assertIsNone(self.metadata()['updated_by'])
        self.assertEqual(self.source_rows(), before)

    def test_old_data_hash_refuses_even_with_the_current_revision(self):
        old_hash = self.data_hash()
        self.sql(f"""UPDATE public.family_state SET data=data || '{{"new_writer":true}}'::jsonb
          WHERE household_id='{HOUSE}';""")
        self.assertNotEqual(self.data_hash(), old_hash)
        self.assert_refused_without_changes(self.parameters(data_hash=old_hash))

    def test_stale_revision_hash_database_and_household_are_atomic_refusals(self):
        arguments = [
            {'revision': 999}, {'revision': -1}, {'revision': 9223372036854775807},
            {'data_hash': '0' * 64}, {'data_hash': 'invalid'},
            {'database': 'wrong_database'},
            {'database': "sync_fictional'; UPDATE public.family_state SET data='{}'; --"},
            {'household': MISSING}, {'household': OTHER},
        ]
        for override in arguments:
            with self.subTest(override=override):
                self.assert_refused_without_changes(self.parameters(**override))

    def test_null_bound_values_fail_without_modifying_any_row(self):
        for field in ('database', 'household', 'revision', 'data_hash'):
            with self.subTest(field=field):
                self.assert_refused_without_changes(self.parameters(**{field: None}))

    def test_already_active_protocol_cannot_be_activated_again(self):
        self.execute()
        self.assert_refused_without_changes(self.parameters())

    def test_read_only_transaction_cannot_activate_as_postgres(self):
        self.assert_refused_without_changes(self.parameters(),
            prefix='BEGIN READ ONLY;', sqlstate='25006')

    def test_nonpostgres_bypassrls_maintenance_role_cannot_activate(self):
        # The reviewed trigger trusts this maintenance role. Even with its row
        # access and UPDATE privilege, the API artifact must insist on postgres.
        self.sql('GRANT USAGE ON SCHEMA public TO supabase_admin; '
                 'GRANT SELECT,UPDATE ON public.family_state TO supabase_admin;')
        self.assert_refused_without_changes(self.parameters(), prefix='SET ROLE supabase_admin;')

    def test_authenticated_member_cannot_activate(self):
        prefix = ("SET ROLE authenticated; SET request.jwt.claim.role='authenticated'; "
                  f"SET request.jwt.claim.sub='{USER}';")
        self.assert_refused_without_changes(self.parameters(), prefix=prefix)

    def test_post_update_invariant_failure_rolls_back_the_actual_update(self):
        self.sql("""CREATE FUNCTION public.activation_fixture_tamper() RETURNS trigger
          LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;
          CREATE TRIGGER zz_activation_fixture_tamper BEFORE UPDATE ON public.family_state
          FOR EACH ROW EXECUTE FUNCTION public.activation_fixture_tamper();""")
        mutations = [
            "NEW.data:=NEW.data || '{\"tampered\":true}'::jsonb;",
            "NEW.updated_at:=NEW.updated_at+interval '1 second';",
            f"NEW.updated_by:='{OUTSIDER}'::uuid;",
            'NEW.sync_revision:=NEW.sync_revision+1;',
            f"NEW.last_request_id:='{OUTSIDER}'::uuid;",
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.sql('CREATE OR REPLACE FUNCTION public.activation_fixture_tamper() '
                         'RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN '
                         + mutation + ' RETURN NEW; END $$;')
                self.assert_refused_without_changes(self.parameters())

    def test_semantically_equal_numeric_scale_change_is_also_rolled_back(self):
        self.assertEqual(self.sql("SELECT '12.3400'::jsonb='12.34'::jsonb;"), 't')
        self.assertEqual(self.sql("SELECT '12.3400'::jsonb::text='12.34'::jsonb::text;"), 'f')
        self.sql("""CREATE FUNCTION public.activation_fixture_scale() RETURNS trigger
          LANGUAGE plpgsql AS $$ BEGIN
            NEW.data:=jsonb_set(NEW.data,'{entries,0,amount}','12.34'::jsonb);
            RETURN NEW;
          END $$;
          CREATE TRIGGER zz_activation_fixture_scale BEFORE UPDATE ON public.family_state
          FOR EACH ROW EXECUTE FUNCTION public.activation_fixture_scale();""")
        self.assert_refused_without_changes(self.parameters())

    def test_concurrent_activation_has_one_winner_and_one_atomic_refusal(self):
        before = self.source_rows()
        parameters = self.parameters()
        with ThreadPoolExecutor(max_workers=2) as pool:
            answers = list(pool.map(lambda _: self.execute(parameters, check=False), range(2)))
        self.assertEqual(sum(answer.returncode == 0 for answer in answers), 1)
        loser = next(answer for answer in answers if answer.returncode != 0)
        self.assertIn('22012', loser.stderr)
        self.assertEqual((self.metadata()['protocol'], self.metadata()['revision']), (2, 1))
        self.assertEqual(self.source_rows(), before)


if __name__ == '__main__':
    unittest.main()

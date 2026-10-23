"""Production inspector boundary tests; no production request or credential needed."""
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import test_sync_database as database_harness


SPEC = importlib.util.spec_from_file_location('production_schema_inspector',
    Path(__file__).resolve().parents[1] / 'tools/inspect_production_schema.py')
inspector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspector)
TOKEN = 'synthetic-production-inspection-token'
CONFIG = "const CONFIG=Object.freeze({url:'https://" + inspector.PROJECT_REF + ".supabase.co',key:'unused'});"


def project(**changes):
    return dict(dict(ref=inspector.PROJECT_REF, id=inspector.PROJECT_REF,
                     name=inspector.PROJECT_NAME, status='ACTIVE_HEALTHY', region='eu-west-1'), **changes)


def inventory():
    return {'format': 'marichevy-schema-inventory-v1', 'catalog_only': True,
            'database_name': 'postgres', 'server_version': '16.0',
            'namespaces': ['public'], 'tables': [], 'policies': [],
            'triggers': [], 'routines': [], 'event_triggers': []}


class FakeTransport:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def request(self, method, url, headers, body=None):
        self.calls.append((method, url, deepcopy(headers), deepcopy(body)))
        if not self.answers:
            raise AssertionError('Unexpected HTTP request')
        return self.answers.pop(0)


class Response(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(json.dumps(payload).encode())
        self.status = status


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def open(self, request, timeout):
        self.calls.append(request)
        if self.error:
            raise self.error
        return self.response or Response({})


class ProductionInspectorTests(unittest.TestCase):
    def inspect(self, transport):
        with patch.object(Path, 'read_text', return_value=CONFIG):
            return inspector.ProductionSchemaInspector(TOKEN, transport).inspect()

    def test_current_application_config_must_match_fixed_production(self):
        self.assertEqual(inspector.configured_project_ref(CONFIG), inspector.PROJECT_REF)
        for source in ['', CONFIG.replace(inspector.PROJECT_REF, 'a' * 20),
                       CONFIG.replace('https://', 'http://'),
                       CONFIG.replace('.supabase.co', '.supabase.co.evil.invalid')]:
            with self.subTest(source=source), self.assertRaises(inspector.InspectionError):
                inspector.configured_project_ref(source)

    def test_missing_binding_never_starts_transport(self):
        transport = FakeTransport()
        with self.assertRaisesRegex(inspector.InspectionError, inspector.TOKEN_NAME):
            inspector.ProductionSchemaInspector(None, transport)
        self.assertEqual(transport.calls, [])

    def test_wrong_config_stops_before_network(self):
        transport = FakeTransport()
        with patch.object(Path, 'read_text', return_value=CONFIG.replace(inspector.PROJECT_REF, 'a' * 20)):
            with self.assertRaisesRegex(inspector.InspectionError, 'CONFIG'):
                inspector.ProductionSchemaInspector(TOKEN, transport).inspect()
        self.assertEqual(transport.calls, [])

    def test_identity_ref_name_and_health_checked_before_catalog_query(self):
        for invalid in [project(ref='a' * 20), project(name='marichevy-finance-staging'),
                        project(status='COMING_UP'), None]:
            with self.subTest(invalid=invalid):
                transport = FakeTransport((200, invalid))
                with self.assertRaises(inspector.InspectionError):
                    self.inspect(transport)
                self.assertEqual(len(transport.calls), 1)
                self.assertEqual(transport.calls[0][:2], ('GET', inspector.PROJECT_URL))

    def test_fixed_read_only_query_accepts_201_and_safe_report_excludes_extra_project_fields(self):
        info = project(access_token=TOKEN, database={'password': 'synthetic-secret-db-password'})
        transport = FakeTransport((200, info), (201, [{'inventory': inventory()}]))
        result = self.inspect(transport)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(transport.calls[1][:2], ('POST', inspector.PROJECT_URL + '/database/query'))
        self.assertEqual(transport.calls[1][3], {'query': inspector.INVENTORY_SQL, 'read_only': True})
        self.assertEqual(result['outcome'], 'inspected')
        for name in ['data_rows_read', 'schema_changed', 'api_keys_revealed', 'authorization_tested']:
            self.assertFalse(result[name])
        self.assertTrue(result['read_only'])
        self.assertEqual(result['query_sha256'], hashlib.sha256(inspector.INVENTORY_SQL.encode()).hexdigest())
        encoded = json.dumps(result)
        self.assertNotIn(TOKEN, encoded)
        self.assertNotIn('synthetic-secret-db-password', encoded)

    def test_query_accepts_200_without_retries(self):
        transport = FakeTransport((200, project()), (200, [{'inventory': inventory()}]))
        self.assertEqual(self.inspect(transport)['inventory'], inventory())
        self.assertEqual(len(transport.calls), 2)

    def test_missing_catalog_marker_or_collections_is_not_success(self):
        bad_inventory = inventory()
        del bad_inventory['tables']
        for rows in [None, [], {}, [{}], [{'inventory': {}}],
                     [{'inventory': {**inventory(), 'catalog_only': False}}],
                     [{'inventory': bad_inventory}]]:
            with self.subTest(rows=rows), self.assertRaises(inspector.InspectionError):
                self.inspect(FakeTransport((200, project()), (201, rows)))

    def test_errors_do_not_echo_remote_bodies_or_tokens(self):
        for answers, expected in [([(403, {'error': TOKEN})], 'identity'),
                                  ([(200, project()), (403, {'error': TOKEN})], 'catalog')]:
            with self.subTest(answers=answers):
                with self.assertRaises(inspector.InspectionError) as raised:
                    self.inspect(FakeTransport(*answers))
                self.assertNotIn(TOKEN, str(raised.exception))
                self.assertIn(expected, str(raised.exception))

    def test_missing_token_overwrites_stale_success_with_blocked_report(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'inventory.json'
            report.write_text('{"outcome":"inspected","stale":true}')
            with patch.dict(inspector.os.environ, {}, clear=True), \
                    patch('sys.argv', ['inspect_production_schema.py', '--report', str(report)]), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(inspector.main(), 1)
            saved = json.loads(report.read_text())
            self.assertEqual(saved['outcome'], 'blocked')
            self.assertNotIn('stale', saved)
            self.assertTrue(saved['observed_at'])
            self.assertFalse(saved['data_rows_read'])
            self.assertNotIn(TOKEN, report.read_text())


class InspectionTransportBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.transport = inspector.Transport()
        self.transport.opener = FakeOpener()

    def test_only_exact_identity_get_and_fixed_readonly_post_are_allowed(self):
        for method, url, body in [
            ('GET', inspector.PROJECT_URL + '/api-keys?reveal=true', None),
            ('PATCH', inspector.PROJECT_URL, {'name': 'changed'}),
            ('DELETE', inspector.PROJECT_URL, None),
            ('POST', inspector.PROJECT_URL + '/database/query', {'query': 'SELECT * FROM auth.users', 'read_only': True}),
            ('POST', inspector.PROJECT_URL + '/database/query', {'query': inspector.INVENTORY_SQL, 'read_only': False}),
            ('POST', inspector.PROJECT_URL + '/database/query', {'query': inspector.INVENTORY_SQL, 'read_only': True, 'parameters': []}),
            ('GET', inspector.PROJECT_URL + '/../other', None),
            ('GET', inspector.PROJECT_URL + '?include=secrets', None),
            ('GET', inspector.PROJECT_URL + '#fragment', None),
            ('GET', inspector.PROJECT_URL.replace('https://', 'https://user:password@'), None),
            ('GET', inspector.PROJECT_URL.replace('https://', 'http://'), None),
            ('GET', inspector.PROJECT_URL.replace(inspector.PROJECT_REF, 'a' * 20), None),
        ]:
            with self.subTest(method=method, url=url), self.assertRaises(inspector.InspectionError):
                self.transport.request(method, url, {}, body)
        self.assertEqual(self.transport.opener.calls, [])

    def test_complete_transport_sends_only_fixed_body_and_inherited_credential_header(self):
        self.transport.opener = FakeOpener(Response({'safe': True}, 201))
        status, value = self.transport.request('POST', inspector.PROJECT_URL + '/database/query',
            {'Authorization': 'Bearer ' + TOKEN}, {'query': inspector.INVENTORY_SQL, 'read_only': True})
        self.assertEqual((status, value), (201, {'safe': True}))
        sent = self.transport.opener.calls[0]
        self.assertEqual(sent.get_header('Authorization'), 'Bearer ' + TOKEN)
        self.assertEqual(json.loads(sent.data), {'query': inspector.INVENTORY_SQL, 'read_only': True})

    def test_network_error_is_scrubbed(self):
        self.transport.opener = FakeOpener(error=URLError(TOKEN))
        with self.assertRaises(inspector.InspectionError) as raised:
            self.transport.request('GET', inspector.PROJECT_URL, {})
        self.assertNotIn(TOKEN, str(raised.exception))

    def test_http_error_is_status_and_never_raised_with_sensitive_message(self):
        error = HTTPError(inspector.PROJECT_URL, 401, TOKEN, {}, io.BytesIO(b'not json'))
        self.transport.opener = FakeOpener(error=error)
        self.assertEqual(self.transport.request('GET', inspector.PROJECT_URL, {}), (401, None))

    def test_redirect_is_blocked(self):
        self.assertIsNone(inspector.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.invalid/'))


class InventorySQLLocalDatabase(unittest.TestCase):
    """Compile/run the exact catalog query in an ephemeral synthetic PostgreSQL."""
    def test_catalog_query_never_returns_row_or_routine_default_secrets(self):
        fixture = database_harness.SyncDatabaseTests
        fixture.setUpClass()
        try:
            test = fixture()
            test.setUp()
            fixture.sql("""CREATE TABLE public.private_fixture(value text DEFAULT 'PRIVATE_DEFAULT_DO_NOT_RETURN');
                INSERT INTO public.private_fixture VALUES ('PRIVATE_ROW_DO_NOT_RETURN');
                CREATE FUNCTION public.private_body_fixture() RETURNS text LANGUAGE sql AS
                $$ SELECT 'PRIVATE_ROUTINE_BODY_DO_NOT_RETURN'::text $$;
                CREATE FUNCTION public.private_webhook_fixture() RETURNS trigger LANGUAGE plpgsql AS
                $$ BEGIN RETURN NEW; END $$;
                CREATE TRIGGER private_webhook BEFORE INSERT ON public.private_fixture
                FOR EACH ROW EXECUTE FUNCTION public.private_webhook_fixture(
                  'https://example.invalid/private', 'POST',
                  '{"Authorization":"Bearer PRIVATE_TRIGGER_ARGUMENT_DO_NOT_RETURN"}');
                ALTER TABLE public.private_fixture ADD CONSTRAINT private_constraint
                  CHECK (value <> 'PRIVATE_CONSTRAINT_LITERAL_DO_NOT_RETURN');
                ALTER TABLE public.private_fixture ENABLE ROW LEVEL SECURITY;
                CREATE POLICY private_policy ON public.private_fixture
                  USING (value <> 'PRIVATE_POLICY_LITERAL_DO_NOT_RETURN')
                  WITH CHECK (value <> 'PRIVATE_WITHCHECK_LITERAL_DO_NOT_RETURN');""")
            escaped_secret = "PRIVATE_ESCAPED_POLICY_LITERAL_DO_NOT_RETURN-'quote-\\slash"
            fixture.sql("CREATE POLICY private_escaped_policy ON public.private_fixture USING (value <> "
                        + database_harness.literal(escaped_secret) + ");")
            raw = fixture.sql(inspector.INVENTORY_SQL)
            result = json.loads(raw)
            self.assertEqual(result['format'], 'marichevy-schema-inventory-v1')
            self.assertTrue(result['catalog_only'])
            for secret in ['PRIVATE_DEFAULT_DO_NOT_RETURN', 'PRIVATE_ROW_DO_NOT_RETURN', 'PRIVATE_ROUTINE_BODY_DO_NOT_RETURN',
                           'PRIVATE_TRIGGER_ARGUMENT_DO_NOT_RETURN', 'PRIVATE_CONSTRAINT_LITERAL_DO_NOT_RETURN',
                           'PRIVATE_POLICY_LITERAL_DO_NOT_RETURN', 'PRIVATE_WITHCHECK_LITERAL_DO_NOT_RETURN',
                           'PRIVATE_ESCAPED_POLICY_LITERAL_DO_NOT_RETURN']:
                self.assertNotIn(secret, raw)
            family = next(t for t in result['tables'] if t['schema'] == 'public' and t['name'] == 'family_state')
            self.assertTrue(family['rls_enabled'])
            self.assertEqual(len(family['columns']), 7)
            self.assertTrue(any(c['type'] == 'p' for c in family['constraints']))
            self.assertTrue(any(p['table'] == 'family_state' for p in result['policies']))
            self.assertTrue(any(t['name'] == 'family_state_sync_guard' for t in result['triggers']))
            trigger = next(t for t in result['triggers'] if t['name'] == 'private_webhook')
            self.assertNotIn('definition', trigger)
            self.assertEqual(trigger['argument_count'], 3)
            self.assertTrue(trigger['row_level'])
            self.assertTrue(trigger['before'])
            self.assertTrue(trigger['insert'])
            self.assertRegex(trigger['definition_md5'], r'^[0-9a-f]{32}$')
            policy = next(p for p in result['policies'] if p['name'] == 'private_policy')
            self.assertNotIn('using', policy)
            self.assertNotIn('with_check', policy)
            self.assertIn('<redacted>', policy['using_redacted'])
            self.assertIn('<redacted>', policy['with_check_redacted'])
            self.assertRegex(policy['using_md5'], r'^[0-9a-f]{32}$')
            family_policy = next(p for p in result['policies'] if p['table'] == 'family_state')
            self.assertIn('auth.uid()', family_policy['using_redacted'])
            private_table = next(t for t in result['tables'] if t['name'] == 'private_fixture')
            constraint = next(c for c in private_table['constraints'] if c['name'] == 'private_constraint')
            self.assertIn('<redacted>', constraint['definition_redacted'])
            self.assertEqual(constraint['columns'], ['value'])
            self.assertRegex(constraint['definition_md5'], r'^[0-9a-f]{32}$')
            routine = next(r for r in result['routines'] if r['name'] == 'private_body_fixture')
            self.assertRegex(routine['source_md5'], r'^[0-9a-f]{32}$')
            self.assertNotIn('source', routine)
        finally:
            fixture.doClassCleanups()


if __name__ == '__main__':
    unittest.main()

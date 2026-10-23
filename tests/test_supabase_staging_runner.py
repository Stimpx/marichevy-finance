"""Offline guard/credential tests; these do not validate hosted Supabase behavior."""
from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError


SPEC = importlib.util.spec_from_file_location(
    'supabase_staging_runner', Path(__file__).resolve().parents[1] / 'tools/supabase_staging.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
TOKEN = 'synthetic-management-token-never-log'


def identity(**changes):
    return dict(dict(ref=runner.PROJECT_REF, id=runner.PROJECT_REF,
                     name=runner.PROJECT_NAME, status='ACTIVE_HEALTHY', region='eu-west-1'), **changes)


class QueueTransport:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def request(self, method, url, headers=None, body=None):
        self.calls.append((method, url, deepcopy(headers), deepcopy(body)))
        if not self.answers:
            raise AssertionError('Unexpected transport call')
        return self.answers.pop(0)


class Response(io.BytesIO):
    status = 200


class Opener:
    def __init__(self, *, result=None, error=None):
        self.result, self.error = result, error
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request)
        if self.error:
            raise self.error
        return Response(json.dumps(self.result).encode())


class StagingRunnerGuards(unittest.TestCase):
    def test_missing_token_never_starts_transport(self):
        transport = QueueTransport()
        with self.assertRaisesRegex(runner.StagingError, runner.TOKEN_NAME):
            runner.Staging(None, transport)
        self.assertEqual(transport.calls, [])

    def test_matching_ref_and_name_required_before_queries_or_key_reveal(self):
        for wrong in [identity(ref='aaaaaaaaaaaaaaaaaaaa'), identity(name='production'),
                      identity(status='COMING_UP')]:
            with self.subTest(wrong=wrong):
                transport = QueueTransport((200, wrong))
                stage = runner.Staging(TOKEN, transport)
                with self.assertRaises(runner.StagingError):
                    stage.inspect()
                self.assertFalse(stage.identity_verified)
                self.assertEqual(len(transport.calls), 1)
                self.assertEqual(transport.calls[0][1], runner.MANAGEMENT)
                with self.assertRaisesRegex(runner.StagingError, 'identity'):
                    stage.keys()
                self.assertEqual(len(transport.calls), 1)

    def test_query_before_identity_verification_is_denied(self):
        transport = QueueTransport()
        stage = runner.Staging(TOKEN, transport)
        with self.assertRaisesRegex(runner.StagingError, 'identity'):
            stage.query('SELECT 1')
        self.assertEqual(transport.calls, [])

    def test_failed_revalidation_revokes_the_previous_identity_check(self):
        transport = QueueTransport((200, identity()), (200, identity(name='production')))
        stage = runner.Staging(TOKEN, transport)
        stage.verify_identity()
        self.assertTrue(stage.identity_verified)
        with self.assertRaises(runner.StagingError):
            stage.verify_identity()
        self.assertFalse(stage.identity_verified)
        with self.assertRaises(runner.StagingError):
            stage.keys()
        self.assertEqual(len(transport.calls), 2)

    def test_inspect_is_read_only_and_report_excludes_secrets(self):
        project = identity()
        project['access_token'] = 'synthetic-secret-extra-field'
        project['database'] = {'password': 'synthetic-password-extra-field'}
        inventory = {'public_relations': 0, 'auth_users': 0, 'fixture_exists': False}
        transport = QueueTransport((200, project), (200, [inventory]))
        stage = runner.Staging(TOKEN, transport)
        report = stage.inspect()
        self.assertEqual(report['inventory'], inventory)
        self.assertTrue(transport.calls[1][3]['read_only'])
        self.assertEqual(transport.calls[1][3]['parameters'], [])
        self.assertEqual(transport.calls[1][0], 'POST')
        encoded = json.dumps(report)
        for secret in [TOKEN, 'synthetic-secret-extra-field', 'synthetic-password-extra-field']:
            self.assertNotIn(secret, encoded)

    def test_pristine_preflight_refuses_existing_users_tables_or_marker(self):
        for field in ['public_relations', 'auth_users', 'fixture_exists']:
            with self.subTest(field=field):
                inventory = {'public_relations': 0, 'auth_users': 0, 'fixture_exists': False}
                inventory[field] = True if field == 'fixture_exists' else 1
                transport = QueueTransport((200, identity()), (200, [inventory]))
                stage = runner.Staging(TOKEN, transport)
                with self.assertRaisesRegex(runner.StagingError, 'will not be reset'):
                    stage.run()
                self.assertEqual(len(transport.calls), 2)
                self.assertTrue(transport.calls[1][3]['read_only'])

    def test_modern_keys_preferred_without_key_mutation(self):
        keys = [{'name': 'anon', 'type': 'legacy', 'api_key': 'old-anon'},
                {'name': 'service_role', 'type': 'legacy', 'api_key': 'old-service'},
                {'name': 'public', 'type': 'publishable', 'api_key': 'sb_publishable_fixture'},
                {'name': 'private', 'type': 'secret', 'api_key': 'sb_secret_fixture'}]
        transport = QueueTransport((200, identity()), (200, keys))
        stage = runner.Staging(TOKEN, transport)
        stage.verify_identity()
        self.assertEqual(stage.keys(), ('sb_publishable_fixture', 'sb_secret_fixture'))
        self.assertEqual(transport.calls[-1][0], 'GET')
        self.assertEqual(transport.calls[-1][1], runner.MANAGEMENT + '/api-keys?reveal=true')

    def test_legacy_key_fallback_uses_existing_values(self):
        keys = [{'name': 'anon', 'type': 'legacy', 'api_key': 'synthetic-anon'},
                {'name': 'service_role', 'type': 'legacy', 'api_key': 'synthetic-service'}]
        transport = QueueTransport((200, identity()), (200, keys))
        stage = runner.Staging(TOKEN, transport)
        stage.verify_identity()
        self.assertEqual(stage.keys(), ('synthetic-anon', 'synthetic-service'))

    def test_unrevealed_keys_fail_closed_without_token_in_error(self):
        transport = QueueTransport((200, identity()), (200, [{'name': 'public', 'type': 'publishable', 'api_key': None}]))
        stage = runner.Staging(TOKEN, transport)
        stage.verify_identity()
        with self.assertRaises(runner.StagingError) as raised:
            stage.keys()
        self.assertNotIn(TOKEN, str(raised.exception))
        self.assertEqual(len(transport.calls), 2)

    def test_management_error_does_not_echo_secret_body(self):
        transport = QueueTransport((403, {'error': TOKEN, 'details': 'synthetic-sensitive-body'}))
        with self.assertRaises(runner.StagingError) as raised:
            runner.Staging(TOKEN, transport).verify_identity()
        self.assertEqual(str(raised.exception), 'Management API returned HTTP 403')

    def test_main_missing_secret_does_not_create_success_report(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'report.json'
            report.write_text(json.dumps({'outcome': 'passed', 'stale': True}))
            output = io.StringIO()
            with patch.dict(runner.os.environ, {}, clear=True), \
                    patch('sys.argv', ['supabase_staging.py', 'inspect', '--report', str(report)]), \
                    redirect_stdout(output):
                self.assertEqual(runner.main(), 1)
            result = json.loads(report.read_text())
            self.assertEqual(result['outcome'], 'blocked')
            self.assertEqual(result['checks_completed'], [])
            self.assertFalse(result['production_tested'])
            self.assertNotIn('stale', result)
            self.assertNotIn(TOKEN, report.read_text())
            self.assertTrue(result['observed_at'])
            self.assertIn(runner.TOKEN_NAME, output.getvalue())

    def test_main_partial_failure_replaces_stale_success_and_retains_completed_checks(self):
        class Partial:
            checks = ['fixture guard passed']

            def inspect(self):
                raise runner.StagingError('Hosted assertion failed: fictional check')

        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'report.json'
            report.write_text(json.dumps({'outcome': 'passed', 'stale': True}))
            with patch.object(runner, 'Staging', return_value=Partial()), \
                    patch('sys.argv', ['supabase_staging.py', 'inspect', '--report', str(report)]), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(), 1)
            result = json.loads(report.read_text())
            self.assertEqual(result['outcome'], 'failed')
            self.assertEqual(result['checks_completed'], ['fixture guard passed'])
            self.assertNotIn('stale', result)
            self.assertFalse(result['production_tested'])


class StagingTransportGuards(unittest.TestCase):
    def transport(self, opener=None):
        result = runner.Transport()
        result.opener = opener or Opener(result=[])
        return result

    def test_other_origin_or_project_is_rejected_before_network(self):
        transport = self.transport()
        for url in ['https://production.supabase.co/rest/v1/family_state',
                    'http://' + runner.PROJECT_REF + '.supabase.co/rest/v1/',
                    'https://api.supabase.com/v1/projects/aaaaaaaaaaaaaaaaaaaa/database/query',
                    runner.PROJECT_URL + '.evil.invalid/rest/v1/',
                    'https://user:password@' + runner.PROJECT_REF + '.supabase.co/rest/v1/']:
            with self.subTest(url=url), self.assertRaises(runner.StagingError):
                transport.request('GET', url)
        self.assertEqual(transport.opener.calls, [])

    def test_redirects_are_never_followed(self):
        self.assertIsNone(runner.NoRedirect().redirect_request(None, None, 302, '', {},
                          'https://production.supabase.co/'))

    def test_traversal_encoded_paths_fragments_and_unneeded_services_are_denied(self):
        transport = self.transport()
        for url in [runner.MANAGEMENT + '/../other/database/query',
                    runner.MANAGEMENT + '/%2e%2e/other/database/query',
                    runner.MANAGEMENT + '//database/query',
                    runner.MANAGEMENT + '/database/query#not-sent-to-server',
                    runner.PROJECT_URL + '/auth/v1/../admin/users',
                    runner.PROJECT_URL + '/storage/v1/object/private',
                    runner.PROJECT_URL + '/rest/v1/family_state/./',
                    runner.PROJECT_URL.replace('https://', 'https://user:pass@') + '/rest/v1/']:
            with self.subTest(url=url), self.assertRaises(runner.StagingError):
                transport.request('GET', url)
        self.assertEqual(transport.opener.calls, [])

    def test_exact_staging_management_auth_and_rest_endpoints_are_allowed(self):
        transport = self.transport()
        for url in [runner.MANAGEMENT, runner.MANAGEMENT + '/database/query',
                    runner.MANAGEMENT + '/api-keys?reveal=true',
                    runner.PROJECT_URL + '/auth/v1/token?grant_type=password',
                    runner.PROJECT_URL + '/rest/v1/family_state?household_id=eq.fixture']:
            with self.subTest(url=url):
                self.assertEqual(transport.request('GET', url), (200, []))
        self.assertEqual(len(transport.opener.calls), 5)

    def test_network_errors_do_not_echo_exception_details(self):
        transport = self.transport(Opener(error=URLError(TOKEN)))
        with self.assertRaises(runner.StagingError) as raised:
            transport.request('GET', runner.MANAGEMENT, {'Authorization': 'Bearer ' + TOKEN})
        self.assertNotIn(TOKEN, str(raised.exception))

    def test_http_error_body_is_not_in_exception_message(self):
        error = HTTPError(runner.MANAGEMENT, 401, TOKEN, {}, io.BytesIO(json.dumps({'secret': TOKEN}).encode()))
        transport = self.transport(Opener(error=error))
        status, body = transport.request('GET', runner.MANAGEMENT)
        self.assertEqual(status, 401)
        self.assertEqual(body, {'secret': TOKEN})
        # Caller can examine status, but only safe StagingError reaches stdout.


if __name__ == '__main__':
    unittest.main()

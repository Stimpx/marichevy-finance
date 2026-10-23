"""Offline guard/credential tests; these do not validate hosted Supabase behavior."""
from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import hashlib
import re
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit


SPEC = importlib.util.spec_from_file_location(
    'supabase_staging_runner', Path(__file__).resolve().parents[1] / 'tools/supabase_staging.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
TOKEN = 'synthetic-management-token-never-log'
HOUSE = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
USERS = ['aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa' + str(index) for index in (1, 2, 3)]
RUN = 'b' * 32


def fixture_members():
    return [{'household_id': HOUSE if index < 2 else OTHER, 'user_id': user,
             'email': 'stage-' + RUN + '-' + str(index) + '@example.invalid', 'run_id': RUN}
            for index, user in enumerate(USERS)]


def fixture_metadata():
    return [{'household_id': house, 'sync_protocol': 2, 'sync_revision': 9,
             'updated_at': '2026-10-23T12:00:00Z', 'updated_by': None,
             'last_request_id': None, 'data_md5': 'c' * 32} for house in (HOUSE, OTHER)]


def fixture_context(version):
    return {'inspected': {'project': identity(), 'inventory': {'public_relations': 2 if version == 1 else 5,
                'auth_users': 3, 'fixture_exists': True}}, 'fixture_version': version,
            'members': fixture_members(), 'own_household': HOUSE, 'other_household': OTHER,
            'family_metadata': fixture_metadata()}


def fixture_answers(version):
    relations = ['family_state', 'staging_membership'] if version == 1 else [
        'family_chore_deliveries', 'family_state', 'household_members', 'households', 'staging_membership']
    answers = [(200, identity()),
        (201, [fixture_context(version)['inspected']['inventory']]),
        (201, [{'project_ref': runner.PROJECT_REF, 'project_name': runner.PROJECT_NAME, 'fixture_version': version}]),
        (201, fixture_members()), (201, [{'tables': relations}]), (201, fixture_metadata())]
    if version == 2:
        answers += [(201, [{key: member[key] for key in ('household_id', 'user_id')} for member in fixture_members()]),
                    (201, [{'deliveries': 0}])]
    return answers


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

    def test_management_query_accepts_documented_created_response(self):
        transport = QueueTransport((200, identity()), (201, [{'value': 1}]))
        stage = runner.Staging(TOKEN, transport)
        stage.verify_identity()
        self.assertEqual(stage.query('SELECT 1 AS value', read_only=True), [{'value': 1}])

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

    def test_browser_resume_refuses_an_unexpected_extra_account(self):
        inventory = {'public_relations': 2, 'auth_users': 4, 'fixture_exists': True}
        transport = QueueTransport((200, identity()), (201, [inventory]))
        stage = runner.Staging(TOKEN, transport)
        with self.assertRaisesRegex(runner.StagingError, 'three-user fixture'):
            stage.browser()
        self.assertEqual(len(transport.calls), 2)

    def test_browser_resume_refuses_accounts_without_fictional_metadata(self):
        inventory = {'public_relations': 2, 'auth_users': 3, 'fixture_exists': True}
        marker = [{'project_ref': runner.PROJECT_REF, 'project_name': runner.PROJECT_NAME, 'fixture_version': 1}]
        members = [{'household_id': 'house', 'user_id': str(index), 'email': 'real@example.com',
                    'run_id': None} for index in range(3)]
        transport = QueueTransport((200, identity()), (201, [inventory]), (201, marker), (201, members))
        stage = runner.Staging(TOKEN, transport)
        with self.assertRaisesRegex(runner.StagingError, 'non-fixture'):
            stage.browser()
        self.assertEqual(len(transport.calls), 4)

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


class StagingFixtureVersionGuards(unittest.TestCase):
    def hardening_answers(self):
        capabilities = [{'table_name': table, 'role_name': role, 'can_truncate': False, 'can_trigger': False}
            for table in ['family_state', 'households', 'household_members', 'family_chore_deliveries']
            for role in ['anon', 'authenticated']]
        normalized = "selectexists(select1frompublic.household_membershmwherehm.household_id=p_household_idandhm.user_id=p_user_idand(auth.role()='service_role'orp_user_id=auth.uid()));"
        helper = {'owner': 'postgres', 'security_definer': True, 'volatility': 'v', 'leakproof': False,
            'configuration': ['search_path=pg_catalog, public'], 'arguments': ['p_household_id', 'p_user_id'],
            'default_arguments': 0, 'variadic': 0, 'language': 'sql',
            'normalized_source_md5': hashlib.md5(normalized.encode()).hexdigest(),
            'overloads': 1, 'anon_execute': False, 'authenticated_execute': True, 'service_execute': True}
        return capabilities, helper

    def test_hardening_verifier_requires_the_exact_reviewed_helper_hash_and_capabilities(self):
        capabilities, helper = self.hardening_answers()
        stage = runner.Staging(TOKEN, QueueTransport())
        with patch.object(stage, 'query', side_effect=[capabilities, [helper]]):
            result = stage._verify_hardening()
        self.assertEqual(result['helper_normalized_source_md5'], helper['normalized_source_md5'])
        self.assertRegex(result['helper_sql_sha256'], r'^[0-9a-f]{64}$')

    def test_hardening_verifier_refuses_unknown_body_anon_execution_or_broad_grants(self):
        for change in [{'normalized_source_md5': '0' * 32}, {'anon_execute': True},
                       {'configuration': ['search_path=public']}]:
            with self.subTest(change=change):
                capabilities, helper = self.hardening_answers()
                helper.update(change)
                stage = runner.Staging(TOKEN, QueueTransport())
                with patch.object(stage, 'query', side_effect=[capabilities, [helper]]):
                    with self.assertRaisesRegex(runner.StagingError, 'exact reviewed'):
                        stage._verify_hardening()
        capabilities, _ = self.hardening_answers()
        capabilities[0]['can_truncate'] = True
        stage = runner.Staging(TOKEN, QueueTransport())
        with patch.object(stage, 'query', return_value=capabilities) as query:
            with self.assertRaisesRegex(runner.StagingError, 'TRUNCATE'):
                stage._verify_hardening()
        self.assertEqual(query.call_count, 1)

    def test_fixture_credentials_verify_each_renewed_user_and_session_identity(self):
        keys = [{'name': 'public', 'type': 'publishable', 'api_key': 'sb_publishable_fixture'},
                {'name': 'private', 'type': 'secret', 'api_key': 'sb_secret_fixture'}]
        responses = [(200, keys)]
        for user in USERS:
            responses += [(200, {'id': user}), (200, {'access_token': 'synthetic-user-token-' + user, 'user': {'id': user}})]
        transport = QueueTransport(*responses)
        stage = runner.Staging(TOKEN, transport)
        stage.identity_verified = True
        public_key, credentials, tokens, admin_key = stage._fixture_credentials(fixture_context(2), sessions=True)
        self.assertEqual(public_key, 'sb_publishable_fixture')
        self.assertEqual(admin_key, 'sb_secret_fixture')
        self.assertEqual(len(credentials), 3)
        self.assertEqual(len(tokens), 3)
        self.assertEqual([call[0] for call in transport.calls], ['GET', 'PUT', 'POST', 'PUT', 'POST', 'PUT', 'POST'])
        for index in (1, 3, 5):
            self.assertNotIn('Authorization', transport.calls[index][2], 'modern admin key belongs only in apikey')
        for index in (2, 4, 6):
            self.assertEqual(transport.calls[index][2]['apikey'], 'sb_publishable_fixture')
        wrong = QueueTransport((200, keys), (200, {'id': USERS[0]}),
            (200, {'access_token': 'not-accepted', 'user': {'id': USERS[2]}}))
        stage = runner.Staging(TOKEN, wrong)
        stage.identity_verified = True
        with self.assertRaisesRegex(runner.StagingError, 'session identity'):
            stage._fixture_credentials(fixture_context(2), sessions=True)
        self.assertEqual(len(wrong.calls), 3)

    def test_exact_v1_and_v2_fictional_contexts_are_accepted_without_key_access(self):
        for version in (1, 2):
            with self.subTest(version=version):
                transport = QueueTransport(*fixture_answers(version))
                context = runner.Staging(TOKEN, transport)._fixture()
                self.assertEqual(context['fixture_version'], version)
                self.assertEqual(context['members'], fixture_members())
                self.assertEqual(context['family_metadata'], fixture_metadata())
                self.assertEqual(context['own_household'], HOUSE)
                self.assertTrue(all(call[0] == 'GET' or call[3].get('read_only') for call in transport.calls))
                self.assertTrue(all('/api-keys' not in call[1] for call in transport.calls))

    def test_v2_relation_count_does_not_accept_v1_marker(self):
        answers = fixture_answers(1)
        answers[1][1][0]['public_relations'] = 5
        transport = QueueTransport(*answers)
        with self.assertRaisesRegex(runner.StagingError, 'count disagrees'):
            runner.Staging(TOKEN, transport)._fixture()
        self.assertEqual(len(transport.calls), 3)

    def test_relation_name_substitution_is_refused_before_keys_or_account_updates(self):
        answers = fixture_answers(2)
        answers[4] = (201, [{'tables': ['family_state', 'unknown_sensitive_table', 'households', 'household_members', 'staging_membership']}])
        transport = QueueTransport(*answers)
        with self.assertRaisesRegex(runner.StagingError, 'relation names'):
            runner.Staging(TOKEN, transport)._fixture()
        self.assertEqual(len(transport.calls), 5)

    def test_wrong_family_id_or_unprotected_revision_metadata_is_refused(self):
        for change in [{'household_id': '33333333-3333-4333-8333-333333333333'}, {'sync_protocol': 1},
                       {'sync_revision': -1}, {'data_md5': 'not-a-hash'}]:
            with self.subTest(change=change):
                answers = fixture_answers(2)
                answers[5][1][0].update(change)
                transport = QueueTransport(*answers)
                with self.assertRaisesRegex(runner.StagingError, 'revision metadata'):
                    runner.Staging(TOKEN, transport)._fixture()
                self.assertEqual(len(transport.calls), 6)

    def test_v2_must_match_retained_provenance_and_have_no_delivery_rows(self):
        for index, replacement, error in [(6, [], 'provenance'), (7, [{'deliveries': 1}], 'empty fictional delivery')]:
            with self.subTest(index=index):
                answers = fixture_answers(2)
                answers[index] = (201, replacement)
                transport = QueueTransport(*answers)
                with self.assertRaisesRegex(runner.StagingError, error):
                    runner.Staging(TOKEN, transport)._fixture()
                self.assertEqual(len(transport.calls), index + 1)

    def test_browser_v2_hardening_checked_before_any_password_renewal(self):
        stage = runner.Staging(TOKEN, QueueTransport())
        events = []
        with patch.object(stage, '_fixture', return_value=fixture_context(2)), \
                patch.object(stage, '_verify_hardening', side_effect=runner.StagingError('unreviewed helper')), \
                patch.object(stage, '_fixture_credentials', side_effect=lambda *_: events.append('renewed')):
            with self.assertRaisesRegex(runner.StagingError, 'unreviewed helper'):
                stage.browser()
        self.assertEqual(events, [])

    def test_browser_v1_and_v2_report_versions_without_serializing_passwords(self):
        for version in (1, 2):
            with self.subTest(version=version):
                stage = runner.Staging(TOKEN, QueueTransport())
                credentials = [{'email': item['email'], 'password': 'synthetic-private-password'} for item in fixture_members()]
                browser_module = types.SimpleNamespace(BrowserCheckError=RuntimeError,
                    verify_browser_flow=lambda *_: {'checks': ['nine-source-bound-browser-cases'], 'passed': True})
                with patch.object(stage, '_fixture', return_value=fixture_context(version)), \
                        patch.object(stage, '_verify_hardening', return_value={'safe': 'hash-only'}) as hardening, \
                        patch.object(stage, '_fixture_credentials', return_value=('sb_publishable_fixture', credentials, [], 'sb_secret_fixture')), \
                        patch.dict('sys.modules', {'staging_browser': browser_module}):
                    report = stage.browser()
                self.assertEqual(report['fixture_version'], version)
                self.assertEqual(report['hardening_verified'], version == 2)
                self.assertEqual(hardening.call_count, 1 if version == 2 else 0)
                encoded = json.dumps(report)
                for secret in ['synthetic-private-password', 'sb_secret_fixture', TOKEN]:
                    self.assertNotIn(secret, encoded)


class MembershipFakeHTTP:
    """Offline protocol double; never evidence that a hosted service passed."""
    def __init__(self):
        self.calls = []
        self.row = {'household_id': HOUSE, 'data': {'entries': [], 'future': {'preserve': True}},
                    'sync_revision': 9, 'sync_protocol': 2, 'last_request_id': None, 'updated_by': None}

    def request(self, method, url, headers=None, body=None):
        self.calls.append((method, url, deepcopy(headers), deepcopy(body)))
        parsed, headers = urlsplit(url), headers or {}
        path, query = parsed.path, parse_qs(parsed.query)
        role = headers.get('Authorization', '').removeprefix('Bearer ')
        who = {'synthetic-user-0': 0, 'synthetic-user-1': 1, 'synthetic-user-2': 2}.get(role)
        service = headers.get('apikey') == 'sb_secret_fixture'
        if path.endswith('/rpc/is_household_member'):
            if who is None and not service:
                return 403, None
            actual_house = HOUSE if body['p_user_id'] in USERS[:2] else OTHER
            return 200, body['p_household_id'] == actual_house and (service or body['p_user_id'] == USERS[who])
        if path.endswith('/rpc/family_state_cas'):
            if who is None:
                return 403, None
            if who == 2:
                return 200, {'status': 'not_found'}
            self.row.update(data=deepcopy(body['p_data']), sync_revision=self.row['sync_revision'] + 1,
                            last_request_id=body['p_request_id'], updated_by=USERS[who])
            return 200, {'status': 'written', 'protocol': 2, 'revision': self.row['sync_revision'],
                         'request_id': body['p_request_id'], 'data': deepcopy(body['p_data'])}
        table = path.rsplit('/', 1)[-1]
        if method != 'GET':
            if who is None:
                return 403, None
            if table == 'family_state' and who in (0, 1) and method != 'DELETE':
                return 409, None
            return (403, None) if method == 'POST' else (200, [])
        if who is None:
            return 403, None
        if who == 2:
            return 200, []
        if table == 'households':
            return 200, [{'id': HOUSE, 'name': 'Fictional own family'}]
        if table == 'household_members':
            return 200, [{'household_id': HOUSE, 'user_id': user, 'role': 'member'} for user in USERS[:2]]
        if table == 'family_state':
            return 200, [deepcopy(self.row)]
        raise AssertionError('Unexpected synthetic HTTP path')


class MembershipRunnerFlowTests(unittest.TestCase):
    def stage(self, version=1, changed_family=False):
        stage = runner.Staging(TOKEN, MembershipFakeHTTP())
        before, after = fixture_context(version), fixture_context(2)
        if changed_family:
            after['family_metadata'][0]['sync_revision'] += 1
        contexts = iter([before, after])
        stage._fixture = lambda **_: deepcopy(next(contexts))
        stage._verify_hardening = lambda: {'helper_normalized_source_md5': 'd' * 32}
        stage._fixture_credentials = lambda *_, **__: ('sb_publishable_fixture', [],
            ['synthetic-user-0', 'synthetic-user-1', 'synthetic-user-2'], 'sb_secret_fixture')
        stage.sql_calls = []
        def query(sql, parameters=(), read_only=False):
            stage.sql_calls.append((sql, parameters, read_only))
            return [{'deliveries': 0}] if sql.startswith('SELECT count(*) AS deliveries') else []
        stage.query = query
        return stage

    def test_v1_evolution_and_both_hardenings_precede_api_checks(self):
        stage = self.stage()
        report = stage.membership()
        self.assertTrue(report['evolution_applied'])
        self.assertEqual(report['fixture_version'], 2)
        self.assertTrue(report['migration_preserved_family_metadata'])
        self.assertEqual(set(report['sql_sha256']), {'staging_membership_v2.sql',
            '002_restrict_table_capabilities.sql', '003_bound_membership_lookup.sql'})
        self.assertIn("SET LOCAL marichevy.staging_project_ref=", stage.sql_calls[0][0])
        self.assertIn('TRUNCATE', stage.sql_calls[1][0])
        self.assertIn('CREATE OR REPLACE FUNCTION public.is_household_member', stage.sql_calls[2][0])
        self.assertIn('V2 helper bounded lookup anonymous', report['checks'])
        self.assertIn('V2 helper preserves service-role lookup without user identity', report['checks'])
        self.assertIn('V2 own CAS accepts exact snapshot with server revision', report['checks'])
        encoded = json.dumps(report)
        for secret in [TOKEN, 'sb_secret_fixture', 'sb_publishable_fixture', 'synthetic-user-0']:
            self.assertNotIn(secret, encoded)
        self.assertTrue(all(call[1].startswith(runner.PROJECT_URL + '/rest/v1/') for call in stage.transport.calls))

    def test_partial_v2_resume_skips_evolution_and_reapplies_exact_guarded_hardenings(self):
        stage = self.stage(version=2)
        report = stage.membership()
        self.assertFalse(report['evolution_applied'])
        self.assertNotIn('membership_v2_before', stage.sql_calls[0][0])
        self.assertIn('TRUNCATE', stage.sql_calls[0][0])
        self.assertIn('CREATE OR REPLACE FUNCTION public.is_household_member', stage.sql_calls[1][0])
        self.assertEqual(report['outcome'], 'passed')

    def test_changed_family_metadata_stops_before_password_or_http_checks(self):
        stage = self.stage(changed_family=True)
        with self.assertRaisesRegex(runner.StagingError, 'preserves family JSON'):
            stage.membership()
        self.assertEqual(stage.transport.calls, [])

    def test_missing_sql_file_cannot_partially_evolve_fixture(self):
        stage = self.stage()
        with patch.object(Path, 'read_text', side_effect=OSError('synthetic unavailable file')):
            with self.assertRaisesRegex(runner.StagingError, 'no fixture migration was started'):
                stage.membership()
        self.assertEqual(stage.sql_calls, [])
        self.assertEqual(stage.transport.calls, [])


if __name__ == '__main__':
    unittest.main()

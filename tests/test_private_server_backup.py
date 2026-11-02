"""Private backup boundaries with fictional responses/files only; no external calls."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('private_server_backup', ROOT / 'tools/export_private_server_backup.py')
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)
HOUSE = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
USER = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
TOKEN = 'SYNTHETIC_PRIVATE_BACKUP_TOKEN'
CONFIG = "const CONFIG=Object.freeze({\n url:'https://" + backup.PROJECT_REF \
         + ".supabase.co',\n key:'synthetic-public-key',\n household:'" + HOUSE + "'\n});"


def project(**changes):
    result = dict(ref=backup.PROJECT_REF, id=backup.PROJECT_REF, name=backup.PROJECT_NAME, status='ACTIVE_HEALTHY')
    result.update(changes)
    return result


def snapshot():
    return {
        'family_state': [{'household_id': HOUSE, 'data': {'entries': [{'id': 'fictional-entry',
            'amount': 1250.5, 'unknown': {'nested': [None, True, 'чай']}}],
            'futureCollection': {'preserve': ['raw', 42]}},
            'updated_at': '2026-01-01T00:00:00+00:00', 'updated_by': USER, 'unknown_column': 'preserve'}],
        'households': [{'id': HOUSE, 'name': 'PRIVATE_FICTIONAL_NAME', 'created_at': '2025-01-01T00:00:00+00:00'}],
        'household_members': [{'household_id': HOUSE, 'user_id': USER, 'role': 'owner', 'future_role_field': 7}],
        'family_chore_deliveries': [{'household_id': HOUSE, 'chore_id': 'fictional-chore', 'due_date': '2026-01-01',
            'chat_id': 'PRIVATE_FICTIONAL_CHAT', 'last_error': 'PRIVATE_FICTIONAL_ERROR'}]
    }


def snapshot_text(value=None):
    return json.dumps(snapshot() if value is None else value, ensure_ascii=False, indent=3)


class FakeTransport:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def request(self, method, url, headers, body=None):
        self.calls.append((method, url, deepcopy(headers), deepcopy(body)))
        if not self.answers:
            raise AssertionError('Unexpected request; synthetic transport is exhausted')
        return self.answers.pop(0)


def success_transport(raw=None):
    return FakeTransport((200, project(extra_secret=TOKEN)),
                         (201, [{'snapshot_json': snapshot_text() if raw is None else raw, 'snapshot_timezone': 'UTC'}]))


class Response(io.BytesIO):
    def __init__(self, value, status=200):
        super().__init__(json.dumps(value).encode('utf-8'))
        self.status = status


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def open(self, request, timeout):
        self.calls.append(request)
        if self.error:
            raise self.error
        return self.response or Response({})


class PrivateBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / 'private-output'

    def export(self, transport=None, **changes):
        arguments = dict(authorized_private_backup=True, token=TOKEN, output_dir=self.directory,
                         source=CONFIG, transport=transport or success_transport())
        arguments.update(changes)
        return backup.export_private_backup(**arguments)

    def test_authorization_precedes_config_token_transport_and_file_access(self):
        class ForbiddenToken:
            def __bool__(self):
                raise AssertionError('Token inspected before authorization')
        transport = FakeTransport()
        for flag in [False, None, 1, 'yes']:
            with self.subTest(flag=flag), patch.object(backup, 'configured_household') as config:
                with self.assertRaisesRegex(backup.BackupError, 'owner authorization'):
                    self.export(transport, authorized_private_backup=flag, token=ForbiddenToken())
                config.assert_not_called()
        self.assertEqual(transport.calls, [])
        self.assertFalse(self.directory.exists())

    def test_cli_without_flag_never_reads_token_or_runs_export(self):
        output = io.StringIO()
        environment_get = backup.os.environ.get
        def reject_token_lookup(name, default=None):
            if name == backup.TOKEN_NAME:
                raise AssertionError('No token lookup before authorization')
            return environment_get(name, default)
        with patch('sys.argv', ['export_private_server_backup.py']), \
                patch.object(backup, 'export_private_backup') as export, \
                patch.object(backup.os.environ, 'get', side_effect=reject_token_lookup), \
                redirect_stdout(output):
            self.assertEqual(backup.main(), 1)
        export.assert_not_called()
        self.assertIn('separate explicit owner authorization', output.getvalue())
        self.assertNotIn(HOUSE, output.getvalue())

    def test_fixed_config_only_no_arbitrary_target_or_duplicate(self):
        self.assertEqual(backup.configured_household(CONFIG), HOUSE)
        for source in ['', CONFIG + '\n' + CONFIG, CONFIG.replace(backup.PROJECT_REF, 'a' * 20),
                       CONFIG.replace('https://', 'http://'), CONFIG.replace(HOUSE, '0' * 36),
                       CONFIG.replace(HOUSE, '00000000-0000-0000-0000-000000000000'),
                       CONFIG.replace('.supabase.co', '.supabase.co.evil.invalid')]:
            with self.subTest(source=source), self.assertRaises(backup.BackupError) as raised:
                self.export(source=source)
            self.assertNotIn(HOUSE, str(raised.exception))
        self.assertFalse(self.directory.exists())

    def test_cli_has_no_arbitrary_household_target_and_does_not_echo_unknown_values(self):
        stream = io.StringIO()
        with patch('sys.argv', ['export_private_server_backup.py', '--household', HOUSE]), \
                patch.object(backup, 'export_private_backup') as export, \
                redirect_stdout(stream), redirect_stderr(stream), self.assertRaises(SystemExit) as raised:
            backup.main()
        self.assertEqual(raised.exception.code, 2)
        export.assert_not_called()
        self.assertNotIn(HOUSE, stream.getvalue())

    def test_missing_token_stops_before_network_and_output_creation(self):
        transport = FakeTransport()
        with self.assertRaisesRegex(backup.BackupError, 'credential binding'):
            self.export(transport, token=None)
        self.assertEqual(transport.calls, [])
        self.assertFalse(self.directory.exists())

    def test_wrong_project_or_health_prevents_any_data_query(self):
        for value in [project(ref='a' * 20), project(id='a' * 20), project(name='staging'),
                      project(status='COMING_UP'), None]:
            transport = FakeTransport((200, value))
            with self.subTest(value=value), self.assertRaises(backup.BackupError):
                self.export(transport)
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(transport.calls[0][:2], ('GET', backup.PROJECT_URL))
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_exact_readonly_snapshot_original_json_and_unknown_columns_saved_privately(self):
        raw = snapshot_text().replace('1250.5', '1250.50000000000000000000000000000000000001')
        transport = success_transport(raw)
        result = self.export(transport)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(transport.calls[1][:2], ('POST', backup.PROJECT_URL + '/database/query'))
        self.assertEqual(transport.calls[1][3], {'query': backup.SNAPSHOT_SQL, 'read_only': True,
                                                'parameters': [HOUSE]})
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
        saved = self.directory / result['backup_filename']
        manifest_path = self.directory / result['manifest_filename']
        for path in (saved, manifest_path):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.stat().st_uid, os.geteuid())
        document = json.loads(saved.read_bytes())
        self.assertEqual(document['format'], 'marichevy-private-server-backup-v1')
        self.assertEqual(document['configured_household'], HOUSE)
        self.assertEqual(document['configured_household_count'], 1)
        self.assertTrue(document['read_only'])
        self.assertEqual(document['project_ref'], backup.PROJECT_REF)
        self.assertEqual(document['database_timezone'], 'UTC')
        self.assertEqual(document['snapshot_json'], raw)
        self.assertEqual(document['snapshot_json_sha256'], hashlib.sha256(raw.encode('utf-8')).hexdigest())
        self.assertEqual(json.loads(document['snapshot_json'], parse_float=Decimal)['family_state'][0]['data']['entries'][0]['amount'],
                         Decimal('1250.50000000000000000000000000000000000001'))
        self.assertEqual(json.loads(document['snapshot_json'])['family_state'][0]['unknown_column'], 'preserve')
        manifest = json.loads(manifest_path.read_bytes())
        self.assertEqual(manifest['backup_sha256'], hashlib.sha256(saved.read_bytes()).hexdigest())
        self.assertEqual(manifest['backup_bytes'], saved.stat().st_size)
        self.assertEqual(manifest['counts'], {table: 1 for table in backup.TABLES})
        self.assertNotIn(TOKEN, saved.read_text())
        public_result = json.dumps(result)
        for private in [HOUSE, USER, TOKEN, 'PRIVATE_FICTIONAL_NAME', 'PRIVATE_FICTIONAL_CHAT', 'PRIVATE_FICTIONAL_ERROR']:
            self.assertNotIn(private, public_result)

    def test_snapshot_wrong_scope_missing_state_or_unexpected_collections_refused(self):
        cases = []
        for table in backup.TABLES:
            value = snapshot()
            value[table][0]['id' if table == 'households' else 'household_id'] = OTHER
            cases.append(value)
        for table in ('family_state', 'households'):
            value = snapshot()
            value[table] = []
            cases.append(value)
            value = snapshot()
            value[table].append(deepcopy(value[table][0]))
            cases.append(value)
        value = snapshot(); del value['family_state'][0]['data']; cases.append(value)
        value = snapshot(); value['unrequested_rows'] = [{'value': TOKEN}]; cases.append(value)
        value = snapshot(); value['family_state'] = [None]; cases.append(value)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(backup.BackupError) as raised:
                self.export(success_transport(snapshot_text(value)))
            self.assertNotIn(HOUSE, str(raised.exception))
            self.assertNotIn(TOKEN, str(raised.exception))
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_malformed_duplicate_or_nonfinite_json_never_becomes_backup(self):
        for raw in ['not JSON', '{"family_state":[],"family_state":[]}',
                    snapshot_text().replace('1250.5', 'NaN'), snapshot_text().replace('1250.5', 'Infinity')]:
            with self.subTest(raw=raw), self.assertRaises(backup.BackupError):
                self.export(success_transport(raw))
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_unexpected_snapshot_result_and_remote_errors_are_scrubbed(self):
        for rows in [None, [], {}, [{}], [{'snapshot_json': None, 'snapshot_timezone': 'UTC'}],
                     [{'snapshot_json': snapshot_text(), 'snapshot_timezone': 'UTC', 'extra_secret': TOKEN}],
                     [{'snapshot_json': snapshot_text(), 'snapshot_timezone': None}],
                     [{'snapshot_json': snapshot_text(), 'snapshot_timezone': 'x' * 129}]]:
            with self.subTest(rows=rows), self.assertRaises(backup.BackupError):
                self.export(FakeTransport((200, project()), (201, rows)))
        for answers in [[(403, {'error': TOKEN + HOUSE})],
                        [(200, project()), (403, {'error': TOKEN + HOUSE})]]:
            with self.assertRaises(backup.BackupError) as raised:
                self.export(FakeTransport(*answers))
            self.assertNotIn(TOKEN, str(raised.exception))
            self.assertNotIn(HOUSE, str(raised.exception))
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_unsafe_output_paths_refused_before_network(self):
        self.directory.mkdir(mode=0o755)
        self.directory.chmod(0o755)
        link = Path(self.temporary.name) / 'linked-parent'
        link.symlink_to(self.directory, target_is_directory=True)
        paths = [Path('relative-output'), ROOT / 'private-output',
                 Path(self.temporary.name) / '..' / 'unsafe-output', self.directory,
                 link, link / 'child', Path(self.temporary.name) / 'missing-parent' / 'child']
        for path in paths:
            transport = FakeTransport()
            with self.subTest(path=path), self.assertRaises(backup.BackupError):
                self.export(transport, output_dir=path)
            self.assertEqual(transport.calls, [])
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o755)

    def test_exclusive_file_creation_never_overwrites_and_rolls_back_only_own_partial_file(self):
        self.directory.mkdir(mode=0o700)
        basename = 'family-server-backup-PRIVATE-synthetic-collision'
        existing_backup = self.directory / (basename + '.json')
        existing_backup.write_bytes(b'PRIVATE_EXISTING_BACKUP')
        with patch.object(backup, '_new_basename', return_value=basename), self.assertRaises(backup.BackupError):
            self.export()
        self.assertEqual(existing_backup.read_bytes(), b'PRIVATE_EXISTING_BACKUP')
        existing_backup.unlink()
        existing_manifest = self.directory / (basename + '.manifest.json')
        existing_manifest.write_bytes(b'PRIVATE_EXISTING_MANIFEST')
        with patch.object(backup, '_new_basename', return_value=basename), self.assertRaises(backup.BackupError):
            self.export()
        self.assertEqual(existing_manifest.read_bytes(), b'PRIVATE_EXISTING_MANIFEST')
        self.assertFalse(existing_backup.exists())
        self.assertEqual(list(self.directory.iterdir()), [existing_manifest])

    def test_oversized_serialized_wrapper_is_refused_before_writing_and_cli_is_private(self):
        self.directory.mkdir(mode=0o700)
        original = self.directory / 'existing-private-backup.json'
        original.write_bytes(b'SYNTHETIC_PREVIOUS_BACKUP_KEEP_EXACTLY')
        before = {path.name: path.read_bytes() for path in self.directory.iterdir()}
        transport = success_transport()
        stream = io.StringIO()
        with patch('sys.argv', ['export_private_server_backup.py', '--authorized-private-backup',
                                '--output-dir', str(self.directory)]), \
                patch.object(backup.os.environ, 'get', return_value=TOKEN), \
                patch.object(Path, 'read_text', return_value=CONFIG), \
                patch.object(backup, 'Transport', return_value=transport), \
                patch.object(backup, 'MAX_BACKUP_FILE_BYTES', 64), \
                patch.object(backup, '_write_pair') as write, redirect_stdout(stream):
            self.assertEqual(backup.main(), 1)
        write.assert_not_called()
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual({path.name: path.read_bytes() for path in self.directory.iterdir()}, before)
        self.assertIn('offline verification size limit', stream.getvalue())
        for private in [HOUSE, USER, TOKEN, 'PRIVATE_FICTIONAL_NAME', 'PRIVATE_FICTIONAL_CHAT', 'PRIVATE_FICTIONAL_ERROR']:
            self.assertNotIn(private, stream.getvalue())

    def test_existing_symlink_file_and_unsafe_generated_name_never_followed(self):
        self.directory.mkdir(mode=0o700)
        target = Path(self.temporary.name) / 'existing-sensitive-file'
        target.write_bytes(b'SYNTHETIC_EXISTING_VALUE')
        basename = 'family-server-backup-PRIVATE-synthetic-symlink'
        link = self.directory / (basename + '.json')
        link.symlink_to(target)
        with patch.object(backup, '_new_basename', return_value=basename), self.assertRaises(backup.BackupError):
            self.export()
        self.assertEqual(target.read_bytes(), b'SYNTHETIC_EXISTING_VALUE')
        self.assertTrue(link.is_symlink())
        with patch.object(backup, '_new_basename', return_value='../unsafe'), self.assertRaises(backup.BackupError):
            self.export()
        self.assertFalse((self.directory.parent / 'unsafe.json').exists())

    def test_cli_output_is_aggregate_and_does_not_include_family_rows_or_errors(self):
        expected = dict(outcome='exported', counts={table: 1 for table in backup.TABLES},
                        backup_filename='family-server-backup-PRIVATE-synthetic.json')
        for action, expected_code in [(expected, 0), (RuntimeError(TOKEN + HOUSE), 1)]:
            stream = io.StringIO()
            with patch('sys.argv', ['export_private_server_backup.py', '--authorized-private-backup']), \
                    patch.object(backup.os.environ, 'get', return_value=TOKEN), \
                    patch.object(backup, 'export_private_backup',
                                 **({'side_effect': action} if isinstance(action, Exception) else {'return_value': action})), \
                    redirect_stdout(stream):
                self.assertEqual(backup.main(), expected_code)
            self.assertNotIn(TOKEN, stream.getvalue())
            self.assertNotIn(HOUSE, stream.getvalue())


class PrivateBackupTransportTests(unittest.TestCase):
    def setUp(self):
        self.transport = backup.Transport(HOUSE)
        self.transport.opener = FakeOpener()

    def test_only_exact_identity_and_single_fixed_readonly_snapshot_allowed(self):
        expected = {'query': backup.SNAPSHOT_SQL, 'read_only': True, 'parameters': [HOUSE]}
        for method, url, body in [
            ('POST', backup.PROJECT_URL + '/database/query', {**expected, 'read_only': False}),
            ('POST', backup.PROJECT_URL + '/database/query', {**expected, 'read_only': 1}),
            ('POST', backup.PROJECT_URL + '/database/query', {**expected, 'parameters': [OTHER]}),
            ('POST', backup.PROJECT_URL + '/database/query', {**expected, 'query': 'SELECT * FROM auth.users'}),
            ('POST', backup.PROJECT_URL + '/database/query', {**expected, 'extra': []}),
            ('GET', backup.PROJECT_URL + '/api-keys?reveal=true', None),
            ('PATCH', backup.PROJECT_URL, {'name': 'changed'}), ('DELETE', backup.PROJECT_URL, None),
            ('GET', backup.PROJECT_URL + '/../other', None),
            ('GET', backup.PROJECT_URL + '#fragment', None),
            ('GET', backup.PROJECT_URL.replace('https://', 'http://'), None),
            ('GET', backup.PROJECT_URL.replace('https://', 'https://user:pass@'), None),
            ('GET', backup.PROJECT_URL.replace(backup.PROJECT_REF, 'a' * 20), None),
        ]:
            with self.subTest(method=method, url=url), self.assertRaises(backup.BackupError):
                self.transport.request(method, url, {}, body)
        self.assertEqual(self.transport.opener.calls, [])
        self.assertNotIn('auth.users', backup.SNAPSHOT_SQL)
        self.assertNotIn('set_config', backup.SNAPSHOT_SQL.lower())
        self.assertEqual(backup.SNAPSHOT_SQL.count(';'), 1)
        self.assertEqual(backup.SNAPSHOT_SQL.count('$1'), 1)

    def test_exact_body_and_inherited_token_sent_without_reformatting_snapshot_string(self):
        raw = snapshot_text()
        self.transport.opener = FakeOpener(Response([{'snapshot_json': raw, 'snapshot_timezone': 'UTC'}], 201))
        expected = {'query': backup.SNAPSHOT_SQL, 'read_only': True, 'parameters': [HOUSE]}
        status, value = self.transport.request('POST', backup.PROJECT_URL + '/database/query',
            {'Authorization': 'Bearer ' + TOKEN}, expected)
        self.assertEqual(status, 201)
        self.assertEqual(value, [{'snapshot_json': raw, 'snapshot_timezone': 'UTC'}])
        request = self.transport.opener.calls[0]
        self.assertEqual(json.loads(request.data), expected)
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + TOKEN)

    def test_tls_network_http_errors_and_redirects_do_not_reveal_credentials(self):
        self.transport.opener = FakeOpener(error=URLError(TOKEN + HOUSE))
        with self.assertRaises(backup.BackupError) as raised:
            self.transport.request('GET', backup.PROJECT_URL, {})
        self.assertNotIn(TOKEN, str(raised.exception))
        self.transport.opener = FakeOpener(error=HTTPError(backup.PROJECT_URL, 403, TOKEN, {},
                                                         io.BytesIO((TOKEN + HOUSE).encode())))
        self.assertEqual(self.transport.request('GET', backup.PROJECT_URL, {}), (403, None))
        self.assertIsNone(backup.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.invalid'))


if __name__ == '__main__':
    unittest.main()

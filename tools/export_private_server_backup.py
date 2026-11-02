#!/usr/bin/env python3
"""Prepare a private, read-only backup of the configured production household.

NOT AUTHORIZED BY THE EXISTING CATALOG-ONLY INSPECTION PERMISSION.
Run only after explicit owner authorization to read real household rows for backup.
The mandatory --authorized-private-backup flag records that separate prerequisite;
it does not grant permission by itself. Never run this tool against a test project.
No authentication rows, API keys, schema writes or data writes are requested.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid


ROOT = Path(__file__).resolve().parents[1]
PROJECT_REF = 'kqndxecziamypdjpxhyq'
PROJECT_NAME = 'marichevy-finance'
PROJECT_URL = 'https://api.supabase.com/v1/projects/' + PROJECT_REF
TOKEN_NAME = 'PRODUCTION_SUPABASE_INSPECTION_TOKEN'
DEFAULT_OUTPUT = Path('/workspace/private-backups')
MAX_RESPONSE_BYTES = 128 * 1024 * 1024
# The local verifier and restore helper accept at most this serialized wrapper.
# API response escaping can be larger, hence the separate transport limit above.
MAX_BACKUP_FILE_BYTES = 32 * 1024 * 1024
TABLES = ('family_state', 'households', 'household_members', 'family_chore_deliveries')

# One statement means one MVCC snapshot. The only parameter is local CONFIG's
# household UUID. to_jsonb preserves every column, including unknown extensions.
# Returning text prevents Python float conversion from changing JSON numbers.
SNAPSHOT_SQL = r"""WITH target AS (SELECT $1::uuid AS household_id)
SELECT pg_catalog.jsonb_build_object(
  'family_state', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(s) ORDER BY s.household_id)
    FROM public.family_state s, target t WHERE s.household_id=t.household_id), '[]'::jsonb),
  'households', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(h) ORDER BY h.id)
    FROM public.households h, target t WHERE h.id=t.household_id), '[]'::jsonb),
  'household_members', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(m) ORDER BY m.user_id)
    FROM public.household_members m, target t WHERE m.household_id=t.household_id), '[]'::jsonb),
  'family_chore_deliveries', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(d)
      ORDER BY d.chore_id,d.due_date,d.chat_id)
    FROM public.family_chore_deliveries d, target t WHERE d.household_id=t.household_id), '[]'::jsonb)
)::text AS snapshot_json, pg_catalog.current_setting('TimeZone') AS snapshot_timezone;"""


class BackupError(RuntimeError):
    """Only constant, credential-free errors may reach the console."""


def configured_household(source):
    matches = list(re.finditer(r"^const CONFIG=Object\.freeze\(\{\s*"
        r"url:'https://(?P<ref>[a-z]{20})\.supabase\.co',\s*"
        r"key:'[^'\r\n]*',\s*household:'(?P<household>[0-9a-fA-F-]{36})'\s*\}\);", source, re.M))
    if len(matches) != 1 or matches[0].group('ref') != PROJECT_REF:
        raise BackupError('Application CONFIG does not uniquely match the fixed production project')
    raw = matches[0].group('household')
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError):
        raise BackupError('Application CONFIG household is not a canonical UUID') from None
    if str(parsed) != raw.lower() or parsed.int == 0:
        raise BackupError('Application CONFIG household is not a canonical UUID')
    return str(parsed)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Transport:
    def __init__(self, household):
        self.household = household
        self.opener = build_opener(NoRedirect())

    def request(self, method, url, headers, body=None):
        permitted = (method == 'GET' and url == PROJECT_URL and body is None) or (
            method == 'POST' and url == PROJECT_URL + '/database/query'
            and body == {'query': SNAPSHOT_SQL, 'read_only': True, 'parameters': [self.household]}
            and body.get('read_only') is True)
        if not permitted:
            raise BackupError('Request is outside the fixed private-backup read-only boundary')
        request = Request(url, method=method, headers={'Content-Type': 'application/json', **headers},
                          data=None if body is None else json.dumps(body).encode('utf-8'))
        try:
            with self.opener.open(request, timeout=45) as response:
                status, raw = response.status, response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            # A service error can echo query/data. Its body is never parsed or logged.
            return error.code, None
        except (URLError, TimeoutError, OSError):
            raise BackupError('Private backup request failed; check network, TLS and service health') from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise BackupError('Private backup response exceeded the fixed size limit; nothing was saved')
        try:
            result = json.loads(raw) if raw else None
        except (ValueError, UnicodeError):
            result = None
        return status, result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BackupError('Private backup snapshot contains duplicate JSON fields')
        result[key] = value
    return result


def _invalid_number(_value):
    raise BackupError('Private backup snapshot contains a non-JSON number')


def validate_snapshot(snapshot_json, household):
    if not isinstance(snapshot_json, str):
        raise BackupError('Private backup response is missing the original snapshot JSON text')
    try:
        snapshot = json.loads(snapshot_json, parse_float=Decimal, parse_constant=_invalid_number,
                              object_pairs_hook=_unique_object)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise BackupError('Private backup snapshot JSON could not be validated') from None
    if not isinstance(snapshot, dict) or set(snapshot) != set(TABLES):
        raise BackupError('Private backup snapshot has an unexpected table collection')
    if any(not isinstance(snapshot[table], list) or any(not isinstance(row, dict) for row in snapshot[table])
           for table in TABLES):
        raise BackupError('Private backup snapshot has an unexpected row collection')
    if len(snapshot['family_state']) != 1 or len(snapshot['households']) != 1:
        raise BackupError('Private backup requires exactly one configured household and one state row')
    for table in TABLES:
        key = 'id' if table == 'households' else 'household_id'
        if any(row.get(key) != household for row in snapshot[table]):
            raise BackupError('Private backup contains a row outside the configured household')
    if 'data' not in snapshot['family_state'][0]:
        raise BackupError('Private backup state row is missing its JSON data column')
    try:
        snapshot_json.encode('utf-8')
    except UnicodeError:
        raise BackupError('Private backup snapshot text is not valid UTF-8') from None
    return {table: len(snapshot[table]) for table in TABLES}


def _open_private_directory(directory):
    """Use directory descriptors and O_NOFOLLOW for every component, including parents."""
    path = Path(directory)
    if not path.is_absolute() or '..' in path.parts or path == Path('/') or path.is_relative_to(ROOT):
        raise BackupError('Backup output must be an absolute private directory outside the checkout')
    descriptor = None
    try:
        descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        for index, component in enumerate(path.parts[1:]):
            final = index == len(path.parts[1:]) - 1
            try:
                next_descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                          dir_fd=descriptor)
            except FileNotFoundError:
                if not final:
                    raise BackupError('Backup output parent directory must already exist') from None
                os.mkdir(component, 0o700, dir_fd=descriptor)
                next_descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                          dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        attributes = os.fstat(descriptor)
        if attributes.st_uid != os.geteuid() or stat.S_IMODE(attributes.st_mode) != 0o700:
            raise BackupError('Backup output directory must be owned by this user with permissions 0700')
        return descriptor
    except (OSError, ValueError):
        if descriptor is not None:
            os.close(descriptor)
        raise BackupError('Backup output directory is unavailable or contains an unsafe path component') from None
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        raise


def _new_basename(captured_at):
    return 'family-server-backup-PRIVATE-' + captured_at.strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex


def _write_pair(directory_fd, basename, backup, manifest):
    if not isinstance(basename, str) or re.fullmatch(r'[A-Za-z0-9_-]+', basename) is None:
        raise BackupError('Private backup generated filename is unsafe')
    names = (basename + '.json', basename + '.manifest.json')
    created = []
    try:
        for name, contents in zip(names, (backup, manifest)):
            descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory_fd)
            created.append((name, os.fstat(descriptor).st_ino))
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, 'wb', closefd=False) as stream:
                    stream.write(contents)
                    stream.flush()
                    os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.fsync(directory_fd)
        return names
    except (OSError, ValueError):
        for name, inode in created:
            try:
                if os.stat(name, dir_fd=directory_fd, follow_symlinks=False).st_ino == inode:
                    os.unlink(name, dir_fd=directory_fd)
            except OSError:
                pass
        raise BackupError('Private backup files could not be saved exclusively; no existing file was overwritten') from None


def export_private_backup(*, authorized_private_backup=False, token=None, output_dir=DEFAULT_OUTPUT,
                          transport=None, source=None):
    if authorized_private_backup is not True:
        raise BackupError('Explicit owner authorization for real household backup is required; catalog inspection permission is insufficient')
    if source is None:
        try:
            source = (ROOT / 'index.html').read_text()
        except (OSError, UnicodeError):
            raise BackupError('Application CONFIG could not be read') from None
    household = configured_household(source)
    if not token:
        raise BackupError('Missing protected private-backup credential binding')
    directory_fd = _open_private_directory(output_dir)
    try:
        active_transport = transport or Transport(household)
        headers = {'Authorization': 'Bearer ' + token}
        status, project = active_transport.request('GET', PROJECT_URL, headers)
        if status != 200:
            raise BackupError('Private backup project identity request did not succeed')
        if not isinstance(project, dict) or project.get('ref', project.get('id')) != PROJECT_REF \
                or ('id' in project and project['id'] != PROJECT_REF) or project.get('name') != PROJECT_NAME \
                or project.get('status') != 'ACTIVE_HEALTHY':
            raise BackupError('Private backup project identity or health did not match; no data query was sent')
        status, rows = active_transport.request('POST', PROJECT_URL + '/database/query', headers,
            {'query': SNAPSHOT_SQL, 'read_only': True, 'parameters': [household]})
        if status not in (200, 201):
            raise BackupError('Private backup read-only snapshot request did not succeed')
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict) \
                or set(rows[0]) != {'snapshot_json', 'snapshot_timezone'}:
            raise BackupError('Private backup read-only snapshot result shape is unexpected')
        snapshot_json = rows[0]['snapshot_json']
        database_timezone = rows[0]['snapshot_timezone']
        if not isinstance(database_timezone, str) or not 1 <= len(database_timezone) <= 128 \
                or '\x00' in database_timezone:
            raise BackupError('Private backup snapshot timezone metadata is invalid')
        counts = validate_snapshot(snapshot_json, household)
        captured_at = datetime.now(timezone.utc)
        query_sha256 = hashlib.sha256(SNAPSHOT_SQL.encode('utf-8')).hexdigest()
        document = {'format': 'marichevy-private-server-backup-v1',
            'captured_at_utc': captured_at.isoformat(), 'project_ref': PROJECT_REF,
            'configured_household': household, 'configured_household_count': 1,
            'read_only': True, 'query_sha256': query_sha256, 'database_timezone': database_timezone,
            'snapshot_json_sha256': hashlib.sha256(snapshot_json.encode('utf-8')).hexdigest(),
            'snapshot_json': snapshot_json}
        backup = (json.dumps(document, ensure_ascii=True, indent=2) + '\n').encode('utf-8')
        if len(backup) > MAX_BACKUP_FILE_BYTES:
            raise BackupError('Private backup wrapper exceeds the supported offline verification size limit; nothing was saved')
        backup_sha256 = hashlib.sha256(backup).hexdigest()
        basename = _new_basename(captured_at)
        manifest_document = {'format': 'marichevy-private-server-backup-manifest-v1',
            'backup_filename': basename + '.json', 'backup_sha256': backup_sha256,
            'backup_bytes': len(backup), 'captured_at_utc': document['captured_at_utc'],
            'query_sha256': query_sha256, 'counts': counts}
        manifest = (json.dumps(manifest_document, sort_keys=True, indent=2) + '\n').encode('utf-8')
        backup_name, manifest_name = _write_pair(directory_fd, basename, backup, manifest)
        # Only generated filenames and aggregate counts leave the private document.
        return {'outcome': 'exported', 'backup_filename': backup_name, 'manifest_filename': manifest_name,
                'backup_sha256': backup_sha256, 'backup_bytes': len(backup), 'counts': counts}
    finally:
        os.close(directory_fd)


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'Blocked: unsupported arguments; credentials and household identifiers must not be passed on the command line.\n')


def main():
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument('--authorized-private-backup', action='store_true',
                        help='Required only after separate explicit owner authorization to read real household backup rows')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.authorized_private_backup:
        print('Blocked: separate explicit owner authorization for real household backup is required.')
        return 1
    try:
        result = export_private_backup(authorized_private_backup=True,
            token=os.environ.get(TOKEN_NAME), output_dir=args.output_dir)
    except BackupError as error:
        print('Blocked: ' + str(error))
        return 1
    except Exception:
        # Never print a traceback containing returned household data or credentials.
        print('Blocked: private backup failed; no success is claimed.')
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

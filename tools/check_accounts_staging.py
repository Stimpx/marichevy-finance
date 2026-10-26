#!/usr/bin/env python3
"""Real HTTPS authorization checks in the fixed, fictional staging project only.

Optional --install adds the fresh 004 namespace without altering legacy tables.
Only test users and households created by this invocation are removed in finally.
Keys/passwords/sessions and provider response bodies are never written or printed.
This runner sends no emails and does not establish signup/SMTP delivery.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from supabase_staging import PROJECT_URL, Staging, StagingError, TOKEN_NAME

MIGRATION = ROOT / 'server/004_public_accounts.sql'
LEGACY_TABLES = ('households', 'household_members', 'family_state',
                 'family_chore_deliveries', 'staging_membership')


def legacy_fingerprint(stage):
    parts = []
    for table in LEGACY_TABLES:
        rows = stage.query("SELECT encode(sha256(convert_to(coalesce(jsonb_agg(to_jsonb(t) "
                           "ORDER BY to_jsonb(t)::text),'[]'::jsonb)::text,'UTF8')),'hex') AS hash "
                           "FROM public." + table + " t", read_only=True)
        parts.append(rows[0]['hash'])
    definitions = stage.query("SELECT encode(sha256(convert_to(coalesce(string_agg("
        "pg_get_functiondef(p.oid), E'\\n' ORDER BY p.oid),''),'UTF8')),'hex') AS hash "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public' AND p.proname IN ('family_state_cas','is_household_member')",
        read_only=True)
    parts.append(definitions[0]['hash'])
    controls = stage.query("""SELECT encode(sha256(convert_to(coalesce(jsonb_agg(jsonb_build_object(
      'table',c.relname,'rls',c.relrowsecurity,'force_rls',c.relforcerowsecurity,'acl',c.relacl::text,
      'columns',(SELECT jsonb_agg(jsonb_build_array(a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull) ORDER BY a.attnum)
        FROM pg_attribute a WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped),
      'policies',(SELECT jsonb_agg(to_jsonb(p) ORDER BY p.polname) FROM pg_policy p WHERE p.polrelid=c.oid),
      'constraints',(SELECT jsonb_agg(pg_get_constraintdef(k.oid) ORDER BY k.conname) FROM pg_constraint k WHERE k.conrelid=c.oid)
    ) ORDER BY c.relname),'[]'::jsonb)::text,'UTF8')),'hex') AS hash
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
      AND c.relname=ANY($1::text[])""", [list(LEGACY_TABLES)], read_only=True)
    parts.append(controls[0]['hash'])
    parts.append(stage.query("SELECT encode(sha256(convert_to(coalesce(string_agg(id::text,',' ORDER BY id),''),'UTF8')),'hex') AS hash FROM auth.users", read_only=True)[0]['hash'])
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()


class Probe:
    def __init__(self, stage):
        self.stage = stage
        self.users = []
        self.houses = []
        self.tokens = []
        self.checks = []
        self.phase = 'identity'
        self.public_key = self.admin_key = ''
        self.run_id = uuid.uuid4().hex

    def check(self, label, condition):
        if not condition:
            raise StagingError('Assertion failed: ' + label)
        self.checks.append(label)

    def admin(self, method, suffix, body=None):
        headers = {'apikey': self.admin_key}
        if not self.admin_key.startswith('sb_secret_'):
            headers['Authorization'] = 'Bearer ' + self.admin_key
        return self.stage.transport.request(method, PROJECT_URL + '/auth/v1/admin/users' + suffix, headers, body)

    def rpc(self, name, body=None, who=0):
        headers = {'apikey': self.public_key}
        if who is not None:
            headers['Authorization'] = 'Bearer ' + self.tokens[who]
        return self.stage.transport.request('POST', PROJECT_URL + '/rest/v1/rpc/finance_' + name,
                                            headers, body or {})

    def run(self):
        self.phase = 'create fake Auth users'
        self.public_key, self.admin_key = self.stage.keys()
        emails = []
        for index in range(4):
            email = 'accounts-' + self.run_id + '-' + str(index) + '@example.invalid'
            emails.append(email)
            password = secrets.token_urlsafe(36)
            status, user = self.admin('POST', '', {'email': email, 'password': password,
                'email_confirm': True, 'app_metadata': {'finance_accounts_probe': self.run_id}})
            self.check('fake confirmed Auth account ' + str(index + 1),
                       status in (200, 201) and isinstance(user, dict) and bool(user.get('id')))
            self.users.append(str(uuid.UUID(user['id'])))
            status, session = self.stage.transport.request('POST', PROJECT_URL + '/auth/v1/token?grant_type=password',
                {'apikey': self.public_key}, {'email': email, 'password': password})
            self.check('real GoTrue password session ' + str(index + 1), status == 200
                       and isinstance(session, dict) and bool(session.get('access_token')))
            self.tokens.append(session['access_token'])

        self.phase = 'independent households'
        request_id = str(uuid.uuid4())
        payload = {'p_name': 'Учебная семья A', 'p_timezone': 'Europe/Moscow', 'p_request_id': request_id}
        status, house = self.rpc('create_household', payload)
        self.check('create independent household', status == 200 and isinstance(house, dict) and bool(house.get('id')))
        a = str(uuid.UUID(house['id']))
        self.houses.append(a)
        self.check('create request retry is idempotent', self.rpc('create_household', payload) == (200, house))
        status, other = self.rpc('create_household', {'p_name': 'Учебная семья B',
            'p_timezone': 'Asia/Yekaterinburg', 'p_request_id': str(uuid.uuid4())}, who=3)
        self.check('create second independent household', status == 200 and isinstance(other, dict) and bool(other.get('id')))
        b = str(uuid.UUID(other['id']))
        self.houses.append(b)
        for target, actor in ((a, 3), (b, 0)):
            self.check('foreign household read denied ' + str(actor),
                       self.rpc('read_state', {'p_household_id': target}, who=actor)[0] in (401, 403))
        status, rows = self.rpc('read_state', {'p_household_id': a})
        self.check('new family has no inherited financial history', status == 200 and len(rows) == 1
                   and rows[0]['data']['entries'] == [] and rows[0]['data']['birthdays'] == []
                   and rows[0]['data']['installments'] == [])
        original = rows[0]

        self.phase = 'address bound invitations'
        invite_tokens = []
        for actor, role in ((1, 'editor'), (2, 'viewer')):
            raw_token = secrets.token_hex(32)
            invite_tokens.append(raw_token)
            status, invite = self.rpc('create_invite', {'p_household_id': a, 'p_email': emails[actor],
                'p_role': role, 'p_request_id': str(uuid.uuid4()),
                'p_token_hash': hashlib.sha256(raw_token.encode()).hexdigest()})
            self.check(role + ' invitation creates pending mail only', status == 200 and invite.get('mail_status') == 'pending')
            self.check('wrong email cannot accept ' + role,
                       self.rpc('accept_invite', {'p_token': raw_token}, who=3)[0] in (400, 401, 403))
            status, accepted = self.rpc('accept_invite', {'p_token': raw_token}, who=actor)
            self.check(role + ' accepts own address-bound invitation', status == 200
                       and accepted.get('role') == role and accepted.get('id') == a)

        self.phase = 'real PostgREST roles and CAS'
        changed = deepcopy(original['data'])
        changed['entries'] = [{'id': str(uuid.uuid4()), 'type': 'expense', 'amount': 123.45,
            'date': '2026-10-26', 'category': 'Продукты', 'who': 'Общее', 'place': 'Учебный магазин'}]
        cas = {'p_household_id': a, 'p_expected_revision': original['sync_revision'],
               'p_data': changed, 'p_request_id': str(uuid.uuid4())}
        self.check('viewer direct CAS denied', self.rpc('state_cas', cas, who=2)[0] in (401, 403))
        self.check('anonymous direct CAS denied', self.rpc('state_cas', cas, who=None)[0] in (401, 403))
        status, ack = self.rpc('state_cas', cas, who=1)
        self.check('editor writes exact fictional expense', status == 200 and ack.get('status') == 'written'
                   and ack.get('data') == changed)
        self.check('CAS request retry is idempotent', self.rpc('state_cas', cas, who=1) == (200, ack))
        status, viewed = self.rpc('read_state', {'p_household_id': a}, who=2)
        self.check('viewer reads current expense', status == 200 and viewed[0]['data'] == changed)
        self.check('editor cannot change family roles', self.rpc('set_member_role',
            {'p_household_id': a, 'p_user_id': self.users[2], 'p_role': 'editor'}, who=1)[0] in (401, 403))
        self.check('last owner cannot be removed', self.rpc('remove_member',
            {'p_household_id': a, 'p_user_id': self.users[0]})[0] in (400, 409))

        self.phase = 'access revocation with stale JWT'
        status, _ = self.rpc('remove_member', {'p_household_id': a, 'p_user_id': self.users[1]})
        self.check('owner removes editor', status == 200)
        self.check('old JWT cannot read after removal', self.rpc('read_state', {'p_household_id': a}, who=1)[0] in (401, 403))
        status, denied_write = self.rpc('state_cas', cas, who=1)
        self.check('old JWT cannot write after removal', status in (401, 403) or
                   (status == 200 and denied_write.get('status') == 'not_found' and denied_write.get('data') is None))
        self.check('old invitation cannot restore access',
                   self.rpc('accept_invite', {'p_token': invite_tokens[0]}, who=1)[0] in (400, 401, 403))
        status, final = self.rpc('read_state', {'p_household_id': a})
        self.check('removing access preserves financial history', status == 200 and final[0]['data'] == changed)

    def cleanup(self):
        # Discover this run's exact markers too: an accepted POST whose response
        # was lost must not leave an untracked user/household behind.
        records = self.stage.query("SELECT id,email FROM auth.users WHERE raw_app_meta_data->>'finance_accounts_probe'=$1", [self.run_id], read_only=True)
        allowed_emails = {'accounts-' + self.run_id + '-' + str(i) + '@example.invalid' for i in range(4)}
        own = []
        for record in records:
            if record.get('email') not in allowed_emails:
                raise StagingError('Refusing cleanup of an unrecognized test marker')
            own.append(str(uuid.UUID(record['id'])))
        errors = []
        if own:
            try:
                self.stage.query('DELETE FROM finance_app.households WHERE created_by=ANY($1::uuid[])', [own])
            except Exception:
                errors.append('household cleanup')
        for user_id in reversed(own):
            try:
                status, record = self.admin('GET', '/' + user_id)
                if status != 200 or not isinstance(record, dict) or record.get('app_metadata', {}).get('finance_accounts_probe') != self.run_id or record.get('email') not in allowed_emails:
                    raise StagingError('Refusing cleanup of an unrecognized test account')
                status, _ = self.admin('DELETE', '/' + user_id)
                if status not in (200, 204):
                    raise StagingError('Test Auth cleanup failed')
            except Exception:
                errors.append('Auth cleanup')
        remaining = self.stage.query("SELECT count(*) AS count FROM auth.users WHERE raw_app_meta_data->>'finance_accounts_probe'=$1", [self.run_id], read_only=True)
        if errors or remaining[0]['count']:
            raise StagingError('Test account cleanup incomplete')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true', help='Install 004 only into the fresh finance_app namespace')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    migration_bytes = MIGRATION.read_bytes()
    source_hash = hashlib.sha256(migration_bytes).hexdigest()
    report = {'kind': 'fixed_staging_public_accounts', 'status': 'failed', 'phase': 'identity',
              'migration_sha256': source_hash, 'checks': [], 'emails_sent': 0,
              'limits': ['Admin-confirmed fake Auth accounts: this does not test hosted signup/SMTP.',
                         'Local real GoTrue/SMTP/browser acceptance is separate evidence.']}
    stage = Staging(os.environ.get(TOKEN_NAME))
    probe = Probe(stage)
    before = None
    started = time.monotonic()
    try:
        stage.verify_identity()
        before = legacy_fingerprint(stage)
        exists = stage.query("SELECT to_regnamespace('finance_app') IS NOT NULL AS present", read_only=True)[0]['present']
        if args.install:
            if exists:
                raise StagingError('finance_app already exists; never reset or overwrite it')
            probe.phase = 'install separate staging namespace'
            migration = migration_bytes.decode('utf-8').rstrip()
            if not migration.endswith('\nCOMMIT;'):
                raise StagingError('Migration transaction boundary changed; review required')
            marker_sql = "COMMENT ON SCHEMA finance_app IS 'public-accounts-004-sha256:" + source_hash + "';\n"
            stage.query(migration[:-len('COMMIT;')] + marker_sql + 'COMMIT;')
            stage.query("NOTIFY pgrst, 'reload schema';")
        elif not exists:
            raise StagingError('Missing separate accounts namespace; explicit --install required')
        marker = stage.query("SELECT obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname='finance_app'",
                             read_only=True)
        probe.check('installed staging migration matches reviewed source', marker[0]['marker'] == 'public-accounts-004-sha256:' + source_hash)
        probe.run()
        report['status'] = 'passed'
    except Exception:
        # Never emit exceptions containing Auth/provider body or user credentials.
        report['status'] = 'failed'
    finally:
        report['phase'] = probe.phase
        try:
            probe.cleanup()
            report['created_test_accounts_removed'] = True
        except Exception:
            report['status'] = 'failed'
            report['created_test_accounts_removed'] = False
        try:
            unchanged = before is not None and legacy_fingerprint(stage) == before
            report['legacy_fixture_unchanged'] = unchanged
            if not unchanged:
                report['status'] = 'failed'
        except Exception:
            report['status'] = 'failed'
            report['legacy_fixture_unchanged'] = False
        report['checks'] = probe.checks
        report['assertion_count'] = len(probe.checks)
        report['elapsed_seconds'] = round(time.monotonic() - started, 2)
        if report['status'] == 'passed':
            report['phase'] = 'complete'
    raw = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(raw)
    print(raw, end='')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Inspect/bootstrap/test only the explicitly selected fictional Supabase project.

No configurable host, production fallback, token logging, or destructive reset.
The management token is supplied through a protected proxy binding. Project keys,
fictional passwords and user sessions remain in memory for this invocation.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid

ROOT = Path(__file__).resolve().parents[1]
PROJECT_REF = "iqpoxphtvtogjowruufe"
PROJECT_NAME = "marichevy-finance-staging"
MANAGEMENT = "https://api.supabase.com/v1/projects/" + PROJECT_REF
PROJECT_URL = "https://" + PROJECT_REF + ".supabase.co"
TOKEN_NAME = "STAGING_SUPABASE_MANAGEMENT_TOKEN"


class StagingError(RuntimeError):
    """Safe error messages contain no response bodies or credential values."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Transport:
    def __init__(self):
        self.opener = build_opener(NoRedirect())

    def request(self, method, url, headers=None, body=None):
        parsed = urlsplit(url)
        path = parsed.path
        management_path = "/v1/projects/" + PROJECT_REF
        valid_origin = (parsed.scheme == "https" and not parsed.fragment
                        and parsed.netloc in ("api.supabase.com", PROJECT_REF + ".supabase.co"))
        valid_path = (unquote(path) == path and "//" not in path
                      and not any(piece in (".", "..") for piece in path.split("/")))
        allowed = ((parsed.netloc == "api.supabase.com"
                    and (path == management_path or path.startswith(management_path + "/")))
                   or (parsed.netloc == PROJECT_REF + ".supabase.co"
                       and (path.startswith("/auth/v1/") or path.startswith("/rest/v1/"))))
        if not (valid_origin and valid_path and allowed):
            raise StagingError("Destination is outside the fixed staging boundary")
        # Do not follow redirects with authorization headers.
        data = None if body is None else json.dumps(body).encode()
        request = Request(url, data=data, method=method,
                          headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with self.opener.open(request, timeout=30) as response:
                status, raw = response.status, response.read()
        except HTTPError as error:
            status, raw = error.code, error.read()
        except (URLError, TimeoutError, OSError):
            raise StagingError("Staging request failed: check network policy, TLS and service health") from None
        try:
            result = json.loads(raw) if raw else None
        except (ValueError, UnicodeError):
            result = None
        return status, result


class Staging:
    def __init__(self, token, transport=None):
        if not token:
            raise StagingError("Missing protected environment binding: " + TOKEN_NAME)
        self.token = token
        self.transport = transport or Transport()
        self.identity_verified = False
        self.checks = []

    def management(self, method, suffix="", body=None):
        if suffix and not self.identity_verified:
            raise StagingError("Project identity must be verified before further operations")
        status, result = self.transport.request(method, MANAGEMENT + suffix,
            {"Authorization": "Bearer " + self.token}, body)
        allowed_statuses = (200, 201) if method == "POST" and suffix == "/database/query" else (200,)
        if status not in allowed_statuses:
            raise StagingError("Management API returned HTTP " + str(status))
        return result

    def verify_identity(self):
        self.identity_verified = False
        project = self.management("GET")
        if not isinstance(project, dict) or project.get("ref", project.get("id")) != PROJECT_REF \
                or project.get("name") != PROJECT_NAME:
            raise StagingError("Project ref/name mismatch: no further operation is allowed")
        if project.get("status") != "ACTIVE_HEALTHY":
            raise StagingError("Staging project is not ACTIVE_HEALTHY")
        self.identity_verified = True
        return {key: project.get(key) for key in ("ref", "name", "status", "region")}

    def query(self, sql, parameters=(), read_only=False):
        result = self.management("POST", "/database/query",
            {"query": sql, "parameters": list(parameters), "read_only": read_only})
        if not isinstance(result, list):
            raise StagingError("Management query returned an unexpected result shape")
        return result

    def inspect(self):
        identity = self.verify_identity()
        inventory = self.query("""SELECT
          (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')) AS public_relations,
          (SELECT count(*) FROM auth.users) AS auth_users,
          to_regnamespace('marichevy_staging') IS NOT NULL AS fixture_exists;""", read_only=True)
        if len(inventory) != 1:
            raise StagingError("Unexpected inventory result")
        return {"project": identity, "inventory": inventory[0]}

    def keys(self):
        keys = self.management("GET", "/api-keys?reveal=true")
        if not isinstance(keys, list):
            raise StagingError("Unexpected staging key metadata")
        def choose(kind, legacy):
            modern = [item.get("api_key") for item in keys if item.get("type") == kind and item.get("api_key")]
            old = [item.get("api_key") for item in keys if item.get("name") == legacy and item.get("api_key")]
            if modern or old:
                return (modern or old)[0]
            raise StagingError("Staging project has no usable " + kind + " key; no keys were changed")
        return choose("publishable", "anon"), choose("secret", "service_role")

    def check(self, label, condition):
        if not condition:
            raise StagingError("Hosted assertion failed: " + label)
        self.checks.append(label)

    def _fixture(self, versions=(1, 2)):
        """Inspect only the exact previously verified fictional installation."""
        inspected = self.inspect()
        inventory = inspected['inventory']
        if (inventory.get('auth_users') != 3 or inventory.get('fixture_exists') is not True
                or inventory.get('public_relations') not in (2, 5)):
            raise StagingError('Checks require exactly the known two-family/three-user fixture')
        marker = self.query('SELECT project_ref,project_name,fixture_version FROM marichevy_staging.fixture_registry', read_only=True)
        if (len(marker) != 1 or marker[0].get('project_ref') != PROJECT_REF
                or marker[0].get('project_name') != PROJECT_NAME
                or marker[0].get('fixture_version') not in versions):
            raise StagingError('Staging fixture marker does not match the expected installation/version')
        version = marker[0]['fixture_version']
        if inventory['public_relations'] != {1: 2, 2: 5}[version]:
            raise StagingError('Staging relation count disagrees with the fixture version')
        membership_table = {1: 'staging_membership', 2: 'household_members'}[version]
        members = self.query("SELECT m.household_id,m.user_id,u.email, "
            "u.raw_app_meta_data->>'marichevy_staging_run' AS run_id "
            "FROM public." + membership_table + " m JOIN auth.users u ON u.id=m.user_id "
            "ORDER BY m.household_id,m.user_id", read_only=True)
        if len(members) != 3 or len({member.get('run_id') for member in members}) != 1:
            raise StagingError('Unknown fixture membership; no account password will be changed')
        for member in members:
            run, email = member.get('run_id') or '', member.get('email') or ''
            if not re.fullmatch('[0-9a-f]{32}', run) or not re.fullmatch('stage-' + run + '-[012]@example[.]invalid', email):
                raise StagingError('Refusing to change a non-fixture authentication account')
            try:
                uuid.UUID(member['user_id']); uuid.UUID(member['household_id'])
            except (KeyError, ValueError, TypeError, AttributeError):
                raise StagingError('Invalid fictional membership identifiers') from None
        if len({member['email'] for member in members}) != 3 or len({member['user_id'] for member in members}) != 3:
            raise StagingError('Expected three distinct fictional accounts')
        groups = {}
        for member in members:
            groups.setdefault(member['household_id'], []).append(member)
        if sorted(len(group) for group in groups.values()) != [1, 2]:
            raise StagingError('Expected two fictional households with two/one members')
        relations = self.query("""SELECT array_agg(c.relname::text ORDER BY c.relname) AS tables
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')""", read_only=True)
        expected = {1: ['family_state', 'staging_membership'],
                    2: ['family_chore_deliveries', 'family_state', 'household_members', 'households', 'staging_membership']}[version]
        if relations != [{'tables': expected}]:
            raise StagingError('Unexpected public relation names; no fixture account will be changed')
        family_metadata = self.query("""SELECT household_id,sync_protocol,sync_revision,
            updated_at,updated_by,last_request_id,md5(data::text) AS data_md5
            FROM public.family_state ORDER BY household_id""", read_only=True)
        if (len(family_metadata) != 2
                or {row.get('household_id') for row in family_metadata} != set(groups)
                or any(row.get('sync_protocol') != 2 or type(row.get('sync_revision')) is not int
                       or row['sync_revision'] < 0 or not row.get('updated_at')
                       or not re.fullmatch('[0-9a-f]{32}', row.get('data_md5') or '') for row in family_metadata)):
            raise StagingError('Expected two protected fictional family snapshots with valid revision metadata')
        if version == 2:
            retained = self.query('SELECT household_id,user_id FROM public.staging_membership ORDER BY household_id,user_id', read_only=True)
            expected_pairs = [{'household_id': member['household_id'], 'user_id': member['user_id']} for member in members]
            if retained != expected_pairs:
                raise StagingError('V2 membership differs from the preserved fictional provenance')
            if self.query('SELECT count(*) AS deliveries FROM public.family_chore_deliveries', read_only=True) != [{'deliveries': 0}]:
                raise StagingError('Expected an empty fictional delivery fixture; no messages are tested')
        own_household, own = next((house, group) for house, group in groups.items() if len(group) == 2)
        outsider = next(group[0] for group in groups.values() if len(group) == 1)
        return {'inspected': inspected, 'fixture_version': version, 'members': [*own, outsider],
                'own_household': own_household, 'other_household': outsider['household_id'],
                'family_metadata': family_metadata}

    def _fixture_credentials(self, fixture, *, sessions=False):
        public_key, admin_key = self.keys()
        headers = {'apikey': admin_key}
        if not admin_key.startswith('sb_secret_'):
            headers['Authorization'] = 'Bearer ' + admin_key
        credentials, tokens = [], []
        for index, member in enumerate(fixture['members']):
            password = secrets.token_urlsafe(36)
            status, result = self.transport.request('PUT', PROJECT_URL + '/auth/v1/admin/users/' + member['user_id'],
                headers, {'password': password})
            self.check('fixture-only password renewed ' + str(index + 1), status == 200 and isinstance(result, dict)
                       and result.get('id') == member['user_id'])
            credentials.append({'email': member['email'], 'password': password})
            if sessions:
                status, session = self.transport.request('POST', PROJECT_URL + '/auth/v1/token?grant_type=password',
                    {'apikey': public_key}, {'email': member['email'], 'password': password})
                self.check('fictional session identity ' + str(index + 1), status == 200 and isinstance(session, dict)
                    and bool(session.get('access_token')) and session.get('user', {}).get('id') == member['user_id'])
                tokens.append(session['access_token'])
        return public_key, credentials, tokens, admin_key

    def _verify_hardening(self):
        capabilities = self.query("""SELECT t.name AS table_name,r.name AS role_name,
            has_table_privilege(r.name,format('public.%I',t.name),'TRUNCATE') AS can_truncate,
            has_table_privilege(r.name,format('public.%I',t.name),'TRIGGER') AS can_trigger
            FROM unnest(ARRAY['family_state','households','household_members','family_chore_deliveries']) t(name)
            CROSS JOIN unnest(ARRAY['anon','authenticated']) r(name) ORDER BY t.name,r.name""", read_only=True)
        expected = {(table, role) for table in ['family_state','households','household_members','family_chore_deliveries']
                    for role in ['anon','authenticated']}
        self.check('V2 anonymous/authenticated lack TRUNCATE and TRIGGER capabilities',
            {(row.get('table_name'), row.get('role_name')) for row in capabilities} == expected
            and len(capabilities) == 8 and all(row.get('can_truncate') is False and row.get('can_trigger') is False for row in capabilities))
        try:
            reviewed = (ROOT / 'server/003_bound_membership_lookup.sql').read_text()
        except OSError:
            raise StagingError('Missing reviewed membership lookup SQL; hardening is unverified') from None
        bodies = re.findall(r'AS \$membership\$(.*?)\$membership\$;', reviewed, flags=re.S)
        if len(bodies) != 1:
            raise StagingError('Reviewed membership function marker changed; no account will be renewed')
        expected_hash = hashlib.md5(re.sub(r'\s', '', bodies[0]).lower().encode()).hexdigest()
        helpers = self.query("""SELECT pg_get_userbyid(p.proowner) AS owner,p.prosecdef AS security_definer,
            p.provolatile::text AS volatility,p.proleakproof AS leakproof,p.proconfig AS configuration,
            p.proargnames AS arguments,p.pronargdefaults AS default_arguments,p.provariadic AS variadic,
            l.lanname AS language,md5(regexp_replace(lower(p.prosrc),'[[:space:]]','','g')) AS normalized_source_md5,
            (SELECT count(*) FROM pg_proc q WHERE q.pronamespace='public'::regnamespace AND q.proname='is_household_member') AS overloads,
            has_function_privilege('anon',p.oid,'EXECUTE') AS anon_execute,
            has_function_privilege('authenticated',p.oid,'EXECUTE') AS authenticated_execute,
            has_function_privilege('service_role',p.oid,'EXECUTE') AS service_execute
            FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
            WHERE p.oid=to_regprocedure('public.is_household_member(uuid,uuid)')""", read_only=True)
        expected_helper = {'owner': 'postgres', 'security_definer': True, 'volatility': 'v', 'leakproof': False,
            'configuration': ['search_path=pg_catalog, public'], 'arguments': ['p_household_id','p_user_id'],
            'default_arguments': 0, 'variadic': 0, 'language': 'sql', 'normalized_source_md5': expected_hash,
            'overloads': 1, 'anon_execute': False, 'authenticated_execute': True, 'service_execute': True}
        self.check('V2 exact reviewed self-bound helper and execution grants verified', helpers == [expected_helper])
        return {'helper_normalized_source_md5': expected_hash,
                'helper_sql_sha256': hashlib.sha256(reviewed.encode()).hexdigest()}

    def browser(self):
        """Resume only exact V1 or V2 synthetic fixtures; never reset real users."""
        fixture = self._fixture()
        hardening = self._verify_hardening() if fixture['fixture_version'] == 2 else None
        public_key, credentials, _, _ = self._fixture_credentials(fixture)
        from staging_browser import BrowserCheckError, verify_browser_flow
        try:
            browser_result = verify_browser_flow(self.transport, public_key, fixture['own_household'], credentials)
        except BrowserCheckError as error:
            self.checks.extend(error.checks_completed)
            self.browser_diagnostics = error.diagnostics
            raise StagingError(str(error)) from None
        except ValueError:
            raise StagingError('Staging client sanitization failed; no browser check was accepted') from None
        self.checks.extend(browser_result['checks'])
        return {**fixture['inspected'], 'outcome': 'passed', 'checks': self.checks,
                'fixture_version': fixture['fixture_version'], 'hardening_verified': hardening is not None,
                'hardening': hardening,
                'fixture_only': True, 'production_tested': False,
                'browser': browser_result,
                'client_sha256': hashlib.sha256((ROOT / 'index.html').read_bytes()).hexdigest(),
                'network_path': 'real verified HTTPS forwarded through Playwright route bridge; native CORS untested'}

    def membership(self):
        """Nondestructively evolve verified V1, then verify the supported V2 API."""
        before = self._fixture(versions=(1, 2))
        evolution_applied = before['fixture_version'] == 1
        sql_files = ['staging_membership_v2.sql', '002_restrict_table_capabilities.sql', '003_bound_membership_lookup.sql']
        hashes = {}
        try:
            sources = {name: (ROOT / 'server' / name).read_text() for name in sql_files}
        except OSError:
            raise StagingError('Missing reviewed V2 SQL files; no fixture migration was started') from None
        for name, source in sources.items():
            hashes[name] = hashlib.sha256(source.encode()).hexdigest()
            if name == 'staging_membership_v2.sql' and not evolution_applied:
                continue
            if name == 'staging_membership_v2.sql':
                source = "BEGIN; SET LOCAL marichevy.staging_project_ref='" + PROJECT_REF + "';\n" + source + "\nCOMMIT;"
            self.query(source)
        fixture = self._fixture(versions=(2,))
        self.check('V2 migration preserves family JSON and revision metadata', before['family_metadata'] == fixture['family_metadata'])
        self.check('V2 migration preserves all fictional membership identities',
            before['members'] == fixture['members'])
        hardening = self._verify_hardening()
        self.query("NOTIFY pgrst, 'reload schema';")
        public_key, _, sessions, admin_key = self._fixture_credentials(fixture, sessions=True)
        house, other = fixture['own_household'], fixture['other_household']
        users = [member['user_id'] for member in fixture['members']]
        def api(method, path, who=0, body=None, extra=None):
            headers = {'apikey': public_key, 'Prefer': 'return=representation', **(extra or {})}
            if who is not None:
                headers['Authorization'] = 'Bearer ' + sessions[who]
            return self.transport.request(method, PROJECT_URL + path, headers, body)
        def read(table, columns, filter_query='', who=0):
            order = {'household_members': 'household_id,user_id', 'households': 'id', 'family_state': 'household_id'}[table]
            return api('GET', '/rest/v1/' + table + '?select=' + columns + filter_query + '&order=' + order, who)
        for attempt in range(15):
            status, own_houses = read('households', 'id,name', '&id=eq.' + house)
            if status == 200 and isinstance(own_houses, list) and len(own_houses) == 1:
                break
            if status not in (404, 503):
                raise StagingError('V2 household read failed: HTTP ' + str(status))
            time.sleep(1)
        self.check('V2 own household visible', status == 200 and len(own_houses) == 1 and own_houses[0].get('id') == house)
        self.check('V2 foreign household invisible', read('households', 'id,name', '&id=eq.' + house, 2) == (200, []))
        own_members = read('household_members', 'household_id,user_id,role', '&household_id=eq.' + house)
        self.check('V2 family members visible to own member', own_members[0] == 200 and isinstance(own_members[1], list)
            and {row.get('user_id') for row in own_members[1]} == set(users[:2]))
        self.check('V2 family members invisible to foreign family', read('household_members', 'user_id', '&household_id=eq.' + house, 2) == (200, []))
        status, own_rows = read('family_state', '*', '&household_id=eq.' + house)
        self.check('V2 own family snapshot visible', status == 200 and isinstance(own_rows, list) and len(own_rows) == 1)
        self.check('V2 second member sees same snapshot', read('family_state', '*', '&household_id=eq.' + house, 1) == (200, own_rows))
        self.check('V2 foreign family snapshot invisible', read('family_state', '*', '&household_id=eq.' + house, 2) == (200, []))
        for table, columns in [('family_state', 'household_id'), ('household_members', 'user_id'), ('households', 'id')]:
            status, rows = read(table, columns, who=None)
            self.check('V2 anonymous ' + table + ' exposes no rows', status in (401, 403) or (status == 200 and rows == []))
        baselines = {'households': own_houses, 'household_members': own_members[1]}
        for table, identifier, create, update in [
            ('households', '&id=eq.' + house, {'id': str(uuid.uuid4()), 'name': 'Forbidden fictional household'}, {'name': 'Forbidden change'}),
            ('household_members', '&household_id=eq.' + house, {'household_id': house, 'user_id': users[2], 'role': 'member'}, {'role': 'owner'})]:
            for method, body in [('POST', create), ('PATCH', update), ('DELETE', None)]:
                path = '/rest/v1/' + table + ('?select=*' if method == 'POST' else '?select=*' + identifier)
                status, rows = api(method, path, body=body)
                self.check('V2 member cannot ' + method + ' ' + table,
                    status in (401, 403) or (method != 'POST' and status == 200 and rows == []))
        self.check('V2 denied household mutations preserve rows', read('households', 'id,name', '&id=eq.' + house) == (200, baselines['households']))
        self.check('V2 denied membership mutations preserve rows', read('household_members', 'household_id,user_id,role', '&household_id=eq.' + house) == (200, baselines['household_members']))
        for who, user_id, target_house, expected, label in [
            (0, users[0], house, True, 'own self'), (0, users[0], other, False, 'foreign self'),
            (2, users[0], house, False, 'other user'), (None, users[0], house, None, 'anonymous')]:
            status, value = api('POST', '/rest/v1/rpc/is_household_member', who,
                {'p_household_id': target_house, 'p_user_id': user_id})
            self.check('V2 helper bounded lookup ' + label,
                status in (401, 403) if who is None else status == 200 and value is expected)
        service_headers = {'apikey': admin_key}
        if not admin_key.startswith('sb_secret_'):
            service_headers['Authorization'] = 'Bearer ' + admin_key
        status, value = self.transport.request('POST', PROJECT_URL + '/rest/v1/rpc/is_household_member', service_headers,
            {'p_household_id': house, 'p_user_id': users[0]})
        self.check('V2 helper preserves service-role lookup without user identity', status == 200 and value is True)
        for who in (2, None):
            status, value = api('POST', '/rest/v1/rpc/family_state_cas', who,
                {'p_household_id': house, 'p_expected_revision': own_rows[0]['sync_revision'],
                 'p_data': own_rows[0]['data'], 'p_request_id': str(uuid.uuid4())})
            self.check('V2 foreign/anonymous CAS denied ' + str(who),
                status in (401, 403) if who is None else status == 200 and isinstance(value, dict) and value.get('status') == 'not_found')
        self.check('V2 denied requests preserve complete family snapshot', read('family_state', '*', '&household_id=eq.' + house) == (200, own_rows))
        receipt = str(uuid.uuid4())
        status, ack = api('POST', '/rest/v1/rpc/family_state_cas', body={
            'p_household_id': house, 'p_expected_revision': own_rows[0]['sync_revision'],
            'p_data': own_rows[0]['data'], 'p_request_id': receipt})
        self.check('V2 own CAS accepts exact snapshot with server revision', status == 200 and isinstance(ack, dict)
            and ack.get('status') == 'written' and ack.get('protocol') == 2
            and ack.get('revision') == own_rows[0]['sync_revision'] + 1
            and ack.get('request_id') == receipt and ack.get('data') == own_rows[0]['data'])
        final_status, final_rows = read('family_state', '*', '&household_id=eq.' + house)
        self.check('V2 own CAS preserves JSON and attributes real writer', final_status == 200 and len(final_rows) == 1
            and final_rows[0].get('data') == own_rows[0]['data'] and final_rows[0].get('sync_revision') == ack['revision']
            and final_rows[0].get('updated_by') == users[0])
        self.check('V2 second member sees acknowledged version', read('family_state', '*', '&household_id=eq.' + house, 1) == (200, final_rows))
        for method, path, body in [
            ('PATCH', '/rest/v1/family_state?household_id=eq.' + house, {'data': {}}),
            ('POST', '/rest/v1/family_state?on_conflict=household_id', {'household_id': house, 'data': {}})]:
            status, _ = api(method, path, body=body, extra={'Prefer': 'resolution=merge-duplicates,return=representation'})
            self.check('V2 legacy own ' + method + ' rejected', status == 409)
        status, value = api('DELETE', '/rest/v1/family_state?household_id=eq.' + house)
        self.check('V2 own DELETE filtered by production-shaped RLS', status in (401, 403, 409) or (status == 200 and value == []))
        for method, body in [('PATCH', {'data': {}}), ('DELETE', None)]:
            status, value = api(method, '/rest/v1/family_state?household_id=eq.' + house, who=2, body=body)
            self.check('V2 foreign direct ' + method + ' changes nothing', status in (401, 403) or (status == 200 and value == []))
        self.check('V2 rejected legacy requests preserve acknowledged snapshot', read('family_state', '*', '&household_id=eq.' + house) == (200, final_rows))
        self.check('V2 delivery fixture remains empty', self.query('SELECT count(*) AS deliveries FROM public.family_chore_deliveries', read_only=True) == [{'deliveries': 0}])
        return {**fixture['inspected'], 'outcome': 'passed', 'checks': self.checks,
                'fixture_version': 2, 'fixture_only': True, 'production_tested': False,
                'migration_preserved_family_metadata': True, 'sql_sha256': hashes,
                'evolution_applied': evolution_applied, 'hardening_verified': True, 'hardening': hardening,
                'helper_lookup': 'self-bound authenticated lookups; anonymous execution denied',
                'capability_validation': 'effective catalog privileges; no generic SQL/TRUNCATE RPC is exposed or fabricated',
                'limitations': ['Existing V1 33-check report is separate historical evidence.',
                    'Empty delivery schema only; no notification or payment is sent.']}

    def run(self):
        inspected = self.inspect()
        inventory = inspected["inventory"]
        if inventory.get("public_relations") != 0 or inventory.get("auth_users") != 0 or inventory.get("fixture_exists"):
            raise StagingError("Run requires a fresh empty staging project; existing work will not be reset")
        fixture = (ROOT / "server/staging_fixture.sql").read_text()
        self.query("BEGIN; SET LOCAL marichevy.staging_project_ref = '" + PROJECT_REF + "';\n" + fixture + "\nCOMMIT;")
        migration = (ROOT / "server/001_family_state_cas.sql").read_text()
        self.query(migration)
        public_key, admin_key = self.keys()
        auth_headers = {"apikey": admin_key}
        # A legacy admin JWT also uses Authorization. Modern secret keys belong
        # in apikey; they are not user JWTs and must never authorize RLS tests.
        if not admin_key.startswith("sb_secret_"):
            auth_headers["Authorization"] = "Bearer " + admin_key
        run_id = uuid.uuid4().hex
        users, sessions = [], []
        for index in range(3):
            password = secrets.token_urlsafe(36)
            email = f"stage-{run_id}-{index}@example.invalid"
            status, user = self.transport.request("POST", PROJECT_URL + "/auth/v1/admin/users", auth_headers,
                {"email": email, "password": password, "email_confirm": True,
                 "app_metadata": {"marichevy_staging_run": run_id}})
            self.check("fictional auth user " + str(index + 1), status in (200, 201) and isinstance(user, dict) and bool(user.get("id")))
            users.append(user["id"])
            status, session = self.transport.request("POST", PROJECT_URL + "/auth/v1/token?grant_type=password",
                {"apikey": public_key}, {"email": email, "password": password})
            self.check("real password session " + str(index + 1), status == 200 and isinstance(session, dict) and bool(session.get("access_token")))
            sessions.append(session["access_token"])
        houses = [str(uuid.uuid4()), str(uuid.uuid4())]
        data = {"entries": [], "goals": [], "birthdays": [], "boardItems": [], "chores": [],
                "installments": [], "settings": {}, "futureCollection": [{"id": "opaque", "keep": [1, True]}]}
        for house, user_id in zip([houses[0], houses[0], houses[1]], users):
            self.query("INSERT INTO public.staging_membership(household_id,user_id) VALUES ($1::uuid,$2::uuid)", [house, user_id])
        for house in houses:
            self.query("INSERT INTO public.family_state(household_id,data) VALUES ($1::uuid,$2::jsonb)", [house, json.dumps(data)])
        # Explicitly request schema-cache refresh, then wait only for that change.
        self.query("NOTIFY pgrst, 'reload schema';")
        def api(method, path, who=0, body=None, extra=None):
            headers = {"apikey": public_key, **(extra or {})}
            if who is not None:
                headers["Authorization"] = "Bearer " + sessions[who]
            return self.transport.request(method, PROJECT_URL + path, headers, body)
        def read(house=houses[0], who=0):
            return api("GET", "/rest/v1/family_state?household_id=eq." + house + "&select=*", who)
        for _ in range(15):
            status, rows = read()
            if status == 200 and isinstance(rows, list) and len(rows) == 1:
                break
            if status not in (404, 503):
                raise StagingError("Staging table read failed: HTTP " + str(status))
            time.sleep(1)
        self.check("own household visible", status == 200 and len(rows) == 1 and rows[0]["data"] == data)
        self.check("second member sees same household", read(who=1)[1] == rows)
        self.check("other family cannot read", read(who=2) == (200, []))
        self.check("own family cannot read second family", read(houses[1]) == (200, []))
        self.check("anon cannot read family table", read(who=None)[0] in (401, 403))
        def cas(snapshot, revision, who=0, request_id=None, house=houses[0]):
            return api("POST", "/rest/v1/rpc/family_state_cas", who,
                {"p_household_id": house, "p_expected_revision": revision,
                 "p_data": snapshot, "p_request_id": request_id or str(uuid.uuid4())})
        status, response = cas(data, 0)
        self.check("protocol one refuses CAS", status == 200 and response.get("status") == "upgrade_required")
        self.query("UPDATE public.family_state SET sync_protocol=2 WHERE household_id IN ($1::uuid,$2::uuid)", houses)
        a, b = deepcopy(data), deepcopy(data)
        for snapshot, name, amount in [(a, "a", 1250.50), (b, "b", 3000)]:
            snapshot["entries"] = [{"id": "fictional-" + name, "type": "expense", "amount": amount,
                "date": "2026-10-23", "category": "Продукты", "who": "Общее"}]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(cas, a, 1, 0), pool.submit(cas, b, 1, 1)]
            answers = [future.result() for future in futures]
        self.check("real concurrent CAS has one winner", all(code == 200 for code, _ in answers)
                   and sorted(answer.get("status") for _, answer in answers) == ["conflict", "written"])
        conflict = next(answer for _, answer in answers if answer["status"] == "conflict")
        merged = deepcopy(conflict["data"])
        merged["entries"] = a["entries"] + b["entries"]
        receipt = str(uuid.uuid4())
        status, ack = cas(merged, conflict["revision"], request_id=receipt)
        self.check("conflict retry preserves both additions", status == 200 and ack.get("status") == "written" and ack.get("data") == merged)
        self.check("retry receipt is idempotent", cas(merged, conflict["revision"], request_id=receipt) == (200, ack))
        self.check("server revision advances exactly twice", ack["revision"] == 3)
        status, row = read()
        self.check("server owns update identity", row[0]["updated_by"] == users[0])
        self.check("both members see final snapshot", read(who=1)[1] == row)
        for method, path, payload in [
            ("PATCH", "/rest/v1/family_state?household_id=eq." + houses[0], {"data": {}}),
            ("PATCH", "/rest/v1/family_state?household_id=eq." + houses[0], {"sync_protocol": 1}),
            ("DELETE", "/rest/v1/family_state?household_id=eq." + houses[0], None),
            ("POST", "/rest/v1/family_state?on_conflict=household_id", {"household_id": houses[0], "data": {}}),
        ]:
            status, _ = api(method, path, body=payload, extra={"Prefer": "resolution=merge-duplicates,return=representation"})
            self.check("legacy " + method + " rejected: " + ("protocol" if payload == {"sync_protocol": 1} else "data"), status == 409)
        for outsider in [2, None]:
            status, result = cas({}, ack["revision"], who=outsider)
            self.check("foreign/anon CAS denied " + str(outsider),
                       (outsider == 2 and status == 200 and result.get("status") == "not_found")
                       or (outsider is None and status in (401, 403)))
        for method, payload in [("PATCH", {"data": {"forbidden": True}}), ("DELETE", None)]:
            status, result = api(method, "/rest/v1/family_state?household_id=eq." + houses[0],
                who=2, body=payload, extra={"Prefer": "return=representation"})
            self.check("foreign direct " + method + " cannot change family",
                       (status == 200 and result == []) or status in (401, 403))
        status, _ = api("POST", "/rest/v1/family_state?on_conflict=household_id", who=2,
            body={"household_id": houses[0], "data": {"forbidden": True}},
            extra={"Prefer": "resolution=merge-duplicates,return=representation"})
        self.check("foreign upsert denied", status in (401, 403, 409))
        status, _ = api("POST", "/rest/v1/staging_membership", who=2,
            body={"household_id": houses[0], "user_id": users[2]})
        self.check("outsider cannot add membership", status in (401, 403))
        self.check("denied writes changed no history", read()[1] == row)
        # Recover the exact synthetic JSON in an unexposed table. This is a fixture
        # restore check, never a claim that the real family's backup was verified.
        self.query("CREATE TABLE marichevy_staging.restore_check(data jsonb NOT NULL)")
        self.query("INSERT INTO marichevy_staging.restore_check(data) VALUES ($1::jsonb)", [json.dumps(merged)])
        restored = self.query("SELECT data FROM marichevy_staging.restore_check", read_only=True)
        self.check("synthetic server backup roundtrip", len(restored) == 1 and restored[0]["data"] == merged)
        before = read()[1][0]
        self.query("UPDATE public.family_state SET sync_protocol=1 WHERE household_id=$1::uuid AND sync_revision=$2::bigint",
                   [houses[0], before["sync_revision"]])
        rolled = read()[1][0]
        self.check("protocol rollback preserves JSON", rolled["data"] == before["data"] and rolled["sync_revision"] == before["sync_revision"] + 1)
        self.check("CAS disabled after rollback", cas(merged, rolled["sync_revision"])[1].get("status") == "upgrade_required")
        self.query("UPDATE public.family_state SET sync_protocol=2 WHERE household_id=$1::uuid AND sync_revision=$2::bigint",
                   [houses[0], rolled["sync_revision"]])
        self.check("reactivation preserves JSON", read()[1][0]["data"] == merged)
        return {**inspected, "outcome": "passed", "checks": self.checks,
                "households": houses, "fictional_user_ids": users,
                "fixture_only": True, "production_tested": False,
                "cas_sql_sha256": hashlib.sha256(migration.encode()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inspect", "run", "browser", "membership"])
    parser.add_argument("--report", type=Path, default=Path("/workspace/artifacts/supabase-staging-report.json"))
    args = parser.parse_args()
    staging = None
    observed_at = datetime.now(timezone.utc).isoformat()
    try:
        staging = Staging(os.environ.get(TOKEN_NAME))
        report = getattr(staging, args.command)()
        report["observed_at"] = observed_at
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print("Staging " + args.command + " completed; safe report: " + str(args.report))
        return 0
    except StagingError as error:
        report = {"observed_at": observed_at, "project_ref": PROJECT_REF,
                  "command": args.command, "outcome": "blocked" if staging is None else "failed",
                  "checks_completed": [] if staging is None else staging.checks,
                  "safe_error": str(error), "production_tested": False}
        if staging is not None and hasattr(staging, 'browser_diagnostics'):
            report['browser_diagnostics'] = staging.browser_diagnostics
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read production schema metadata only, using a narrowly scoped inspection token.

This tool cannot apply SQL, reveal API keys or read application/authentication rows.
Its two possible requests are a project identity GET and one fixed catalog SELECT.
The token is provided only through PRODUCTION_SUPABASE_INSPECTION_TOKEN.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
PROJECT_REF = "kqndxecziamypdjpxhyq"
PROJECT_NAME = "marichevy-finance"
TOKEN_NAME = "PRODUCTION_SUPABASE_INSPECTION_TOKEN"
PROJECT_URL = "https://api.supabase.com/v1/projects/" + PROJECT_REF

# Every relation below is a PostgreSQL catalog. No household/auth table is read.
# Defaults and function bodies are hashed inside PostgreSQL, never returned.
INVENTORY_SQL = r"""WITH
app_namespaces AS (
  SELECT oid, nspname FROM pg_catalog.pg_namespace
  WHERE nspname <> 'information_schema' AND nspname !~ '^pg_'
),
app_tables AS (
  SELECT c.*, n.nspname FROM pg_catalog.pg_class c
  JOIN app_namespaces n ON n.oid=c.relnamespace
  WHERE c.relkind IN ('r','p','v','m','f')
),
app_routines AS (
  SELECT p.*, n.nspname FROM pg_catalog.pg_proc p
  JOIN app_namespaces n ON n.oid=p.pronamespace
  WHERE p.prokind IN ('f','p')
),
test_roles AS (
  SELECT oid, rolname FROM pg_catalog.pg_roles
  WHERE rolname IN ('anon','authenticated','service_role')
)
SELECT pg_catalog.jsonb_build_object(
 'format', 'marichevy-schema-inventory-v1',
 'database_name', pg_catalog.current_database(),
 'server_version', pg_catalog.current_setting('server_version'),
 'catalog_only', true,
 'observed_db_schemas_setting', pg_catalog.current_setting('pgrst.db_schemas', true),
 'namespaces', COALESCE((SELECT pg_catalog.jsonb_agg(nspname ORDER BY nspname)
                         FROM app_namespaces), '[]'::jsonb),
 'tables', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'schema', t.nspname, 'name', t.relname, 'kind', t.relkind,
   'owner', pg_catalog.pg_get_userbyid(t.relowner),
   'rls_enabled', t.relrowsecurity, 'rls_forced', t.relforcerowsecurity,
   'columns', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
     'name', a.attname, 'position', a.attnum,
     'type', pg_catalog.format_type(a.atttypid,a.atttypmod),
     'not_null', a.attnotnull, 'identity', a.attidentity, 'generated', a.attgenerated,
     'has_default', a.atthasdef,
     'default_source_md5', CASE WHEN d.oid IS NULL THEN NULL
       ELSE pg_catalog.md5(pg_catalog.pg_get_expr(d.adbin,d.adrelid)) END,
     'column_acl', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
       'grantee', CASE WHEN x.grantee=0 THEN 'PUBLIC' ELSE pg_catalog.pg_get_userbyid(x.grantee) END,
       'privilege', x.privilege_type, 'grantable', x.is_grantable
     ) ORDER BY x.grantee,x.privilege_type) FROM pg_catalog.aclexplode(a.attacl) x), '[]'::jsonb),
     'effective_app_column_privileges', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
       'role', r.rolname,
       'select', pg_catalog.has_column_privilege(r.oid,t.oid,a.attnum,'SELECT'),
       'insert', pg_catalog.has_column_privilege(r.oid,t.oid,a.attnum,'INSERT'),
       'update', pg_catalog.has_column_privilege(r.oid,t.oid,a.attnum,'UPDATE')
     ) ORDER BY r.rolname) FROM test_roles r), '[]'::jsonb)
   ) ORDER BY a.attnum) FROM pg_catalog.pg_attribute a
   LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
   WHERE a.attrelid=t.oid AND a.attnum>0 AND NOT a.attisdropped), '[]'::jsonb),
   'constraints', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
     'name', k.conname, 'type', k.contype, 'validated', k.convalidated,
     'definition_md5', pg_catalog.md5(pg_catalog.pg_get_constraintdef(k.oid,true)),
     'definition_redacted', pg_catalog.regexp_replace(pg_catalog.pg_get_constraintdef(k.oid,true),
       $literal$(?:[eE])?'(?:[^'\\]|\\.|'')*'$literal$, $replacement$'<redacted>'$replacement$, 'g'),
     'columns', COALESCE((SELECT pg_catalog.jsonb_agg(a.attname ORDER BY key.position)
       FROM pg_catalog.unnest(k.conkey) WITH ORDINALITY key(attnum,position)
       JOIN pg_catalog.pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=key.attnum), '[]'::jsonb),
     'referenced_relation', (SELECT pg_catalog.jsonb_build_object('schema',n.nspname,'table',c.relname)
       FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=k.confrelid),
     'referenced_columns', COALESCE((SELECT pg_catalog.jsonb_agg(a.attname ORDER BY key.position)
       FROM pg_catalog.unnest(k.confkey) WITH ORDINALITY key(attnum,position)
       JOIN pg_catalog.pg_attribute a ON a.attrelid=k.confrelid AND a.attnum=key.attnum), '[]'::jsonb)
   ) ORDER BY k.conname) FROM pg_catalog.pg_constraint k WHERE k.conrelid=t.oid), '[]'::jsonb),
   'effective_app_privileges', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
     'role', r.rolname,
     'select', pg_catalog.has_table_privilege(r.oid,t.oid,'SELECT'),
     'insert', pg_catalog.has_table_privilege(r.oid,t.oid,'INSERT'),
     'update', pg_catalog.has_table_privilege(r.oid,t.oid,'UPDATE'),
     'delete', pg_catalog.has_table_privilege(r.oid,t.oid,'DELETE'),
     'truncate', pg_catalog.has_table_privilege(r.oid,t.oid,'TRUNCATE'),
     'trigger', pg_catalog.has_table_privilege(r.oid,t.oid,'TRIGGER')
   ) ORDER BY r.rolname) FROM test_roles r), '[]'::jsonb),
   'acl', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
     'grantee', CASE WHEN x.grantee=0 THEN 'PUBLIC' ELSE pg_catalog.pg_get_userbyid(x.grantee) END,
     'grantor', pg_catalog.pg_get_userbyid(x.grantor),
     'privilege', x.privilege_type, 'grantable', x.is_grantable
   ) ORDER BY x.grantee,x.privilege_type)
   FROM pg_catalog.aclexplode(COALESCE(t.relacl,pg_catalog.acldefault('r',t.relowner))) x), '[]'::jsonb)
 ) ORDER BY t.nspname,t.relname) FROM app_tables t), '[]'::jsonb),
 'policies', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'schema', t.nspname, 'table', t.relname, 'name', p.polname,
   'command', p.polcmd, 'permissive', p.polpermissive,
   'roles', (SELECT pg_catalog.jsonb_agg(CASE WHEN role_id=0 THEN 'PUBLIC'
      ELSE pg_catalog.pg_get_userbyid(role_id) END ORDER BY role_id)
      FROM pg_catalog.unnest(p.polroles) role_id),
   'using_md5', pg_catalog.md5(pg_catalog.pg_get_expr(p.polqual,p.polrelid)),
   'using_redacted', pg_catalog.regexp_replace(pg_catalog.pg_get_expr(p.polqual,p.polrelid),
     $literal$(?:[eE])?'(?:[^'\\]|\\.|'')*'$literal$, $replacement$'<redacted>'$replacement$, 'g'),
   'with_check_md5', pg_catalog.md5(pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid)),
   'with_check_redacted', pg_catalog.regexp_replace(pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid),
     $literal$(?:[eE])?'(?:[^'\\]|\\.|'')*'$literal$, $replacement$'<redacted>'$replacement$, 'g')
 ) ORDER BY t.nspname,t.relname,p.polname)
 FROM pg_catalog.pg_policy p JOIN app_tables t ON t.oid=p.polrelid), '[]'::jsonb),
 'triggers', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'schema', t.nspname, 'table', t.relname, 'name', g.tgname,
   'enabled', g.tgenabled,
   'definition_md5', pg_catalog.md5(pg_catalog.pg_get_triggerdef(g.oid,true)),
   'type_bits', g.tgtype, 'column_numbers', g.tgattr::smallint[],
   'argument_count', g.tgnargs,
   'row_level', (g.tgtype::integer & 1)<>0, 'before', (g.tgtype::integer & 2)<>0,
   'insert', (g.tgtype::integer & 4)<>0, 'delete', (g.tgtype::integer & 8)<>0,
   'update', (g.tgtype::integer & 16)<>0, 'truncate', (g.tgtype::integer & 32)<>0,
   'instead_of', (g.tgtype::integer & 64)<>0,
   'function_schema', fn.nspname, 'function', fp.proname,
   'function_security_definer', fp.prosecdef,
   'function_source_md5', pg_catalog.md5(pg_catalog.pg_get_functiondef(fp.oid))
 ) ORDER BY t.nspname,t.relname,g.tgname)
 FROM pg_catalog.pg_trigger g JOIN app_tables t ON t.oid=g.tgrelid
 JOIN pg_catalog.pg_proc fp ON fp.oid=g.tgfoid
 JOIN pg_catalog.pg_namespace fn ON fn.oid=fp.pronamespace
 WHERE NOT g.tgisinternal), '[]'::jsonb),
 'routines', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'schema', p.nspname, 'name', p.proname, 'kind', p.prokind,
   'arguments', pg_catalog.pg_get_function_identity_arguments(p.oid),
   'returns', pg_catalog.pg_get_function_result(p.oid),
   'owner', pg_catalog.pg_get_userbyid(p.proowner),
   'security_definer', p.prosecdef, 'volatility', p.provolatile,
   'leakproof', p.proleakproof, 'language', l.lanname,
   'configuration_names', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.split_part(v,'=',1))
       FROM pg_catalog.unnest(p.proconfig) v), '[]'::jsonb),
   'has_search_path', EXISTS(SELECT FROM pg_catalog.unnest(p.proconfig) v WHERE v LIKE 'search_path=%'),
   'source_md5', pg_catalog.md5(pg_catalog.pg_get_functiondef(p.oid)),
   'effective_app_execute', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
     'role', r.rolname, 'execute', pg_catalog.has_function_privilege(r.oid,p.oid,'EXECUTE')
   ) ORDER BY r.rolname) FROM test_roles r), '[]'::jsonb)
 ) ORDER BY p.nspname,p.proname,pg_catalog.pg_get_function_identity_arguments(p.oid))
 FROM app_routines p JOIN pg_catalog.pg_language l ON l.oid=p.prolang), '[]'::jsonb),
 'event_triggers', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'name', e.evtname, 'event', e.evtevent, 'enabled', e.evtenabled, 'tags', e.evttags,
   'function_schema', n.nspname, 'function', p.proname,
   'function_security_definer', p.prosecdef,
   'function_source_md5', pg_catalog.md5(pg_catalog.pg_get_functiondef(p.oid))
 ) ORDER BY e.evtname) FROM pg_catalog.pg_event_trigger e
 JOIN pg_catalog.pg_proc p ON p.oid=e.evtfoid
 JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace), '[]'::jsonb)
) AS inventory;"""


class InspectionError(RuntimeError):
    """Only agent-authored, credential-free messages reach the report/stdout."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def configured_project_ref(source):
    match = re.search(r"const CONFIG=Object\.freeze\(\{\s*url:'https://([a-z]{20})\.supabase\.co'", source)
    if not match or match.group(1) != PROJECT_REF:
        raise InspectionError("Current application CONFIG does not match the fixed production project")
    return match.group(1)


class Transport:
    def __init__(self):
        self.opener = build_opener(NoRedirect())

    def request(self, method, url, headers, body=None):
        allowed = (method == 'GET' and url == PROJECT_URL and body is None) or (
            method == 'POST' and url == PROJECT_URL + '/database/query'
            and body == {'query': INVENTORY_SQL, 'read_only': True})
        if not allowed:
            raise InspectionError("Request is outside the fixed read-only inspection boundary")
        request = Request(url, method=method, headers={"Content-Type": "application/json", **headers},
                          data=None if body is None else json.dumps(body).encode())
        try:
            with self.opener.open(request, timeout=30) as response:
                status, raw = response.status, response.read()
        except HTTPError as error:
            status, raw = error.code, error.read()
        except (URLError, TimeoutError, OSError):
            raise InspectionError("Inspection request failed: check network policy, TLS and service health") from None
        try:
            result = json.loads(raw) if raw else None
        except (ValueError, UnicodeError):
            result = None
        return status, result


class ProductionSchemaInspector:
    def __init__(self, token, transport=None):
        if not token:
            raise InspectionError("Missing protected environment binding: " + TOKEN_NAME)
        self.token = token
        self.transport = transport or Transport()

    def inspect(self):
        configured_project_ref((ROOT / 'index.html').read_text())
        headers = {"Authorization": "Bearer " + self.token}
        status, project = self.transport.request('GET', PROJECT_URL, headers)
        if status != 200:
            raise InspectionError("Production identity request returned HTTP " + str(status))
        if not isinstance(project, dict) or project.get('ref', project.get('id')) != PROJECT_REF \
                or project.get('name') != PROJECT_NAME:
            raise InspectionError("Production project ref/name mismatch; no catalog query was sent")
        if project.get('status') != 'ACTIVE_HEALTHY':
            raise InspectionError("Production project is not ACTIVE_HEALTHY; no catalog query was sent")
        status, rows = self.transport.request('POST', PROJECT_URL + '/database/query', headers,
            {'query': INVENTORY_SQL, 'read_only': True})
        if status not in (200, 201):
            raise InspectionError("Read-only catalog request returned HTTP " + str(status))
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise InspectionError("Read-only catalog result shape is unexpected")
        inventory = rows[0].get('inventory')
        if not isinstance(inventory, dict) or inventory.get('format') != 'marichevy-schema-inventory-v1' \
                or inventory.get('catalog_only') is not True:
            raise InspectionError("Read-only catalog result is missing the fixed inventory marker")
        expected_lists = ('namespaces', 'tables', 'policies', 'triggers', 'routines', 'event_triggers')
        if any(not isinstance(inventory.get(key), list) for key in expected_lists):
            raise InspectionError("Read-only catalog result has incomplete metadata collections")
        return {'outcome': 'inspected', 'read_only': True,
                'project': {key: project.get(key) for key in ('ref', 'name', 'status', 'region')},
                'query_sha256': hashlib.sha256(INVENTORY_SQL.encode()).hexdigest(),
                'inventory': inventory, 'data_rows_read': False, 'schema_changed': False,
                'api_keys_revealed': False, 'authorization_tested': False,
                'limitations': ['Catalog metadata does not prove hosted RLS behavior.',
                    'Routine bodies are hashed, not returned or reviewed.',
                    'Trigger definitions and arguments are hashed, not returned; policy/constraint string literals are redacted.',
                    'Runtime PostgREST exposed-schema configuration may differ from observed DB setting.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=Path('/workspace/artifacts/production-schema-inventory-PRIVATE.json'))
    args = parser.parse_args()
    observed_at = datetime.now(timezone.utc).isoformat()
    try:
        report = ProductionSchemaInspector(os.environ.get(TOKEN_NAME)).inspect()
        result = 0
        message = 'Read-only production schema inventory completed; private report: ' + str(args.report)
    except InspectionError as error:
        report = {'outcome': 'blocked', 'project_ref': PROJECT_REF, 'safe_error': str(error),
                  'data_rows_read': False, 'schema_changed': False, 'api_keys_revealed': False}
        result, message = 1, str(error)
    report['observed_at'] = observed_at
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(message)
    return result


if __name__ == '__main__':
    raise SystemExit(main())

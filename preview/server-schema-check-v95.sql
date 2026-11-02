-- READ-ONLY SCHEMA CHECK. No application or authentication rows are read.
-- Run in the verified production project SQL Editor; export schema_report as CSV.
-- This is catalog evidence, not an update, backup, activation or writer-pause proof.
-- Inventory/default/function hashes and the allowlisted membership review reuse
-- the exact fixed SELECT bodies from tools/inspect_production_schema.py.
WITH inventory_result AS (
WITH
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
) AS inventory
),
membership_result AS (
WITH helper AS (
  SELECT p.*, n.nspname, l.lanname FROM pg_catalog.pg_proc p
  JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
  JOIN pg_catalog.pg_language l ON l.oid=p.prolang
  WHERE n.nspname='public' AND p.proname='is_household_member'
    AND pg_catalog.oidvectortypes(p.proargtypes)='uuid, uuid' AND p.prokind='f'
), reviewed AS (
  SELECT h.*,
    (pg_catalog.length(h.prosrc) BETWEEN 1 AND 2000
      AND h.prosrc ~ '^[A-Za-z0-9_[:space:]().=,;]+$'
      AND NOT EXISTS (
        SELECT FROM pg_catalog.regexp_matches(pg_catalog.lower(h.prosrc), '[a-z_][a-z_0-9]*|[0-9]+', 'g') w
        WHERE w[1] NOT IN ('select','exists','from','where','and','or','not','true','false','as',
          'public','household_members','household_id','user_id','p_household_id','p_user_id',
          'auth','uid','hm','m','member','membership','1')
      )) AS body_safe,
    ARRAY(SELECT pg_catalog.regexp_replace(pg_catalog.lower(v), '[[:space:]"]', '', 'g')
      FROM pg_catalog.unnest(h.proconfig) v WHERE v LIKE 'search_path=%') AS search_paths
  FROM helper h
)
SELECT pg_catalog.jsonb_build_object(
  'format', 'marichevy-membership-review-v1', 'catalog_only', true,
  'helper_count', (SELECT pg_catalog.count(*) FROM reviewed),
  'helper', (SELECT pg_catalog.jsonb_build_object(
    'schema', h.nspname, 'name', h.proname,
    'arguments', pg_catalog.pg_get_function_identity_arguments(h.oid),
    'returns', pg_catalog.pg_get_function_result(h.oid),
    'owner', pg_catalog.pg_get_userbyid(h.proowner),
    'language', h.lanname, 'security_definer', h.prosecdef, 'volatility', h.provolatile,
    'definition_md5', pg_catalog.md5(pg_catalog.pg_get_functiondef(h.oid)),
    'matches_inventory_hash', pg_catalog.md5(pg_catalog.pg_get_functiondef(h.oid))='ee70441dfc53e994de80474ad6fb344a',
    'body_safe_for_review', h.body_safe,
    'body_for_review', CASE WHEN h.body_safe THEN h.prosrc ELSE NULL END,
    'search_path_allowlisted', pg_catalog.cardinality(h.search_paths)=1 AND NOT EXISTS (
      SELECT FROM pg_catalog.unnest(pg_catalog.string_to_array(pg_catalog.substr(h.search_paths[1],13),',')) part
      WHERE part NOT IN ('public','auth','pg_catalog','pg_temp','extensions')),
    'search_path_names', CASE WHEN pg_catalog.cardinality(h.search_paths)=1 AND NOT EXISTS (
      SELECT FROM pg_catalog.unnest(pg_catalog.string_to_array(pg_catalog.substr(h.search_paths[1],13),',')) part
      WHERE part NOT IN ('public','auth','pg_catalog','pg_temp','extensions'))
      THEN pg_catalog.string_to_array(pg_catalog.substr(h.search_paths[1],13),',') ELSE NULL END
  ) FROM reviewed h LIMIT 1)
) AS membership_review
)
SELECT pg_catalog.jsonb_build_object(
  'format', 'marichevy-server-schema-check-v95-v1',
  'catalog_only', true,
  'database_name', pg_catalog.current_database(),
  'database_role', current_user,
  'transaction_read_only', pg_catalog.current_setting('transaction_read_only'),
  'server_version_num', pg_catalog.current_setting('server_version_num'),
  'inventory', i.inventory,
  'membership_review', m.membership_review
)::text AS schema_report
FROM inventory_result i CROSS JOIN membership_result m;

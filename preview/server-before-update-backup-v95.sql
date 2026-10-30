-- READ-ONLY PRIVATE BACKUP AND PRE-001 ACTIVATION CHECKPOINT.
-- Run only in the independently verified production SQL Editor after all
-- writers are paused. The fixed project_ref is a label, not identity proof.
-- Export the single backup_json cell as CSV and KEEP IT PRIVATE.
-- One SELECT / one MVCC snapshot; no writes, credentials or Auth rows.
-- expected_revision=0 is the future 001 default ONLY while this exact original
-- four-column schema is present. This does not activate or authorize a release.
WITH scope AS MATERIALIZED (
  SELECT count(*) AS households_count, min(id::text)::uuid AS household_id
  FROM public.households
), original_schema AS MATERIALIZED (
  SELECT
    EXISTS (
      SELECT FROM pg_catalog.pg_class c
      WHERE c.oid = 'public.family_state'::regclass
        AND c.relkind = 'r' AND c.relrowsecurity AND NOT c.relforcerowsecurity
        AND pg_catalog.pg_get_userbyid(c.relowner) = 'postgres'
    )
    AND (
      SELECT pg_catalog.array_agg(a.attname::text || ':' ||
        pg_catalog.format_type(a.atttypid, a.atttypmod) || ':' || a.attnotnull::text
        ORDER BY a.attname)
      FROM pg_catalog.pg_attribute a
      WHERE a.attrelid = 'public.family_state'::regclass
        AND a.attnum > 0 AND NOT a.attisdropped
    ) = ARRAY[
      'data:jsonb:true', 'household_id:uuid:true',
      'updated_at:timestamp with time zone:true', 'updated_by:uuid:false'
    ]::text[]
    AND (
      SELECT count(*) = 1
        AND bool_and(k.conkey = ARRAY[(SELECT a.attnum
          FROM pg_catalog.pg_attribute a
          WHERE a.attrelid = 'public.family_state'::regclass
            AND a.attname = 'household_id' AND NOT a.attisdropped)]::smallint[])
        AND bool_and(k.convalidated)
      FROM pg_catalog.pg_constraint k
      WHERE k.conrelid = 'public.family_state'::regclass AND k.contype = 'p'
    )
    AND NOT EXISTS (
      SELECT FROM pg_catalog.pg_trigger t
      WHERE t.tgrelid = 'public.family_state'::regclass AND NOT t.tgisinternal
    )
    AND NOT EXISTS (
      SELECT FROM pg_catalog.pg_proc p
      WHERE p.pronamespace = 'public'::regnamespace
        AND p.proname IN ('family_state_sync_guard', 'family_state_cas')
    ) AS verified
), gate AS MATERIALIZED (
  SELECT s.household_id, s.households_count,
    1 / CASE WHEN pg_catalog.current_database() = 'postgres'
      AND current_user = 'postgres' AND o.verified IS TRUE
      AND s.households_count = 1 AND s.household_id IS NOT NULL
      AND (SELECT count(*) FROM public.family_state) = 1
      AND (SELECT count(*) FROM public.family_state f
           WHERE f.household_id = s.household_id) = 1
      AND EXISTS (SELECT FROM public.household_members m
                   WHERE m.household_id = s.household_id)
      AND NOT EXISTS (SELECT FROM public.household_members m
                       WHERE m.household_id IS DISTINCT FROM s.household_id)
      AND NOT EXISTS (SELECT FROM public.family_chore_deliveries d
                       WHERE d.household_id IS DISTINCT FROM s.household_id)
    THEN 1 ELSE 0 END AS verified
  FROM scope s CROSS JOIN original_schema o
), payload AS MATERIALIZED (
  SELECT g.household_id, g.households_count,
    pg_catalog.jsonb_build_object(
      'family_state', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(f) ORDER BY f.household_id)
        FROM public.family_state f WHERE f.household_id = g.household_id), '[]'::jsonb),
      'households', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(h) ORDER BY h.id)
        FROM public.households h WHERE h.id = g.household_id), '[]'::jsonb),
      'household_members', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(m) ORDER BY m.user_id)
        FROM public.household_members m WHERE m.household_id = g.household_id), '[]'::jsonb),
      'family_chore_deliveries', COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(d)
          ORDER BY d.chore_id, d.due_date, d.chat_id)
        FROM public.family_chore_deliveries d WHERE d.household_id = g.household_id), '[]'::jsonb)
    )::text AS snapshot_json,
    (SELECT pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(f.data::text, 'UTF8')), 'hex')
      FROM public.family_state f WHERE f.household_id = g.household_id) AS data_sha256
  FROM gate g WHERE g.verified = 1
)
SELECT pg_catalog.jsonb_build_object(
  'format', 'marichevy-private-server-backup-v1',
  'read_only', true,
  'project_ref', 'kqndxecziamypdjpxhyq',
  'configured_household', p.household_id,
  'configured_household_count', p.households_count,
  'database_name', pg_catalog.current_database(),
  'database_role', current_user,
  'database_timezone', pg_catalog.current_setting('TimeZone'),
  'transaction_read_only', pg_catalog.current_setting('transaction_read_only'),
  'export_method', 'sql-editor-select-v1',
  'query_sha256', pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.current_query(), 'UTF8')), 'hex'),
  'captured_at_utc', pg_catalog.to_char(pg_catalog.statement_timestamp() AT TIME ZONE 'UTC',
                                     'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'snapshot_json', p.snapshot_json,
  'snapshot_json_sha256', pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.snapshot_json, 'UTF8')), 'hex'),
  'activation_checkpoint', pg_catalog.jsonb_build_object(
    'format', 'marichevy-sync-activation-plan-v1',
    'activation_sql_sha256', '7fc72248cd65e790dfec12abc4da1811ae2146f414b8be46cd5cd7ae5244e248',
    'expected_database', pg_catalog.current_database(),
    'household_id', p.household_id,
    'expected_revision', 0,
    'expected_data_sha256', p.data_sha256
  )
)::text AS backup_json
FROM payload p;

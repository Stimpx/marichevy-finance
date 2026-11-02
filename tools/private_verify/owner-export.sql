-- READ-ONLY OWNER EXPORT. Run only in the verified production project
-- marichevy-finance / kqndxecziamypdjpxhyq, after pausing all writers.
-- The fixed project_ref below is an expected label, not database identity proof.
-- Download the single backup_json result as CSV; keep the file private.
-- One SELECT / one MVCC snapshot; no authentication rows or credentials.
-- Refuse ambiguous/missing families instead of choosing a household by name.
-- query_sha256 hashes the actual statement received by PostgreSQL; it is
-- evidence to compare with the reviewed query, not a claim made from a label.
WITH scope AS MATERIALIZED (
  SELECT count(*) AS households_count, min(id::text)::uuid AS household_id
  FROM public.households
), gate AS MATERIALIZED (
  SELECT s.household_id, s.households_count,
    1 / CASE WHEN current_user = 'postgres'
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
  FROM scope s
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
    )::text AS snapshot_json
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
  'snapshot_json_sha256', pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.snapshot_json, 'UTF8')), 'hex')
)::text AS backup_json
FROM payload p;

-- REVIEWED OPERATOR ARTIFACT; not an application RPC or a generic SQL executor.
-- One PostgreSQL statement, suitable for Management API bound parameters:
-- $1 text: verified database name; $2 uuid: configured household;
-- $3 bigint: privately verified current revision; $4 text: SHA-256 of data::text
-- encoded as UTF-8, calculated by PostgreSQL before activation.
-- Requires a separate verified backup, reconciled queues and paused writers.
-- Run only through a fixed-project operator boundary, as postgres, read_only:false.
-- Save the returned activation_revision in a private activation receipt before
-- publishing the matching client. A failed assertion rolls back this statement.
-- An ambiguous HTTP response is not permission to retry or infer that receipt.
WITH args AS MATERIALIZED (
  SELECT $1::text AS expected_database,
         $2::uuid AS household_id,
         $3::bigint AS expected_revision,
         $4::text AS expected_data_sha256
),
locked AS MATERIALIZED (
  SELECT s.household_id,s.data,s.updated_at,s.updated_by,
         s.sync_protocol,s.sync_revision
  FROM public.family_state s CROSS JOIN args a
  WHERE s.household_id=a.household_id
    AND current_database()=a.expected_database
    AND current_user='postgres'
    AND current_setting('transaction_read_only')='off'
    AND a.expected_revision >= 0
    AND a.expected_revision < 9223372036854775807
    AND a.expected_data_sha256 ~ '^[0-9a-f]{64}$'
  FOR UPDATE OF s
),
changed AS (
  UPDATE public.family_state s SET sync_protocol=2
  FROM locked l CROSS JOIN args a
  WHERE s.household_id=l.household_id
    AND l.sync_protocol=1
    AND l.sync_revision=a.expected_revision
    AND s.sync_protocol=1
    AND s.sync_revision=a.expected_revision
    AND encode(sha256(convert_to(l.data::text,'UTF8')),'hex')
        =a.expected_data_sha256
  RETURNING s.sync_revision AS activation_revision,
    s.sync_protocol=2 AS protocol_valid,
    s.sync_revision=a.expected_revision+1 AS revision_valid,
    s.last_request_id IS NULL AS receipt_valid,
    -- JSONB equality ignores numeric scale (12.3400 = 12.34). Preserve the
    -- exact PostgreSQL text representation used for the verified data hash.
    s.data::text IS NOT DISTINCT FROM l.data::text AS data_unchanged,
    s.updated_at IS NOT DISTINCT FROM l.updated_at AS time_unchanged,
    s.updated_by IS NOT DISTINCT FROM l.updated_by AS author_unchanged
)
SELECT
  -- The denominator depends on actual UPDATE results; no constant 1/0 branch
  -- can be folded during planning. Any mismatch aborts this single statement.
  1 / CASE WHEN count(*)=1
    AND bool_and(protocol_valid AND revision_valid AND receipt_valid
      AND data_unchanged AND time_unchanged AND author_unchanged)
    THEN 1 ELSE 0 END AS verified,
  min(activation_revision) AS activation_revision
FROM changed;

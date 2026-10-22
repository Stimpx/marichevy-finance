-- Rollback DISABLES safe sync. First stop/drain clients and disable cloud writes.
-- Preserve a fresh verified backup; do not restore an old data snapshot.
-- psql -v expected_database=... -v household_id=... -v expected_revision=... \
--   -v confirmation=DISABLE_SYNC_REVIEWED_HOUSEHOLD -f server/rollback_household.sql
\set ON_ERROR_STOP on
BEGIN;
SELECT current_database() = :'expected_database'
  AND current_user IN ('postgres', 'supabase_admin')
  AND :'confirmation' = 'DISABLE_SYNC_REVIEWED_HOUSEHOLD' AS approved \gset
\if :approved
WITH changed AS (
  UPDATE public.family_state SET sync_protocol = 1
  WHERE household_id = :'household_id'::uuid
    AND sync_protocol = 2 AND sync_revision = :'expected_revision'::bigint
  RETURNING household_id
) SELECT count(*) = 1 AS changed FROM changed \gset
\if :changed
COMMIT;
\else
ROLLBACK;
DO $$ BEGIN RAISE EXCEPTION 'Rollback refused: row/protocol/revision did not match.'; END $$;
\endif
\else
ROLLBACK;
DO $$ BEGIN RAISE EXCEPTION 'Rollback refused: database/operator/confirmation did not match.'; END $$;
\endif

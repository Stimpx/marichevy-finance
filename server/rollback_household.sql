-- Rollback DISABLES safe sync. First stop/drain clients and disable cloud writes.
-- Preserve a fresh verified backup; do not restore an old data snapshot.
-- Only BEFORE any application writes after activation. Read the activation
-- revision from the saved activation receipt, never infer it from the live row.
-- After new v95 writes keep protocol 2 and repair the client with writers paused:
-- the original v94 client drops fields it does not understand when saving.
-- psql -v expected_database=... -v household_id=... -v expected_revision=... \
--   -v expected_activation_revision=... \
--   -v confirmation=DISABLE_SYNC_REVIEWED_HOUSEHOLD -f server/rollback_household.sql
\set ON_ERROR_STOP on
BEGIN;
SELECT current_database() = :'expected_database'
  AND current_user IN ('postgres', 'supabase_admin')
  AND :'expected_revision'::bigint = :'expected_activation_revision'::bigint
  AND :'expected_activation_revision'::bigint >= 0
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
DO $$ BEGIN RAISE EXCEPTION 'Rollback refused: database/operator/confirmation/activation revision did not match; new writes require a compatible client.'; END $$;
\endif

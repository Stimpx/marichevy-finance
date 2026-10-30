-- OPERATOR TEMPLATE: use only after the bank update and checks are complete.
-- Replace the placeholder with resume_config_sha256 saved from the pause.
-- The unchanged placeholder fails closed. Do not substitute a newly read hash.
ROLLBACK;
BEGIN;
SET LOCAL lock_timeout = '5s';
DO $resume$
DECLARE
  expected_config_sha256 text := 'REPLACE_WITH_SAVED_RESUME_CONFIG_SHA256';
  before_job cron.job%ROWTYPE;
  after_job cron.job%ROWTYPE;
BEGIN
  IF current_database() <> 'postgres' OR current_user <> 'postgres'
      OR current_setting('transaction_read_only') <> 'off'
      OR pg_catalog.row_security_active('cron.job'::regclass)
      OR expected_config_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'cutover-cron-identity-or-receipt-mismatch';
  END IF;

  -- Use the extension API; direct row locking requires an unavailable grant.
  SELECT * INTO before_job FROM cron.job WHERE jobid = 1;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'cutover-cron-resume-mismatch';
  END IF;
  IF before_job.active IS DISTINCT FROM false
      OR before_job.database IS DISTINCT FROM current_database()
      OR (SELECT count(*) FROM cron.job) <> 1
      OR encode(sha256(convert_to((to_jsonb(before_job) - 'active')::text,
        'UTF8')), 'hex') IS DISTINCT FROM expected_config_sha256
      OR substring(before_job.command FROM
        'https://kqndxecziamypdjpxhyq[.]supabase[.]co/functions/v1/([A-Za-z][A-Za-z0-9_-]{0,63})'
      ) IS DISTINCT FROM 'family-reminders' THEN
    RAISE EXCEPTION 'cutover-cron-resume-mismatch';
  END IF;

  PERFORM cron.alter_job(1, active := true);
  SELECT * INTO after_job FROM cron.job WHERE jobid = 1;
  IF NOT FOUND OR after_job.active IS DISTINCT FROM true
      OR (to_jsonb(after_job) - 'active')
        IS DISTINCT FROM (to_jsonb(before_job) - 'active') THEN
    RAISE EXCEPTION 'cutover-cron-resume-unverified';
  END IF;
END
$resume$;
COMMIT;

SELECT j.jobid, j.active
FROM cron.job j WHERE j.jobid = 1;

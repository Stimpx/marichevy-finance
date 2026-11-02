-- CUTOVER CHANGE: temporarily pause only the reviewed family-reminders job.
-- Run in the independently verified marichevy-finance production SQL Editor.
-- This does not change expenses, the command, schedule, or credentials.
-- Save the final result privately; restore only the same saved configuration.
-- Clear the failed earlier attempt if its transaction is still open.
ROLLBACK;
BEGIN;
SET LOCAL lock_timeout = '5s';
DO $pause$
DECLARE
  before_job cron.job%ROWTYPE;
  after_job cron.job%ROWTYPE;
BEGIN
  IF current_database() <> 'postgres' OR current_user <> 'postgres'
      OR current_setting('transaction_read_only') <> 'off'
      OR pg_catalog.row_security_active('cron.job'::regclass) THEN
    RAISE EXCEPTION 'cutover-cron-identity-mismatch';
  END IF;

  -- Managed pg_cron grants SELECT here, not caller-side UPDATE/row locking.
  -- alter_job performs its own authorized UPDATE and holds the row lock.
  SELECT * INTO before_job FROM cron.job WHERE jobid = 1;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'cutover-cron-job-mismatch';
  END IF;
  IF before_job.active IS DISTINCT FROM true
      OR before_job.database IS DISTINCT FROM current_database()
      OR (SELECT count(*) FROM cron.job) <> 1
      OR substring(before_job.command FROM
        'https://kqndxecziamypdjpxhyq[.]supabase[.]co/functions/v1/([A-Za-z][A-Za-z0-9_-]{0,63})'
      ) IS DISTINCT FROM 'family-reminders' THEN
    RAISE EXCEPTION 'cutover-cron-job-mismatch';
  END IF;

  PERFORM cron.alter_job(1, active := false);
  SELECT * INTO after_job FROM cron.job WHERE jobid = 1;
  IF NOT FOUND OR after_job.active IS DISTINCT FROM false
      OR (to_jsonb(after_job) - 'active')
        IS DISTINCT FROM (to_jsonb(before_job) - 'active') THEN
    RAISE EXCEPTION 'cutover-cron-pause-unverified';
  END IF;
END
$pause$;
COMMIT;

SELECT j.jobid, j.active,
  encode(sha256(convert_to((to_jsonb(j) - 'active')::text, 'UTF8')), 'hex')
    AS resume_config_sha256,
  NOT pg_catalog.row_security_active('cron.job_run_details'::regclass)
    AS runs_unfiltered,
  (SELECT count(*) FROM cron.job_run_details WHERE end_time IS NULL)
    AS runs_unfinished,
  (SELECT count(*) FROM net.http_request_queue
    WHERE url ~ '^https://kqndxecziamypdjpxhyq[.]supabase[.]co/functions/v1/family-reminders([/?#]|$)')
    AS queued_reminder_requests
FROM cron.job j WHERE j.jobid = 1;

-- FICTIONAL, ISOLATED STAGING ONLY. Never run in the personal/production project.
-- Caller must first verify BOTH the Management API project ref and project name:
--   iqpoxphtvtogjowruufe / marichevy-finance-staging
-- Caller must wrap this whole file in ONE transaction, in the SAME SQL request:
--   BEGIN; SET LOCAL marichevy.staging_project_ref = 'iqpoxphtvtogjowruufe';
--   <this complete file>
--   COMMIT;
-- The setting is only an accidental-target guard, not an authorization capability.
-- This transaction refuses existing tables/data; there is no destructive reset.
-- Create real fictional auth users via the supported GoTrue Admin API separately.
-- This file never writes auth.users, never applies CAS, and creates no family data.
DO $staging_preflight$
BEGIN
  IF current_user NOT IN ('postgres', 'supabase_admin') THEN
    RAISE EXCEPTION 'Staging bootstrap requires the database administrator';
  END IF;
  IF current_setting('marichevy.staging_project_ref', true) IS DISTINCT FROM 'iqpoxphtvtogjowruufe' THEN
    RAISE EXCEPTION 'Staging project identity guard missing or mismatched';
  END IF;
  IF to_regprocedure('auth.uid()') IS NULL OR to_regclass('auth.users') IS NULL
      OR NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated')
      OR NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
    RAISE EXCEPTION 'Expected real Supabase authentication prerequisites';
  END IF;
  IF to_regnamespace('marichevy_staging') IS NOT NULL THEN
    RAISE EXCEPTION 'Staging marker already exists: inspect the existing installation instead of resetting it';
  END IF;
  IF EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')) THEN
    RAISE EXCEPTION 'Expected an empty public schema; existing tables/views require manual inspection';
  END IF;
END
$staging_preflight$;

CREATE SCHEMA marichevy_staging;
REVOKE ALL ON SCHEMA marichevy_staging FROM PUBLIC, anon, authenticated;
CREATE TABLE marichevy_staging.fixture_registry (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  project_ref text NOT NULL CHECK (project_ref = 'iqpoxphtvtogjowruufe'),
  project_name text NOT NULL CHECK (project_name = 'marichevy-finance-staging'),
  fixture_version integer NOT NULL CHECK (fixture_version = 1)
);
REVOKE ALL ON marichevy_staging.fixture_registry FROM PUBLIC, anon, authenticated;
INSERT INTO marichevy_staging.fixture_registry
  (project_ref, project_name, fixture_version)
  VALUES ('iqpoxphtvtogjowruufe', 'marichevy-finance-staging', 1);

CREATE TABLE public.staging_membership (
  household_id uuid NOT NULL,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  PRIMARY KEY (household_id, user_id)
);
COMMENT ON TABLE public.staging_membership IS
  'Fictional staging membership only. Admin-managed; not a production membership migration.';
ALTER TABLE public.staging_membership ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.staging_membership FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.staging_membership TO authenticated;
CREATE POLICY staging_membership_self ON public.staging_membership FOR SELECT TO authenticated
  USING (user_id = auth.uid());

-- Deliberately the exact inferred legacy shape accepted by 001_family_state_cas.sql.
CREATE TABLE public.family_state (
  household_id uuid PRIMARY KEY,
  data jsonb NOT NULL,
  updated_at timestamptz DEFAULT now(),
  updated_by uuid
);
COMMENT ON TABLE public.family_state IS
  'Fictional staging state only. No real family export may be inserted here.';
ALTER TABLE public.family_state ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.family_state FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA public TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.family_state TO authenticated;
CREATE POLICY staging_household_members ON public.family_state TO authenticated
  USING (EXISTS (SELECT FROM public.staging_membership m
    WHERE m.household_id = family_state.household_id AND m.user_id = auth.uid()))
  WITH CHECK (EXISTS (SELECT FROM public.staging_membership m
    WHERE m.household_id = family_state.household_id AND m.user_id = auth.uid()));


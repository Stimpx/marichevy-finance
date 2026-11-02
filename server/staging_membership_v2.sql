-- FICTIONAL STAGING EVOLUTION ONLY; this is NOT a production migration.
-- Verify Management API identity first: iqpoxphtvtogjowruufe / marichevy-finance-staging.
-- Caller wraps the complete file in ONE transaction in the SAME SQL request:
-- BEGIN; SET LOCAL marichevy.staging_project_ref='iqpoxphtvtogjowruufe'; <file> COMMIT;
-- No auth user, existing family JSON, revision, receipt or timestamp is rewritten.
-- Keep the v1 membership table solely for fixture provenance and runner compatibility.
-- The new membership/RLS/FK structure follows the read-only production catalog;
-- the helper body/search_path match the separately reviewed production helper.
-- An empty deliveries table reproduces confirmed columns/PK/access only. Its redacted
-- production status CHECK/default were not copied; no delivery worker is exercised here.
DO $membership_v2_preflight$
DECLARE v_relations text[]; v_columns text[];
BEGIN
  IF current_user NOT IN ('postgres', 'supabase_admin') THEN
    RAISE EXCEPTION 'Fixture evolution requires the database administrator';
  END IF;
  IF current_setting('marichevy.staging_project_ref',true) IS DISTINCT FROM 'iqpoxphtvtogjowruufe' THEN
    RAISE EXCEPTION 'Staging project identity guard missing or mismatched';
  END IF;
  IF to_regclass('marichevy_staging.fixture_registry') IS NULL
      OR to_regclass('public.family_state') IS NULL
      OR to_regclass('public.staging_membership') IS NULL
      OR to_regclass('auth.users') IS NULL
      OR to_regprocedure('auth.uid()') IS NULL
      OR NOT EXISTS (SELECT FROM pg_roles WHERE rolname='service_role') THEN
    RAISE EXCEPTION 'Expected the previously verified fictional v1 fixture';
  END IF;
  SELECT array_agg(c.relname::text ORDER BY c.relname) INTO v_relations
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f');
  IF v_relations IS DISTINCT FROM ARRAY['family_state','staging_membership'] THEN
    RAISE EXCEPTION 'Unexpected public relations; no existing installation will be replaced';
  END IF;
  IF EXISTS (SELECT FROM pg_class WHERE oid IN ('public.family_state'::regclass,
       'public.staging_membership'::regclass,'marichevy_staging.fixture_registry'::regclass)
       AND (relkind<>'r' OR relowner<>'postgres'::regrole))
      OR EXISTS (SELECT FROM pg_class WHERE oid IN ('public.family_state'::regclass,
       'public.staging_membership'::regclass) AND NOT relrowsecurity) THEN
    RAISE EXCEPTION 'Unexpected fixture relation ownership or RLS';
  END IF;
  LOCK TABLE public.family_state,public.staging_membership,marichevy_staging.fixture_registry
    IN ACCESS EXCLUSIVE MODE;
  LOCK TABLE auth.users IN SHARE MODE;
  IF NOT (SELECT count(*)=1 AND bool_and(singleton AND
        project_ref='iqpoxphtvtogjowruufe' AND project_name='marichevy-finance-staging'
        AND fixture_version=1) FROM marichevy_staging.fixture_registry) THEN
    RAISE EXCEPTION 'Expected exactly the untouched v1 fixture marker';
  END IF;
  SELECT array_agg(attname::text||':'||atttypid::regtype::text ORDER BY attname)
    INTO v_columns FROM pg_attribute WHERE attrelid='marichevy_staging.fixture_registry'::regclass
      AND attnum>0 AND NOT attisdropped;
  IF v_columns IS DISTINCT FROM ARRAY['fixture_version:integer','project_name:text',
       'project_ref:text','singleton:boolean']
      OR EXISTS (SELECT FROM pg_trigger WHERE tgrelid IN ('public.staging_membership'::regclass,
        'marichevy_staging.fixture_registry'::regclass) AND NOT tgisinternal) THEN
    RAISE EXCEPTION 'Unexpected fixture provenance columns or triggers';
  END IF;
  SELECT array_agg(attname::text||':'||atttypid::regtype::text ORDER BY attname)
    INTO v_columns FROM pg_attribute WHERE attrelid='public.family_state'::regclass
      AND attnum>0 AND NOT attisdropped;
  IF v_columns IS DISTINCT FROM ARRAY['data:jsonb','household_id:uuid','last_request_id:uuid',
       'sync_protocol:smallint','sync_revision:bigint','updated_at:timestamp with time zone','updated_by:uuid']
      OR NOT EXISTS (SELECT FROM pg_trigger WHERE tgrelid='public.family_state'::regclass
        AND tgname='family_state_sync_guard' AND NOT tgisinternal)
      OR to_regprocedure('public.family_state_cas(uuid,bigint,jsonb,uuid)') IS NULL
      OR to_regprocedure('public.is_household_member(uuid,uuid)') IS NOT NULL THEN
    RAISE EXCEPTION 'Expected the reviewed v1 CAS schema without a membership helper';
  END IF;
  IF EXISTS (SELECT FROM pg_constraint WHERE conrelid='public.family_state'::regclass AND contype='f')
      OR (SELECT count(*) FROM pg_trigger WHERE tgrelid='public.family_state'::regclass
        AND NOT tgisinternal)<>1
      OR (SELECT count(*) FROM pg_policy WHERE polrelid='public.family_state'::regclass)<>1
      OR NOT EXISTS (SELECT FROM pg_policy WHERE polrelid='public.family_state'::regclass
        AND polname='staging_household_members' AND polcmd='*') THEN
    RAISE EXCEPTION 'Unexpected family triggers, foreign keys or policies';
  END IF;
  SELECT array_agg(attname::text||':'||atttypid::regtype::text ORDER BY attname)
    INTO v_columns FROM pg_attribute WHERE attrelid='public.staging_membership'::regclass
      AND attnum>0 AND NOT attisdropped;
  IF v_columns IS DISTINCT FROM ARRAY['household_id:uuid','user_id:uuid'] THEN
    RAISE EXCEPTION 'Unexpected v1 membership columns';
  END IF;
  IF (SELECT count(*) FROM auth.users)<>3
      OR (SELECT count(*) FROM public.staging_membership)<>3
      OR (SELECT count(DISTINCT user_id) FROM public.staging_membership)<>3
      OR (SELECT count(*) FROM public.family_state)<>2
      OR (SELECT count(DISTINCT household_id) FROM public.staging_membership)<>2
      OR NOT (SELECT array_agg(n ORDER BY n)=ARRAY[1,2]::bigint[]
         FROM (SELECT count(*) n FROM public.staging_membership GROUP BY household_id) groups)
      OR EXISTS (SELECT FROM public.staging_membership m LEFT JOIN auth.users u ON u.id=m.user_id
           LEFT JOIN public.family_state f ON f.household_id=m.household_id
           WHERE u.id IS NULL OR f.household_id IS NULL)
      OR EXISTS (SELECT FROM public.family_state f WHERE f.updated_at IS NULL OR f.sync_protocol<>2
           OR jsonb_typeof(f.data)<>'object'
           OR (f.updated_by IS NOT NULL AND NOT EXISTS (SELECT FROM auth.users u WHERE u.id=f.updated_by))) THEN
    RAISE EXCEPTION 'Expected only two known fictional families and three fictional members';
  END IF;
  IF EXISTS (SELECT FROM auth.users u WHERE u.email IS NULL
        OR u.email !~ '^stage-[0-9a-f]{32}-[012]@example[.]invalid$'
        OR u.raw_app_meta_data->>'marichevy_staging_run' IS NULL
        OR u.raw_app_meta_data->>'marichevy_staging_run' !~ '^[0-9a-f]{32}$'
        OR u.raw_app_meta_data->>'marichevy_staging_run'
          IS DISTINCT FROM substring(u.email FROM '^stage-([0-9a-f]{32})-'))
      OR (SELECT count(DISTINCT raw_app_meta_data->>'marichevy_staging_run') FROM auth.users)<>1
      OR (SELECT count(DISTINCT email) FROM auth.users)<>3 THEN
    RAISE EXCEPTION 'Unknown authentication accounts; no account or family will be changed';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_constraint
      WHERE conrelid='marichevy_staging.fixture_registry'::regclass
      AND conname='fixture_registry_fixture_version_check' AND contype='c'
      AND pg_get_constraintdef(oid)='CHECK ((fixture_version = 1))') THEN
    RAISE EXCEPTION 'Unexpected fixture version constraint';
  END IF;
END
$membership_v2_preflight$;

CREATE TEMP TABLE membership_v2_before ON COMMIT DROP AS
  SELECT household_id,to_jsonb(f) AS row_json FROM public.family_state f;

CREATE TABLE public.households (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.household_members (
  household_id uuid NOT NULL REFERENCES public.households(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'member',
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(household_id,user_id)
);
ALTER TABLE public.households OWNER TO postgres;
ALTER TABLE public.household_members OWNER TO postgres;
INSERT INTO public.households(id,name)
  SELECT household_id,'Fictional staging family '||row_number() OVER (ORDER BY household_id)
    FROM public.staging_membership GROUP BY household_id;
INSERT INTO public.household_members(household_id,user_id,role)
  SELECT household_id,user_id,'member' FROM public.staging_membership;

CREATE FUNCTION public.is_household_member(p_household_id uuid,p_user_id uuid)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path=public AS $member$
  SELECT EXISTS (
    SELECT 1 FROM public.household_members hm
    WHERE hm.household_id=p_household_id AND hm.user_id=p_user_id
  );
$member$;
ALTER FUNCTION public.is_household_member(uuid,uuid) OWNER TO postgres;
-- Mirrors the observed callable surface solely for testing the production model.
REVOKE ALL ON FUNCTION public.is_household_member(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_household_member(uuid,uuid) TO anon,authenticated,service_role;
ALTER TABLE public.households ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.household_members ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.households,public.household_members FROM PUBLIC,anon,authenticated,service_role;
-- Broad CRUD mirrors production; SELECT-only RLS must still block all mutations.
GRANT SELECT,INSERT,UPDATE,DELETE ON public.households,public.household_members TO authenticated;
CREATE POLICY "members can view their households" ON public.households FOR SELECT TO authenticated
  USING(public.is_household_member(id,auth.uid()));
CREATE POLICY "members can view family members" ON public.household_members FOR SELECT TO authenticated
  USING(public.is_household_member(household_id,auth.uid()));

ALTER TABLE public.family_state ALTER COLUMN updated_at SET NOT NULL;
ALTER TABLE public.family_state ADD CONSTRAINT family_state_household_id_fkey
  FOREIGN KEY(household_id) REFERENCES public.households(id) ON DELETE CASCADE;
ALTER TABLE public.family_state ADD CONSTRAINT family_state_updated_by_fkey
  FOREIGN KEY(updated_by) REFERENCES auth.users(id);
DROP POLICY staging_household_members ON public.family_state;
CREATE POLICY "members can insert family state" ON public.family_state FOR INSERT TO authenticated
  WITH CHECK(public.is_household_member(household_id,auth.uid()));
CREATE POLICY "members can read family state" ON public.family_state FOR SELECT TO authenticated
  USING(public.is_household_member(household_id,auth.uid()));
CREATE POLICY "members can update family state" ON public.family_state FOR UPDATE TO authenticated
  USING(public.is_household_member(household_id,auth.uid()))
  WITH CHECK(public.is_household_member(household_id,auth.uid()));

CREATE TABLE public.family_chore_deliveries (
  household_id uuid NOT NULL,
  chore_id text NOT NULL,
  due_date date NOT NULL,
  chat_id text NOT NULL,
  status text NOT NULL,
  attempts integer NOT NULL DEFAULT 0,
  last_attempt_at timestamptz,
  sent_at timestamptz,
  telegram_message_id bigint,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(household_id,chore_id,due_date,chat_id)
);
ALTER TABLE public.family_chore_deliveries OWNER TO postgres;
COMMENT ON TABLE public.family_chore_deliveries IS
  'EMPTY fictional schema fixture only; production status defaults/CHECK and delivery worker are not reproduced.';
ALTER TABLE public.family_chore_deliveries ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.family_chore_deliveries FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT,INSERT,UPDATE,TRIGGER,TRUNCATE ON public.family_chore_deliveries TO service_role;

ALTER TABLE marichevy_staging.fixture_registry DROP CONSTRAINT fixture_registry_fixture_version_check;
ALTER TABLE marichevy_staging.fixture_registry ADD CONSTRAINT fixture_registry_fixture_version_check
  CHECK(fixture_version IN(1,2));
UPDATE marichevy_staging.fixture_registry SET fixture_version=2;
DO $membership_v2_postflight$
BEGIN
  IF EXISTS ((SELECT household_id,row_json FROM membership_v2_before
       EXCEPT SELECT household_id,to_jsonb(f) FROM public.family_state f)
       UNION ALL
       (SELECT household_id,to_jsonb(f) FROM public.family_state f
       EXCEPT SELECT household_id,row_json FROM membership_v2_before)) THEN
    RAISE EXCEPTION 'Fixture evolution changed a family snapshot; rolling back';
  END IF;
END
$membership_v2_postflight$;

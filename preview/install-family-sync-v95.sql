-- APPLY FAMILY SYNC SCHEMA: this script changes production schema and privileges.
-- Use only after the verified private backup match and coordinated writer pause.
-- Exact reviewed migrations 001, 002, 003 run in three separate transactions.
-- This does not replace expense JSON or activate protocol 2.
-- Stop on any error; do not repeat blindly after a partial migration.

-- REVIEW/STAGING TEMPLATE ONLY. This file does not activate protocol 2.
-- Run as the table owner in a transaction; unsupported schemas fail closed.
BEGIN;
LOCK TABLE public.family_state IN ACCESS EXCLUSIVE MODE;
DO $preflight$
DECLARE v_columns text[];
BEGIN
  IF (SELECT relkind <> 'r' OR NOT relrowsecurity FROM pg_class WHERE oid = 'public.family_state'::regclass) THEN
    RAISE EXCEPTION 'Expected an ordinary family_state table with existing RLS enabled';
  END IF;
  SELECT array_agg(attname::text || ':' || atttypid::regtype::text ORDER BY attname)
    INTO v_columns FROM pg_attribute
    WHERE attrelid = 'public.family_state'::regclass AND attnum > 0 AND NOT attisdropped;
  IF v_columns IS DISTINCT FROM ARRAY['data:jsonb','household_id:uuid','updated_at:timestamp with time zone','updated_by:uuid'] THEN
    RAISE EXCEPTION 'Unsupported family_state columns/types: %; review migration for the actual schema', v_columns;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.family_state'::regclass
      AND contype = 'p' AND conkey = ARRAY[(SELECT attnum FROM pg_attribute
        WHERE attrelid = 'public.family_state'::regclass AND attname = 'household_id')]::smallint[]) THEN
    RAISE EXCEPTION 'Expected household_id as the sole primary key';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'public.family_state'::regclass AND NOT tgisinternal) THEN
    RAISE EXCEPTION 'Existing family_state triggers require explicit compatibility review';
  END IF;
  IF to_regprocedure('auth.uid()') IS NULL OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated')
      OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    RAISE EXCEPTION 'Expected Supabase auth.uid(), authenticated and anon roles';
  END IF;
END
$preflight$;

ALTER TABLE public.family_state
  ADD COLUMN sync_revision bigint NOT NULL DEFAULT 0 CHECK (sync_revision >= 0),
  ADD COLUMN sync_protocol smallint NOT NULL DEFAULT 1 CHECK (sync_protocol IN (1, 2)),
  ADD COLUMN last_request_id uuid;

CREATE FUNCTION public.family_state_sync_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $guard$
DECLARE v_marker jsonb; v_maintenance boolean := current_user IN ('postgres', 'supabase_admin');
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.sync_protocol = 2 AND NOT v_maintenance THEN
      RAISE SQLSTATE 'PT409' USING MESSAGE = 'upgrade_required';
    END IF;
    RETURN OLD;
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF NOT v_maintenance AND NEW.sync_protocol <> 1 THEN
      RAISE SQLSTATE 'PT409' USING MESSAGE = 'upgrade_required';
    END IF;
    NEW.sync_revision := 0;
    NEW.last_request_id := NULL;
  ELSE
    IF NOT v_maintenance AND (NEW.household_id IS DISTINCT FROM OLD.household_id
        OR NEW.sync_protocol IS DISTINCT FROM OLD.sync_protocol) THEN
      RAISE SQLSTATE 'PT409' USING MESSAGE = 'upgrade_required';
    END IF;
    IF OLD.sync_protocol = 2 AND NOT v_maintenance THEN
      BEGIN
        v_marker := nullif(current_setting('marichevy_sync.cas', true), '')::jsonb;
      EXCEPTION WHEN invalid_text_representation THEN
        RAISE SQLSTATE 'PT409' USING MESSAGE = 'upgrade_required';
      END;
      IF v_marker IS NULL OR v_marker->>'household_id' IS DISTINCT FROM OLD.household_id::text
          OR v_marker->>'revision' IS DISTINCT FROM OLD.sync_revision::text
          OR v_marker->>'request_id' IS NULL OR v_marker->'data' IS DISTINCT FROM NEW.data THEN
        RAISE SQLSTATE 'PT409' USING MESSAGE = 'upgrade_required';
      END IF;
      NEW.last_request_id := (v_marker->>'request_id')::uuid;
    ELSE
      NEW.last_request_id := NULL;
    END IF;
    -- Every UPDATE advances the server revision, including maintenance/activation.
    NEW.sync_revision := OLD.sync_revision + 1;
  END IF;
  IF NOT v_maintenance THEN
    NEW.updated_by := auth.uid();
    NEW.updated_at := clock_timestamp();
  END IF;
  RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION public.family_state_sync_guard() FROM PUBLIC, anon, authenticated;
CREATE TRIGGER family_state_sync_guard BEFORE INSERT OR UPDATE OR DELETE ON public.family_state
FOR EACH ROW EXECUTE FUNCTION public.family_state_sync_guard();

CREATE FUNCTION public.family_state_cas(p_household_id uuid, p_expected_revision bigint,
  p_data jsonb, p_request_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $cas$
DECLARE v_row public.family_state%ROWTYPE; v_status text; v_previous_marker text; v_updated boolean;
BEGIN
  IF auth.uid() IS NULL THEN
    RAISE insufficient_privilege USING MESSAGE = 'Authenticated user required';
  END IF;
  IF p_household_id IS NULL OR p_expected_revision IS NULL OR p_expected_revision < 0
      OR p_request_id IS NULL OR p_data IS NULL OR jsonb_typeof(p_data) <> 'object' THEN
    RAISE invalid_parameter_value USING MESSAGE = 'Invalid CAS request';
  END IF;
  -- The row lock serializes writers. SECURITY INVOKER preserves table privileges/RLS.
  SELECT * INTO v_row FROM public.family_state WHERE household_id = p_household_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('status','not_found','revision',NULL,'protocol',NULL,'data',NULL,'request_id',NULL);
  END IF;
  IF v_row.sync_protocol <> 2 THEN
    v_status := 'upgrade_required';
  ELSIF v_row.last_request_id = p_request_id THEN
    v_status := CASE WHEN v_row.data = p_data THEN 'written' ELSE 'conflict' END;
  ELSIF v_row.sync_revision <> p_expected_revision THEN
    v_status := 'conflict';
  ELSE
    v_previous_marker := current_setting('marichevy_sync.cas', true);
    PERFORM set_config('marichevy_sync.cas', jsonb_build_object('household_id', p_household_id,
      'revision', p_expected_revision, 'request_id', p_request_id, 'data', p_data)::text, true);
    BEGIN
      UPDATE public.family_state SET data = p_data
        WHERE household_id = p_household_id AND sync_revision = p_expected_revision
        RETURNING * INTO v_row;
      v_updated := FOUND;
      PERFORM set_config('marichevy_sync.cas', coalesce(v_previous_marker, ''), true);
    EXCEPTION WHEN OTHERS THEN
      PERFORM set_config('marichevy_sync.cas', coalesce(v_previous_marker, ''), true);
      RAISE;
    END;
    IF NOT v_updated THEN
      RETURN jsonb_build_object('status','not_found','revision',NULL,'protocol',NULL,'data',NULL,'request_id',NULL);
    END IF;
    v_status := 'written';
  END IF;
  RETURN jsonb_build_object('status',v_status,'revision',v_row.sync_revision,
    'protocol',v_row.sync_protocol,'data',v_row.data,'request_id',v_row.last_request_id);
END
$cas$;
REVOKE ALL ON FUNCTION public.family_state_cas(uuid,bigint,jsonb,uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.family_state_cas(uuid,bigint,jsonb,uuid) TO authenticated;
-- No policy, RLS flag, existing grants or household data is changed by this migration.
COMMIT;

-- REVIEW/STAGING CANDIDATE ONLY. Apply with the coordinated server/client release.
-- Catalog-shaped preflight; does not read or replace any family rows.
-- Keep CRUD grants, service_role grants, RLS policies and functions unchanged.
BEGIN;
SET LOCAL search_path = pg_catalog, public;
DO $preflight$
DECLARE v_name text; v_oid oid;
BEGIN
  IF current_user <> 'postgres' THEN
    RAISE EXCEPTION 'Expected postgres table owner for capability hardening';
  END IF;
  IF EXISTS (SELECT 1 FROM unnest(ARRAY['anon','authenticated','service_role']) AS r(name)
      WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r.name)) THEN
    RAISE EXCEPTION 'Expected Supabase anon, authenticated and service_role roles';
  END IF;
  FOREACH v_name IN ARRAY ARRAY['family_state','households','household_members','family_chore_deliveries'] LOOP
    v_oid := to_regclass(format('public.%I', v_name));
    IF v_oid IS NULL OR NOT EXISTS (SELECT 1 FROM pg_class WHERE oid = v_oid
        AND relkind = 'r' AND relrowsecurity AND pg_get_userbyid(relowner) = 'postgres') THEN
      RAISE EXCEPTION 'Expected ordinary public.% table owned by postgres with RLS enabled', v_name;
    END IF;
  END LOOP;
END
$preflight$;

REVOKE TRUNCATE, TRIGGER ON public.family_state, public.households,
  public.household_members, public.family_chore_deliveries
  FROM PUBLIC, anon, authenticated;

DO $verify$
DECLARE v_name text; v_role text;
BEGIN
  FOREACH v_name IN ARRAY ARRAY['family_state','households','household_members','family_chore_deliveries'] LOOP
    FOREACH v_role IN ARRAY ARRAY['anon','authenticated'] LOOP
      IF has_table_privilege(v_role, format('public.%I', v_name), 'TRUNCATE')
          OR has_table_privilege(v_role, format('public.%I', v_name), 'TRIGGER') THEN
        -- Inherited rights cannot be removed by this narrowly scoped revoke.
        -- Refuse/roll back; review the role graph rather than changing it here.
        RAISE EXCEPTION 'Effective TRUNCATE/TRIGGER remains for % on public.%; review inherited privileges', v_role, v_name;
      END IF;
    END LOOP;
  END LOOP;
END
$verify$;
COMMIT;

-- REVIEW/STAGING CANDIDATE ONLY. No family rows or policy definitions change.
-- The authenticated lookup is bound to its verified Auth identity. service_role
-- retains the original arbitrary-user lookup for existing trusted workers.
-- auth.role() is a JWT claim supplied by PostgREST, not current_user (postgres
-- inside SECURITY DEFINER). This contract assumes no untrusted arbitrary SQL.
BEGIN;
SET LOCAL search_path = pg_catalog, public;
DO $preflight$
DECLARE v_fn pg_proc%ROWTYPE; v_name text; v_original text; v_bound text;
BEGIN
  IF current_user <> 'postgres' THEN
    RAISE EXCEPTION 'Expected postgres owner for membership lookup hardening';
  END IF;
  IF EXISTS (SELECT 1 FROM unnest(ARRAY['anon','authenticated','service_role']) AS r(name)
      WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r.name)) THEN
    RAISE EXCEPTION 'Expected Supabase application roles';
  END IF;
  IF to_regprocedure('auth.uid()') IS NULL OR to_regprocedure('auth.role()') IS NULL
      OR (SELECT prorettype FROM pg_proc WHERE oid=to_regprocedure('auth.uid()')) <> 'uuid'::regtype
      OR (SELECT prorettype FROM pg_proc WHERE oid=to_regprocedure('auth.role()')) <> 'text'::regtype THEN
    RAISE EXCEPTION 'Expected Supabase auth.uid() and auth.role()';
  END IF;
  FOREACH v_name IN ARRAY ARRAY['family_state','households','household_members','family_chore_deliveries'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_class WHERE oid = to_regclass(format('public.%I', v_name))
        AND relkind='r' AND relrowsecurity AND pg_get_userbyid(relowner)='postgres') THEN
      RAISE EXCEPTION 'Expected ordinary RLS public.% table owned by postgres', v_name;
    END IF;
  END LOOP;
  IF (SELECT count(*) FROM pg_proc WHERE pronamespace='public'::regnamespace
      AND proname='is_household_member') <> 1 THEN
    RAISE EXCEPTION 'Expected only the reviewed membership lookup overload';
  END IF;
  SELECT * INTO v_fn FROM pg_proc WHERE oid=to_regprocedure('public.is_household_member(uuid,uuid)');
  IF NOT FOUND OR v_fn.prokind <> 'f' OR v_fn.proretset
      OR v_fn.proargtypes <> ARRAY['uuid'::regtype::oid,'uuid'::regtype::oid]::oidvector
      OR v_fn.proargnames IS DISTINCT FROM ARRAY['p_household_id','p_user_id']::text[]
      OR v_fn.proargmodes IS NOT NULL OR v_fn.pronargdefaults <> 0 OR v_fn.provariadic <> 0
      OR v_fn.prorettype <> 'boolean'::regtype
      OR v_fn.prolang <> (SELECT oid FROM pg_language WHERE lanname='sql')
      OR pg_get_userbyid(v_fn.proowner) <> 'postgres' OR NOT v_fn.prosecdef
      OR v_fn.provolatile <> 'v' OR v_fn.proleakproof THEN
    RAISE EXCEPTION 'Unsupported membership lookup signature or security attributes';
  END IF;
  v_original := 'selectexists(select1frompublic.household_membershmwherehm.household_id=p_household_idandhm.user_id=p_user_id);';
  v_bound := $normalized$selectexists(select1frompublic.household_membershmwherehm.household_id=p_household_idandhm.user_id=p_user_idand(auth.role()='service_role'orp_user_id=auth.uid()));$normalized$;
  IF NOT (
      (regexp_replace(lower(v_fn.prosrc), '[[:space:]]', '', 'g')=v_original
        AND v_fn.proconfig IS NOT DISTINCT FROM ARRAY['search_path=public']::text[])
      OR (regexp_replace(lower(v_fn.prosrc), '[[:space:]]', '', 'g')=v_bound
        AND v_fn.proconfig IS NOT DISTINCT FROM ARRAY['search_path=pg_catalog, public']::text[])) THEN
    RAISE EXCEPTION 'Membership lookup source/search_path differs from reviewed original or exact hardened candidate';
  END IF;
  IF EXISTS (
    WITH expected(table_name,policy_name,command,qual,check_qual) AS (VALUES
      ('family_state','members can insert family state','a',NULL::text,'is_household_member(household_id,auth.uid())'),
      ('family_state','members can read family state','r','is_household_member(household_id,auth.uid())',NULL::text),
      ('family_state','members can update family state','w','is_household_member(household_id,auth.uid())','is_household_member(household_id,auth.uid())'),
      ('household_members','members can view family members','r','is_household_member(household_id,auth.uid())',NULL::text),
      ('households','members can view their households','r','is_household_member(id,auth.uid())',NULL::text)),
    actual AS (SELECT c.relname::text AS table_name, p.polname::text AS policy_name,
      p.polcmd::text AS command, p.polpermissive, p.polroles,
      regexp_replace(pg_get_expr(p.polqual,p.polrelid),'[[:space:]]','','g') AS qual,
      regexp_replace(pg_get_expr(p.polwithcheck,p.polrelid),'[[:space:]]','','g') AS check_qual
      FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid
      WHERE c.relnamespace='public'::regnamespace AND c.relname IN
        ('family_state','households','household_members','family_chore_deliveries'))
    SELECT 1 FROM expected e FULL JOIN actual a USING(table_name,policy_name)
      WHERE e.table_name IS NULL OR a.table_name IS NULL
        OR a.command IS DISTINCT FROM e.command OR NOT a.polpermissive
        OR a.polroles IS DISTINCT FROM ARRAY['authenticated'::regrole::oid]::oid[]
        OR a.qual IS DISTINCT FROM e.qual OR a.check_qual IS DISTINCT FROM e.check_qual
  ) THEN
    RAISE EXCEPTION 'Membership RLS policies differ from the reviewed five-policy catalog';
  END IF;
END
$preflight$;

CREATE OR REPLACE FUNCTION public.is_household_member(p_household_id uuid,p_user_id uuid)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, public AS $membership$
  SELECT EXISTS (SELECT 1 FROM public.household_members hm
    WHERE hm.household_id = p_household_id AND hm.user_id = p_user_id
      AND (auth.role() = 'service_role' OR p_user_id = auth.uid()));
$membership$;
REVOKE ALL ON FUNCTION public.is_household_member(uuid,uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_household_member(uuid,uuid) TO authenticated, service_role;

DO $verify$
BEGIN
  IF has_function_privilege('anon','public.is_household_member(uuid,uuid)','EXECUTE') THEN
    RAISE EXCEPTION 'Effective anonymous membership lookup remains; review inherited privileges';
  END IF;
  IF NOT has_function_privilege('authenticated','public.is_household_member(uuid,uuid)','EXECUTE')
      OR NOT has_function_privilege('service_role','public.is_household_member(uuid,uuid)','EXECUTE') THEN
    RAISE EXCEPTION 'Required authenticated/service_role lookup access missing';
  END IF;
END
$verify$;
COMMIT;

-- Actual readiness metadata only; no household IDs, expenses, or private hashes.
WITH checks AS (
  SELECT
    (SELECT array_agg(attname::text || ':' || format_type(atttypid,atttypmod)
      || ':' || attnotnull::text ORDER BY attname)
      FROM pg_attribute WHERE attrelid='public.family_state'::regclass
        AND attnum>0 AND NOT attisdropped) = ARRAY[
      'data:jsonb:true','household_id:uuid:true','last_request_id:uuid:false',
      'sync_protocol:smallint:true','sync_revision:bigint:true',
      'updated_at:timestamp with time zone:true','updated_by:uuid:false'
    ]::text[] AS schema_ready,
    EXISTS (SELECT FROM pg_proc p
      WHERE p.oid=to_regprocedure('public.family_state_cas(uuid,bigint,jsonb,uuid)')
        AND NOT p.prosecdef AND pg_get_userbyid(p.proowner)='postgres'
        AND p.prorettype='jsonb'::regtype
        AND p.proconfig=ARRAY['search_path=pg_catalog, public']::text[])
    AND EXISTS (SELECT FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid
      WHERE t.tgrelid='public.family_state'::regclass
        AND t.tgname='family_state_sync_guard' AND NOT t.tgisinternal
        AND t.tgenabled='O' AND t.tgtype=31 AND t.tgnargs=0
        AND p.oid=to_regprocedure('public.family_state_sync_guard()')
        AND NOT p.prosecdef AND pg_get_userbyid(p.proowner)='postgres')
    AND has_function_privilege('authenticated',
      'public.family_state_cas(uuid,bigint,jsonb,uuid)','EXECUTE')
    AND NOT has_function_privilege('anon',
      'public.family_state_cas(uuid,bigint,jsonb,uuid)','EXECUTE') AS cas_ready,
    NOT EXISTS (SELECT FROM unnest(ARRAY['family_state','households',
      'household_members','family_chore_deliveries']) AS t(name)
      CROSS JOIN unnest(ARRAY['anon','authenticated']) AS r(name)
      WHERE has_table_privilege(r.name,format('public.%I',t.name),'TRUNCATE')
        OR has_table_privilege(r.name,format('public.%I',t.name),'TRIGGER'))
      AS table_permissions_ready,
    EXISTS (SELECT FROM pg_proc p
      WHERE p.oid=to_regprocedure('public.is_household_member(uuid,uuid)')
        AND p.prosecdef AND pg_get_userbyid(p.proowner)='postgres'
        AND p.proconfig=ARRAY['search_path=pg_catalog, public']::text[]
        AND regexp_replace(lower(p.prosrc),'[[:space:]]','','g')=
          $bound$selectexists(select1frompublic.household_membershmwherehm.household_id=p_household_idandhm.user_id=p_user_idand(auth.role()='service_role'orp_user_id=auth.uid()));$bound$)
    AND NOT has_function_privilege('anon',
      'public.is_household_member(uuid,uuid)','EXECUTE')
    AND has_function_privilege('authenticated',
      'public.is_household_member(uuid,uuid)','EXECUTE')
    AND has_function_privilege('service_role',
      'public.is_household_member(uuid,uuid)','EXECUTE') AS membership_ready,
    (SELECT count(*)=1 FROM public.family_state)
    AND NOT EXISTS (SELECT FROM public.family_state
      WHERE sync_protocol IS DISTINCT FROM 1 OR sync_revision IS DISTINCT FROM 0
        OR last_request_id IS NOT NULL) AS activation_pending
)
SELECT schema_ready, cas_ready, table_permissions_ready, membership_ready,
  activation_pending,
  schema_ready AND cas_ready AND table_permissions_ready AND membership_ready
    AND activation_pending AS ready
FROM checks;

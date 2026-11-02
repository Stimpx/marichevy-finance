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

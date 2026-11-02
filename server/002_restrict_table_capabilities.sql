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

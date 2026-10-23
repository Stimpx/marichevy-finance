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

-- FICTIONAL STAGING / REVIEW ONLY. Independent public-account storage.
-- Does not read or change legacy public households, members, family_state or policies.
-- Run once as postgres. A pre-existing finance_app schema fails closed for review.
BEGIN;
DO $preflight$
BEGIN
  IF current_user <> 'postgres' OR to_regnamespace('finance_app') IS NOT NULL
      OR to_regclass('auth.users') IS NULL OR to_regprocedure('auth.uid()') IS NULL
      OR to_regprocedure('auth.role()') IS NULL
      OR NOT EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated')
      OR NOT EXISTS (SELECT FROM pg_roles WHERE rolname='anon')
      OR NOT EXISTS (SELECT FROM pg_roles WHERE rolname='service_role') THEN
    RAISE EXCEPTION 'Expected postgres, fresh finance_app schema and Supabase Auth roles/users';
  END IF;
  IF EXISTS (SELECT FROM pg_proc WHERE pronamespace='public'::regnamespace
      AND proname LIKE 'finance\_%' ESCAPE '\') THEN
    RAISE EXCEPTION 'Existing finance_* RPCs require explicit review';
  END IF;
END
$preflight$;

CREATE SCHEMA finance_app AUTHORIZATION postgres;
REVOKE ALL ON SCHEMA finance_app FROM PUBLIC, anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA finance_app REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA finance_app REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated, service_role;

CREATE TABLE finance_app.households (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 100 AND name=btrim(name)),
  timezone text NOT NULL,
  settings jsonb NOT NULL DEFAULT '{"people":[],"categories":[]}'::jsonb,
  created_by uuid NOT NULL REFERENCES auth.users(id),
  creation_request_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  settings_request_id uuid,
  settings_request_payload jsonb,
  UNIQUE (created_by,creation_request_id)
);
CREATE TABLE finance_app.members (
  household_id uuid NOT NULL REFERENCES finance_app.households(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users(id),
  role text NOT NULL CHECK (role IN ('owner','editor','viewer')),
  joined_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (household_id,user_id)
);
CREATE INDEX finance_members_user ON finance_app.members(user_id,household_id);
CREATE TABLE finance_app.family_state (
  household_id uuid PRIMARY KEY REFERENCES finance_app.households(id) ON DELETE CASCADE,
  data jsonb NOT NULL CHECK (jsonb_typeof(data)='object'),
  sync_revision bigint NOT NULL DEFAULT 0 CHECK (sync_revision>=0),
  sync_protocol smallint NOT NULL DEFAULT 2 CHECK (sync_protocol=2),
  last_request_id uuid,
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_by uuid NOT NULL REFERENCES auth.users(id)
);
CREATE TABLE finance_app.invitations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id uuid NOT NULL REFERENCES finance_app.households(id) ON DELETE CASCADE,
  email text NOT NULL CHECK (email=lower(btrim(email)) AND length(email) BETWEEN 3 AND 254),
  role text NOT NULL CHECK (role IN ('editor','viewer')),
  created_by uuid NOT NULL REFERENCES auth.users(id),
  request_id uuid NOT NULL,
  token_hash text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','revoked')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  expires_at timestamptz NOT NULL DEFAULT (clock_timestamp()+interval '72 hours'),
  accepted_at timestamptz,
  accepted_by uuid REFERENCES auth.users(id),
  revoked_at timestamptz,
  UNIQUE (household_id,created_by,request_id),
  CHECK ((status='accepted')=(accepted_at IS NOT NULL AND accepted_by IS NOT NULL))
);
CREATE INDEX finance_invitations_household ON finance_app.invitations(household_id,created_at);
-- Only invitation delivery metadata. Never store financial JSON, raw tokens or SMTP responses.
CREATE TABLE finance_app.mail_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  invite_id uuid NOT NULL UNIQUE REFERENCES finance_app.invitations(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','leased','sent','failed','cancelled')),
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
  available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  worker_id uuid,
  lease_id uuid,
  lease_until timestamptz,
  sent_at timestamptz,
  error_code text CHECK (error_code ~ '^[a-z0-9_]{1,40}$')
);
CREATE INDEX finance_mail_ready ON finance_app.mail_jobs(available_at) WHERE status IN ('pending','leased');

-- No direct client table access: all five tables additionally fail closed under RLS.
ALTER TABLE finance_app.households ENABLE ROW LEVEL SECURITY;
ALTER TABLE finance_app.members ENABLE ROW LEVEL SECURITY;
ALTER TABLE finance_app.family_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE finance_app.invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE finance_app.mail_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON ALL TABLES IN SCHEMA finance_app FROM PUBLIC, anon, authenticated, service_role;

CREATE FUNCTION finance_app.verified_user() RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_user uuid:=auth.uid();
BEGIN
  -- Current Auth rows are authoritative; JWT email/metadata/confirmation claims are ignored.
  IF auth.role() IS DISTINCT FROM 'authenticated' OR v_user IS NULL
      OR NOT EXISTS (SELECT FROM auth.users WHERE id=v_user
        AND email_confirmed_at IS NOT NULL AND email IS NOT NULL AND btrim(email)<>'') THEN
    RAISE insufficient_privilege USING MESSAGE='Verified authenticated user required';
  END IF;
  RETURN v_user;
END
$f$;
CREATE FUNCTION finance_app.require_role(p_household_id uuid,p_user_id uuid,p_roles text[])
RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_role text;
BEGIN
  SELECT role INTO v_role FROM finance_app.members
    WHERE household_id=p_household_id AND user_id=p_user_id;
  IF v_role IS NULL OR NOT (v_role=ANY(p_roles)) THEN
    RAISE insufficient_privilege USING MESSAGE='Household access denied';
  END IF;
  RETURN v_role;
END
$f$;
CREATE FUNCTION finance_app.lock_household(p_household_id uuid) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
BEGIN
  -- Always acquire this lock before a member/invitation/state row lock.
  -- Revocation, acceptance, CAS and last-owner changes therefore serialize.
  PERFORM 1 FROM finance_app.households WHERE id=p_household_id FOR UPDATE;
  IF NOT FOUND THEN RAISE insufficient_privilege USING MESSAGE='Household access denied'; END IF;
END
$f$;
CREATE FUNCTION finance_app.check_settings(p_name text,p_timezone text,p_people jsonb,p_categories jsonb)
RETURNS void LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_items jsonb; v_item jsonb; v_name text; v_id text; v_names text[]; v_ids text[]; v_archived boolean;
BEGIN
  IF p_name IS NULL OR length(btrim(p_name)) NOT BETWEEN 1 AND 100
      OR p_timezone IS NULL OR NOT EXISTS (SELECT FROM pg_timezone_names WHERE name=p_timezone)
      OR p_people IS NULL OR jsonb_typeof(p_people)<>'array'
      OR p_categories IS NULL OR jsonb_typeof(p_categories)<>'array' THEN
    RAISE invalid_parameter_value USING MESSAGE='Invalid household settings';
  END IF;
  IF jsonb_array_length(p_people)>100 OR jsonb_array_length(p_categories)>200
      OR octet_length(p_people::text)>65536 OR octet_length(p_categories::text)>65536 THEN
    RAISE invalid_parameter_value USING MESSAGE='Household settings too large';
  END IF;
  FOREACH v_items IN ARRAY ARRAY[p_people,p_categories] LOOP
    v_names:=ARRAY[]::text[]; v_ids:=ARRAY[]::text[];
    FOR v_item IN SELECT value FROM jsonb_array_elements(v_items) LOOP
      v_id:=NULL; v_archived:=false;
      IF jsonb_typeof(v_item)='string' THEN
        -- Compatibility with earlier review clients; current UI writes stable IDs.
        v_name:=v_item#>>'{}';
      ELSIF jsonb_typeof(v_item)='object' THEN
        v_name:=v_item->>'name'; v_id:=v_item->>'id';
        IF jsonb_typeof(v_item->'name') IS DISTINCT FROM 'string'
            OR jsonb_typeof(v_item->'id') IS DISTINCT FROM 'string'
            OR v_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            OR (v_item ? 'archived' AND jsonb_typeof(v_item->'archived') IS DISTINCT FROM 'boolean') THEN
          RAISE invalid_parameter_value USING MESSAGE='Invalid household catalog item';
        END IF;
        v_archived:=coalesce((v_item->>'archived')::boolean,false);
        IF lower(v_id)=ANY(v_ids) THEN
          RAISE invalid_parameter_value USING MESSAGE='Duplicate household catalog identifier';
        END IF;
        v_ids:=array_append(v_ids,lower(v_id));
      ELSE RAISE invalid_parameter_value USING MESSAGE='Invalid household catalog item';
      END IF;
      IF v_name IS NULL OR length(v_name) NOT BETWEEN 1 AND 120 OR v_name<>btrim(v_name) THEN
        RAISE invalid_parameter_value USING MESSAGE='Invalid household catalog name';
      END IF;
      IF NOT v_archived THEN
        IF lower(v_name)=ANY(v_names) THEN
          RAISE invalid_parameter_value USING MESSAGE='Duplicate active household catalog name';
        END IF;
        v_names:=array_append(v_names,lower(v_name));
      END IF;
    END LOOP;
  END LOOP;
END
$f$;
CREATE FUNCTION finance_app.household_json(p_household_id uuid,p_user_id uuid) RETURNS jsonb
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
  SELECT jsonb_build_object('id',h.id,'household_id',h.id,'name',h.name,'timezone',h.timezone,
    'settings',h.settings,'role',m.role,'plan','free')
  FROM finance_app.households h JOIN finance_app.members m ON m.household_id=h.id
  WHERE h.id=p_household_id AND m.user_id=p_user_id
$f$;
CREATE FUNCTION finance_app.invite_json(p_invite_id uuid) RETURNS jsonb
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
  SELECT jsonb_build_object('id',i.id,'household_id',i.household_id,'email',i.email,'role',i.role,
    'request_id',i.request_id,'created_by',i.created_by,'created_at',i.created_at,
    'expires_at',i.expires_at,'status',CASE WHEN i.status='pending' AND i.expires_at<=clock_timestamp()
      THEN 'expired' ELSE i.status END,'mail_status',j.status)
  FROM finance_app.invitations i LEFT JOIN finance_app.mail_jobs j ON j.invite_id=i.id
  WHERE i.id=p_invite_id
$f$;

CREATE FUNCTION public.finance_list_households() RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_user uuid:=finance_app.verified_user(); v_result jsonb;
BEGIN
  SELECT coalesce(jsonb_agg(finance_app.household_json(h.id,v_user) ORDER BY h.created_at,h.id),'[]'::jsonb)
  INTO v_result FROM finance_app.households h JOIN finance_app.members m ON m.household_id=h.id
    WHERE m.user_id=v_user;
  RETURN v_result;
END
$f$;
CREATE FUNCTION public.finance_create_household(p_name text,p_timezone text,p_request_id uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_user uuid:=finance_app.verified_user(); v_id uuid; v_new boolean; v_settings jsonb;
BEGIN
  PERFORM finance_app.check_settings(p_name,p_timezone,'[]','[]');
  IF p_request_id IS NULL THEN RAISE invalid_parameter_value USING MESSAGE='Request UUID required'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('finance-create:'||v_user::text,0));
  SELECT id INTO v_id FROM finance_app.households WHERE created_by=v_user AND creation_request_id=p_request_id;
  IF FOUND THEN
    PERFORM finance_app.require_role(v_id,v_user,ARRAY['owner','editor','viewer']);
    RETURN finance_app.household_json(v_id,v_user);
  END IF;
  IF (SELECT count(*) FROM finance_app.households WHERE created_by=v_user)>=20
      OR (SELECT count(*) FROM finance_app.households WHERE created_by=v_user
        AND created_at>clock_timestamp()-interval '24 hours')>=5 THEN
    RAISE SQLSTATE 'PT429' USING MESSAGE='Family creation rate limit reached';
  END IF;
  -- Product catalogs only: stable family-local IDs, no personal names or history.
  SELECT jsonb_build_object('people',jsonb_build_array(jsonb_build_object('id',gen_random_uuid(),
      'name','Общее','archived',false)),'categories',jsonb_agg(jsonb_build_object('id',gen_random_uuid(),
      'name',label,'archived',false) ORDER BY ordinal)) INTO v_settings
    FROM unnest(ARRAY['Продукты','Кафе','Транспорт','Дом','Здоровье','Дети','Подписки','Прочее'])
      WITH ORDINALITY AS labels(label,ordinal);
  -- Unique request key handles concurrent retries without creating another family.
  INSERT INTO finance_app.households(name,timezone,settings,created_by,creation_request_id)
    VALUES(btrim(p_name),p_timezone,v_settings,v_user,p_request_id)
    ON CONFLICT(created_by,creation_request_id) DO NOTHING RETURNING id INTO v_id;
  v_new:=FOUND;
  IF v_new THEN
    INSERT INTO finance_app.members(household_id,user_id,role) VALUES(v_id,v_user,'owner');
    INSERT INTO finance_app.family_state(household_id,updated_by,data) VALUES(v_id,v_user,
      '{"entries":[],"goals":[],"birthdays":[],"boardItems":[],"chores":[],"installments":[],"intelligence":{"budgets":[],"recurring":[],"accounts":[]},"settings":{}}');
  ELSE
    SELECT id INTO v_id FROM finance_app.households
      WHERE created_by=v_user AND creation_request_id=p_request_id;
    PERFORM finance_app.require_role(v_id,v_user,ARRAY['owner','editor','viewer']);
  END IF;
  RETURN finance_app.household_json(v_id,v_user);
END
$f$;
CREATE FUNCTION public.finance_get_household(p_household_id uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_user uuid:=finance_app.verified_user();
BEGIN
  PERFORM finance_app.require_role(p_household_id,v_user,ARRAY['owner','editor','viewer']);
  RETURN finance_app.household_json(p_household_id,v_user);
END
$f$;
CREATE FUNCTION public.finance_update_settings(p_household_id uuid,p_name text,p_timezone text,
  p_people jsonb,p_categories jsonb,p_request_id uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_user uuid:=finance_app.verified_user(); v_payload jsonb; v_row finance_app.households%ROWTYPE;
BEGIN
  PERFORM finance_app.lock_household(p_household_id);
  PERFORM finance_app.require_role(p_household_id,v_user,ARRAY['owner']);
  PERFORM finance_app.check_settings(p_name,p_timezone,p_people,p_categories);
  IF p_request_id IS NULL THEN RAISE invalid_parameter_value USING MESSAGE='Request UUID required'; END IF;
  v_payload:=jsonb_build_object('name',btrim(p_name),'timezone',p_timezone,'people',p_people,'categories',p_categories);
  SELECT * INTO v_row FROM finance_app.households WHERE id=p_household_id;
  IF v_row.settings_request_id=p_request_id THEN
    IF v_row.settings_request_payload IS DISTINCT FROM v_payload THEN
      RAISE invalid_parameter_value USING MESSAGE='Request UUID payload differs';
    END IF;
    RETURN finance_app.household_json(p_household_id,v_user);
  END IF;
  UPDATE finance_app.households SET name=btrim(p_name),timezone=p_timezone,
    settings=jsonb_build_object('people',p_people,'categories',p_categories),
    settings_request_id=p_request_id,settings_request_payload=v_payload WHERE id=p_household_id;
  -- Household catalogs are separate from ledger settings (loan/preferences/etc).
  -- Updating household metadata never rewrites a financial document or its revision.
  RETURN finance_app.household_json(p_household_id,v_user);
END
$f$;
CREATE FUNCTION public.finance_list_members(p_household_id uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_user uuid:=finance_app.verified_user(); v_result jsonb;
BEGIN
  PERFORM finance_app.require_role(p_household_id,v_user,ARRAY['owner','editor','viewer']);
  SELECT coalesce(jsonb_agg(jsonb_build_object('user_id',m.user_id,'role',m.role,'email',u.email,
    'joined_at',m.joined_at) ORDER BY m.joined_at,m.user_id),'[]'::jsonb) INTO v_result
    FROM finance_app.members m JOIN auth.users u ON u.id=m.user_id WHERE m.household_id=p_household_id;
  RETURN v_result;
END
$f$;
CREATE FUNCTION public.finance_set_member_role(p_household_id uuid,p_user_id uuid,p_role text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_user uuid:=finance_app.verified_user(); v_old text;
BEGIN
  PERFORM finance_app.lock_household(p_household_id);
  PERFORM finance_app.require_role(p_household_id,v_user,ARRAY['owner']);
  IF p_role IS NULL OR p_role NOT IN ('editor','viewer') THEN
    RAISE invalid_parameter_value USING MESSAGE='Only editor or viewer can be assigned';
  END IF;
  SELECT role INTO v_old FROM finance_app.members WHERE household_id=p_household_id AND user_id=p_user_id;
  IF NOT FOUND THEN RAISE invalid_parameter_value USING MESSAGE='Member not found'; END IF;
  IF v_old='owner' AND (SELECT count(*) FROM finance_app.members WHERE household_id=p_household_id AND role='owner')<=1 THEN
    RAISE check_violation USING MESSAGE='Last owner cannot be demoted';
  END IF;
  UPDATE finance_app.members SET role=p_role WHERE household_id=p_household_id AND user_id=p_user_id;
  RETURN jsonb_build_object('user_id',p_user_id,'role',p_role,'status','updated');
END
$f$;
CREATE FUNCTION public.finance_remove_member(p_household_id uuid,p_user_id uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_user uuid:=finance_app.verified_user(); v_old text; v_email text;
BEGIN
  PERFORM finance_app.lock_household(p_household_id);
  PERFORM finance_app.require_role(p_household_id,v_user,ARRAY['owner']);
  SELECT role INTO v_old FROM finance_app.members WHERE household_id=p_household_id AND user_id=p_user_id;
  IF v_old='owner' AND (SELECT count(*) FROM finance_app.members WHERE household_id=p_household_id AND role='owner')<=1 THEN
    RAISE check_violation USING MESSAGE='Last owner cannot be removed';
  END IF;
  DELETE FROM finance_app.members WHERE household_id=p_household_id AND user_id=p_user_id;
  SELECT lower(btrim(email)) INTO v_email FROM auth.users WHERE id=p_user_id;
  -- Removing access invalidates all earlier outstanding grants for this address.
  -- A second, previously issued invitation must not silently undo revocation.
  UPDATE finance_app.invitations SET status='revoked',revoked_at=clock_timestamp()
    WHERE household_id=p_household_id AND email=v_email AND status='pending';
  UPDATE finance_app.mail_jobs j SET status='cancelled',lease_id=NULL,lease_until=NULL
    FROM finance_app.invitations i WHERE i.id=j.invite_id AND i.household_id=p_household_id
      AND i.email=v_email AND i.status='revoked' AND j.status IN ('pending','leased');
  RETURN jsonb_build_object('user_id',p_user_id,'status','removed');
END
$f$;

CREATE FUNCTION public.finance_create_invite(p_household_id uuid,p_email text,p_role text,p_request_id uuid,p_token_hash text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_user uuid:=finance_app.verified_user(); v_email text:=lower(btrim(p_email));
  v_row finance_app.invitations%ROWTYPE; v_created timestamptz;
BEGIN
  PERFORM finance_app.lock_household(p_household_id);
  PERFORM finance_app.require_role(p_household_id,v_user,ARRAY['owner']);
  IF v_email IS NULL OR length(v_email) NOT BETWEEN 3 AND 254 OR v_email !~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'
      OR p_role IS NULL OR p_role NOT IN ('editor','viewer') OR p_request_id IS NULL
      OR p_token_hash IS NULL OR p_token_hash !~ '^[0-9a-f]{64}$' THEN
    RAISE invalid_parameter_value USING MESSAGE='Invalid invitation';
  END IF;
  SELECT * INTO v_row FROM finance_app.invitations
    WHERE household_id=p_household_id AND created_by=v_user AND request_id=p_request_id;
  IF FOUND THEN
    IF v_row.email<>v_email OR v_row.role<>p_role OR v_row.token_hash<>p_token_hash THEN
      RAISE invalid_parameter_value USING MESSAGE='Request UUID payload differs';
    END IF;
    RETURN finance_app.invite_json(v_row.id);
  END IF;
  -- Actor and recipient budgets span every household. User/email advisory locks
  -- serialize concurrent requests against these global limits.
  PERFORM pg_advisory_xact_lock(hashtextextended('finance-invite-user:'||v_user::text,0));
  PERFORM pg_advisory_xact_lock(hashtextextended('finance-invite-email:'||v_email,0));
  IF (SELECT count(*) FROM finance_app.invitations WHERE created_by=v_user
      AND created_at>clock_timestamp()-interval '1 hour')>=30
      OR (SELECT count(*) FROM finance_app.invitations WHERE email=v_email
        AND created_at>clock_timestamp()-interval '1 hour')>=5 THEN
    RAISE SQLSTATE 'PT429' USING MESSAGE='Invitation rate limit reached';
  END IF;
  IF (SELECT count(*) FROM finance_app.invitations WHERE household_id=p_household_id
      AND created_at>clock_timestamp()-interval '1 hour')>=30 THEN
    RAISE SQLSTATE 'PT429' USING MESSAGE='Invitation rate limit reached';
  END IF;
  v_created:=clock_timestamp();
  INSERT INTO finance_app.invitations(household_id,email,role,created_by,request_id,token_hash,created_at,expires_at)
    VALUES(p_household_id,v_email,p_role,v_user,p_request_id,p_token_hash,v_created,v_created+interval '72 hours')
    RETURNING * INTO v_row;
  INSERT INTO finance_app.mail_jobs(invite_id) VALUES(v_row.id);
  RETURN finance_app.invite_json(v_row.id);
END
$f$;
CREATE FUNCTION public.finance_list_invites(p_household_id uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_user uuid:=finance_app.verified_user(); v_result jsonb;
BEGIN
  PERFORM finance_app.require_role(p_household_id,v_user,ARRAY['owner']);
  SELECT coalesce(jsonb_agg(finance_app.invite_json(id) ORDER BY created_at DESC,id),'[]'::jsonb)
    INTO v_result FROM finance_app.invitations WHERE household_id=p_household_id;
  RETURN v_result;
END
$f$;
CREATE FUNCTION public.finance_accept_invite(p_token text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_user uuid:=finance_app.verified_user(); v_email text; v_household uuid; v_row finance_app.invitations%ROWTYPE;
BEGIN
  IF p_token IS NULL OR p_token !~ '^[0-9a-f]{64}$' THEN
    RAISE invalid_parameter_value USING MESSAGE='Invalid or expired invitation';
  END IF;
  SELECT household_id INTO v_household FROM finance_app.invitations
    WHERE token_hash=encode(sha256(convert_to(p_token,'UTF8')),'hex');
  IF v_household IS NULL THEN RAISE invalid_parameter_value USING MESSAGE='Invalid or expired invitation'; END IF;
  PERFORM finance_app.lock_household(v_household);
  SELECT * INTO v_row FROM finance_app.invitations
    WHERE token_hash=encode(sha256(convert_to(p_token,'UTF8')),'hex') FOR UPDATE;
  -- Lock the current Auth row so a concurrent email change cannot race acceptance.
  SELECT lower(btrim(email)) INTO v_email FROM auth.users WHERE id=v_user
    AND email_confirmed_at IS NOT NULL FOR SHARE;
  IF v_email IS NULL OR v_email IS DISTINCT FROM v_row.email OR v_row.status='revoked'
      OR v_row.expires_at<=clock_timestamp()
      OR NOT EXISTS (SELECT FROM finance_app.members WHERE household_id=v_household
        AND user_id=v_row.created_by AND role='owner') THEN
    RAISE invalid_parameter_value USING MESSAGE='Invalid or expired invitation';
  END IF;
  IF v_row.status='accepted' THEN
    -- A replay acknowledges existing access only; it NEVER recreates a removed member.
    IF v_row.accepted_by IS DISTINCT FROM v_user OR NOT EXISTS (SELECT FROM finance_app.members
        WHERE household_id=v_household AND user_id=v_user) THEN
      RAISE invalid_parameter_value USING MESSAGE='Invalid or expired invitation';
    END IF;
    RETURN finance_app.household_json(v_household,v_user)||jsonb_build_object('status','accepted');
  END IF;
  -- Existing membership is retained verbatim; an invitation cannot upgrade its role.
  INSERT INTO finance_app.members(household_id,user_id,role) VALUES(v_household,v_user,v_row.role)
    ON CONFLICT(household_id,user_id) DO NOTHING;
  UPDATE finance_app.invitations SET status='accepted',accepted_at=clock_timestamp(),accepted_by=v_user WHERE id=v_row.id;
  UPDATE finance_app.mail_jobs SET status='cancelled',lease_id=NULL,lease_until=NULL
    WHERE invite_id=v_row.id AND status IN ('pending','leased');
  RETURN finance_app.household_json(v_household,v_user)||jsonb_build_object('status','accepted');
END
$f$;
CREATE FUNCTION public.finance_revoke_invite(p_household_id uuid,p_invite_id uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_user uuid:=finance_app.verified_user(); v_status text;
BEGIN
  PERFORM finance_app.lock_household(p_household_id);
  PERFORM finance_app.require_role(p_household_id,v_user,ARRAY['owner']);
  SELECT status INTO v_status FROM finance_app.invitations WHERE id=p_invite_id AND household_id=p_household_id FOR UPDATE;
  IF NOT FOUND THEN RAISE invalid_parameter_value USING MESSAGE='Invitation not found'; END IF;
  IF v_status='pending' THEN
    UPDATE finance_app.invitations SET status='revoked',revoked_at=clock_timestamp() WHERE id=p_invite_id;
    UPDATE finance_app.mail_jobs SET status='cancelled',lease_id=NULL,lease_until=NULL
      WHERE invite_id=p_invite_id AND status IN ('pending','leased');
  END IF;
  -- An accepted invitation is immutable; remove_member is the explicit access revocation.
  RETURN finance_app.invite_json(p_invite_id);
END
$f$;

CREATE FUNCTION public.finance_read_state(p_household_id uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_user uuid:=finance_app.verified_user(); v_result jsonb;
BEGIN
  PERFORM finance_app.require_role(p_household_id,v_user,ARRAY['owner','editor','viewer']);
  SELECT jsonb_build_array(to_jsonb(s)) INTO v_result FROM finance_app.family_state s WHERE household_id=p_household_id;
  RETURN coalesce(v_result,'[]'::jsonb);
END
$f$;
CREATE FUNCTION public.finance_state_cas(p_household_id uuid,p_expected_revision bigint,p_data jsonb,p_request_id uuid)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_user uuid:=finance_app.verified_user(); v_row finance_app.family_state%ROWTYPE; v_status text;
BEGIN
  IF p_household_id IS NULL OR p_expected_revision IS NULL OR p_expected_revision<0
      OR p_request_id IS NULL OR p_data IS NULL OR jsonb_typeof(p_data)<>'object' THEN
    RAISE invalid_parameter_value USING MESSAGE='Invalid CAS request';
  END IF;
  IF octet_length(p_data::text)>1000000 THEN
    RAISE invalid_parameter_value USING MESSAGE='Financial document exceeds size limit';
  END IF;
  -- Hide foreign-row existence under the legacy CAS not_found contract.
  IF NOT EXISTS (SELECT FROM finance_app.members WHERE household_id=p_household_id AND user_id=v_user) THEN
    RETURN jsonb_build_object('status','not_found','revision',NULL,'protocol',NULL,'data',NULL,'request_id',NULL);
  END IF;
  PERFORM finance_app.lock_household(p_household_id);
  PERFORM finance_app.require_role(p_household_id,v_user,ARRAY['owner','editor']);
  SELECT * INTO v_row FROM finance_app.family_state WHERE household_id=p_household_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('status','not_found','revision',NULL,'protocol',NULL,'data',NULL,'request_id',NULL);
  END IF;
  IF v_row.last_request_id=p_request_id THEN
    v_status:=CASE WHEN v_row.data=p_data THEN 'written' ELSE 'conflict' END;
  ELSIF v_row.sync_revision<>p_expected_revision THEN v_status:='conflict';
  ELSE
    IF p_data ?| ARRAY['plan','pro','entitlements','entitlement']
        OR coalesce(p_data->'settings','{}'::jsonb) ?| ARRAY['plan','pro','entitlements','entitlement'] THEN
      RAISE insufficient_privilege USING MESSAGE='Plan is server controlled';
    END IF;
    UPDATE finance_app.family_state SET data=p_data,sync_revision=sync_revision+1,last_request_id=p_request_id,
      updated_at=clock_timestamp(),updated_by=v_user WHERE household_id=p_household_id RETURNING * INTO v_row;
    v_status:='written';
  END IF;
  RETURN jsonb_build_object('status',v_status,'revision',v_row.sync_revision,'protocol',v_row.sync_protocol,
    'data',v_row.data,'request_id',v_row.last_request_id);
END
$f$;

-- Fixed-scope mail worker APIs. They cannot read or write financial state/membership.
CREATE FUNCTION public.finance_claim_mail_jobs(p_worker_id uuid,p_limit integer DEFAULT 10) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_result jsonb;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE insufficient_privilege USING MESSAGE='Mail worker service role required';
  END IF;
  IF p_worker_id IS NULL OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 25 THEN
    RAISE invalid_parameter_value USING MESSAGE='Invalid worker claim';
  END IF;
  -- Only update job rows: acceptance/revocation use household -> invitation -> job lock order.
  UPDATE finance_app.mail_jobs j SET status='cancelled',lease_id=NULL,lease_until=NULL
    FROM finance_app.invitations i WHERE i.id=j.invite_id AND j.status IN ('pending','leased')
      AND (i.status<>'pending' OR i.expires_at<=clock_timestamp()
        OR NOT EXISTS (SELECT FROM finance_app.members m WHERE m.household_id=i.household_id AND m.user_id=i.created_by AND m.role='owner'));
  UPDATE finance_app.mail_jobs SET status='failed',lease_id=NULL,lease_until=NULL,error_code='attempts_exhausted'
    WHERE status IN ('pending','leased') AND attempts>=5 AND (lease_until IS NULL OR lease_until<=clock_timestamp());
  WITH candidates AS (
    SELECT j.id FROM finance_app.mail_jobs j JOIN finance_app.invitations i ON i.id=j.invite_id
    WHERE ((j.status='pending' AND j.available_at<=clock_timestamp())
      OR (j.status='leased' AND j.lease_until<=clock_timestamp()))
      AND j.attempts<5 AND i.status='pending' AND i.expires_at>clock_timestamp()
      AND EXISTS (SELECT FROM finance_app.members m WHERE m.household_id=i.household_id AND m.user_id=i.created_by AND m.role='owner')
    ORDER BY j.available_at,j.id FOR UPDATE OF j SKIP LOCKED LIMIT p_limit
  ), claimed AS (
    UPDATE finance_app.mail_jobs j SET status='leased',worker_id=p_worker_id,lease_id=gen_random_uuid(),
      lease_until=clock_timestamp()+interval '120 seconds',attempts=attempts+1
    FROM candidates c WHERE j.id=c.id RETURNING j.*
  )
  SELECT coalesce(jsonb_agg(jsonb_build_object('id',c.id,'job_id',c.id,'lease_id',c.lease_id,
    'lease_until',c.lease_until,'invite_id',i.id,'request_id',i.request_id,'household_id',i.household_id,
    'email',i.email,'role',i.role,'created_by',i.created_by,'token_hash',i.token_hash,
    'household_name',h.name,'expires_at',i.expires_at,'attempt',c.attempts)),'[]'::jsonb)
    INTO v_result FROM claimed c JOIN finance_app.invitations i ON i.id=c.invite_id
    JOIN finance_app.households h ON h.id=i.household_id;
  RETURN v_result;
END
$f$;
CREATE FUNCTION public.finance_finish_mail_job(p_job_id uuid,p_lease_id uuid,p_sent boolean,p_error_code text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,finance_app AS $f$
DECLARE v_row finance_app.mail_jobs%ROWTYPE; v_status text;
BEGIN
  IF auth.role() IS DISTINCT FROM 'service_role' THEN
    RAISE insufficient_privilege USING MESSAGE='Mail worker service role required';
  END IF;
  IF p_job_id IS NULL OR p_lease_id IS NULL OR p_sent IS NULL
      OR (p_error_code IS NOT NULL AND p_error_code !~ '^[a-z0-9_]{1,40}$') THEN
    RAISE invalid_parameter_value USING MESSAGE='Invalid worker completion';
  END IF;
  SELECT * INTO v_row FROM finance_app.mail_jobs WHERE id=p_job_id FOR UPDATE;
  IF NOT FOUND OR v_row.status<>'leased' OR v_row.lease_id IS DISTINCT FROM p_lease_id
      OR v_row.lease_until<=clock_timestamp() THEN RETURN jsonb_build_object('status','stale'); END IF;
  IF NOT EXISTS (SELECT FROM finance_app.invitations i WHERE i.id=v_row.invite_id
      AND i.status='pending' AND i.expires_at>clock_timestamp()
      AND EXISTS (SELECT FROM finance_app.members m WHERE m.household_id=i.household_id AND m.user_id=i.created_by AND m.role='owner')) THEN
    UPDATE finance_app.mail_jobs SET status='cancelled',lease_id=NULL,lease_until=NULL WHERE id=p_job_id;
    RETURN jsonb_build_object('status','stale');
  END IF;
  v_status:=CASE WHEN p_sent THEN 'sent' WHEN v_row.attempts>=5 THEN 'failed' ELSE 'pending' END;
  UPDATE finance_app.mail_jobs SET status=v_status,lease_id=NULL,lease_until=NULL,
    sent_at=CASE WHEN p_sent THEN clock_timestamp() ELSE NULL END,
    available_at=clock_timestamp()+make_interval(secs=>least(3600,60*(2^v_row.attempts)::integer)),
    error_code=CASE WHEN p_sent THEN NULL ELSE coalesce(p_error_code,'delivery_failed') END WHERE id=p_job_id;
  RETURN jsonb_build_object('status',CASE WHEN v_status='pending' THEN 'retry' ELSE v_status END);
END
$f$;

-- All public functions are explicitly granted. No default PUBLIC execution survives.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA finance_app FROM PUBLIC, anon, authenticated, service_role;
DO $grants$
DECLARE v_fn regprocedure;
BEGIN
  FOR v_fn IN SELECT oid::regprocedure FROM pg_proc WHERE pronamespace='public'::regnamespace
      AND proname LIKE 'finance\_%' ESCAPE '\' LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC, anon, authenticated, service_role',v_fn);
    IF v_fn::text LIKE 'finance_claim_mail_jobs(%' OR v_fn::text LIKE 'finance_finish_mail_job(%'
        OR v_fn::text LIKE 'public.finance_claim_mail_jobs(%' OR v_fn::text LIKE 'public.finance_finish_mail_job(%' THEN
      EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role',v_fn);
    ELSE
      EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO authenticated',v_fn);
    END IF;
  END LOOP;
END
$grants$;
COMMIT;

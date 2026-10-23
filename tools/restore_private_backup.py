#!/usr/bin/env python3
"""Restore four private application tables into a disposable offline PostgreSQL.

Never connects to Supabase. Auth users contain UUIDs only; this is not a full
Supabase/Auth/platform restore. Original files are read only. stdout is a safe
receipt; the separately requested 0600 output contains private row data.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid

import verify_private_backup as verify

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "postgres:16-alpine@sha256:f4610795587492cd4fb887c2dc3de301b813278bb6f616992061141b5f15ac36"
SCHEMA = {
    "households": {"id": "uuid", "name": "text", "created_at": "timestamp"},
    "household_members": {"household_id": "uuid", "user_id": "uuid", "role": "text", "created_at": "timestamp"},
    "family_state": {"household_id": "uuid", "data": "json", "updated_at": "timestamp", "updated_by": "uuid?"},
    "family_chore_deliveries": {
        "household_id": "uuid", "chore_id": "text", "due_date": "date", "chat_id": "text",
        "status": "text", "attempts": "int", "last_attempt_at": "timestamp?", "sent_at": "timestamp?",
        "telegram_message_id": "bigint?", "last_error": "text?", "created_at": "timestamp"},
}

BOOTSTRAP_SQL = r"""
CREATE ROLE anon;
CREATE ROLE authenticated;
CREATE ROLE service_role BYPASSRLS;
CREATE SCHEMA auth;
GRANT USAGE ON SCHEMA public,auth TO anon,authenticated,service_role;
CREATE TABLE auth.users(id uuid PRIMARY KEY);
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
  $$ SELECT nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
CREATE FUNCTION auth.role() RETURNS text LANGUAGE sql STABLE AS
  $$ SELECT nullif(current_setting('request.jwt.claim.role',true),'') $$;
CREATE TABLE public.households(
  id uuid PRIMARY KEY, name text NOT NULL, created_at timestamptz NOT NULL);
CREATE TABLE public.household_members(
  household_id uuid NOT NULL REFERENCES public.households(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role text NOT NULL, created_at timestamptz NOT NULL,
  PRIMARY KEY(household_id,user_id));
CREATE TABLE public.family_state(
  household_id uuid PRIMARY KEY REFERENCES public.households(id) ON DELETE CASCADE,
  data jsonb NOT NULL, updated_at timestamptz NOT NULL,
  updated_by uuid REFERENCES auth.users(id));
-- Confirmed types/PK only. The unreviewed delivery status CHECK/defaults are
-- intentionally not invented; no Telegram delivery takes place in this clone.
CREATE TABLE public.family_chore_deliveries(
  household_id uuid NOT NULL, chore_id text NOT NULL, due_date date NOT NULL,
  chat_id text NOT NULL, status text NOT NULL, attempts integer NOT NULL,
  last_attempt_at timestamptz, sent_at timestamptz, telegram_message_id bigint,
  last_error text, created_at timestamptz NOT NULL,
  PRIMARY KEY(household_id,chore_id,due_date,chat_id));
CREATE FUNCTION public.is_household_member(p_household_id uuid,p_user_id uuid)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=public AS $$
  SELECT EXISTS (SELECT 1 FROM public.household_members hm
    WHERE hm.household_id=p_household_id AND hm.user_id=p_user_id);
$$;
ALTER TABLE public.households ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.household_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.family_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.family_chore_deliveries ENABLE ROW LEVEL SECURITY;
CREATE POLICY "members can insert family state" ON public.family_state
  FOR INSERT TO authenticated WITH CHECK(public.is_household_member(household_id,auth.uid()));
CREATE POLICY "members can read family state" ON public.family_state
  FOR SELECT TO authenticated USING(public.is_household_member(household_id,auth.uid()));
CREATE POLICY "members can update family state" ON public.family_state
  FOR UPDATE TO authenticated USING(public.is_household_member(household_id,auth.uid()))
  WITH CHECK(public.is_household_member(household_id,auth.uid()));
CREATE POLICY "members can view family members" ON public.household_members
  FOR SELECT TO authenticated USING(public.is_household_member(household_id,auth.uid()));
CREATE POLICY "members can view their households" ON public.households
  FOR SELECT TO authenticated USING(public.is_household_member(id,auth.uid()));
GRANT SELECT,INSERT,UPDATE,DELETE ON public.family_state,public.household_members,public.households TO authenticated;
GRANT TRUNCATE,TRIGGER ON public.family_state,public.household_members,public.households TO anon,authenticated;
GRANT SELECT ON public.family_state TO service_role;
GRANT SELECT,INSERT,UPDATE ON public.family_chore_deliveries TO service_role;
GRANT TRUNCATE,TRIGGER ON public.family_state,public.household_members,public.households,public.family_chore_deliveries TO service_role;
"""

INSERT_SQL = r"""
INSERT INTO auth.users(id)
  SELECT DISTINCT (m->>'user_id')::uuid FROM restore_payload p,
    jsonb_array_elements(p.value->'household_members') m
  UNION SELECT DISTINCT (s->>'updated_by')::uuid FROM restore_payload p,
    jsonb_array_elements(p.value->'family_state') s WHERE s->>'updated_by' IS NOT NULL;
INSERT INTO public.households SELECT r.* FROM restore_payload p,
  jsonb_populate_recordset(NULL::public.households,p.value->'households') r;
INSERT INTO public.household_members SELECT r.* FROM restore_payload p,
  jsonb_populate_recordset(NULL::public.household_members,p.value->'household_members') r;
INSERT INTO public.family_state SELECT r.* FROM restore_payload p,
  jsonb_populate_recordset(NULL::public.family_state,p.value->'family_state') r;
INSERT INTO public.family_chore_deliveries SELECT r.* FROM restore_payload p,
  jsonb_populate_recordset(NULL::public.family_chore_deliveries,p.value->'family_chore_deliveries') r;
"""

READBACK_SQL = r"""
SELECT jsonb_build_object(
 'family_state',COALESCE((SELECT jsonb_agg(to_jsonb(s) ORDER BY household_id) FROM public.family_state s),'[]'::jsonb),
 'households',COALESCE((SELECT jsonb_agg(to_jsonb(h) ORDER BY id) FROM public.households h),'[]'::jsonb),
 'household_members',COALESCE((SELECT jsonb_agg(to_jsonb(m) ORDER BY household_id,user_id) FROM public.household_members m),'[]'::jsonb),
 'family_chore_deliveries',COALESCE((SELECT jsonb_agg(to_jsonb(d) ORDER BY household_id,chore_id,due_date,chat_id) FROM public.family_chore_deliveries d),'[]'::jsonb)
)::text;
"""


class RestoreError(Exception):
    pass


def fail(code):
    raise RestoreError(code)


def validate_types(tables):
    for table, fields in SCHEMA.items():
        for row in tables[table]:
            if row.keys() != fields.keys():
                fail("unknown-or-missing-outer-table-columns")
            for column, kind in fields.items():
                value = row[column]
                if kind.endswith("?") and value is None:
                    continue
                kind = kind.rstrip("?")
                if kind == "uuid":
                    verify.uuid_value(value)
                elif kind == "text":
                    if not isinstance(value, str) or "\x00" in value:
                        fail("invalid-column-type")
                elif kind == "json":
                    if not isinstance(value, dict):
                        fail("invalid-column-type")
                elif kind in ("int", "bigint"):
                    limit = 2 ** (31 if kind == "int" else 63)
                    if not isinstance(value, Decimal) or value != value.to_integral_value() or not -limit <= value < limit:
                        fail("invalid-column-type")
                elif kind == "date":
                    if not verify.dated(value):
                        fail("invalid-column-type")
                elif kind == "timestamp":
                    try:
                        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                        if stamp.tzinfo is None:
                            fail("invalid-column-type")
                    except (ValueError, AttributeError, TypeError):
                        fail("invalid-column-type")


def load_backup(path):
    reader = verify.Reader(path)
    wrapper = reader.read(path)
    if not isinstance(wrapper, dict):
        fail("invalid-snapshot-format")
    project = wrapper.get("project_ref")
    household = verify.uuid_value(wrapper.get("configured_household"))
    if not isinstance(project, str) or not re.fullmatch(r"[a-z0-9]{20}", project):
        fail("invalid-project-ref")
    if type(wrapper.get("configured_household_count")) is not Decimal or wrapper["configured_household_count"] != Decimal(1):
        fail("invalid-household-coverage")
    database_timezone = wrapper.get("database_timezone")
    if not isinstance(database_timezone, str) or not re.fullmatch(r"[A-Za-z0-9_+./:-]{1,100}", database_timezone):
        fail("missing-or-invalid-database-timezone")
    tables, _, health = verify.snapshot(wrapper, project, household)
    validate_types(tables)
    return wrapper, tables, reader.digests[0], health


def copy_text(raw):
    """One COPY text field; data cannot terminate COPY or become SQL syntax."""
    return raw.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def docker(*arguments, input_text=None, check=True):
    env = os.environ.copy()
    for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        env.pop(key, None)
    try:
        result = subprocess.run(["docker", "--host=unix:///var/run/docker.sock", *arguments],
            input=input_text, text=True, capture_output=True, env=env, timeout=45)
    except (OSError, subprocess.TimeoutExpired):
        fail("local-docker-command-failed")
    if check and result.returncode:
        # PostgreSQL stderr can include a failing row, COPY bytes or SQL text.
        # Do not print, log or attach it to an exception.
        fail("local-docker-or-postgresql-failed")
    return result


class Clone:
    def __init__(self, database_timezone):
        self.name = "marichevy-private-restore-" + uuid.uuid4().hex[:16]
        self.timezone = database_timezone
        self.started = False

    def __enter__(self):
        docker("image", "inspect", IMAGE)
        self.started = True
        try:
            docker("run", "--detach", "--rm", "--pull=never", "--network=none",
                   "--log-driver=none", "--memory=512m", "--cpus=1", "--pids-limit=128",
                   "--name", self.name, "--tmpfs", "/var/lib/postgresql/data:rw,nosuid,noexec,size=256m",
                   "-e", "POSTGRES_HOST_AUTH_METHOD=trust", IMAGE,
                   "postgres", "-c", "log_min_error_statement=panic", "-c", "log_error_verbosity=terse")
            for _ in range(100):
                result = docker("exec", self.name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", check=False)
                if result.returncode == 0:
                    break
                time.sleep(.1)
            else:
                fail("local-postgresql-not-ready")
            self.sql(BOOTSTRAP_SQL)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.started:
            result = docker("rm", "--force", self.name, check=False)
            if result.returncode:
                fail("private-container-cleanup-failed")
            self.started = False

    def sql(self, query, variables=()):
        arguments = ["exec", "-i", self.name, "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
                     "-v", "snapshot_timezone=" + self.timezone, "-U", "postgres", "-d", "postgres"]
        for name, value in variables:
            arguments.extend(("-v", name + "=" + value))
        # TimeZone is the only source selector in argv and is metadata, not row
        # data. psql's :'...' performs SQL-literal quoting in this fixed command.
        return docker(*arguments, input_text="SET TIME ZONE :'snapshot_timezone';\nSET DateStyle = 'ISO, YMD';\n" + query).stdout.strip()

    def import_snapshot(self, raw):
        query = "BEGIN; CREATE TEMP TABLE restore_payload(value jsonb) ON COMMIT DROP;\nCOPY restore_payload(value) FROM STDIN;\n"
        query += copy_text(raw) + "\n\\.\n" + INSERT_SQL + "\nCOMMIT;"
        self.sql(query)

    def verify_rls(self):
        own = self.sql("""
BEGIN;
DO $$ BEGIN
  PERFORM set_config('request.jwt.claim.sub',(SELECT user_id::text FROM public.household_members ORDER BY user_id LIMIT 1),true);
  PERFORM set_config('request.jwt.claim.role','authenticated',true);
END $$;
SET LOCAL ROLE authenticated;
SELECT count(*) FROM public.family_state;
ROLLBACK;
""")
        outsider = self.sql("""
BEGIN;
DO $$ DECLARE v_user uuid; BEGIN
  LOOP v_user:=gen_random_uuid(); EXIT WHEN NOT EXISTS(SELECT 1 FROM public.household_members WHERE user_id=v_user); END LOOP;
  PERFORM set_config('request.jwt.claim.sub',v_user::text,true);
  PERFORM set_config('request.jwt.claim.role','authenticated',true);
END $$;
SET LOCAL ROLE authenticated;
SELECT count(*) FROM public.family_state;
ROLLBACK;
""")
        if own != "1" or outsider != "0":
            fail("local-clone-rls-check-failed")

    def verify_cas_in_rolled_back_transaction(self):
        status = self.sql("""
BEGIN;
UPDATE public.family_state SET sync_protocol=2;
DO $$ BEGIN
  PERFORM set_config('request.jwt.claim.sub',(SELECT user_id::text FROM public.household_members ORDER BY user_id LIMIT 1),true);
  PERFORM set_config('request.jwt.claim.role','authenticated',true);
END $$;
SET LOCAL ROLE authenticated;
SELECT public.family_state_cas(household_id,sync_revision,data,gen_random_uuid())->>'status' FROM public.family_state;
ROLLBACK;
""")
        if status != "written":
            fail("local-clone-cas-check-failed")


def compare_rows(source, readback):
    return all(verify.equal(verify.indexed(source[table], keys), verify.indexed(readback[table], keys))
               for table, keys in verify.TABLE_KEYS.items())


def private_output(path):
    if not path.is_absolute() or ".." in path.parts or path.is_relative_to(ROOT):
        fail("private-output-must-be-outside-checkout")
    descriptor = None
    try:
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        for component in path.parent.parts[1:]:
            next_descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        info = os.fstat(descriptor)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            fail("output-folder-must-be-private-and-owned")
        try:
            os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return descriptor
        fail("output-already-exists")
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        fail("unsafe-or-unavailable-output-folder")
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        raise


def restore(backup, output, *, allow_private_input=False, rehearse_migrations=False):
    report = {"format": "marichevy-private-local-restore-receipt-v1", "outcome": "blocked",
              "network_used": False, "production_changed": False, "original_files_modified": False,
              "supabase_auth_restored": False, "supabase_platform_restored": False,
              "engine": "disposable-postgresql-16-app-table-clone", "issues": []}
    if not allow_private_input:
        report["issues"] = ["explicit-private-input-authorization-required"]
        return report
    output_directory_fd = None
    try:
        source_path, output_path = Path(backup).absolute(), Path(output).absolute()
        if ".." in source_path.parts or source_path.is_relative_to(ROOT):
            fail("private-input-must-be-outside-checkout")
        if source_path == output_path:
            fail("output-cannot-replace-source")
        output_directory_fd = private_output(output_path)
        wrapper, tables, source_digest, health = load_backup(source_path)
        with tempfile.TemporaryDirectory(prefix="marichevy-private-restore-") as temporary:
            os.chmod(temporary, 0o700)
            with Clone(wrapper["database_timezone"]) as clone:
                clone.import_snapshot(wrapper["snapshot_json"])
                raw = clone.sql(READBACK_SQL)
                restored = verify.parse(raw)
                if not compare_rows(tables, restored):
                    fail("restored-rows-differ")
                clone.verify_rls()
                report["four_table_roundtrip_verified"] = True
                report["foreign_keys_and_not_null_restored"] = True
                report["minimal_auth_user_stubs_only"] = True
                report["local_clone_rls_verified"] = True
                report["table_counts"] = {table: len(rows) for table, rows in tables.items()}
                if rehearse_migrations:
                    for filename in ("001_family_state_cas.sql", "002_restrict_table_capabilities.sql", "003_bound_membership_lookup.sql"):
                        clone.sql((ROOT / "server" / filename).read_text())
                    clone.verify_rls()
                    clone.verify_cas_in_rolled_back_transaction()
                    projected = clone.sql(READBACK_SQL.replace("to_jsonb(s)", "to_jsonb(s)-'sync_revision'-'sync_protocol'-'last_request_id'"))
                    if not compare_rows(tables, verify.parse(projected)):
                        fail("migration-rehearsal-changed-original-data")
                    report["migration_rehearsal_preserved_original_columns"] = True
                    report["migration_rehearsal_local_cas_verified"] = True
        # Container is destroyed before any private readback file is created.
        restored_wrapper = {"format": "marichevy-private-server-backup-v1",
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "project_ref": wrapper["project_ref"], "configured_household": wrapper["configured_household"],
            "configured_household_count": 1, "read_only": True,
            "database_timezone": wrapper["database_timezone"],
            "query_sha256": hashlib.sha256(READBACK_SQL.encode()).hexdigest(),
            "snapshot_json_sha256": hashlib.sha256(raw.encode()).hexdigest(), "snapshot_json": raw,
            "source_backup_sha256": source_digest, "restore_scope": "offline-four-app-tables-auth-id-stubs"}
        encoded = (json.dumps(restored_wrapper, ensure_ascii=True, indent=2) + "\n").encode()
        if len(encoded) > verify.MAX_FILE:
            fail("restored-output-size-limit")
        fd = os.open(output_path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=output_directory_fd)
        created_inode = os.fstat(fd).st_ino
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            try:
                if os.stat(output_path.name, dir_fd=output_directory_fd, follow_symlinks=False).st_ino == created_inode:
                    os.unlink(output_path.name, dir_fd=output_directory_fd)
            except OSError:
                pass
            raise
        os.fsync(output_directory_fd)
        report["outcome"] = "passed"
        report["readback_file_sha256"] = hashlib.sha256(encoded).hexdigest()
        report["source_file_sha256"] = source_digest
        report["source_unknown_delivery_checks_reproduced"] = False
        report["app_health_counts"] = health
        if any(health.get(key, 0) for key in ("invalid_cent_values", "invalid_period_values", "broken_known_links", "ambiguous_duplicate_ids")):
            report["outcome"] = "review_required"
            report["issues"] = ["existing-app-data-requires-review"]
    except (RestoreError, verify.InvalidBackup) as error:
        report["outcome"] = "failed"
        report["issues"] = [str(error)]
    except KeyboardInterrupt:
        report["outcome"] = "failed"
        report["issues"] = ["private-restore-interrupted"]
    except Exception:
        report["outcome"] = "failed"
        report["issues"] = ["local-restore-internal-error"]
    finally:
        if output_directory_fd is not None:
            os.close(output_directory_fd)
    return report


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message):
        self.exit(2, "private-restore-cli-arguments-invalid\n")


def main(argv=None):
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-private-input", action="store_true")
    parser.add_argument("--rehearse-migrations", action="store_true")
    args = parser.parse_args(argv)
    report = restore(args.backup, args.output, allow_private_input=args.allow_private_input,
                     rehearse_migrations=args.rehearse_migrations)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return {"passed": 0, "review_required": 2}.get(report["outcome"], 1)


if __name__ == "__main__":
    sys.exit(main())

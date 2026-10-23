#!/usr/bin/env python3
"""Inspect/bootstrap/test only the explicitly selected fictional Supabase project.

No configurable host, production fallback, token logging, or destructive reset.
The management token is supplied through a protected proxy binding. Project keys,
fictional passwords and user sessions remain in memory for this invocation.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid

ROOT = Path(__file__).resolve().parents[1]
PROJECT_REF = "iqpoxphtvtogjowruufe"
PROJECT_NAME = "marichevy-finance-staging"
MANAGEMENT = "https://api.supabase.com/v1/projects/" + PROJECT_REF
PROJECT_URL = "https://" + PROJECT_REF + ".supabase.co"
TOKEN_NAME = "STAGING_SUPABASE_MANAGEMENT_TOKEN"


class StagingError(RuntimeError):
    """Safe error messages contain no response bodies or credential values."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Transport:
    def __init__(self):
        self.opener = build_opener(NoRedirect())

    def request(self, method, url, headers=None, body=None):
        parsed = urlsplit(url)
        path = parsed.path
        management_path = "/v1/projects/" + PROJECT_REF
        valid_origin = (parsed.scheme == "https" and not parsed.fragment
                        and parsed.netloc in ("api.supabase.com", PROJECT_REF + ".supabase.co"))
        valid_path = (unquote(path) == path and "//" not in path
                      and not any(piece in (".", "..") for piece in path.split("/")))
        allowed = ((parsed.netloc == "api.supabase.com"
                    and (path == management_path or path.startswith(management_path + "/")))
                   or (parsed.netloc == PROJECT_REF + ".supabase.co"
                       and (path.startswith("/auth/v1/") or path.startswith("/rest/v1/"))))
        if not (valid_origin and valid_path and allowed):
            raise StagingError("Destination is outside the fixed staging boundary")
        # Do not follow redirects with authorization headers.
        data = None if body is None else json.dumps(body).encode()
        request = Request(url, data=data, method=method,
                          headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with self.opener.open(request, timeout=30) as response:
                status, raw = response.status, response.read()
        except HTTPError as error:
            status, raw = error.code, error.read()
        except (URLError, TimeoutError, OSError):
            raise StagingError("Staging request failed: check network policy, TLS and service health") from None
        try:
            result = json.loads(raw) if raw else None
        except (ValueError, UnicodeError):
            result = None
        return status, result


class Staging:
    def __init__(self, token, transport=None):
        if not token:
            raise StagingError("Missing protected environment binding: " + TOKEN_NAME)
        self.token = token
        self.transport = transport or Transport()
        self.identity_verified = False
        self.checks = []

    def management(self, method, suffix="", body=None):
        if suffix and not self.identity_verified:
            raise StagingError("Project identity must be verified before further operations")
        status, result = self.transport.request(method, MANAGEMENT + suffix,
            {"Authorization": "Bearer " + self.token}, body)
        allowed_statuses = (200, 201) if method == "POST" and suffix == "/database/query" else (200,)
        if status not in allowed_statuses:
            raise StagingError("Management API returned HTTP " + str(status))
        return result

    def verify_identity(self):
        self.identity_verified = False
        project = self.management("GET")
        if not isinstance(project, dict) or project.get("ref", project.get("id")) != PROJECT_REF \
                or project.get("name") != PROJECT_NAME:
            raise StagingError("Project ref/name mismatch: no further operation is allowed")
        if project.get("status") != "ACTIVE_HEALTHY":
            raise StagingError("Staging project is not ACTIVE_HEALTHY")
        self.identity_verified = True
        return {key: project.get(key) for key in ("ref", "name", "status", "region")}

    def query(self, sql, parameters=(), read_only=False):
        result = self.management("POST", "/database/query",
            {"query": sql, "parameters": list(parameters), "read_only": read_only})
        if not isinstance(result, list):
            raise StagingError("Management query returned an unexpected result shape")
        return result

    def inspect(self):
        identity = self.verify_identity()
        inventory = self.query("""SELECT
          (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')) AS public_relations,
          (SELECT count(*) FROM auth.users) AS auth_users,
          to_regnamespace('marichevy_staging') IS NOT NULL AS fixture_exists;""", read_only=True)
        if len(inventory) != 1:
            raise StagingError("Unexpected inventory result")
        return {"project": identity, "inventory": inventory[0]}

    def keys(self):
        keys = self.management("GET", "/api-keys?reveal=true")
        if not isinstance(keys, list):
            raise StagingError("Unexpected staging key metadata")
        def choose(kind, legacy):
            modern = [item.get("api_key") for item in keys if item.get("type") == kind and item.get("api_key")]
            old = [item.get("api_key") for item in keys if item.get("name") == legacy and item.get("api_key")]
            if modern or old:
                return (modern or old)[0]
            raise StagingError("Staging project has no usable " + kind + " key; no keys were changed")
        return choose("publishable", "anon"), choose("secret", "service_role")

    def check(self, label, condition):
        if not condition:
            raise StagingError("Hosted assertion failed: " + label)
        self.checks.append(label)

    def browser(self):
        """Resume only known fictional fixture accounts; never reset real users."""
        inspected = self.inspect()
        inventory = inspected['inventory']
        if inventory != {'public_relations': 2, 'auth_users': 3, 'fixture_exists': True}:
            raise StagingError('Browser checks require exactly the existing two-family/three-user fixture')
        marker = self.query('SELECT project_ref,project_name,fixture_version FROM marichevy_staging.fixture_registry', read_only=True)
        if marker != [{'project_ref': PROJECT_REF, 'project_name': PROJECT_NAME, 'fixture_version': 1}]:
            raise StagingError('Staging fixture marker does not match the expected installation')
        members = self.query("""SELECT m.household_id,m.user_id,u.email,
            u.raw_app_meta_data->>'marichevy_staging_run' AS run_id
            FROM public.staging_membership m JOIN auth.users u ON u.id=m.user_id
            ORDER BY m.household_id,m.user_id""", read_only=True)
        if len(members) != 3 or len({member.get('run_id') for member in members}) != 1:
            raise StagingError('Unknown fixture membership; no account password will be changed')
        for member in members:
            run = member.get('run_id') or ''
            email = member.get('email') or ''
            if not re.fullmatch('[0-9a-f]{32}', run) or not re.fullmatch('stage-' + run + '-[012]@example[.]invalid', email):
                raise StagingError('Refusing to change a non-fixture authentication account')
        groups = {}
        for member in members:
            groups.setdefault(member['household_id'], []).append(member)
        if sorted(len(group) for group in groups.values()) != [1, 2]:
            raise StagingError('Expected two fictional households with two/one members')
        own_household, own = next((house, group) for house, group in groups.items() if len(group) == 2)
        outsider = next(group[0] for group in groups.values() if len(group) == 1)
        public_key, admin_key = self.keys()
        headers = {'apikey': admin_key}
        if not admin_key.startswith('sb_secret_'):
            headers['Authorization'] = 'Bearer ' + admin_key
        credentials = []
        for member in [*own, outsider]:
            password = secrets.token_urlsafe(36)
            status, result = self.transport.request('PUT', PROJECT_URL + '/auth/v1/admin/users/' + member['user_id'],
                headers, {'password': password})
            self.check('fixture-only password renewed', status == 200 and isinstance(result, dict)
                       and result.get('id') == member['user_id'])
            credentials.append({'email': member['email'], 'password': password})
        from staging_browser import BrowserCheckError, verify_browser_flow
        try:
            browser_result = verify_browser_flow(self.transport, public_key, own_household, credentials)
        except BrowserCheckError as error:
            self.checks.extend(error.checks_completed)
            self.browser_diagnostics = error.diagnostics
            raise StagingError(str(error)) from None
        except ValueError:
            raise StagingError('Staging client sanitization failed; no browser check was accepted') from None
        self.checks.extend(browser_result['checks'])
        return {**inspected, 'outcome': 'passed', 'checks': self.checks,
                'fixture_only': True, 'production_tested': False,
                'browser': browser_result,
                'client_sha256': hashlib.sha256((ROOT / 'index.html').read_bytes()).hexdigest(),
                'network_path': 'real verified HTTPS forwarded through Playwright route bridge; native CORS untested'}

    def run(self):
        inspected = self.inspect()
        inventory = inspected["inventory"]
        if inventory.get("public_relations") != 0 or inventory.get("auth_users") != 0 or inventory.get("fixture_exists"):
            raise StagingError("Run requires a fresh empty staging project; existing work will not be reset")
        fixture = (ROOT / "server/staging_fixture.sql").read_text()
        self.query("BEGIN; SET LOCAL marichevy.staging_project_ref = '" + PROJECT_REF + "';\n" + fixture + "\nCOMMIT;")
        migration = (ROOT / "server/001_family_state_cas.sql").read_text()
        self.query(migration)
        public_key, admin_key = self.keys()
        auth_headers = {"apikey": admin_key}
        # A legacy admin JWT also uses Authorization. Modern secret keys belong
        # in apikey; they are not user JWTs and must never authorize RLS tests.
        if not admin_key.startswith("sb_secret_"):
            auth_headers["Authorization"] = "Bearer " + admin_key
        run_id = uuid.uuid4().hex
        users, sessions = [], []
        for index in range(3):
            password = secrets.token_urlsafe(36)
            email = f"stage-{run_id}-{index}@example.invalid"
            status, user = self.transport.request("POST", PROJECT_URL + "/auth/v1/admin/users", auth_headers,
                {"email": email, "password": password, "email_confirm": True,
                 "app_metadata": {"marichevy_staging_run": run_id}})
            self.check("fictional auth user " + str(index + 1), status in (200, 201) and isinstance(user, dict) and bool(user.get("id")))
            users.append(user["id"])
            status, session = self.transport.request("POST", PROJECT_URL + "/auth/v1/token?grant_type=password",
                {"apikey": public_key}, {"email": email, "password": password})
            self.check("real password session " + str(index + 1), status == 200 and isinstance(session, dict) and bool(session.get("access_token")))
            sessions.append(session["access_token"])
        houses = [str(uuid.uuid4()), str(uuid.uuid4())]
        data = {"entries": [], "goals": [], "birthdays": [], "boardItems": [], "chores": [],
                "installments": [], "settings": {}, "futureCollection": [{"id": "opaque", "keep": [1, True]}]}
        for house, user_id in zip([houses[0], houses[0], houses[1]], users):
            self.query("INSERT INTO public.staging_membership(household_id,user_id) VALUES ($1::uuid,$2::uuid)", [house, user_id])
        for house in houses:
            self.query("INSERT INTO public.family_state(household_id,data) VALUES ($1::uuid,$2::jsonb)", [house, json.dumps(data)])
        # Explicitly request schema-cache refresh, then wait only for that change.
        self.query("NOTIFY pgrst, 'reload schema';")
        def api(method, path, who=0, body=None, extra=None):
            headers = {"apikey": public_key, **(extra or {})}
            if who is not None:
                headers["Authorization"] = "Bearer " + sessions[who]
            return self.transport.request(method, PROJECT_URL + path, headers, body)
        def read(house=houses[0], who=0):
            return api("GET", "/rest/v1/family_state?household_id=eq." + house + "&select=*", who)
        for _ in range(15):
            status, rows = read()
            if status == 200 and isinstance(rows, list) and len(rows) == 1:
                break
            if status not in (404, 503):
                raise StagingError("Staging table read failed: HTTP " + str(status))
            time.sleep(1)
        self.check("own household visible", status == 200 and len(rows) == 1 and rows[0]["data"] == data)
        self.check("second member sees same household", read(who=1)[1] == rows)
        self.check("other family cannot read", read(who=2) == (200, []))
        self.check("own family cannot read second family", read(houses[1]) == (200, []))
        self.check("anon cannot read family table", read(who=None)[0] in (401, 403))
        def cas(snapshot, revision, who=0, request_id=None, house=houses[0]):
            return api("POST", "/rest/v1/rpc/family_state_cas", who,
                {"p_household_id": house, "p_expected_revision": revision,
                 "p_data": snapshot, "p_request_id": request_id or str(uuid.uuid4())})
        status, response = cas(data, 0)
        self.check("protocol one refuses CAS", status == 200 and response.get("status") == "upgrade_required")
        self.query("UPDATE public.family_state SET sync_protocol=2 WHERE household_id IN ($1::uuid,$2::uuid)", houses)
        a, b = deepcopy(data), deepcopy(data)
        for snapshot, name, amount in [(a, "a", 1250.50), (b, "b", 3000)]:
            snapshot["entries"] = [{"id": "fictional-" + name, "type": "expense", "amount": amount,
                "date": "2026-10-23", "category": "Продукты", "who": "Общее"}]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(cas, a, 1, 0), pool.submit(cas, b, 1, 1)]
            answers = [future.result() for future in futures]
        self.check("real concurrent CAS has one winner", all(code == 200 for code, _ in answers)
                   and sorted(answer.get("status") for _, answer in answers) == ["conflict", "written"])
        conflict = next(answer for _, answer in answers if answer["status"] == "conflict")
        merged = deepcopy(conflict["data"])
        merged["entries"] = a["entries"] + b["entries"]
        receipt = str(uuid.uuid4())
        status, ack = cas(merged, conflict["revision"], request_id=receipt)
        self.check("conflict retry preserves both additions", status == 200 and ack.get("status") == "written" and ack.get("data") == merged)
        self.check("retry receipt is idempotent", cas(merged, conflict["revision"], request_id=receipt) == (200, ack))
        self.check("server revision advances exactly twice", ack["revision"] == 3)
        status, row = read()
        self.check("server owns update identity", row[0]["updated_by"] == users[0])
        self.check("both members see final snapshot", read(who=1)[1] == row)
        for method, path, payload in [
            ("PATCH", "/rest/v1/family_state?household_id=eq." + houses[0], {"data": {}}),
            ("PATCH", "/rest/v1/family_state?household_id=eq." + houses[0], {"sync_protocol": 1}),
            ("DELETE", "/rest/v1/family_state?household_id=eq." + houses[0], None),
            ("POST", "/rest/v1/family_state?on_conflict=household_id", {"household_id": houses[0], "data": {}}),
        ]:
            status, _ = api(method, path, body=payload, extra={"Prefer": "resolution=merge-duplicates,return=representation"})
            self.check("legacy " + method + " rejected: " + ("protocol" if payload == {"sync_protocol": 1} else "data"), status == 409)
        for outsider in [2, None]:
            status, result = cas({}, ack["revision"], who=outsider)
            self.check("foreign/anon CAS denied " + str(outsider),
                       (outsider == 2 and status == 200 and result.get("status") == "not_found")
                       or (outsider is None and status in (401, 403)))
        for method, payload in [("PATCH", {"data": {"forbidden": True}}), ("DELETE", None)]:
            status, result = api(method, "/rest/v1/family_state?household_id=eq." + houses[0],
                who=2, body=payload, extra={"Prefer": "return=representation"})
            self.check("foreign direct " + method + " cannot change family",
                       (status == 200 and result == []) or status in (401, 403))
        status, _ = api("POST", "/rest/v1/family_state?on_conflict=household_id", who=2,
            body={"household_id": houses[0], "data": {"forbidden": True}},
            extra={"Prefer": "resolution=merge-duplicates,return=representation"})
        self.check("foreign upsert denied", status in (401, 403, 409))
        status, _ = api("POST", "/rest/v1/staging_membership", who=2,
            body={"household_id": houses[0], "user_id": users[2]})
        self.check("outsider cannot add membership", status in (401, 403))
        self.check("denied writes changed no history", read()[1] == row)
        # Recover the exact synthetic JSON in an unexposed table. This is a fixture
        # restore check, never a claim that the real family's backup was verified.
        self.query("CREATE TABLE marichevy_staging.restore_check(data jsonb NOT NULL)")
        self.query("INSERT INTO marichevy_staging.restore_check(data) VALUES ($1::jsonb)", [json.dumps(merged)])
        restored = self.query("SELECT data FROM marichevy_staging.restore_check", read_only=True)
        self.check("synthetic server backup roundtrip", len(restored) == 1 and restored[0]["data"] == merged)
        before = read()[1][0]
        self.query("UPDATE public.family_state SET sync_protocol=1 WHERE household_id=$1::uuid AND sync_revision=$2::bigint",
                   [houses[0], before["sync_revision"]])
        rolled = read()[1][0]
        self.check("protocol rollback preserves JSON", rolled["data"] == before["data"] and rolled["sync_revision"] == before["sync_revision"] + 1)
        self.check("CAS disabled after rollback", cas(merged, rolled["sync_revision"])[1].get("status") == "upgrade_required")
        self.query("UPDATE public.family_state SET sync_protocol=2 WHERE household_id=$1::uuid AND sync_revision=$2::bigint",
                   [houses[0], rolled["sync_revision"]])
        self.check("reactivation preserves JSON", read()[1][0]["data"] == merged)
        return {**inspected, "outcome": "passed", "checks": self.checks,
                "households": houses, "fictional_user_ids": users,
                "fixture_only": True, "production_tested": False,
                "cas_sql_sha256": hashlib.sha256(migration.encode()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inspect", "run", "browser"])
    parser.add_argument("--report", type=Path, default=Path("/workspace/artifacts/supabase-staging-report.json"))
    args = parser.parse_args()
    staging = None
    observed_at = datetime.now(timezone.utc).isoformat()
    try:
        staging = Staging(os.environ.get(TOKEN_NAME))
        report = getattr(staging, args.command)()
        report["observed_at"] = observed_at
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print("Staging " + args.command + " completed; safe report: " + str(args.report))
        return 0
    except StagingError as error:
        report = {"observed_at": observed_at, "project_ref": PROJECT_REF,
                  "command": args.command, "outcome": "blocked" if staging is None else "failed",
                  "checks_completed": [] if staging is None else staging.checks,
                  "safe_error": str(error), "production_tested": False}
        if staging is not None and hasattr(staging, 'browser_diagnostics'):
            report['browser_diagnostics'] = staging.browser_diagnostics
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

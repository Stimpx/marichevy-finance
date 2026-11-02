#!/usr/bin/env python3
"""Real, disposable local Auth + PostgREST + SMTP + public-client acceptance.

No provider response is mocked. Containers use an isolated internal bridge;
browser contexts, generated credentials, invitation links and mail stay in RAM.
The JSON report contains source hashes, assertion labels and coverage limits.
This is local Chromium evidence, not hosted Supabase or physical Safari evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import secrets
import sys
import time
from urllib.parse import parse_qs, urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from accounts_stack_runtime import LocalAccountsStack
sys.path.insert(0, str(ROOT))
from server.account_gateway import MailWorker, invite_token as derive_invite_token

SOURCE_PATHS = (
    "server/004_public_accounts.sql", "server/account_gateway.py",
    "tools/check_accounts_stack.py", "tools/accounts_stack_runtime.py",
    "tools/build_public_client.py", "public/index.html", "public/accounts.js",
    "public/accounts.css", "public/ledger.js", "public/ledger-template.html",
)
LIMITS = [
    "Disposable local GoTrue/PostgREST/PostgreSQL; no hosted project contacted.",
    "SMTP acceptance is observed at an isolated in-memory sink; external delivery is not tested.",
    "Chromium automation does not establish physical iPhone/Safari behavior.",
    "Provider signup, SMTP, redirect allowlists and abuse controls must also be configured on the hosted project.",
    "No payments or PRO activation is implemented or exercised.",
]


class CheckFailed(RuntimeError):
    pass


class Acceptance:
    def __init__(self, stack, *, backend_only=False):
        self.stack, self.backend_only = stack, backend_only
        self.phase = "initialization"
        self.checks = []
        self.browser_errors = 0
        self.external_requests = 0
        self.response_counts = {}
        self.ui_state_counts = {}
        self.accounts = {}

    def check(self, label, condition=True):
        if not condition:
            raise CheckFailed(label)
        self.checks.append(label)

    def api(self, path, body, token=None, expected=200):
        status, result = self.stack.call(path, body, token=token)
        if status != expected:
            raise CheckFailed(f"gateway_status_{status}_expected_{expected}")
        return result

    def rpc(self, name, body=None, token=None, expected=200):
        return self.api("/api/rpc/finance_" + name, body or {}, token, expected)

    def signup_api(self, label):
        email = "local-" + uuid.uuid4().hex + "@example.invalid"
        password = secrets.token_urlsafe(24)
        start = len(self.stack.messages)
        reply = self.api("/api/auth/signup", {"email": email, "password": password})
        self.check("signup_neutral_" + label, "session" not in reply and "message" in reply)
        message = self.stack.wait_message(email, since=start)
        account = {"email": email, "password": password,
                   "confirmation": self.stack.take_link(message, "signup")}
        self.accounts[label] = account
        return account

    def session(self, page):
        return page.evaluate("""() => {
          for(const key of Object.keys(localStorage)) {
            if(!key.startsWith('finance.auth.v1:'))continue;
            try {const value=JSON.parse(localStorage.getItem(key));
              if(value?.access_token && value?.user?.id)return value;}catch(_){}
          }
          return null;
        }""")

    def wait_js(self, page, expression, timeout=20):
        # Playwright wait_for_function compiles strings with page-side eval,
        # which the delivered strict CSP correctly forbids. CDP evaluation
        # observes state without relaxing or replacing the application's CSP.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if page.evaluate(expression):
                return
            time.sleep(.05)
        raise CheckFailed("browser_state_wait_expired")

    def remember(self, label, page):
        session = self.session(page)
        if not session or not session.get("user", {}).get("email_confirmed_at"):
            raise CheckFailed("verified_browser_session_required")
        self.accounts[label]["token"] = session["access_token"]
        self.accounts[label]["uid"] = session["user"]["id"]
        return session["access_token"]

    def confirm_browser(self, label, page):
        account = self.accounts[label]
        page.goto(account["confirmation"], wait_until="domcontentloaded")
        page.wait_for_selector("#family-name", timeout=20000)
        self.remember(label, page)
        self.check("real_confirmation_redirect_clean_" + label,
                   urlsplit(page.url).fragment == "" and urlsplit(page.url).query == "")

    def run_browser(self):
        from playwright.sync_api import sync_playwright

        self.phase = "browser_launch"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
            contexts = []
            try:
                def page_for():
                    context = browser.new_context()
                    contexts.append(context)
                    page = context.new_page()
                    page.set_default_timeout(15000)
                    page.on("pageerror", lambda _error: setattr(self, "browser_errors", self.browser_errors + 1))
                    def response_seen(response):
                        path = urlsplit(response.url).path
                        if path.startswith('/api/'):
                            key = path + ':' + str(response.status)
                            self.response_counts[key] = self.response_counts.get(key, 0) + 1
                    page.on('response', response_seen)
                    allowed = {self.stack.gateway_url, self.stack.router_url}

                    def network(route):
                        parsed = urlsplit(route.request.url)
                        if parsed.scheme in ("data", "blob", "about") or parsed.scheme + "://" + parsed.netloc in allowed:
                            route.continue_()
                        else:
                            self.external_requests += 1
                            route.abort()
                    context.route("**/*", network)
                    return page

                self.phase = "signup_unconfirmed_gate"
                owner = page_for()
                owner.goto(self.stack.gateway_url)
                owner.locator("#auth-signup").click()
                email = "local-" + uuid.uuid4().hex + "@example.invalid"
                password = secrets.token_urlsafe(24)
                start = len(self.stack.messages)
                owner.locator("#auth-email").fill(email)
                owner.locator("#auth-password").fill(password)
                owner.locator("#auth-submit").click()
                owner.wait_for_selector("#pending-login")
                self.accounts["owner"] = {"email": email, "password": password}
                self.check("browser_signup_waits_for_email", owner.locator("#create-family").count() == 0 and self.session(owner) is None)
                self.api("/api/auth/login", {"email": email, "password": password}, expected=401)
                self.check("real_auth_blocks_unconfirmed_login")
                message = self.stack.wait_message(email, since=start)
                self.accounts["owner"]["confirmation"] = self.stack.take_link(message, "signup")
                self.phase = "real_signup_confirmation"
                self.confirm_browser("owner", owner)
                owner_token = self.accounts["owner"]["token"]

                self.phase = "create_family_browser"
                owner.locator("#family-name").fill("Local fictional family")
                owner.locator("#family-timezone").fill("UTC")
                owner.locator("#create-family").click()
                owner.wait_for_selector("#nav-settings")
                households = self.rpc("list_households", token=owner_token)
                self.check("browser_family_created_once", len(households) == 1)
                house = households[0]["id"]
                self.accounts["owner"]["house"] = house
                state = self.rpc("read_state", {"p_household_id": house}, owner_token)[0]
                self.check("new_financial_state_is_empty", all(state["data"].get(key, []) == []
                    for key in ("entries", "birthdays", "goals", "boardItems", "chores", "installments")))
                metadata = self.rpc("get_household", {"p_household_id": house}, owner_token)
                self.check("starter_catalogs_are_generic_and_free", metadata["plan"] == "free"
                    and [person["name"] for person in metadata["settings"]["people"]] == ["Общее"]
                    and len(metadata["settings"]["categories"]) == 8)

                self.phase = "owner_settings_browser"
                owner.locator("#nav-settings").click()
                owner.locator("#settings-name").fill("Local fictional workspace")
                owner.locator("#settings-save").click()
                self.wait_js(owner, "document.querySelector('.family-title h1')?.textContent==='Local fictional workspace'")
                metadata = self.rpc("get_household", {"p_household_id": house}, owner_token)
                self.check("owner_settings_saved_via_real_rpc", metadata["name"] == "Local fictional workspace"
                    and metadata["settings"] == households[0]["settings"])

                self.phase = "second_family_isolation"
                outsider = page_for()
                self.signup_api("outsider")
                self.confirm_browser("outsider", outsider)
                outsider.locator("#family-name").fill("Independent fictional family")
                outsider.locator("#family-timezone").fill("UTC")
                outsider.locator("#create-family").click()
                outsider.wait_for_selector("#nav-settings")
                outsider_token = self.accounts["outsider"]["token"]
                other = self.rpc("list_households", token=outsider_token)[0]["id"]
                self.check("independent_family_ids", other != house)
                status, _ = self.stack.direct_rpc("finance_read_state", {"p_household_id": house}, token=outsider_token)
                self.check("postgrest_denies_foreign_family", status in (401, 403))
                status, _ = self.stack.direct_rpc("finance_list_households", {}, token=None)
                self.check("postgrest_denies_anonymous_rpc", status in (401, 403))

                self.phase = "actual_ledger_expense"
                owner.locator("#nav-finances").click()
                owner.wait_for_selector("#ledger-container iframe:not([hidden])", timeout=20000)
                frame = owner.frames[-1]
                self.wait_js(frame, "typeof state==='object' && typeof addEntry==='function'")
                self.check("full_ledger_has_no_seeded_financial_records", frame.evaluate("state.entries.length===0 && state.settings.loans.loan1===0 && getBirthdayRows().length===0"))
                frame.evaluate("go('today'); openEntry('expense')")
                frame.locator("#eAmount").fill("12,34")
                frame.evaluate("v90Choose('Продукты')")
                frame.locator("#eBeneficiary").select_option(label="Общее")
                frame.locator("#v90Save").click()
                deadline = time.monotonic() + 20
                persisted = None
                while time.monotonic() < deadline:
                    persisted = self.rpc("read_state", {"p_household_id": house}, owner_token)[0]
                    if len(persisted["data"].get("entries", [])) == 1:
                        break
                    owner.wait_for_timeout(100)
                entries = (persisted or {}).get("data", {}).get("entries", [])
                entry = entries[0] if entries else {}
                expected_category = metadata["settings"]["categories"][0]["id"]
                self.check("actual_iframe_expense_reaches_postgresql", entry.get("amount") == 12.34
                    and entry.get("category_id") == expected_category
                    and entry.get("person_id") == metadata["settings"]["people"][0]["id"])
                self.check("second_family_remains_empty", self.rpc("read_state", {"p_household_id": other}, outsider_token)[0]["data"]["entries"] == [])

                self.phase = "invitation_real_smtp"
                guests = {}
                for label, role in (("editor", "editor"), ("viewer", "viewer")):
                    guest = page_for()
                    guests[label] = guest
                    self.signup_api(label)
                    self.confirm_browser(label, guest)
                    owner.locator("#nav-settings").click()
                    start = len(self.stack.messages)
                    owner.locator("#invite-email").fill(self.accounts[label]["email"])
                    owner.locator("#invite-role").select_option(role)
                    owner.locator("#invite-send").click()
                    self.wait_js(owner, "document.querySelector('#invite-email')?.value===''")
                    counts = MailWorker(self.stack.settings).run_once()
                    self.check("worker_real_smtp_accepted_" + label, counts.get("sent") == 1)
                    message = self.stack.wait_message(self.accounts[label]["email"], since=start)
                    invite_link = self.stack.take_link(message, "invite")
                    invite_token = parse_qs(urlsplit(invite_link).fragment).get("invite_token", [None])[0]
                    self.accounts[label]["invite_token"] = invite_token
                    status, _ = self.stack.direct_rpc("finance_accept_invite", {"p_token": invite_token}, token=outsider_token)
                    self.check("wrong_verified_account_denied_" + label, status in (400, 403))
                    guest.goto(invite_link)
                    guest.wait_for_selector("#accept-invite")
                    self.check("invitation_secret_removed_from_browser_url_" + label, not urlsplit(guest.url).fragment)
                    guest.locator("#accept-invite").click()
                    guest.wait_for_selector("#nav-settings")
                    token = self.remember(label, guest)
                    role_result = self.rpc("get_household", {"p_household_id": house}, token)
                    self.check("verified_invitation_role_" + label, role_result["role"] == role)

                self.phase = "role_enforcement_direct_postgrest"
                viewer_token = self.accounts["viewer"]["token"]
                current = self.rpc("read_state", {"p_household_id": house}, owner_token)[0]
                status, _ = self.stack.direct_rpc("finance_state_cas", {"p_household_id": house,
                    "p_expected_revision": current["sync_revision"], "p_data": current["data"],
                    "p_request_id": str(uuid.uuid4())}, token=viewer_token)
                self.check("viewer_direct_postgrest_write_denied", status == 403)
                viewer = guests["viewer"]
                viewer.wait_for_selector("#ledger-container iframe:not([hidden])", timeout=20000)
                self.check("viewer_iframe_write_controls_disabled", viewer.frames[-1].locator("#v90Save").is_disabled())
                status, _ = self.stack.direct_rpc("finance_update_settings", {"p_household_id": house,
                    "p_name": "Blocked", "p_timezone": "UTC", "p_people": [], "p_categories": [],
                    "p_request_id": str(uuid.uuid4())}, token=self.accounts["editor"]["token"])
                self.check("editor_owner_settings_denied", status == 403)

                self.phase = "current_auth_rows_override_stale_jwt"
                viewer_uid = self.accounts["viewer"]["uid"]
                self.stack.sql("UPDATE auth.users SET email_confirmed_at=NULL WHERE id='" + viewer_uid + "';")
                try:
                    status, _ = self.stack.direct_rpc("finance_list_households", {}, token=viewer_token)
                    self.check("current_confirmation_overrides_stale_user_jwt", status == 403)
                finally:
                    self.stack.sql("UPDATE auth.users SET email_confirmed_at=now() WHERE id='" + viewer_uid + "';")
                stale_invite = self.api("/api/invites/create", {"household_id": house,
                    "email": self.accounts["viewer"]["email"], "role": "editor",
                    "request_id": str(uuid.uuid4())}, owner_token)
                stale_token = derive_invite_token(
                    self.stack.settings.invite_token_key, stale_invite['request_id'], house,
                    self.accounts['viewer']['email'], self.accounts['owner']['uid'])
                new_email = 'changed-' + uuid.uuid4().hex + '@example.invalid'
                self.stack.sql("UPDATE auth.users SET email='" + new_email + "' WHERE id='" + viewer_uid + "';")
                try:
                    status, _ = self.stack.direct_rpc("finance_accept_invite", {"p_token": stale_token}, token=viewer_token)
                    self.check("current_auth_email_overrides_stale_user_jwt", status in (400, 403))
                finally:
                    self.stack.sql("UPDATE auth.users SET email='" + self.accounts['viewer']['email'] + "' WHERE id='" + viewer_uid + "';")
                    self.rpc('revoke_invite', {'p_household_id': house, 'p_invite_id': stale_invite['id']}, owner_token)

                self.phase = "revoke_and_single_use"
                editor = self.accounts["editor"]
                extra = self.api("/api/invites/create", {"household_id": house, "email": editor["email"],
                    "role": "editor", "request_id": str(uuid.uuid4())}, owner_token)
                self.rpc("remove_member", {"p_household_id": house, "p_user_id": editor["uid"]}, owner_token)
                status, _ = self.stack.direct_rpc("finance_read_state", {"p_household_id": house}, token=editor["token"])
                self.check("revocation_blocks_existing_access_token", status == 403)
                status, _ = self.stack.direct_rpc("finance_accept_invite", {"p_token": editor["invite_token"]}, token=editor["token"])
                self.check("accepted_token_replay_does_not_restore_membership", status in (400, 403))
                invitations = self.rpc("list_invites", {"p_household_id": house}, owner_token)
                self.check("removal_invalidates_other_pending_grants", any(i["id"] == extra["id"] and i["status"] == "revoked" for i in invitations))
                guests["editor"].reload()
                guests["editor"].wait_for_selector("#family-name")
                self.check("revoked_browser_cannot_reopen_cached_family", guests["editor"].locator("#ledger-container iframe").count() == 0)

                self.phase = "unknown_recipient_and_invite_revoke"
                unknown = "local-missing-" + uuid.uuid4().hex + "@example.invalid"
                start = len(self.stack.messages)
                invite = self.api("/api/invites/create", {"household_id": house, "email": unknown,
                    "role": "viewer", "request_id": str(uuid.uuid4())}, owner_token)
                counts = MailWorker(self.stack.settings).run_once()
                self.check("invite_unknown_recipient_is_delivery_only", counts.get("sent") == 1
                    and self.stack.sql("SELECT count(*) FROM finance_app.members WHERE household_id='" + house + "';").strip() == "2")
                message = self.stack.wait_message(unknown, since=start)
                unknown_token = parse_qs(urlsplit(self.stack.take_link(message, "invite")).fragment)["invite_token"][0]
                self.rpc("revoke_invite", {"p_household_id": house, "p_invite_id": invite["id"]}, owner_token)
                status, _ = self.stack.direct_rpc("finance_accept_invite", {"p_token": unknown_token}, token=outsider_token)
                self.check("revoked_invitation_cannot_be_accepted", status in (400, 403))

                self.phase = "real_recovery_password_change"
                owner.locator("#logout").click()
                owner.wait_for_selector("#auth-recover")
                owner.locator("#auth-recover").click()
                start = len(self.stack.messages)
                owner.locator("#recover-email").fill(self.accounts["owner"]["email"])
                owner.locator("#recover-submit").click()
                message = self.stack.wait_message(self.accounts["owner"]["email"], since=start)
                owner.goto(self.stack.take_link(message, "recovery"))
                owner.wait_for_selector("#reset-password")
                self.check("real_recovery_redirect_fragment_clean", not urlsplit(owner.url).fragment)
                new_password = secrets.token_urlsafe(24)
                owner.locator("#reset-password").fill(new_password)
                owner.locator("#reset-repeat").fill(new_password)
                owner.locator("#reset-submit").click()
                owner.wait_for_selector("[data-household]")
                self.api("/api/auth/login", {"email": self.accounts["owner"]["email"], "password": self.accounts["owner"]["password"]}, expected=401)
                recovered = self.api("/api/auth/login", {"email": self.accounts["owner"]["email"], "password": new_password})
                self.check("password_changed_in_real_auth", bool(recovered.get("session", {}).get("access_token")))
                unknown_reply = self.api("/api/auth/recover", {"email": unknown})
                known_reply = self.api("/api/auth/recover", {"email": self.accounts["viewer"]["email"]})
                self.check("recovery_does_not_disclose_account_existence", unknown_reply == known_reply)
                self.check("browser_has_no_javascript_errors", self.browser_errors == 0)
                self.check("browser_made_no_external_requests", self.external_requests == 0)
            finally:
                for context in contexts:
                    for page in context.pages:
                        if not page.is_closed():
                            for selector in ('#auth-submit', '#pending-login', '#create-family', '#settings-save', '.form-error:not([hidden])'):
                                try:
                                    self.ui_state_counts[selector] = self.ui_state_counts.get(selector, 0) + page.locator(selector).count()
                                except Exception:
                                    pass
                for context in contexts:
                    context.close()
                browser.close()

    def run_backend(self):
        """Incremental diagnostic mode still uses real Auth, SMTP and PostgREST."""
        import http.client
        self.phase = "backend_auth_smoke"
        account = self.signup_api("backend")
        self.api("/api/auth/login", {"email": account["email"], "password": account["password"]}, expected=401)
        parsed = urlsplit(account["confirmation"])
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=20)
        try:
            connection.request("GET", parsed.path + "?" + parsed.query)
            response = connection.getresponse()
            response.read()
            self.check("real_gotrue_confirmation_redirect", response.status in (302, 303))
        finally:
            connection.close()
        session = self.api("/api/auth/login", {"email": account["email"], "password": account["password"]})["session"]
        token = session["access_token"]
        self.check("real_confirmed_auth_login", bool(session["user"].get("email_confirmed_at")))
        family = self.rpc("create_household", {"p_name": "Local backend family", "p_timezone": "UTC", "p_request_id": str(uuid.uuid4())}, token)
        state = self.rpc("read_state", {"p_household_id": family["id"]}, token)[0]
        self.check("real_postgrest_creates_blank_family", state["data"]["entries"] == [] and family["plan"] == "free")
        start = len(self.stack.messages)
        self.api("/api/invites/create", {"household_id": family["id"], "email": "unregistered@example.invalid", "role": "viewer", "request_id": str(uuid.uuid4())}, token)
        counts = MailWorker(self.stack.settings).run_once()
        self.stack.wait_message("unregistered@example.invalid", since=start)
        self.check("real_sql_worker_to_smtp", counts["sent"] == 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-only", action="store_true", help="Run an incremental real Auth/RPC/SMTP smoke without browser coverage")
    parser.add_argument("--report", type=Path, help="Write the sanitized source-bound JSON report")
    args = parser.parse_args()
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_PATHS}
    report = {"kind": "local_public_accounts_acceptance", "status": "failed", "phase": "stack_startup",
              "source_sha256": hashes, "coverage": "backend_only" if args.backend_only else "chromium_full_stack",
              "checks": [], "limits": LIMITS}
    acceptance = None
    started = time.monotonic()
    runtime = LocalAccountsStack()
    try:
        with runtime as stack:
            acceptance = Acceptance(stack, backend_only=args.backend_only)
            if args.backend_only:
                acceptance.run_backend()
            else:
                acceptance.run_browser()
            report["status"] = "passed"
            report["phase"] = "complete"
    except Exception as error:
        # Playwright errors and upstream responses may contain tokens/passwords.
        # Report only the controlled phase and successful assertion labels.
        report["phase"] = acceptance.phase if acceptance else runtime.phase
        if isinstance(error, CheckFailed):
            report["failure_assertion"] = str(error)
        report["failure_type"] = type(error).__name__
    finally:
        if acceptance:
            report["checks"] = acceptance.checks
            report["browser_error_count"] = acceptance.browser_errors
            report["external_request_count"] = acceptance.external_requests
            if report["status"] != "passed":
                report["response_counts"] = acceptance.response_counts
                report["ui_state_counts"] = acceptance.ui_state_counts
        report["assertion_count"] = len(report["checks"])
        report["source_unchanged"] = all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value
                                         for name, value in hashes.items())
        if report['status'] == 'passed' and not report['source_unchanged']:
            report['status'], report['phase'] = 'failed', 'source_changed_during_check'
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    raw = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(raw)
    print(raw, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

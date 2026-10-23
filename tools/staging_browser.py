"""Actual client/Auth/PostgREST checks against the fixed fictional staging project.

The route bridge forwards real HTTPS requests through the caller's TLS-verifying
transport. It does not synthesize auth/RPC responses. Native browser CORS and
direct browser proxy/CA configuration are outside this check's evidence.
"""
from __future__ import annotations

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
import time
import uuid
from urllib.parse import urlsplit

from build_bundle import ICON, transform_demo
from serve_staging import CONFIG_RE
from supabase_staging import PROJECT_URL


ROOT = Path(__file__).resolve().parents[1]
STATE_KEY = "marichevy_staging_browser_state_v10"
PENDING_KEY = "marichevy_staging_browser_pending_v10"


class BrowserCheckError(RuntimeError):
    """Only a safe phase name and completed assertion labels leave this helper."""
    def __init__(self, phase, checks, diagnostics=None):
        super().__init__("Hosted browser check failed during " + phase)
        self.checks_completed = list(checks)
        self.diagnostics = diagnostics or {}


def sanitized_client(source, public_key, household):
    """Keep delivered auth/sync code, remove only the generator's demo wrappers."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", public_key or ""):
        raise ValueError("Expected a staging public API key")
    if public_key.startswith("sb_secret_"):
        raise ValueError("Admin keys must never enter the browser")
    if not public_key.startswith("sb_publishable_"):
        try:
            parts = public_key.split(".")
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
            if len(parts) != 3 or payload.get("role") != "anon":
                raise ValueError()
        except (ValueError, IndexError, UnicodeError):
            raise ValueError("Expected a public publishable/anon key") from None
    household = str(uuid.UUID(household))
    html = transform_demo(source)
    guard_marker = '<meta http-equiv="Content-Security-Policy"'
    footer_marker = '<script>\n(()=>{session=null;stopCloudSync();startCloudSync=()=>{};'
    if html.count(guard_marker) != 1 or html.count(footer_marker) != 1:
        raise ValueError("Demo wrapper changed; review the staging transform")
    start = html.index(guard_marker)
    end = html.index("</script>", start) + len("</script>")
    wrapper = html[start:end]
    if "window.fetch=()=>Promise.reject" not in wrapper or "localStorage.setItem('marichevy_demo_state_v10'" not in wrapper:
        raise ValueError("Unexpected demo network/fixture wrapper")
    html = html[:start] + html[end:]
    start = html.index(footer_marker)
    end = html.index("</script>", start) + len("</script>")
    wrapper = html[start:end]
    if "showApp();setStatus('ДЕМО" not in wrapper or "testTelegram=async()=>" not in wrapper:
        raise ValueError("Unexpected demo authentication wrapper")
    html = html[:start] + html[end:]
    replacement = "const CONFIG=Object.freeze({url:'" + PROJECT_URL + "',key:'" + public_key + "',household:'" + household + "'});"
    html, count = CONFIG_RE.subn(lambda _: replacement, html)
    if count != 1:
        raise ValueError("Expected one sanitized CONFIG")
    html = html.replace("marichevy_demo_", "marichevy_staging_browser_")
    csp = ("default-src 'self' data: blob:; script-src 'self' 'unsafe-inline'; "
           "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
           "connect-src " + PROJECT_URL + "; form-action 'none'; base-uri 'none'; object-src 'none'")
    html = html.replace("<head>", '<head><meta http-equiv="Content-Security-Policy" content="' + csp + '">', 1)
    if STATE_KEY not in html or PENDING_KEY not in html:
        raise ValueError("Expected isolated staging-browser storage namespace")
    return html


class RouteBridge:
    """Strict allowlist + deterministic read barrier, using real HTTPS responses."""
    def __init__(self, transport, local_base):
        self.transport, self.local_base = transport, local_base
        self.offline = set()
        self.hold_reads = False
        self.held = []
        self.cas_conflicts = 0
        self.forwarded = 0
        self.blocked_integrations = 0
        self.failures = 0
        self.responses = []

    def fulfill(self, route, status, body):
        route.fulfill(status=status, body="" if body is None else json.dumps(body),
            headers={"Content-Type": "application/json", "Access-Control-Allow-Origin": self.local_base.rstrip("/"),
                     "Access-Control-Allow-Headers": "authorization,apikey,content-type", "Cache-Control": "no-store"})

    def route(self, route, label):
        request = route.request
        if request.url.startswith(self.local_base):
            route.continue_()
            return
        parsed = urlsplit(request.url)
        if parsed.scheme != "https" or parsed.netloc != urlsplit(PROJECT_URL).netloc \
                or not (parsed.path.startswith("/auth/v1/") or parsed.path.startswith("/rest/v1/")):
            self.blocked_integrations += 1
            route.abort()
            return
        if label in self.offline:
            route.abort()
            return
        if request.method == "OPTIONS":
            # Browser-origin policy is deliberately a bridge concern; the real
            # HTTPS calls below test server auth/RLS/CAS, not native CORS.
            self.fulfill(route, 204, None)
            return
        try:
            headers = {key: value for key, value in request.headers.items()
                       if key.lower() in ("authorization", "apikey", "content-type", "prefer")}
            body = json.loads(request.post_data) if request.post_data else None
            status, result = self.transport.request(request.method, request.url, headers, body)
            self.forwarded += 1
            self.responses.append({'method': request.method, 'path': parsed.path, 'status': status})
            if parsed.path == "/rest/v1/rpc/family_state_cas" and isinstance(result, dict) and result.get("status") == "conflict":
                self.cas_conflicts += 1
            if self.hold_reads and request.method == "GET" and parsed.path == "/rest/v1/family_state":
                self.held.append((route, status, result))
                if len(self.held) == 2:
                    self.hold_reads = False
                    held, self.held = self.held, []
                    for waiting, code, snapshot in held:
                        self.fulfill(waiting, code, snapshot)
                return
            self.fulfill(route, status, result)
        except Exception:
            self.failures += 1
            route.abort()


def verify_browser_flow(transport, public_key, household, credentials):
    """Run with two own-family logins and one foreign-family login, in memory.

    `credentials` is a list of three {email, password} dictionaries supplied by
    the root staging runner. No credential or browser-storage file is written.
    """
    from playwright.sync_api import sync_playwright

    checks, phase = [], "initialization"
    html = sanitized_client((ROOT / "index.html").read_text(), public_key, household).encode()
    if len(credentials) != 3:
        raise ValueError("Expected two family members and one foreign-family account")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/", "/index.html", "/favicon.svg"):
                self.send_error(404)
                return
            body = ICON.encode() if self.path == "/favicon.svg" else html
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml" if self.path == "/favicon.svg" else "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}/"
    bridge = RouteBridge(transport, base)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
            try:
                def wait(page, expression, timeout=30000):
                    # Playwright wait_for_function creates a Function in-page,
                    # which this staging CSP correctly rejects without unsafe-eval.
                    deadline = time.monotonic() + timeout / 1000
                    while not page.evaluate(expression):
                        if time.monotonic() >= deadline:
                            raise RuntimeError('Client readiness condition timed out')
                        page.wait_for_timeout(50)
                def context(label, seed=None):
                    result = browser.new_context(service_workers="block", timezone_id="Europe/Moscow")
                    result.route("**/*", lambda route: bridge.route(route, label))
                    if seed is not None:
                        result.add_init_script("localStorage.setItem(" + json.dumps(STATE_KEY) + "," + json.dumps(seed) + ");")
                    return result
                def login(page, credential):
                    page.locator("#gateEmail").fill(credential["email"])
                    page.locator("#gatePassword").fill(credential["password"])
                    page.locator("#gateLoginBtn").click()
                    wait(page, "!document.getElementById('appRoot').classList.contains('auth-locked')")
                    wait(page, "!saving&&!cloudSyncBusy&&localStorage.getItem(CLOUD_BASE_KEY)!==null")
                    page.evaluate("stopCloudSync()")
                pages = []
                phase = "two real UI logins"
                for label, credential in zip(("a", "b"), credentials[:2]):
                    page = context(label).new_page()
                    page.set_default_timeout(30000)
                    page.goto(base, wait_until="domcontentloaded")
                    login(page, credential)
                    pages.append(page)
                initial = pages[0].evaluate("state.entries.map(x=>x.id)")
                if not initial or pages[1].evaluate("state.entries.map(x=>x.id)") != initial:
                    raise RuntimeError()
                checks.extend(["two actual UI logins authorized", "both clients read existing synthetic history"])
                phase = "concurrent real client additions"
                ids = ["browser-a-" + uuid.uuid4().hex, "browser-b-" + uuid.uuid4().hex]
                bridge.hold_reads = True
                for page, identifier in zip(pages, ids):
                    page.evaluate("""id=>{const now=new Date().toISOString();
                      state.entries.push({id,type:'expense',amount:12.50,date:today(),category:'Продукты',who:'Общее',created_at:now,updated_at:now});
                      window.__browserWrite=saveAll();}""", identifier)
                for page in pages:
                    if page.evaluate("window.__browserWrite") is not True:
                        raise RuntimeError()
                for page in pages:
                    page.evaluate("syncFromCloud()")
                    values = page.evaluate("state.entries.map(x=>x.id)")
                    if not all(identifier in values for identifier in initial + ids) or any(values.count(identifier) != 1 for identifier in ids):
                        raise RuntimeError()
                    page.reload(wait_until="domcontentloaded")
                    wait(page, "!document.getElementById('appRoot').classList.contains('auth-locked')&&!cloudSyncBusy")
                    page.evaluate("stopCloudSync()")
                    if not all(identifier in page.evaluate("state.entries.map(x=>x.id)") for identifier in initial + ids):
                        raise RuntimeError()
                if bridge.cas_conflicts < 1:
                    raise RuntimeError()
                checks.extend(["actual clients resolve a real server revision conflict", "both additions survive both reloads exactly once"])
                phase = "offline queue and reload"
                bridge.offline.add("a")
                pages[0].evaluate("""id=>{const row=state.entries.find(x=>x.id===id);row.amount=12.75;row.updated_at='2001-01-01T00:00:00.000Z';window.__offlineWrite=saveAll()}""", ids[0])
                if pages[0].evaluate("window.__offlineWrite") is not False:
                    raise RuntimeError()
                pending = pages[0].evaluate("localStorage.getItem(KEYS.pending)")
                if not pending or not any(row["id"] == ids[0] and row["amount"] == 12.75
                                          for row in json.loads(pending)["entries"]):
                    raise RuntimeError()
                pages[0].reload(wait_until="domcontentloaded")
                wait(pages[0], "session===null")
                if pages[0].evaluate("localStorage.getItem(KEYS.pending)") != pending:
                    raise RuntimeError()
                bridge.offline.remove("a")
                login(pages[0], credentials[0])
                pages[1].evaluate("syncFromCloud()")
                if not all(page.evaluate("id=>state.entries.find(x=>x.id===id)?.amount", ids[0]) == 12.75 for page in pages):
                    raise RuntimeError()
                checks.extend(["offline pending survives reload without clearing storage", "queued edit reaches both real clients after login"])
                phase = "same-record conflict with skewed clocks"
                for page, amount, stamp in [(pages[0], 13, '2099-01-01'), (pages[1], 14, '2001-01-01')]:
                    result = page.evaluate("""v=>{const row=state.entries.find(x=>x.id===v.id);
                      row.amount=v.amount;row.updated_at=v.stamp;return saveAll()}""",
                      {'id': ids[0], 'amount': amount, 'stamp': stamp})
                    if result is not (amount == 13):
                        raise RuntimeError()
                saved_pending = pages[1].evaluate("localStorage.getItem(KEYS.pending)")
                packet = pages[1].evaluate("JSON.parse(localStorage.getItem(CLOUD_CONFLICT_KEY))")
                def amount(snapshot):
                    return next(row['amount'] for row in snapshot['entries'] if row['id'] == ids[0])
                if [amount(packet[key]) for key in ('base', 'cloud', 'local')] != [12.75, 13, 14]:
                    raise RuntimeError()
                pages[1].reload(wait_until='domcontentloaded')
                wait(pages[1], "!document.getElementById('appRoot').classList.contains('auth-locked')&&!cloudSyncBusy")
                pages[1].evaluate('stopCloudSync()')
                if pages[1].evaluate("localStorage.getItem(KEYS.pending)") != saved_pending:
                    raise RuntimeError()
                if pages[0].evaluate("id=>state.entries.find(x=>x.id===id).amount", ids[0]) != 13:
                    raise RuntimeError()
                checks.append('same-record conflict retains both variants and local queue after reload')
                phase = 'edit versus deletion with skewed clocks'
                editing = context('editing').new_page()
                editing.goto(base, wait_until='domcontentloaded')
                login(editing, credentials[1])
                if pages[0].evaluate("""id=>{state.entries=state.entries.filter(x=>x.id!==id);
                    state.deletedEntries[id]='2001-01-01';return saveAll()}""", ids[0]) is not True:
                    raise RuntimeError()
                result = editing.evaluate("""id=>{const row=state.entries.find(x=>x.id===id);
                    row.amount=15;row.updated_at='2099-01-01';return saveAll()}""", ids[0])
                packet = editing.evaluate("JSON.parse(localStorage.getItem(CLOUD_CONFLICT_KEY))")
                if result is not False or amount(packet['local']) != 15 \
                        or any(row['id'] == ids[0] for row in packet['cloud']['entries']) \
                        or packet['cloud']['deletedEntries'].get(ids[0]) != '2001-01-01':
                    raise RuntimeError()
                checks.append('real edit/delete conflict preserves unsent edit regardless of clocks')
                phase = "foreign UI login with cached fictional finances"
                seed = pages[0].evaluate("localStorage.getItem(KEYS.state)")
                outsider = context("foreign", seed).new_page()
                outsider.goto(base, wait_until="domcontentloaded")
                outsider.locator("#gateEmail").fill(credentials[2]["email"])
                outsider.locator("#gatePassword").fill(credentials[2]["password"])
                outsider.locator("#gateLoginBtn").click()
                wait(outsider, "document.getElementById('gateError').textContent.includes('Нет доступа')")
                if not outsider.evaluate("session===null&&document.getElementById('appRoot').classList.contains('auth-locked')"):
                    raise RuntimeError()
                if outsider.evaluate("localStorage.getItem(KEYS.state)") != seed:
                    raise RuntimeError()
                checks.append("foreign account cannot unlock cached household UI")
                if bridge.failures:
                    raise RuntimeError()
                return {"checks": checks, "forwarded_real_https_requests": bridge.forwarded,
                        "real_cas_conflicts": bridge.cas_conflicts, "integration_requests_blocked": bridge.blocked_integrations,
                        "native_browser_cors_tested": False, "production_tested": False}
            finally:
                browser.close()
    except Exception as error:
        summary = str(error).splitlines()[0][:240]
        for value in [public_key, *[value for credential in credentials for value in credential.values()]]:
            summary = summary.replace(value, '[redacted]')
        summary = re.sub(r'(?:sbp_|sb_secret_)[A-Za-z0-9_-]+|eyJ[A-Za-z0-9_.-]+', '[redacted]', summary)
        raise BrowserCheckError(phase, checks, {'exception_type': type(error).__name__,
            'safe_summary': summary,
            'https_responses': bridge.responses, 'bridge_failures': bridge.failures,
            'held_reads': len(bridge.held)}) from None
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

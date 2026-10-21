#!/usr/bin/env python3
"""Serve a network-isolated local copy of the Marichevy finance app."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent.parent
ALLOWED_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/favicon.ico": ("favicon.ico", "image/vnd.microsoft.icon"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    "/favicon-32.png": ("favicon-32.png", "image/png"),
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
}

# Replace exactly the live CONFIG object, in memory only. Empty values prevent
# accidental credential use even if this server is later run without its CSP.
CONFIG_RE = re.compile(
    r"const CONFIG=Object\.freeze\(\{\s*"
    r"url:'[^']*',\s*key:'[^']*',\s*household:'[^']*'\s*"
    r"\}\);"
)

FIXTURE_EARLY_SCRIPT = r"""
<script>
try { localStorage.removeItem('marichevy_staging_session_v10'); } catch (_) {}
</script>
"""

FIXTURE_SCRIPT = r"""
<script>
(() => {
  const announce = (message) => {
    const node = document.getElementById('syncStatus');
    if (node) node.textContent = message;
  };
  try {
    const rawState = localStorage.getItem(KEYS.state);
    const rawPending = localStorage.getItem(KEYS.pending);
    const recoveryKeys = [
      'marichevy_staging_state_backup_v44',
      'marichevy_staging_pre_import_backup_v73',
      'marichevy_staging_state_v10_corrupt_v1',
      'marichevy_staging_pending_v10_corrupt_v1',
      'marichevy_staging_state_backup_v44_corrupt_v1',
      'marichevy_staging_pre_import_backup_v73_corrupt_v1',
    ];
    const hasRecovery = recoveryKeys.some((key) => localStorage.getItem(key) !== null);
    if (!localRecoveryBlocked && rawState === null && rawPending === null && !hasRecovery) {
      state = blankState();
      state.entries = [];
      saveLocal();
      announce('Локальный режим · тестовые данные пусты · облако отключено');
    } else {
      // Existing and recovery values, including malformed JSON, stay intact.
      announce('Локальный режим · сохранённые или резервные данные не заменены · облако отключено');
    }
  } catch (error) {
    announce('Локальный режим · хранилище недоступно · облако отключено');
  }
  session = null;
  stopCloudSync();
  showApp();
  setStatus('Локальная тестовая среда', false);
  announce('Локальный режим · облако отключено' +
    (localRecoveryNotice ? ' · ' + localRecoveryNotice : '') +
    (v89StorageFailed && !localRecoveryNotice ? ' · Ошибка локального хранения: скачайте JSON' : ''));
})();
</script>
"""


def response_body(path: str, fixture: bool) -> tuple[bytes, str]:
    filename, content_type = ALLOWED_FILES[path]
    body = (ROOT / filename).read_bytes()
    if filename == "index.html":
        html = body.decode("utf-8")
        html, replacements = CONFIG_RE.subn(
            "const CONFIG=Object.freeze({url:'',key:'',household:'local-staging'});",
            html,
        )
        if replacements != 1:
            raise RuntimeError(
                f"Expected exactly one live CONFIG block in index.html; found {replacements}"
            )
        staging_keys = {
            "marichevy_state_v10": "marichevy_staging_state_v10",
            "marichevy_session_v10": "marichevy_staging_session_v10",
            "marichevy_pending_v10": "marichevy_staging_pending_v10",
            "marichevy_state_backup_v44": "marichevy_staging_state_backup_v44",
            "marichevy_pre_import_backup_v73": "marichevy_staging_pre_import_backup_v73",
        }
        for original, staging in staging_keys.items():
            if original not in html:
                raise RuntimeError(f"Expected staging storage key {original!r} in index.html")
            html = html.replace(original, staging)
        if fixture:
            html, head_replacements = re.subn(
                r"(<head(?:\s[^>]*)?>)",
                lambda match: match.group(1) + FIXTURE_EARLY_SCRIPT,
                html,
                count=1,
                flags=re.IGNORECASE,
            )
            if head_replacements != 1:
                raise RuntimeError("Expected exactly one <head> in index.html")
            html = html.replace("</body>", FIXTURE_SCRIPT + "\n</body>", 1)
        body = html.encode("utf-8")
    return body, content_type


class StagingHandler(BaseHTTPRequestHandler):
    server_version = "MarichevyStaging/1.0"
    sys_version = ""

    def _send_file(self, *, head_only: bool) -> None:
        # Ignore query strings; accept only the small explicit allowlist.
        path = urlsplit(self.path).path
        if path not in ALLOWED_FILES:
            self.send_error(404, "Not found")
            return
        try:
            body, content_type = response_body(path, self.server.fixture_mode)
        except OSError:
            self.send_error(404, "Not found")
            return
        except RuntimeError as error:
            self.send_error(500, str(error))
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self' data: blob:; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "font-src 'self' data:; "
            "img-src 'self' data: blob:; "
            "connect-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'",
        )
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self._send_file(head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API
        self._send_file(head_only=True)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        self.send_error(405, "Method not allowed")

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST
    do_OPTIONS = do_POST

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="loopback bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="port (default: 8765)")
    parser.add_argument("--fixture", action="store_true", help="enable an isolated blank local fixture")
    args = parser.parse_args()
    if args.host != "127.0.0.1":
        parser.error("the staging server may bind only to 127.0.0.1")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), StagingHandler)
    server.fixture_mode = args.fixture
    mode = "fixture" if args.fixture else "read-only staging"
    print(f"Serving {mode} on 127.0.0.1:{args.port}; press Ctrl+C to stop", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping staging server", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

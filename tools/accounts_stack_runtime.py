"""Disposable real GoTrue/PostgREST/account gateway stack, entirely local.

Images must already exist locally. The internal Docker bridge has no external
egress, only the two HTTP services publish ports, and every published/listening
HTTP port is bound to loopback. Credentials and captured mail stay in memory.
"""
from __future__ import annotations

import base64
from dataclasses import replace
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr
import hashlib
import hmac
import html
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import socketserver
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from server.account_gateway import Gateway, GatewayServer, Settings

POSTGRES_IMAGE = "postgres:16-alpine@sha256:f4610795587492cd4fb887c2dc3de301b813278bb6f616992061141b5f15ac36"
GOTRUE_IMAGE = "supabase/gotrue:v2.177.0@sha256:6a916b47af0386b7e0152ca84f3d45d050bf056e449a75a5460b48742fd67822"
POSTGREST_IMAGE = "postgrest/postgrest:v12.2.3@sha256:729bf65c733b73f5b52777f0e4b853f22ed73aa67a22d38269d289779b0a8401"


def _jwt(secret: str, role: str) -> str:
    def encoded(value):
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")
    now = int(time.time())
    message = encoded({"alg": "HS256", "typ": "JWT"}) + "." + encoded({
        "role": role, "aud": "authenticated", "iss": "local-accounts-stack",
        "iat": now - 10, "exp": now + 7200,
    })
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
    return message + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")


class _QuietHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, *_args):
        pass


class _Router(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def _forward(self):
        stack = self.server.stack
        if self.path.startswith("/auth/v1/"):
            host, port, path = stack._auth_host, stack._auth_port, self.path[len("/auth/v1"):]
        elif self.path.startswith("/rest/v1/"):
            host, port, path = stack._rest_host, stack._rest_port, self.path[len("/rest/v1"):]
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        connection = http.client.HTTPConnection(host, port, timeout=20)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else None
            excluded = {"host", "connection", "transfer-encoding", "content-length"}
            headers = {key: value for key, value in self.headers.items() if key.lower() not in excluded}
            connection.request(self.command, path, body=body, headers=headers)
            upstream = connection.getresponse()
            raw = upstream.read()
            self.send_response(upstream.status, upstream.reason)
            for key, value in upstream.getheaders():
                if key.lower() not in {"connection", "transfer-encoding", "content-length"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)
        except (OSError, ValueError, http.client.HTTPException):
            self.close_connection = True
        finally:
            connection.close()

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _forward


class _SMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, *_args):
        pass


class _SMTP(socketserver.StreamRequestHandler):
    def reply(self, line):
        self.wfile.write(line.encode() + b"\r\n")
        self.wfile.flush()

    def handle(self):
        self.connection.settimeout(20)
        recipients = []
        self.reply("220 local-accounts-mail ESMTP")
        while True:
            raw = self.rfile.readline(65537)
            if not raw:
                return
            text = raw.decode("utf-8", errors="replace").strip()
            command = text.split(" ", 1)[0].upper()
            if command in ("EHLO", "HELO"):
                self.reply("250-local-accounts-mail")
                self.reply("250-8BITMIME")
                self.reply("250 SIZE 10485760")
            elif command == "MAIL":
                recipients = []
                self.reply("250 OK")
            elif command == "RCPT":
                address = text.split(":", 1)[-1].strip().split(" ", 1)[0]
                recipients.append(parseaddr(address)[1].lower())
                self.reply("250 OK")
            elif command == "DATA":
                self.reply("354 End data with <CR><LF>.<CR><LF>")
                chunks = []
                while True:
                    line = self.rfile.readline(10485761)
                    if not line:
                        return
                    if line in (b".\r\n", b".\n"):
                        break
                    chunks.append(line[1:] if line.startswith(b"..") else line)
                message = BytesParser(policy=policy.default).parsebytes(b"".join(chunks))
                message.envelope_recipients = tuple(recipients)
                with self.server.stack._mail_condition:
                    self.server.stack.messages.append(message)
                    self.server.stack._mail_condition.notify_all()
                self.reply("250 Message accepted")
            elif command == "QUIT":
                self.reply("221 Bye")
                return
            elif command in ("RSET", "NOOP"):
                recipients = [] if command == "RSET" else recipients
                self.reply("250 OK")
            else:
                self.reply("502 Command not implemented")


class LocalAccountsStack:
    """Context-managed stack. No existing Docker objects or remote services change."""

    def __init__(self):
        self._prefix = "finance-accounts-" + uuid.uuid4().hex[:12]
        self._network = self._prefix + "-network"
        self._containers = []
        self._servers = []
        self._threads = []
        self._network_created = False
        self._mail_condition = threading.Condition()
        self.messages: list[EmailMessage] = []
        self._db_password = secrets.token_urlsafe(36)
        self._jwt_secret = secrets.token_urlsafe(48)
        self._anon_key = _jwt(self._jwt_secret, "anon")
        self._service_key = _jwt(self._jwt_secret, "service_role")
        self._database = "accounts_fictional"
        self._postgres = self._prefix + "-postgres"
        self._auth_port = self._rest_port = 0
        self._auth_host = self._rest_host = "127.0.0.1"
        self.gateway_url = self.router_url = ""
        self.settings = None
        self.phase = "initialization"

    @staticmethod
    def _docker(*args, input=None, check=True):
        env = os.environ.copy()
        for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
            env.pop(key, None)
        try:
            result = subprocess.run(["docker", "--host=unix:///var/run/docker.sock", *args],
                                    input=input, text=True, capture_output=True, env=env, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError("Local Docker command did not complete") from None
        if check and result.returncode:
            # Docker errors can echo environment values or connection strings.
            raise RuntimeError("Local Docker command failed") from None
        return result

    def _run(self, name, image, env, *extra):
        self._containers.append(name)
        args = ["run", "--detach", "--pull=never", "--name", name,
                "--network", self._network, "--log-driver=none", *extra]
        for key, value in env.items():
            args.extend(("--env", key + "=" + str(value)))
        self._docker(*args, image)

    def _published(self, name, port):
        result = self._docker("port", name, str(port) + "/tcp", check=False)
        value = result.stdout.strip()
        if result.returncode == 0 and value.startswith("127.0.0.1:"):
            return "127.0.0.1", int(value.rsplit(":", 1)[1])
        # Docker 28 suppresses all host mappings for an --internal bridge. Keep
        # that stricter isolation: the host router can reach its private bridge
        # addresses, while callers still use only the loopback router endpoint.
        record = json.loads(self._docker("inspect", name).stdout)[0]
        bindings = record["HostConfig"].get("PortBindings", {})
        if any(item.get("HostIp") != "127.0.0.1" for entries in bindings.values() for item in entries):
            raise RuntimeError("Local HTTP service attempted a non-loopback publication")
        address = record["NetworkSettings"]["Networks"][self._network].get("IPAddress")
        if not address:
            raise RuntimeError("Local HTTP service has no isolated bridge address")
        return address, port

    def _serve(self, server):
        self._servers.append(server)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._threads.append(thread)
        thread.start()

    def _wait_http(self, host, port, path):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            connection = http.client.HTTPConnection(host, port, timeout=1)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                response.read()
                if response.status == 200:
                    return
            except (OSError, http.client.HTTPException):
                pass
            finally:
                connection.close()
            time.sleep(.15)
        raise RuntimeError("Local HTTP service readiness timed out")

    def __enter__(self):
        try:
            self.phase = "local Docker images"
            self._docker("info", "--format", "{{.ServerVersion}}")
            for image in (POSTGRES_IMAGE, GOTRUE_IMAGE, POSTGREST_IMAGE):
                self._docker("image", "inspect", image)
            self.phase = "isolated Docker network"
            self._docker("network", "create", "--internal", self._network)
            self._network_created = True
            bridge = json.loads(self._docker("network", "inspect", self._network).stdout)[0]["IPAM"]["Config"][0]["Gateway"]
            for address in (bridge, "127.0.0.1"):
                server = _SMTPServer((address, 0), _SMTP)
                server.stack = self
                self._serve(server)
                if address == bridge:
                    smtp_bridge_port = server.server_address[1]
                else:
                    smtp_loopback_port = server.server_address[1]
            router = _QuietHTTPServer(("127.0.0.1", 0), _Router)
            router.stack = self
            self.router_url = "http://127.0.0.1:" + str(router.server_address[1])
            self._serve(router)
            initial = Settings(
                supabase_url=self.router_url, publishable_key=self._anon_key,
                service_role_key=self._service_key, public_origin="http://127.0.0.1:1",
                invite_token_key=secrets.token_bytes(48), dev_loopback=True,
                smtp_host="127.0.0.1", smtp_port=smtp_loopback_port, smtp_mode="plain",
                smtp_from="finance@example.invalid", smtp_plain_loopback_test=True,
                public_dir=ROOT / "public")
            gateway = GatewayServer(("127.0.0.1", 0), initial)
            self.gateway_url = "http://127.0.0.1:" + str(gateway.server_address[1])
            self.settings = replace(initial, public_origin=self.gateway_url)
            gateway.gateway = Gateway(self.settings)
            self._serve(gateway)
            self.phase = "PostgreSQL startup"
            self._run(self._postgres, POSTGRES_IMAGE, {
                "POSTGRES_PASSWORD": self._db_password, "POSTGRES_DB": self._database,
            }, "--tmpfs", "/var/lib/postgresql/data", "--network-alias", "postgres")
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                ready = self._docker("exec", self._postgres, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", check=False)
                if ready.returncode == 0:
                    break
                time.sleep(.15)
            else:
                raise RuntimeError("Local PostgreSQL readiness timed out")
            password = "'" + self._db_password.replace("'", "''") + "'"
            self.sql("CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN;"
                     "CREATE ROLE service_role NOLOGIN BYPASSRLS; CREATE ROLE authenticator LOGIN NOINHERIT PASSWORD " + password + ";"
                     "GRANT anon,authenticated,service_role TO authenticator; CREATE SCHEMA auth;")
            self.phase = "GoTrue migrations and startup"
            auth_name = self._prefix + "-gotrue"
            self._run(auth_name, GOTRUE_IMAGE, {
                "GOTRUE_API_HOST": "0.0.0.0", "GOTRUE_API_PORT": "9999",
                "API_EXTERNAL_URL": self.router_url,
                "GOTRUE_SITE_URL": self.gateway_url,
                "GOTRUE_URI_ALLOW_LIST": self.gateway_url + "/**",
                "GOTRUE_DB_DRIVER": "postgres",
                "GOTRUE_DB_DATABASE_URL": "postgres://postgres:" + self._db_password + "@postgres:5432/" + self._database + "?sslmode=disable&search_path=auth",
                "GOTRUE_DB_NAMESPACE": "auth", "GOTRUE_JWT_SECRET": self._jwt_secret,
                "GOTRUE_JWT_AUD": "authenticated", "GOTRUE_JWT_DEFAULT_GROUP_NAME": "authenticated",
                "GOTRUE_JWT_ADMIN_ROLES": "service_role", "GOTRUE_JWT_EXP": "3600",
                "GOTRUE_DISABLE_SIGNUP": "false", "GOTRUE_EXTERNAL_EMAIL_ENABLED": "true",
                "GOTRUE_MAILER_AUTOCONFIRM": "false", "GOTRUE_SMTP_HOST": bridge,
                "GOTRUE_SMTP_PORT": smtp_bridge_port, "GOTRUE_SMTP_ADMIN_EMAIL": "auth@example.invalid",
                "GOTRUE_SMTP_SENDER_NAME": "Fictional local accounts", "GOTRUE_SMTP_MAX_FREQUENCY": "1s",
                "GOTRUE_MAILER_URLPATHS_CONFIRMATION": "/auth/v1/verify",
                "GOTRUE_MAILER_URLPATHS_RECOVERY": "/auth/v1/verify",
                "GOTRUE_MAILER_URLPATHS_INVITE": "/auth/v1/verify",
                "GOTRUE_RATE_LIMIT_EMAIL_SENT": "1000", "GOTRUE_LOG_LEVEL": "error",
            }, "--publish", "127.0.0.1::9999")
            self._auth_host, self._auth_port = self._published(auth_name, 9999)
            self._wait_http(self._auth_host, self._auth_port, "/health")
            self.phase = "account SQL migration"
            self.sql("""
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$
 SELECT coalesce(nullif(current_setting('request.jwt.claim.sub',true),''),
   nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub')::uuid $$;
CREATE OR REPLACE FUNCTION auth.role() RETURNS text LANGUAGE sql STABLE AS $$
 SELECT coalesce(nullif(current_setting('request.jwt.claim.role',true),''),
   nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'role') $$;
GRANT USAGE ON SCHEMA public,auth TO anon,authenticated,service_role;
""" + (ROOT / "server/004_public_accounts.sql").read_text())
            self.phase = "PostgREST startup"
            rest_name = self._prefix + "-postgrest"
            self._run(rest_name, POSTGREST_IMAGE, {
                "PGRST_DB_URI": "postgres://authenticator:" + self._db_password + "@postgres:5432/" + self._database,
                "PGRST_DB_SCHEMAS": "public", "PGRST_DB_ANON_ROLE": "anon",
                "PGRST_JWT_SECRET": self._jwt_secret, "PGRST_JWT_AUD": "authenticated",
                "PGRST_SERVER_HOST": "0.0.0.0", "PGRST_SERVER_PORT": "3000",
                "PGRST_LOG_LEVEL": "crit",
            }, "--publish", "127.0.0.1::3000")
            self._rest_host, self._rest_port = self._published(rest_name, 3000)
            self._wait_http(self._rest_host, self._rest_port, "/")
            self.phase = "ready"
            return self
        except BaseException:
            phase = self.phase
            self.close()
            raise RuntimeError("Local accounts stack failed during " + phase) from None

    def sql(self, query):
        result = self._docker("exec", "-i", self._postgres, "psql", "-X", "-qAt",
                              "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", self._database,
                              input=query)
        return result.stdout.strip()

    @staticmethod
    def _request(url, body=None, token=None, origin=None, key=None):
        parsed = urlsplit(url)
        if parsed.hostname != "127.0.0.1" or parsed.scheme != "http":
            raise ValueError("Only this local loopback HTTP stack is supported")
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=25)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if origin:
            headers["Origin"] = origin
        if key:
            headers["apikey"] = key
        try:
            raw_body = json.dumps(body).encode() if body is not None else None
            connection.request("POST" if body is not None else "GET", parsed.path + ("?" + parsed.query if parsed.query else ""),
                               body=raw_body, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            try:
                payload = json.loads(raw) if raw else {}
            except (ValueError, UnicodeDecodeError):
                payload = raw.decode("utf-8", errors="replace")
            return response.status, payload
        finally:
            connection.close()

    def call(self, path, body=None, token=None):
        return self._request(self.gateway_url + path, body, token, self.gateway_url)

    def direct_rpc(self, name, body, token=None):
        return self._request(self.router_url + "/rest/v1/rpc/" + name, body, token, key=self._anon_key)

    def wait_message(self, recipient, since=0, timeout=20):
        recipient = recipient.lower()
        deadline = time.monotonic() + timeout
        with self._mail_condition:
            while True:
                for message in self.messages[since:]:
                    addresses = getattr(message, "envelope_recipients", ()) or tuple(
                        address.lower() for _, address in getaddresses(message.get_all("To", [])))
                    if recipient in addresses:
                        return message
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Local SMTP message did not arrive")
                self._mail_condition.wait(remaining)

    @staticmethod
    def take_link(message, kind="signup"):
        text = []
        for part in message.walk():
            if part.get_content_type() in ("text/plain", "text/html"):
                try:
                    text.append(part.get_content())
                except (UnicodeDecodeError, LookupError):
                    pass
        for link in re.findall(r"https?://[^\s<>\"']+", html.unescape("\n".join(text))):
            parsed = urlsplit(link)
            if kind == "invite" and "invite_token=" in parsed.fragment:
                return link
            if parse_qs(parsed.query).get("type") == [kind]:
                return link
        raise RuntimeError("Expected local email link was not found")

    def close(self):
        for server in reversed(self._servers):
            try:
                server.shutdown()
                server.server_close()
            except OSError:
                pass
        self._servers.clear()
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads.clear()
        for name in reversed(self._containers):
            try:
                self._docker("rm", "--force", name, check=False)
            except RuntimeError:
                # Continue cleaning the remaining objects after a daemon error.
                pass
        self._containers.clear()
        if self._network_created:
            try:
                self._docker("network", "rm", self._network, check=False)
            except RuntimeError:
                pass
            self._network_created = False
        self.messages.clear()
        self._jwt_secret = self._db_password = self._anon_key = self._service_key = ""
        self.settings = None

    def __exit__(self, *_exc):
        self.close()
        return False

"""Real loopback HTTP/SMTP integration of the gateway; GoTrue is a contract stub.

These tests never contact Supabase or send external mail. Database permission
tests and real GoTrue integration are separate from this protocol fixture.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import shutil
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

SPEC = importlib.util.spec_from_file_location('account_gateway', Path(__file__).resolve().parents[1] / 'server/account_gateway.py')
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)

USER = '10000000-0000-4000-8000-000000000001'
HOUSEHOLD = '20000000-0000-4000-8000-000000000001'
FOREIGN = '20000000-0000-4000-8000-000000000002'
REQUEST = '30000000-0000-4000-8000-000000000001'
JOB = '40000000-0000-4000-8000-000000000001'
LEASE = '50000000-0000-4000-8000-000000000001'
INVITE = '60000000-0000-4000-8000-000000000001'
SESSION = {'access_token': 'valid.jwt.token', 'refresh_token': 'fake-refresh',
           'user': {'id': USER, 'email': 'owner@example.invalid', 'email_confirmed_at': '2026-01-01T00:00:00Z'}}


class ProviderHandler(BaseHTTPRequestHandler):
    """HTTP fixture models only GoTrue/PostgREST request/response contracts."""
    def log_message(self, *_args):
        pass

    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        if status == 302:
            self.send_header('Location', 'https://untrusted.invalid/steal')
        self.end_headers()
        self.wfile.write(body)

    def handle_call(self):
        raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        body = json.loads(raw) if raw else {}
        self.server.calls.append((self.command, self.path, body, dict(self.headers)))
        if self.server.failure:
            return self.reply(self.server.failure, {'error': 'private provider diagnostic owner@example.invalid secret-token'})
        auth = self.headers.get('Authorization')
        if self.path == '/auth/v1/user' and self.command == 'GET':
            return self.reply(200, SESSION['user']) if auth == 'Bearer valid.jwt.token' else self.reply(401, {})
        if self.path.startswith('/auth/v1/signup') or self.path.startswith('/auth/v1/recover') or self.path.startswith('/auth/v1/resend'):
            return self.reply(400 if body['email'].startswith('exists') else 200, {'id': USER})
        if self.path.startswith('/auth/v1/token') or self.path == '/auth/v1/verify':
            if body.get('password') == 'wrong-password':
                return self.reply(400, {'error': 'bad credentials'})
            return self.reply(200, SESSION)
        if self.path == '/auth/v1/user' and self.command == 'PUT':
            return self.reply(200, SESSION['user']) if auth == 'Bearer valid.jwt.token' else self.reply(401, {})
        if self.path == '/auth/v1/logout':
            return self.reply(204, {})
        name = self.path.rsplit('/', 1)[-1]
        if name in ('finance_claim_mail_jobs', 'finance_finish_mail_job'):
            if auth != 'Bearer service-test-only' or self.headers.get('apikey') != 'service-test-only':
                return self.reply(403, {})
            if name == 'finance_claim_mail_jobs':
                return self.reply(200, [dict(self.server.job)] if self.server.job_state in ('pending', 'retry') else [])
            if body['p_lease_id'] != LEASE:
                return self.reply(200, {'status': 'stale'})
            self.server.job_state = 'sent' if body['p_sent'] else 'retry'
            self.server.finishes.append(body)
            return self.reply(200, {'status': self.server.job_state})
        if auth != 'Bearer valid.jwt.token' or self.headers.get('apikey') != 'publishable-test-only':
            return self.reply(401, {})
        if body.get('p_household_id') == FOREIGN:
            return self.reply(403, {})
        if name == 'finance_create_invite':
            self.server.invites.setdefault(body['p_request_id'], dict(body, id=INVITE, mail_status='pending'))
            return self.reply(200, self.server.invites[body['p_request_id']])
        return self.reply(200, {'ok': True, 'rpc': name})

    do_GET = handle_call
    do_POST = handle_call
    do_PUT = handle_call


class SMTPHandler(socketserver.StreamRequestHandler):
    """A real SMTP sink, including optional verified STARTTLS/implicit TLS."""
    def line(self, value):
        self.wfile.write(value + b'\r\n')
        self.wfile.flush()

    def finish(self):
        try:
            super().finish()
        finally:
            if self.connection is not self.request:
                self.connection.close()

    def handle(self):
        self.line(b'220 local test SMTP')
        while True:
            command = self.rfile.readline(16_384)
            if not command:
                return
            verb = command.split(b' ', 1)[0].strip().upper()
            if verb in (b'EHLO', b'HELO'):
                if self.server.tls_context and not self.server.implicit_tls:
                    self.line(b'250-localhost')
                    self.line(b'250 STARTTLS')
                else:
                    self.line(b'250 localhost')
            elif verb == b'STARTTLS' and self.server.tls_context:
                self.line(b'220 Begin TLS')
                self.connection = self.server.tls_context.wrap_socket(self.connection, server_side=True)
                self.rfile = self.connection.makefile('rb')
                self.wfile = self.connection.makefile('wb')
                self.server.tls_connections += 1
            elif verb == b'MAIL':
                self.line(b'250 Sender accepted')
            elif verb == b'RCPT':
                self.line(b'550 Fake temporary refusal' if self.server.refuse else b'250 Recipient accepted')
            elif verb == b'DATA':
                self.line(b'354 Send message')
                data = []
                while True:
                    line = self.rfile.readline(1_048_576)
                    if line == b'.\r\n' or not line:
                        break
                    data.append(line[1:] if line.startswith(b'..') else line)
                self.server.messages.append(b''.join(data))
                self.line(b'250 Accepted by test sink')
            elif verb == b'QUIT':
                if self.server.drop_quit:
                    return
                self.line(b'221 Bye')
                return
            elif verb == b'RSET':
                self.line(b'250 Reset')
            else:
                self.line(b'500 Unsupported')


class SMTPSink(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, tls_context=None, implicit_tls=False):
        self.tls_context, self.implicit_tls = tls_context, implicit_tls
        self.tls_connections, self.messages, self.refuse, self.drop_quit = 0, [], False, False
        super().__init__(('127.0.0.1', 0), SMTPHandler)

    def get_request(self):
        sock, addr = super().get_request()
        if self.implicit_tls:
            sock = self.tls_context.wrap_socket(sock, server_side=True)
            self.tls_connections += 1
        return sock, addr


class AccountGatewayHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = ThreadingHTTPServer(('127.0.0.1', 0), ProviderHandler)
        cls.provider_thread = threading.Thread(target=cls.provider.serve_forever, daemon=True)
        cls.provider_thread.start()
        cls.files = tempfile.TemporaryDirectory()
        for filename in ('index.html', 'ledger-template.html', 'accounts.js'):
            (Path(cls.files.name) / filename).write_text('<html>fake account shell</html>')
        settings = gateway.Settings(supabase_url=f'http://127.0.0.1:{cls.provider.server_port}',
            publishable_key='publishable-test-only', public_origin='http://127.0.0.1:1',
            invite_token_key=b'local-fake-key-only-32bytes-or-more', service_role_key='service-test-only',
            dev_loopback=True, public_dir=Path(cls.files.name))
        cls.http = gateway.GatewayServer(('127.0.0.1', 0), settings)
        cls.base = f'http://127.0.0.1:{cls.http.server_port}'
        cls.settings = replace(settings, public_origin=cls.base)
        cls.http.gateway = gateway.Gateway(cls.settings)
        cls.http_thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.http_thread.start()

    @classmethod
    def tearDownClass(cls):
        for server, thread in ((cls.http, cls.http_thread), (cls.provider, cls.provider_thread)):
            server.shutdown()
            server.server_close()
            thread.join()
        cls.files.cleanup()

    def setUp(self):
        self.provider.failure, self.provider.calls, self.provider.invites = 0, [], {}
        self.provider.finishes, self.provider.job_state = [], 'pending'
        self.http.gateway.limiter = gateway.RateLimiter(self.settings.invite_token_key)
        raw = gateway.invite_token(self.settings.invite_token_key, REQUEST, HOUSEHOLD, 'guest@example.invalid', USER)
        self.provider.job = {'id': JOB, 'lease_id': LEASE, 'invite_id': INVITE,
            'request_id': REQUEST, 'household_id': HOUSEHOLD, 'email': 'guest@example.invalid',
            'role': 'editor', 'created_by': USER, 'household_name': 'Fake family',
            'token_hash': hashlib.sha256(raw.encode()).hexdigest(),
            'lease_until': (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()}

    def call(self, path, body=None, *, origin=True, token=None, headers=None, method=None):
        request_headers = {'Content-Type': 'application/json'}
        if origin:
            request_headers['Origin'] = self.base if origin is True else origin
        if token:
            request_headers['Authorization'] = 'Bearer ' + token
        request_headers.update(headers or {})
        request = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.read(), response.headers
        except HTTPError as exc:
            return exc.code, exc.read(), exc.headers

    def test_config_exposes_only_public_credentials_and_static_boundaries(self):
        status, raw, headers = self.call('/api/config')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['publishableKey'], 'publishable-test-only')
        self.assertNotIn(b'service-test-only', raw)
        self.assertNotIn(self.settings.invite_token_key, raw)
        self.assertNotIn("'unsafe-inline'", headers['Content-Security-Policy'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(self.call('/?token_hash=fake&type=signup')[0], 200)
        for path in ('/.git/config', '/server/account_gateway.py', '/../index.html', '/%2e%2e/index.html'):
            self.assertEqual(self.call(path)[0], 404)
        self.assertIn("script-src 'self' 'unsafe-inline'", self.call('/ledger-template.html')[2]['Content-Security-Policy'])

    def test_csrf_host_content_type_and_size_fail_before_provider(self):
        body = {'email': 'fake@example.invalid', 'password': 'fake-password'}
        self.assertEqual(self.call('/api/auth/signup', body, origin=False)[0], 403)
        self.assertEqual(self.call('/api/auth/signup', body, origin='https://foreign.invalid')[0], 403)
        self.assertEqual(self.call('/api/auth/signup', body, headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.call('/api/auth/signup', body, headers={'Host': 'foreign.invalid'})[0], 421)
        self.assertEqual(self.call('/api/auth/signup', body, headers={'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.call('/api/auth/signup', {'large': 'a' * 17_000})[0], 413)
        self.assertEqual(self.provider.calls, [])

    def test_signup_recovery_resend_are_neutral_and_redirect_fixed(self):
        for action in ('signup', 'recover', 'resend'):
            replies = []
            for email in (' Fake@Example.invalid ', 'exists@example.invalid'):
                body = {'email': email}
                if action == 'signup':
                    body['password'] = 'fake-password'
                status, raw, _ = self.call('/api/auth/' + action, body)
                self.assertEqual(status, 200)
                replies.append(json.loads(raw))
                _, path, sent, headers = self.provider.calls[-1]
                self.assertIn('redirect_to=http%3A%2F%2F127.0.0.1', path)
                self.assertEqual(sent['email'], email.strip().lower())
                self.assertEqual(headers['Apikey'], 'publishable-test-only')
                self.assertNotIn('Authorization', headers)
            self.assertEqual(replies[0], replies[1])
        self.assertEqual(self.call('/api/auth/signup', {'email': 'fake@example.invalid', 'password': 'fake-password',
                                                      'redirect_to': 'https://evil.invalid'})[0], 400)

    def test_auth_sessions_and_gotrue_exact_contract(self):
        status, raw, _ = self.call('/api/auth/login', {'email': 'fake@example.invalid', 'password': 'fake-password'})
        self.assertEqual((status, json.loads(raw)['session']), (200, SESSION))
        self.assertEqual(self.provider.calls[-1][1], '/auth/v1/token?grant_type=password')
        self.assertEqual(self.call('/api/auth/login', {'email': 'fake@example.invalid', 'password': 'wrong-password'})[0], 401)
        self.assertEqual(self.call('/api/auth/confirm', {'token_hash': 'fake-hash', 'type': 'recovery'})[0], 200)
        self.assertEqual(self.provider.calls[-1][1], '/auth/v1/verify')
        self.assertEqual(self.call('/api/auth/confirm', {'code': 'fake-code', 'code_verifier': 'fake-verifier'})[0], 200)
        self.assertEqual(self.provider.calls[-1][2], {'auth_code': 'fake-code', 'code_verifier': 'fake-verifier'})
        self.assertEqual(self.call('/api/auth/confirm', {'code': 'fake-code'})[0], 400)
        self.assertEqual(self.call('/api/auth/refresh', {'refresh_token': 'fake-refresh'})[0], 200)
        self.assertEqual(self.call('/api/auth/reset', {'password': 'new-fake-password'}, token='valid.jwt.token')[0], 200)
        self.assertEqual(self.provider.calls[-1][0:2], ('PUT', '/auth/v1/user'))
        self.assertEqual(self.call('/api/auth/logout', {}, token='valid.jwt.token')[0], 200)

    def test_public_rate_limits_and_provider_failures_are_honest(self):
        for _ in range(8):
            self.assertEqual(self.call('/api/auth/recover', {'email': 'fake@example.invalid'})[0], 200)
        self.assertEqual(self.call('/api/auth/recover', {'email': 'fake@example.invalid'})[0], 429)
        self.assertFalse(any('fake@example.invalid' in key for key in self.http.gateway.limiter.events))
        self.provider.failure = 500
        status, raw, _ = self.call('/api/auth/signup', {'email': 'fake@example.invalid', 'password': 'fake-password'})
        self.assertEqual(status, 502)
        self.assertNotIn(b'secret-token', raw)
        self.provider.failure = 302
        self.assertEqual(self.call('/api/auth/signup', {'email': 'fake@example.invalid', 'password': 'fake-password'})[0], 502)

    def test_rpc_uses_caller_jwt_and_public_key_and_blocks_internal_names(self):
        for name in ('finance_create_invite', 'finance_claim_mail_jobs', 'finance_finish_mail_job', 'sql', '../table'):
            self.assertEqual(self.call('/api/rpc/' + name, {}, token='valid.jwt.token')[0], 404)
        self.assertEqual(self.call('/api/rpc/finance_list_households', {})[0], 401)
        self.assertEqual(self.call('/api/rpc/finance_list_households', {}, token='bad.jwt.token')[0], 401)
        self.assertEqual(self.call('/api/rpc/finance_get_household', {'p_household_id': FOREIGN}, token='valid.jwt.token')[0], 403)
        self.assertEqual(self.call('/api/rpc/finance_list_households', {}, token='valid.jwt.token')[0], 200)
        headers = self.provider.calls[-1][3]
        self.assertEqual(headers['Authorization'], 'Bearer valid.jwt.token')
        self.assertEqual(headers['Apikey'], 'publishable-test-only')

    def test_privileged_tokens_are_rejected_before_user_rpc(self):
        import base64
        secret_jwt = 'header.' + base64.urlsafe_b64encode(b'{"role":"service_role"}').decode().rstrip('=') + '.signature'
        for token in ('service-test-only', 'sb_secret_fake', secret_jwt):
            self.assertEqual(self.call('/api/rpc/finance_list_households', {}, token=token)[0], 401)
        self.assertEqual(self.provider.calls, [])

    def test_invite_uses_authenticated_identity_hash_only_and_idempotent_normalization(self):
        body = {'household_id': HOUSEHOLD, 'request_id': REQUEST, 'email': ' Guest@Example.invalid ', 'role': 'editor'}
        status, first, _ = self.call('/api/invites/create', body, token='valid.jwt.token')
        self.assertEqual(status, 200)
        expected = gateway.invite_token(self.settings.invite_token_key, REQUEST, HOUSEHOLD, 'guest@example.invalid', USER)
        sent = self.provider.calls[-1][2]
        self.assertEqual(sent['p_token_hash'], hashlib.sha256(expected.encode()).hexdigest())
        self.assertNotIn(expected, json.dumps(sent))
        body['email'] = 'guest@example.invalid'
        self.assertEqual(first, self.call('/api/invites/create', body, token='valid.jwt.token')[1])
        self.assertEqual(len(self.provider.invites), 1)
        for injected in ('p_token_hash', 'token_hash', 'created_by', 'user_id'):
            self.assertEqual(self.call('/api/invites/create', dict(body, **{injected: 'attacker'}), token='valid.jwt.token')[0], 400)
        self.assertEqual(self.call('/api/invites/create', dict(body, role='owner'), token='valid.jwt.token')[0], 400)
        self.assertEqual(self.call('/api/invites/create', body, token='bad.jwt.token')[0], 401)
        self.assertEqual(self.call('/api/invites/create', dict(body, household_id=FOREIGN), token='valid.jwt.token')[0], 403)

    def test_smtp_sink_acceptance_retry_and_no_repeat_after_sent(self):
        sink = SMTPSink()
        thread = threading.Thread(target=sink.serve_forever, daemon=True)
        thread.start()
        try:
            settings = replace(self.settings, smtp_host='127.0.0.1', smtp_port=sink.server_address[1],
                               smtp_mode='plain', smtp_from='sender@example.invalid', smtp_plain_loopback_test=True)
            worker = gateway.MailWorker(settings)
            sink.refuse = True
            self.assertEqual(worker.run_once()['retry'], 1)
            self.assertFalse(self.provider.finishes[-1]['p_sent'])
            self.assertEqual(len(sink.messages), 0)
            sink.refuse = False
            sink.drop_quit = True  # DATA accepted remains sent even if QUIT fails.
            self.assertEqual(worker.run_once()['sent'], 1)
            self.assertTrue(self.provider.finishes[-1]['p_sent'])
            self.assertEqual(worker.run_once()['claimed'], 0)
            self.assertEqual(len(sink.messages), 1)
            message = BytesParser(policy=policy.default).parsebytes(sink.messages[0])
            raw = gateway.invite_token(settings.invite_token_key, REQUEST, HOUSEHOLD, 'guest@example.invalid', USER)
            self.assertIn(self.base + '/#invite_token=' + raw, message.get_content())
            self.assertNotIn('?invite', message.get_content())
            self.assertEqual(message['To'], 'guest@example.invalid')
            for _, path, _, headers in self.provider.calls:
                if '/finance_' in path:
                    self.assertEqual(headers['Apikey'], 'service-test-only')
        finally:
            sink.shutdown()
            sink.server_close()
            thread.join()

    def test_worker_rejects_hash_injection_and_tls_downgrade(self):
        sink = SMTPSink()
        thread = threading.Thread(target=sink.serve_forever, daemon=True)
        thread.start()
        try:
            settings = replace(self.settings, smtp_host='127.0.0.1', smtp_port=sink.server_address[1],
                               smtp_from='sender@example.invalid')
            self.assertEqual(gateway.MailWorker(settings).run_once()['retry'], 1)
            self.assertEqual(sink.messages, [])  # STARTTLS was mandatory; no downgrade.
            self.provider.job['token_hash'] = '0' * 64
            plain = replace(settings, smtp_mode='plain', smtp_plain_loopback_test=True)
            self.assertEqual(gateway.MailWorker(plain).run_once()['retry'], 1)
            self.assertEqual(self.provider.finishes[-1]['p_error_code'], 'invalid_job')
            self.assertEqual(sink.messages, [])
            self.provider.job['lease_until'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            self.assertEqual(gateway.MailWorker(plain).run_once()['retry'], 1)
            self.assertEqual(sink.messages, [])
            with self.assertRaises(ValueError):
                gateway.MailWorker(replace(plain, smtp_host='smtp.example.invalid'))
            with self.assertRaises(ValueError):
                gateway.MailWorker(replace(plain, smtp_plain_loopback_test=False))
        finally:
            sink.shutdown()
            sink.server_close()
            thread.join()

    def test_smtp_absolute_deadline_stops_slow_multiline_peer(self):
        class SlowSMTP(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    for _ in range(100):
                        self.wfile.write(b'220-keep waiting\r\n')
                        self.wfile.flush()
                        time.sleep(0.02)
                except OSError:
                    pass
        sink = socketserver.ThreadingTCPServer(('127.0.0.1', 0), SlowSMTP)
        sink.daemon_threads = True
        thread = threading.Thread(target=sink.serve_forever, daemon=True)
        thread.start()
        try:
            started = time.monotonic()
            with self.assertRaises((TimeoutError, OSError)):
                gateway.DeadlineSMTP('127.0.0.1', sink.server_address[1], timeout=1, total_timeout=0.1)
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            sink.shutdown()
            sink.server_close()
            thread.join()

    @unittest.skipUnless(shutil.which('openssl'), 'openssl is needed to issue a local test certificate')
    def test_real_verified_starttls_and_ssl_smtp(self):
        with tempfile.TemporaryDirectory() as temp:
            cert, key = Path(temp) / 'cert.pem', Path(temp) / 'key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                            '-keyout', str(key), '-out', str(cert), '-subj', '/CN=localhost',
                            '-addext', 'subjectAltName=IP:127.0.0.1,DNS:localhost'],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.load_cert_chain(cert, key)
            trusted_client = ssl.create_default_context(cafile=str(cert))
            self.assertEqual(trusted_client.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(trusted_client.check_hostname)
            for mode in ('starttls', 'ssl'):
                with self.subTest(mode=mode):
                    self.provider.job_state = 'pending'
                    sink = SMTPSink(server_context, implicit_tls=mode == 'ssl')
                    thread = threading.Thread(target=sink.serve_forever, daemon=True)
                    thread.start()
                    try:
                        settings = replace(self.settings, smtp_host='127.0.0.1', smtp_port=sink.server_address[1],
                                           smtp_mode=mode, smtp_from='sender@example.invalid')
                        worker = gateway.MailWorker(settings)
                        with patch.object(gateway.ssl, 'create_default_context', return_value=trusted_client):
                            self.assertEqual(worker.run_once()['sent'], 1)
                        self.assertEqual(len(sink.messages), 1)
                        self.assertEqual(sink.tls_connections, 1)
                    finally:
                        sink.shutdown()
                        sink.server_close()
                        thread.join()


class RuntimeConfiguration(unittest.TestCase):
    def test_https_required_except_explicit_loopback(self):
        for value in ('http://example.invalid', 'https://app.invalid/path', 'https://user:pass@app.invalid',
                      'https://app.invalid/?redirect=evil', 'https://app.invalid/#token'):
            with self.assertRaises(ValueError):
                gateway.origin(value, dev=True)
        self.assertEqual(gateway.origin('http://127.0.0.1:8787/', dev=True), 'http://127.0.0.1:8787')
        with self.assertRaises(ValueError):
            gateway.origin('http://127.0.0.1:8787')

    def test_private_credentials_never_valid_public_config(self):
        import base64
        secret_jwt = 'header.' + base64.urlsafe_b64encode(b'{"role":"service_role"}').decode().rstrip('=') + '.signature'
        for public_key in ('sb_secret_fake', secret_jwt):
            with self.assertRaises(ValueError):
                gateway.Settings(supabase_url='https://stage.example.invalid', publishable_key=public_key,
                                 public_origin='https://app.example.invalid', invite_token_key=b'x' * 32)


if __name__ == '__main__':
    unittest.main()

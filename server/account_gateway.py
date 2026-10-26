#!/usr/bin/env python3
"""Same-origin account API and leased invitation SMTP worker (Python stdlib).

User requests always use the publishable key and the caller's access token.
The service credential is used exclusively by the two mail worker RPCs.
"""
from __future__ import annotations

import argparse
import base64
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import smtplib
import socket
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
import uuid

ROOT = Path(__file__).resolve().parents[1]
RPC_ALLOWLIST = frozenset({
    'finance_list_households', 'finance_create_household', 'finance_get_household',
    'finance_update_settings', 'finance_list_members', 'finance_set_member_role',
    'finance_remove_member', 'finance_list_invites', 'finance_accept_invite',
    'finance_revoke_invite', 'finance_read_state', 'finance_state_cas',
})
NEUTRAL_MESSAGE = 'Если адрес доступен, письмо будет отправлено.'
SMTP_TOTAL_TIMEOUT = 60.0
EMAIL_RE = re.compile(r'^[^\s@\x00-\x1f<>(),;:\\"]+@[^\s@\x00-\x1f<>(),;:\\"]+\.[^\s@\x00-\x1f<>(),;:\\"]+$')


def loopback(host: str | None) -> bool:
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host or '').is_loopback
    except ValueError:
        return False


def origin(value: str, *, dev: bool = False) -> str:
    parsed = urlsplit(value)
    try:
        parsed.port
    except ValueError:
        raise ValueError('Origin has an invalid port') from None
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query
            or parsed.fragment or parsed.path not in ('', '/')
            or parsed.scheme not in ('http', 'https') or any(c.isspace() for c in value)):
        raise ValueError('Origin must be an absolute origin without a path or credentials')
    if parsed.scheme != 'https' and not (dev and loopback(parsed.hostname)):
        raise ValueError('HTTPS is required (HTTP is allowed only for explicit loopback development)')
    return value.rstrip('/')


def normalize_email(value: object) -> str:
    if not isinstance(value, str):
        raise ApiError(400, 'invalid_input', 'Укажите корректный адрес почты.')
    value = value.strip().lower()
    if len(value) > 254 or not EMAIL_RE.fullmatch(value):
        raise ApiError(400, 'invalid_input', 'Укажите корректный адрес почты.')
    return value


def canonical_uuid(value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ApiError(400, 'invalid_input', 'Некорректный идентификатор.') from None


def token_role(value: str) -> object:
    """Read only to reject privileged tokens; provider still verifies all JWTs."""
    try:
        payload = value.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        return claims.get('role') if isinstance(claims, dict) else None
    except (IndexError, ValueError, UnicodeDecodeError):
        return None


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    publishable_key: str = field(repr=False)
    public_origin: str
    invite_token_key: bytes = field(repr=False)
    service_role_key: str = field(default='', repr=False)
    dev_loopback: bool = False
    upstream_timeout: float = 10
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_mode: str = 'starttls'
    smtp_user: str = field(default='', repr=False)
    smtp_password: str = field(default='', repr=False)
    smtp_from: str = ''
    smtp_plain_loopback_test: bool = False
    public_dir: Path = field(default=ROOT / 'public')

    def __post_init__(self) -> None:
        object.__setattr__(self, 'supabase_url', origin(self.supabase_url, dev=self.dev_loopback))
        object.__setattr__(self, 'public_origin', origin(self.public_origin, dev=self.dev_loopback))
        if not self.publishable_key or self.publishable_key.startswith('sb_secret_'):
            raise ValueError('A publishable/anon key is required')
        # Prevent accidental exposure of a legacy service-role JWT in /api/config.
        if token_role(self.publishable_key) == 'service_role' or self.publishable_key == self.service_role_key:
            raise ValueError('The public key must not be a service credential')
        if len(self.invite_token_key) < 32:
            raise ValueError('The stable invitation HMAC key must contain at least 32 random bytes')
        if not 0 < self.upstream_timeout <= 30:
            raise ValueError('Upstream timeout must be between 0 and 30 seconds')

    @classmethod
    def from_env(cls) -> 'Settings':
        try:
            token_key = base64.b64decode(os.environ.get('INVITE_TOKEN_KEY_BASE64', ''), validate=True)
            return cls(
                supabase_url=os.environ.get('SUPABASE_URL', ''),
                publishable_key=os.environ.get('SUPABASE_PUBLISHABLE_KEY', ''),
                public_origin=os.environ.get('PUBLIC_ORIGIN', ''),
                invite_token_key=token_key,
                service_role_key=os.environ.get('SUPABASE_SERVICE_ROLE_KEY', ''),
                dev_loopback=os.environ.get('ACCOUNT_DEV_LOOPBACK') == '1',
                smtp_host=os.environ.get('SMTP_HOST', ''),
                smtp_port=int(os.environ.get('SMTP_PORT', '587')),
                smtp_mode=os.environ.get('SMTP_MODE', 'starttls'),
                smtp_user=os.environ.get('SMTP_USER', ''),
                smtp_password=os.environ.get('SMTP_PASSWORD', ''),
                smtp_from=os.environ.get('SMTP_FROM', ''),
                smtp_plain_loopback_test=os.environ.get('SMTP_PLAIN_LOOPBACK_TEST') == '1',
            )
        except (ValueError, TypeError) as exc:
            # Do not include environment values in a configuration error.
            raise ValueError('Invalid account gateway runtime configuration') from exc


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Upstream:
    def __init__(self, settings: Settings):
        self.settings = settings
        # urllib preserves inherited proxy settings and Python's CA trust.
        self.opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))

    def request(self, method: str, path: str, body: dict | None = None,
                *, token: str | None = None, worker: bool = False) -> tuple[int, object]:
        key = self.settings.service_role_key if worker else self.settings.publishable_key
        if not key:
            raise ApiError(503, 'not_configured', 'Сервис временно недоступен.')
        headers = {'apikey': key, 'Accept': 'application/json', 'Content-Type': 'application/json'}
        if worker or token:
            headers['Authorization'] = 'Bearer ' + (key if worker else token)
        data = json.dumps(body, separators=(',', ':'), ensure_ascii=False).encode() if body is not None else None
        req = Request(self.settings.supabase_url + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=self.settings.upstream_timeout) as response:
                status, raw = response.status, response.read(2_097_153)
        except HTTPError as exc:
            status, raw = exc.code, exc.read(2_097_153)
        except (URLError, TimeoutError, OSError):
            raise ApiError(502, 'upstream_unavailable', 'Сервис временно недоступен. Повторите позже.') from None
        if len(raw) > 2_097_152 or 300 <= status < 400 or status >= 500:
            raise ApiError(502, 'upstream_unavailable', 'Сервис временно недоступен. Повторите позже.')
        try:
            result = json.loads(raw) if raw else {}
        except (ValueError, UnicodeDecodeError):
            raise ApiError(502, 'invalid_upstream', 'Сервис временно недоступен.') from None
        return status, result

    def rpc(self, name: str, body: dict, *, token: str | None = None, worker: bool = False) -> object:
        status, result = self.request('POST', '/rest/v1/rpc/' + name, body, token=token, worker=worker)
        check_upstream(status)
        return result


def check_upstream(status: int) -> None:
    if 200 <= status < 300:
        return
    if status == 429:
        raise ApiError(429, 'rate_limited', 'Слишком много запросов. Повторите позже.')
    if status == 401:
        raise ApiError(401, 'invalid_session', 'Войдите в аккаунт ещё раз.')
    if status == 403:
        raise ApiError(403, 'forbidden', 'Недостаточно прав для этого действия.')
    raise ApiError(400 if status < 500 else 502, 'request_rejected', 'Не удалось выполнить действие. Проверьте данные.')


def invite_token(key: bytes, request_id: str, household_id: str, email: str, created_by: str) -> str:
    """Stable 256-bit token; database and jobs persist only SHA256(token UTF8)."""
    payload = json.dumps([canonical_uuid(request_id), canonical_uuid(household_id),
                          normalize_email(email), canonical_uuid(created_by)], separators=(',', ':')).encode()
    return hmac.new(key, b'finance-invite-v1\x00' + payload, hashlib.sha256).hexdigest()


class RateLimiter:
    def __init__(self, key: bytes, *, limit: int = 8, period: int = 900):
        self.key, self.limit, self.period = key, limit, period
        self.events: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, ip: str, action: str, email: str = '') -> None:
        # Only a keyed digest is retained, never email addresses or access tokens.
        keys = [action + ':' + ip]
        if email:
            keys.append(action + ':email:' + hmac.new(self.key, email.encode(), hashlib.sha256).hexdigest())
        now = time.monotonic()
        with self.lock:
            # Bound memory for unauthenticated hostile input.
            if len(self.events) > 20_000:
                self.events = defaultdict(deque, {k: v for k, v in self.events.items()
                                                  if v and v[-1] > now - self.period})
                if len(self.events) > 20_000:
                    raise ApiError(429, 'rate_limited', 'Слишком много запросов. Повторите позже.')
            for key in keys:
                while self.events[key] and self.events[key][0] <= now - self.period:
                    self.events[key].popleft()
                if len(self.events[key]) >= self.limit:
                    raise ApiError(429, 'rate_limited', 'Слишком много запросов. Повторите позже.')
            for key in keys:
                self.events[key].append(now)


def fields(body: dict, required: set[str], optional: set[str] = frozenset()) -> None:
    if not required <= body.keys() or body.keys() - (required | optional):
        raise ApiError(400, 'invalid_input', 'Некорректные параметры запроса.')


def password(body: dict) -> str:
    value = body.get('password')
    if not isinstance(value, str) or not 8 <= len(value) <= 1024:
        raise ApiError(400, 'invalid_input', 'Пароль должен содержать от 8 до 1024 символов.')
    return value


class Gateway:
    def __init__(self, settings: Settings):
        self.settings, self.upstream = settings, Upstream(settings)
        self.limiter = RateLimiter(settings.invite_token_key)

    def post(self, path: str, body: dict, token: str | None, client_ip: str) -> object:
        if token and (token == self.settings.service_role_key or token_role(token) == 'service_role'
                      or token.startswith('sb_secret_')):
            raise ApiError(401, 'invalid_session', 'Для входа требуется пользовательская сессия.')
        if path.startswith('/api/auth/'):
            return self.auth(path.rsplit('/', 1)[1], body, token, client_ip)
        if not token:
            raise ApiError(401, 'invalid_session', 'Войдите в аккаунт.')
        if path == '/api/invites/create':
            fields(body, {'household_id', 'email', 'role', 'request_id'})
            email = normalize_email(body['email'])
            if body['role'] not in ('editor', 'viewer'):
                raise ApiError(400, 'invalid_input', 'Выберите роль участника.')
            household, request_id = canonical_uuid(body['household_id']), canonical_uuid(body['request_id'])
            status, user = self.upstream.request('GET', '/auth/v1/user', token=token)
            check_upstream(status)
            if not isinstance(user, dict) or not user.get('email_confirmed_at'):
                raise ApiError(403, 'email_unconfirmed', 'Сначала подтвердите адрес почты.')
            uid = canonical_uuid(user.get('id'))
            raw = invite_token(self.settings.invite_token_key, request_id, household, email, uid)
            return self.upstream.rpc('finance_create_invite', {
                'p_household_id': household, 'p_email': email, 'p_role': body['role'],
                'p_request_id': request_id, 'p_token_hash': hashlib.sha256(raw.encode()).hexdigest(),
            }, token=token)
        name = path.removeprefix('/api/rpc/') if path.startswith('/api/rpc/') else ''
        if name not in RPC_ALLOWLIST:
            raise ApiError(404, 'not_found', 'Адрес не найден.')
        return self.upstream.rpc(name, body, token=token)

    def auth(self, action: str, body: dict, token: str | None, ip: str) -> object:
        redirect = '?' + urlencode({'redirect_to': self.settings.public_origin + '/'})
        if action in ('signup', 'recover', 'resend', 'login'):
            required = {'email', 'password'} if action in ('signup', 'login') else {'email'}
            fields(body, required, {'type'} if action == 'resend' else set())
            email = normalize_email(body['email'])
            self.limiter.check(ip, action, email)
            payload = {'email': email}
            if action in ('signup', 'login'):
                payload['password'] = password(body)
            if action == 'resend':
                if body.get('type', 'signup') != 'signup':
                    raise ApiError(400, 'invalid_input', 'Некорректный тип письма.')
                payload['type'] = 'signup'
            suffix = '/token?grant_type=password' if action == 'login' else '/' + action + redirect
            status, result = self.upstream.request('POST', '/auth/v1' + suffix, payload)
            if action == 'login':
                if status in (400, 401, 422):
                    raise ApiError(401, 'invalid_credentials', 'Не удалось войти. Проверьте почту, пароль и подтверждение адреса.')
                check_upstream(status)
                return {'session': self.session(result)}
            # Account existence and confirmation state never change the response.
            if status in (200, 201, 202, 204, 400, 401, 403, 404, 409, 422):
                return {'message': NEUTRAL_MESSAGE}
            check_upstream(status)
            return {'message': NEUTRAL_MESSAGE}
        if action == 'confirm':
            self.limiter.check(ip, action)
            if 'code' in body:
                fields(body, {'code', 'code_verifier'})
                if not all(isinstance(body[x], str) and 1 <= len(body[x]) <= 2048 for x in body):
                    raise ApiError(400, 'invalid_input', 'Некорректная ссылка подтверждения.')
                status, result = self.upstream.request('POST', '/auth/v1/token?grant_type=pkce', {
                    'auth_code': body['code'], 'code_verifier': body['code_verifier']})
            else:
                fields(body, {'token_hash', 'type'})
                if (body['type'] not in ('signup', 'recovery', 'email', 'invite', 'email_change')
                        or not isinstance(body['token_hash'], str) or not 1 <= len(body['token_hash']) <= 2048):
                    raise ApiError(400, 'invalid_input', 'Некорректная ссылка подтверждения.')
                status, result = self.upstream.request('POST', '/auth/v1/verify', body)
            check_upstream(status)
            return {'session': self.session(result)}
        if action == 'refresh':
            fields(body, {'refresh_token'})
            if not isinstance(body['refresh_token'], str) or not 1 <= len(body['refresh_token']) <= 8192:
                raise ApiError(400, 'invalid_input', 'Некорректная сессия.')
            status, result = self.upstream.request('POST', '/auth/v1/token?grant_type=refresh_token', body)
            check_upstream(status)
            return {'session': self.session(result)}
        if action in ('reset', 'logout'):
            if not token:
                raise ApiError(401, 'invalid_session', 'Войдите в аккаунт.')
            fields(body, {'password'} if action == 'reset' else set())
            status, result = self.upstream.request(
                'PUT' if action == 'reset' else 'POST', '/auth/v1/user' if action == 'reset' else '/auth/v1/logout',
                {'password': password(body)} if action == 'reset' else {}, token=token)
            check_upstream(status)
            return {'user': result} if action == 'reset' else {'ok': True}
        raise ApiError(404, 'not_found', 'Адрес не найден.')

    @staticmethod
    def session(result: object) -> dict:
        if not isinstance(result, dict) or not result.get('access_token') or not result.get('refresh_token'):
            raise ApiError(502, 'invalid_upstream', 'Сервис не вернул подтверждённую сессию.')
        return result


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address: tuple[str, int], settings: Settings):
        self.gateway = Gateway(settings)
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(address, GatewayHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # Tracebacks from HTTP parsing or sockets can include sensitive data.
        pass


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = 'FinanceGateway/1'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(12)

    def log_message(self, *_args):
        # Request lines can contain tokens; even errors do not print them.
        pass

    def send_error(self, code, message=None, explain=None):
        self.respond(code, {'error': {'code': 'invalid_request', 'message': 'Некорректный запрос.'}})

    def respond(self, status: int, payload: object, *, head: bool = False,
                content_type: str = 'application/json; charset=utf-8', ledger: bool = False):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy',
            "default-src 'self'; script-src 'self'" + (" 'unsafe-inline'" if ledger else '')
            + "; style-src 'self'" + (" 'unsafe-inline'" if ledger else '')
            + "; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; frame-src 'self'; "
            + ("frame-ancestors 'self'; " if ledger else "frame-ancestors 'none'; ")
            + "form-action 'self'; base-uri 'none'; object-src 'none'")
        self.send_header('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        if self.server.gateway.settings.public_origin.startswith('https:'):
            self.send_header('Strict-Transport-Security', 'max-age=31536000')
        if status == 429:
            self.send_header('Retry-After', '900')
        self.end_headers()
        if not head:
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def validate_host(self):
        configured = urlsplit(self.server.gateway.settings.public_origin).netloc
        if len(self.headers.get_all('Host', [])) != 1 or self.headers.get('Host') != configured:
            raise ApiError(421, 'invalid_host', 'Некорректный адрес сервера.')

    def get(self, head=False):
        try:
            self.validate_host()
            parsed = urlsplit(self.path)
            if parsed.fragment or (parsed.query and parsed.path != '/'):
                raise ApiError(400, 'invalid_request', 'Некорректный адрес запроса.')
            if parsed.path == '/api/config':
                s = self.server.gateway.settings
                return self.respond(200, {'enabled': True, 'supabaseUrl': s.supabase_url,
                    'publishableKey': s.publishable_key, 'publicOrigin': s.public_origin,
                    'appName': 'Семейные финансы', 'ledgerUrl': '/'}, head=head)
            filename = 'index.html' if parsed.path == '/' else parsed.path.removeprefix('/')
            if ('/' in filename or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*\.(?:html|js|css|svg|png|ico)', filename)):
                raise ApiError(404, 'not_found', 'Адрес не найден.')
            root = self.server.gateway.settings.public_dir.resolve()
            file = (root / filename).resolve()
            if file.parent != root or not file.is_file():
                raise ApiError(404, 'not_found', 'Адрес не найден.')
            return self.respond(200, file.read_bytes(), head=head,
                                content_type=(mimetypes.guess_type(filename)[0] or 'application/octet-stream') + '; charset=utf-8',
                                ledger=filename == 'ledger-template.html')
        except ApiError as exc:
            self.respond(exc.status, {'error': {'code': exc.code, 'message': exc.message}}, head=head)

    def do_GET(self):
        self.get()

    def do_HEAD(self):
        self.get(head=True)

    def do_POST(self):
        try:
            self.validate_host()
            if (len(self.headers.get_all('Origin', [])) != 1
                    or self.headers.get('Origin') != self.server.gateway.settings.public_origin):
                raise ApiError(403, 'invalid_origin', 'Запрос должен исходить из приложения.')
            if self.headers.get('Sec-Fetch-Site') not in (None, 'same-origin', 'none'):
                raise ApiError(403, 'invalid_origin', 'Запрос должен исходить из приложения.')
            parsed = urlsplit(self.path)
            if parsed.query or parsed.fragment:
                raise ApiError(400, 'invalid_request', 'Некорректный адрес запроса.')
            if self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
                raise ApiError(415, 'invalid_content_type', 'Требуется JSON.')
            try:
                if len(self.headers.get_all('Content-Length', [])) != 1:
                    raise ValueError
                length = int(self.headers.get('Content-Length', ''))
            except ValueError:
                raise ApiError(411, 'length_required', 'Укажите размер запроса.') from None
            limit = 1_048_576 if parsed.path == '/api/rpc/finance_state_cas' else 16_384
            if not 0 < length <= limit:
                raise ApiError(413, 'body_too_large', 'Превышен размер запроса.')
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ApiError(400, 'invalid_json', 'Некорректный JSON.')
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                raise ApiError(400, 'invalid_json', 'Некорректный JSON.') from None
            if not isinstance(body, dict):
                raise ApiError(400, 'invalid_json', 'Ожидается объект JSON.')
            authorization = self.headers.get('Authorization', '')
            token = None
            if authorization:
                if (len(self.headers.get_all('Authorization', [])) != 1
                        or not re.fullmatch(r'Bearer [A-Za-z0-9._~-]{1,8192}', authorization)):
                    raise ApiError(401, 'invalid_session', 'Некорректная сессия.')
                token = authorization[7:]
            result = self.server.gateway.post(parsed.path, body, token, self.client_address[0])
            self.respond(200, result)
        except ApiError as exc:
            self.close_connection = True
            self.respond(exc.status, {'error': {'code': exc.code, 'message': exc.message}})
        except (TimeoutError, socket.timeout):
            self.close_connection = True
            self.respond(408, {'error': {'code': 'timeout', 'message': 'Время ожидания истекло.'}})
        except Exception:
            self.close_connection = True
            self.respond(500, {'error': {'code': 'internal_error', 'message': 'Не удалось выполнить действие.'}})

    def do_OPTIONS(self):
        self.respond(405, {'error': {'code': 'method_not_allowed', 'message': 'Метод не поддерживается.'}})

    do_PUT = do_OPTIONS
    do_DELETE = do_OPTIONS
    do_PATCH = do_OPTIONS


class DeadlineSMTPMixin:
    """An absolute SMTP budget, including slow multiline replies and TLS.

    Socket timeouts alone reset on each successful read. Reading bounded SMTP
    reply bytes with the remaining budget prevents a slow peer extending a
    fixed database claim lease indefinitely.
    """
    def __init__(self, *args, total_timeout=SMTP_TOTAL_TIMEOUT, **kwargs):
        self.deadline = time.monotonic() + total_timeout
        super().__init__(*args, **kwargs)

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('SMTP overall deadline exceeded')
        return min(self.timeout, remaining)

    def send(self, value):
        if self.sock is not None:
            self.sock.settimeout(self.remaining())
        return super().send(value)

    def getreply(self):
        parts, total = [], 0
        try:
            while True:
                line = bytearray()
                while not line.endswith(b'\n'):
                    self.sock.settimeout(self.remaining())
                    byte = self.sock.recv(1)
                    if not byte:
                        raise smtplib.SMTPServerDisconnected('SMTP connection closed')
                    line.extend(byte)
                    total += 1
                    if len(line) > 8192 or total > 65_536:
                        raise smtplib.SMTPResponseException(500, b'SMTP reply too long')
                parts.append(bytes(line[4:]).strip(b' \t\r\n'))
                try:
                    code = int(line[:3])
                except ValueError:
                    code = -1
                if line[3:4] != b'-':
                    return code, b'\n'.join(parts)
        except (OSError, smtplib.SMTPException):
            self.close()
            raise


class DeadlineSMTP(DeadlineSMTPMixin, smtplib.SMTP):
    def starttls(self, *, context=None):
        self.ehlo_or_helo_if_needed()
        if not self.has_extn('starttls'):
            raise smtplib.SMTPNotSupportedError('STARTTLS is required')
        code, reply = self.docmd('STARTTLS')
        if code != 220:
            raise smtplib.SMTPResponseException(code, reply)
        self.sock.settimeout(self.remaining())
        self.sock = (context or ssl.create_default_context()).wrap_socket(self.sock, server_hostname=self._host)
        self.file = None
        self.helo_resp = self.ehlo_resp = None
        self.esmtp_features = {}
        self.does_esmtp = False
        return code, reply


class DeadlineSMTPSSL(DeadlineSMTPMixin, smtplib.SMTP_SSL):
    def _get_socket(self, host, port, timeout):
        sock = socket.create_connection((host, port), min(timeout, self.remaining()), self.source_address)
        try:
            sock.settimeout(self.remaining())
            return self.context.wrap_socket(sock, server_hostname=self._host)
        except BaseException:
            sock.close()
            raise


class MailWorker:
    def __init__(self, settings: Settings):
        self.settings, self.upstream = settings, Upstream(settings)
        self.worker_id = str(uuid.uuid4())
        if not settings.service_role_key or not settings.smtp_host or not settings.smtp_from:
            raise ValueError('Mail worker requires service credential, SMTP host, and SMTP sender')
        normalize_email(settings.smtp_from)
        if settings.smtp_mode not in ('ssl', 'starttls', 'plain'):
            raise ValueError('SMTP_MODE must be ssl or starttls (plain requires explicit loopback test mode)')
        if settings.smtp_mode == 'plain' and not (settings.dev_loopback and settings.smtp_plain_loopback_test
                                                  and loopback(settings.smtp_host)):
            raise ValueError('Unencrypted SMTP is permitted only for explicit loopback tests')
        if bool(settings.smtp_user) != bool(settings.smtp_password):
            raise ValueError('SMTP username and password must be configured together')

    def message(self, job: dict) -> EmailMessage:
        raw = invite_token(self.settings.invite_token_key, job['request_id'], job['household_id'],
                           job['email'], job['created_by'])
        expected = hashlib.sha256(raw.encode()).hexdigest()
        if not isinstance(job.get('token_hash'), str) or not hmac.compare_digest(expected, job['token_hash']):
            raise ValueError('token_hash_mismatch')
        message = EmailMessage()
        message['From'] = self.settings.smtp_from
        message['To'] = normalize_email(job['email'])
        message['Subject'] = 'Приглашение в семейные финансы'
        message['Message-ID'] = '<finance-invite-' + canonical_uuid(job['id']) + '@' + urlsplit(self.settings.public_origin).hostname + '>'
        name = str(job.get('household_name', 'Семья'))[:200]
        message.set_content('Вас пригласили в семью «' + name + '».\n\n'
                            + 'Войдите с этим адресом почты и откройте ссылку:\n'
                            + self.settings.public_origin + '/#invite_token=' + raw
                            + '\n\nСрок действия приглашения ограничен. Если вы не ожидали письмо, его можно проигнорировать.\n')
        return message

    def send(self, message: EmailMessage, *, budget: float = SMTP_TOTAL_TIMEOUT) -> None:
        s = self.settings
        context = ssl.create_default_context()
        timeout = min(s.upstream_timeout, budget)
        client = (DeadlineSMTPSSL(s.smtp_host, s.smtp_port, timeout=timeout,
                                 total_timeout=budget, context=context)
                  if s.smtp_mode == 'ssl' else DeadlineSMTP(s.smtp_host, s.smtp_port,
                                                          timeout=timeout, total_timeout=budget))
        try:
            client.ehlo()
            if s.smtp_mode == 'starttls':
                client.starttls(context=context)
                client.ehlo()
            if s.smtp_user:
                client.login(s.smtp_user, s.smtp_password)
            refused = client.send_message(message)
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)
        finally:
            # A failed QUIT must not relabel an already accepted DATA transaction
            # as unsent. Acceptance is send_message's successful SMTP response.
            try:
                client.quit()
            except (smtplib.SMTPException, OSError):
                client.close()

    def run_once(self) -> dict:
        # Claim just one lease: SMTP on another job must not consume its 120s
        # lease before this process reaches it. Run multiple worker processes
        # or invoke repeatedly for throughput; SQL SKIP LOCKED isolates claims.
        jobs = self.upstream.rpc('finance_claim_mail_jobs', {'p_worker_id': self.worker_id,
                                 'p_limit': 1}, worker=True)
        if not isinstance(jobs, list):
            raise ApiError(502, 'invalid_upstream', 'Invalid mail claim result')
        counts = {'claimed': len(jobs), 'sent': 0, 'retry': 0, 'failed': 0, 'stale': 0}
        for job in jobs:
            sent, error = False, None
            try:
                # New SQL includes the authoritative expiry. An absent field is
                # rejected rather than sending under an unknown claim lease.
                lease_until = datetime.fromisoformat(job['lease_until'].replace('Z', '+00:00'))
                budget = min(SMTP_TOTAL_TIMEOUT,
                             (lease_until - datetime.now(timezone.utc)).total_seconds() - 10)
                if budget <= 0:
                    raise ValueError('lease_expired')
                self.send(self.message(job), budget=budget)
                sent = True
            except (ValueError, KeyError, TypeError):
                error = 'invalid_job'
            except smtplib.SMTPRecipientsRefused:
                error = 'recipient_refused'
            except smtplib.SMTPAuthenticationError:
                error = 'smtp_authentication'
            except (smtplib.SMTPException, OSError, TimeoutError):
                error = 'smtp_unavailable'
            result = self.upstream.rpc('finance_finish_mail_job', {
                'p_job_id': job['id'], 'p_lease_id': job['lease_id'],
                'p_sent': sent, 'p_error_code': error,
            }, worker=True)
            status = result.get('status') if isinstance(result, dict) else None
            if status not in ('sent', 'retry', 'failed', 'stale'):
                raise ApiError(502, 'invalid_upstream', 'Invalid mail finish result')
            counts[status] += 1
        return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--worker-once', action='store_true', help='claim/send one batch, reporting counts only')
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
        if args.worker_once:
            print(json.dumps(MailWorker(settings).run_once()))
            return 0
        server = GatewayServer((args.host, args.port), settings)
    except (ValueError, ApiError, OSError):
        print('Account gateway configuration/startup failed; verify protected runtime settings.')
        return 1
    print('Account gateway started; request logging is disabled.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

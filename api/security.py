"""Accounts, sign-in sessions, CSRF, rate limits and HTTP hardening for Radar when it is reachable over a network.

Design:
- Passwords: scrypt (standard library), per-user salt, constant-time comparison.
- Sessions: a random cookie value (HttpOnly, SameSite=Lax, Secure on HTTPS); the database stores only its SHA-256.
- CSRF: every POST/PUT/PATCH/DELETE needs the X-CSRF-Token header to equal the session's server-side token, and
  the middleware rejects cross-site Origin / Sec-Fetch-Site on unsafe methods.
- The n8n result callbacks (strategy plans, social content) are the only unauthenticated writes; they keep their own token
  check (callback_allowed in api/routers/strategy.py).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from db.database import AuthSession, User, get_db

SESSION_COOKIE = 'radar_session'
CSRF_COOKIE = 'radar_csrf'
CSRF_HEADER = 'x-csrf-token'
SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}
USERNAME = re.compile(r'^[a-z0-9][a-z0-9._@-]{2,63}$')
ROLES = {'admin', 'member', 'viewer', 'client'}
# A client login (M0 Watch) sees only the Watch section; the watch router decides which writes it may make.
CLIENT_AREA = '/watch'
PENDING = 'pending'   # signed up, waiting for an admin to choose a role; cannot sign in


def signup_mode() -> str:
    """SIGNUP_MODE: approval (default: an admin approves each new account), viewer (new accounts can view at once), off."""
    mode = os.getenv('SIGNUP_MODE', 'approval').strip().lower()
    return mode if mode in {'approval', 'viewer', 'off'} else 'approval'
# A viewer only reads. These are the only writes a viewer may make (their own session and password).
VIEWER_WRITES = {'/auth/logout', '/auth/password'}


def _hours(name, default):
    try:
        return max(1, float(os.getenv(name, default)))
    except ValueError:
        return float(default)


SESSION_IDLE = timedelta(hours=_hours('SESSION_IDLE_HOURS', 12))
SESSION_MAX = timedelta(hours=_hours('SESSION_MAX_HOURS', 24 * 7))
MAX_BODY_BYTES = int(os.getenv('MAX_REQUEST_BYTES', str(1024 * 1024)))

# ---- Passwords -------------------------------------------------------------------------

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
COMMON = {'password', 'password1', 'password123', '12345678', '123456789', '1234567890', 'qwertyuiop', 'iloveyou1',
          'odynza123', 'radar12345', 'admin12345', 'letmein123', 'welcome123', '1q2w3e4r5t', 'qwerty1234'}


def _scrypt(password: str, salt: bytes, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P) -> bytes:
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=n, r=r, p=p, maxmem=128 * 1024 * 1024, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt)
    b64 = lambda b: base64.b64encode(b).decode('ascii')
    return f'scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(digest)}'


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.split('$')
        if kind != 'scrypt':
            return False
        actual = _scrypt(password, base64.b64decode(salt), int(n), int(r), int(p))
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = None


def burn_password_check(password: str):
    """Same work as a real check, so a wrong username takes as long as a wrong password."""
    global _DUMMY_HASH
    _DUMMY_HASH = _DUMMY_HASH or hash_password(secrets.token_urlsafe(12))
    verify_password(password, _DUMMY_HASH)


def password_problem(password: str, username: str = '') -> str | None:
    if not isinstance(password, str) or len(password) < 10:
        return 'Use a password of at least 10 characters.'
    if len(password) > 256:
        return 'Use a password of at most 256 characters.'
    if password.lower() in COMMON or (username and username.lower() in password.lower()):
        return 'Choose a less guessable password (not a common one and not your username).'
    if len(set(password)) < 5:
        return 'Choose a password with more different characters.'
    return None


def clean_username(value: str) -> str:
    name = (value or '').strip().lower()
    if not USERNAME.match(name):
        raise HTTPException(422, 'Usernames are 3–64 characters: letters, numbers, dots, dashes, underscores or @.')
    return name


# ---- Rate limits (in memory, per process) -----------------------------------------------

class RateLimiter:
    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, key: str, limit: int, window: float, record=True) -> float:
        """Returns 0 when allowed (and records the hit), else seconds until a slot frees."""
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return max(1.0, q[0] + window - now)
            if record:
                q.append(now)
            return 0.0

    def add(self, key: str):
        with self.lock:
            self.hits[key].append(time.monotonic())

    def clear(self, key: str | None = None):
        with self.lock:
            if key is None:
                self.hits.clear()
            else:
                self.hits.pop(key, None)


limiter = RateLimiter()


def too_many(wait: float, what='requests'):
    minutes = max(1, round(wait / 60))
    raise HTTPException(429, f'Too many {what}. Try again in about {minutes} minute{"s" if minutes > 1 else ""}.',
                        headers={'Retry-After': str(int(wait))})


# ---- Client details ---------------------------------------------------------------------

def client_ip(request: Request) -> str:
    # Behind a reverse proxy, run uvicorn with --proxy-headers --forwarded-allow-ips=<proxy ip> so this is the real client.
    return (request.client.host if request.client else '') or 'unknown'


FORWARD_HEADERS = ('forwarded', 'x-forwarded-for', 'x-real-ip', 'x-forwarded-host')


def direct_loopback(request: Request) -> bool:
    """True only for a request made on this computer itself, not relayed by a proxy."""
    try:
        local = ipaddress.ip_address(client_ip(request)).is_loopback
    except ValueError:
        return False
    return local and not any(h in request.headers for h in FORWARD_HEADERS)


def secure_cookies(request: Request) -> bool:
    mode = os.getenv('COOKIE_SECURE', 'auto').strip().lower()
    if mode in {'1', 'true', 'yes', 'on'}:
        return True
    if mode in {'0', 'false', 'no', 'off'}:
        return False
    return request.url.scheme == 'https'


# ---- Sessions ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuthUser:
    id: int
    username: str
    role: str
    csrf: str = ''
    token_hash: str = ''

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def can_edit(self):
        return self.role in ('admin', 'member')

    def public(self):
        return {'id': self.id, 'username': self.username, 'role': self.role}


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def start_session(db: Session, user: User, request: Request, response: Response) -> AuthSession:
    old = request.cookies.get(SESSION_COOKIE)
    if old:  # a new sign-in never reuses a session id (no fixation)
        db.query(AuthSession).filter(AuthSession.token_hash == token_hash(old)).delete()
    token = secrets.token_urlsafe(32)
    row = AuthSession(token_hash=token_hash(token), user_id=user.id, csrf=secrets.token_urlsafe(32),
                      ip=client_ip(request)[:64], user_agent=(request.headers.get('user-agent') or '')[:300])
    db.add(row)
    cutoff = datetime.utcnow() - SESSION_MAX
    db.query(AuthSession).filter(AuthSession.created_at < cutoff).delete()
    user.last_login_at = datetime.utcnow()
    db.commit()
    secure = secure_cookies(request)
    response.set_cookie(SESSION_COOKIE, token, max_age=int(SESSION_MAX.total_seconds()), httponly=True,
                        secure=secure, samesite='lax', path='/')
    # Readable by the page so it can echo it in X-CSRF-Token; useless to another site, which cannot read it.
    response.set_cookie(CSRF_COOKIE, row.csrf, max_age=int(SESSION_MAX.total_seconds()), httponly=False,
                        secure=secure, samesite='strict', path='/')
    return row


def end_session(db: Session, request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.query(AuthSession).filter(AuthSession.token_hash == token_hash(token)).delete()
        db.commit()
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path='/', secure=secure_cookies(request), samesite='lax')


def lookup_session(db: Session, request: Request) -> AuthUser | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token or len(token) > 200:
        return None
    row = db.get(AuthSession, token_hash(token))
    if row is None:
        return None
    now = datetime.utcnow()
    user = db.get(User, row.user_id)
    if (user is None or user.disabled or user.role not in ROLES or now - (row.created_at or now) > SESSION_MAX
            or now - (row.last_seen_at or now) > SESSION_IDLE):
        db.delete(row)
        db.commit()
        return None
    if now - (row.last_seen_at or now) > timedelta(minutes=5):
        row.last_seen_at = now
        db.commit()
    return AuthUser(user.id, user.username, user.role, row.csrf, row.token_hash)


def current_user(request: Request, db: Session = Depends(get_db)) -> AuthUser:
    user = lookup_session(db, request)
    if user is None:
        raise HTTPException(401, 'Sign in to continue.')
    request.state.user = user
    return user


def require_user(request: Request, user: AuthUser = Depends(current_user)) -> AuthUser:
    """Signed in, and for writes the request carries this session's CSRF token."""
    path = request.url.path
    watch_area = path == CLIENT_AREA or path.startswith(CLIENT_AREA + '/')
    if user.role == 'client' and not watch_area and path not in VIEWER_WRITES:
        raise HTTPException(403, 'Your client account can open the Watch section only.')
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, '')
        if not sent or not hmac.compare_digest(sent.encode(), user.csrf.encode()):
            raise HTTPException(403, 'Your session token is missing or out of date. Refresh the page and try again.')
        if not user.can_edit and path not in VIEWER_WRITES and not (user.role == 'client' and watch_area):
            raise HTTPException(403, 'Your account can view results only. Ask an admin for member access to make changes.')
    return user


def require_admin(user: AuthUser = Depends(require_user)) -> AuthUser:
    if not user.is_admin:
        raise HTTPException(403, 'Only an admin can do this.')
    return user


def rate_limit(name: str, limit: int, window_seconds: int):
    """Per-user limit for endpoints that spend API quota or CPU (Gemini, Serper, Apify, Chromium)."""
    def dependency(user: AuthUser = Depends(require_user)) -> AuthUser:
        wait = limiter.check(f'{name}:{user.id}', limit, window_seconds)
        if wait:
            too_many(wait)
        return user
    dependency.__name__ = f'rate_limit_{name}'
    return dependency


def env_int(name, default):
    try:
        return max(1, int(os.getenv(name, default)))
    except ValueError:
        return default


# ---- HTTP hardening middleware ----------------------------------------------------------

CALLBACK = re.compile(r'^/((strategy/plans|content/runs)/[^/]+/(result|fail)|watch/n8n/[a-z0-9/_-]+)$')
# Images made in the Gemini app and reels made on Higgsfield are uploaded here; everything else keeps the small cap.
UPLOAD = re.compile(r'^/content/items/\d+/media/(image|video)$')
MAX_UPLOAD_BYTES = 125 * 1024 * 1024
FONTS_CSS, FONTS = 'https://fonts.googleapis.com', 'https://fonts.gstatic.com'


BRIEF_VIEW = re.compile(r'^/watch/briefs/\d+/view$')


def content_security_policy(path: str) -> str:
    base = ["default-src 'self'", "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'", "form-action 'self'",
            "img-src 'self' data: blob:", "connect-src 'self'", f'font-src {FONTS} data:']
    if BRIEF_VIEW.match(path):
        # The weekly brief page uses inline style attributes (the same markup goes into email); no scripts at all.
        return '; '.join(base + ["script-src 'none'", f"style-src 'unsafe-inline' {FONTS_CSS}"])
    return '; '.join(base + ["script-src 'self'", f"style-src 'self' {FONTS_CSS}"])


def same_origin(request_headers: dict, scheme: str) -> bool:
    origin = request_headers.get('origin')
    site = request_headers.get('sec-fetch-site')
    if site and site not in ('same-origin', 'none'):
        return False
    if not origin:
        return True  # non-browser clients; the CSRF token still applies
    if origin == 'null':
        return False
    host = request_headers.get('x-forwarded-host') or request_headers.get('host', '')
    return urlsplit(origin).netloc.lower() == host.split(',')[0].strip().lower()


class SecurityMiddleware:
    """Pure ASGI (keeps NDJSON streaming intact): body size cap, cross-site write block, security headers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope.get('path', '')
        method = scope.get('method', 'GET')
        headers = {k.decode('latin-1').lower(): v.decode('latin-1') for k, v in scope.get('headers', [])}

        async def reply(status, detail):
            body = ('{"detail": "%s"}' % detail).encode()
            await send({'type': 'http.response.start', 'status': status,
                        'headers': [(b'content-type', b'application/json'), (b'content-length', str(len(body)).encode())]
                        + self.hardening(path, scope, b'application/json')})
            await send({'type': 'http.response.body', 'body': body})

        cap = MAX_UPLOAD_BYTES if method == 'PUT' and UPLOAD.match(path) else MAX_BODY_BYTES
        if method not in SAFE_METHODS:
            if not CALLBACK.match(path) and not same_origin(headers, scope.get('scheme', 'http')):
                return await reply(403, 'Cross-site requests are not allowed.')
            try:
                declared = int(headers.get('content-length') or 0)
            except ValueError:
                return await reply(400, 'Invalid Content-Length.')
            if declared > cap:
                return await reply(413, 'Request body is too large.')

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message['type'] == 'http.request':
                received += len(message.get('body', b''))
                if received > cap:
                    raise HTTPException(413, 'Request body is too large.')
            return message

        async def send_with_headers(message):
            if message['type'] == 'http.response.start':
                existing = list(message.get('headers', []))
                ctype = next((v for k, v in existing if k.lower() == b'content-type'), b'')
                names = {k.lower() for k, _ in existing}
                message['headers'] = existing + [h for h in self.hardening(path, scope, ctype) if h[0] not in names]
            await send(message)

        await self.app(scope, limited_receive, send_with_headers)

    @staticmethod
    def hardening(path, scope, ctype: bytes):
        out = [(b'x-content-type-options', b'nosniff'),
               (b'x-frame-options', b'DENY'),
               (b'referrer-policy', b'same-origin'),
               (b'cross-origin-opener-policy', b'same-origin'),
               (b'cross-origin-resource-policy', b'same-origin'),
               (b'permissions-policy', b'camera=(), microphone=(), geolocation=(), payment=(), usb=()'),
               (b'content-security-policy', content_security_policy(path).encode())]
        if scope.get('scheme') == 'https':
            out.append((b'strict-transport-security', b'max-age=31536000; includeSubDomains'))
        static = path.startswith('/static/')
        if not static:
            out.append((b'cache-control', b'no-store'))
        return out


def allowed_hosts() -> list[str]:
    raw = os.getenv('ALLOWED_HOSTS', '').strip()
    hosts = [h.strip() for h in raw.split(',') if h.strip()] if raw else []
    return hosts or ['localhost', '127.0.0.1', '::1', '[::1]']

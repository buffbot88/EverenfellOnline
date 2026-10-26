"""HTTP account API mirroring the legacy PHP contract (ThreadingHTTPServer).

  POST /AjaxRequest/AccountHandler.php {Action:Login, uName, uPas}
      -> text containing '登陆成功' ("login succeeded"; sets mko_session cookie)
  POST /AjaxRequest/AccountHandler.php {Action:Register, uName, uPas, sCode}
      -> text containing '注册成功' ("registration succeeded"; captcha-checked when enabled)
  GET  /configuration/VerifyCode.php -> 4-char captcha PNG (Pillow)
  GET  /gamesession.php -> {ok,uid,t,sign,seid,sport,ip,pid} (401 logged out)
      sign = HMAC-SHA256(server secret, uid|t); see auth.generate_sign.
"""
import hashlib
import hmac
import io
import json
import logging
import mimetypes
import os
import random
import secrets
import string
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from auth import Sessions, generate_sign, hash_password, verify_password
from oidc import begin_login, can_play, exchange_code, verify_id_token

log = logging.getLogger('web')

SEID, SPORT, IP, PID = 'fu1304', 8008, '127.0.0.1', 'gmthai'

# Read-only local asset root for the original client (dev only, never shipped).
RES_ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         '..', 'MKO_Client', 'Assets', 'res'))
ASSET_ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            '..', 'websites', 'everenfell', 'assets'))
OIDC_STATE_COOKIE = 'evf_oidc_state'
AGP_SESSION_COOKIE = 'evf_session'
AGP_CSRF_COOKIE = 'evf_csrf'
GATEWAY_AUDIENCE = 'everenfell-gateway'
RES_TYPES = {'.swf': 'application/x-shockwave-flash', '.png': 'image/png',
             '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.mp3': 'audio/mpeg',
             '.xml': 'application/xml', '.gz': 'application/octet-stream',
             '.mpq': 'application/octet-stream', '.dat': 'application/octet-stream',
             '.ani': 'application/octet-stream', '.pak': 'application/octet-stream',
             '.txt': 'text/plain'}
LOGIN_FAIL_LIMIT = 5      # failed logins/registers per client IP ...
LOGIN_FAIL_WINDOW_S = 300  # ... within this window before we refuse


def session_cookie(tok):
    """mko_session with HttpOnly and SameSite=Strict (no Secure: plain HTTP on loopback)."""
    return f'mko_session={tok}; Path=/; HttpOnly; SameSite=Strict'


def agp_session_cookie(token, max_age):
    return f'{AGP_SESSION_COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; Secure; SameSite=Lax'


def agp_csrf_cookie(token, max_age):
    return f'{AGP_CSRF_COOKIE}={token}; Path=/; Max-Age={max_age}; Secure; SameSite=Lax'


def clear_agp_cookies():
    return [f'{AGP_SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax',
            f'{AGP_CSRF_COOKIE}=; Path=/; Max-Age=0; Secure; SameSite=Lax']


def clear_oidc_state_cookie():
    return f'{OIDC_STATE_COOKIE}=; Path=/auth/callback; Max-Age=0; HttpOnly; Secure; SameSite=Lax'


def cross_origin(headers):
    """True when browser metadata says the POST came from another site or origin.

    Requests without Origin or Sec-Fetch-Site (the Flash projector, scripts) pass.
    """
    fetch_site = headers.get('Sec-Fetch-Site')
    if fetch_site and fetch_site not in ('same-origin', 'none'):
        return True
    origin = headers.get('Origin')
    if origin is None:
        return False
    host = (headers.get('Host') or '').lower()
    return origin.lower() not in (f'http://{host}', f'https://{host}')


class FailLimiter:
    """Sliding-window count of failed auth attempts per client IP."""

    def __init__(self, limit=LOGIN_FAIL_LIMIT, window=LOGIN_FAIL_WINDOW_S):
        self.limit, self.window = limit, window
        self._hits = {}
        self._lock = threading.Lock()

    def _recent(self, ip, now):
        cutoff = now - self.window
        recent = [t for t in self._hits.get(ip, []) if t > cutoff]
        if recent:
            self._hits[ip] = recent
        else:
            self._hits.pop(ip, None)
        return recent

    def blocked(self, ip, now=None):
        now = time.time() if now is None else now
        with self._lock:
            return len(self._recent(ip, now)) >= self.limit

    def failed(self, ip, now=None):
        now = time.time() if now is None else now
        with self._lock:
            self._hits[ip] = self._recent(ip, now) + [now]

    def reset(self, ip):
        with self._lock:
            self._hits.pop(ip, None)


class Handler(BaseHTTPRequestHandler):
    server_version = 'MkoPy/0.1'

    def _send(self, code, body, ctype='text/html; charset=utf-8', headers=None):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        for k, value in (headers or {}).items():
            for v in value if isinstance(value, (list, tuple)) else (value,):
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _cookies(self):
        out = {}
        for part in self.headers.get('Cookie', '').split(';'):
            if '=' in part:
                k, v = part.strip().split('=', 1)
                out[k] = v
        return out

    def _session_uid(self):
        s = self.server.sessions.get(self._cookies().get('mko_session', ''))
        return s['uid'] if s else None

    def _agp_session(self):
        return self.server.store.get_agp_session(
            self._cookies().get(AGP_SESSION_COOKIE, ''))

    def _same_origin_post(self):
        return bool(self.headers.get('Origin')) and not cross_origin(self.headers)

    def _csrf_valid(self, session):
        token = self.headers.get('X-CSRF-Token', '')
        cookie = self._cookies().get(AGP_CSRF_COOKIE, '')
        return (bool(token) and hmac.compare_digest(token, cookie)
                and hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(),
                                        session['csrf_hash']))

    def _auth_session(self):
        session = self._agp_session()
        if not session:
            return self._send(200, json.dumps({'authenticated': False}),
                              'application/json', {'Cache-Control': 'no-store'})
        user = {key: session[key] for key in
                ('username', 'display_name', 'email', 'role')}
        user['everenfell_s1'] = bool(session['everenfell_s1'])
        user['can_play'] = can_play(session)
        return self._send(200, json.dumps({'authenticated': True, 'user': user}),
                          'application/json', {'Cache-Control': 'no-store'})

    def _oidc_login(self):
        try:
            state, location = begin_login(self.server.store)
        except Exception:
            return self._send(503, 'AGP sign-in is unavailable.', 'text/plain')
        return self._send(302, b'', headers={
            'Location': location,
            'Set-Cookie': f'{OIDC_STATE_COOKIE}={state}; Path=/auth/callback; Max-Age=600; HttpOnly; Secure; SameSite=Lax',
            'Cache-Control': 'no-store',
        })

    def _oidc_callback(self, query):
        cookies = self._cookies()
        state = query.get('state', [''])[0]
        code = query.get('code', [''])[0]
        state_cookie = cookies.get(OIDC_STATE_COOKIE, '')
        if not state or not state_cookie or not hmac.compare_digest(state, state_cookie):
            return self._send(400, 'Invalid sign-in state.', 'text/plain',
                              {'Set-Cookie': clear_oidc_state_cookie(), 'Cache-Control': 'no-store'})
        transaction = self.server.store.consume_oidc_transaction(state)
        if not transaction or not code or query.get('error'):
            return self._send(400, 'AGP sign-in was not completed.', 'text/plain',
                              {'Set-Cookie': clear_oidc_state_cookie(), 'Cache-Control': 'no-store'})
        try:
            identity = verify_id_token(
                exchange_code(code, transaction['verifier']), transaction['nonce'])
            session_token = secrets.token_urlsafe(32)
            csrf_token = secrets.token_urlsafe(32)
            expires = identity['expires']
            self.server.store.create_agp_session(
                session_token, csrf_token, identity, expires)
            max_age = max(1, expires - int(time.time()))
            return self._send(303, b'', headers={
                'Location': '/',
                'Set-Cookie': [agp_session_cookie(session_token, max_age),
                               agp_csrf_cookie(csrf_token, max_age),
                               clear_oidc_state_cookie()],
                'Cache-Control': 'no-store',
            })
        except Exception:
            return self._send(502, 'AGP sign-in could not be verified. Please try again.',
                              'text/plain', {'Set-Cookie': clear_oidc_state_cookie(),
                                             'Cache-Control': 'no-store'})

    def _protected_asset(self, path):
        session = self._agp_session()
        if not session:
            return self._send(401, 'authentication required', 'text/plain',
                              {'Cache-Control': 'no-store'})
        if not can_play(session):
            return self._send(403, 'Everenfell access required', 'text/plain',
                              {'Cache-Control': 'no-store'})
        rel = urllib.parse.unquote(path[len('/protected-assets/'):])
        target = os.path.realpath(os.path.join(ASSET_ROOT, rel))
        if (not rel or '\x00' in rel or not target.startswith(ASSET_ROOT + os.sep)
                or not os.path.isfile(target)):
            return self._send(404, 'not found', 'text/plain')
        with open(target, 'rb') as asset:
            body = asset.read()
        etag = '"' + hashlib.sha256(body).hexdigest() + '"'
        headers = {'ETag': etag, 'Cache-Control': 'private, max-age=86400',
                   'X-Content-Type-Options': 'nosniff',
                   'Cross-Origin-Resource-Policy': 'same-origin'}
        if self.headers.get('If-None-Match') == etag:
            self.send_response(304)
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            return
        ext = os.path.splitext(target)[1].lower()
        ctype = RES_TYPES.get(ext) or mimetypes.guess_type(target)[0] or 'application/octet-stream'
        return self._send(200, body, ctype, headers)

    def _game_ticket(self):
        session = self._agp_session()
        if not session:
            return self._send(401, 'authentication required', 'text/plain')
        if not self._csrf_valid(session):
            return self._send(403, 'csrf_failed', 'text/plain')
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 1024:
                return self._send(400, 'invalid request', 'text/plain')
            body = json.loads(self.rfile.read(length) or b'{}')
        except (ValueError, json.JSONDecodeError):
            return self._send(400, 'invalid request', 'text/plain')
        if not isinstance(body, dict) or body.get('server') != 'S1':
            return self._send(400, 'unknown server', 'text/plain')
        if not can_play(session):
            return self._send(403, 'Everenfell access required', 'text/plain')
        token = secrets.token_urlsafe(32)
        expires = int(time.time()) + 30
        self.server.store.create_gateway_ticket(
            token, secrets.token_urlsafe(16), session, 'S1', SEID,
            GATEWAY_AUDIENCE, expires)
        return self._send(200, json.dumps({'ticket': token, 'expires_in': 30}),
                          'application/json', {'Cache-Control': 'no-store'})

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == '/auth/login':
            return self._oidc_login()
        if path == '/auth/callback':
            return self._oidc_callback(urllib.parse.parse_qs(parsed.query))
        if path == '/api/auth/session':
            return self._auth_session()
        if path.startswith('/protected-assets/'):
            return self._protected_asset(path)
        if path.endswith('gamesession.php'):
            uid = self._session_uid()
            if not uid:
                return self._send(401, json.dumps({'ok': False, 'error': 'not logged in'}),
                                  'application/json')
            t = str(int(time.time()))
            return self._send(200, json.dumps({
                'ok': True, 'uid': uid, 't': t,
                'sign': generate_sign(uid, t),
                'seid': SEID,
                'sport': getattr(self.server, 'game_port', SPORT),
                'ip': getattr(self.server, 'game_host', IP),
                'pid': PID,
            }), 'application/json')
        if path.endswith('VerifyCode.php'):
            code = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
            tok = self._cookies().get('mko_session', '')
            if self.server.sessions.get(tok) is None:
                tok = self.server.sessions.create('')  # pre-login captcha session
            self.server.sessions.set_captcha(tok, code)
            return self._send(200, render_captcha(code), 'image/png',
                              {'Set-Cookie': session_cookie(tok)})
        if path.startswith('/res/'):
            return self._send_res(path[len('/res/'):])
        return self._send(404, 'not found', 'text/plain')

    def _send_res(self, rel):
        """Read-only static route for the local original client assets (dev only).

        Serves regular files under the res root and nothing else; any path that
        escapes the root is refused.
        """
        root = RES_ROOT
        target = os.path.realpath(os.path.join(root, urllib.parse.unquote(rel)))
        if not target.startswith(root + os.sep) or not os.path.isfile(target):
            return self._send(404, 'not found', 'text/plain')
        ctype = RES_TYPES.get(os.path.splitext(target)[1].lower(),
                              'application/octet-stream')
        with open(target, 'rb') as fh:
            return self._send(200, fh.read(), ctype)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ('/api/auth/logout', '/api/game/ticket'):
            if not self._same_origin_post():
                return self._send(403, 'forbidden', 'text/plain')
            if path == '/api/auth/logout':
                session = self._agp_session()
                if session and not self._csrf_valid(session):
                    return self._send(403, 'csrf_failed', 'text/plain')
                if session:
                    self.server.store.delete_agp_session(
                        self._cookies().get(AGP_SESSION_COOKIE, ''))
                return self._send(200, json.dumps({'ok': True}), 'application/json',
                                  {'Set-Cookie': clear_agp_cookies(),
                                   'Cache-Control': 'no-store'})
            return self._game_ticket()
        if not path.endswith('AccountHandler.php'):
            return self._send(404, 'not found', 'text/plain')
        if cross_origin(self.headers):
            return self._send(403, 'forbidden', 'text/plain')
        ln = int(self.headers.get('Content-Length', 0))
        form = urllib.parse.parse_qs(self.rfile.read(ln).decode('utf-8', 'replace'))
        f = {k: v[0] for k, v in form.items()}
        if f.get('Action') == 'Register':
            return self.register(f)
        return self.login(f)

    def login(self, f):
        ip = self.client_address[0]
        if self.server.limiter.blocked(ip):
            return self._send(429, '登录失败次数过多，请稍后再试 Too many failed attempts')
        acc = self.server.store.get_account(f.get('uName', ''))
        if acc and verify_password(f.get('uPas', ''), acc['pass_hash']):
            tok = self.server.sessions.create(acc['username'])
            self.server.limiter.reset(ip)
            log.info('web login ok: %s', acc['username'])
            return self._send(200, '登陆成功 Login successful',
                              headers={'Set-Cookie': session_cookie(tok)})
        self.server.limiter.failed(ip)
        log.info('web login failed: %s', f.get('uName', ''))
        return self._send(200, '用户名或者密码错误 Invalid username or password')

    def register(self, f):
        u, p, code = f.get('uName', ''), f.get('uPas', ''), f.get('sCode', '')
        ip = self.client_address[0]
        if self.server.limiter.blocked(ip):
            return self._send(429, '登录失败次数过多，请稍后再试 Too many failed attempts')
        if len(u) < 3 or len(p) < 3:
            return self._send(200, '用户名或密码太短 (min 3 chars)')
        if self.server.require_captcha:
            sess = self.server.sessions.get(self._cookies().get('mko_session', ''))
            if not sess or sess.get('captcha', '').lower() != code.lower():
                self.server.limiter.failed(ip)
                return self._send(200, '验证码错误 Invalid captcha')

        if self.server.store.create_account(u, hash_password(p)):
            # "注册并登录": a fresh registration also starts the session,
            # like the legacy site (which kept PHP session state across it).
            tok = self.server.sessions.create(u)
            log.info('web register ok: %s', u)
            return self._send(200, '注册成功 Registered',
                              headers={'Set-Cookie': session_cookie(tok)})
        self.server.limiter.failed(ip)
        return self._send(200, '用户名已存在 Username taken')


def render_captcha(code):
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (100, 36), (240, 240, 240))
    d = ImageDraw.Draw(img)
    for _ in range(60):
        d.point((random.randrange(100), random.randrange(36)),
                fill=(random.randrange(256), random.randrange(256), random.randrange(256)))
    d.text((22, 8), code, fill=(20, 20, 120))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def serve(store, sessions, host, port, require_captcha, game_host=IP,
          game_port=SPORT):
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.store = store
    httpd.sessions = sessions
    httpd.require_captcha = require_captcha
    httpd.game_host = game_host
    httpd.game_port = game_port
    httpd.limiter = FailLimiter()
    log.info('web up: http://%s:%d (captcha %s)',
             host, port, 'on' if require_captcha else 'off')
    httpd.serve_forever()

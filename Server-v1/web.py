"""HTTP account API mirroring the legacy PHP contract (ThreadingHTTPServer).

  POST /AjaxRequest/AccountHandler.php {Action:Login, uName, uPas}
      -> text containing '登陆成功' ("login succeeded"; sets mko_session cookie)
  POST /AjaxRequest/AccountHandler.php {Action:Register, uName, uPas, sCode}
      -> text containing '注册成功' ("registration succeeded"; captcha-checked when enabled)
  GET  /configuration/VerifyCode.php -> 4-char captcha PNG (Pillow)
  GET  /gamesession.php -> {ok,uid,t,sign,seid,sport,ip,pid} (401 logged out)
      sign = md5(uid.'xianlingkey'.t), same as LoginHelper/PHP.
"""
import io
import json
import logging
import random
import string
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from auth import Sessions, generate_sign, hash_password, verify_password

log = logging.getLogger('web')

SEID, SPORT, IP, PID = 'fu1304', 8008, '127.0.0.1', 'gmthai'


class Handler(BaseHTTPRequestHandler):
    server_version = 'MkoPy/0.1'

    def _send(self, code, body, ctype='text/html; charset=utf-8', headers=None):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        for k, v in (headers or {}).items():
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

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.endswith('gamesession.php'):
            uid = self._session_uid()
            if not uid:
                return self._send(401, json.dumps({'ok': False, 'error': 'not logged in'}),
                                  'application/json')
            t = str(int(time.time()))
            return self._send(200, json.dumps({
                'ok': True, 'uid': uid, 't': t,
                'sign': generate_sign(uid, t),
                'seid': SEID, 'sport': SPORT, 'ip': IP, 'pid': PID,
            }), 'application/json')
        if path.endswith('VerifyCode.php'):
            code = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
            tok = self._cookies().get('mko_session', '')
            if self.server.sessions.get(tok) is None:
                tok = self.server.sessions.create('')  # pre-login captcha session
            self.server.sessions.set_captcha(tok, code)
            return self._send(200, render_captcha(code), 'image/png',
                              {'Set-Cookie': f'mko_session={tok}; Path=/'})
        return self._send(404, 'not found', 'text/plain')

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not path.endswith('AccountHandler.php'):
            return self._send(404, 'not found', 'text/plain')
        ln = int(self.headers.get('Content-Length', 0))
        form = urllib.parse.parse_qs(self.rfile.read(ln).decode('utf-8', 'replace'))
        f = {k: v[0] for k, v in form.items()}
        if f.get('Action') == 'Register':
            return self.register(f)
        return self.login(f)

    def login(self, f):
        acc = self.server.store.get_account(f.get('uName', ''))
        if acc and verify_password(f.get('uPas', ''), acc['pass_hash']):
            tok = self.server.sessions.create(acc['username'])
            log.info('web login ok: %s', acc['username'])
            return self._send(200, '登陆成功 Login successful',
                              headers={'Set-Cookie': f'mko_session={tok}; Path=/'})
        log.info('web login failed: %s', f.get('uName', ''))
        return self._send(200, '用户名或者密码错误 Invalid username or password')

    def register(self, f):
        u, p, code = f.get('uName', ''), f.get('uPas', ''), f.get('sCode', '')
        if len(u) < 3 or len(p) < 3:
            return self._send(200, '用户名或密码太短 (min 3 chars)')
        if self.server.require_captcha:
            sess = self.server.sessions.get(self._cookies().get('mko_session', ''))
            if not sess or sess.get('captcha', '').lower() != code.lower():
                return self._send(200, '验证码错误 Invalid captcha')

        if self.server.store.create_account(u, hash_password(p)):
            # "注册并登录": a fresh registration also starts the session,
            # like the legacy site (which kept PHP session state across it).
            tok = self.server.sessions.create(u)
            log.info('web register ok: %s', u)
            return self._send(200, '注册成功 Registered',
                              headers={'Set-Cookie': f'mko_session={tok}; Path=/'})
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


def serve(store, sessions, host, port, require_captcha):
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.store = store
    httpd.sessions = sessions
    httpd.require_captcha = require_captcha
    log.info('web up: http://%s:%d (captcha %s)',
             host, port, 'on' if require_captcha else 'off')
    httpd.serve_forever()

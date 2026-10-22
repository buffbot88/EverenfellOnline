"""Security regressions: game sign freshness/secret, cookie flags, login rate limit, role ownership."""
import hashlib
import http.cookiejar
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import auth
from auth import SIGN_WINDOW_S, Sessions, check_sign, generate_sign, hash_password
from db import Store
from game.protocol import Session
from game.ratelimit import TokenBucket
import web


def temp_store(cleanups):
    d = tempfile.mkdtemp()
    cleanups.append((shutil.rmtree, (d,), {'ignore_errors': True}))
    st = Store(os.path.join(d, 't.db'))
    cleanups.append((st.close, (), {}))
    return st


class TestGameSign(unittest.TestCase):
    def test_fresh_signed_timestamp_accepted(self):
        now = int(time.time())
        self.assertTrue(check_sign('hero', str(now), generate_sign('hero', str(now))))

    def test_legacy_md5_sign_rejected(self):
        ts = str(int(time.time()))
        legacy = hashlib.md5(f'hero{"xianlingkey"}{ts}'.encode()).hexdigest()
        self.assertFalse(check_sign('hero', ts, legacy))

    def test_stale_timestamp_rejected(self):
        now = 1_800_000_000
        ts = str(now - SIGN_WINDOW_S - 1)
        self.assertFalse(check_sign('hero', ts, generate_sign('hero', ts), now=now))

    def test_timestamp_at_window_edge_accepted(self):
        now = 1_800_000_000
        ts = str(now - SIGN_WINDOW_S)
        self.assertTrue(check_sign('hero', ts, generate_sign('hero', ts), now=now))

    def test_sign_bound_to_user(self):
        ts = str(int(time.time()))
        self.assertFalse(check_sign('other', ts, generate_sign('hero', ts)))

    def test_non_integer_timestamp_rejected(self):
        self.assertFalse(check_sign('hero', 'abc', generate_sign('hero', 'abc')))

    def test_secret_comes_from_env(self):
        saved = auth._sign_secret
        self.addCleanup(lambda: setattr(auth, '_sign_secret', saved))
        auth._sign_secret = None
        old = os.environ.get('MKO_SIGN_SECRET')
        self.addCleanup(lambda: os.environ.pop('MKO_SIGN_SECRET', None) if old is None
                        else os.environ.__setitem__('MKO_SIGN_SECRET', old))
        os.environ['MKO_SIGN_SECRET'] = 'configured-secret'
        ts = '1700000000'
        expected = __import__('hmac').new(b'configured-secret', b'hero|' + ts.encode(),
                                          hashlib.sha256).hexdigest()
        self.assertEqual(generate_sign('hero', ts), expected)


class TestSessionCookie(unittest.TestCase):
    def test_cookie_flags(self):
        c = web.session_cookie('tok')
        self.assertIn('mko_session=tok', c)
        self.assertIn('HttpOnly', c)
        self.assertIn('SameSite=Strict', c)
        self.assertIn('Path=/', c)


class TestFailLimiter(unittest.TestCase):
    def test_blocks_after_limit_and_expires(self):
        lim = web.FailLimiter(limit=3, window=60)
        for t in (0, 1, 2):
            self.assertFalse(lim.blocked('1.2.3.4', now=t))
            lim.failed('1.2.3.4', now=t)
        self.assertTrue(lim.blocked('1.2.3.4', now=3))
        self.assertFalse(lim.blocked('1.2.3.4', now=100))

    def test_other_ip_unaffected_and_reset(self):
        lim = web.FailLimiter(limit=1, window=60)
        lim.failed('a', now=0)
        self.assertTrue(lim.blocked('a', now=1))
        self.assertFalse(lim.blocked('b', now=1))
        lim.reset('a')
        self.assertFalse(lim.blocked('a', now=1))


class TestLoginRateLimitHTTP(unittest.TestCase):
    def setUp(self):
        self.cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in reversed(self.cleanups)])
        store = temp_store(self.cleanups)
        store.create_account('hero', hash_password('pw-correct'))
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
        httpd.store = store
        httpd.sessions = Sessions(store)
        httpd.require_captcha = False
        httpd.limiter = web.FailLimiter(limit=2, window=300)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        self.cleanups.append((httpd.server_close, (), {}))
        self.cleanups.append((httpd.shutdown, (), {}))  # runs first (reverse order)
        self.url = f'http://127.0.0.1:{httpd.server_address[1]}/AjaxRequest/AccountHandler.php'

    def post(self, headers=None, **form):
        data = urllib.parse.urlencode(form).encode()
        req = urllib.request.Request(self.url, data=data, method='POST')
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.headers.get('Set-Cookie', ''), r.read().decode()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.headers.get('Set-Cookie', ''), e.read().decode()

    def test_login_sets_hardened_cookie(self):
        status, cookie, body = self.post(Action='Login', uName='hero', uPas='pw-correct')
        self.assertEqual(status, 200)
        self.assertIn('登陆成功', body)
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Strict', cookie)

    def test_failed_logins_then_blocked_even_with_right_password(self):
        for _ in range(2):
            _, _, body = self.post(Action='Login', uName='hero', uPas='wrong')
            self.assertIn('Invalid', body)
        status, cookie, _ = self.post(Action='Login', uName='hero', uPas='pw-correct')
        self.assertEqual(status, 429)
        self.assertEqual(cookie, '')


class TestGamesessionEndpoint(unittest.TestCase):
    def setUp(self):
        self.cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in reversed(self.cleanups)])
        store = temp_store(self.cleanups)
        store.create_account('hero', hash_password('pw-correct'))
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
        httpd.store = store
        httpd.sessions = Sessions(store)
        httpd.require_captcha = False
        httpd.limiter = web.FailLimiter(limit=100, window=300)
        httpd.game_host = '127.0.0.1'
        httpd.game_port = 8028
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        self.cleanups.append((httpd.server_close, (), {}))
        self.cleanups.append((httpd.shutdown, (), {}))  # runs first (reverse order)
        self.base = f'http://127.0.0.1:{httpd.server_address[1]}'

    def gamesession(self, user, password):
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar))
        data = urllib.parse.urlencode(
            {'Action': 'Login', 'uName': user, 'uPas': password}).encode()
        req = urllib.request.Request(
            self.base + '/AjaxRequest/AccountHandler.php',
            data=data, method='POST')
        with opener.open(req, timeout=10) as r:
            r.read()
        with opener.open(self.base + '/gamesession.php',
                         timeout=10) as r:
            return json.load(r)

    def test_gamesession_reports_the_bound_game_port(self):
        sess = self.gamesession('hero', 'pw-correct')
        self.assertTrue(sess['ok'])
        self.assertEqual(sess['sport'], 8028)
        self.assertEqual(sess['ip'], '127.0.0.1')
        self.assertTrue(check_sign(sess['uid'], sess['t'], sess['sign']))


class TestCrossOrigin(unittest.TestCase):
    def test_no_browser_headers_allowed(self):
        self.assertFalse(web.cross_origin({'Host': '127.0.0.1:8080'}))

    def test_same_origin_allowed(self):
        h = {'Host': '127.0.0.1:8080', 'Origin': 'http://127.0.0.1:8080',
             'Sec-Fetch-Site': 'same-origin'}
        self.assertFalse(web.cross_origin(h))

    def test_foreign_origin_rejected(self):
        self.assertTrue(web.cross_origin({'Host': '127.0.0.1:8080',
                                          'Origin': 'http://evil.example'}))

    def test_null_origin_rejected(self):
        self.assertTrue(web.cross_origin({'Host': '127.0.0.1:8080', 'Origin': 'null'}))

    def test_cross_site_fetch_metadata_rejected(self):
        self.assertTrue(web.cross_origin({'Host': '127.0.0.1:8080',
                                          'Sec-Fetch-Site': 'cross-site'}))


class TestCrossOriginHTTP(unittest.TestCase):
    def setUp(self):
        self.cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in reversed(self.cleanups)])
        store = temp_store(self.cleanups)
        store.create_account('hero', hash_password('pw-correct'))
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
        httpd.store = store
        httpd.sessions = Sessions(store)
        httpd.require_captcha = False
        httpd.limiter = web.FailLimiter(limit=5, window=300)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.cleanups.append((httpd.server_close, (), {}))
        self.cleanups.append((httpd.shutdown, (), {}))
        self.url = f'http://127.0.0.1:{httpd.server_address[1]}/AjaxRequest/AccountHandler.php'

    post = TestLoginRateLimitHTTP.post

    def test_foreign_origin_post_is_forbidden(self):
        status, cookie, _ = self.post(headers={'Origin': 'http://evil.example'},
                                      Action='Login', uName='hero', uPas='pw-correct')
        self.assertEqual(status, 403)
        self.assertEqual(cookie, '')

    def test_same_origin_post_still_logs_in(self):
        host = urllib.parse.urlparse(self.url).netloc
        status, cookie, body = self.post(headers={'Origin': f'http://{host}'},
                                         Action='Login', uName='hero', uPas='pw-correct')
        self.assertEqual(status, 200)
        self.assertIn('登陆成功', body)


class TestFrameRateLimit(unittest.TestCase):
    def test_token_bucket_burst_then_refill(self):
        now = [0.0]
        bucket = TokenBucket(rate=2, burst=2, clock=lambda: now[0])
        self.assertTrue(bucket.allow())
        self.assertTrue(bucket.allow())
        self.assertFalse(bucket.allow())
        now[0] = 0.5  # refills one token at 2/s
        self.assertTrue(bucket.allow())
        self.assertFalse(bucket.allow())

    def test_connection_dropped_when_frame_budget_exhausted(self):
        sess = Session(conn_id=7, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [], server_start_ms=0)
        now = [0.0]
        sess.frame_bucket = TokenBucket(rate=1, burst=2, clock=lambda: now[0])
        empty_frame = struct.pack('>I', 0)
        self.assertEqual(sess.feed(empty_frame * 2), [])
        with self.assertRaises(ValueError):
            sess.feed(empty_frame)


class TestRoleOwnership(unittest.TestCase):
    """A role id from another account must never be read or written."""

    def setUp(self):
        self.cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in reversed(self.cleanups)])
        self.store = temp_store(self.cleanups)
        self.store.create_account('alice', hash_password('a'))
        self.store.create_account('mallory', hash_password('m'))
        self.alice_role = self.store.create_character('alice', 'fu1304', 'Alice')
        self.store.save_role_settings(self.alice_role, 'alice', 'fu1304',
                                      quickbar_info='alice-bar')

    def test_foreign_role_not_listed(self):
        ids = [str(r.get('id')) for r in self.store.list_roles('mallory', 'fu1304')]
        self.assertNotIn(str(self.alice_role), ids)

    def test_foreign_role_settings_not_readable(self):
        self.assertIsNone(self.store.get_role_settings(str(self.alice_role),
                                                       'mallory', 'fu1304'))

    def test_foreign_role_settings_not_writable(self):
        self.assertFalse(self.store.save_role_settings(self.alice_role, 'mallory',
                                                       'fu1304', quickbar_info='pwned'))
        settings = self.store.get_role_settings(str(self.alice_role), 'alice', 'fu1304')
        self.assertEqual(settings['quickbar_info'], 'alice-bar')

    def test_wrong_server_not_accessible(self):
        self.assertIsNone(self.store.get_role_settings(str(self.alice_role),
                                                       'alice', 'other-server'))


if __name__ == '__main__':
    unittest.main()

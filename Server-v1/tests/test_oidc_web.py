import hashlib
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import web  # noqa: E402
from auth import Sessions  # noqa: E402
from db import Store  # noqa: E402


class OidcWebFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(os.path.join(self.temp.name, 'game.db'))
        self.addCleanup(self.store.close)
        self.asset_root = Path(self.temp.name) / 'assets'
        (self.asset_root / 'maps/map0').mkdir(parents=True)
        (self.asset_root / 'maps/map0/tile.jpg').write_bytes(b'authorized tile')
        self.old_assets = web.ASSET_ROOT
        web.ASSET_ROOT = str(self.asset_root)
        self.addCleanup(lambda: setattr(web, 'ASSET_ROOT', self.old_assets))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
        self.server.store = self.store
        self.server.sessions = Sessions(self.store)
        self.server.require_captcha = False
        self.server.limiter = web.FailLimiter()
        self.server.game_host = '127.0.0.1'
        self.server.game_port = 8008
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = f'127.0.0.1:{self.server.server_port}'

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(*self.base.split(':', 1))
        raw = json.dumps(body).encode() if body is not None else None
        request_headers = dict(headers or {})
        if raw is not None:
            request_headers['Content-Type'] = 'application/json'
        conn.request(method, path, body=raw, headers=request_headers)
        response = conn.getresponse()
        data = response.read()
        result = response.status, response.getheaders(), data
        conn.close()
        return result

    @staticmethod
    def cookies(headers):
        values = [value for name, value in headers if name.lower() == 'set-cookie']
        return {value.split('=', 1)[0]: value for value in values}

    def test_login_callback_session_assets_and_single_use_ticket(self):
        state = 'state-' + 's' * 24

        def begin(store):
            store.create_oidc_transaction(state, 'verifier', 'nonce', int(time.time()) + 600)
            return state, 'https://www.agpstudios.org/api/oauth/authorize?state=' + state

        with patch.object(web, 'begin_login', side_effect=begin):
            status, headers, _ = self.request('GET', '/auth/login')
        self.assertEqual(status, 302)
        state_cookie = self.cookies(headers)[web.OIDC_STATE_COOKIE]
        self.assertIn('HttpOnly', state_cookie)
        self.assertIn('Secure', state_cookie)
        self.assertIn('SameSite=Lax', state_cookie)

        identity = {'sub': 'agp-1', 'username': 'admin', 'display_name': 'Admin',
                    'email': 'admin@example.test', 'role': 'Admin',
                    'everenfell_s1': True, 'expires': int(time.time()) + 3600}
        with patch.object(web, 'exchange_code', return_value='id-token') as exchange, \
             patch.object(web, 'verify_id_token', return_value=identity) as verify:
            status, headers, _ = self.request(
                'GET', '/auth/callback?code=code-1&state=' + state,
                headers={'Cookie': state_cookie.split(';', 1)[0]})
        self.assertEqual(status, 303)
        exchange.assert_called_once_with('code-1', 'verifier')
        verify.assert_called_once_with('id-token', 'nonce')
        set_cookies = self.cookies(headers)
        self.assertIn('HttpOnly', set_cookies[web.AGP_SESSION_COOKIE])
        self.assertIn('Secure', set_cookies[web.AGP_SESSION_COOKIE])
        self.assertNotIn('Domain=', set_cookies[web.AGP_SESSION_COOKIE])
        session_token = set_cookies[web.AGP_SESSION_COOKIE].split('=', 1)[1].split(';', 1)[0]
        csrf_token = set_cookies[web.AGP_CSRF_COOKIE].split('=', 1)[1].split(';', 1)[0]
        cookie = f'{web.AGP_SESSION_COOKIE}={session_token}; {web.AGP_CSRF_COOKIE}={csrf_token}'

        status, _, raw = self.request('GET', '/api/auth/session', headers={'Cookie': cookie})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(raw)['user']['can_play'])

        status, headers, body = self.request(
            'GET', '/protected-assets/maps/map0/tile.jpg', headers={'Cookie': cookie})
        self.assertEqual((status, body), (200, b'authorized tile'))
        etag = dict(headers)['ETag']
        status, _, body = self.request(
            'GET', '/protected-assets/maps/map0/tile.jpg',
            headers={'Cookie': cookie, 'If-None-Match': etag})
        self.assertEqual((status, body), (304, b''))
        status, _, _ = self.request(
            'GET', '/protected-assets/%2e%2e/README.md', headers={'Cookie': cookie})
        self.assertEqual(status, 404)

        origin = 'http://' + self.base
        ticket_headers = {'Cookie': cookie, 'Origin': origin,
                          'X-CSRF-Token': csrf_token}
        status, _, raw = self.request('POST', '/api/game/ticket', {'server': 'S1'}, ticket_headers)
        self.assertEqual(status, 200)
        ticket = json.loads(raw)['ticket']
        record = self.store.consume_gateway_ticket(ticket)
        self.assertEqual((record['sub'], record['game'], record['server'], record['audience']),
                         ('agp-1', 'everenfell', 'S1', web.GATEWAY_AUDIENCE))
        self.assertIsNone(self.store.consume_gateway_ticket(ticket))
        status, _, _ = self.request('POST', '/api/game/ticket', {'server': 'S1'},
                                    {**ticket_headers, 'Origin': 'https://evil.example'})
        self.assertEqual(status, 403)

    def test_anonymous_and_non_entitled_users_cannot_get_assets_or_tickets(self):
        status, _, _ = self.request('GET', '/protected-assets/maps/map0/tile.jpg')
        self.assertEqual(status, 401)
        token, csrf = 'member-session', 'member-csrf'
        self.store.create_agp_session(token, csrf, {
            'sub': 'agp-member', 'username': 'member', 'display_name': 'Member',
            'email': '', 'role': 'Admin', 'everenfell_s1': False,
        }, int(time.time()) + 3600)
        cookie = f'{web.AGP_SESSION_COOKIE}={token}; {web.AGP_CSRF_COOKIE}={csrf}'
        status, _, _ = self.request('GET', '/protected-assets/maps/map0/tile.jpg',
                                    headers={'Cookie': cookie})
        self.assertEqual(status, 403)
        status, _, _ = self.request('POST', '/api/game/ticket', {'server': 'S1'}, {
            'Cookie': cookie, 'Origin': 'http://' + self.base,
            'X-CSRF-Token': csrf,
        })
        self.assertEqual(status, 403)

    def test_state_cookie_mismatch_does_not_create_session(self):
        state = 'state-' + 'x' * 24
        self.store.create_oidc_transaction(state, 'verifier', 'nonce', int(time.time()) + 600)
        status, headers, _ = self.request(
            'GET', '/auth/callback?code=code&state=' + state,
            headers={'Cookie': f'{web.OIDC_STATE_COOKIE}=wrong'})
        self.assertEqual(status, 400)
        self.assertIn('Max-Age=0', self.cookies(headers)[web.OIDC_STATE_COOKIE])
        self.assertIsNone(self.store.get_agp_session(''))


if __name__ == '__main__':
    unittest.main()

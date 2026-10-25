"""Focused gateway tests: WS framing, op mapping, snapshot shaping.

No sockets, no server boot: the GameLink queue and a fake WS conn drive
the session. The full server suite stays gated on an explicit version
bump; this file runs standalone.
"""
import json
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from gateway import (GatewayError, GatewaySession, WsFrameReader,  # noqa: E402
                     SERVERS, handshake_cookies, monster_actors,
                     npc_actors, ws_accept_key, ws_encode_text,
                     ws_handshake_response)


def masked_text_frame(text):
    payload = text.encode('utf-8')
    mask = bytes([1, 2, 3, 4])
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return bytes([0x81, 0x80 | len(payload)]) + mask + masked


def server_text_payload(raw):
    assert raw[0] == 0x81
    length = raw[1]
    assert length < 126
    return json.loads(bytes(raw[2:2 + length]).decode())


class FakeConn:
    def __init__(self, inbound=b''):
        self.inbound = bytearray(inbound)
        self.sent = bytearray()

    def recv(self, n):
        if not self.inbound:
            return b''
        chunk = bytes(self.inbound[:n])
        del self.inbound[:n]
        return chunk

    def sendall(self, data):
        self.sent += data

    def close(self):
        pass


class FakeSessions:
    def __init__(self, users):
        self.users = users

    def get(self, token):
        return self.users.get(token)


class WsCodecTest(unittest.TestCase):
    def test_rfc6455_accept_vector(self):
        self.assertEqual(ws_accept_key('dGhlIHNhbXBsZSBub25jZQ=='),
                         's3pPLMBiTxaQ9kYGzzhZRbK+xOo=')

    def test_handshake_response(self):
        req = ('GET /everenfell HTTP/1.1\r\n'
               'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n')
        res = ws_handshake_response(req).decode()
        self.assertIn('101 Switching Protocols', res)
        self.assertIn('s3pPLMBiTxaQ9kYGzzhZRbK+xOo=', res)
        self.assertIsNone(ws_handshake_response('GET / HTTP/1.1\r\n\r\n'))

    def test_server_text_frame(self):
        raw = ws_encode_text('hi')
        self.assertEqual(raw, b'\x81\x02hi')

    def test_masked_client_frame_roundtrip(self):
        reader = WsFrameReader()
        events = reader.feed(masked_text_frame('{"op":"x"}'))
        self.assertEqual(events, [('text', '{"op":"x"}')])

    def test_fragmented_delivery(self):
        frame = masked_text_frame('hello')
        reader = WsFrameReader()
        self.assertEqual(reader.feed(frame[:3]), [])
        self.assertEqual(reader.feed(frame[3:]), [('text', 'hello')])

    def test_ping_and_close(self):
        reader = WsFrameReader()
        mask = bytes([9, 9, 9, 9])
        ping = bytes([0x89, 0x80 | 2]) + mask + bytes(
            b ^ mask[i % 2] for i, b in enumerate(b'ab'))
        self.assertEqual(reader.feed(ping), [('ping', b'ab')])
        close = bytes([0x88, 0x80]) + bytes([1, 2, 3, 4])
        self.assertEqual(reader.feed(close), [('close', None)])


class ActorMappingTest(unittest.TestCase):
    def test_monster_records(self):
        recs = [['m_7_0', 'T1', 'mob', 3, 100.0, 100, 50, 50, 200, 200,
                 0, 5, 6, 0, None, False, None, 0],
                ['bad'],
                ['m_7_1', 'T1', 'mob', 3, 50.0, 100, 50, 50, 200, 200,
                 0, 7, 8, 0, None, True, None, 0]]
        actors = monster_actors(recs)
        self.assertEqual(len(actors), 2)
        self.assertEqual(actors[0]['id'], 'm_7_0')
        self.assertEqual(actors[0]['kind'], 'mob')
        self.assertEqual((actors[0]['x'], actors[0]['y']), (5, 6))
        self.assertEqual(actors[0]['hp'], 100.0)

    def test_npc_records(self):
        actors = npc_actors([['N020001', 6, 152], ['bad', 'x']])
        self.assertEqual(actors, [{'id': 'N020001', 'kind': 'npc',
                                   'x': 6, 'y': 152}])

    def test_frames_to_snapshot(self):
        frames = [
            ['21000', [1, 1, 2]],
            ['23003', [['N020001', 6, 152]]],
            ['23002', [['m_2_0', 'T9', 'mob', 1, 40.0, 40, 10, 10,
                        100, 100, 0, 27, 104, 0, None, False, None, 0]]],
            ['12004', ['9', 144.0, 144.0, 96.0, 96.0]],
            ['12005', [0]],
        ]
        snapshot = GatewaySession._frames_to_snapshot('2', frames, '9')
        self.assertEqual(snapshot['mapId'], '2')
        kinds = sorted(a['kind'] for a in snapshot['actors'])
        self.assertEqual(kinds, ['mob', 'npc', 'player'])
        player = [a for a in snapshot['actors'] if a['kind'] == 'player'][0]
        self.assertEqual(player['vitals']['hp'], 144.0)


class SessionDispatchTest(unittest.TestCase):
    def session(self, users=None):
        conn = FakeConn()
        sess = GatewaySession(conn, FakeSessions(users or {}),
                              '127.0.0.1', 8008,
                              make_sign=lambda u, t: 'sig')
        return sess, conn

    def last_message(self, conn):
        raw = bytes(conn.sent)
        messages = []
        while raw:
            assert raw[0] == 0x81
            length = raw[1]
            messages.append(json.loads(bytes(raw[2:2 + length]).decode()))
            raw = raw[2 + length:]
        return messages[-1]

    def test_unknown_op_refused(self):
        sess, conn = self.session()
        sess._handle_request(json.dumps({'op': 'bogus.x', 'seq': 7}))
        msg = self.last_message(conn)
        self.assertEqual((msg['op'], msg['seq'], msg['ok']), ('bogus.x', 7, False))

    def test_bad_json_ignored(self):
        sess, conn = self.session()
        sess._handle_request('{not json')
        self.assertEqual(bytes(conn.sent), b'')

    def test_auth_session_rejects_unknown_token(self):
        sess, conn = self.session()
        sess._handle_request(json.dumps({'op': 'auth.session', 'seq': 1,
                                         'body': {'token': 'nope'}}))
        msg = self.last_message(conn)
        self.assertFalse(msg['ok'])
        self.assertIn('invalid session', msg['body']['error'])

    def test_move_requires_snapshot_first(self):
        sess, conn = self.session({'tok': {'username': 'hero'}})
        sess.username = 'hero'
        sess._handle_request(json.dumps({'op': 'player.move', 'seq': 3,
                                         'body': {'x': 9, 'y': 150}}))
        msg = self.last_message(conn)
        self.assertFalse(msg['ok'])

    def test_world_enter_replays_login_roles(self):
        sess, conn = self.session()
        sess._handle_request(json.dumps({'op': 'world.enter', 'seq': 2}))
        msg = self.last_message(conn)
        self.assertFalse(msg['ok'])
        sess.username = 'hero'
        sess.roles = [{'id': '1', 'name': 'Hero', 'job': 'A', 'level': 1}]
        sess._handle_request(json.dumps({'op': 'world.enter', 'seq': 3}))
        msg = self.last_message(conn)
        self.assertTrue(msg['ok'])
        self.assertEqual(msg['body']['roles'][0]['name'], 'Hero')

    def test_snapshot_requires_login_first(self):
        sess, conn = self.session()
        sess._handle_request(json.dumps({'op': 'world.snapshot', 'seq': 4,
                                         'body': {'roleId': '1'}}))
        msg = self.last_message(conn)
        self.assertFalse(msg['ok'])

    def test_move_rejects_bad_coords(self):
        sess, conn = self.session()
        sess.username = 'hero'
        sess.role_id = '1'
        sess._handle_request(json.dumps({'op': 'player.move', 'seq': 5,
                                         'body': {'x': 'far'}}))
        msg = self.last_message(conn)
        self.assertFalse(msg['ok'])


class FakeLink:
    """Headless upstream stub: canned 10001/10003/20000 replies."""

    def __init__(self, roles=()):
        self.roles = roles
        self.sent = []

    def connect(self, host, port):
        pass

    def send(self, cmd):
        self.sent.append(cmd)

    def wait_for(self, cmd, timeout=5.0):
        if str(cmd) == '10001':
            return ['10001', [1, None, None, self.roles]]
        if str(cmd) == '10003':
            return ['10003', ['ok']]
        if str(cmd) == '20000':
            return ['20000', ['apply', '3', [58, 149]]]
        return None

    def drain(self, timeout=0.2):
        return []


class FakeStore:
    def __init__(self):
        self.bindings = {}

    def ensure_server_binding(self, member, server_id, game_account):
        self.bindings.setdefault((member, server_id), game_account)
        return self.bindings[(member, server_id)]


class ServerBindingTest(unittest.TestCase):
    def session(self, users=None, store=None, roles=()):
        conn = FakeConn()
        sess = GatewaySession(conn, FakeSessions(users or {}),
                              '127.0.0.1', 8008,
                              make_sign=lambda u, t: 'sig',
                              store=store)
        sess.link = FakeLink(roles)
        return sess, conn

    def auth(self, sess, conn, body, seq=1):
        sess._handle_request(json.dumps({'op': 'auth.session', 'seq': seq,
                                         'body': body}))
        return self.last_message(conn)

    def last_message(self, conn):
        raw = bytes(conn.sent)
        messages = []
        while raw:
            assert raw[0] == 0x81
            length = raw[1]
            pos = 2
            if length == 126:
                length = struct.unpack('>H', raw[2:4])[0]
                pos = 4
            elif length == 127:
                length = struct.unpack('>Q', raw[2:10])[0]
                pos = 10
            messages.append(json.loads(bytes(raw[pos:pos + length]).decode()))
            raw = raw[pos + length:]
        return messages[-1]

    def test_registry_lists_s1_only(self):
        self.assertEqual(SERVERS, {'S1': 'fu1304'})

    def test_handshake_cookie_parsing(self):
        req = ('GET /everenfell HTTP/1.1\r\n'
               'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
               'Cookie: mko_session=tok123; other=x\r\n\r\n')
        self.assertEqual(handshake_cookies(req)['mko_session'], 'tok123')
        self.assertEqual(handshake_cookies('GET / HTTP/1.1\r\n\r\n'), {})

    def test_unknown_server_refused(self):
        sess, conn = self.session({'tok': {'username': 'hero'}})
        msg = self.auth(sess, conn, {'token': 'tok', 'server': 'S2'})
        self.assertFalse(msg['ok'])
        self.assertIn('unknown server', msg['body']['error'])

    def test_auth_session_uses_handshake_cookie(self):
        roles = [['7', 'Hero', 'A', 0, 1]]
        sess, conn = self.session({'tok': {'username': 'hero'}},
                                    store=FakeStore(), roles=roles)
        sess.handshake_token = 'tok'
        msg = self.auth(sess, conn, {'server': 'S1'})
        self.assertTrue(msg['ok'])
        self.assertEqual(msg['body']['member'], 'hero')
        self.assertEqual(msg['body']['server'], 'S1')
        login = [c for c in sess.link.sent if c[0] == 10001][0]
        self.assertEqual(login[1][0], 'hero')
        self.assertEqual(login[1][2], 'fu1304')

    def test_binding_written_lazily_on_first_entry(self):
        store = FakeStore()
        roles = [['7', 'Hero', 'A', 0, 1]]
        sess, conn = self.session({'tok': {'username': 'hero'}},
                                    store=store, roles=roles)
        self.assertEqual(store.bindings, {})
        msg = self.auth(sess, conn, {'token': 'tok', 'server': 'S1'})
        self.assertTrue(msg['ok'])
        self.assertEqual(store.bindings, {('hero', 'fu1304'): 'hero'})

    def test_snapshot_rejects_unowned_character(self):
        sess, conn = self.session()
        sess.username = 'hero'
        sess.roles = [{'id': '7', 'name': 'Hero'}]
        sess._handle_request(json.dumps({'op': 'world.snapshot', 'seq': 4,
                                         'body': {'roleId': '9'}}))
        msg = self.last_message(conn)
        self.assertFalse(msg['ok'])
        self.assertIn('not owned', msg['body']['error'])
        self.assertIsNone(sess.role_id)

    def test_snapshot_accepts_owned_character(self):
        roles = [['7', 'Hero', 'A', 0, 1]]
        sess, conn = self.session({'tok': {'username': 'hero'}},
                                    roles=roles)
        self.auth(sess, conn, {'token': 'tok', 'server': 'S1'})
        sess._handle_request(json.dumps({'op': 'world.snapshot', 'seq': 5,
                                         'body': {'roleId': '7'}}))
        msg = self.last_message(conn)
        self.assertTrue(msg['ok'])
        self.assertEqual(msg['body']['mapId'], '3')
        self.assertEqual(sess.role_id, '7')


if __name__ == '__main__':
    unittest.main()

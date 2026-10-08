"""Protocol + persistence tests. The handshake/login vectors are built from
evidence, not invention: INITKEY bytes captured live from the real client,
framing/cipher/login/role layouts from jar bytecode (see docs/protocol.md).
"""
import os
import shutil
import struct
import sys
import tempfile
import unittest
import importlib.util

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
spec = importlib.util.spec_from_file_location(
    'decode_tap', os.path.join(ROOT, 'tools', 'decode-tap.py'))
decode_tap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decode_tap)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import check_sign, generate_sign, hash_password, verify_password
from db import Store
from game import amf3
from game.amf3 import ByteArray, Obj
from game.cipher import SimpleEncrypt, new_key
from game.protocol import Session, frame

# Live-captured first frame from the original client (bridge LOG_PACKETS=1).
CAPTURED_INITKEY = bytes.fromhex('00000009060f494e49544b4559')


def temp_store(cleanups):
    """A Store on a throwaway DB.

    Ordering matters on Windows: cleanup handlers run LIFO, so register the
    directory removal FIRST and the connection close second, otherwise rmtree
    runs while SQLite still holds the file (WinError 32 masks the real
    failure being debugged).
    """
    d = tempfile.mkdtemp()
    cleanups.append((shutil.rmtree, (d,), {'ignore_errors': True}))
    st = Store(os.path.join(d, 't.db'))
    cleanups.append((st.close, (), {}))
    return st


class TestVectors(unittest.TestCase):
    def test_captured_initkey_shape(self):
        ln = struct.unpack('>I', CAPTURED_INITKEY[:4])[0]
        self.assertEqual(ln, 9)
        self.assertEqual(amf3.decode(CAPTURED_INITKEY[4:]), 'INITKEY')

    def test_cipher_known_answer(self):
        # encode/decode are inverses; algorithm matches SimpleEncrypt bytecode:
        # enc[i] = (b + ticket[i%tl] - key[i%kl]) mod 256 (independent counters)
        c = SimpleEncrypt('k', 't')
        enc = c.encode(b'\x00\x01\xffABC')
        tk, kv = ord('t'), ord('k')
        want = bytes([(0 + tk - kv) & 0xFF, (1 + tk - kv) & 0xFF,
                      (0xFF + tk - kv) & 0xFF]) + SimpleEncrypt('k', 't').encode(b'ABC')[2:]
        self.assertEqual(enc[:3], want[:3])
        self.assertEqual(SimpleEncrypt('k', 't').decode(enc), b'\x00\x01\xffABC')

    def test_u29_boundaries(self):
        for v in [0, 1, 0x7F, 0x80, 0x3FFF, 0x4000, 0x1FFFFF, 0x200000,
                  0xFFFFFFF, -1, -0x10000000]:
            self.assertEqual(amf3.decode(amf3.encode(v)), v, hex(v & 0xFFFFFFFF))

    def test_exact_login_response_envelope(self):
        # Genuine Java sends the 2-element envelope ['10001', result]
        # (PublicMsgSender$2 path, byte-verified via raw-TCP probe). The old
        # 10-element shape belongs to a different sender; the client drops it.
        env = ['10001', [1, [1, 2, None, 'UTC', False, None], [0, 0], []]]
        raw = amf3.encode(env)
        back = amf3.decode(raw)
        self.assertEqual(back, env)
        self.assertEqual(len(back), 2)

    def test_amf3_byte_array_inline_and_object_reference(self):
        payload = bytes.fromhex('0c07010203')
        reader = amf3.Reader(payload + bytes.fromhex('0c00'))
        first = reader.read()
        second = reader.read()
        self.assertEqual(first, amf3.ByteArray(bytes([1, 2, 3])))
        self.assertIs(second, first)
        self.assertEqual(reader.p, len(payload) + 2)

    def test_amf3_byte_array_truncation_is_rejected(self):
        with self.assertRaises(amf3.Amf3Error):
            amf3.decode(bytes.fromhex('0c090102'))

    def test_amf3_byte_array_roundtrip(self):
        value = ['13000', [None, amf3.ByteArray(bytes(range(100))), None]]
        self.assertEqual(amf3.decode(amf3.encode(value)), value)

    def test_amf3_anonymous_object(self):
        # Canonical BlazeDS anonymous dynamic object: 0A 0B 01 <k><v>.. 01
        raw = amf3.encode(Obj({'rawOffset': 0}))
        self.assertEqual(raw[0], 0x0A)
        self.assertEqual(raw[1], 0x0B)
        self.assertEqual(raw[2], 0x01)
        self.assertEqual(raw[-1], 0x01)
        back = amf3.decode(raw)
        self.assertEqual(back['rawOffset'], 0)
        # roundtrip with mixed value types
        tz = Obj({'rawOffset': 28800000, 'ID': 'Asia/Shanghai',
                  'displayName': 'Asia/Shanghai', 'dstSavings': 0})
        self.assertEqual(amf3.decode(amf3.encode(tz)), tz)

    def test_server_info_vo_shape(self):
        # Mirrors ServerInfoVO.decode(): slot 3 must be an object carrying
        # rawOffset (the String we sent before raised AS3 Error #1069).
        tz = Obj({'rawOffset': 0, 'ID': 'UTC', 'displayName': 'UTC',
                  'dstSavings': 0})
        env = ['10001', [1, [1, 2, None, tz, False, None], [0, 0], []]]
        back = amf3.decode(amf3.encode(env))
        # result[1] is the 6-slot server-info array; slot 3 is the TimeZone.
        # (result[3] is the roles list — easy to conflate, hence the assert.)
        self.assertEqual(back[1][3], [])
        self.assertNotIsInstance(back[1][1][3], str)
        self.assertEqual(back[1][1][3]['rawOffset'], 0)

    def test_amf3_login_shapes(self):
        login = [10001, ['hero', 1700000000.0, 'fu1304', False, 'sig', 0, 1]]
        self.assertEqual(amf3.decode(amf3.encode(login)), login)
        env = ['10001', [1, [1, 2, None, 'UTC', False, None], [0, 0], []]]
        self.assertEqual(amf3.decode(amf3.encode(env)), env)


def make_session(store=None):
    return Session(conn_id=7, check_sign=check_sign,
                   get_roles=(lambda u, s: store.list_roles(u, s)) if store
                   else (lambda u, s: []),
                   get_role_settings=(lambda r, u, s: store.get_role_settings(r, u, s))
                   if store else (lambda r, u, s: None),
                   server_start_ms=1234567890000)


class TestHandshake(unittest.TestCase):
    def test_initkey_triggers_key_reply(self):
        s = make_session()
        out = s.feed(CAPTURED_INITKEY)
        self.assertEqual(len(out), 1)
        ln = struct.unpack('>I', out[0][:4])[0]
        key = out[0][4:].decode()
        self.assertEqual(ln, len(out[0][4:]))
        self.assertEqual(len(key), 36)  # UUID string
        self.assertIsNotNone(s.cipher)

    def test_policy_answered_raw(self):
        s = make_session()
        out = s.feed(b'<policy-file-request/>\x00')
        self.assertEqual(len(out), 1)
        self.assertIn(b'cross-domain-policy', out[0])
        self.assertNotIn(out[0][:4], [struct.pack('>I', len(out[0][4:]))])

    def test_fragmented_initkey(self):
        s = make_session()
        self.assertEqual(s.feed(CAPTURED_INITKEY[:5]), [])
        out = s.feed(CAPTURED_INITKEY[5:])
        self.assertEqual(len(out), 1)


class TestLogin(unittest.TestCase):
    def login_frame(self, sess, user, ts, verify):
        data = [user, float(ts), 'fu1304', False, verify, 0, 1]
        return frame(sess.cipher.encode(amf3.encode([10001, data])))

    def test_login_success_empty_roles(self):
        s = make_session()
        s.feed(CAPTURED_INITKEY)
        ts, user = '1700000000', 'hero'
        out = s.feed(self.login_frame(s, user, ts, generate_sign(user, ts)))
        self.assertEqual(len(out), 1)
        ln = struct.unpack('>I', out[0][:4])[0]
        env = amf3.decode(out[0][4:4 + ln])
        self.assertEqual(env[0], '10001')
        self.assertEqual(env[1][0], 1)  # success flag (InOutput.success)
        self.assertEqual(env[1][2], [0, 0])
        self.assertEqual(env[1][3], [])
        self.assertEqual(len(env), 2)  # genuine 2-element envelope
        self.assertEqual(s.authed_user, user)

    def test_login_bad_sign(self):
        s = make_session()
        s.feed(CAPTURED_INITKEY)
        out = s.feed(self.login_frame(s, 'hero', '1700000000', 'wrong'))
        env = amf3.decode(out[0][4:])
        self.assertEqual(env[1], [0, '16002'])  # InOutput.signError shape

    def test_login_pushes_java_bootstrap_after_login_reply(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        store.create_account('hero', hash_password('pw'))
        role_id = store.create_character(
            'hero', 'fu1304', 'SunWukong', job='C', tongqian=4509290,
            lingshi=9986377, bind_lingshi=360, recive_yb=0)
        panel = ByteArray(b'captured panel config')
        store.save_role_settings(role_id, 'hero', 'fu1304', panel_config=panel)
        s = make_session(store)
        s.feed(CAPTURED_INITKEY)
        out = s.feed(self.login_frame(s, 'hero', '1700000000',
                                      generate_sign('hero', '1700000000')))
        self.assertEqual(len(out), 3)
        messages = [amf3.decode(packet[4:]) for packet in out]
        self.assertEqual([msg[0] for msg in messages],
                         ['10001', '13000', '32010'])
        self.assertEqual(messages[1], ['13000', [None, panel, None, None]])
        self.assertEqual(messages[2], ['32010', [4509290, 9986377, 360, 0]])
        self.assertEqual(s.authed_user, 'hero')
        self.assertEqual(store.get_role_settings(str(role_id), 'someone-else',
                                                'fu1304'), None)

    def test_response_is_plaintext_not_enciphered(self):
        # Regression guard for the asymmetric protocol: server->client must
        # be parseable raw. If this ever fails, responses got encrypted again
        # and the Flash client aborts socketData with "Invalid object".
        s = make_session()
        s.feed(CAPTURED_INITKEY)
        ts, user = '1700000000', 'hero'
        out = s.feed(self.login_frame(s, user, ts, generate_sign(user, ts)))
        ln = struct.unpack('>I', out[0][:4])[0]
        payload = out[0][4:4 + ln]
        self.assertEqual(payload[0], 0x09)  # AMF3 array marker, in the clear
        self.assertEqual(amf3.decode(payload)[0], '10001')
        # and it must NOT be valid ciphertext of the AMF3 shape
        self.assertNotEqual(s.cipher.decode(payload)[0], 0x09)

    def test_unknown_command_ignored(self):
        s = make_session()
        s.feed(CAPTURED_INITKEY)
        bad = frame(s.cipher.encode(amf3.encode([99999, []])))
        self.assertEqual(s.feed(bad), [])


class TestCharacters(unittest.TestCase):
    def test_character_roundtrip_and_login_roles(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        st = temp_store(cleanups)
        st.create_account('hero', hash_password('pw'))
        cid = st.create_character('hero', 'fu1304', 'SunWukong', job='C', sex=0,
                                  exp=10692892, map_id='5', map_x=44,
                                  map_y=33, hp=5226, mp=1811,
                                  max_hp=5466, max_mp=1811,
                                  tongqian=4509290, bind_lingshi=360,
                                  lingshi=9986377, recive_yb=0)
        self.assertIsNotNone(cid)
        # duplicate name on the same account+server is rejected
        self.assertIsNone(st.create_character('hero', 'fu1304', 'SunWukong'))
        roles = st.list_roles('hero', 'fu1304')
        self.assertEqual(len(roles), 1)
        self.assertEqual(roles[0]['name'], 'SunWukong')
        self.assertEqual(roles[0]['job'], 'C')
        self.assertEqual(roles[0]['map_id'], '5')
        self.assertEqual((roles[0]['map_x'], roles[0]['map_y']), (44, 33))
        self.assertEqual((roles[0]['hp'], roles[0]['max_hp']), (5226, 5466))
        self.assertEqual(roles[0]['tongqian'], 4509290)
        # characters are scoped per server, and other accounts see none
        self.assertEqual(st.list_roles('hero', 'other'), [])
        self.assertEqual(st.list_roles('nobody', 'fu1304'), [])

        # ...and they show up in the 10001 login reply, one Array per role.
        sess = make_session(st)
        sess.feed(CAPTURED_INITKEY)
        ts, user = '1700000000', 'hero'
        data = [user, float(ts), 'fu1304', False,
                generate_sign(user, ts), 0, 1]
        out = sess.feed(frame(sess.cipher.encode(amf3.encode([10001, data]))))
        env = amf3.decode(out[0][4:])
        self.assertEqual(env[1][0], 1)
        self.assertEqual(len(env[1][3]), 1)
        role = env[1][3][0]
        # GetRoleOutput.roleInfo builds a positional Object[8]; the client
        # does `as Array` per entry (AS3 #1034 if we send an object instead).
        self.assertIsInstance(role, list)
        self.assertEqual(len(role), 8)
        self.assertEqual(role[0], str(cid))   # [0] getId(), a String
        self.assertEqual(role[1], 'SunWukong')  # [1] name
        self.assertEqual(role[2], 'C')        # [2] getJob(), a String
        self.assertEqual(role[3], 0)          # [3] sex
        self.assertEqual(role[4], 1)          # [4] level
        self.assertIsNone(role[5])            # [5] reserved, always null
        self.assertEqual(role[6], '')         # [6] face
        # [7] createTime is a Java Long: past AMF3's 29-bit int range it
        # travels as an AMF3 double, hence float on the way back.
        self.assertIsInstance(role[7], (int, float))
        self.assertEqual(int(role[7]), roles[0]['created'] * 1000)


class TestCaptureDecoder(unittest.TestCase):
    def test_multiple_server_messages_and_bytearray_payload(self):
        payload = amf3.encode(['13000', [None, ByteArray(b'opaque bootstrap'), None]])
        second = amf3.encode(['10003', [1, ['C', 56], ['5', 45, 31]]])
        framed = frame(payload + second)[4:]
        decoded = list(decode_tap.decode_server([('frame', framed)]))
        self.assertEqual(decoded[0][1][0], '13000')
        self.assertEqual(decoded[0][1][1][1], ByteArray(b'opaque bootstrap'))
        self.assertEqual(decoded[1][1][0], '10003')
        self.assertEqual(decoded[1][1][1][2], ['5', 45, 31])

    def test_frame_reader_handles_fragment_and_coalesced_frames(self):
        one, two = b'first', b'second'
        data = frame(one) + frame(two) + frame(b'incomplete')[:7]
        frames, used = decode_tap.read_frames(data)
        self.assertEqual(frames, [('frame', one), ('frame', two)])
        self.assertEqual(used, len(frame(one)) + len(frame(two)))


class TestWorldInit(unittest.TestCase):
    def reply(self, cmd, arg=None):
        s = make_session()
        if cmd == 20000:
            s.authed_user, s.server_id = 'hero', 'fu1304'
        s.feed(CAPTURED_INITKEY)
        out = s.feed(frame(s.cipher.encode(amf3.encode([cmd, arg]))))
        if not out:
            return None
        self.assertEqual(len(out), 1)
        return amf3.decode(out[0][4:])

    def test_world_init_replies(self):
        # Existing startup shapes remain covered while state-specific handlers
        # are tested with a role-backed session below.
        self.assertEqual(self.reply(19001)[0], '19001')
        self.assertIsNone(self.reply(20000))
        self.assertEqual(self.reply(32010)[1], [0, 0, 0, 0])

    def test_java_scene_entry_confirmation_21000(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        role_id = store.create_character(
            'hero', 'fu1304', 'SunWukong', job='C', map_id='5', map_x=44,
            map_y=33)
        session = make_session(store)
        session.authed_user, session.server_id = 'hero', 'fu1304'
        session.feed(CAPTURED_INITKEY)
        request = frame(session.cipher.encode(
            amf3.encode([21000, [str(role_id), '5']])))
        out = session.feed(request)
        self.assertEqual(len(out), 1)
        result = amf3.decode(out[0][4:])
        self.assertEqual(result, ['21000', [1, 1, 1]])

        # Unknown or unowned roles/maps must not receive a made-up scene reply.
        self.assertIsNone(session.change_stage([21000, '999']))
        store.update_character_state(role_id, map_id='999')
        self.assertIsNone(session.change_stage([21000, str(role_id)]))

    def test_java_capture_role_stage_and_money_values(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        role_id = store.create_character(
            'hero', 'fu1304', 'SunWukong', job='C', sex=0,
            exp=10692892, map_id='5', map_x=44, map_y=33,
            hp=5226, mp=1811, max_hp=5466, max_mp=1811,
            tongqian=4509290, bind_lingshi=360, lingshi=9986377,
            recive_yb=0)
        s = make_session(store)
        s.authed_user, s.server_id = 'hero', 'fu1304'
        entry = amf3.decode(s.enter_world([10003, str(role_id)])[4:])
        self.assertEqual(entry[0], '10003')
        self.assertEqual(entry[1][1],
                         ['', 1, 10692892, 0, 'C', False, 0, 10,
                          [20000000, 0], 0])
        self.assertEqual(entry[1][2], ['5', 44, 33])
        money = amf3.decode(s.money_info()[4:])
        self.assertEqual(money, ['32010', [4509290, 9986377, 360, 0]])
        apply = amf3.decode(s.apply_stage([20000, [str(role_id), '5']])[4:])
        self.assertEqual(apply, ['20000', [1, '5', [44, 33]]])
        scene = amf3.decode(s.change_stage([21000, str(role_id)])[4:])
        self.assertEqual(scene, ['21000', [1, 1, 1]])
        extra = amf3.decode(s.role_extra_info()[4:])
        self.assertEqual(extra, ['12011', [1, 5226, 1811, 9999, 0, 0,
                                           0, None, None, 0, 1]])
        panel = ByteArray(bytes(range(256)) * 2 + b'panel')
        self.assertTrue(store.save_role_settings(
            role_id, 'hero', 'fu1304', panel_config=panel))
        setting = amf3.decode(s.role_settings([13000, str(role_id)])[4:])
        self.assertEqual(setting, ['13000', [None, panel, None, None]])
        self.assertEqual(len(self.reply(12011)[1]), 11)
        self.assertEqual(self.reply(12010)[1], [[0] * 5] * 5)
        self.assertEqual(self.reply(35011)[1], 0)
        self.assertEqual(self.reply(32000, [None, '2000'])[1], [1, '', []])
        self.assertEqual(self.reply(64010)[1], [])
        self.assertEqual(self.reply(64001)[1], [])
        self.assertIsNone(self.reply(62000)[1])
        self.assertEqual(self.reply(111000)[1], [[], []])
        self.assertEqual(self.reply(108001)[1], [])
        self.assertEqual(self.reply(13000, 'slot')[1], [None, None, None, None])


class TestStore(unittest.TestCase):
    def test_account_roundtrip(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        st = temp_store(cleanups)
        self.assertTrue(st.create_account('hero', hash_password('pw')))
        self.assertFalse(st.create_account('hero', hash_password('pw')))
        acc = st.get_account('hero')
        self.assertTrue(verify_password('pw', acc['pass_hash']))
        self.assertFalse(verify_password('nope', acc['pass_hash']))
        self.assertEqual(st.list_roles('hero', 'fu1304'), [])

    def test_sessions_persist_in_sqlite(self):
        # A restart must not log everyone out (the browser keeps its cookie).
        from auth import Sessions
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        st = temp_store(cleanups)
        tok = Sessions(st).create('hero')
        # a brand-new Sessions object over the same DB = a "restart"
        self.assertEqual(Sessions(st).get(tok)['uid'], 'hero')
        self.assertIsNone(Sessions(st).get('nope'))


if __name__ == '__main__':
    unittest.main()

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

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
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
from game.config import GameConfig
from game.protocol import DEFAULT_MAP_TYPE, Session, frame

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

    def test_amf3_traits_reference_reuses_the_class(self):
        # Two anonymous-class objects sharing one sealed trait set: the second
        # object writes a traits REFERENCE (header bit1 clear, index << 2), not
        # the member list again. Ignoring that desynced the legacy tables.
        # 0x09 dense[2] -> 0x0A inline traits 0x23 (1 sealed member, sealed) "a"
        # then value 1; second object 0x0A header 0x01 (object, traits ref 0).
        # Object header 0x13 = 1 sealed member | traits-inline 0x02 | object-inline 0x01.
        # Second object header 0x01 = object-inline with traits ref index 0.
        raw = (b'\x09\x05\x01'
               b'\x0a\x13\x01' + b'\x03a' + b'\x04\x01'
               b'\x0a\x01' + b'\x04\x02')
        out = amf3.decode(raw)
        self.assertEqual(out, [{'a': 1}, {'a': 2}])

    def test_amf3_typed_vectors_and_dictionary(self):
        # Vector<int> [-1, 2]: marker 0x0D, U29 len<<1|1 = 5, fixed flag 0.
        vi = b'\x0d\x05\x00' + struct.pack('>i', -1) + struct.pack('>i', 2)
        self.assertEqual(amf3.decode(vi), [-1, 2])
        # Vector<double> [1.5]: marker 0x0F, len 1, fixed 1.
        vd = b'\x0f\x03\x01' + struct.pack('>d', 1.5)
        self.assertEqual(amf3.decode(vd), [1.5])
        # Dictionary {'k': 3}: 0x11, count 1 (header 0x03), weak 0, key, value.
        dct = b'\x11\x03\x00' + b'\x06\x03k' + b'\x04\x03'
        self.assertEqual(amf3.decode(dct), [('k', 3)])

    def test_amf3_date_marker(self):
        # 0x08 is the AMF3 Date marker: U29 (odd = inline) + big-endian ms.
        # The legacy config tables embed these, which is what stopped
        # MapLine.dat decoding (the mapType source for command 21000).
        raw = b'\x08\x01' + struct.pack('>d', 1386633600000.0)
        self.assertEqual(amf3.decode(raw), 1386633600000.0)

    def test_amf3_date_reference_reuses_the_object(self):
        # An even U29 is a reference into the object table, not a value. The
        # dense array itself takes slot 0, so the date is slot 1 -> U29 0x02.
        raw = (b'\x09\x05\x01' + b'\x08\x01' + struct.pack('>d', 5.0)
               + b'\x08\x02')
        self.assertEqual(amf3.decode(raw), [5.0, 5.0])


def make_session(store=None, config=None):
    kwargs = {} if store is None else {
        'create_role': (lambda a, s, n, j, x, f: store.create_character(
            a, s, n, job=j, sex=x, face=f)),
        'save_role_state': store.update_character_state,
    }
    if config is not None:
        kwargs['config'] = config
    return Session(conn_id=7, check_sign=check_sign,
                   get_roles=(lambda u, s: store.list_roles(u, s)) if store
                   else (lambda u, s: []),
                   get_role_settings=(lambda r, u, s: store.get_role_settings(r, u, s))
                   if store else (lambda r, u, s: None),
                   server_start_ms=1234567890000, **kwargs)


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

    def test_frame_reader_skips_socket_policy_on_either_side(self):
        # Live capture: the client sends <policy-file-request/> and Java
        # answers raw <cross-domain-policy> XML (no length prefix).
        req = b'<policy-file-request/>\x00'
        reply = (b'<cross-domain-policy><allow-access-from domain="*" '
                 b'to-ports="8000-8889"/></cross-domain-policy>\x00')
        frames, used = decode_tap.read_frames(req, allow_policy=True)
        self.assertEqual(frames, [('policy', req)])
        self.assertEqual(used, len(req))
        frames, used = decode_tap.read_frames(reply + frame(b'data'),
                                              allow_policy=True)
        self.assertEqual(frames[0], ('policy', reply))
        self.assertEqual(frames[1], ('frame', b'data'))
        self.assertEqual(list(decode_tap.decode_server(frames[:1])),
                         [('policy', reply)])

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

        # An unknown/unowned role id still gets nothing (no role to place).
        self.assertIsNone(session.change_stage([21000, '999']))
        # A map the legacy table does not list still gets the frame Java always
        # sends; the type falls back to the documented default rather than
        # leaving the client with no scene entry at all.
        store.update_character_state(role_id, map_id='999')
        fallback = amf3.decode(session.change_stage(
            [21000, str(role_id)])[4:])
        self.assertEqual(fallback, ['21000', [1, 1, DEFAULT_MAP_TYPE]])

    def test_map5_change_pushes_scene_entry_and_role_hp(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        role_id = store.create_character(
            'hero', 'fu1304', 'SunWukong', job='C', map_id='5', map_x=44,
            map_y=33, hp=5226, mp=1811, max_hp=5466, max_mp=1811)
        session = make_session(store)
        session.authed_user, session.server_id = 'hero', 'fu1304'
        session.feed(CAPTURED_INITKEY)
        out = session.feed(frame(session.cipher.encode(
            amf3.encode([20000, [str(role_id), '5']]))))
        self.assertEqual(len(out), 4)
        decoded = [amf3.decode(o[4:]) for o in out]
        self.assertEqual(decoded[0], ['20000', [1, '5', [44, 33]]])
        self.assertEqual(decoded[1], ['21000', [1, 1, 1]])
        self.assertEqual(decoded[2], ['12004', [str(role_id), 5226, 5466, 1811, 1811]])
        # Tap order continues with the shanbi value (none stored for this role).
        self.assertEqual(decoded[3], ['12005', [0]])

    def test_stage_and_movement_persist_to_db(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        role_id = store.create_character('hero', 'fu1304', 'SunWukong', job='C')
        s = make_session(store)
        s.authed_user, s.server_id = 'hero', 'fu1304'
        s.feed(CAPTURED_INITKEY)

        # 20000: the client's requested stage is authoritative and is saved.
        s.feed(frame(s.cipher.encode(amf3.encode([20000, [str(role_id), '5']]))))
        role = store.get_character(str(role_id), 'hero', 'fu1304')
        self.assertEqual(role['map_id'], '5')
        self.assertEqual(role['map_x'], 57)
        self.assertEqual(role['map_y'], 148)

        # 40000: the tile step is authoritative and is saved.
        step = [40000, [43, 32, 1, 2, str(role_id)]]
        self.assertIsNone(s.tile_step(step))
        role = store.get_character(str(role_id), 'hero', 'fu1304')
        self.assertEqual((role['map_x'], role['map_y']), (43, 32))

        # 42001: pixel movement echoes the server broadcast but never
        # persists (capture carries pixels like [2610, 1005], not tiles).
        echo = s.skill_move(
            [42001, [str(role_id), 'normal003', [2610, 1005],
                      [[2670, 1005, 3.14159, 0, 659]], 1]])
        role = store.get_character(str(role_id), 'hero', 'fu1304')
        self.assertEqual((role['map_x'], role['map_y']), (43, 32))
        self.assertEqual(amf3.decode(echo[4:])[0], '42001')

        # enter_world now reports the persisted stage, not the defaults.
        entry = amf3.decode(s.enter_world([10003, str(role_id)])[4:])
        self.assertEqual(entry[1][2], ['5', 43, 32])

    def test_move_without_coordinates_is_ignored(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        role_id = store.create_character('hero', 'fu1304', 'SunWukong', job='C')
        s = make_session(store)
        self.assertIsNone(s.skill_move([42001, [str(role_id), 'normal003']]))
        self.assertIsNone(s.tile_step([40000, [43, 32]]))
        self.assertIsNone(store.get_character(
            str(role_id), 'hero', 'fu1304')['map_x'])

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


class TestCreateRole(unittest.TestCase):
    def setUp(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        self.store = temp_store(cleanups)
        self.s = make_session(self.store)
        self.s.authed_user, self.s.server_id = 'hero', 'fu1304'

    def create(self, name):
        req = [10002, ['hero', name, 'C', 0, 'C', False, 'fu1304', 'gmthai']]
        return self.s.create_role(req)

    def result(self, name):
        return amf3.decode(self.create(name)[4:])

    def test_valid_cjk_name_creates_role(self):
        env = self.result('孫悟空')
        self.assertEqual(env[0], '10002')
        self.assertEqual(env[1][0], 1)
        role = env[1][1]
        self.assertEqual(role[1:4], ['孫悟空', 'C', 0])
        self.assertEqual(role[4:6], [1, None])

    def test_ascii_name_rejected_like_java_2001(self):
        # Live capture: Java answered [0, 2001] ROLE_NAME_NO_ALLOW for 'stress'.
        self.assertEqual(self.result('stress'), ['10002', [0, 2001]])

    def test_empty_and_s_names_rejected(self):
        self.assertEqual(self.result(''), ['10002', [0, 2001]])
        self.assertEqual(self.result('s孫悟空'), ['10002', [0, 2001]])
        self.assertEqual(self.result('悟空!'), ['10002', [0, 2001]])

    def test_duplicate_name_is_2002(self):
        self.result('孫悟空')
        self.assertEqual(self.result('孫悟空'), ['10002', [0, 2002]])

    def test_fifth_role_is_2005(self):
        for name in ('悟空壹', '悟空貳', '悟空參', '悟空肆'):
            self.assertEqual(self.result(name)[1][0], 1)
        self.assertEqual(self.result('悟空伍'), ['10002', [0, 2005]])


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


class TestCreateRoleWire(unittest.TestCase):
    """Command 10002 with the request shape captured from the live client."""

    def _reply(self, out):
        from game.amf3 import decode as amf3_decode
        (n,) = struct.unpack('>I', out[:4])
        return amf3_decode(out[4:4 + n])

    def test_create_role_success_duplicate_and_empty_name(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        st = temp_store(cleanups)
        st.create_account('hero', hash_password('pw'))
        sess = Session(conn_id=8, check_sign=check_sign,
                       get_roles=lambda u, s: [dict(r) for r in st.list_roles(u, s)],
                       server_start_ms=1,
                       create_role=lambda a, sid, n, j, x, f: st.create_character(
                           a, sid, n, job=j, sex=x, face=f))
        # 'Stress' starts with S, which Java rejects (checkInputName2), so
        # the success case uses a CJK name like a real client would.
        req = ['hero', '孫悟空', 'A', 0, 'A', False, 'fu1304', 'gmthai']

        ok = self._reply(sess.create_role([10002, req]))
        self.assertEqual(ok[0], '10002')
        self.assertEqual(ok[1][0], 1)
        role = ok[1][1]
        self.assertEqual([role[1], role[2], role[3], role[4], role[6]],
                         ['孫悟空', 'A', 0, 1, 'A'])
        self.assertEqual([r['name'] for r in st.list_roles('hero', 'fu1304')],
                         ['孫悟空'])

        dup = self._reply(sess.create_role([10002, req]))
        self.assertEqual(dup[1], [0, 2002])
        # Java has no 2003: empty names are 2001 nameIllegal.
        empty = self._reply(sess.create_role([10002, ['hero', '', 'A', 0, 'A',
                                                      False, 'fu1304', 'gmthai']]))
        self.assertEqual(empty[1], [0, 2001])
        ascii_name = self._reply(sess.create_role(
            [10002, ['hero', 'stress', 'A', 0, 'A', False, 'fu1304', 'gmthai']]))
        self.assertEqual(ascii_name[1], [0, 2001])


class TestMigratedRoleStage(unittest.TestCase):
    """A role migrated from MySQL: the role_stage row, not characters, wins.

    The source is dntg.role_stage row 'fu0UR1-10-0-1' (map 2 at 10,150 with
    144/96 hp/mp), which has no equivalent in the characters columns.
    """

    def setUp(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        self.store = temp_store(cleanups)
        self.role_id = self.store.create_character(
            'stress', 'fu1304', 'Tuan565.酆芷○訪蕊', job='B', sex=1, face='B',
            level=7, exp=1310)
        self.store.save_role_stage(
            self.role_id, map_id='2', map_x=10, map_y=150, hp=144, mp=96,
            max_hp=144, max_mp=96, ti_li=1)
        self.s = make_session(self.store)
        self.s.authed_user, self.s.server_id = 'stress', 'fu1304'

    def test_list_roles_prefers_the_stage_row(self):
        role = self.store.list_roles('stress', 'fu1304')[0]
        # legacy_id is NULL here because the migration tool, not this
        # constructor, writes it; the stage join is what this test covers.
        self.assertIsNone(role['legacy_id'])
        self.assertEqual(
            [role['map_id'], role['map_x'], role['map_y'], role['hp'],
             role['mp'], role['max_hp'], role['max_mp']],
            ['2', 10, 150, 144, 96, 144, 96])
        self.assertEqual(role['level'], 7)

    def test_enter_world_reports_the_migrated_stage(self):
        entry = amf3.decode(self.s.enter_world([10003, str(self.role_id)])[4:])
        self.assertEqual(entry[0], '10003')
        self.assertEqual(entry[1][2], ['2', 10, 150])
        # level/exp come from the migrated role row.
        self.assertEqual(entry[1][1][1], 7)
        self.assertEqual(entry[1][1][2], 1310)

    def test_apply_stage_keeps_migrated_coordinates(self):
        apply = amf3.decode(
            self.s.apply_stage([20000, [str(self.role_id), '']])[4:])
        self.assertEqual(apply, ['20000', [1, '2', [10, 150]]])

    def test_bootstrap_pushes_hp_mp_from_the_stage_row(self):
        frames = self.s.apply_stage_bootstrap([20000, [str(self.role_id), '']])
        self.assertIsInstance(frames, tuple)
        decoded = [amf3.decode(f[4:]) for f in frames]
        self.assertEqual(decoded[0], ['20000', [1, '2', [10, 150]]])
        # The scene entry is pushed for map 2 too, not only for map 5.
        self.assertEqual(decoded[1], ['21000', [1, 1, DEFAULT_MAP_TYPE]])
        # Tap order after the scene entry: hp/mp, then shanbi. This session
        # has no config, so the 12050/12000 pushes that follow are skipped.
        self.assertEqual(decoded[2], ['12004', [str(self.role_id), 144, 144,
                                                 96, 96]])
        self.assertEqual(decoded[3], ['12005', [0]])
        self.assertEqual(len(decoded), 4)

    def test_empty_stage_blobs_stay_null(self):
        stage = self.store.get_role_stage(self.role_id)
        for column in ('buff', 'props', 'map_node', 'meiren_info',
                       'zuoqi_info', 'copy_info'):
            self.assertIsNone(stage[column], column)


class TestWorldEntryStats(unittest.TestCase):
    """Captured world-entry stats pushes: 12004 -> 12005 -> 12050 -> 12000.

    Order comes from the Java tap (docs/java-python-parity-audit.md); payload
    shapes from StageInfoAction.info, FightOutputWrapper.outputAttributeChange
    and ZhujueAttributeExportServiceImpl bytecode.
    """

    LEVEL = 5

    def build(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        role_id = store.create_character(
            'hero', 'fu1304', 'Wukong', job='A', sex=0, face=1,
            level=self.LEVEL, exp=0, hp=120, mp=60, max_hp=120,
            max_mp=60, zhenqi=77)
        cfg_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cfg_dir, ignore_errors=True)
        os.makedirs(os.path.join(cfg_dir, 'sys_config'))
        with open(os.path.join(cfg_dir, 'sys_config',
                               'ZhuJueShuXingBiao.jat'), 'wb') as f:
            f.write(amf3.encode([
                Obj(level=self.LEVEL, mana=96, physicdamage=200,
                    physicdefence=50, critical=10, volt=7, attackrate=3,
                    velocity=520, dunshudian=12.7, jiangu=0.25,
                    zhenqi=100000)]))
        s = make_session(store, config=GameConfig(cfg_dir))
        s.authed_user, s.server_id = 'hero', 'fu1304'
        return s, role_id

    def test_entry_pushes_the_captured_stats_sequence(self):
        s, role_id = self.build()
        decoded = [amf3.decode(f[4:]) for f in
                   s.apply_stage_bootstrap([20000, [str(role_id), '']])]
        self.assertEqual([d[0] for d in decoded],
                         ['20000', '21000', '12004', '12005', '12050', '12000'])
        self.assertEqual(decoded[3], ['12005', [0]])    # shanbi_val: none stored
        self.assertEqual(decoded[4], ['12050', [77, 100000]])  # zhenqi, cap
        self.assertEqual(decoded[5][1], {
            '1': 60.0,    # persisted max_mp wins over the level row's mana
            '2': 200.0,   # physicdamage; effect slots are empty in migration
            '3': 62.5,    # physicdefence*(1+jiangu) = 50*1.25
            '4': 10.0,
            '5': 7.0,
            '6': 3.0,
            '7': 520.0,
            '10': 12.0,   # MaxShanBiValFormula casts dunshudian to int
        })

    def test_client_can_request_the_attribute_map(self):
        s, _ = self.build()
        s.feed(CAPTURED_INITKEY)
        out = s.feed(frame(s.cipher.encode(amf3.encode([12000, []]))))
        self.assertEqual(len(out), 1)
        decoded = amf3.decode(out[0][4:])
        self.assertEqual(decoded[0], '12000')
        self.assertEqual(decoded[1]['7'], 520.0)

    def test_without_a_level_row_only_the_first_four_are_pushed(self):
        s, role_id = self.build()
        s.config = None
        decoded = [amf3.decode(f[4:]) for f in
                   s.apply_stage_bootstrap([20000, [str(role_id), '']])]
        self.assertEqual([d[0] for d in decoded],
                         ['20000', '21000', '12004', '12005'])


class TestZuoQiPetFrame(unittest.TestCase):
    """Captured 23009 (tap line 9): the mount pet at scene entry.

    Layout from ZuoQiPet.getMsgData bytecode, values from the capture
    (rank 1, hp/max 500, level 30 via maxlv clamp, pet at 43,32 for a role
    at 44,33), placement from RoleEventManager.createZuoQiPetEnterStage +
    AoiStage.getSurroundValidPoint's AExtendOffs order.
    """

    MOUNTED = '{"id":1,"hp":500,"deadTime":0,"useTime":0,"rideOrNo":false}'
    LEVEL = 56

    def build(self, zuoqi_info=MOUNTED):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        role_id = store.create_character(
            'hero', 'fu1304', 's0.萬俊◆一刀', job='C', sex=0, face='C',
            level=self.LEVEL, exp=10692892, hp=5466, mp=1811, max_hp=5466,
            max_mp=1811, zhenqi=565260)
        store.save_role_stage(role_id, map_id='5', map_x=44, map_y=33,
                              shanbi_val=1, zuoqi_info=zuoqi_info)
        cfg_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cfg_dir, ignore_errors=True)
        os.makedirs(os.path.join(cfg_dir, 'sys_config'))
        with open(os.path.join(cfg_dir, 'sys_config',
                               'ZuoJiBiao.jat'), 'wb') as f:
            f.write(amf3.encode([
                Obj(stratum='001', ridelv=1, maxlv=30, meinvhp=100,
                    meinvatt=20),
                Obj(stratum='001', ridelv=30, maxlv=30, meinvhp=500,
                    meinvatt=100)]))
        with open(os.path.join(cfg_dir, 'sys_config',
                               'ZhuJueShuXingBiao.jat'), 'wb') as f:
            f.write(amf3.encode([
                Obj(level=self.LEVEL, mana=1811, physicdamage=2049,
                    physicdefence=996, critical=191, volt=196,
                    attackrate=147, velocity=550, dunshudian=0,
                    zhenqi=100000)]))
        # A fully walkable path grid around the captured role position.
        os.makedirs(os.path.join(cfg_dir, 'map_config', '5'))
        with open(os.path.join(cfg_dir, 'map_config', '5', 'path.mm'), 'wb') as f:
            f.write(struct.pack('>ii', 60, 60) + bytes([1]) * (60 * 60))
        s = make_session(store, config=GameConfig(cfg_dir))
        s.authed_user, s.server_id = 'hero', 'fu1304'
        return s, role_id

    def bootstrap(self, s, role_id):
        return [amf3.decode(f[4:]) for f in
                s.apply_stage_bootstrap([20000, [str(role_id), '']])]

    def test_entry_pushes_the_captured_mount_frame(self):
        s, role_id = self.build()
        decoded = self.bootstrap(s, role_id)
        self.assertEqual([d[0] for d in decoded],
                         ['20000', '21000', '23009', '12004', '12005',
                          '12050', '12000'])
        record = decoded[2][1][0]
        self.assertEqual(len(record), 14)
        self.assertTrue(record[0].startswith('zuoqi_5_'))
        # 1..13: rank, curHp (clamped), maxHp from meinvhp, owner id/name,
        # surround point, no buffs, alive, sex, pet level (56 clamped to 30),
        # the owner's move speed, and the '0' ride-weapon id.
        self.assertEqual(record[1:], [
            1, 500.0, 500.0, str(role_id), 's0.萬俊◆一刀', 43, 32,
            None, 0, 0, 30, 550.0, '0'])

    def test_without_zuoqi_info_no_mount_frame(self):
        s, role_id = self.build(zuoqi_info=None)
        decoded = self.bootstrap(s, role_id)
        self.assertEqual([d[0] for d in decoded],
                         ['20000', '21000', '12004', '12005', '12050',
                          '12000'])

    def test_riding_or_dead_mount_is_not_spawned(self):
        for info in ('{"id":1,"hp":500,"rideOrNo":true}',
                     '{"id":1,"hp":0,"rideOrNo":false}',
                     '{"id":0,"hp":500,"rideOrNo":false}',
                     'not json'):
            s, role_id = self.build(zuoqi_info=info)
            cmds = [d[0] for d in self.bootstrap(s, role_id)]
            self.assertNotIn('23009', cmds, info)

    def test_unknown_rank_is_skipped_not_invented(self):
        s, role_id = self.build(
            zuoqi_info='{"id":9,"hp":500,"rideOrNo":false}')
        with self.assertLogs('game', level='INFO'):
            cmds = [d[0] for d in self.bootstrap(s, role_id)]
        self.assertNotIn('23009', cmds)

    def test_zuoqi_info_reply_shape(self):
        s, role_id = self.build()
        s.feed(CAPTURED_INITKEY)
        out = s.feed(frame(s.cipher.encode(
            amf3.encode([12102, str(role_id)]))))
        self.assertEqual(len(out), 1)
        self.assertEqual(amf3.decode(out[0][4:]),
                         ['12102', [1, 30, None, None, 0, 0, 0, None]])

    def test_zuoqi_info_reply_without_a_mount_is_all_defaults(self):
        s, role_id = self.build(zuoqi_info=None)
        s.feed(CAPTURED_INITKEY)
        out = s.feed(frame(s.cipher.encode(
            amf3.encode([12102, str(role_id)]))))
        self.assertEqual(amf3.decode(out[0][4:]),
                         ['12102', [0, 0, None, None, 0, 0, 0, None]])


class TestLiveScene(unittest.TestCase):
    """Slice 1: tile steps persist, pixel moves echo, skill fire is logged."""

    def build(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        role_id = store.create_character(
            'hero', 'fu1304', 'SunWukong', job='C', map_id='5', map_x=44,
            map_y=33)
        s = make_session(store)
        s.authed_user, s.server_id = 'hero', 'fu1304'
        s.feed(CAPTURED_INITKEY)
        return s, store, str(role_id)

    def test_tile_step_persists_owned_role_only(self):
        s, store, role_id = self.build()
        self.assertIsNone(s.tile_step([40000, [45, 33, 1, 2, role_id]]))
        role = store.get_character(role_id, 'hero', 'fu1304')
        self.assertEqual((role['map_x'], role['map_y']), (45, 33))
        self.assertIsNone(s.tile_step([40000, [46, 33, 0, 2, 'm_64_93']]))
        role = store.get_character(role_id, 'hero', 'fu1304')
        self.assertEqual((role['map_x'], role['map_y']), (45, 33))

    def test_skill_move_echoes_capture_shape_without_db_write(self):
        s, store, role_id = self.build()
        out = s.skill_move([42001, [role_id, 'normal003', [2610, 1005],
                                    [[2670, 1005, 3.141592653589793, 0, 659]], 1]])
        env = amf3.decode(out[4:])
        self.assertEqual(env, ['42001', [1, role_id, 'normal003', [2610, 1005],
                                        [[2670, 1005, 3.141592653589793, 0, 659]],
                                        1, None]])
        role = store.get_character(role_id, 'hero', 'fu1304')
        self.assertEqual((role['map_x'], role['map_y']), (44, 33))
        self.assertIsNone(s.skill_move([42001, ['m_64_96', 'monster06']]))

    def test_skill_fire_logs_without_inventing_damage(self):
        s, _, role_id = self.build()
        self.assertIsNone(s.skill_fire(
            [42002, [role_id, 'normal003', 0, ['m_64_96'], None, 1]]))
        self.assertIsNone(s.skill_fire([42002, [['m_64_96']]]))
        self.assertIsNone(s.skill_fire(
            [42002, ['nobody', 'normal003', 0, ['m_64_96'], None, 1]]))

    def test_jump_and_teleport_log_without_reply(self):
        s, _, _ = self.build()
        self.assertIsNone(s.jump([40001, []]))
        self.assertIsNone(s.teleport([40100, []]))


if __name__ == '__main__':
    unittest.main()

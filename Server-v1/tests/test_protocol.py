"""Protocol + persistence tests. The handshake/login vectors are built from
evidence, not invention: INITKEY bytes captured live from the real client,
framing/cipher/login/role layouts from jar bytecode (see docs/protocol.md).
"""
import json
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
from game.config import DEFAULT_CONFIG_DIR, GameConfig
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
        'find_roles_by_name': store.find_roles_by_name,
        'get_role_equip': store.get_role_equip,
        'get_role_attr_buffs': store.get_role_attr_buffs,
        'get_role_vip': store.get_role_vip,
        'get_role_xianjiechenhao': store.get_role_xianjiechenhao,
        'get_role_meiren': store.get_role_meiren,
        'get_role_zuoqi': store.get_role_zuoqi,
        'save_role_stage': store.save_role_stage,
    }
    if config is not None:
        kwargs['config'] = config
    return Session(conn_id=7, check_sign=check_sign,
                   get_roles=(lambda u, s: store.list_roles(u, s)) if store
                   else (lambda u, s: []),
                   get_role_settings=(lambda r, u, s: store.get_role_settings(r, u, s))
                   if store else (lambda r, u, s: None),
                   save_role_settings=(lambda *a, **k: store.save_role_settings(*a, **k))
                   if store else (lambda *a, **k: False),
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
        self.assertEqual(len(out), 5)
        decoded = [amf3.decode(o[4:]) for o in out]
        self.assertEqual(decoded[0], ['20000', [1, '5', [44, 33]]])
        self.assertEqual(decoded[1], ['21000', [1, 1, 1]])
        self.assertEqual(decoded[2], ['12004', [str(role_id), 5226, 5466, 1811, 1811]])
        # Tap order continues with the shanbi value (none stored for this role).
        self.assertEqual(decoded[3], ['12005', [0]])
        # No level row is migrated, so the burst closes with 40501.
        self.assertEqual(decoded[4], ['40501', str(role_id)])

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
        self.assertEqual(self.reply(12010)[1], [
            [0, 0, 0, 0, 0], 0, [0, 0], [0, 0, 0], [0, 0], 0,
            [0, 0, 0], 0, 0, 0, [0, 0], 0, 0, 0, 0, 0,
            [0, 0, 0], 0, 0, 0, 0, 0, 0, [0, 0], 0])
        self.assertEqual(self.reply(35011)[1], 0)
        self.assertIsNone(self.reply(32000, [None, None]))
        self.assertIsNone(self.reply(64010)[1])
        self.assertEqual(self.reply(64001)[1], [1, [0, None, None, None]])
        self.assertEqual(self.reply(62000)[1], [0, 0, [], 0, 0])
        self.assertEqual(self.reply(108001)[1], [1, [None, [], None]])
        self.assertEqual(self.reply(13000, 'slot')[1], [None, None, None, None])


class TestSettings(unittest.TestCase):
    """Goldens for the setting slice (13001-13004; 13000 already ported).

    Oracle: SettingAction.changeQuickbar/savePanel/saveUiInfo/saveGuaJi
    plus RoleSettingServiceImpl.changeQuickBar/arrayToString/saveUIInfo/
    savePanelConfig/saveGuajiInfo, traced via tools/javap.py against
    dntg_start.jar. All four are fire-and-forget (no reply); the
    quickbar joins with ',' (null/'null' cells read back empty, but
    only '' or skill strings are ever written), grows with '' padding,
    and negative or mistyped slots are silent like Java's throw. The
    three blob saves upsert one column each, like cacheInsert-or-update.
    """
    def setUp(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        self.store = temp_store(cleanups)
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'SunWukong', job='C')
        self.s = make_session(self.store)
        self.s.authed_user, self.s.server_id = 'hero', 'fu1304'

    def bar(self):
        return self.store.get_role_settings(str(self.role_id), 'hero',
                                            'fu1304')['quickbar_info']

    def test_quickbar_fresh_row(self):
        self.assertIsNone(self.s.setting_quickbar([13001, [2, 'fire']]))
        self.assertEqual(self.bar(), ',,fire')

    def test_quickbar_overwrite_and_grow(self):
        self.store.save_role_settings(self.role_id, 'hero', 'fu1304',
                                      quickbar_info='a,b')
        self.assertIsNone(self.s.setting_quickbar([13001, [3, 'd']]))
        self.assertEqual(self.bar(), 'a,b,,d')
        self.assertIsNone(self.s.setting_quickbar([13001, [0, 'x']]))
        self.assertEqual(self.bar(), 'x,b,,d')

    def test_quickbar_bad_slots_silent(self):
        self.store.save_role_settings(self.role_id, 'hero', 'fu1304',
                                      quickbar_info='a')
        self.assertIsNone(self.s.setting_quickbar([13001, [-1, 'x']]))
        self.assertIsNone(self.s.setting_quickbar([13001, ['0', 'x']]))
        self.assertIsNone(self.s.setting_quickbar([13001, [0, 5]]))
        self.assertIsNone(self.s.setting_quickbar([13001, None]))
        self.assertEqual(self.bar(), 'a')

    def test_blob_saves_round_trip(self):
        panel, ui, guaji = ByteArray(b'panel'), ByteArray(b'ui'), \
            ByteArray(b'guaji')
        self.assertIsNone(self.s.setting_panel([13002, panel]))
        self.assertIsNone(self.s.setting_ui([13003, ui]))
        self.assertIsNone(self.s.setting_guaji([13004, guaji]))
        setting = amf3.decode(self.s.role_settings(
            [13000, str(self.role_id)])[4:])
        self.assertEqual(setting,
                         ['13000', [None, panel, ui, guaji]])

    def test_blob_mistyped_silent(self):
        self.assertIsNone(self.s.setting_panel([13002, 'panel']))
        self.assertIsNone(self.s.setting_panel([13002, None]))
        self.assertEqual(amf3.decode(self.s.role_settings(
            [13000, str(self.role_id)])[4:]),
            ['13000', [None, None, None, None]])

    def test_setting_ids_match_map(self):
        from game.protocol import (CMD_ROLE_SETTINGS, CMD_SETTING_QUICKBAR,
                                   CMD_SETTING_PANEL, CMD_SETTING_UI,
                                   CMD_SETTING_GUAJI)
        self.assertEqual(
            (CMD_ROLE_SETTINGS, CMD_SETTING_QUICKBAR, CMD_SETTING_PANEL,
             CMD_SETTING_UI, CMD_SETTING_GUAJI),
            (13000, 13001, 13002, 13003, 13004))


class TestReciveYbClaimAndNameQuery(unittest.TestCase):
    """Phase 1 ports: 35012 reciveYb claim and 12200 queryRoleByName.

    Shapes and codes trace AccountServiceImpl.reciveYb and
    RoleAction.queryRoleByName bytecode (javap).
    """

    def setUp(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        self.store = temp_store(cleanups)
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'SunWukong', job='C', sex=0)
        self.s = make_session(self.store)
        self.s.authed_user, self.s.server_id = 'hero', 'fu1304'

    def row(self):
        return self.store.get_character(self.role_id, 'hero', 'fu1304')

    def test_command_ids_match_map(self):
        from game.protocol import CMD_RECIVE_YB_CLAIM, CMD_ROLE_QUERY_NAME
        self.assertEqual((CMD_RECIVE_YB_CLAIM, CMD_ROLE_QUERY_NAME),
                         (35012, 12200))

    def test_claim_moves_pending_yb_into_lingshi(self):
        self.store.update_character_state(self.role_id, recive_yb=300,
                                          lingshi=100)
        money, reply = self.s.recive_yb_claim()
        self.assertEqual(amf3.decode(money[4:])[0], '32010')
        self.assertEqual(amf3.decode(money[4:])[1][1::2], [400, 0])
        self.assertEqual(amf3.decode(reply[4:]), ['35012', [1, 300]])
        self.assertEqual((self.row()['lingshi'], self.row()['recive_yb']),
                         (400, 0))

    def test_nothing_pending_answers_424016(self):
        self.store.update_character_state(self.role_id, recive_yb=0,
                                          lingshi=0)
        out = self.s.recive_yb_claim()
        self.assertEqual(amf3.decode(out[4:]), ['35012', [0, 424016]])
        self.assertEqual(self.row()['lingshi'], 0)

    def test_negative_pending_resets_to_zero(self):
        self.store.update_character_state(self.role_id, recive_yb=-5)
        out = self.s.recive_yb_claim()
        self.assertEqual(amf3.decode(out[4:]), ['35012', [0, 424016]])
        self.assertEqual(self.row()['recive_yb'], 0)

    def test_lingshi_overflow_answers_424017_and_keeps_state(self):
        big = 9223372036854775807 - 10
        self.store.update_character_state(self.role_id, recive_yb=50,
                                          lingshi=big)
        out = self.s.recive_yb_claim()
        self.assertEqual(amf3.decode(out[4:]), ['35012', [0, 424017]])
        self.assertEqual((self.row()['lingshi'], self.row()['recive_yb']),
                         (big, 50))

    def test_name_query_matches_substring_and_blank_is_empty(self):
        other = self.store.create_character(
            'hero', 'fu1304', 'SunBaby', job='A', sex=1)
        rows = amf3.decode(self.s.role_query_by_name([12200, 'Sun'])[4:])
        self.assertEqual(rows[0], '12200')
        self.assertEqual(sorted(rows[1]), sorted([
            [str(self.role_id), 'SunWukong', 0, '', 1, 'C'],
            [str(other), 'SunBaby', 1, '', 1, 'A']]))
        for query in ('', None):
            out = self.s.role_query_by_name([12200, query])
            self.assertEqual(amf3.decode(out[4:]), ['12200', []])


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
        # 40501 needs no config: the fight-state notice always closes entry.
        self.assertEqual(decoded[4], ['40501', str(self.role_id)])
        self.assertEqual(len(decoded), 5)

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
                         ['20000', '21000', '12004', '12005', '12050', '12000',
                          '40501'])
        # 40501 is the bare role id (send2One), closing the entry burst.
        self.assertEqual(decoded[6], ['40501', str(role_id)])
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
                         ['20000', '21000', '12004', '12005', '40501'])


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
        s.store = store
        return s, role_id

    def bootstrap(self, s, role_id):
        return [amf3.decode(f[4:]) for f in
                s.apply_stage_bootstrap([20000, [str(role_id), '']])]

    def test_entry_pushes_the_captured_mount_frame(self):
        s, role_id = self.build()
        decoded = self.bootstrap(s, role_id)
        self.assertEqual([d[0] for d in decoded],
                         ['20000', '21000', '23009', '12004', '12005',
                          '12050', '12000', '40501'])
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
                          '12000', '40501'])

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

    def pet_fighter(self, s, role_id):
        """The mount pet registered by the entry bootstrap, as a fighter."""
        decoded = self.bootstrap(s, role_id)
        pet_id = decoded[2][1][0][0]
        return s._stage_fighter(pet_id)

    def stored_mount(self, store, role_id):
        return json.loads(store.get_role_stage(role_id)['zuoqi_info'])

    def test_pet_hit_persists_hp_to_the_stored_mount(self):
        s, role_id = self.build()
        pet = self.pet_fighter(s, role_id)
        s._store_fighter_hp(pet, 120.0)
        mount = self.stored_mount(s.store, role_id)
        self.assertEqual(mount, {'id': 1, 'hp': 120, 'deadTime': 0,
                                 'useTime': 0, 'rideOrNo': False})

    def test_persisted_mount_hp_comes_back_on_reentry(self):
        s, role_id = self.build()
        s._store_fighter_hp(self.pet_fighter(s, role_id), 120.0)
        s2 = make_session(s.store, config=s.config)
        s2.authed_user, s2.server_id = 'hero', 'fu1304'
        decoded = self.bootstrap(s2, role_id)
        record = [d for d in decoded if d[0] == '23009'][0][1][0]
        self.assertEqual(record[2], 120.0)   # curHp after the hit
        self.assertEqual(record[3], 500.0)   # maxHp unchanged

    def test_pet_killed_persists_zero_and_stays_off_stage(self):
        s, role_id = self.build()
        s._store_fighter_hp(self.pet_fighter(s, role_id), 0.0)
        self.assertEqual(self.stored_mount(s.store, role_id)['hp'], 0)
        s2 = make_session(s.store, config=s.config)
        s2.authed_user, s2.server_id = 'hero', 'fu1304'
        cmds = [d[0] for d in self.bootstrap(s2, role_id)]
        self.assertNotIn('23009', cmds)

    def test_hit_without_stored_mount_writes_nothing(self):
        s, role_id = self.build(zuoqi_info=None)
        s._pet_state['zuoqi_5_99'] = {
            'max_hp': 500.0, 'hp': 500.0, 'level': 30,
            'owner': str(role_id), 'owner_name': 'x', 'name': 'mount',
            'template_id': 'zuoqi1', 'pos': [43, 32]}
        s._store_fighter_hp(s._stage_fighter('zuoqi_5_99'), 100.0)
        self.assertIsNone(s.store.get_role_stage(role_id)['zuoqi_info'])


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

    def test_skill_fire_ignores_garbage(self):
        # Live combat resolution lives in tests/test_combat.py; without a
        # config the session knows no fighters or skills, so everything is
        # ignored instead of invented.
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


class TestPhase1InitBurst(unittest.TestCase):
    """Phase 1 init-burst replies: bytecode shapes, real config/DB sources."""

    def setUp(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        self.store = temp_store(cleanups)
        self.store.create_account('hero', 'x')
        self.role_id = self.store.create_character('hero', 'fu1304', '悟空')
        cfg = os.path.normpath(os.path.join(os.path.dirname(__file__), '..',
                                            DEFAULT_CONFIG_DIR))
        self.s = make_session(self.store, config=GameConfig(cfg))
        self.s.authed_user, self.s.server_id = 'hero', 'fu1304'

    def test_ping_replies_with_a_heartbeat_interval(self):
        # PingVo.genInterval: 5000 + Random.nextInt(5000); the capture's
        # 6830/8265/9018 all fall in [5000, 9999].
        for _ in range(5):
            env = amf3.decode(self.s.ping()[4:])
            self.assertEqual(env[0], '19000')
            self.assertIsInstance(env[1], int)
            self.assertGreaterEqual(env[1], 5000)
            self.assertLess(env[1], 10000)

    def test_vip_empty_role_is_all_zeros(self):
        env = amf3.decode(self.s.vip_info()[4:])
        self.assertEqual(env, ['62000', [0, 0, [], 0, 0]])

    def test_vip_row_flows_through_with_level_zeroing(self):
        self.store.save_role_vip(self.role_id, vip_level=10, state_day=3,
                                 state_week=1, state_tejia='{"a": 2}',
                                 prop_value=7, tody_prop_value=9)
        env = amf3.decode(self.s.vip_info()[4:])
        self.assertEqual(env, ['62000', [3, 1, [['a', 2]], 7, 9]])
        self.store.save_role_vip(self.role_id, vip_level=0, state_day=3,
                                 state_week=1)
        env = amf3.decode(self.s.vip_info()[4:])
        self.assertEqual(env[1][:2], [0, 0])  # Java zeroes day/week at level 0

    def test_mall_sends_list_with_null_sign_like_java(self):
        # Java's sign is null (classpath loader), so every non-empty
        # category request gets [1, None, raw rows].
        for sign in ('stale', None):
            env = amf3.decode(self.s.mall_info([32000, [sign, '1001']])[4:])
            self.assertEqual(env[0], '32000')
            self.assertEqual(env[1][0], 1)
            self.assertIsNone(env[1][1])
            self.assertTrue(env[1][2])  # real WuPinChuShouBiao rows
            self.assertEqual(env[1][2][0]['modelid'], 1001)
            self.assertIn('sellid', env[1][2][0])

    def test_mall_empty_category_has_no_reply_like_java(self):
        self.assertIsNone(self.s.mall_info([32000, ['x', '']]))
        self.assertIsNone(self.s.mall_info([32000, ['x', None]]))

    def test_zuwu_is_mocks_plus_zero_fragments(self):
        env = amf3.decode(self.s.zuwu_info()[4:])
        self.assertEqual(env[0], '111000')
        entries, frags = env[1]
        self.assertEqual(frags, 0)
        self.assertTrue(entries)  # one mock per ZuWuShuxing type
        for entry in entries:
            self.assertEqual(entry[1:4], [0, 0, 0])

    def test_recive_yb_reads_the_role_row(self):
        self.s.feed(CAPTURED_INITKEY)
        out = self.s.feed(frame(
            self.s.cipher.encode(amf3.encode([35011, None]))))
        self.assertEqual(amf3.decode(out[0][4:]), ['35011', 0])


class MallBuyTest(unittest.TestCase):
    """Command 32001 goldens: MallAction guards + MallServiceImpl.buyGoods.

    Oracle: MallAction.buyGoods request parsing/gates and
    MallServiceImpl.buyGoods/checkConsume/checkExpireTime/BuyMallOutput
    shapes via tools/javap.py. Portable subset: no guild (BANGGONG fails
    closed 430412) and no coupon discount table (present coupon fails
    closed 430418; missing coupon 430416; coupon off YB 430417).
    """

    def setUp(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        self.store = temp_store(cleanups)
        self.store.create_account('hero', 'x')
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56, tongqian=10000,
            bind_lingshi=5000, lingshi=1000)
        cfg = os.path.normpath(os.path.join(os.path.dirname(__file__), '..',
                                            DEFAULT_CONFIG_DIR))
        self.s = Session(
            conn_id=7, check_sign=check_sign,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=1234567890000,
            save_role_state=self.store.update_character_state,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            get_role_bag_slot_by_bag_id=
            self.store.get_role_bag_slot_by_bag_id,
            update_role_bag_slot=self.store.update_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            config=GameConfig(cfg))
        self.s.authed_user, self.s.server_id = 'hero', 'fu1304'
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=30)

    def buy(self, *args):
        out = self.s.mall_buy([32001, list(args)])
        self.assertIsNotNone(out)
        return amf3.decode(out[4:])

    def role(self):
        return self.store.list_roles('hero', 'fu1304')[0]

    def bag_counts(self, goods):
        return sum(s['count'] for s in
                   self.store.get_role_bag_slots(self.role_id, 1, 150)
                   if s['goods_id'] == goods)

    def test_yb_buy_deducts_lingshi_and_grants(self):
        # xuechi @ npc 2000: moneytype 2, gold 15.
        self.assertEqual(self.buy('xuechi', 2, '2000', '', 2, -1),
                         ['32001', [1, ['xuechi', 2, 30, 2]]])
        self.assertEqual(self.role()['lingshi'], 970)
        self.assertEqual(self.bag_counts('xuechi'), 2)

    def test_yxb_buy_deducts_tongqian(self):
        # hpadd001 @ npc 3000: moneytype 1, coin 100.
        self.assertEqual(self.buy('hpadd001', 1, '3000', '', 1, -1),
                         ['32001', [1, ['hpadd001', 1, 100, 1]]])
        self.assertEqual(self.role()['tongqian'], 9900)

    def test_bind_yb_buy_binds_the_grant(self):
        # xuechi merges {2: 15, 3: 75} across its two 2000 rows.
        self.assertEqual(self.buy('xuechi', 1, '2000', '', 3, -1),
                         ['32001', [1, ['xuechi', 1, 75, 3]]])
        self.assertEqual(self.role()['bind_lingshi'], 4925)
        slots = [s for s in
                 self.store.get_role_bag_slots(self.role_id, 1, 150)
                 if s['goods_id'] == 'xuechi']
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0]['bind'], 1)

    def test_banggong_buy_fails_closed_without_guild(self):
        # 72shengming1 @ npc 4000 prices in banggong; no guild system.
        self.assertEqual(self.buy('72shengming1', 1, '4000', '', 5, -1),
                         ['32001', [0, 430412]])
        self.assertEqual(self.role()['lingshi'], 1000)

    def test_unknown_goods_id(self):
        self.assertEqual(self.buy('no-such-goods', 1, '2000', '', 2, -1),
                         ['32001', [0, 430201]])

    def test_wrong_npc_is_not_in_buy_list(self):
        self.assertEqual(self.buy('xuechi', 1, '3000', '', 2, -1),
                         ['32001', [0, 430402]])

    def test_unlisted_money_type_is_account_type_error(self):
        self.assertEqual(self.buy('hpadd001', 1, '3000', '', 2, -1),
                         ['32001', [0, 430401]])

    def test_short_yb_replies_yb_no_enought(self):
        self.store.update_character_state(self.role_id, lingshi=10)
        self.assertEqual(self.buy('xuechi', 1, '2000', '', 2, -1),
                         ['32001', [0, 430403]])
        self.assertEqual(self.role()['lingshi'], 10)

    def test_short_tongqian_replies_jb_no_enought(self):
        self.store.update_character_state(self.role_id, tongqian=10)
        self.assertEqual(self.buy('hpadd001', 1, '3000', '', 1, -1),
                         ['32001', [0, 430208]])

    def test_full_bag_replies_slot_code(self):
        self.store.save_role_bag_state(self.role_id, bag_capacity=0,
                                       storage_capacity=30)
        self.assertEqual(self.buy('xuechi', 1, '2000', '', 2, -1),
                         ['32001', [0, 430214]])
        self.assertEqual(self.role()['lingshi'], 1000)

    def test_coupon_off_yb_cannot_be_used(self):
        self.assertEqual(self.buy('xuechi', 1, '2000', '', 1, -1, 'g1'),
                         ['32001', [0, 430417]])

    def test_missing_coupon_row_is_expired(self):
        self.assertEqual(self.buy('xuechi', 1, '2000', '', 2, -1, 'g9'),
                         ['32001', [0, 430416]])

    def test_entry_guards_are_silent(self):
        self.assertIsNone(self.s.mall_buy([32001, ['', 1, '2000', '', 2,
                                                    -1]]))
        self.assertIsNone(self.s.mall_buy([32001, ['xuechi', 1, '', '', 2,
                                                    -1]]))
        self.assertIsNone(self.s.mall_buy([32001, ['xuechi', 0, '2000', '',
                                                    2, -1]]))
        self.assertIsNone(self.s.mall_buy([32001, ['xuechi', 1, '2000', '',
                                                    -1, -1]]))
        self.assertIsNone(self.s.mall_buy([32001, ['xuechi', 2, '2000', '',
                                                    2, 0]]))
        self.assertIsNone(self.s.mall_buy([32001, ['xuechi', 1, '2000', '',
                                                    9, -1]]))

    def test_dispatched_as_32001(self):
        self.s.feed(CAPTURED_INITKEY)
        out = self.s.feed(frame(
            self.s.cipher.encode(amf3.encode(
                [32001, ['xuechi', 1, '2000', '', 2, -1]]))))
        self.assertEqual(amf3.decode(out[0][4:]),
                         ['32001', [1, ['xuechi', 1, 15, 2]]])


class TestEntryBuffs(unittest.TestCase):
    """Phase 2 entry pushes: 42100 buff flush, 42005 skill cooldown, 40501.

    Shapes from FightOutputWrapper.buffChange / skillReadyFire /
    RoleEventManager.enterFightState2 bytecode; the entry order
    (12000 -> 42100 -> 42005 -> 40501) from tap-decoded.txt lines 12-24.
    """

    LEVEL = 5

    def build(self, vip_level=None):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        role_id = store.create_character(
            'hero', 'fu1304', 'Wukong', job='A', sex=0, face=1,
            level=self.LEVEL, exp=0, hp=120, mp=60, max_hp=120,
            max_mp=60, zhenqi=77)
        if vip_level is not None:
            store.save_role_vip(role_id, vip_level=vip_level)
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
        with open(os.path.join(cfg_dir, 'sys_config',
                               'XiaoGuoBiao.jat'), 'wb') as f:
            f.write(amf3.encode([Obj(effectid='birthprotect', lasttime=10000),
                                 Obj(effectid='vip010', effectlevel='010')]))
        with open(os.path.join(cfg_dir, 'sys_config',
                               'vipbiao.jat'), 'wb') as f:
            # VipConfig row: replaceVipAttribute reads the vipbuff cell.
            f.write(amf3.encode([Obj(lv=10, vipbuff='vip010', zhanli=1600)]))
        with open(os.path.join(cfg_dir, 'sys_config', 'CdBiao.jat'), 'wb') as f:
            f.write(amf3.encode([Obj(cdid='t070', cdtime=700)]))
        with open(os.path.join(cfg_dir, 'sys_config', 'JiNengBiao.jat'),
                   'wb') as f:
            f.write(amf3.encode([Obj(skilltype='normal003', cd1='t070')]))
        s = make_session(store, config=GameConfig(cfg_dir))
        s.authed_user, s.server_id = 'hero', 'fu1304'
        return s, role_id

    def bootstrap(self, s, role_id):
        return [amf3.decode(f[4:]) for f in
                s.apply_stage_bootstrap([20000, [str(role_id), '']])]

    def test_vip_role_gets_vip_plus_birthprotect_then_fight_state(self):
        s, role_id = self.build(vip_level=10)
        decoded = self.bootstrap(s, role_id)
        # No attack_skill on the role row, so 42005 is skipped, not faked.
        self.assertEqual([d[0] for d in decoded],
                         ['20000', '21000', '12004', '12005', '12050',
                          '12000', '42100', '40501'])
        buff = decoded[6]
        self.assertEqual(buff[0], '42100')
        self.assertEqual(buff[1][0], str(role_id))
        self.assertIsNone(buff[1][2])  # no removals at entry
        adds = buff[1][1]
        # Capture order: vip buff first, birthprotect last; ids are the
        # session-local buff_<stage>_<seq> shape (Java's counters are
        # JVM-global and unreproducible).
        self.assertEqual([a[1] for a in adds], ['vip010', 'birthprotect'])
        self.assertEqual(adds[0], ['buff_1_1', 'vip010', -1.0, 1,
                                   str(role_id)])
        self.assertEqual(adds[1], ['buff_1_2', 'birthprotect', 10000.0, 1,
                                   str(role_id)])
        self.assertEqual(decoded[7], ['40501', str(role_id)])

    def test_role_without_vip_gets_birthprotect_alone(self):
        s, role_id = self.build()
        decoded = self.bootstrap(s, role_id)
        buff = next(d for d in decoded if d[0] == '42100')
        self.assertEqual([a[1] for a in buff[1][1]], ['birthprotect'])

    def test_skill_cd_uses_live_attack_speed(self):
        s, role_id = self.build(vip_level=10)
        roles = s.get_roles('hero', 'fu1304')
        role = dict(next(r for r in roles
                         if str(r.get('id')) == str(role_id)))
        role['attack_skill'] = 'normal003'
        env = amf3.decode(s.skill_cd_frame(role)[4:])
        # attackrate 3 -> int(700 / (1 + 3/2000)) = int(698.95) = 698.
        self.assertEqual(env, ['42005', ['normal003', 698]])

    def test_skill_cd_skipped_without_role_skill_state(self):
        s, role_id = self.build()
        roles = s.get_roles('hero', 'fu1304')
        role = next(r for r in roles if str(r.get('id')) == str(role_id))
        with self.assertLogs('game', level='INFO'):
            self.assertIsNone(s.skill_cd_frame(role))

    def test_buff_value_tick_shape(self):
        s, _ = self.build()
        env = amf3.decode(s.buff_value_frame('r1', 'propbuff_1_3', 328576)[4:])
        self.assertEqual(env, ['42102', ['r1', 'propbuff_1_3', 328576.0]])


if __name__ == '__main__':
    unittest.main()

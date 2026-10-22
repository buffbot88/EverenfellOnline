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
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def read_frames(data, allow_policy=False):
    """u32be framing (ex-tools/decode-tap.py): split policy/frames."""
    frames, offset = [], 0
    if allow_policy and data.startswith(b'<'):
        end = data.find(b'\x00')
        if end < 0:
            return frames, offset
        frames.append(('policy', data[:end + 1]))
        offset = end + 1
    while len(data) - offset >= 4:
        length = struct.unpack('>I', data[offset:offset + 4])[0]
        if length > 48 * 1024 * 1024:
            raise ValueError(f'invalid frame length {length} at {offset}')
        end = offset + 4 + length
        if end > len(data):
            break
        frames.append(('frame', data[offset + 4:end]))
        offset = end
    return frames, offset


def decode_server(frames):
    """Plaintext server frames to AMF (ex-tools/decode-tap.py)."""
    from game.amf3 import Reader
    for kind, payload in frames:
        if kind == 'policy':
            yield ('policy', payload)
        elif len(payload) == 36:
            yield ('key', payload.decode('ascii', 'replace'))
        else:
            reader = Reader(payload)
            try:
                while reader.p < len(payload):
                    yield ('message', reader.read())
            except Exception as exc:
                yield ('error',
                       f'{len(payload)} bytes at AMF offset {reader.p}: {exc}')

from unittest import mock

from auth import check_sign, generate_sign, hash_password, verify_password
from db import Store
from game import amf3
from game.amf3 import ByteArray, Obj
from game.cipher import SimpleEncrypt, new_key
from game.config import DEFAULT_CONFIG_DIR, GameConfig
from game.protocol import DEFAULT_MAP_TYPE, Session, frame

# Live-captured first frame from the original client (bridge LOG_PACKETS=1).
CAPTURED_INITKEY = bytes.fromhex('00000009060f494e49544b4559')
# Login signs are only valid within SIGN_WINDOW_S of now, so tests use a fresh stamp.
NOW_TS = str(int(time.time()))


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
        'get_role_bag_slots': store.get_role_bag_slots,
        'get_role_bag_state': store.get_role_bag_state,
        'insert_role_bag_slot': store.insert_role_bag_slot,
        'update_role_bag_slot': store.update_role_bag_slot,
        'delete_role_bag_slot': store.delete_role_bag_slot,
        'get_role_loginlibao': store.get_role_loginlibao,
        'save_role_loginlibao': store.save_role_loginlibao,
        'get_role_lvlibao': store.get_role_lvlibao,
        'save_role_lvlibao': store.save_role_lvlibao,
        'get_role_dengluqi': store.get_role_dengluqi,
        'save_role_dengluqi': store.save_role_dengluqi,
        'get_role_online_reward': store.get_role_online_reward,
        'save_role_online_reward': store.save_role_online_reward,
        'get_role_husong': store.get_role_husong,
        'save_role_husong': store.save_role_husong,
        'get_role_loginlingjiang': store.get_role_loginlingjiang,
        'save_role_loginlingjiang': store.save_role_loginlingjiang,
        'get_role_touxian': store.get_role_touxian,
        'save_role_touxian': store.save_role_touxian,
        'get_role_guangyi': store.get_role_guangyi,
        'save_role_guangyi': store.save_role_guangyi,
        'get_role_baixian': store.get_role_baixian,
        'save_role_baixian': store.save_role_baixian,
        'get_role_zhuihui': store.get_role_zhuihui,
        'save_role_zhuihui': store.save_role_zhuihui,
        'get_role_dafuwong': store.get_role_dafuwong,
        'save_role_dafuwong': store.save_role_dafuwong,
        'get_role_xianshibuy': store.get_role_xianshibuy,
        'save_role_xianshibuy': store.save_role_xianshibuy,
        'get_xianshi_buy': store.get_xianshi_buy,
        'save_xianshi_buy': store.save_xianshi_buy,
        'list_role_email': store.list_role_email,
        'get_role_email': store.get_role_email,
        'save_role_email': store.save_role_email,
        'update_role_email': store.update_role_email,
        'delete_role_email': store.delete_role_email,
        'get_role_shenjiang': store.get_role_shenjiang,
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
        ts, user = NOW_TS, 'hero'
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
        out = s.feed(self.login_frame(s, 'hero', NOW_TS, 'wrong'))
        env = amf3.decode(out[0][4:])
        self.assertEqual(env[1], [0, '16002'])  # InOutput.signError shape

    def test_login_sends_no_bootstrap(self):
        # The Java captures (session-20261018-040230,
        # session-20261020-072313) show the 13000/32010 pushes arriving
        # after the client sends 10003, just before the 10003 reply — never
        # with the login reply. Pushing them at login wedged the stock
        # client at a black screen (no 21000 ever sent).
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        store.create_account('hero', hash_password('pw'))
        store.create_character(
            'hero', 'fu1304', 'SunWukong', job='C', tongqian=4509290,
            lingshi=9986377, bind_lingshi=360, recive_yb=0)
        s = make_session(store)
        s.feed(CAPTURED_INITKEY)
        out = s.feed(self.login_frame(s, 'hero', NOW_TS,
                                      generate_sign('hero', NOW_TS)))
        self.assertEqual(len(out), 1)
        self.assertEqual(amf3.decode(out[0][4:])[0], '10001')
        self.assertEqual(s.authed_user, 'hero')

    def test_enter_world_pushes_java_bootstrap_before_10003_reply(self):
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
        s.authed_user, s.server_id = 'hero', 'fu1304'
        out = s.enter_world([10003, str(role_id)])
        self.assertEqual(len(out), 3)
        messages = [amf3.decode(packet[4:]) for packet in out]
        self.assertEqual([msg[0] for msg in messages],
                         ['13000', '32010', '10003'])
        self.assertEqual(messages[1], ['32010', [4509290.0, 9986377.0, 360.0,
                                                  1]])
        self.assertEqual(messages[0], ['13000', [None, panel, None, None]])
        self.assertEqual(store.get_role_settings(str(role_id), 'someone-else',
                                                'fu1304'), None)

    def test_response_is_plaintext_not_enciphered(self):
        # Regression guard for the asymmetric protocol: server->client must
        # be parseable raw. If this ever fails, responses got encrypted again
        # and the Flash client aborts socketData with "Invalid object".
        s = make_session()
        s.feed(CAPTURED_INITKEY)
        ts, user = NOW_TS, 'hero'
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
        ts, user = NOW_TS, 'hero'
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
        decoded = list(decode_server([('frame', framed)]))
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
        frames, used = read_frames(req, allow_policy=True)
        self.assertEqual(frames, [('policy', req)])
        self.assertEqual(used, len(req))
        frames, used = read_frames(reply + frame(b'data'),
                                              allow_policy=True)
        self.assertEqual(frames[0], ('policy', reply))
        self.assertEqual(frames[1], ('frame', b'data'))
        self.assertEqual(list(decode_server(frames[:1])),
                         [('policy', reply)])

    def test_frame_reader_handles_fragment_and_coalesced_frames(self):
        one, two = b'first', b'second'
        data = frame(one) + frame(two) + frame(b'incomplete')[:7]
        frames, used = read_frames(data)
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
        # CreateAccountOutPut.getMoneyChange: Longs as doubles, NOTIFYORNOT 1.
        self.assertEqual(self.reply(32010)[1], [0.0, 0.0, 0.0, 1])

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
        # No configmonsters/vitals here: the ack plus the 12005 shanbi push.
        self.assertEqual(len(out), 2)
        result = amf3.decode(out[0][4:])
        self.assertEqual(result, ['21000', [1, 1, 1]])
        self.assertEqual(amf3.decode(out[1][4:]), ['12005', [0]])

        # An unknown/unowned role id still gets nothing (no role to place).
        self.assertIsNone(session.change_stage([21000, '999']))
        # A map the legacy table does not list still gets the frame Java always
        # sends; the type falls back to the documented default rather than
        # leaving the client with no scene entry at all.
        store.update_character_state(role_id, map_id='999')
        fallback = session.change_stage([21000, str(role_id)])
        fallback = fallback if isinstance(fallback, bytes) else fallback[0]
        self.assertEqual(amf3.decode(fallback[4:]),
                         ['21000', [1, 1, DEFAULT_MAP_TYPE]])

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
        # Java answers 20000 bare; the scene follows the client's own 21000.
        self.assertEqual(len(out), 1)
        self.assertEqual(amf3.decode(out[0][4:]),
                         ['20000', [1, '5', [44, 33]]])
        tail = session.change_stage([21000, str(role_id)])
        decoded = [amf3.decode(f[4:]) for f in tail]
        self.assertEqual([d[0] for d in decoded],
                         ['21000', '12004', '12005'])
        self.assertEqual(decoded[0], ['21000', [1, 1, 1]])
        self.assertEqual(decoded[1], ['12004', [str(role_id), 5226.0, 5466.0,
                                                 1811.0, 1811.0]])
        # Tap order continues with the shanbi value (none stored for this role).
        self.assertEqual(decoded[2], ['12005', [0]])

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
        # The 10003 reply is the last frame after the 13000/32010 bootstrap.
        entry = amf3.decode(s.enter_world([10003, str(role_id)])[-1][4:])
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
        entry = amf3.decode(s.enter_world([10003, str(role_id)])[-1][4:])
        self.assertEqual(entry[0], '10003')
        # StageControllOutputWrapper.login: vip from role_vip (none -> 0),
        # recharge from unmigrated rows ([0.0, 0.0]), exp Long as double.
        self.assertEqual(entry[1][1],
                         ['', 1, 10692892.0, 0, 'C', False, 0, 0,
                          [0.0, 0.0], 0])
        self.assertEqual(entry[1][2], ['5', 44, 33])
        money = amf3.decode(s.money_info()[4:])
        self.assertEqual(money, ['32010', [4509290.0, 9986377.0, 360.0, 1]])
        apply = amf3.decode(s.apply_stage([20000, [str(role_id), '5']])[4:])
        self.assertEqual(apply, ['20000', [1, '5', [44, 33]]])
        scene = s.change_stage([21000, str(role_id)])
        scene = scene if isinstance(scene, bytes) else scene[0]
        self.assertEqual(amf3.decode(scene[4:]), ['21000', [1, 1, 1]])
        # RoleAdditionalDataOutput.info: no mount/pk/guild state migrated.
        extra = amf3.decode(s.role_extra_info()[4:])
        self.assertEqual(extra, ['12011', [0, 0, 0, 0, 0, 0, 0,
                                           None, None, 0, 1]])
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
        self.assertEqual(self.reply(108001)[1], [1, [0, [['1', 0, 1]], None]])
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
        self.assertEqual(amf3.decode(money[4:])[1][1::2], [400.0, 1])
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
        entry = amf3.decode(
            self.s.enter_world([10003, str(self.role_id)])[-1][4:])
        self.assertEqual(entry[0], '10003')
        self.assertEqual(entry[1][2], ['2', 10, 150])
        # level/exp come from the migrated role row.
        self.assertEqual(entry[1][1][1], 7)
        self.assertEqual(entry[1][1][2], 1310)

    def test_apply_stage_keeps_migrated_coordinates(self):
        apply = amf3.decode(
            self.s.apply_stage([20000, [str(self.role_id), '']])[4:])
        self.assertEqual(apply, ['20000', [1, '2', [10, 150]]])

    def test_apply_stage_answers_bare_like_java(self):
        # The 20000 reply carries no scene: the client sends 21000 when it
        # is ready, and only then does the server push the scene tail.
        reply = self.s.apply_stage([20000, [str(self.role_id), '']])
        self.assertEqual(amf3.decode(reply[4:]),
                         ['20000', [1, '2', [10, 150]]])

    def test_change_stage_pushes_hp_mp_from_the_stage_row(self):
        frames = self.s.change_stage([21000, str(self.role_id)])
        self.assertIsInstance(frames, tuple)
        decoded = [amf3.decode(f[4:]) for f in frames]
        # The scene entry is pushed for map 2 too, not only for map 5.
        self.assertEqual(decoded[0], ['21000', [1, 1, DEFAULT_MAP_TYPE]])
        # Tap order after the scene entry: hp/mp as doubles, then shanbi.
        # This session has no config, so 12050/12000 are skipped.
        self.assertEqual(decoded[1], ['12004', [str(self.role_id), 144.0, 144.0,
                                                 96.0, 96.0]])
        self.assertEqual(decoded[2], ['12005', [0]])
        self.assertEqual(len(decoded), 3)

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
        with open(os.path.join(cfg_dir, 'sys_config',
                               'XiaoGuoBiao.jat'), 'wb') as f:
            f.write(amf3.encode([Obj(effectid='birthprotect',
                                     lasttime=10000)]))
        s = make_session(store, config=GameConfig(cfg_dir))
        s.authed_user, s.server_id = 'hero', 'fu1304'
        return s, role_id

    def test_entry_pushes_the_captured_stats_sequence(self):
        s, role_id = self.build()
        first = amf3.decode(s.apply_stage([20000, [str(role_id), '']])[4:])
        self.assertEqual(first, ['20000', [1, '0', [57, 148]]])
        tail = s.change_stage([21000, str(role_id)])
        decoded = [amf3.decode(f[4:]) for f in tail]
        self.assertEqual([d[0] for d in decoded],
                         ['21000', '12004', '12005', '12050', '12000',
                          '42100'])
        self.assertEqual(decoded[1][1], [str(role_id), 120.0, 120.0,
                                         60.0, 60.0])
        self.assertEqual(decoded[2], ['12005', [0]])    # shanbi_val: none stored
        self.assertEqual(decoded[3], ['12050', [77, 100000]])  # zhenqi, cap
        self.assertEqual(decoded[4][1], {
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

    def test_without_a_level_row_only_vitals_and_shanbi_are_pushed(self):
        s, role_id = self.build()
        s.config = None
        tail = s.change_stage([21000, str(role_id)])
        decoded = [amf3.decode(f[4:]) for f in tail]
        self.assertEqual([d[0] for d in decoded],
                         ['21000', '12004', '12005'])

    def test_xianjie_fight_feeds_slot_11(self):
        # ZhanDouLiServiceImpl.getxianjie: the stress role's active
        # xianjie 1 bag computes to the captured 122 (getFight over the
        # XianJieConfig attributes with ZhanLiXiShu factors).
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        role_id = store.create_character('hero', 'fu1304', 'Wukong', job='A')
        store.save_role_xianjiechenhao(role_id, xianjie_id='["1"]')
        cfg_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cfg_dir, ignore_errors=True)
        os.makedirs(os.path.join(cfg_dir, 'sys_config'))
        with open(os.path.join(cfg_dir, 'sys_config',
                               'xianjie.jat'), 'wb') as f:
            f.write(amf3.encode([
                Obj(id=1, shuxing='hitpoints:60;mana:60;physicdamage:30;'
                                 'physicdefence:15;critical:8;volt:8;'
                                 'attackrate:3;velocity:10')]))
        with open(os.path.join(cfg_dir, 'sys_config',
                               'ZhanLiXiShu.jat'), 'wb') as f:
            f.write(amf3.encode([
                Obj(name='hitpoints', factor=0.25),
                Obj(name='mana', factor=0.25),
                Obj(name='physicdamage', factor=0.5),
                Obj(name='physicdefence', factor=1.0),
                Obj(name='critical', factor=2.0),
                Obj(name='volt', factor=2.0),
                Obj(name='attackrate', factor=10.0),
                Obj(name='velocity', factor=0.0)]))
        s = make_session(store, config=GameConfig(cfg_dir))
        s.authed_user, s.server_id = 'hero', 'fu1304'
        env = amf3.decode(s.fighting_info()[4:])
        self.assertEqual(env[1][11], 122)
        # No xianjie row stays 0 like Java's empty source.
        s2 = make_session(temp_store(cleanups), config=GameConfig(cfg_dir))
        self.assertEqual(amf3.decode(s2.fighting_info()[4:])[1][11], 0)


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
        first = amf3.decode(s.apply_stage([20000, [str(role_id), '']])[4:])
        tail = s.change_stage([21000, str(role_id)])
        tail = list(tail) if isinstance(tail, tuple) else [tail]
        return [first] + [amf3.decode(f[4:]) for f in tail]

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
        # Live combat resolution is locked (see the v1.4 lock decision);
        # without a config the session knows no fighters or skills, so
        # everything is ignored instead of invented.
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

    def test_mall_sends_list_with_sign_like_java(self):
        # The sign comes from the gameconfig sign service; a stale (or no)
        # sign gets [1, sign, raw rows], a matching sign gets [-1, category].
        from game.config import MALL_SIGN
        for sign in ('stale', None):
            env = amf3.decode(self.s.mall_info([32000, [sign, '1001']])[4:])
            self.assertEqual(env[0], '32000')
            self.assertEqual(env[1][0], 1)
            self.assertEqual(env[1][1], MALL_SIGN)
            self.assertTrue(env[1][2])  # real WuPinChuShouBiao rows
            self.assertEqual(env[1][2][0]['modelid'], 1001)
            self.assertIn('sellid', env[1][2][0])
        echo = amf3.decode(self.s.mall_info([32000, [MALL_SIGN, '1001']])[4:])
        self.assertEqual(echo, ['32000', [-1, '1001']])

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


class MallBuyBackTest(unittest.TestCase):
    """Commands 32002/32003/32004/32006 goldens: GoodsBuyBackAction + service.

    Oracle: GoodsBuyBackAction sellGoodsBuyBack/goodsHuiGou/getGoodsBuyBack
    parsing, BuyBackModuleInit routes (32002/32003/32004), MallModuleInit
    (32006), GoodsBuyBackServiceImpl add/remove/getAll/model2Entity, the
    GoodsBackComppator createtime-ascending eviction at 27 rows, and
    GetGoodsBuyBackOutPut getData/getError shapes via tools/javap.py.
    32005 is a server push with no inbound route (ledger push-only, like
    30104/30105); 32006 stays null (the guild mall that writes
    RoleMallBangpai is unmigrated, and Java answers null without the row).
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
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            get_role_buyback_all=self.store.get_role_buyback_all,
            get_role_buyback=self.store.get_role_buyback,
            insert_role_buyback=self.store.insert_role_buyback,
            delete_role_buyback=self.store.delete_role_buyback,
            config=GameConfig(cfg))
        self.s.authed_user, self.s.server_id = 'hero', 'fu1304'
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=30)

    def role(self):
        return self.store.list_roles('hero', 'fu1304')[0]

    def seed_bag(self, bag_id, goods, count, slot=1, bind=0):
        self.store.save_role_bag_slots(
            self.role_id, [{'slot_num': slot, 'bag_id': bag_id,
                            'goods_id': goods, 'count': count, 'bind': bind}])

    def seed_buyback(self, bid, goods, count, created, bind=0):
        self.store.insert_role_buyback(
            self.role_id, {'buyback_id': bid, 'slot_num': 5,
                           'goods_id': goods, 'count': count, 'bind': bind,
                           'expire_time': None, 'rare_level': 0,
                           'item_level': 0, 'attributes': None,
                           'createtime': created})

    @staticmethod
    def assoc(m):
        """Unwrap the decoder's dynamic-object envelope around formart maps."""
        return m.get('__assoc__', m)

    def sell(self, *args):
        out = self.s.buyback_sell([32002, list(args)])
        if out is None:
            return None
        if isinstance(out, tuple):
            return tuple(amf3.decode(f[4:]) for f in out)
        return amf3.decode(out[4:])

    def huigou(self, *args):
        out = self.s.buyback_huigou([32003, list(args)])
        return None if out is None else amf3.decode(out[4:])

    def test_sell_pays_recycle_and_moves_row_to_buyback(self):
        # xuechi recycles at 10; a stack of 2 pays 20 YXB.
        self.seed_bag('g1', 'xuechi', 2)
        env = self.sell('g1', 1)
        self.assertEqual(env[0], '32002')
        self.assertEqual(env[1][0], 1)
        sold = self.assoc(env[1][1])
        self.assertEqual((sold['0'], sold['1'], sold['3'], sold['4']),
                         ('xuechi', 'g1', 2, str(self.role_id)))
        self.assertIsNone(
            self.store.get_role_bag_slot_by_bag_id(self.role_id, 'g1'))
        kept = self.store.get_role_buyback(self.role_id, 'g1')
        self.assertEqual((kept['goods_id'], kept['count']), ('xuechi', 2))
        self.assertEqual(self.role()['tongqian'], 10020)

    def test_sell_count_arg_is_parsed_but_ignored(self):
        self.seed_bag('g1', 'xuechi', 2)
        env = self.sell('g1', 99)
        self.assertEqual(env[1][0], 1)
        self.assertIsNone(
            self.store.get_role_bag_slot_by_bag_id(self.role_id, 'g1'))
        self.assertEqual(self.role()['tongqian'], 10020)

    def test_sell_missing_row_is_silent(self):
        self.assertIsNone(self.sell('nope', 1))
        self.assertEqual(self.role()['tongqian'], 10000)

    def test_sell_unknown_goods_replies_430405_with_bag_intact(self):
        self.seed_bag('g1', 'no-such-goods', 1)
        self.assertEqual(self.sell('g1', 1), ['32002', [0, '430405']])
        self.assertIsNotNone(
            self.store.get_role_bag_slot_by_bag_id(self.role_id, 'g1'))
        self.assertEqual(
            self.store.get_role_buyback_all(self.role_id), [])

    def test_sell_evicts_oldest_with_a_32005_push_at_27(self):
        for i in range(1, 28):
            self.seed_buyback('b%d' % i, 'xuechi', 1, i)
        self.seed_bag('g1', 'xuechi', 1)
        env = self.sell('g1', 1)
        self.assertIsInstance(env, tuple)
        self.assertEqual(len(env), 2)
        self.assertEqual(env[0][0], '32005')
        self.assertEqual(env[0][1][0], 'b1')
        self.assertEqual(self.assoc(env[0][1][1])['1'], 'g1')
        self.assertEqual(env[1][0], '32002')
        self.assertEqual(env[1][1][0], 1)
        self.assertEqual(self.assoc(env[1][1][1]),
                         self.assoc(env[0][1][1]))
        self.assertIsNone(self.store.get_role_buyback(self.role_id, 'b1'))
        kept = self.store.get_role_buyback_all(self.role_id)
        self.assertEqual(len(kept), 27)
        self.assertEqual(kept[0]['buyback_id'], 'b2')
        self.assertEqual(kept[-1]['buyback_id'], 'g1')

    def test_huigou_restores_the_stack_for_recycle_times_count(self):
        self.seed_buyback('g1', 'xuechi', 2, 7)
        env = self.huigou('g1')
        self.assertEqual(env[0], '32003')
        self.assertEqual(env[1][0], 1)
        self.assertEqual(env[1][1], 'g1')
        record = env[1][2][0]
        self.assertEqual(len(record), 18)
        self.assertEqual(record[0], 'xuechi')
        self.assertEqual(record[1], 'g1')
        self.assertEqual(record[3], 2)
        self.assertEqual(record[4], str(self.role_id))
        self.assertEqual(env[1][3], 20)
        self.assertEqual(self.role()['tongqian'], 9980)
        self.assertIsNone(self.store.get_role_buyback(self.role_id, 'g1'))
        held = [s for s in
                self.store.get_role_bag_slots(self.role_id, 1, 150)
                if s['goods_id'] == 'xuechi']
        self.assertEqual(sum(s['count'] for s in held), 2)

    def test_huigou_missing_row_is_silent(self):
        self.assertIsNone(self.huigou('nope'))
        self.assertEqual(self.role()['tongqian'], 10000)

    def test_huigou_short_money_replies_1003_with_row_intact(self):
        self.seed_buyback('g1', 'xuechi', 2, 7)
        self.store.update_character_state(self.role_id, tongqian=10)
        self.assertEqual(self.huigou('g1'), ['32003', [0, '1003']])
        self.assertIsNotNone(
            self.store.get_role_buyback(self.role_id, 'g1'))
        self.assertEqual(self.role()['tongqian'], 10)

    def test_huigou_full_bag_replies_1006(self):
        # zj0013 stacks to 1, so a zero-capacity bag has no room.
        self.store.save_role_bag_state(self.role_id, bag_capacity=0,
                                       storage_capacity=30)
        self.seed_buyback('g9', 'zj0013', 1, 7)
        self.assertEqual(self.huigou('g9'), ['32003', [0, '1006']])
        self.assertIsNotNone(
            self.store.get_role_buyback(self.role_id, 'g9'))

    def test_list_empty_is_null_and_rows_come_oldest_first(self):
        out = self.s.buyback_list()
        self.assertEqual(amf3.decode(out[4:]), ['32004', None])
        self.seed_buyback('new', 'xuechi', 1, 9)
        self.seed_buyback('old', 'xuechi', 1, 3)
        out = self.s.buyback_list()
        env = amf3.decode(out[4:])
        self.assertEqual(env[0], '32004')
        self.assertEqual([r[1] for r in env[1]], ['old', 'new'])

    def test_gonghui_mall_count_stays_null_without_guild(self):
        out = self.s.gonghui_mall_count()
        self.assertEqual(amf3.decode(out[4:]), ['32006', None])

    def test_entry_guards_are_silent(self):
        self.assertIsNone(self.s.buyback_sell([32002, []]))
        self.assertIsNone(self.s.buyback_sell([32002, ['g1']]))
        self.assertIsNone(self.s.buyback_sell([32002, [123, 1]]))
        self.assertIsNone(self.s.buyback_sell([32002, ['g1', 'x']]))
        self.assertIsNone(self.s.buyback_sell([32002, ['g1', True]]))
        self.assertIsNone(self.s.buyback_huigou([32003, []]))
        self.assertIsNone(self.s.buyback_huigou([32003, [123]]))

    def test_dispatched_as_32004(self):
        self.s.feed(CAPTURED_INITKEY)
        out = self.s.feed(frame(
            self.s.cipher.encode(amf3.encode([32004, []]))))
        self.assertEqual(amf3.decode(out[0][4:]), ['32004', None])


class TestEntryBuffs(unittest.TestCase):
    """Entry buff flush 42100 after the 12000 attribute map.

    Shape from FightOutputWrapper.buffChange bytecode; position from both
    captures (fresh map-2 entry and old map-5 tap). 42005 fires on
    skill-ready and 40501 on fight-state change, never as entry frames.
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
        first = amf3.decode(s.apply_stage([20000, [str(role_id), '']])[4:])
        tail = s.change_stage([21000, str(role_id)])
        tail = list(tail) if isinstance(tail, tuple) else [tail]
        return [first] + [amf3.decode(f[4:]) for f in tail]

    def test_vip_role_gets_vip_plus_birthprotect(self):
        s, role_id = self.build(vip_level=10)
        decoded = self.bootstrap(s, role_id)
        # No attack_skill on the role row, so 42005 is skipped, not faked;
        # 40501 is a fight-state frame, not an entry frame.
        self.assertEqual([d[0] for d in decoded],
                         ['20000', '21000', '12004', '12005', '12050',
                          '12000', '42100'])
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


class ShenjiangSlotInfoTest(unittest.TestCase):
    """Command 41023 against the captured Java replies (sj0101, sj0199, sj0202)."""

    def setUp(self):
        self.sess = Session(conn_id=1, check_sign=lambda *a: False,
                            get_roles=lambda u, s: [], server_start_ms=0,
                            config=None)

    def test_captured_ids_reply_with_null_slots(self):
        for sj_id in ('sj0101', 'sj0199', 'sj0202'):
            out = self.sess.shenjiang_slot_info([41023, sj_id])
            self.assertEqual(amf3.decode(out[4:]), ['41023', [1, sj_id, None]])

    def test_missing_id_still_replies_with_null_id(self):
        out = self.sess.shenjiang_slot_info([41023])
        self.assertEqual(amf3.decode(out[4:]), ['41023', [1, None, None]])

    def test_non_string_id_is_silent(self):
        self.assertIsNone(self.sess.shenjiang_slot_info([41023, 7]))


class QiandaoInfoTest(unittest.TestCase):
    """Command 58011 against the captured Java reply (no role_qiandao row)."""

    def test_reply_matches_captured_no_row_shape(self):
        sess = Session(conn_id=1, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [], server_start_ms=0,
                       config=None)
        out = sess.qiandao_info()
        self.assertEqual(amf3.decode(out[4:]),
                         ['58011', [1, None, 0, None, None]])

    def test_row_formats_month_days_and_rewards(self):
        row = {'total_qiandao_count': 3, 'month': 10,
               'month_qiandao': '1,2,3',
               'total_qiandao_reward': 'a,b',
               'month_qiandao_reward': 'x1',
               'week': 43, 'vip_buqian_count': 0,
               'qiandao_time': 1, 'online_time': 2}
        sess = Session(conn_id=1, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [{'id': 'r1'}],
                       get_role_qiandao=lambda rid: row,
                       server_start_ms=0, config=None)
        out = sess.qiandao_info()
        self.assertEqual(amf3.decode(out[4:]),
                         ['58011', [1, [1, 2, 3], 3, ['x1'], ['a', 'b']]])

    def test_row_with_empty_strings_answers_empty_lists(self):
        # The legacy fu0UR1-0-1-1 row stores '' in every list column. The live
        # Java server answered [1, [], 1, [], []] for it (capture:
        # output/swfdec/trace/reply58011-row.txt).
        row = {'total_qiandao_count': 1, 'month': 10, 'month_qiandao': '',
               'total_qiandao_reward': '', 'month_qiandao_reward': ''}
        sess = Session(conn_id=1, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [{'id': 'r1'}],
                       get_role_qiandao=lambda rid: row,
                       server_start_ms=0, config=None)
        out = sess.qiandao_info()
        self.assertEqual(amf3.decode(out[4:]),
                         ['58011', [1, [], 1, [], []]])

    def test_dispatch_routes_58011_through_handle(self):
        row = {'total_qiandao_count': 2, 'month_qiandao': '4',
               'total_qiandao_reward': '', 'month_qiandao_reward': ''}
        sess = Session(conn_id=1, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [{'id': 1}],
                       get_role_qiandao=lambda rid: row,
                       server_start_ms=0, config=None)
        sess.cipher = SimpleEncrypt('testkey')
        out = sess.handle(sess.cipher.encode(amf3.encode([58011])))
        self.assertEqual(amf3.decode(bytes(out)[4:]),
                         ['58011', [1, [4], 2, [], []]])

    def test_real_store_row_reaches_the_reply(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        store.save_role_qiandao(42, total_qiandao_count=1, month=10,
                                month_qiandao='', total_qiandao_reward='',
                                month_qiandao_reward='')
        sess = Session(conn_id=1, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [{'id': 42}],
                       get_role_qiandao=store.get_role_qiandao,
                       server_start_ms=0, config=None)
        out = sess.qiandao_info()
        self.assertEqual(amf3.decode(out[4:]),
                         ['58011', [1, [], 1, [], []]])

    def test_no_role_still_answers_the_no_row_shape(self):
        sess = Session(conn_id=1, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [],
                       get_role_qiandao=lambda rid: {'month_qiandao': '1'},
                       server_start_ms=0, config=None)
        out = sess.qiandao_info()
        self.assertEqual(amf3.decode(out[4:]),
                         ['58011', [1, None, 0, None, None]])




class TestLoadingStubs(unittest.TestCase):
    """Post-21000 loading replies match the Java fresh-role capture.

    session-20261020-072313 (fu0 fresh level 8): every C> in the loading
    cascade that Java answers with an S> must get the same shape from
    Python. The 8 fire-and-forget notifies (81000, 40600, 53021, 82022,
    130000, 101000, 73113, 75004) have no S> in either Java capture,
    so they stay silent like Java instead of inventing a reply.
    """

    def sess(self):
        return Session(conn_id=7, check_sign=lambda *a: True,
                       get_roles=lambda u, s: [{'id': 2, 'name': 'NewHero'}],
                       server_start_ms=0, config=None)

    def call(self, cmd, arg=None):
        s = self.sess()
        s.authed_user, s.server_id = 'hero', 'fu1304'
        return s.loading_stub([cmd, arg], cmd)

    def decode(self, cmd, arg=None):
        out = self.call(cmd, arg)
        self.assertIsNotNone(out, f'{cmd} should reply')
        return amf3.decode(out[4:])

    def test_simple_shapes(self):
        self.assertEqual(self.decode(35115), ['35115', [[0.0, 0.0]]])
        self.assertEqual(self.decode(53006), ['53006', [None]])
        self.assertEqual(self.decode(51000), ['51000', [[0, None, [], [], [], []]]])
        self.assertEqual(self.decode(82024), ['82024', [None]])
        self.assertEqual(self.decode(74000), ['74000', [[1, 0]]])
        self.assertEqual(self.decode(86000), ['86000', [[0, 0, [], 0, None]]])
        self.assertEqual(self.decode(85000), ['85000', [None]])
        self.assertEqual(self.decode(87000), ['87000', [None]])
        self.assertEqual(self.decode(70500), ['70500', [[]]])
        self.assertEqual(self.decode(90000), ['90000', [[0, [['1', '0'], ['11', 2130]], []]]])
        self.assertEqual(self.decode(92015), ['92015', [[None, [], None]]])
        self.assertEqual(self.decode(93000), ['93000', [None]])
        self.assertEqual(self.decode(94000), ['94000', [None]])
        self.assertEqual(self.decode(94002), ['94002', [None]])
        self.assertEqual(self.decode(94100), ['94100', [None]])
        self.assertEqual(self.decode(95000), ['95000', [None]])
        self.assertEqual(self.decode(113000), ['113000', [None]])
        self.assertEqual(self.decode(124001), ['124001', [None]])
        self.assertEqual(self.decode(70000), ['70000', [None]])

    def test_buff_query_quiet_session_is_null_null(self):
        # BuffStatistics serializes empty lists as null, never [].
        s = self.sess()
        s.authed_user, s.server_id = 'hero', 'fu1304'
        out = s.buff_query([42100, None])
        self.assertEqual(amf3.decode(out[4:]), ['42100', ['2', None, None]])

    def test_buff_query_replays_entry_ids_with_ticked_remaining(self):
        s = self.sess()
        s.authed_user, s.server_id = 'hero', 'fu1304'
        t0 = time.time()
        s._buff_live = [['buff_0_1', 'birthprotect', 10000.0, t0],
                        ['buff_0_2', 'vip010', None, t0]]
        env = amf3.decode(s.buff_query([42100, None])[4:])
        self.assertEqual(env[0], '42100')
        self.assertEqual([a[0] for a in env[1][1]],
                         ['buff_0_1', 'buff_0_2'])
        self.assertEqual(env[1][1][1][1], 'vip010')
        self.assertEqual(env[1][1][1][2], -1.0)
        remaining = env[1][1][0][2]
        self.assertLessEqual(remaining, 10000.0)
        self.assertGreater(remaining, 9000.0)
        self.assertIsNone(env[1][2])

    def test_buff_query_reports_expired_once_then_forgets(self):
        s = self.sess()
        s.authed_user, s.server_id = 'hero', 'fu1304'
        s._buff_live = [['buff_0_1', 'birthprotect', 10000.0,
                         time.time() - 20.0],
                        ['buff_0_2', 'vip010', None, time.time()]]
        env = amf3.decode(s.buff_query([42100, None])[4:])
        self.assertEqual(env[1][2], ['buff_0_1'])
        self.assertEqual([a[0] for a in env[1][1]], ['buff_0_2'])
        env = amf3.decode(s.buff_query([42100, None])[4:])
        self.assertIsNone(env[1][2])
        self.assertEqual([a[0] for a in env[1][1]], ['buff_0_2'])

    def test_entry_buff_frame_stashes_live_instances(self):
        # Without config there is no VIP mapping and no birthprotect
        # lasttime, so the frame is None — but the stash is still reset.
        s = self.sess()
        s._buff_live = [['stale', 'x', 1.0, 0.0]]
        self.assertIsNone(
            s.entry_buff_frame({'id': 2, 'name': 'NewHero'}))
        self.assertEqual(s._buff_live, [])

    def test_zuoqi_hp_without_pet_is_zero_zero(self):
        s = self.sess()
        s.authed_user, s.server_id = 'hero', 'fu1304'
        out = s.zuoqi_hp([33022, None])
        self.assertEqual(amf3.decode(out[4:]), ['33022', [[0, 0]]])

    def test_zuoqi_hp_reports_live_pet(self):
        s = self.sess()
        s.authed_user, s.server_id = 'hero', 'fu1304'
        s._pet_state['zuoqi_2_1'] = {'max_hp': 372.0, 'hp': 200.0,
                                     'template_id': 'zuoqi1'}
        out = s.zuoqi_hp([33022, None])
        self.assertEqual(amf3.decode(out[4:]), ['33022', [[200, 372]]])

    def test_97001_pages(self):
        got = self.decode(97001, 1)
        self.assertEqual(got[0], '97001')
        self.assertEqual(got[1][0], 1)
        self.assertEqual(self.decode(97001, 2)[1][0], 2)
        self.assertIn('xunbaonew.ani', got[1])

    def test_114000_pages(self):
        p1 = self.decode(114000, 1)
        p2 = self.decode(114000, 2)
        self.assertEqual(p1[0], '114000')
        self.assertEqual(p2[0], '114000')
        self.assertEqual(p1[1][1], '1')
        self.assertEqual(p2[1][1], '2')
        self.assertNotEqual(p1[1][4], p2[1][4])

    def test_122002_live_shape(self):
        # 122002 went live (tuangou_config): the stale stub row is gone,
        # so this asserts the live config shape instead of dead bytes.
        # The sign still matches the session capture.
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        store.create_account('hero', hash_password('pw'))
        store.create_character('hero', 'fu1304', 'SunWukong', job='C')
        s = make_session(store, config=GameConfig(DEFAULT_CONFIG_DIR))
        s.authed_user, s.server_id = 'hero', 'fu1304'
        env = amf3.decode(s.tuangou_config([122002, [None]])[4:])
        self.assertEqual(env[0], '122002')
        self.assertEqual(env[1][0], 'd7e8e1151e8d1e608e5277bac82adf60')
        self.assertEqual(len(env[1][1]), 404)
        self.assertEqual(env[1][2], [1392008400000.0, 1394510399000.0])
        # a matching client sign stays silent like Java's null
        self.assertIsNone(s.tuangou_config(
            [122002, ['d7e8e1151e8d1e608e5277bac82adf60']]))

    def test_kapai_qianfu_guanggao_fight_push_shapes(self):
        # 121000/121001/120000/109000 are config pushes with no
        # inbound route; 40501 is the fight-state builder the stage
        # loop calls. All pin live wire heads plus fresh-role zeros.
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        store.create_account('hero', hash_password('pw'))
        store.create_character('hero', 'fu1304', 'SunWukong', job='C')
        s = make_session(store, config=GameConfig(DEFAULT_CONFIG_DIR))
        s.authed_user, s.server_id = 'hero', 'fu1304'
        client = amf3.decode(s.kapai_client([121000, None])[4:])
        self.assertEqual(client[0], '121000')
        self.assertTrue(client[1][0])
        self.assertTrue(client[1][1])
        info = amf3.decode(s.kapai_info([121001, None])[4:])
        self.assertEqual(info[0], '121001')
        self.assertEqual(info[1][0], 0)
        self.assertTrue(all(n == 0 for _, n in info[1][1]))
        self.assertTrue(all(g == 0 and c == 0
                             for _, g, c in info[1][2]))
        qian = amf3.decode(s.qianfu_client([120000, None])[4:])
        self.assertEqual(qian[0], '120000')
        self.assertTrue(qian[1][0])
        self.assertTrue(qian[1][1])
        ads = amf3.decode(s.guanggao_list([109000, None])[4:])
        self.assertEqual(ads[0], '109000')
        self.assertTrue(ads[1][0])
        self.assertEqual(amf3.decode(s.fight_state_frame(
            {'id': 7})[4:]), ['40501', '7'])

    def test_dispatch_prefers_real_handlers_over_stubs(self):
        # 88003 has a real handler (vipqq_info) and must not sit in the
        # stub table: the reply has to come from live logic. With no vip_qq
        # row seeded, Java answers [0, 794002] — same bytes the capture
        # showed, but computed, not copied.
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        store.create_account('hero', hash_password('pw'))
        store.create_character('hero', 'fu1304', 'SunWukong', job='C')
        s = make_session(store)
        s.feed(CAPTURED_INITKEY)
        s.authed_user, s.server_id = 'hero', 'fu1304'
        out = s.feed(frame(s.cipher.encode(amf3.encode([88003, None]))))
        self.assertEqual(len(out), 1)
        self.assertEqual(amf3.decode(out[0][4:]), ['88003', [0, '794002']])

    def test_fire_and_forget_stays_silent_like_java(self):
        s = self.sess()
        s.authed_user, s.server_id = 'hero', 'fu1304'
        for cmd in (81000, 40600, 53021, 82022, 130000, 101000, 73113, 75004):
            self.assertIsNone(s.loading_stub([cmd, None], cmd), f'{cmd}')


class TestLiveJiangliOnline(unittest.TestCase):
    """De-stubbed slice: online rewards + login-device (10060/10061/58003-58005).

    10060 reads the dengluqi claim state ([state] — the tunnel wraps
    Java's bare Integer, as the session capture showed); 10061 claims the
    dengluqijiangli pool but only for micro-end sessions, so it answers
    [0, 592011] here exactly like Java does for every normal login.
    58003 totals the stored ms plus the open session's delta (Longs ride
    as doubles) with the month bind-yb claim state; 58004 rolls open daily
    tiers with weighted prizes and marks them claimed; 58005 claims the
    month's bind-yb into bind_lingshi. Daily/monthly resets run lazily in
    the handlers (Java runs them at login, which has no hook here).
    """

    def live(self, dailies, monthly):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        store.create_account('hero', hash_password('pw'))
        rid = store.create_character('hero', 'fu1304', 'SunWukong', job='C')
        kaifu = make_session(store)._online_kaifu_months()
        cfgdir = tempfile.mkdtemp()
        cleanups.append((shutil.rmtree, (cfgdir,), {'ignore_errors': True}))
        sysdir = os.path.join(cfgdir, 'sys_config')
        os.makedirs(sysdir)
        rows = []
        for pos, (tier, secs, mtime, prize) in enumerate(dailies):
            rows.append(Obj(type=1, daytime='', time=secs, bindgold='',
                            monthtime=mtime, month='', id='d%d' % pos,
                            count=tier, randomaward=prize))
        mday, mmonth, bindgold, mtime = monthly
        if mmonth is None:
            mmonth = kaifu
        rows.append(Obj(type=2, daytime=mday, time='', bindgold=bindgold,
                        monthtime=mtime, month=mmonth, id='m', count=''))
        with open(os.path.join(sysdir, 'zaixianjiangli.jat'), 'wb') as f:
            f.write(amf3.encode(rows))
        cfg = GameConfig(cfgdir)
        s = make_session(store, config=cfg)
        s.authed_user, s.server_id = 'hero', 'fu1304'
        store.save_role_bag_state(rid, bag_capacity=150)
        return store, rid, s, kaifu

    def decode(self, out):
        self.assertIsNotNone(out)
        return amf3.decode(out[4:])

    def seed_online(self, store, rid, anchor_ago_ms=408460, bind_yb=0,
                    claimed='', done=0):
        now = int(time.time() * 1000)
        store.save_role_online_reward(
            rid, month=time.localtime().tm_mon, online_time=0,
            month_online_time=0, refresh_time=now, online_reward=claimed,
            is_lingqu_reward=done, month_bind_yb=bind_yb,
            role_online_time=now - anchor_ago_ms)

    def test_weidan_state_fresh_claimed_and_daily_reset(self):
        store, rid, s, _ = self.live([], ('', 3, 20, 300))
        self.assertEqual(self.decode(s.weidan_state([10060, None])),
                         ['10060', [0]])
        row = store.get_role_dengluqi(str(rid))
        self.assertEqual(row['lingqu_state'], 0)
        self.assertIsNotNone(row['lingqu_time'])
        store.save_role_dengluqi(rid, lingqu_state=1)
        self.assertEqual(self.decode(s.weidan_state([10060, None])),
                         ['10060', [1]])
        store.save_role_dengluqi(rid, lingqu_time=1)
        self.assertEqual(self.decode(s.weidan_state([10060, None])),
                         ['10060', [0]])
        self.assertEqual(store.get_role_dengluqi(str(rid))['lingqu_state'],
                         0)

    def test_weidan_reward_needs_micro_end(self):
        # No micro-end login channel exists, so isMicroEndLogin is never
        # true and Java answers 592011 before any other check.
        store, rid, s, _ = self.live([], ('', 3, 20, 300))
        self.assertEqual(self.decode(s.weidan_reward([10061, None])),
                         ['10061', [0, '592011']])
        self.assertEqual(store.get_role_dengluqi(str(rid))['lingqu_state'],
                         0)

    def test_online_info_fresh_role_matches_capture_shape(self):
        # The session capture showed [[183111.0, 370120.0, 0, [], 2]];
        # the stub's [[408460.0, 1221939.0, 0, [], 2]] is the same shape
        # from a longer session. Totals are ms-as-doubles.
        store, rid, s, _ = self.live(
            [(1, 0, '', 'ceshi_item:1:1:1.0:7'),
             (2, 999999999, 999999999, 'ceshi_item:1:1:1.0:8')],
            ('', 3, 20, 300))
        self.seed_online(store, rid)
        env = self.decode(s.online_reward_info([58003, None]))
        self.assertEqual(env[0], '58003')
        total, month_total, bind, claimed, state = env[1][0]
        self.assertAlmostEqual(total, 408460.0, delta=5000.0)
        self.assertAlmostEqual(month_total, 408460.0, delta=5000.0)
        self.assertEqual((bind, claimed, state), (0, [], 2))

    def test_online_info_fresh_row_and_bindyb_state(self):
        # No row yet: the handler settles Java's loginInit state itself.
        store, rid, s, kaifu = self.live(
            [(1, 0, '', 'ceshi_item:1:1:1.0:7')],
            (str(time.localtime().tm_mday), None, 20, 300))
        env = self.decode(s.online_reward_info([58003, None]))
        total, month_total, bind, claimed, state = env[1][0]
        self.assertLess(total, 5000.0)
        self.assertEqual((bind, claimed, state), (0, [], 2))
        # A banked month accrual on an open day flips the state to 1.
        self.seed_online(store, rid, bind_yb=50)
        env = self.decode(s.online_reward_info([58003, None]))
        self.assertEqual(env[1][0][2:], [50, [], 1])

    def test_yaojiang_draw_marks_claimed(self):
        store, rid, s, _ = self.live(
            [(1, 0, '', 'ceshi_item:1:1:1.0:7'),
             (2, 999999999, 999999999, 'ceshi_item:1:1:1.0:8')],
            ('', 3, 20, 300))
        self.seed_online(store, rid)
        env = self.decode(s.online_yaojiang([58004, None]))
        self.assertEqual(env, ['58004', [1, [[1, 7]]]])
        self.assertEqual(store.get_role_online_reward(str(rid))
                         ['online_reward'], '1')
        slots = store.get_role_bag_slots(rid, 1, 150)
        self.assertEqual([(b['goods_id'], b['count']) for b in slots],
                         [('ceshi_item', 1)])

    def test_yaojiang_guards(self):
        store, rid, s, _ = self.live(
            [(1, 0, '', 'ceshi_item:1:1:1.0:7'),
             (2, 999999999, 999999999, 'ceshi_item:1:1:1.0:8')],
            ('', 3, 20, 300))
        # everything claimed: the not-repeat guard fires first
        self.seed_online(store, rid, claimed='1,2')
        self.assertEqual(self.decode(s.online_yaojiang([58004, None])),
                         ['58004', [0, '592003']])
        # one tier claimed, the other locked: nothing to draw
        self.seed_online(store, rid, claimed='1')
        self.assertEqual(self.decode(s.online_yaojiang([58004, None])),
                         ['58004', [0, '592004']])
        # no bag room: the draw is refused before anything lands
        store.save_role_bag_state(rid, bag_capacity=0)
        self.seed_online(store, rid)
        self.assertEqual(self.decode(s.online_yaojiang([58004, None])),
                         ['58004', [0, '592001']])
        self.assertEqual(store.get_role_online_reward(str(rid))
                         ['online_reward'], '')

    def test_lingqu_guards(self):
        store, rid, s, _ = self.live(
            [(1, 0, '', 'ceshi_item:1:1:1.0:7')],
            ('', None, 20, 300))
        # no tier for this kaifu month
        store2, rid2, s2, _ = self.live(
            [(1, 0, '', 'ceshi_item:1:1:1.0:7')], ('', 99, 20, 300))
        s2.authed_user, s2.server_id = 'hero', 'fu1304'
        self.seed_online(store2, rid2, bind_yb=50)
        self.assertEqual(self.decode(s2.online_lingqu([58005, None])),
                         ['58005', [0, '592005']])
        # nothing accrued
        self.seed_online(store, rid, bind_yb=0)
        self.assertEqual(self.decode(s.online_lingqu([58005, None])),
                         ['58005', [0, '592006']])
        # accrued but today is outside the open days (daytime '')
        self.seed_online(store, rid, bind_yb=50)
        self.assertEqual(self.decode(s.online_lingqu([58005, None])),
                         ['58005', [0, '592005']])

    def test_lingqu_repeat_and_success(self):
        today = str(time.localtime().tm_mday)
        store, rid, s, kaifu = self.live(
            [(1, 0, '', 'ceshi_item:1:1:1.0:7')], (today, None, 20, 300))
        store.update_character_state(rid, bind_lingshi=360)
        # already claimed this month
        self.seed_online(store, rid, bind_yb=50, done=1)
        self.assertEqual(self.decode(s.online_lingqu([58005, None])),
                         ['58005', [0, '592003']])
        # success zeroes the accrual and credits bind_lingshi
        self.seed_online(store, rid, bind_yb=50)
        self.assertEqual(self.decode(s.online_lingqu([58005, None])),
                         ['58005', [1, 50]])
        row = store.get_role_online_reward(str(rid))
        self.assertEqual((row['month_bind_yb'],
                          row['is_lingqu_reward']), (0, 1))
        char = store.get_character(str(rid), 'hero', 'fu1304')
        self.assertEqual(char['bind_lingshi'], 410)

    def test_dispatch_routes_live_handlers(self):
        store, rid, s, _ = self.live([], ('', 3, 20, 300))
        s.feed(CAPTURED_INITKEY)
        out = s.feed(frame(s.cipher.encode(amf3.encode([10060, None]))))
        self.assertEqual(len(out), 1)
        self.assertEqual(amf3.decode(out[0][4:]), ['10060', [0]])
        out = s.feed(frame(s.cipher.encode(amf3.encode([58003, None]))))
        self.assertEqual(len(out), 1)
        env = amf3.decode(out[0][4:])
        self.assertEqual(env[0], '58003')
        self.assertEqual(env[1][0][2:], [0, [], 2])


class TestLiveHusong(unittest.TestCase):
    """De-stubbed slice: escort info/position/rob count (83000/83001/83008).

    83001 answers [meiQiId, vip quota minus today's count] — [['1', 3]]
    fresh, matching the session capture and the vipbiao husongsishu
    quota; 83008 answers the jiebiao rob remainder ([[10]] fresh, [[0]]
    with no row like Java's null branch). 83000 pushes the escort
    beauty's spot, which is null with no escort running ([None] as
    captured). The daily escort count resets past its day stamp.
    """

    def live(self, husong_rows=None, vip_rows=None):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        store.create_account('hero', hash_password('pw'))
        rid = store.create_character('hero', 'fu1304', 'SunWukong', job='C')
        cfgdir = tempfile.mkdtemp()
        cleanups.append((shutil.rmtree, (cfgdir,), {'ignore_errors': True}))
        sysdir = os.path.join(cfgdir, 'sys_config')
        os.makedirs(sysdir)
        with open(os.path.join(sysdir, 'husong.jat'), 'wb') as f:
            f.write(amf3.encode(husong_rows if husong_rows is not None
                               else [Obj(id=1, name='mei1')]))
        with open(os.path.join(sysdir, 'vipbiao.jat'), 'wb') as f:
            f.write(amf3.encode(vip_rows if vip_rows is not None
                               else [Obj(lv=0, husongsishu=3, jiebiao=10)]))
        s = make_session(store, config=GameConfig(cfgdir))
        s.authed_user, s.server_id = 'hero', 'fu1304'
        return store, rid, s

    def decode(self, out):
        self.assertIsNotNone(out)
        return amf3.decode(out[4:])

    def test_info_fresh_matches_capture(self):
        store, rid, s = self.live()
        self.assertEqual(self.decode(s.husong_info([83001, None])),
                         ['83001', [['1', 3]]])
        row = store.get_role_husong(str(rid))
        self.assertEqual((row['mei_qi_id'], row['husong_times'],
                          row['dajie_cishu']), ('1', 0, 0))

    def test_info_counts_down_and_resets_daily(self):
        store, rid, s = self.live()
        store.save_role_husong(rid, mei_qi_id='1', husong_times=1,
                               refresh_time=int(time.time() * 1000))
        self.assertEqual(self.decode(s.husong_info([83001, None])),
                         ['83001', [['1', 2]]])
        store.save_role_husong(rid, husong_times=2, refresh_time=1)
        self.assertEqual(self.decode(s.husong_info([83001, None])),
                         ['83001', [['1', 3]]])
        self.assertEqual(store.get_role_husong(str(rid))['husong_times'],
                         0)

    def test_dajie_missing_used_and_fresh(self):
        store, rid, s = self.live()
        # no row yet: Java's null branch answers [[0]]
        self.assertEqual(self.decode(s.husong_dajie([83008, None])),
                         ['83008', [[0]]])
        # the info call settles the row; the full quota answers
        self.decode(s.husong_info([83001, None]))
        self.assertEqual(self.decode(s.husong_dajie([83008, None])),
                         ['83008', [[10]]])
        store.save_role_husong(rid, dajie_cishu=4)
        self.assertEqual(self.decode(s.husong_dajie([83008, None])),
                         ['83008', [[6]]])

    def test_position_stays_null_without_escort(self):
        _, _, s = self.live()
        self.assertEqual(self.decode(s.husong_position([83000, None])),
                         ['83000', [None]])

    def test_dispatch_routes_live_handlers(self):
        _, _, s = self.live()
        s.feed(CAPTURED_INITKEY)
        out = s.feed(frame(s.cipher.encode(amf3.encode([83001, None]))))
        self.assertEqual(len(out), 1)
        self.assertEqual(amf3.decode(out[0][4:]), ['83001', [['1', 3]]])
        # the info call settled the row, so the rob quota answers
        out = s.feed(frame(s.cipher.encode(amf3.encode([83008, None]))))
        self.assertEqual(len(out), 1)
        self.assertEqual(amf3.decode(out[0][4:]), ['83008', [[10]]])


class TestLiveLoginLvEmailShenjiang(unittest.TestCase):
    """De-stubbed slice 1: config/DB-backed infos + claim loops."""

    def live(self, **kw):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        store.create_account('hero', hash_password('pw'))
        rid = store.create_character('hero', 'fu1304', '孫悟空', job='C')
        cfg = GameConfig(DEFAULT_CONFIG_DIR)
        s = make_session(store, config=cfg)
        s.authed_user, s.server_id = 'hero', 'fu1304'
        for k, v in kw.items():
            setattr(s, k, v)
        return store, rid, s, cfg

    def test_loginlibao_info_live(self):
        store, rid, s, cfg = self.live()
        env = amf3.decode(s.loginlibao_info([127000, [None]])[4:])
        sign, rows = cfg.denglulibao_table()
        self.assertEqual(env[0], '127000')
        self.assertEqual(env[1][0], sign)
        self.assertEqual(len(env[1][1]), len(rows))
        self.assertEqual(env[1][2], 1)
        # client sign match -> configs null, unclaimed still computed
        env2 = amf3.decode(s.loginlibao_info([127000, [sign]])[4:])
        self.assertIsNone(env2[1][1])
        self.assertEqual(env2[1][2], 1)

    def test_loginlibao_claim_roundtrip(self):
        store, rid, s, cfg = self.live()
        sign, rows = cfg.denglulibao_table()
        gid = str(rows[0]['id'])
        out = amf3.decode(s.loginlibao_claim([127001, [gid]])[4:])
        self.assertEqual(out, ['127001', [1, gid]])
        row = store.get_role_loginlibao(str(rid))
        self.assertIn(gid, json.loads(row['lingqujson']))
        self.assertEqual(amf3.decode(s.loginlibao_claim(
            [127001, [gid]])[4:]), ['127001', [0]])
        env = amf3.decode(s.loginlibao_info([127000, [None]])[4:])
        # one of two claimed -> still unclaimed (2 rows in the table)
        self.assertEqual(env[1][2], 1)

    def test_lvlibao_claim_level_gated(self):
        store, rid, s, cfg = self.live()
        self.assertEqual(amf3.decode(s.lvlibao_info([58000, None])[4:]),
                         ['58000', []])
        _, rows = cfg.dengjilibao_table()
        lv10 = next(r for r in rows if str(r.get('levelneed')) == '10')
        num = str(lv10['number'])
        # level 1 role cannot claim the Lv.10 pack
        self.assertEqual(amf3.decode(s.lvlibao_claim(
            [58001, [num]])[4:]), ['58001', [0]])
        store.update_character_state(rid, level=10)
        out = amf3.decode(s.lvlibao_claim([58001, [num]])[4:])
        self.assertEqual(out, ['58001', [1, num]])
        env = amf3.decode(s.lvlibao_info([58000, None])[4:])
        self.assertEqual(env, ['58000', [[num, 1]]])

    def test_email_empty_null_then_crud(self):
        store, rid, s, cfg = self.live()
        self.assertEqual(amf3.decode(s.email_list([63001, None])[4:]),
                         ['63001', None])
        mid = store.save_role_email(str(rid), title='hi', content='yo',
                                    attachment='silver1:1:1')
        env = amf3.decode(s.email_list([63001, None])[4:])
        self.assertEqual(env[0], '63001')
        self.assertEqual(len(env[1]), 1)
        info = amf3.decode(s.email_info([63002, [str(mid)]])[4:])
        self.assertEqual(info[0], '63002')
        self.assertEqual(store.get_role_email(str(rid), str(mid))['is_read'], 1)
        self.assertEqual(amf3.decode(s.email_delete(
            [63004, [str(mid)]])[4:]), ['63004', [1, str(mid)]])
        self.assertEqual(amf3.decode(s.email_list([63001, None])[4:]),
                         ['63001', None])

    def test_shenjiang_empty_then_live(self):
        store, rid, s, cfg = self.live()
        self.assertEqual(amf3.decode(s.shenjiang_info([41000, None])[4:]),
                         ['41000', []])


class TestLiveRewardInfos2(unittest.TestCase):
    """De-stubbed slice 2: loginlingjiang, touxian, guangyi, baixian, zhuihui.

    Infos reproduce the captured fresh-role bytes when the DB is empty
    ([1, []] not the capture's [5, []] for 103000: the day count is the
    live streak, and 107000 rows carry 0 progress until activity
    tracking lands). Claim/worship flows validate, move currency/bag
    state, persist, and guard double-claims. Worship (71001) and
    recovery (107001) economy mappings are best-effort from
    BaiXianHuaFei/ziyuanzhuihui column semantics; the oracle diff
    adjudicates the exact Java mapping.
    """

    def live(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        store.create_account('hero', hash_password('pw'))
        rid = store.create_character('hero', 'fu1304', '孫悟空', job='C')
        cfg = GameConfig(DEFAULT_CONFIG_DIR)
        s = make_session(store, config=cfg)
        s.authed_user, s.server_id = 'hero', 'fu1304'
        return store, rid, s, cfg

    def test_loginlingjiang_info_and_claim(self):
        store, rid, s, cfg = self.live()
        env = amf3.decode(s.loginlingjiang_info([103000, None])[4:])
        self.assertEqual(env, ['103000', [1, []]])
        out = amf3.decode(s.loginlingjiang_claim([103001, ['1']])[4:])
        self.assertEqual(out, ['103001', [1, '1']])
        self.assertEqual(amf3.decode(s.loginlingjiang_claim(
            [103001, ['1']])[4:]), ['103001', [0]])
        self.assertEqual(amf3.decode(s.loginlingjiang_claim(
            [103001, ['2']])[4:]), ['103001', [0]])
        env = amf3.decode(s.loginlingjiang_info([103000, None])[4:])
        self.assertEqual(env, ['103000', [1, ['1']]])

    def test_touxian_activate_and_wear(self):
        store, rid, s, cfg = self.live()
        self.assertEqual(amf3.decode(s.touxian_info([104000, None])[4:]),
                         ['104000', [None, []]])
        self.assertEqual(amf3.decode(s.touxian_activate(
            [104001, ['999']])[4:]), ['104001', [0]])
        tid = next(iter(cfg.touxian_table()))
        self.assertEqual(amf3.decode(s.touxian_activate(
            [104001, [tid]])[4:]), ['104001', [1, tid]])
        self.assertEqual(amf3.decode(s.touxian_activate(
            [104001, [tid]])[4:]), ['104001', [0]])
        self.assertEqual(amf3.decode(s.touxian_wear(
            [104002, ['999']])[4:]), ['104002', [0]])
        self.assertEqual(amf3.decode(s.touxian_wear(
            [104002, [tid]])[4:]), ['104002', [1, tid]])
        self.assertEqual(amf3.decode(s.touxian_info([104000, None])[4:]),
                         ['104000', [tid, [tid]]])

    def test_guangyi_buy_and_wear(self):
        store, rid, s, cfg = self.live()
        self.assertEqual(amf3.decode(s.guangyi_info([102000, None])[4:]),
                         ['102000', None])
        first = cfg.guangyi_table()[0]
        need_id = str(first.get('needthingsid') or '')
        need_n = int(first.get('needthingsvalue') or 0)
        store.insert_role_bag_slot(
            rid, {'slot_num': 1, 'goods_id': need_id, 'count': need_n,
                  'bind': 1})
        self.assertEqual(amf3.decode(s.guangyi_buy([102002, None])[4:]),
                         ['102002', [1, 1]])
        self.assertEqual(amf3.decode(s.guangyi_buy([102002, None])[4:]),
                         ['102002', [0]])
        env = amf3.decode(s.guangyi_info([102000, None])[4:])
        self.assertEqual(env[0], '102000')
        self.assertEqual(env[1][:4], [1, 1, 0, 1])
        self.assertEqual(env[1][4], [])
        self.assertEqual(amf3.decode(s.guangyi_wear(
            [102003, [1]])[4:]), ['102003', [1, 1]])

    def test_guangyi_buy_short_bag_fails(self):
        store, rid, s, cfg = self.live()
        self.assertEqual(amf3.decode(s.guangyi_buy([102002, None])[4:]),
                         ['102002', [0]])

    def test_baixian_info_and_free_worship(self):
        store, rid, s, cfg = self.live()
        flat = []
        for r in cfg.baixian_table():
            flat.extend([str(r.get('id')), 0])
        self.assertEqual(amf3.decode(s.baixian_info([71000, None])[4:]),
                         ['71000', [[flat, 0.0]]])
        god = str(cfg.baixian_table()[0]['id'])
        out = amf3.decode(s.baixian_worship([71001, [god]])[4:])
        self.assertEqual(out, ['71001', [1, god, 1]])
        env = amf3.decode(s.baixian_info([71000, None])[4:])
        self.assertEqual(env[1][0][0][1], 1)
        self.assertEqual(amf3.decode(s.baixian_worship(
            [71001, ['999']])[4:]), ['71001', [0]])

    def test_zhuihui_info_and_claim(self):
        store, rid, s, cfg = self.live()
        env = amf3.decode(s.zhuihui_info([107000, None])[4:])
        self.assertEqual(env[0], '107000')
        self.assertEqual(len(env[1][0]), 8)
        self.assertTrue(all(r[1] == 0 and r[2] == 0 for r in env[1][0]))
        zid = sorted(cfg.zhuihui_table(), key=int)[0]
        cost = int(cfg.zhuihui_table()[zid].get('money1') or 0)
        store.update_character_state(rid, lingshi=cost)
        tongqian_before = store.get_character(
            str(rid), 'hero', 'fu1304')['tongqian'] or 0
        out = amf3.decode(s.zhuihui_claim([107001, [zid]])[4:])
        self.assertEqual(out, ['107001', [1, zid]])
        self.assertEqual(amf3.decode(s.zhuihui_claim(
            [107001, [zid]])[4:]), ['107001', [0]])
        after = store.get_character(str(rid), 'hero', 'fu1304')
        self.assertEqual(after['lingshi'], 0)
        self.assertGreaterEqual(after['tongqian'], tongqian_before)
        env = amf3.decode(s.zhuihui_info([107000, None])[4:])
        row = next(r for r in env[1][0] if r[0] == zid)
        self.assertEqual(row[2], 1)


class TestLiveDafuwongXianshibuy(unittest.TestCase):
    """De-stubbed slice 3: dafuwong board (105000-105002) + timed shop.

    105000 reproduces the captured fresh-role bytes; rolls move coin/gold
    balances, grant board items, persist counters, and enforce the vip
    coin-roll cap. Exchange spends grade points or yushi goods. Resets
    are daily (slot/counters) and weekly (zanshi stamps). The timed shop
    has no published xianshishop drop, so 119000 stays silent and the
    buy/clearCd loop runs against a mocked shop table; isBuy windows,
    server/personal caps, the shared-type cooldown, and both pushes are
    covered. Broadcasts beyond the buyer's own 119001 push need a bus.
    """

    SHOP = [{'id': 't1', 'type': 1, 'smax': 5, 'pmax': 2, 'price': 50,
             'cd': 3600000, 'consume': 10, 'kaifudays': 0, 'startday': 0,
             'hefustart': 0, 'hefudays': 0, 'start_ms': 0, 'end_ms': 0,
             'window': ['00:00', '23:59'], 'grants': [('yushi', 2, 1)],
             'client': {'id': 't1'}}]

    def live(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        store.create_account('hero', hash_password('pw'))
        rid = store.create_character('hero', 'fu1304', '孫悟空', job='C')
        cfg = GameConfig(DEFAULT_CONFIG_DIR)
        s = make_session(store, config=cfg)
        s.authed_user, s.server_id = 'hero', 'fu1304'
        return store, rid, s, cfg

    def decode(self, out):
        self.assertIsNotNone(out)
        if isinstance(out, tuple):
            return [amf3.decode(o[4:]) for o in out]
        return amf3.decode(out[4:])

    def test_info_fresh_role_matches_capture(self):
        _, _, s, _ = self.live()
        self.assertEqual(self.decode(s.dafuwong_info([105000, None])),
                         ['105000', [0, 0, 0, 0, 0, False]])

    def test_dispatch_routes_live_handlers(self):
        cleanups = []
        self.addCleanup(lambda: [fn(*a, **k) for fn, a, k in cleanups])
        store = temp_store(cleanups)
        store.create_account('hero', hash_password('pw'))
        store.create_character('hero', 'fu1304', 'SunWukong', job='C')
        s = make_session(store, config=GameConfig(DEFAULT_CONFIG_DIR))
        s.feed(CAPTURED_INITKEY)
        s.authed_user, s.server_id = 'hero', 'fu1304'
        out = s.feed(frame(s.cipher.encode(amf3.encode([105000, None]))))
        self.assertEqual(len(out), 1)
        self.assertEqual(amf3.decode(out[0][4:]),
                         ['105000', [0, 0, 0, 0, 0, False]])
        out = s.feed(frame(s.cipher.encode(amf3.encode([119001, None]))))
        self.assertEqual(len(out), 1)
        self.assertEqual(amf3.decode(out[0][4:]), ['119001', [1, []]])

    def test_roll_coin_and_gold_move_balances(self):
        store, rid, s, _ = self.live()
        store.update_character_state(rid, tongqian=1000000,
                                     lingshi=1000000)
        with mock.patch('game.protocol.random.randint',
                         return_value=3):
            env = self.decode(s.dafuwong_roll([105001, [1]]))
        # slot 3 is a +10 grade stop: price 10000 coin, counters bump
        self.assertEqual(env, ['105001', [1, 3, 3, 0, 10, False, 1,
                                          1, None]])
        char = store.get_character(str(rid), 'hero', 'fu1304')
        self.assertEqual(char['tongqian'], 990000)
        row = store.get_role_dafuwong(str(rid))
        self.assertEqual((row['slot'], row['grade'],
                          row['tongqian_count']), (3, 10, 1))
        with mock.patch('game.protocol.random.randint',
                         return_value=3):
            env = self.decode(s.dafuwong_roll([105001, [2]]))
        self.assertEqual(env[1][:6], [1, 3, 6, 0, 20, False])
        self.assertEqual(env[1][8], None)
        char = store.get_character(str(rid), 'hero', 'fu1304')
        self.assertEqual(char['lingshi'], 999990)
        env = self.decode(s.dafuwong_info([105000, None]))
        self.assertEqual(env, ['105000', [6, 20, 0, 2, 1, False]])

    def test_roll_guards(self):
        store, rid, s, _ = self.live()
        # broke role: coin roll wants tongqian (1003), gold wants gold
        self.assertEqual(self.decode(s.dafuwong_roll([105001, [1]])),
                         ['105001', [0, 1003]])
        self.assertEqual(self.decode(s.dafuwong_roll([105001, [2]])),
                         ['105001', [0, 1002]])
        self.assertIsNone(s.dafuwong_roll([105001, [9]]))
        self.assertIsNone(s.dafuwong_roll([105001, ['x']]))
        # vip0 allows 10 coin rolls a day; the 11th answers 105001
        store.update_character_state(rid, tongqian=10000000)
        store.save_role_dafuwong(str(rid), tongqian_count=10,
                                 last_roll_ms=int(time.time() * 1000))
        self.assertEqual(self.decode(s.dafuwong_roll([105001, [1]])),
                         ['105001', [0, 105001]])

    def test_roll_ten_gold_shape(self):
        store, rid, s, _ = self.live()
        store.update_character_state(rid, lingshi=1000000)
        with mock.patch('game.protocol.random.randint',
                         return_value=1):
            env = self.decode(s.dafuwong_roll([105001, [3]]))
        self.assertEqual(env[0], '105001')
        body = env[1]
        self.assertEqual(body[0], 1)
        self.assertEqual(len(body[8]), 10)
        char = store.get_character(str(rid), 'hero', 'fu1304')
        self.assertEqual(char['lingshi'], 999900)
        row = store.get_role_dafuwong(str(rid))
        self.assertEqual(row['roll_count'], 10)
        self.assertEqual(row['tongqian_count'], 0)

    def test_exchange_grade_and_yushi_pages(self):
        store, rid, s, _ = self.live()
        self.assertIsNone(s.dafuwong_exchange([105002, ['nope']]))
        # page 1: 101 costs 10000 grade points
        self.assertEqual(self.decode(s.dafuwong_exchange(
            [105002, ['101']])), ['105002', [0, 105000]])
        store.save_role_dafuwong(str(rid), grade=10000,
                                 last_roll_ms=int(time.time() * 1000))
        self.assertEqual(self.decode(s.dafuwong_exchange(
            [105002, ['101']])), ['105002', [1, '101']])
        self.assertEqual(self.decode(s.dafuwong_exchange(
            [105002, ['101']])), ['105002', [0, 105000]])
        goods = [g.get('goods_id')
                 for g in store.get_role_bag_slots(str(rid), 1, 150)]
        self.assertIn('txdihu', goods)
        # page 2: 187 costs 100 yushi goods
        self.assertEqual(self.decode(s.dafuwong_exchange(
            [105002, ['187']])), ['105002', [0, 1005]])
        store.insert_role_bag_slot(str(rid), {'slot_num': 20,
                                              'goods_id': 'yushi',
                                              'count': 100, 'bind': 0})
        self.assertEqual(self.decode(s.dafuwong_exchange(
            [105002, ['187']])), ['105002', [1, '187']])
        goods = [g.get('goods_id')
                 for g in store.get_role_bag_slots(str(rid), 1, 150)]
        self.assertIn('sj0210', goods)
        self.assertNotIn('yushi', goods)

    def test_resets_daily_and_weekly(self):
        store, rid, s, _ = self.live()
        eight_days = int(time.time() * 1000) - 8 * 86400000
        store.save_role_dafuwong(str(rid), slot=7, grade=50, zanshi=5,
                                 roll_count=3, tongqian_count=4,
                                 last_roll_ms=eight_days)
        env = self.decode(s.dafuwong_info([105000, None]))
        self.assertEqual(env, ['105000', [0, 50, 0, 0, 0, False]])
        # a different day in the same ISO week keeps the zanshi stamps:
        # freeze a Tuesday noon, stamp Monday noon
        tue_noon = time.mktime((2024, 5, 14, 12, 0, 0, 0, 0, -1))
        with mock.patch('game.protocol.time.time',
                         return_value=tue_noon):
            store.save_role_dafuwong(str(rid), slot=7, zanshi=5,
                                     roll_count=3, tongqian_count=4,
                                     last_roll_ms=int(
                                         (tue_noon - 86400) * 1000))
            env = self.decode(s.dafuwong_info([105000, None]))
        self.assertEqual(env, ['105000', [0, 50, 5, 0, 0, False]])

    def test_week_helper_edges(self):
        noon = lambda y, m, d: int(time.mktime((y, m, d, 12, 0, 0, 0, 0,
                                                -1)) * 1000)
        changed = Session._dafuwong_week_changed
        self.assertFalse(changed(noon(2024, 5, 15), noon(2024, 5, 16)))
        self.assertTrue(changed(noon(2024, 5, 8), noon(2024, 5, 16)))

    def test_xianshibuy_silent_without_drop(self):
        _, _, s, _ = self.live()
        self.assertIsNone(s.xianshibuy_client([119000, None]))
        self.assertEqual(self.decode(s.xianshibuy_info([119001, None])),
                         ['119001', [1, []]])
        self.assertIsNone(s.xianshibuy_buy([119002, ['t1']]))

    def test_xianshibuy_buy_and_clearcd_loop(self):
        store, rid, s, cfg = self.live()
        shop = [dict(r) for r in self.SHOP]
        with mock.patch.object(cfg, 'xianshishop_table',
                                return_value=shop):
            self.assertEqual(self.decode(s.xianshibuy_info(
                [119001, None])), ['119001', [1, []]])
            # broke: gold short
            self.assertEqual(self.decode(s.xianshibuy_buy(
                [119002, ['t1']])), ['119002', [0, 1002]])
            store.update_character_state(rid, lingshi=1000)
            reply, push = self.decode(s.xianshibuy_buy([119002,
                                                        ['t1']]))
            self.assertEqual(reply, ['119002', [1, 't1']])
            self.assertEqual(push[0], '119001')
            self.assertEqual(push[1][0], 1)
            entry = push[1][1][0]
            self.assertEqual(entry[:3], ['t1', 1, 1])
            self.assertGreater(entry[3], int(time.time() * 1000))
            sold = store.get_xianshi_buy()
            self.assertEqual(sold and sold.get('buy_data'), '{"t1": 1}')
            goods = [g.get('goods_id') for g in
                     store.get_role_bag_slots(str(rid), 1, 150)]
            self.assertIn('yushi', goods)
            # shared-type cooldown blocks the immediate rebuy
            self.assertEqual(self.decode(s.xianshibuy_buy(
                [119002, ['t1']])), ['119002', [0, 119003]])
            # clearing the cd (10 gold) reopens the second personal buy
            cleared = self.decode(s.xianshibuy_clearcd([119003,
                                                        ['t1']]))
            self.assertEqual(cleared[0], ['119003', [1, 't1']])
            self.assertEqual(cleared[1][0], '119001')
            reply, _ = self.decode(s.xianshibuy_buy([119002, ['t1']]))
            self.assertEqual(reply, ['119002', [1, 't1']])
            # the second buy re-arms the cd; clearing it once more
            # leaves the personal cap as the only block
            cleared = self.decode(s.xianshibuy_clearcd([119003,
                                                        ['t1']]))
            self.assertEqual(cleared[0], ['119003', [1, 't1']])
            self.assertEqual(self.decode(s.xianshibuy_buy(
                [119002, ['t1']])), ['119002', [0, 119002]])
            char = store.get_character(str(rid), 'hero', 'fu1304')
            self.assertEqual(char['lingshi'], 1000 - 50 - 10 - 50 - 10)

    def test_xianshibuy_caps_and_closed(self):
        store, rid, s, cfg = self.live()
        closed = [dict(r, id='shut', kaifudays=5,
                        window=['00:00', '23:59']) for r in self.SHOP]
        tiny = [dict(r, smax=1, pmax=9) for r in self.SHOP]
        with mock.patch.object(cfg, 'xianshishop_table',
                                return_value=closed):
            store.update_character_state(rid, lingshi=1000)
            # kaifu window (server boot 2009 + 5 days) long passed
            self.assertEqual(self.decode(s.xianshibuy_buy(
                [119002, ['shut']])), ['119002', [0, 119000]])
        with mock.patch.object(cfg, 'xianshishop_table',
                                return_value=tiny):
            store.update_character_state(rid, lingshi=1000)
            self.assertEqual(self.decode(s.xianshibuy_buy(
                [119002, ['t1']]))[0], ['119002', [1, 't1']])
            self.assertEqual(self.decode(
                s.xianshibuy_clearcd([119003, ['t1']]))[0],
                ['119003', [1, 't1']])
            # server sold 1 of 1: the next buy is sold out
            self.assertEqual(self.decode(s.xianshibuy_buy(
                [119002, ['t1']])), ['119002', [0, 119001]])
        self.assertEqual(self.decode(s.xianshibuy_clearcd(
            [119003, ['nope']])), ['119003', [0, 119004]])


if __name__ == '__main__':
    unittest.main()

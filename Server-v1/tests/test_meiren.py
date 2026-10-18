"""Meiren panel/obtain/upgrade/chanmian: 82000 lists, 82001 recruits, 82002 levels, 82003 chanmians.

Evidence: MeirenAction.getMeiRenMessage/getMeiRen/MeiRenupgrade/
getMeiRenChanMian and MeirenServiceImpl.getMeiRenAllObj/getMeiRen/
meiRenUpgrade/meiRenChanMian (82000 answers [[type, level, heti]] or null;
82001 gates owned 82100, role level 82101, qiandao 82102, items 82103,
zhenqi 82104, then inserts the level-1 row and pushes [1, type, 1]; 82002
gates heti 82105, role level / top config 82106, zhenqi 82108, pushing
[1, type, level]; 82003 gates order 82109, zhenqi 82110, YXB 82112, pushing
[1, type, level, heti]; 82004 is service-internal with no inbound route).
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.amf3 import encode as amf3_encode  # noqa: E402
from game.cipher import SimpleEncrypt  # noqa: E402
from game.protocol import Session  # noqa: E402

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..',
                           'reference', 'TonNgoKhong', 'server', 'config',
                           'game')
HAVE_REAL = os.path.isdir(REAL_CONFIG)


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class MeirenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'm.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56)
        self.store.update_character_state(
            self.role_id, zhenqi=5000, tongqian=1000000)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            save_role_state=self.store.update_character_state,
            get_role_meiren=self.store.get_role_meiren,
            save_role_meiren=self.store.save_role_meiren,
            get_role_zuoqi=self.store.get_role_zuoqi,
            get_role_bag_slots=self.store.get_role_bag_slots,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'

    @staticmethod
    def frames(out):
        if isinstance(out, (bytes, bytearray)):
            return [decode(bytes(out)[4:])]
        return [decode(bytes(f)[4:]) for f in out]

    def give_chips(self, goods_id, count, slot=10):
        self.store.insert_role_bag_slot(
            self.role_id,
            {'slot_num': slot, 'goods_id': goods_id, 'count': count,
             'bind': 0})

    def grant(self, meinvid='nvwa001', level=1, heti=0):
        rows = self.store.get_role_meiren(self.role_id) or []
        rows = [dict(r) for r in rows]
        rows.append({'meiren_id': meinvid, 'meiren_level': level,
                     'meiren_heti': heti})
        self.store.save_role_meiren(self.role_id, rows)

    def test_panel_empty_is_null_82000(self):
        (frame,) = self.frames(self.sess.meiren_panel())
        self.assertEqual(frame, ['82000', None])

    def test_panel_lists_owned_82000(self):
        self.grant('nvwa001', level=2, heti=1)
        (frame,) = self.frames(self.sess.meiren_panel())
        self.assertEqual(frame, ['82000', [['nvwa', 2, 1]]])

    def test_obtain_nvwa_success_82001(self):
        self.give_chips('chip_nvwa', 6)
        (frame,) = self.frames(self.sess.meiren_obtain(['82001', 'nvwa']))
        self.assertEqual(frame, ['82001', [1, 'nvwa', 1]])
        owned = self.store.get_role_meiren(self.role_id)
        self.assertEqual(
            [(r['meiren_id'], r['meiren_level'], r['meiren_heti'])
             for r in owned],
            [('nvwa001', 1, 0)])

    def test_obtain_owned_is_82100(self):
        self.grant('nvwa001')
        (frame,) = self.frames(self.sess.meiren_obtain(['82001', 'nvwa']))
        self.assertEqual(frame, ['82001', [0, 82100]])

    def test_obtain_short_level_is_82101(self):
        (frame,) = self.frames(
            self.sess.meiren_obtain(['82001', 'xiaolongnv']))
        self.assertEqual(frame, ['82001', [0, 82101, [70]]])

    def test_obtain_short_qiandao_is_82102(self):
        (frame,) = self.frames(
            self.sess.meiren_obtain(['82001', 'baijingjing']))
        self.assertEqual(frame, ['82001', [0, 82102, [60]]])

    def test_obtain_short_items_is_82103(self):
        (frame,) = self.frames(self.sess.meiren_obtain(['82001', 'nvwa']))
        self.assertEqual(frame, ['82001', [0, 82103]])

    def test_obtain_short_zhenqi_is_82104(self):
        self.give_chips('chip_nvwa', 6)
        self.store.update_character_state(self.role_id, zhenqi=0)
        (frame,) = self.frames(self.sess.meiren_obtain(['82001', 'nvwa']))
        self.assertEqual(frame, ['82001', [0, 82104]])

    def test_obtain_unknown_type_is_silent(self):
        self.assertIsNone(self.sess.meiren_obtain(['82001', 'nobody']))
        self.assertIsNone(self.sess.meiren_obtain(['82001', ['nvwa']]))

    def test_upgrade_short_heti_is_82105(self):
        self.grant('nvwa001', level=1, heti=0)
        (frame,) = self.frames(self.sess.meiren_upgrade(['82002', 'nvwa']))
        self.assertEqual(frame, ['82002', [0, 82105]])

    def test_upgrade_short_zhenqi_is_82108(self):
        self.grant('nvwa001', level=1, heti=1)
        self.store.update_character_state(self.role_id, zhenqi=0)
        (frame,) = self.frames(self.sess.meiren_upgrade(['82002', 'nvwa']))
        self.assertEqual(frame, ['82002', [0, 82108]])

    def test_upgrade_success_82002(self):
        self.grant('nvwa001', level=1, heti=1)
        self.store.update_character_state(self.role_id, zhenqi=40000)
        (frame,) = self.frames(self.sess.meiren_upgrade(['82002', 'nvwa']))
        self.assertEqual(frame, ['82002', [1, 'nvwa', 2]])
        owned = self.store.get_role_meiren(self.role_id)
        self.assertEqual(
            [(r['meiren_id'], r['meiren_level']) for r in owned],
            [('nvwa002', 2)])

    def test_upgrade_missing_row_is_silent(self):
        self.assertIsNone(self.sess.meiren_upgrade(['82002', 'nvwa']))

    def test_chanmian_order_gate_is_82109(self):
        self.grant('nvwa001', level=1, heti=1)
        (frame,) = self.frames(self.sess.meiren_chanmian(['82003', 'nvwa']))
        self.assertEqual(frame, ['82003', [0, 82109]])

    def test_chanmian_short_yxb_is_82112(self):
        self.grant('nvwa002', level=2, heti=0)
        self.store.update_character_state(
            self.role_id, zhenqi=500000, tongqian=0)
        (frame,) = self.frames(self.sess.meiren_chanmian(['82003', 'nvwa']))
        self.assertEqual(frame, ['82003', [0, 82112]])

    def test_chanmian_success_82003(self):
        self.grant('nvwa002', level=2, heti=0)
        self.store.update_character_state(
            self.role_id, zhenqi=500000, tongqian=1000000)
        before = self.store.list_roles('hero', 'fu1304')[0]
        (frame,) = self.frames(self.sess.meiren_chanmian(['82003', 'nvwa']))
        self.assertEqual(frame, ['82003', [1, 'nvwa', 2, 1]])
        owned = self.store.get_role_meiren(self.role_id)
        self.assertEqual(
            [(r['meiren_level'], r['meiren_heti']) for r in owned],
            [(2, 1)])
        after = self.store.list_roles('hero', 'fu1304')[0]
        self.assertLess(after['tongqian'], before['tongqian'])

    def test_dispatch_routes_through_handle(self):
        # Full dispatch path: client [82000] -> ['82000', None].
        self.sess.cipher = SimpleEncrypt('testkey')
        payload = self.sess.cipher.encode(amf3_encode([82000, None]))
        (out,) = self.frames(self.sess.handle(payload))
        self.assertEqual(out, ['82000', None])


if __name__ == '__main__':
    unittest.main()

"""Baoshi panel/activate/upgrade: 37000 lists, 37001 sockets, 37002 feeds.

Evidence: BaoShiAction.info/jihuo/upgrade,
RoleBaoshiServiceImpl.loadBaoShi/jihuoBaoShi/upgrade/canJiHuo/canUpgrade/
addBaoShiExp/jiHuoSuccess (37000 answers the formatAll flat panel or
null; 37001 gates config 530002, role level 530009, part-grade 530010,
owned 530001, materials 530003, then the min/max pity lottery, pushing
[1, part, grid] or [-1]; 37002 gates missing/level-0 530002, top 530006,
non-min stone 530002, then the RateScope roll with overflow chained
into the part's lowest stone, pushing [1, part, grid, level, exp,
roll0, roll1] plus the 11101 [530011, ...] notice at a dead-end level).
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

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
class BaoshiTest(unittest.TestCase):
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
            get_role_baoshi=self.store.get_role_baoshi,
            save_role_baoshi=self.store.save_role_baoshi,
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

    def give(self, goods_id, count, slot=10):
        self.store.insert_role_bag_slot(
            self.role_id,
            {'slot_num': slot, 'goods_id': goods_id, 'count': count,
             'bind': 0})

    def stock(self, goods_id):
        return sum(
            s.get('count') or 0
            for s in self.store.get_role_bag_slots(self.role_id, 1, 150)
            if s.get('goods_id') == goods_id)

    def plant(self, part=70, grid=1, level=1, exp=0, fails=0):
        rows = self.store.get_role_baoshi(self.role_id) or []
        rows = [dict(r) for r in rows]
        rows.append({'id': f'b{part}{grid}', 'part': part, 'grid': grid,
                     'level': level, 'fail_count': fails, 'exp': exp,
                     'update_time': 1})
        self.store.save_role_baoshi(self.role_id, rows)

    def row(self, part=70, grid=1):
        for entry in self.store.get_role_baoshi(self.role_id) or []:
            if entry.get('part') == part and entry.get('grid') == grid:
                return entry
        return None

    def test_panel_empty_is_null_37000(self):
        (frame,) = self.frames(self.sess.baoshi_info())
        self.assertEqual(frame, ['37000', None])

    def test_panel_lists_owned_37000(self):
        self.plant(70, 1, level=1, exp=5)
        self.plant(70, 2, level=0, exp=0)
        (frame,) = self.frames(self.sess.baoshi_info())
        self.assertEqual(frame, ['37000', [70, [[1, 5, 1], [2, 0, 0]]]])

    def test_jihuo_success_37001(self):
        self.give('bscl', 3)
        (frame,) = self.frames(self.sess.baoshi_jihuo([37001, [70, 1]]))
        self.assertEqual(frame, ['37001', [1, 70, 1]])
        entry = self.row()
        self.assertEqual(
            (entry['level'], entry['fail_count']), (1, 0))
        self.assertEqual(self.stock('bscl'), 0)

    def test_jihuo_owned_is_530001(self):
        self.plant(70, 1, level=1)
        self.give('bscl', 3)
        (frame,) = self.frames(self.sess.baoshi_jihuo([37001, [70, 1]]))
        self.assertEqual(frame, ['37001', [0, 530001]])

    def test_jihuo_skipped_grid_is_530002(self):
        self.give('bscl', 10)
        (frame,) = self.frames(self.sess.baoshi_jihuo([37001, [70, 3]]))
        self.assertEqual(frame, ['37001', [0, 530002]])

    def test_jihuo_short_level_is_530009(self):
        self.store.update_character_state(self.role_id, level=30)
        self.give('bscl', 3)
        (frame,) = self.frames(self.sess.baoshi_jihuo([37001, [70, 1]]))
        self.assertEqual(frame, ['37001', [0, 530009]])

    def test_jihuo_short_grade_is_530010(self):
        self.plant(70, 1, level=1)
        self.plant(70, 2, level=1)
        self.plant(70, 3, level=1)
        self.give('bsclbig', 1)
        (frame,) = self.frames(self.sess.baoshi_jihuo([37001, [70, 4]]))
        self.assertEqual(frame, ['37001', [0, 530010]])

    def test_jihuo_short_goods_is_530003(self):
        (frame,) = self.frames(self.sess.baoshi_jihuo([37001, [70, 1]]))
        self.assertEqual(frame, ['37001', [0, 530003]])

    def test_jihuo_unknown_part_is_530002(self):
        (frame,) = self.frames(self.sess.baoshi_jihuo([37001, [7, 1]]))
        self.assertEqual(frame, ['37001', [0, 530002]])

    def test_jihuo_bad_shape_is_silent(self):
        self.assertIsNone(self.sess.baoshi_jihuo([37001, [70]]))
        self.assertIsNone(self.sess.baoshi_jihuo([37001, ['70', 1]]))
        self.assertIsNone(self.sess.baoshi_jihuo([37001, None]))

    def test_jihuo_fail_then_pity_lands(self):
        # Part 70 grid 2 needs mintimes 1: grid 1 opens first (sequential
        # unlock), then the first grid-2 roll fails even at odds 1.0,
        # banking failCount; the retry then lands at chushi 1.
        self.give('bscl', 13)
        (opened,) = self.frames(self.sess.baoshi_jihuo([37001, [70, 1]]))
        self.assertEqual(opened, ['37001', [1, 70, 1]])
        (first,) = self.frames(self.sess.baoshi_jihuo([37001, [70, 2]]))
        self.assertEqual(first, ['37001', [-1]])
        self.assertEqual(self.row(70, 2)['fail_count'], 1)
        (second,) = self.frames(self.sess.baoshi_jihuo([37001, [70, 2]]))
        self.assertEqual(second, ['37001', [1, 70, 2]])
        entry = self.row(70, 2)
        self.assertEqual((entry['level'], entry['fail_count']), (1, 0))

    def test_upgrade_missing_row_is_530002(self):
        (frame,) = self.frames(self.sess.baoshi_upgrade([37002, [70, 1]]))
        self.assertEqual(frame, ['37002', [0, 530002]])

    def test_upgrade_level_zero_is_530002(self):
        self.plant(70, 1, level=0)
        self.give('bscl', 15)
        (frame,) = self.frames(self.sess.baoshi_upgrade([37002, [70, 1]]))
        self.assertEqual(frame, ['37002', [0, 530002]])

    def test_upgrade_top_is_530006(self):
        self.plant(70, 1, level=7)
        self.give('bscl', 15)
        (frame,) = self.frames(self.sess.baoshi_upgrade([37002, [70, 1]]))
        self.assertEqual(frame, ['37002', [0, 530006]])

    def test_upgrade_non_min_stone_is_530002(self):
        self.plant(70, 1, level=3)
        self.plant(70, 2, level=1)
        self.give('bscl', 40)
        (frame,) = self.frames(self.sess.baoshi_upgrade([37002, [70, 1]]))
        self.assertEqual(frame, ['37002', [0, 530002]])

    def test_upgrade_short_goods_is_1005(self):
        self.plant(70, 1, level=1)
        (frame,) = self.frames(self.sess.baoshi_upgrade([37002, [70, 1]]))
        self.assertEqual(frame, ['37002', [0, 1005]])

    def test_upgrade_feeds_exp_37002(self):
        self.plant(70, 1, level=1, exp=0)
        self.give('bscl', 15)
        with mock.patch('random.random', return_value=0.0):
            (frame,) = self.frames(
                self.sess.baoshi_upgrade([37002, [70, 1]]))
        self.assertEqual(frame, ['37002', [1, 70, 1, 1, 10, 0, 10]])
        entry = self.row()
        self.assertEqual((entry['level'], entry['exp']), (1, 10))
        self.assertEqual(self.stock('bscl'), 0)

    def test_upgrade_overflow_chains_and_levels(self):
        self.plant(70, 1, level=1, exp=145)
        self.give('bscl', 15)
        with mock.patch('random.random', return_value=0.0):
            (frame,) = self.frames(
                self.sess.baoshi_upgrade([37002, [70, 1]]))
        # 145 + 10 overflows needexp 150 by 5: level 2, the 5 chains
        # back into the same (lowest) stone.
        self.assertEqual(
            frame, ['37002', [1, 70, 1, 2, 5, 0, 10, [1, 5, 2]]])
        entry = self.row()
        self.assertEqual((entry['level'], entry['exp']), (2, 5))

    def test_upgrade_overflow_chains_into_lowest_stone(self):
        self.plant(70, 1, level=1, exp=145)
        self.plant(70, 2, level=1, exp=0)
        self.give('bscl', 15)
        with mock.patch('random.random', return_value=0.0):
            (frame,) = self.frames(
                self.sess.baoshi_upgrade([37002, [70, 1]]))
        # Grid 1 levels to 2; the 5 overflow chains into grid 2 (now the
        # lowest stone), whose formatOne rides slot 7.
        self.assertEqual(
            frame, ['37002', [1, 70, 1, 2, 0, 0, 10, [2, 5, 1]]])
        self.assertEqual(
            (self.row(70, 1)['level'], self.row(70, 2)['exp']), (2, 5))

    def test_upgrade_to_dead_end_broadcasts_11101(self):
        self.plant(70, 1, level=6, exp=95)
        self.give('bsclbig', 1)
        gemname = self.cfg.baoshi_level('gem_001', 7)['name']
        with mock.patch('random.random', return_value=0.0):
            out = self.sess.baoshi_upgrade([37002, [70, 1]])
        notice, reply = self.frames(out)
        self.assertEqual(
            notice, ['11101', [530011, ['Wukong', '{bodyPart|70}',
                                        gemname]]])
        # Level 6 pays 100 exp a roll: 95 + 100 overflows needexp 100 by
        # 95, but the chained row is already capped, so Java's early
        # return fires before it is recorded and slot 7 stays absent.
        self.assertEqual(reply, ['37002', [1, 70, 1, 7, 0, 0, 100]])
        self.assertEqual(self.row()['level'], 7)

    def test_baoshi_bag_feeds_attributes(self):
        self.plant(70, 1, level=1)
        role = self.store.list_roles('hero', 'fu1304')[0]
        bags = self.sess.role_bags(role)
        self.assertIn({'physicdamage': 27.0}, bags)

    def test_dispatch_routes_through_handle(self):
        # Full dispatch path: client [37000] -> ['37000', None].
        self.sess.cipher = SimpleEncrypt('testkey')
        payload = self.sess.cipher.encode(amf3_encode([37000, None]))
        (out,) = self.frames(self.sess.handle(payload))
        self.assertEqual(out, ['37000', None])


if __name__ == '__main__':
    unittest.main()

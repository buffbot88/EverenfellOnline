"""Mount pills via 30301: useLongHun/useLongLing plus the 33010/33012 pushes.

Evidence: RoleZuoQiServiceImpl bytecode (useLongHun/useLongLing,
checkAttDan/checkAttLuckyDan, send2One '33010'/'33012'), the
PropServiceImpl skill tableswitch (33 -> LongHun, 35 -> LongLing, both
consumePrior null) and ZuoQiConfigExportServiceImpl.createLevelConfig
(xlimit -> maxAttributeGoodsCount, perxlimit ->
maxAttributeGoodsCountByPercentage). '33010'/'33012' have no ModuleInit
route, so the ledger tracks them as emitted pushes; these tests pin
their shapes, gates and persistence. The read half ports
ZhanDouLiServiceImpl.getlongLingOrLongHun (skill-33 bags added per pill,
skill-35 level bags scaled by sxbfb) into '33008' and the '12010' slot
[3], plus PropUtil.getLonglingLonghunCount into the '12102' pill slots.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2]
               / 'reference' / 'TonNgoKhong' / 'server' / 'config' / 'game')


class LongHunTest(unittest.TestCase):
    """Skills 33/35 through prop_use (zuoqishuxing2/3, zuoqilv 7/8)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56, tongqian=100,
            bind_lingshi=0, lingshi=50)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            get_role_bag_slot=self.store.get_role_bag_slot,
            get_role_bag_slot_by_bag_id=
            self.store.get_role_bag_slot_by_bag_id,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            get_role_zuoqi=self.store.get_role_zuoqi,
            save_role_zuoqi=self.store.save_role_zuoqi,
            save_role_state=self.store.update_character_state,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=30)

    def row(self, slot, goods, count=1, bag_id=None):
        return {'slot_num': slot, 'goods_id': goods, 'count': count,
                'bag_id': bag_id or f'p{slot}', 'bind': 0,
                'expire_time': 0, 'rare_level': 0, 'item_level': 1,
                'attributes': None}

    def mount(self, rank, att=None):
        self.store.save_role_zuoqi(
            self.role_id, rank, rank, 0, 0, 0, 0, 0, None, 0, 0, None,
            json.dumps(att) if att is not None else None)

    def use(self, guid):
        out = self.sess.prop_use(guid)
        if out is None:
            return None
        if isinstance(out, tuple):
            return [decode(f[4:]) for f in out]
        return [decode(out[4:])]

    def att_map(self):
        return json.loads(
            self.store.get_role_zuoqi(self.role_id)['attribute_goods_id'])

    def test_longhun_pushes_count_and_persists_map(self):
        self.mount(7)
        self.store.save_role_bag_slots(
            self.role_id, [self.row(10, 'zuoqishuxing2', 2)])
        got = self.use('p10')
        self.assertEqual([f[0] for f in got], ['33010', '30301'])
        self.assertEqual(got[0][1], 1)
        self.assertEqual(got[1][1], [1, 'p10'])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 10)['count'], 1)
        self.assertEqual(self.att_map(), {'zuoqishuxing2': 1})

    def test_longhun_second_use_bumps_to_two(self):
        self.mount(7, {'zuoqishuxing2': 1})
        self.store.save_role_bag_slots(
            self.role_id, [self.row(10, 'zuoqishuxing2', 1)])
        got = self.use('p10')
        self.assertEqual([f[0] for f in got], ['33010', '30301'])
        self.assertEqual(got[0][1], 2)
        self.assertIsNone(
            self.store.get_role_bag_slot(self.role_id, 10))
        self.assertEqual(self.att_map(), {'zuoqishuxing2': 2})

    def test_longhun_rank_gate_leaves_stock_and_map(self):
        self.mount(6)
        self.store.save_role_bag_slots(
            self.role_id, [self.row(11, 'zuoqishuxing2', 1)])
        got = self.use('p11')
        self.assertEqual(got, [['30301', [0, 520004]]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 11)['count'], 1)
        self.assertIsNone(
            self.store.get_role_zuoqi(self.role_id)['attribute_goods_id'])

    def test_longhun_rank_zero_gate(self):
        self.mount(0)
        self.store.save_role_bag_slots(
            self.role_id, [self.row(12, 'zuoqishuxing2', 1)])
        got = self.use('p12')
        self.assertEqual(got, [['30301', [0, 520004]]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 12)['count'], 1)

    def test_longhun_cap_hit_keeps_pill(self):
        self.mount(7, {'zuoqishuxing2': 10})
        self.store.save_role_bag_slots(
            self.role_id, [self.row(13, 'zuoqishuxing2', 1)])
        got = self.use('p13')
        self.assertEqual(got, [['30301', [0, 520011]]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 13)['count'], 1)
        self.assertEqual(self.att_map(), {'zuoqishuxing2': 10})

    def test_longling_pushes_count_and_persists_map(self):
        self.mount(8)
        self.store.save_role_bag_slots(
            self.role_id, [self.row(14, 'zuoqishuxing3', 1)])
        got = self.use('p14')
        self.assertEqual([f[0] for f in got], ['33012', '30301'])
        self.assertEqual(got[0][1], 1)
        self.assertEqual(got[1][1], [1, 'p14'])
        self.assertIsNone(
            self.store.get_role_bag_slot(self.role_id, 14))
        self.assertEqual(self.att_map(), {'zuoqishuxing3': 1})

    def test_zhanli_33008_adds_longhun_fight(self):
        # Goods bag {hp 300, mana 300, dmg 150, def 75, crit 35, volt 35}
        # x2 -> {600, 600, 300, 150, 70, 70}; fight over ZhanLiXiShu
        # (hp/mana .25, dmg .5, def 1.0, crit/volt 2.0):
        # 150 + 150 + 150 + 150 + 140 + 140 = 880. Rank-7 jichu is 6786.
        self.mount(7, {'zuoqishuxing2': 2})
        out = self.sess.zuoqi_zhanli()
        self.assertEqual(decode(out[4:]), ['33008', 6786 + 880])

    def test_zhanli_33008_adds_longling_fight(self):
        # Rank-8 level-56 bag {hp 7772, mana 5829, dmg 3886, def 1943,
        # crit 972, volt 972, attackrate 35} x0.02: 38 + 29 + 38 + 38 +
        # 38 + 38 + 7 = 226. Rank-8 jichu is 11524.
        self.mount(8, {'zuoqishuxing3': 1})
        out = self.sess.zuoqi_zhanli()
        self.assertEqual(decode(out[4:]), ['33008', 11524 + 226])

    def test_zhanli_33008_empty_map_stays_jichu(self):
        self.mount(7)
        out = self.sess.zuoqi_zhanli()
        self.assertEqual(decode(out[4:]), ['33008', 6786])

    def test_fighting_info_12010_slot_three_carries_longhun(self):
        self.mount(7, {'zuoqishuxing2': 2})
        out = self.sess.fighting_info()
        self.assertEqual(decode(out[4:])[1][3], [6786, 0, 880])

    def test_zuoqi_info_12102_reports_pill_counts(self):
        # 12102 slots [4]/[5] are getLonglingLonghunCount: skill-33
        # total, then skill-35 total; unknown goods add nothing.
        self.mount(7, {'zuoqishuxing2': 2, 'zuoqishuxing3': 1,
                       'nope': 9})
        out = self.sess.zuoqi_info()
        self.assertEqual(
            decode(out[4:]), ['12102', [0, 0, None, None, 2, 1, 0, None]])

    def test_role_bags_mount_carries_longhun_attrs(self):
        # 12000 mount bag = refined rank-7/56 bag {hp 4512, mana 3385,
        # dmg 2256, def 1128, crit 564, volt 564, attackrate 30} plus 2x
        # the longhun bag {hp 300, mana 300, dmg 150, def 75, crit 35,
        # volt 35} (velocity rides along as 0.0, like addMapValue).
        self.mount(7, {'zuoqishuxing2': 2})
        role = self.store.list_roles('hero', 'fu1304')[0]
        self.assertEqual(self.sess.role_bags(role), [{
            'hitpoints': 5112.0, 'mana': 3985.0,
            'physicdamage': 2556.0, 'physicdefence': 1278.0,
            'critical': 634.0, 'volt': 634.0, 'attackrate': 30.0,
            'velocity': 0.0}])

    def test_role_bags_mount_carries_longling_scale(self):
        # Rank-8/56 bag scaled once by sxbfb 0.02 (count loop, one
        # pass): hp 7772 -> 7927.44, mana 5829 -> 5945.58, dmg 3886 ->
        # 3963.72, def 1943 -> 1981.86, crit/volt 972 -> 991.44,
        # attackrate 35 -> 35.7.
        self.mount(8, {'zuoqishuxing3': 1})
        role = self.store.list_roles('hero', 'fu1304')[0]
        self.assertEqual(self.sess.role_bags(role), [{
            'hitpoints': 7927.44, 'mana': 5945.58,
            'physicdamage': 3963.72, 'physicdefence': 1981.86,
            'critical': 991.44, 'volt': 991.44, 'attackrate': 35.7,
            'velocity': 0.0}])

    def test_role_bags_mount_without_pills_is_plain_level_bag(self):
        self.mount(7)
        role = self.store.list_roles('hero', 'fu1304')[0]
        self.assertEqual(self.sess.role_bags(role), [{
            'hitpoints': 4512.0, 'mana': 3385.0,
            'physicdamage': 2256.0, 'physicdefence': 1128.0,
            'critical': 564.0, 'volt': 564.0, 'attackrate': 30.0}])

    def test_zuoqi_info_12102_counts_default_without_map(self):
        self.mount(7)
        out = self.sess.zuoqi_info()
        self.assertEqual(
            decode(out[4:]), ['12102', [0, 0, None, None, 0, 0, 0, None]])

    def test_longling_rank_gate_and_cap(self):
        self.mount(7)
        self.store.save_role_bag_slots(
            self.role_id, [self.row(15, 'zuoqishuxing3', 1)])
        self.assertEqual(self.use('p15'), [['30301', [0, 520004]]])
        self.mount(8, {'zuoqishuxing3': 10})
        self.store.save_role_bag_slots(
            self.role_id, [self.row(15, 'zuoqishuxing3', 1)])
        self.assertEqual(self.use('p15'), [['30301', [0, 520011]]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 15)['count'], 1)


if __name__ == '__main__':
    unittest.main()

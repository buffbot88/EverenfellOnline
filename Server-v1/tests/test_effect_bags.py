"""Effect-bag attributes: VIP/xianjie/chenghao/meiren into the 12000 map.

Evidence: jar bytecode (RoleFactoryHelper.replaceVip/XianJie/ChengHao/Meiren
Attribute, XianJie/ChengHao/MeiRenConfigExportServiceImpl, BuffConfig-
ExportServiceImpl.createBuffAttributes, BuffFactory.create, and the formula
slot polarity) plus the captured 12000 oracle for role fu0UR1-0-1-1 in
output/orig-stack/tap-decoded.txt.
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
from game.attributes import entry_attribute_map  # noqa: E402
from game.config import (  # noqa: E402
    GameConfig, equip_vo, fujia_client_map, qh_xingxings_client, xingxing_lv)
from game.protocol import Session  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2]
               / 'reference' / 'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config' / 'xianjie.jat').is_file()

# Captured S> 12000 oracle for fu0UR1-0-1-1 (level 56, vip 10,
# xianjie ["1"], chenghao ["2"], no meiren).
ORACLE_12000 = {'1': 1811.0, '2': 2049.800048828125, '3': 996.7999877929688,
                '4': 191.64999389648438, '5': 196.64999389648438,
                '6': 147.40000915527344, '7': 616.0, '10': 1.0}

# role_equip_slot rows for fu0UR1-0-1-1 (matches test_attributes.CAPTURED_GEAR).
CAPTURED_GEAR = [
    {'goods_id': 'zj0021', 'rare_level': 1,
     'attributes': '{"fjattrstr":"{}","jjfailcount":0,"qhcount":2,'
                   '"qhxingxing":"[[1,1],[2,1]]"}'},
    {'goods_id': 'zj0201', 'rare_level': 2,
     'attributes': '{"fjattrstr":"{}","jjfailcount":0,"qhcount":3,'
                   '"qhxingxing":"[[1,1],[2,1],[3,1]]"}'},
    {'goods_id': 'zj0202', 'rare_level': 2,
     'attributes': '{"fjattrstr":"{}","jjfailcount":0,"qhcount":3,'
                   '"qhxingxing":"[[1,1],[2,1],[3,1]]"}'},
    {'goods_id': 'zj0209', 'rare_level': 2,
     'attributes': '{"fjattrstr":"{}","jjfailcount":0,"qhcount":3,'
                   '"qhxingxing":"[[1,1],[2,1],[3,1]]"}'},
    {'goods_id': 'zj0210', 'rare_level': 2,
     'attributes': '{"fjattrstr":"{}","jjfailcount":0,"qhcount":3,'
                   '"qhxingxing":"[[1,1],[2,1],[3,1]]"}'},
    {'goods_id': 'zj0212', 'rare_level': 2,
     'attributes': '{"fjattrstr":"{}","jjfailcount":0,"qhcount":3,'
                   '"qhxingxing":"[[1,1],[2,1],[3,1]]"}'},
    {'goods_id': 'zj0213', 'rare_level': 2,
     'attributes': '{"fjattrstr":"{}","jjfailcount":0,"qhcount":3,'
                   '"qhxingxing":"[[1,1],[2,1],[3,1]]"}'},
    {'goods_id': 'zj0214', 'rare_level': 2,
     'attributes': '{"fjattrstr":"{}","jjfailcount":0,"qhcount":3,'
                   '"qhxingxing":"[[1,1],[2,1],[3,1]]"}'},
    {'goods_id': 'zj0416', 'rare_level': 3,
     'attributes': '{"fjattrstr":"{\\"1\\":\\"9@5\\",\\"2\\":\\"11@5\\",'
                   '\\"3\\":\\"13@5\\",\\"4\\":\\"15@5\\"}","jjfailcount":0,'
                   '"qhcount":0}'},
    {'goods_id': 'zj0615', 'rare_level': 4,
     'attributes': '{"fjattrstr":"{\\"1\\":\\"8@5\\"}","jjfailcount":0,'
                   '"qhcount":0}'},
]


def bare_session():
    return Session(conn_id=1, check_sign=lambda *a: False,
                   get_roles=lambda u, s: [], server_start_ms=0, config=None)


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class XianjieSelectionTest(unittest.TestCase):
    """XianjiechenhaoServiceImpl.getXianjieId/chenHaoIds id selection."""

    def test_single_id_wins(self):
        self.assertEqual(bare_session().xianjie_id_for(
            {'xianjie_id': '["1"]'}), '1')

    def test_missing_row_is_null(self):
        self.assertIsNone(bare_session().xianjie_id_for(None))
        self.assertIsNone(bare_session().chenhao_ids_for(None))

    def test_empty_array_defaults_to_xianjie_1(self):
        self.assertEqual(bare_session().xianjie_id_for({'xianjie_id': '[]'}),
                         '1')

    def test_string_maximum_wins_over_numeric(self):
        # Java compares with String.compareTo: '2' > '10'.
        self.assertEqual(bare_session().xianjie_id_for(
            {'xianjie_id': '["2", "10"]'}), '2')

    def test_garbage_is_no_bag_not_a_fake_id(self):
        self.assertIsNone(bare_session().xianjie_id_for(
            {'xianjie_id': 'nope'}))
        self.assertIsNone(bare_session().chenhao_ids_for(
            {'chenhao_id': 'nope'}))

    def test_chenhao_lists_every_id_and_empty_is_null(self):
        self.assertEqual(bare_session().chenhao_ids_for(
            {'chenhao_id': '["2"]'}), ['2'])
        self.assertIsNone(bare_session().chenhao_ids_for({'chenhao_id': '[]'}))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class XianjieBagTest(unittest.TestCase):
    def setUp(self):
        self.cfg = GameConfig(str(REAL_CONFIG))

    def test_xianjie_1_bag_is_exact(self):
        self.assertEqual(self.cfg.xianjie_attribute_map('1'),
                         {'hitpoints': 60.0, 'mana': 60.0,
                          'physicdamage': 30.0, 'physicdefence': 15.0,
                          'critical': 8.0, 'volt': 8.0, 'attackrate': 3.0,
                          'velocity': 10.0})

    def test_unknown_id_is_no_bag(self):
        with self.assertLogs('config', level='WARNING'):
            self.assertEqual(self.cfg.xianjie_attribute_map('999'), {})


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class ChenghaoBagTest(unittest.TestCase):
    def setUp(self):
        self.cfg = GameConfig(str(REAL_CONFIG))

    def test_chenghao_2_gives_15_attack(self):
        self.assertEqual(self.cfg.chenghao_attribute_map(['2']),
                         {'physicdamage': 15.0})

    def test_ids_sum_like_map_util_add(self):
        self.assertEqual(self.cfg.chenghao_attribute_map(['2', '3']),
                         {'physicdamage': 15.0, 'physicdefence': 15.0})

    def test_unknown_ids_are_skipped(self):
        with self.assertLogs('config', level='WARNING'):
            self.assertEqual(self.cfg.chenghao_attribute_map(['999']), {})


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class VipSlotsTest(unittest.TestCase):
    def setUp(self):
        self.cfg = GameConfig(str(REAL_CONFIG))

    def test_vip_10_buff_id_and_slots(self):
        # vipbiao lv 10 -> vipbuff vip010; XiaoGuoBiao vip010 describe:
        # Atk +1000, Def +500, HP +2000, Aspd +10%, MS +10%.
        self.assertEqual(self.cfg.vip_buff_id(10), 'vip010')
        self.assertEqual(self.cfg.vip_effect_slots(10),
                         {'5': 1000.0, '7': 500.0, '1': 2000.0,
                          '14': 0.1, '16': 0.1})

    def test_no_vip_means_no_slots(self):
        self.assertIsNone(self.cfg.vip_buff_id(0))
        self.assertEqual(self.cfg.vip_effect_slots(0), {})
        self.assertIsNone(self.cfg.vip_buff_id(99))
        self.assertEqual(self.cfg.vip_effect_slots(99), {})
        self.assertEqual(self.cfg.vip_effect_slots(None), {})


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class MeirenBagTest(unittest.TestCase):
    def setUp(self):
        self.cfg = GameConfig(str(REAL_CONFIG))

    def test_real_id_resolves_to_its_type_bag(self):
        by_id, types = self.cfg.meiren_table()
        self.assertTrue(by_id)
        meinvid = sorted(by_id)[0]
        meiren_type, level = by_id[meinvid]
        self.assertEqual(self.cfg.meiren_type_for(meinvid), meiren_type)
        self.assertEqual(self.cfg.meiren_attribute_map([(meiren_type, level)]),
                         types[meiren_type][level])
        self.assertTrue(types[meiren_type][level])

    def test_unknown_type_or_level_is_no_bag(self):
        self.assertIsNone(self.cfg.meiren_type_for('nope'))
        with self.assertLogs('config', level='WARNING'):
            self.assertEqual(self.cfg.meiren_attribute_map([('nope', 1)]), {})
        by_id, types = self.cfg.meiren_table()
        meiren_type = sorted(types)[0]
        with self.assertLogs('config', level='WARNING'):
            self.assertEqual(
                self.cfg.meiren_attribute_map([(meiren_type, 99999)]), {})

    def test_pairs_skip_unlisted_ids_like_get_mei_ren_all_obj(self):
        sess = Session(conn_id=1, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [], server_start_ms=0,
                       config=self.cfg)
        by_id, _ = self.cfg.meiren_table()
        meinvid = sorted(by_id)[0]
        meiren_type, _ = by_id[meinvid]
        pairs = sess.meiren_pairs_for(
            [{'meiren_id': meinvid, 'meiren_level': 1, 'meiren_heti': 3},
             {'meiren_id': 'nope', 'meiren_level': 1, 'meiren_heti': 1}])
        self.assertEqual(pairs, [(meiren_type, 3)])


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class ZuoqiBagTest(unittest.TestCase):
    """replaceZuoqiAttribute: rank gate, level clamp, refined bag."""

    def setUp(self):
        self.cfg = GameConfig(str(REAL_CONFIG))

    def test_rank1_at_role_56_is_the_level_30_row_without_velocity(self):
        # role_zuoqi.rank 1 for fu0UR1-0-1-1; role level 56 clamps to
        # the rank's maxlv 30 (ZuoQiConfig.minLevel is never set).
        self.assertEqual(self.cfg.zuoqi_attribute_map(1, 56),
                         {'hitpoints': 134.0, 'mana': 101.0,
                          'physicdamage': 67.0, 'physicdefence': 34.0,
                          'critical': 17.0, 'volt': 17.0})

    def test_level_clamps_to_maxlv(self):
        self.assertEqual(self.cfg.zuoqi_attribute_map(1, 56),
                         self.cfg.zuoqi_attribute_map(1, 30))
        self.assertEqual(self.cfg.zuoqi_attribute_map(1, 5)['physicdamage'],
                         11.0)  # ridelv 5 row

    def test_no_rank_is_no_bag(self):
        self.assertEqual(self.cfg.zuoqi_attribute_map(0, 56), {})
        self.assertEqual(self.cfg.zuoqi_attribute_map(None, 56), {})
        with self.assertLogs('config', level='WARNING'):
            self.assertEqual(self.cfg.zuoqi_attribute_map(99, 56), {})


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class ZuoqiFightTest(unittest.TestCase):
    """getZuoQiJiChuFight/getZuoEquipFight: 12010 slot [3] vs the oracle.

    Probe-B captured [193, 0, 0] for fu0UR1-0-1-1 (rank 1, level 56 ->
    maxlv 30 row); probe-A captured [0, 0, 0] with no mount state. The
    193 is HashMap-order-proof: every permutation of the six fractional
    products truncates to 193 under Java's per-addition f2i.
    """

    def setUp(self):
        self.cfg = GameConfig(str(REAL_CONFIG))

    def test_rank1_at_role_56_fights_193(self):
        self.assertEqual(self.cfg.zuoqi_fight(1, 56), 193)
        self.assertEqual(self.cfg.zuoqi_fight(1, 30), 193)

    def test_no_rank_or_row_is_zero(self):
        self.assertEqual(self.cfg.zuoqi_fight(0, 56), 0)
        self.assertEqual(self.cfg.zuoqi_fight(None, 56), 0)
        with self.assertLogs('config', level='WARNING'):
            self.assertEqual(self.cfg.zuoqi_fight(99, 56), 0)

    def test_zuoqi_equip_ignores_body_slots(self):
        body = [dict(row, slot_num=-20) for row in CAPTURED_GEAR]
        self.assertEqual(self.cfg.zuoqi_equip_fight([]), 0)
        self.assertEqual(self.cfg.zuoqi_equip_fight(body), 0)

    def test_zuoqi_equip_row_fights_merged(self):
        row = dict(CAPTURED_GEAR[0], slot_num=-101)
        merged = self.cfg.equip_attribute_map([row])
        self.assertEqual(self.cfg.zuoqi_equip_fight([row]),
                         self.cfg.fight_value(merged))
        self.assertGreater(self.cfg.zuoqi_equip_fight([row]), 0)

    def test_fighting_info_slot_matches_the_oracle(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(os.path.join(tmp.name, 't.db'))
        self.addCleanup(store.close)
        store.create_account('hero', hash_password('pw'))
        role_id = store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56, max_mp=1811)
        store.save_role_zuoqi(role_id, zuoqi_rank=1, zuoqi_cur_rank=1)
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    store.list_roles(u, s)],
            server_start_ms=0, get_role_zuoqi=store.get_role_zuoqi,
            config=self.cfg)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        reply = decode(sess.fighting_info()[4:])
        self.assertEqual(reply[0], '12010')
        # Oracle probe-B slot [3]; longhun 0 (no attribute_goods_id).
        self.assertEqual(reply[1][3], [193, 0, 0])

    def test_fighting_info_slot_zero_without_mount(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(os.path.join(tmp.name, 't.db'))
        self.addCleanup(store.close)
        store.create_account('hero', hash_password('pw'))
        store.create_character('hero', 'fu1304', 'Wukong', job='C',
                               level=56, max_mp=1811)
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    store.list_roles(u, s)],
            server_start_ms=0, get_role_zuoqi=store.get_role_zuoqi,
            config=self.cfg)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        reply = decode(sess.fighting_info()[4:])
        self.assertEqual(reply[1][3], [0, 0, 0])


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class CaptureGoldenTest(unittest.TestCase):
    """The captured 12000, decomposed over the traced bags.

    Level 56 row + gear + dan + xianjie + chenghao + zuoqi + VIP effect
    closes the oracle exactly on all eight slots: the zuoqi bag
    (rank 1, level clamped 56 -> 30) contributes precisely the flat
    67/34/17/17 the previous phase left as a documented residual. The
    JIANGXINGTU bag is provably empty (both role_shenjiang rows carry
    empty jiangxing ids, which replaceShenJiangAttribute skips) and the
    ZUOQI_SPEED bag is empty (rideOrNo false at entry).
    """

    def setUp(self):
        self.cfg = GameConfig(str(REAL_CONFIG))

    def full_map(self):
        row = self.cfg.role_attribute_row(56)
        bags = [self.cfg.equip_attribute_map(CAPTURED_GEAR),
                self.cfg.shuxingdan_attribute_map(
                    ['fy_001', 'gj_001', 'sb_001', 'sm_001']),
                self.cfg.xianjie_attribute_map('1'),
                self.cfg.chenghao_attribute_map(['2']),
                self.cfg.zuoqi_attribute_map(1, 56)]
        return entry_attribute_map(row, 1811, bags=bags,
                                   effect=self.cfg.vip_effect_slots(10))

    def test_all_slots_match_the_oracle_exactly(self):
        got = self.full_map()
        for key, want in ORACLE_12000.items():
            if key == '10':
                self.assertEqual(got[key], want)
            else:
                self.assertAlmostEqual(got[key], want, places=4)


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class SessionWiringTest(unittest.TestCase):
    """role_bags/role_attribute_map read the migrated rows end to end."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56, max_mp=1811)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_equip=self.store.get_role_equip,
            get_role_attr_buffs=self.store.get_role_attr_buffs,
            get_role_vip=self.store.get_role_vip,
            get_role_xianjiechenhao=self.store.get_role_xianjiechenhao,
            get_role_meiren=self.store.get_role_meiren,
            get_role_zuoqi=self.store.get_role_zuoqi,
            config=self.cfg)

    def role(self):
        return self.store.list_roles('hero', 'fu1304')[0]

    def test_empty_sources_give_the_bare_level_map(self):
        got = self.sess.role_attribute_map(self.role())
        self.assertEqual(got['2'], 800.0)
        self.assertEqual(got['7'], 550.0)

    def test_vip_xianjie_chenghao_rows_land_in_the_map(self):
        self.store.save_role_vip(self.role_id, vip_level=10)
        self.store.save_role_xianjiechenhao(self.role_id, '["1"]', '["2"]')
        got = self.sess.role_attribute_map(self.role())
        # base 800 + xianjie 30 + chenghao 15, effect e5 +1000.
        self.assertEqual(got['2'], 1845.0)
        # velocity (550 + xianjie 10) * (1 + VIP e16 0.1).
        self.assertAlmostEqual(got['7'], 616.0, places=4)
        self.assertEqual(got['1'], 1811)

    def test_zuoqi_rank_row_lands_in_the_map(self):
        self.store.save_role_zuoqi(self.role_id, zuoqi_rank=1,
                                   zuoqi_cur_rank=1)
        got = self.sess.role_attribute_map(self.role())
        # bare level row 800/400 + zuoqi 67/34, no effect slots.
        self.assertEqual(got['2'], 867.0)
        self.assertEqual(got['3'], 434.0)
        # velocity refined out of the zuoqi bag: bare 550 only.
        self.assertEqual(got['7'], 550.0)

    def test_zuoqi_rank_zero_is_no_bag(self):
        self.store.save_role_zuoqi(self.role_id, zuoqi_rank=0,
                                   zuoqi_cur_rank=0)
        self.assertEqual(self.sess.role_attribute_map(self.role())['2'],
                         800.0)


if __name__ == '__main__':
    unittest.main()


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class ShenjiangSkillSlotTest(unittest.TestCase):
    """12010 slot [6][2]: captured role fu0UR1-0-1-1 sums to 24 (sj0101 + sj0108)."""

    def setUp(self):
        self.cfg = GameConfig(str(REAL_CONFIG))

    def test_captured_shenjiang_skills_sum_to_24(self):
        rows = [{'shenjiang_id': 'sj0101', 'skills': '{"xiaolongnv": 2}'},
                {'shenjiang_id': 'sj0108', 'skills': '{"longtaizi": 1}'}]
        self.assertEqual(self.cfg.shenjiang_skill_upgrade_fight(rows), 24)

    def test_no_shenjiang_means_zero(self):
        self.assertEqual(self.cfg.shenjiang_skill_upgrade_fight([]), 0)

    def test_bad_skill_json_is_skipped(self):
        rows = [{'shenjiang_id': 'sj0101', 'skills': 'not json'},
                {'shenjiang_id': 'sj0108', 'skills': '[1, 2]'}]
        self.assertEqual(self.cfg.shenjiang_skill_upgrade_fight(rows), 0)


class EquipInfoHelpersTest(unittest.TestCase):
    """GoodsEquipVo client helpers, traced from bytecode (31000 record)."""

    def vo(self, **fields):
        return equip_vo(json.dumps(fields))

    def test_zero_qhcount_gives_ten_zero_stars(self):
        self.assertEqual(qh_xingxings_client(self.vo(qhcount=0, qhxingxing='[[1,1]]')),
                         [0] * 10)

    def test_blank_or_missing_qhxingxing_gives_null(self):
        self.assertIsNone(qh_xingxings_client(self.vo(qhcount=2)))
        self.assertIsNone(qh_xingxings_client(self.vo(qhcount=2, qhxingxing='')))

    def test_more_star_pairs_than_qhcount_gives_null(self):
        # Java returns null when the array is longer than qhcount.
        self.assertIsNone(qh_xingxings_client(
            self.vo(qhcount=1, qhxingxing='[[1,1],[2,1]]')))

    def test_fewer_star_pairs_than_qhcount_are_zero_padded(self):
        self.assertEqual(qh_xingxings_client(
            self.vo(qhcount=3, qhxingxing='[[1,1],[2,0]]')), [1, 0, 0])

    def test_xingxing_lv_counts_pairs_whose_value_is_one(self):
        self.assertEqual(xingxing_lv(self.vo(qhcount=3, qhxingxing='[[1,1],[2,0],[3,1]]')), 2)
        self.assertEqual(xingxing_lv(self.vo(qhcount=0)), 0)

    def test_fujia_map_splits_id_at_count_and_keeps_empty_object(self):
        self.assertEqual(fujia_client_map(self.vo(fjattrstr='{"5-1":"7@2"}')),
                         {'5-1': [7, 2]})
        self.assertEqual(fujia_client_map(self.vo(fjattrstr='{}')), {})
        self.assertIsNone(fujia_client_map(self.vo(qhcount=0)))

    def test_non_json_blob_reads_as_blank(self):
        vo = equip_vo('not json')
        self.assertEqual(vo['qhcount'], 0)
        self.assertIsNone(qh_xingxings_client(vo))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class EquipInfoFrameTest(unittest.TestCase):
    """31000 end to end: real store rows, real config, decoded reply."""

    GEAR = [
        {'slot_num': 0, 'goods_id': 'zj0021', 'rare_level': 1, 'item_level': 0,
         'attributes': '{"fjattrstr":"{}","jjfailcount":0,"qhcount":2,'
                       '"qhxingxing":"[[1,1],[2,1]]"}'},
        {'slot_num': 3, 'goods_id': 'zj0202', 'rare_level': 2, 'item_level': 0,
         'attributes': '{"fjattrstr":"{}","jjfailcount":0,"qhcount":3,'
                       '"qhxingxing":"[[1,1],[2,1],[3,1]]"}'},
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56, max_mp=1811)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_equip=self.store.get_role_equip,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'

    def test_no_equipped_rows_sends_null(self):
        self.assertEqual(decode(self.sess.equip_info()[4:]), ['31000', None])

    def test_each_equipped_slot_is_one_eighteen_field_record(self):
        self.store.save_role_equip(self.role_id, self.GEAR)
        records = decode(self.sess.equip_info()[4:])[1]
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertEqual(len(record), 18)
        first, second = records
        self.assertEqual(first[2], 0)
        self.assertEqual(second[2], 3)
        self.assertEqual(first[4], str(self.role_id))
        self.assertEqual(first[3], 1)
        self.assertEqual(first[9], {})
        self.assertEqual(first[10], 2)
        self.assertEqual(first[14], [1, 1])
        self.assertEqual(second[14], [1, 1, 1])

    def test_zhanli_is_the_item_fight_from_the_equip_attribute_map(self):
        self.store.save_role_equip(self.role_id, self.GEAR)
        records = decode(self.sess.equip_info()[4:])[1]
        for item, record in zip(self.GEAR, records):
            self.assertEqual(record[12], self.cfg.equip_item_fight(item))
        self.assertGreater(records[0][12], 0)


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class SkillFightTest(unittest.TestCase):
    """12010 slot [2] = getSkillFighting over role_skill rows (JiNengBiao)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56, max_mp=1811)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_skills=self.store.get_role_skills,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'

    def seed(self, rows):
        for n, (category, level) in enumerate(rows):
            self.store.db.execute(
                'INSERT INTO role_skill(role_id, skill_key, category, level)'
                ' VALUES(?,?,?,?)', (self.role_id, f'k{n}', category, level))
        self.store.db.commit()

    def test_captured_niumowang_skills_sum_to_the_oracle(self):
        # Captured 12010 for fu0UR1-0-1-1 carries [16, 0]: four level-1
        # niumowang skills, each combat 4 at tabshow 2.
        self.seed([('niumowang1', 1), ('niumowang2', 1),
                   ('niumowang3', 1), ('niumowang4', 1)])
        self.assertEqual(self.cfg.skill_fight(self.store.get_role_skills(self.role_id)),
                         [16, 0])
        reply = decode(self.sess.fighting_info()[4:])
        self.assertEqual(reply[1][2], [16, 0])

    def test_no_skills_is_zero(self):
        self.assertEqual(self.cfg.skill_fight([]), [0, 0])

    def test_level_zero_formula_rows_count_as_zero(self):
        self.seed([('niumowang1', 0)])
        self.assertEqual(self.cfg.skill_fight(self.store.get_role_skills(self.role_id)),
                         [0, 0])

    def test_tabshow_one_rows_go_to_the_kangxin_bucket(self):
        row = next(r for r in self.cfg._jineng_rows()
                   if r.get('tabshow') == 1 and isinstance(r.get('combat'), int)
                   and r.get('combat') and r.get('level') == 1)
        self.assertEqual(self.cfg.skill_fight(
            [{'category': row['skilltype'], 'level': 1}]), [0, row['combat']])

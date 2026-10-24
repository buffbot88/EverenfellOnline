"""Wings (guangyi): 102000/102001/102002/102003 plus props 49/50/51.

Evidence: GuangyiServiceImpl/GuangYiExportServiceImpl bytecode, the
GuangYiConfigExportServiceImpl column mapping over guangyi.jat,
RoleGuangyi.xml storage, PropServiceImpl$GuangYi and
$GuangYiUseAttribute, and the ZhanDouLi getGuangYi* readers behind the
12010 slot [16]. Every test drives the real encrypted wire and real
SQLite; the buy price, pity window, blessing cap, wear toggle, dan caps
and the card's [0, level] quirk are pinned to the jar.
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode, encode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session, frame  # noqa: E402

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..',
                           'reference', 'TonNgoKhong', 'server', 'config',
                           'game')
HAVE_REAL = os.path.isfile(os.path.join(REAL_CONFIG, 'sys_config',
                                        'guangyi.jat'))

INITKEY = bytes.fromhex('00000009060f494e49544b4559')

BUY_PRICE = 100        # guangyi.jat row 1 `cost` (buyGuangYi's YB price)
LEVEL1_MATERIALS = 2   # row 1 needthingsvalue (guangyi001 x2)
BOOK = 'gylvsegongji1'  # wing-band skillbook, chibanglv 4


def decoded(out):
    if out is None:
        return []
    if isinstance(out, (bytes, bytearray)):
        return [decode(bytes(out)[4:])]
    return [decode(bytes(f)[4:]) for f in out]


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class GuangyiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'g.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.rid = str(self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=60,
            tongqian=1000000, lingshi=1000000, bind_lingshi=0))
        self.store.save_role_bag_state(self.rid, bag_capacity=144,
                                       storage_capacity=30)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            save_role_state=self.store.update_character_state,
            get_role_guangyi=self.store.get_role_guangyi,
            save_role_guangyi=self.store.save_role_guangyi,
            get_role_equip=self.store.get_role_equip,
            get_role_zuoqi=self.store.get_role_zuoqi,
            get_role_skills=self.store.get_role_skills,
            get_role_shenjiang=self.store.get_role_shenjiang,
            get_role_qibing=self.store.get_role_qibing,
            get_role_vip=self.store.get_role_vip,
            get_role_attr_buffs=self.store.get_role_attr_buffs,
            get_role_skillbook_slots=self.store.get_role_skillbook_slots,
            insert_role_skillbook_slot=
            self.store.insert_role_skillbook_slot,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_slot_by_bag_id=
            self.store.get_role_bag_slot_by_bag_id,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'

    # -- helpers ---------------------------------------------------------
    def wire(self, cmd, data):
        s = self.sess
        if s.cipher is None:
            s.feed(INITKEY)
        return decoded(s.feed(frame(s.cipher.encode(encode([cmd, data])))))

    def role(self):
        return self.store.list_roles('hero', 'fu1304')[0]

    def wing(self):
        return self.store.get_role_guangyi(self.rid)

    def bag(self, goods, count, slot, bag_id=None):
        self.store.insert_role_bag_slot(
            self.rid, {'slot_num': slot, 'goods_id': goods,
                       'count': count, 'bind': 0,
                       'bag_id': bag_id or 'g%d' % slot})

    def grant(self, level=1, **over):
        now = int(time.time() * 1000)
        row = {'peidai_id': level, 'level': level, 'lucky': 0,
               'ispeidai': 1, 'attr_dan': '{}', 'fail_count': 0,
               'upgrade_time': now, 'lingqu_time': now, 'update_time': now}
        row.update(over)
        self.store.save_role_guangyi(self.rid, **row)

    def slot16(self, frames):
        body = [f for f in frames if f[0] == '12010'][-1][1]
        self.assertEqual(len(body), 25)
        return body[16]

    # -- 102000 panel ----------------------------------------------------
    def test_info_without_row_is_null(self):
        self.assertEqual(self.wire(102000, None), [['102000', None]])

    def test_info_reports_row_and_dans(self):
        self.grant(3, peidai_id=2, lucky=7, ispeidai=0,
                   attr_dan='{"yihun": 4, "yiling": 2}')
        self.assertEqual(self.wire(102000, None), [
            ['102000', [2, 3, 7, 0, [['yihun', 4], ['yiling', 2]]]]])

    def test_info_clears_stale_day_blessing(self):
        stale = int(time.time() * 1000) - 2 * 86400000
        self.grant(4, fail_count=9, lucky=30, update_time=stale)
        got = self.wire(102000, None)
        self.assertEqual(got, [['102000', [4, 4, 0, 1, []]]])
        row = self.wing()
        self.assertEqual((row['fail_count'], row['lucky']), (0, 0))
        self.assertGreater(row['update_time'], stale)

    # -- 102002 buy ------------------------------------------------------
    def test_buy_charges_yb_and_grants_level_one(self):
        got = self.wire(102002, None)
        self.assertEqual([f[0] for f in got], ['102002', '12010'])
        self.assertEqual(got[0], ['102002', [1, 1, 0]])
        self.assertEqual(self.role()['lingshi'], 1000000 - BUY_PRICE)
        row = self.wing()
        self.assertEqual((row['level'], row['peidai_id'],
                          row['ispeidai']), (1, 1, 1))
        self.assertEqual(row['attr_dan'], '{}')
        self.assertEqual(self.slot16(got)[0], self.cfg.guangyi_fight(1))

    def test_buy_twice_answers_owned_code(self):
        self.grant()
        self.assertEqual(self.wire(102002, None),
                         [['102002', [0, 102001]]])
        self.assertEqual(self.role()['lingshi'], 1000000)

    def test_buy_without_yb_answers_1002(self):
        self.store.update_character_state(self.rid, lingshi=99)
        self.assertEqual(self.wire(102002, None),
                         [['102002', [0, 1002]]])
        self.assertIsNone(self.wing())

    # -- 102001 upgrade --------------------------------------------------
    def test_upgrade_without_row_is_null(self):
        self.assertEqual(self.wire(102001, False), [['102001', None]])

    def test_upgrade_non_bool_is_silent(self):
        self.grant()
        self.assertEqual(self.wire(102001, 1), [])
        self.assertEqual(self.wire(102001, None), [])
        self.assertEqual(self.wing()['level'], 1)

    def test_upgrade_short_materials_answers_1005(self):
        self.grant()
        self.assertEqual(self.wire(102001, False), [['102001', [0, 1005]]])
        self.assertEqual(self.wing()['level'], 1)

    def test_upgrade_under_min_times_fails_and_banks_blessing(self):
        self.grant(fail_count=56)  # mintims 57: the roll cannot pass
        self.bag('guangyi001', LEVEL1_MATERIALS, 10)
        got = self.wire(102001, False)
        self.assertEqual([f[0] for f in got], ['102001'])
        body = got[0][1]
        self.assertEqual(body[0], -1)
        self.assertEqual(body[1], 1)
        self.assertTrue(3 <= body[2] <= 5)  # addminblessing..addmaxblessing
        row = self.wing()
        self.assertEqual(row['fail_count'], 57)
        self.assertEqual(row['lucky'], body[2])
        self.assertIsNone(self.store.get_role_bag_slot(self.rid, 10))

    def test_upgrade_past_max_times_succeeds_and_notices(self):
        self.grant(fail_count=64)  # maxtimes 63: forced success
        self.bag('guangyi001', LEVEL1_MATERIALS, 10)
        got = self.wire(102001, False)
        self.assertEqual([f[0] for f in got], ['11101', '102001', '12010'])
        self.assertEqual(got[0][1][0], 102000)
        self.assertEqual(got[0][1][1][1], 2)
        self.assertEqual(got[0][1][1][2], self.cfg.guangyi_config(2)['name'])
        self.assertEqual(got[1], ['102001', [1, 2, 0, 1]])
        row = self.wing()
        self.assertEqual((row['level'], row['peidai_id'],
                          row['ispeidai']), (2, 2, 1))
        self.assertEqual((row['fail_count'], row['lucky']), (0, 0))
        self.assertGreater(row['upgrade_time'], 0)
        self.assertGreater(self.slot16(got)[0], 0)

    def test_upgrade_blessing_cap_forces_success(self):
        # maxblessing 500 on the level-1 band; 498 + at least 3 crosses it.
        self.grant(fail_count=56, lucky=498)
        self.bag('guangyi001', LEVEL1_MATERIALS, 10)
        got = self.wire(102001, False)
        self.assertEqual([f[0] for f in got], ['11101', '102001', '12010'])
        self.assertEqual(got[1][1][0], 1)
        self.assertEqual(self.wing()['level'], 2)

    def test_upgrade_at_max_level_answers_1000(self):
        top = self.cfg.guangyi_max_level()
        self.grant(top)
        self.bag('guangyi001', 100, 10)
        self.assertEqual(self.wire(102001, False),
                         [['102001', [0, 1000]]])
        self.assertEqual(self.wing()['level'], top)

    # -- 102003 wear -----------------------------------------------------
    def test_wear_picks_owned_id(self):
        self.grant(3, peidai_id=1)
        got = self.wire(102003, [2])
        self.assertEqual(got, [['102003', [1, 2, 1]]])
        self.assertEqual(self.wing()['peidai_id'], 2)

    def test_wear_above_owned_level_answers_102002(self):
        self.grant(2)
        self.assertEqual(self.wire(102003, [3]),
                         [['102003', [0, 102002]]])
        self.assertEqual(self.wing()['peidai_id'], 2)

    def test_wear_null_toggles_ispeidai(self):
        self.grant(2, ispeidai=1)
        self.assertEqual(self.wire(102003, [None]),
                         [['102003', [1, 2, 0]]])
        self.assertEqual(self.wire(102003, [None]),
                         [['102003', [1, 2, 1]]])
        self.assertEqual(self.wing()['peidai_id'], 2)

    def test_wear_without_row_is_silent(self):
        self.assertEqual(self.wire(102003, [1]), [])

    # -- wing dan (props 50/51) ------------------------------------------
    def test_yihun_dan_bumps_map_and_refreshes(self):
        self.grant(3)
        self.bag('yihun', 2, 20, 'dan1')
        got = self.wire(30301, 'dan1')
        self.assertEqual([f[0] for f in got],
                         ['102000', '30301', '12010'])
        self.assertEqual(got[0][1][:4], [3, 3, 0, 1])
        self.assertEqual(got[0][1][4], [['yihun', 1]])
        self.assertEqual(got[1], ['30301', [1, 'dan1']])
        self.assertEqual(json.loads(self.wing()['attr_dan']),
                         {'yihun': 1})
        self.assertEqual(self.slot16(got)[1],
                         self.cfg.guangyi_dan_fight(3, {'yihun': 1}))
        self.assertGreater(self.slot16(got)[1], 0)

    def test_yiling_dan_scales_the_wing_bag(self):
        self.grant(4)
        self.bag('yiling', 1, 21, 'dan2')
        got = self.wire(30301, 'dan2')
        self.assertEqual(got[0][1][4], [['yiling', 1]])
        expected = self.cfg.guangyi_dan_fight(4, {'yiling': 1})
        self.assertEqual(self.slot16(got)[1], expected)
        self.assertGreater(expected, 0)

    def test_dan_capped_answers_87104_and_keeps_goods(self):
        self.grant(3, attr_dan='{"yihun": 100}')  # level 3 xlimit 100
        self.bag('yihun', 1, 22, 'dan3')
        self.assertEqual(self.wire(30301, 'dan3'),
                         [['30301', [0, 87104]]])
        self.assertEqual(self.store.get_role_bag_slot(
            self.rid, 22)['count'], 1)

    def test_dan_below_wing_level_cap_is_capped(self):
        # Level 1/2 yihun cap is 0: the pill cannot be used at all.
        self.grant(1)
        self.bag('yihun', 1, 23, 'dan4')
        self.assertEqual(self.wire(30301, 'dan4'),
                         [['30301', [0, 87104]]])

    def test_dan_without_wing_row_is_silent(self):
        self.bag('yihun', 1, 24, 'dan5')
        self.assertEqual(self.wire(30301, 'dan5'), [])
        self.assertEqual(self.store.get_role_bag_slot(
            self.rid, 24)['count'], 1)

    # -- wing card (prop 49) ---------------------------------------------
    def test_card_grants_level_one_and_stays_in_bag(self):
        self.bag('guangyi01', 1, 30, 'card1')
        got = self.wire(30301, 'card1')
        # propJiHuo's 102002 push, then the reply built from result[1]
        # (the level) as [0, 1]; the early return skips the consume.
        self.assertEqual([f[0] for f in got],
                         ['102002', '30301', '12010'])
        self.assertEqual(got[0], ['102002', [1, 1, 0]])
        self.assertEqual(got[1], ['30301', [0, 1]])
        self.assertEqual(self.wing()['level'], 1)
        self.assertEqual(self.store.get_role_bag_slot(
            self.rid, 30)['count'], 1)

    def test_card_on_owned_level_answers_102001(self):
        self.grant(2)
        self.bag('guangyi01', 1, 31, 'card2')
        self.assertEqual(self.wire(30301, 'card2'),
                         [['30301', [0, 102001]]])
        self.assertEqual(self.wing()['level'], 2)

    # -- combat integration ----------------------------------------------
    def test_wing_attributes_feed_the_12000_bag(self):
        self.grant(4)
        bags = self.sess.role_bags(self.role())
        wing = self.cfg.guangyi_attribute_map(4)
        self.assertIn(wing, bags)
        self.assertEqual(self.slot16(self.wire(12010, None))[0],
                         self.cfg.guangyi_fight(4))

    def test_skillbook_fight_uses_worn_wing_book(self):
        book = self.cfg.skillbook_book(BOOK)
        info = self.cfg.skill_info(book.get('jhjn'),
                                   book.get('skillbooklevel'))
        self.assertIsNotNone(info)
        self.store.insert_role_skillbook_slot(
            self.rid, {'slot_num': 10051, 'goods_id': BOOK, 'count': 1,
                       'bind': 0, 'expire_time': 0, 'rare_level': 1,
                       'item_level': 1})
        self.assertEqual(self.sess._guangyi_skillbook_fight(self.rid),
                         int(info.get('combat') or 0))
        self.assertEqual(self.wire(12010, None)[0][1][16][2],
                         int(info.get('combat') or 0))

    # -- skillbook eligibility -------------------------------------------
    def test_wing_books_unlock_with_the_wing_level(self):
        book = self.cfg.skillbook_book(BOOK)
        self.assertEqual(int(book.get('chibanglv') or 0), 4)
        self.grant(3)
        self.assertEqual(self.sess._skillbook_wear_gate(
            self.rid, self.role(), book, None, 10051), [0, 99011])
        self.assertFalse(self.sess._skillbook_slot_open(
            self.rid, self.role(), 10051))
        self.grant(4)
        self.assertIsNone(self.sess._skillbook_wear_gate(
            self.rid, self.role(), book, None, 10051))
        self.assertTrue(self.sess._skillbook_slot_open(
            self.rid, self.role(), 10051))

    def test_wing_skill_slots_follow_mutex_cells(self):
        self.grant(4)  # level 4 opens mutex1 only
        self.assertTrue(self.cfg.guangyi_skill_open(4, 1))
        self.assertFalse(self.cfg.guangyi_skill_open(4, 2))
        self.assertFalse(self.cfg.guangyi_skill_open(1, 1))


if __name__ == '__main__':
    unittest.main()

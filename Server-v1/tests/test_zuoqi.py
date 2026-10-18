"""Mount panel/ride/claim: 33001 reads the rank row, 33000 rides, 33004 claims.

Evidence: ZuoQiAction.ZuoqiMianban/rideZuoQi/lingquZuoqi and
RoleZuoQiServiceImpl.getZuoQiPannel/rideZuoqi/changeZuoqiRank (33000 clamps
the ridden rank and stage-pushes [roleId, rank]; 33001 answers
[1, [rank, level, lucky, fight], [], kaifu, cost] or [0, [520005]] with no
mount; 33004 sets rank 1 once and stays silent past the rank gate; 33003
banks each attempt's cailiao count into kaifuData (fail slot 4, panel
cost); 33005 refunds the fanhuan rank's tracked spend with a feed row;
33007 lists [cost, feed]; 33006 grants the kaifu meiren ahead of an
82001 push; 33011 reports the claimable-now award ranks).
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
from game.protocol import Session  # noqa: E402

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..',
                           'reference', 'TonNgoKhong', 'server', 'config',
                           'game')
HAVE_REAL = os.path.isdir(REAL_CONFIG)


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class ZuoqiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'z.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            save_role_state=self.store.update_character_state,
            get_role_equip=self.store.get_role_equip,
            get_role_meiren=self.store.get_role_meiren,
            save_role_meiren=self.store.save_role_meiren,
            get_role_zuoqi=self.store.get_role_zuoqi,
            save_role_zuoqi=self.store.save_role_zuoqi,
            get_zuoqi_fanhuan=self.store.get_zuoqi_fanhuan,
            save_zuoqi_fanhuan=self.store.save_zuoqi_fanhuan,
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

    def test_panel_without_mount_is_empty_33001(self):
        out = self.sess.zuoqi_panel(['33001', ['hero', 1]])
        (frame,) = self.frames(out)
        self.assertEqual(frame[0], '33001')
        self.assertEqual(frame[1], [0, [520005]])
        row = self.store.get_role_zuoqi(self.role_id)
        self.assertEqual((row['zuoqi_rank'], row['zuoqi_cur_rank'],
                          row['lucky_value']), (0, 0, 0))

    def test_claim_grants_rank1_33004_then_silent(self):
        (frame,) = self.frames(self.sess.zuoqi_claim())
        self.assertEqual(frame[0], '33004')
        self.assertEqual(frame[1][0], 1)
        self.assertEqual(frame[1][1], 1)
        row = self.store.get_role_zuoqi(self.role_id)
        self.assertEqual((row['zuoqi_rank'], row['zuoqi_cur_rank']), (1, 1))
        self.assertIsNone(self.sess.zuoqi_claim())

    def test_ride_clamps_and_stage_pushes_33000(self):
        self.sess.zuoqi_claim()
        (frame,) = self.frames(self.sess.zuoqi_ride(['33000', ['x', 1]]))
        self.assertEqual(frame[0], '33000')
        self.assertEqual(frame[1], [str(self.role_id), 1])
        self.assertEqual(
            self.store.get_role_zuoqi(self.role_id)['zuoqi_cur_rank'], 1)
        # Past the owned rank falls back to the owned rank.
        (frame,) = self.frames(self.sess.zuoqi_ride(['33000', ['x', 5]]))
        self.assertEqual(frame[1][1], 1)
        # Dismounting to 0 is allowed.
        (frame,) = self.frames(self.sess.zuoqi_ride(['33000', ['x', 0]]))
        self.assertEqual(frame[1][1], 0)

    def test_panel_with_mount_33001(self):
        self.sess.zuoqi_claim()
        (frame,) = self.frames(self.sess.zuoqi_panel(['33001', ['x', 1]]))
        self.assertEqual(frame[0], '33001')
        head, inner, items, kaifu, cost = frame[1]
        self.assertEqual(head, 1)
        self.assertEqual(inner[0], 1)
        self.assertEqual(inner[1], self.cfg.zuoqi_rank_config(1)['max_level']
                         if 56 > self.cfg.zuoqi_rank_config(1)['max_level']
                         else 56)
        self.assertEqual(inner[2], 0)
        self.assertEqual(inner[3], self.cfg.zuoqi_fight(1, 56))
        self.assertGreater(inner[3], 0)
        # server_start_ms 0 reads as kaifu day 0, inside the 3-day window.
        self.assertEqual((items, kaifu, cost), ([], True, 0))
        self.sess.server_start_ms = (
            __import__('time').time() * 1000 - 10 * 86400 * 1000)
        (frame,) = self.frames(self.sess.zuoqi_panel(['33001', ['x', 1]]))
        self.assertEqual(frame[1][3:], [False, 0])

    def test_stale_day_restamps_update_time(self):
        self.sess.zuoqi_claim()
        self.store.save_role_zuoqi(self.role_id, 1, 1, 7, 1)
        before = self.store.get_role_zuoqi(self.role_id)['update_time']
        self.sess.zuoqi_panel(['33001', ['x', 1]])
        after = self.store.get_role_zuoqi(self.role_id)['update_time']
        self.assertNotEqual(before, after)
        self.assertTrue(self.sess._same_day_ms(
            __import__('time').time() * 1000, after))

    def give_pills(self, goods_id, count, slot=10):
        self.store.insert_role_bag_slot(
            self.role_id,
            {'slot_num': slot, 'goods_id': goods_id, 'count': count,
             'bind': 0})

    def pill_stock(self, goods_id='jinjiedan001'):
        return sum(
            s.get('count') or 0
            for s in self.store.get_role_bag_slots(self.role_id, 1, 150)
            if s.get('goods_id') == goods_id)

    def test_jinjie_bad_shape_silent_33003(self):
        self.assertIsNone(self.sess.zuoqi_jinjie(['33003', ['x']]))
        self.assertIsNone(self.sess.zuoqi_jinjie(['33003', 2]))
        self.assertIsNone(self.sess.zuoqi_jinjie(['33003', True]))

    def test_jinjie_without_mount_silent_33003(self):
        self.assertIsNone(self.sess.zuoqi_jinjie(['33003', 0]))

    def test_jinjie_max_rank_gate_33003(self):
        self.store.save_role_zuoqi(self.role_id, 10, 10, 0, 0)
        (frame,) = self.frames(self.sess.zuoqi_jinjie(['33003', 0]))
        self.assertEqual(frame, ['33003', [0, [520001]]])

    def test_jinjie_level_gate_33003(self):
        self.store.update_character_state(self.role_id, level=1)
        self.store.save_role_zuoqi(self.role_id, 5, 5, 0, 0)
        (frame,) = self.frames(self.sess.zuoqi_jinjie(['33003', 0]))
        self.assertEqual(frame, ['33003', [0, [520002, 40]]])

    def test_jinjie_no_pill_no_autobuy_33003(self):
        self.sess.zuoqi_claim()
        (frame,) = self.frames(self.sess.zuoqi_jinjie(['33003', 0]))
        self.assertEqual(frame, ['33003', [0, 1005]])
        self.assertEqual(
            self.store.get_role_zuoqi(self.role_id)['zuoqi_rank'], 1)

    def test_jinjie_fail_pity_path_33003(self):
        self.sess.zuoqi_claim()
        self.give_pills('jinjiedan001', 1)
        out = self.sess.zuoqi_jinjie(['33003', 0])
        first, second = self.frames(out)
        # 12001 exp notice ahead of the reply, like the kill path.
        self.assertEqual(first[0], '12001')
        self.assertEqual(second[0], '33003')
        head, lucky, kind, exp, cost = second[1]
        self.assertEqual((head, cost), (-1, 0))
        self.assertIn((kind, exp), [(0, 5000), (1, 8000), (2, 10000)])
        self.assertTrue(2 <= lucky <= 4)
        self.assertEqual(self.pill_stock(), 0)
        row = self.store.get_role_zuoqi(self.role_id)
        self.assertEqual((row['zuoqi_rank'], row['fail_count'],
                          row['lucky_value'], row['total_exp']),
                         (1, 1, lucky, exp))

    def test_jinjie_success_pity_path_33003(self):
        self.sess.zuoqi_claim()
        self.give_pills('jinjiedan001', 1)
        self.store.save_role_zuoqi(self.role_id, 1, 1, 0, 0, 1, 0, 0,
                                   None, 0, 0)
        first, second = self.frames(self.sess.zuoqi_jinjie(['33003', 0]))
        # The (2, 40) row wants a notice: 11101 ahead of the reply.
        self.assertEqual(first,
                         ['11101', [520013, ['Wukong', 2, 'ม้ามังกรขาว']]])
        self.assertEqual(second[0], '33003')
        head, inner, items, kaifu, cost = second[1]
        self.assertEqual(head, 1)
        self.assertEqual(inner[0], 2)
        self.assertEqual(inner[1], 40)
        self.assertEqual(inner[2], 0)
        self.assertEqual(inner[3], self.cfg.zuoqi_fight(2, 56))
        self.assertEqual(self.pill_stock(), 0)
        row = self.store.get_role_zuoqi(self.role_id)
        self.assertEqual((row['zuoqi_rank'], row['zuoqi_cur_rank'],
                          row['fail_count'], row['lucky_value']),
                         (2, 2, 0, 0))

    def test_jinjie_lucky_full_success_33003(self):
        self.sess.zuoqi_claim()
        self.give_pills('jinjiedan001', 1)
        self.store.save_role_zuoqi(self.role_id, 1, 1, 100, 0, 0, 0, 0,
                                   None, 0, 0)
        out = self.sess.zuoqi_jinjie(['33003', 0])
        frames = self.frames(out)
        self.assertEqual(frames[-1][1][1][0], 2)
        self.assertEqual(
            self.store.get_role_zuoqi(self.role_id)['zuoqi_rank'], 2)

    def test_jinjie_exp_cap_33003(self):
        self.sess.zuoqi_claim()
        self.give_pills('jinjiedan001', 1)
        self.store.save_role_zuoqi(self.role_id, 1, 1, 0, 0, 0, 100000, 0,
                                   None, 0, 0)
        before = self.store.list_roles('hero', 'fu1304')[0]['exp']
        (frame,) = self.frames(self.sess.zuoqi_jinjie(['33003', 0]))
        self.assertEqual(frame[0], '33003')
        self.assertEqual(frame[1][0], -1)
        self.assertEqual(frame[1][2:], [0, -1, 0])
        self.assertTrue(2 <= frame[1][1] <= 4)
        after = self.store.list_roles('hero', 'fu1304')[0]['exp']
        self.assertEqual(before, after)

    def test_jinjie_autobuy_pays_mall_yb_33003(self):
        self.sess.zuoqi_claim()
        self.store.update_character_state(self.role_id, lingshi=1000)
        self.store.save_role_zuoqi(self.role_id, 1, 1, 0, 0, 1, 0, 0,
                                   None, 0, 0)
        self.sess.zuoqi_jinjie(['33003', 1])
        roles = self.store.list_roles('hero', 'fu1304')
        self.assertEqual(roles[0]['lingshi'], 970)
        self.assertEqual(
            self.store.get_role_zuoqi(self.role_id)['zuoqi_rank'], 2)

    def test_jinjie_substitute_pill_33003(self):
        self.store.save_role_zuoqi(self.role_id, 6, 6, 0, 0, 1, 0, 0,
                                   None, 0, 0)
        self.give_pills('jinjiedan006', 5)
        out = self.sess.zuoqi_jinjie(['33003', 0])
        frames = self.frames(out)
        self.assertEqual(frames[-1][0], '33003')
        self.assertEqual(self.pill_stock('jinjiedan006'), 0)

    def test_jinjie_banks_cost_count_for_fanhuan_rank_33003(self):
        self.store.save_role_zuoqi(self.role_id, 4, 4, 0, 0)
        self.give_pills('jinjiedan001', 3)
        out = self.sess.zuoqi_jinjie(['33003', 0])
        frames = self.frames(out)
        self.assertEqual(frames[-1][0], '33003')
        # fail is forced (0 fails < 31 minTimes); slot 4 is the rank-4
        # spend, banked before the lottery.
        self.assertEqual(frames[-1][1][0], -1)
        self.assertEqual(frames[-1][1][4], 3)
        row = self.store.get_role_zuoqi(self.role_id)
        self.assertIn('"4": 3', row['kaifu_data'])
        # The panel cost slot reads the same count.
        (frame,) = self.frames(self.sess.zuoqi_panel(['33001', ['x', 4]]))
        self.assertEqual(frame[1][3:], [True, 3])

    def test_fanhuan_gates_33005(self):
        # No mount row at all.
        (frame,) = self.frames(self.sess.zuoqi_fanhuan())
        self.assertEqual(frame, ['33005', [0, 520020]])
        # Rank at/below the fanhuan rank 4.
        self.store.save_role_zuoqi(self.role_id, 4, 4, 0, 0)
        (frame,) = self.frames(self.sess.zuoqi_fanhuan())
        self.assertEqual(frame, ['33005', [0, 520020]])
        # Past the 3-day kaifu window.
        self.store.save_role_zuoqi(self.role_id, 5, 5, 0, 0)
        self.sess.server_start_ms = (
            __import__('time').time() * 1000 - 10 * 86400 * 1000)
        (frame,) = self.frames(self.sess.zuoqi_fanhuan())
        self.assertEqual(frame, ['33005', [0, 520024]])
        self.sess.server_start_ms = 0

    def test_fanhuan_claim_pays_tracked_spend_33005(self):
        self.store.save_role_zuoqi(
            self.role_id, 5, 5, 0, 0, 0, 0, 0, None, 0, 0,
            '{"cost-count": {"4": 7}}')
        (frame,) = self.frames(self.sess.zuoqi_fanhuan())
        self.assertEqual(frame, ['33005', [1, [['jinjiedan001', 7]]]])
        slots = [s for s in
                 self.store.get_role_bag_slots(self.role_id, 1, 150)
                 if s.get('goods_id') == 'jinjiedan001']
        self.assertEqual(sum(s.get('count') or 0 for s in slots), 7)
        self.assertTrue(all(s.get('bind') == 1 for s in slots))
        now = __import__('time').time() * 1000
        for slot in slots:
            self.assertTrue(
                now + 3 * 3600 * 1000 - 60000 <= slot.get('expire_time')
                <= now + 3 * 3600 * 1000 + 60000)
        feed = self.store.get_zuoqi_fanhuan()
        self.assertEqual(len(feed), 1)
        self.assertTrue(feed[0][0].startswith('{user|'))
        self.assertTrue(feed[0][0].endswith(',Wukong,0,0}'))
        self.assertEqual(feed[0][1], 7)
        # Claimed reads back as claimed.
        (frame,) = self.frames(self.sess.zuoqi_fanhuan())
        self.assertEqual(frame, ['33005', [0, 520022]])

    def test_fanhuan_full_bag_33005(self):
        self.store.save_role_zuoqi(
            self.role_id, 5, 5, 0, 0, 0, 0, 0, None, 0, 0,
            '{"cost-count": {"4": 50000}}')
        (frame,) = self.frames(self.sess.zuoqi_fanhuan())
        self.assertEqual(frame, ['33005', [0, 1006]])
        self.assertEqual(self.store.get_zuoqi_fanhuan(), [])

    def test_fanhuan_list_33007(self):
        # No mount row answers null.
        (frame,) = self.frames(self.sess.zuoqi_fanhuan_list())
        self.assertEqual(frame, ['33007', None])
        self.store.save_role_zuoqi(
            self.role_id, 5, 5, 0, 0, 0, 0, 0, None, 0, 0,
            '{"cost-count": {"4": 7}}')
        (frame,) = self.frames(self.sess.zuoqi_fanhuan_list())
        self.assertEqual(frame, ['33007', [7, None]])
        self.sess.zuoqi_fanhuan()
        (frame,) = self.frames(self.sess.zuoqi_fanhuan_list())
        self.assertEqual(frame[0], '33007')
        self.assertEqual(frame[1][0], 7)
        self.assertEqual(len(frame[1][1]), 1)
        self.assertEqual(frame[1][1][0][1], 7)

    def test_meiren_gates_33006(self):
        (frame,) = self.frames(self.sess.zuoqi_jiangli_meiren())
        self.assertEqual(frame, ['33006', [0, 520021]])
        self.store.save_role_zuoqi(self.role_id, 3, 3, 0, 0)
        (frame,) = self.frames(self.sess.zuoqi_jiangli_meiren())
        self.assertEqual(frame, ['33006', [0, 520021]])
        self.store.save_role_zuoqi(self.role_id, 4, 4, 0, 0)
        self.sess.server_start_ms = (
            __import__('time').time() * 1000 - 10 * 86400 * 1000)
        (frame,) = self.frames(self.sess.zuoqi_jiangli_meiren())
        self.assertEqual(frame, ['33006', [0, 520024]])
        self.sess.server_start_ms = 0

    def test_meiren_claim_pushes_82001_33006(self):
        self.store.save_role_zuoqi(self.role_id, 4, 4, 0, 0)
        out = self.sess.zuoqi_jiangli_meiren()
        first, second = self.frames(out)
        self.assertEqual(first, ['82001', [1, 'baijingjing', 1]])
        self.assertEqual(second, ['33006', [1, 'baijingjing']])
        owned = self.store.get_role_meiren(self.role_id)
        self.assertEqual(len(owned), 1)
        self.assertEqual(owned[0]['meiren_level'], 1)
        self.assertEqual(owned[0]['meiren_heti'], 0)
        self.assertEqual(
            self.cfg.meiren_type_for(owned[0]['meiren_id']), 'baijingjing')
        # Claimed reads back as claimed, with no second push.
        (frame,) = self.frames(self.sess.zuoqi_jiangli_meiren())
        self.assertEqual(frame, ['33006', [0, 520023]])
        self.assertEqual(len(self.store.get_role_meiren(self.role_id)), 1)

    def test_award_info_33011(self):
        # No mount row answers the empty array.
        (frame,) = self.frames(self.sess.zuoqi_award_info())
        self.assertEqual(frame, ['33011', []])
        # Rank 5 in kaifu: both the rank-4 refund and the rank-3
        # meiren are claimable.
        self.store.save_role_zuoqi(self.role_id, 5, 5, 0, 0)
        (frame,) = self.frames(self.sess.zuoqi_award_info())
        self.assertEqual(frame, ['33011', [4, 3]])
        # Rank 1: nothing claimable.
        self.store.save_role_zuoqi(self.role_id, 1, 1, 0, 0)
        (frame,) = self.frames(self.sess.zuoqi_award_info())
        self.assertEqual(frame, ['33011', [None, None]])
        # After both claims the slots clear.
        self.store.save_role_zuoqi(
            self.role_id, 5, 5, 0, 0, 0, 0, 0, None, 0, 0,
            '{"fanhuan": true, "meiren": true}')
        (frame,) = self.frames(self.sess.zuoqi_award_info())
        self.assertEqual(frame, ['33011', [None, None]])

    def test_zhanli_without_mount_is_zero_33008(self):
        (frame,) = self.frames(self.sess.zuoqi_zhanli())
        self.assertEqual(frame, ['33008', 0])

    def test_zhanli_sums_jichu_and_mount_gear_33008(self):
        self.sess.zuoqi_claim()
        (frame,) = self.frames(self.sess.zuoqi_zhanli())
        self.assertEqual(frame, ['33008', self.cfg.zuoqi_fight(1, 56)])
        self.assertGreater(frame[1], 0)
        self.store.save_role_equip(
            self.role_id, [{'slot_num': -100, 'goods_id': 'zj0011',
                            'rare_level': 1, 'item_level': 1,
                            'attributes': None}])
        rows = self.store.get_role_equip(self.role_id)
        (frame,) = self.frames(self.sess.zuoqi_zhanli())
        self.assertEqual(
            frame,
            ['33008', self.cfg.zuoqi_fight(1, 56)
             + self.cfg.zuoqi_equip_fight(rows)])
        self.assertGreater(frame[1], self.cfg.zuoqi_fight(1, 56))

    def test_rank_config_and_kaifu_rows(self):
        cfg = self.cfg.zuoqi_rank_config(1)
        self.assertEqual(cfg['rank'], 1)
        self.assertTrue(cfg['name'])
        self.assertGreaterEqual(cfg['need_level'], 0)
        self.assertIsNone(self.cfg.zuoqi_rank_config(999))
        self.assertEqual(self.cfg.zuoqi_max_rank(), 10)
        kai = self.cfg.kaifu_zuoqi_config(1)
        self.assertEqual(kai['last_days'], 3)
        self.assertIsNone(self.cfg.kaifu_zuoqi_config(9))
        self.assertEqual(self.cfg.kaifu_zuoqi_fanhuan()['rank'], 4)
        mei = self.cfg.kaifu_zuoqi_meiren()
        self.assertEqual((mei['rank'], mei['meiren']), (3, 'baijingjing'))


if __name__ == '__main__':
    unittest.main()

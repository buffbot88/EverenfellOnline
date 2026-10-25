"""Xianjiehuoyuedu activity: daily counters, rewards, instant-complete.

Evidence: `XianjiehuoyueduServiceImpl` (`changeHuoYuedu`/`huoyuedu`,
`clear`, `getDayHuoYuedu`, `miaoSha`, `jiangLi`), `MeiRiHuoYueConfig`
(dandusuan -> `jisuan`, `value = huoyuezhi / jindu`), the shipped
`meirihuoyue.jat` / `huoyuejiangli.jat` rows and
`ChengHaoHuoYueDu*` producer handlers. The suite drives the real tables
through SQLite and the real command handlers, including the Java quirks
(int-division value 0 rows, finished types still counting, miaoSha
re-buying a finished row).
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode, encode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session, frame  # noqa: E402
from game import xianjie as xianjie_lib  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2]
               / 'reference' / 'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config' / 'meirihuoyue.jat').is_file()
INITKEY = bytes.fromhex('00000009060f494e49544b4559')


def decoded(out):
    if out is None:
        return []
    if isinstance(out, (bytes, bytearray)):
        return [decode(bytes(out)[4:])]
    return [decode(bytes(f)[4:]) for f in out]


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class XianjieHuoyueTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.store = Store(os.path.join(tmp, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = str(self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=25, exp=0,
            tongqian=1000000, zhenqi=100000, lingshi=1000000))
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=30)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = self.make_sess()

    def make_sess(self, **over):
        kw = dict(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            save_role_state=self.store.update_character_state,
            get_role_vip=self.store.get_role_vip,
            save_role_vip=self.store.save_role_vip,
            get_role_xianjiechenhao=self.store.get_role_xianjiechenhao,
            save_role_xianjiechenhao=self.store.save_role_xianjiechenhao,
            get_role_xianjiehuoyuedu=self.store.get_role_xianjiehuoyuedu,
            save_role_xianjiehuoyuedu=self.store.save_role_xianjiehuoyuedu,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            get_role_bag_slot=self.store.get_role_bag_slot,
            get_role_bag_slot_by_bag_id=self.store.get_role_bag_slot_by_bag_id,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            config=self.cfg)
        kw.update(over)
        sess = Session(**kw)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return sess

    def role(self):
        return self.store.list_roles('hero', 'fu1304')[0]

    def wire(self, cmd, data):
        s = self.sess
        if s.cipher is None:
            s.feed(INITKEY)
        return decoded(s.feed(frame(s.cipher.encode(encode([cmd, data])))))

    def row(self):
        return self.store.get_role_xianjiehuoyuedu(self.role_id) or {}

    def push(self):
        out = decoded(self.sess._xianjie_pushes)
        del self.sess._xianjie_pushes[:]
        return out

    # -- config ----------------------------------------------------------
    def test_config_value_is_int_division(self):
        table = self.cfg.meirihuoyue_table()
        self.assertEqual(len(table), 18)
        self.assertEqual(table['1']['type'], 'VIP')
        self.assertEqual(table['1']['value'], 5)      # 50 / 10
        self.assertEqual(table['4']['value'], 2)      # 20 / 10
        self.assertEqual(table['11']['value'], 0)     # 10 / 50000000
        self.assertEqual(table['10']['value'], 0)     # 10 / 50000
        self.assertFalse(table['6']['jisuan'])
        self.assertTrue(table['7']['miaosha'])
        rewards = self.cfg.huoyuejiangli_table()
        self.assertEqual(rewards['1']['huoyue'], 50)
        self.assertEqual(rewards['1']['items'],
                         [{'goods_id': 'expfold_002', 'count': 1, 'bind': 1}])

    # -- 90000 -----------------------------------------------------------
    def test_panel_creates_row_and_accounts_vip_zero(self):
        got = self.wire(90000, None)
        self.assertEqual(got, [['90000', [0, [['1', 0]], []]]])
        self.assertEqual(self.row()['huoyuedu'], 0)

    def test_panel_without_role_is_silent(self):
        sess = self.make_sess(get_roles=lambda u, s: [])
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        self.assertIsNone(sess.xianjie_huoyue_info([90000, None]))

    def test_vip_login_pays_per_level_once(self):
        self.store.save_role_vip(self.role_id, vip_level=3)
        got = self.wire(90000, None)
        self.assertEqual(got[0][1][0], 15)       # 3 levels * 5
        self.assertEqual(got[0][1][1], [['1', 3]])
        # A second panel read the same day pays nothing more.
        got = self.wire(90000, None)
        self.assertEqual(got[0][1][0], 15)
        self.assertEqual(self.row()['huoyuedu'], 15)

    # -- accumulation ----------------------------------------------------
    def test_non_calculated_type_pays_once_on_completion(self):
        for _ in range(19):
            self.sess._huoyue_record(self.role_id, 6, 1)
        self.assertEqual(self.push(), [])
        self.assertEqual(self.row()['huoyuedu'], 0)
        self.sess._huoyue_record(self.role_id, 6, 1)
        # Java pushes the finishing call's own data cell, not the counter.
        self.assertEqual(self.push(), [['91000', ['6', '1', 10]]])
        self.assertEqual(self.row()['huoyuedu'], 10)
        # Further taps keep counting but pay nothing and push nothing.
        self.sess._huoyue_record(self.role_id, 6, 1)
        self.assertEqual(self.push(), [])
        self.assertEqual(self.row()['huoyuedu'], 10)
        self.assertEqual(xianjie_lib.counter(self.row(), 6), 20)

    def test_per_unit_type_pays_every_step(self):
        self.sess._huoyue_record(self.role_id, 4, 3)
        self.assertEqual(self.row()['huoyuedu'], 6)
        self.assertEqual(self.push(), [])
        self.sess._huoyue_record(self.role_id, 4, 7)
        self.assertEqual(self.row()['huoyuedu'], 20)
        self.assertEqual(self.push(), [['91000', ['4', '7', 20]]])
        self.assertEqual(xianjie_lib.counter(self.row(), 4), 10)

    def test_zero_value_type_earns_nothing(self):
        self.sess._huoyue_record(self.role_id, 11, 40000000)
        self.assertEqual(self.row()['huoyuedu'], 0)
        self.assertEqual(xianjie_lib.counter(self.row(), 11), 40000000)

    def test_vip_state_cell_replaces_and_finishes_at_ten(self):
        self.sess._huoyue_record(self.role_id, 1, 4, add=False)
        self.assertEqual(self.row()['huoyuedu'], 20)
        self.assertEqual(self.push(), [])
        self.sess._huoyue_record(self.role_id, 1, 10, add=False)
        self.assertEqual(self.row()['huoyuedu'], 50)
        self.assertEqual(self.push(), [['91000', ['1', '10', 50]]])

    def test_daily_reset_keeps_lifetime_total(self):
        self.sess._huoyue_record(self.role_id, 6, 20)
        self.assertEqual(self.row()['huoyuedu'], 10)
        row = self.row()
        old = int(row['meiri_jiangli_time']) - 2 * 86400000
        self.store.save_role_xianjiehuoyuedu(
            self.role_id, meiri_jiangli_time=old,
            meiri_jiangli='["1"]', huoyuedu=10)
        fresh = self.sess._xianjie_row(self.role_id)
        self.assertEqual(fresh['meiri_finish_id'], '[]')
        self.assertEqual(fresh['meiri_jiangli'], '[]')
        self.assertEqual(fresh['huoyuedu_list'], '{}')
        self.assertEqual(fresh['huoyuedu'], 10)

    def test_counter_survives_reconnect(self):
        self.sess._huoyue_record(self.role_id, 6, 7)
        other = self.make_sess()
        self.assertEqual(xianjie_lib.counter(
            other._xianjie_row(self.role_id), 6), 7)

    # -- 90001 -----------------------------------------------------------
    def test_miaosha_finishes_row_for_yb(self):
        before = int(self.role().get('lingshi') or 0)
        got = self.wire(90001, '7')
        self.assertEqual(got, [['90001', [1, '7', 10]]])
        self.assertEqual(xianjie_lib.counter(self.row(), 7), 1000)
        self.assertEqual(self.row()['huoyuedu'], 10)
        self.assertEqual(int(self.role().get('lingshi') or 0), before - 10)

    def test_miaosha_refuses_a_row_at_its_threshold(self):
        self.sess._huoyue_record(self.role_id, 6, 20)
        got = self.wire(90001, '7')
        self.assertEqual(got, [['90001', [1, '7', 20]]])
        # The buy wrote the counter to jindu, so a second buy hits the
        # below-threshold gate (the finish list is never consulted).
        got = self.wire(90001, '7')
        self.assertEqual(got, [['90001', [0, 90001]]])

    def test_miaosha_without_option(self):
        got = self.wire(90001, '6')
        self.assertEqual(got, [['90001', [0, 90002]]])

    def test_miaosha_short_yb_spends_nothing(self):
        self.store.update_character_state(self.role_id, lingshi=0)
        got = self.wire(90001, '7')
        self.assertEqual(got, [['90001', [0, 1002]]])
        self.assertEqual(self.row().get('huoyuedu_list', '{}'), '{}')

    # -- 91001 -----------------------------------------------------------
    def _finish_vip(self):
        self.store.save_role_xianjiehuoyuedu(
            self.role_id, huoyuedu=50, huoyuedu_list='{"1": 10}',
            meiri_finish_id='["1"]', meiri_jiangli='[]',
            meiri_jiangli_time=self._today())
        return self._today()

    @staticmethod
    def _today():
        import time
        return int(time.time() * 1000)

    def test_claim_grants_and_marks(self):
        self._finish_vip()
        got = self.wire(91001, '1')
        self.assertEqual(got, [['91001', [1, '1']]])
        self.assertIn('"1"', self.row()['meiri_jiangli'])
        slots = self.store.get_role_bag_slots(self.role_id)
        self.assertEqual([s['goods_id'] for s in slots], ['expfold_002'])

    def test_claim_twice_is_denied(self):
        self._finish_vip()
        self.wire(91001, '1')
        got = self.wire(91001, '1')
        self.assertEqual(got, [['91001', [0, 90003]]])

    def test_claim_short_activity_is_denied(self):
        self.store.save_role_xianjiehuoyuedu(
            self.role_id, huoyuedu=0, meiri_jiangli='[]',
            meiri_jiangli_time=self._today())
        got = self.wire(91001, '1')
        self.assertEqual(got, [['91001', [0, 90004]]])

    def test_null_claim_cell_reads_as_claimed(self):
        self.store.save_role_xianjiehuoyuedu(
            self.role_id, huoyuedu=999, meiri_jiangli=None,
            meiri_jiangli_time=self._today())
        got = self.wire(91001, '1')
        self.assertEqual(got, [['91001', [0, 90003]]])

    # -- 91002 / ranks ---------------------------------------------------
    def _activity(self, amount):
        self.store.save_role_xianjiehuoyuedu(
            self.role_id, huoyuedu=amount, huoyuedu_list='{}',
            meiri_jiangli_time=self._today())

    def test_data_panel_lists_every_title(self):
        got = self.wire(91002, None)
        body = got[0][1]
        self.assertEqual(body[0], None)
        self.assertEqual(body[1], 0)
        self.assertEqual(body[2], '1')
        self.assertEqual(body[3], [])
        self.assertEqual(len(body[4]), 72)
        self.assertEqual(body[4][0], ['1', 0])

    def test_rank_one_needs_its_activity(self):
        got = self.wire(91003, '1')
        self.assertEqual(got, [['91003', [0, 91003]]])
        self.assertIsNone(self.store.get_role_xianjiechenhao(self.role_id))

    def test_rank_upgrade_appends_switch_and_refreshes(self):
        self._activity(150)
        got = self.wire(91003, '1')
        codes = [f[0] for f in got]
        # Rank 1 has gonggao 0, so no 11101 rides it.
        self.assertEqual(codes, ['91004', '12000', '91003', '12010'])
        self.assertEqual(got[0][1], '1')
        self.assertEqual(got[2][1], [1, '1'])
        self.assertEqual(got[3][1][11], self.cfg.xianjie_fight('1'))
        self.assertIn('"1"', self.store.get_role_xianjiechenhao(
            self.role_id)['xianjie_id'])

    def test_rank_five_broadcasts_the_upgrade(self):
        self._activity(11250)
        for rank in ('1', '2', '3', '4'):
            self.wire(91003, rank)
        got = self.wire(91003, '5')
        self.assertEqual(got[0][0], '11101')
        self.assertEqual(got[0][1][0], 91010)
        self.assertEqual(got[0][1][1][0], 'Wukong')
        self.assertEqual(got[0][1][1][1],
                         self.cfg.xianjie_table()['5']['mingcheng'])

    def test_rank_one_twice_is_denied(self):
        self._activity(150)
        self.wire(91003, '1')
        got = self.wire(91003, '1')
        self.assertEqual(got, [['91003', [0, 91002]]])

    def test_rank_two_needs_rank_one(self):
        self._activity(5000)
        got = self.wire(91003, '2')
        self.assertEqual(got, [['91003', [0, 91001]]])

    def test_rank_chain_works_with_enough_activity(self):
        self._activity(5000)
        self.wire(91003, '1')
        got = self.wire(91003, '2')
        reply = [f for f in got if f[0] == '91003']
        self.assertEqual(reply, [['91003', [1, '2']]])
        body = self.wire(91002, None)[0][1]
        self.assertEqual(body[2], '2')
        self.assertEqual(body[1], 5000)

    def test_switch_rank_stores_selection(self):
        self._activity(150)
        self.wire(91003, '1')
        got = self.wire(91004, '1')
        self.assertEqual(got, [['91004', [1, '1']]])
        self.assertEqual(self.store.get_role_xianjiechenhao(
            self.role_id)['xianjie_qiyong'], '1')
        self.assertEqual(self.wire(91002, None)[0][1][0], '1')

    def test_switch_to_unowned_rank_is_silent(self):
        self.assertIsNone(self.sess.xianjie_switch([91004, '3']))

    def test_rank_bag_feeds_12000(self):
        before = self.wire(12000, None)[0][1]
        self._activity(150)
        self.wire(91003, '1')
        after = self.wire(12000, None)[0][1]
        moved = [key for key in after
                 if int(after[key]) != int(before.get(key, 0))]
        self.assertTrue(moved)


if __name__ == '__main__':
    unittest.main()

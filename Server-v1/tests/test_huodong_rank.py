"""70508/70580 rank displays (HuodongAction getZuoqiRank/getQibingRank).

Evidence: docs/huodong-ledger.md batch 12 (getQibingRank(Message)
carries an Integer typeId through convert; getZuoqiRank carries no
data; invalid category/type reads [0, 792005], inactive reads [2],
success reads [1, typeId, startMs, endMs, pic, rows] with the
12-slot rows [actId, con, items, maxVal, maxLimit, dayVal,
dayLimit, state, order, desc, name, huodongicon]; the metric is
getSingleHuodongConditionVal per family). fu0 supplies every case:
the kaifu-relative ct-10 rows live at PROD_KAIFU+1h, the explicit
ct-22/ct-30/ct-31 windows cover their claim-tested instants, and
the ct-32 rows live two days after VIP_KAIFU.
"""
import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode, encode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..',
                           'reference', 'TonNgoKhong', 'server', 'config',
                           'game')
HAVE_REAL = os.path.isdir(REAL_CONFIG)
SNAPSHOT = os.path.normpath(os.path.join(
    os.path.dirname(__file__), '..', '..', 'MKO_Client', 'Assets',
    'gameconfig', 'upload', 'gameanalyze', 'compositiveactivity', 'fu0'))
HAVE_SNAPSHOT = os.path.isfile(SNAPSHOT)

PROD_KAIFU = 1394466091000
EX_NOW = PROD_KAIFU + 3600000
BS_NOW = 1393344001000 + 3600000
QB_NOW = 1393344001000 + 3600000
GY_NOW = 1393430401000 + 3600000
VIP_KAIFU = 1394000000000
VIP_NOW = VIP_KAIFU + 2 * 86400000 + 3600000
FAR_FUTURE = 1400000000000


@unittest.skipUnless(HAVE_REAL and HAVE_SNAPSHOT,
                     'legacy config tree or zonghe snapshot missing')
class HuodongRankTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'r.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.rid = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56)
        self.store.save_role_bag_state(self.rid, bag_capacity=144,
                                       storage_capacity=144)
        self.sess = self.make_sess(PROD_KAIFU)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'

    def make_sess(self, kaifu_ms, config=None):
        return Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=kaifu_ms,
            get_role_zuoqi=self.store.get_role_zuoqi,
            save_role_zuoqi=self.store.save_role_zuoqi,
            get_role_qibing=self.store.get_role_qibing,
            save_role_qibing=self.store.save_role_qibing,
            get_role_baoshi=self.store.get_role_baoshi,
            save_role_baoshi=self.store.save_role_baoshi,
            get_role_guangyi=self.store.get_role_guangyi,
            save_role_guangyi=self.store.save_role_guangyi,
            get_role_vip=self.store.get_role_vip,
            save_role_vip=self.store.save_role_vip,
            save_role_state=self.store.update_character_state,
            get_role_huodong=self.store.get_role_huodong,
            save_role_huodong=self.store.save_role_huodong,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            get_huodong_info=self.store.get_huodong_info,
            huodong_exchange_tx=self.store.huodong_exchange_tx,
            huodong_mall_buy_tx=self.store.huodong_mall_buy_tx,
            config=config if config is not None else self.cfg)

    # -- helpers ---------------------------------------------------------
    def rank(self, cmd, data, now_ms):
        out = {70508: self.sess.huodong_zuoqi_rank,
               70580: self.sess.huodong_qibing_rank}[cmd](
                   [cmd, data], now_ms=now_ms)
        return decode(bytes(out)[4:]) if out is not None else None

    # -- 70508 mount display (ct-10, no data) ---------------------------
    def test_zuoqi_exact_golden(self):
        body = self.rank(70508, None, EX_NOW)
        self.assertEqual(body[0], '70508')
        self.assertEqual(body[1][:5],
                         [1, 10, PROD_KAIFU, PROD_KAIFU + 86400000, ''])
        rows = body[1][5]
        self.assertEqual(
            [[r[0], r[1], r[4], r[5], r[6], r[7], r[8]] for r in rows],
            [['201400001-zxzuoqi105-2', 5, 1, 0, 1, 0, 1],
             ['201400001-zxzuoqi106-2', 6, 1, 0, 1, 0, 2],
             ['201400001-zxzuoqi107-2', 7, 1, 0, 1, 0, 3],
             ['201400001-zxzuoqi108-2', 8, 1, 0, 1, 0, 4]])
        # Full first row: the 12-slot getZuoqiRank shape with the
        # 10-slot itemParamVo2Client item and the genuine tail.
        self.assertEqual(
            rows[0],
            ['201400001-zxzuoqi105-2', 5,
             [['jinjiedan001', 300, 1, 0.0, [0, 0], 0, None, None,
               0, None]],
             0, 1, 0, 1, 0, 1, '将坐骑进阶至独角兕（五阶）',
             '新服特惠', 'z5.png'])
        self.assertEqual([r[11] for r in rows],
                         ['z5.png', 'z6.png', 'z7.png', 'z8.png'])

    def test_zuoqi_metric_transitions(self):
        self.store.save_role_zuoqi(self.rid, zuoqi_rank=5,
                                   zuoqi_cur_rank=5)
        rows = self.rank(70508, None, EX_NOW)[1][5]
        self.assertEqual([r[7] for r in rows], [1, 0, 0, 0])
        self.store.save_role_zuoqi(self.rid, zuoqi_rank=8,
                                   zuoqi_cur_rank=8)
        rows = self.rank(70508, None, EX_NOW)[1][5]
        self.assertEqual([r[7] for r in rows], [1, 1, 1, 1])

    def test_zuoqi_claimed_row_reads_completed(self):
        self.store.save_role_zuoqi(self.rid, zuoqi_rank=5,
                                   zuoqi_cur_rank=5)
        claimed = self.sess.huodong_exchange_claim(
            [70551, [10, '201400001-zxzuoqi105-2']], now_ms=EX_NOW)
        self.assertEqual(decode(bytes(claimed)[4:])[1][0], 1)
        rows = self.rank(70508, None, EX_NOW)[1][5]
        # Claimed once: the completion record plus the 1/1 floors
        # force state 2 while the unclaimed tiers stay open.
        self.assertEqual([r[7] for r in rows], [2, 0, 0, 0])
        self.assertEqual([rows[0][3], rows[0][5]], [1, 1])

    # -- 70580 family displays ------------------------------------------
    def test_baoshi_exact_golden_and_metric(self):
        body = self.rank(70580, [22], BS_NOW)
        self.assertEqual(body[0], '70580')
        self.assertEqual(body[1][:5],
                         [1, 22, 1393344001000, 1393430399000,
                          'huodong_bg11.png'])
        rows = body[1][5]
        self.assertEqual(
            [[r[0], r[1], r[7], r[8]] for r in rows],
            [['20140226-1bsa001-3', 30, 0, 1],
             ['20140226-1bsa002-3', 60, 0, 2],
             ['20140226-1bsa003-3', 90, 0, 3],
             ['20140226-1bsa004-3', 120, 0, 4],
             ['20140226-1bsa005-3', 150, 0, 5]])
        self.assertEqual(
            rows[0][:3],
            ['20140226-1bsa001-3', 30,
             [['bscl', 200, 1, 0.0, [0, 0], 0, None, None, 0, None],
              ['baoshilixiang1', 1, 1, 0.0, [0, 0], 0, None, None,
               0, None]]])
        self.assertEqual(rows[0][9:], ['将全身宝石升至30品', '宝石特惠',
                                       'bs1.png'])
        self.store.save_role_baoshi(self.rid, [
            {'id': 'g1', 'part': 1, 'grid': 1, 'level': 10},
            {'id': 'g2', 'part': 2, 'grid': 1, 'level': 10},
            {'id': 'g3', 'part': 3, 'grid': 1, 'level': 10}])
        rows = self.rank(70580, [22], BS_NOW)[1][5]
        self.assertEqual([r[7] for r in rows], [1, 0, 0, 0, 0])

    def test_qibing_default_zero_and_real_row_metric(self):
        body = self.rank(70580, [30], QB_NOW)
        self.assertEqual(body[0], '70580')
        self.assertEqual(body[1][:5],
                         [1, 30, 1393344001000, 1393430399000,
                          'huodong_bg11.png'])
        rows = body[1][5]
        self.assertEqual(len(rows), 6)
        self.assertEqual([r[7] for r in rows], [0] * 6)
        self.assertEqual([rows[0][0], rows[0][1], rows[0][11]],
                         ['20140226-6qc002-3', 2, 'q2.png'])
        # The metric is the persisted progression row (getQizhanBinLevel).
        self.store.save_role_qibing(self.rid, binqi_level=3,
                                    fail_count=0, lucky_value=0,
                                    upgrade_time=0, lingqu_time=0,
                                    update_time=0)
        out = self.sess.huodong_qibing_rank([70580, [30]],
                                             now_ms=QB_NOW)
        states = decode(bytes(out)[4:])[1][5]
        self.assertEqual([r[7] for r in states], [1, 1, 0, 0, 0, 0])

    def test_chibang_metric(self):
        body = self.rank(70580, [31], GY_NOW)
        self.assertEqual(body[1][:5],
                         [1, 31, 1393430401000, 1393516799000,
                          'huodong_bg11.png'])
        rows = body[1][5]
        self.assertEqual(len(rows), 7)
        self.assertEqual([rows[0][0], rows[0][1], rows[0][11]],
                         ['20140227-gygy003-3', 3, 'g3.png'])
        self.store.save_role_guangyi(self.rid, level=3)
        rows = self.rank(70580, [31], GY_NOW)[1][5]
        self.assertEqual([r[7] for r in rows],
                         [1, 0, 0, 0, 0, 0, 0])

    def test_vip_metric(self):
        sess = self.make_sess(VIP_KAIFU)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        out = sess.huodong_qibing_rank([70580, [32]], now_ms=VIP_NOW)
        body = decode(bytes(out)[4:])
        self.assertEqual(body[1][:5],
                         [1, 32, 1394172800000, 1394432000000, ''])
        rows = body[1][5]
        self.assertEqual(len(rows), 5)
        self.assertEqual([rows[0][0], rows[0][1], rows[0][11]],
                         ['201400003-zxvip104-5', 4, 'vip4.png'])
        self.assertEqual([r[7] for r in rows], [0] * 5)
        self.store.save_role_vip(self.rid, vip_level=4)
        out = sess.huodong_qibing_rank([70580, [32]], now_ms=VIP_NOW)
        rows = decode(bytes(out)[4:])[1][5]
        self.assertEqual([r[7] for r in rows], [1, 0, 0, 0, 0])

    # -- edges: invalid, inactive, missing, gated -----------------------
    def test_invalid_type_is_792005(self):
        self.assertEqual(self.rank(70580, [99], BS_NOW),
                         ['70580', [0, 792005]])
        self.assertEqual(self.rank(70580, None, BS_NOW),
                         ['70580', [0, 792005]])
        self.assertEqual(self.rank(70580, ['nope'], BS_NOW),
                         ['70580', [0, 792005]])

    def test_inactive_category_is_bare_two(self):
        self.assertEqual(self.rank(70508, None, FAR_FUTURE),
                         ['70508', [2]])
        self.assertEqual(self.rank(70580, [22], FAR_FUTURE),
                         ['70580', [2]])

    def test_missing_config_is_792005(self):
        cfg, self.sess.config = self.sess.config, None
        try:
            role = dict(self.store.list_roles('hero', 'fu1304')[0])
            self.assertEqual(self.sess._zonghe_rank(role, 10, EX_NOW),
                             [0, 792005])
            self.assertEqual(self.sess._zonghe_rank(role, 22, BS_NOW),
                             [0, 792005])
        finally:
            self.sess.config = cfg

    def test_level_zero_role_sees_no_rows(self):
        role = dict(self.store.list_roles('hero', 'fu1304')[0])
        body = self.sess._zonghe_rank(dict(role, level=0), 10,
                                      now_ms=EX_NOW)
        self.assertEqual(body[:5],
                         [1, 10, PROD_KAIFU, PROD_KAIFU + 86400000,
                          ''])
        self.assertEqual(body[5], [])

    # -- encrypted-wire dispatch ----------------------------------------
    def test_wire_routes_both_commands(self):
        # Wall-clock 2026: no 2014 row is live, so both commands get
        # the jar-verbatim empty reply through the real cipher path.
        # One handshake: re-feeding INITKEY mid-session re-keys the
        # cipher, so the payloads ride a single established session.
        self.sess.feed(bytes.fromhex('00000009060f494e49544b4559'))
        for cmd, data, want in ((70508, None, ['70508', [2]]),
                                (70580, [22], ['70580', [2]]),
                                (70580, [99],
                                 ['70580', [0, 792005]]),
                                (70580, None,
                                 ['70580', [0, 792005]])):
            req = self.sess.cipher.encode(encode([cmd, data]))
            out = self.sess.feed(struct.pack('>I', len(req)) + req)
            self.assertEqual([decode(bytes(f)[4:]) for f in out],
                             [want])


if __name__ == '__main__':
    unittest.main()

"""70520 threshold pushes (zonghe services' send2One fan-in).

Evidence: docs/huodong-ledger.md batches 11-13 (decrYb, zuoqiJinjie,
qibingJinjie, baoshiLevelUp, getProp and vipLevel each queue
70520 [actId, 1] when their metric crosses the claimable
threshold; the port had the metric readers but emitted nothing).
Each synthetic family below is live on the wall clock so the
feed tests exercise the real cipher path; only the family under
test is live in each case, so a push pins its producer exactly.
"""
import json
import os
import struct
import sys
import tempfile
import time
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


class _SynthTable:
    """Wrap a GameConfig appending one wall-clock-live category."""

    def __init__(self, real, clienttype, cat):
        self._real = real
        self._ct = clienttype
        self._cat = cat

    def __getattr__(self, name):
        return getattr(self._real, name)

    def zonghe(self, server_id='fu0', kaifu_ms=0):
        import copy
        table = copy.deepcopy(self._real.zonghe(
            server_id=server_id, kaifu_ms=kaifu_ms))
        bucket = table.setdefault(self._ct, {'categories': [],
                                             'by_activity': {}})
        bucket['categories'].append(copy.deepcopy(self._cat))
        return table


@unittest.skipUnless(HAVE_REAL and HAVE_SNAPSHOT,
                     'legacy config tree or zonghe snapshot missing')
class HuodongNotifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'n.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.rid = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56)
        self.store.update_character_state(
            self.rid, lingshi=100000, zhenqi=5000)

    def make_sess(self, config=None, **extra):
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
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
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            get_huodong_info=self.store.get_huodong_info,
            huodong_exchange_tx=self.store.huodong_exchange_tx,
            huodong_mall_buy_tx=self.store.huodong_mall_buy_tx,
            yb_consume_tx=self.store.yb_consume_tx,
            charge_total_in_time=self.store.recharge_charge_total_in_time,
            charge_total=self.store.recharge_charge_total,
            save_recharge_yb=self.store.save_recharge_yb,
            recharge_check_order_repeat=
            self.store.recharge_check_order_repeat,
            recharge_grant_save_tx=self.store.recharge_grant_save_tx,
            recharge_finish_tx=self.store.recharge_finish_tx,
            config=config if config is not None else self.cfg,
            **extra)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        sess.feed(bytes.fromhex('00000009060f494e49544b4559'))
        return sess

    # -- helpers ---------------------------------------------------------
    def synth(self, ctype, act_id, con, functiontype, day=5,
              maximum=5):
        now = int(time.time() * 1000)
        return _SynthTable(self.cfg, ctype, {
            'id': 'synth-%d-1' % ctype, 'start_ms': now - 3600000,
            'end_ms': now + 3600000, 'pic': '',
            'activities': [{
                'id': act_id, 'order': 1, 'need_level': 1,
                'need_pay_yb': 0, 'day_count': day,
                'max_count': maximum, 'con1': str(con),
                'functiontype': functiontype,
                'currencies': {}, 'item_views': [],
                'choose_awards': {}},
            ]})

    def feed(self, sess, cmd, data):
        req = sess.cipher.encode(encode([cmd, data]))
        out = sess.feed(struct.pack('>I', len(req)) + req)
        return [decode(bytes(f)[4:]) for f in out]

    def pushes(self, frames):
        return [f for f in frames if f[0] == '70520']

    def role(self):
        return dict(self.store.list_roles('hero', 'fu1304')[0])

    # -- yuanbao consumption (decrYb, ct-3) -------------------------------
    def test_consume_crossing_emits_once(self):
        sess = self.make_sess(
            config=self.synth(3, 'c-cross', 10, 92))
        # Pity-ready rank-1 mount; the autobuy debit (30 YB, pinned
        # by the zuoqi suite) carries paid 0 -> 30 over con 10.
        self.store.save_role_zuoqi(self.rid, 1, 1, 0, 0, 1, 0, 0,
                                   None, 0, 0)
        self.store.update_character_state(self.rid, lingshi=1000)
        got = self.feed(sess, 33003, 1)
        self.assertEqual(self.pushes(got), [['70520', ['c-cross', 1]]])
        roles = self.store.list_roles('hero', 'fu1304')
        self.assertEqual(roles[0]['lingshi'], 1000 - 30)
        # A further spend moves paid 30 -> 60 but the threshold was
        # already crossed, so nothing re-fires.
        again = self.feed(sess, 33003, 1)
        self.assertEqual(self.pushes(again), [])

    def test_consume_short_of_threshold_is_silent(self):
        sess = self.make_sess(
            config=self.synth(3, 'c-far', 99999, 92))
        self.store.save_role_zuoqi(self.rid, 1, 1, 0, 0, 1, 0, 0,
                                   None, 0, 0)
        self.store.update_character_state(self.rid, lingshi=1000)
        got = self.feed(sess, 33003, 1)
        self.assertEqual(self.pushes(got), [])

    def test_consume_completed_state_is_silent(self):
        sess = self.make_sess(
            config=self.synth(3, 'c-done', 10, 92))
        self.store.save_role_huodong(
            self.rid, day_count=json.dumps({'c-done': 5}),
            max_count=json.dumps({'c-done': 5}))
        self.store.save_role_zuoqi(self.rid, 1, 1, 0, 0, 1, 0, 0,
                                   None, 0, 0)
        self.store.update_character_state(self.rid, lingshi=1000)
        got = self.feed(sess, 33003, 1)
        # Paid still crosses con 10, but the 5/5 floors mark the
        # activity done, so the jar sends no refresh.
        self.assertEqual(self.pushes(got), [])

    # -- mount progression (zuoqiJinjie, ct-10) ---------------------------
    def test_mount_claim_crossing_via_feed(self):
        now = int(time.time() * 1000)
        cat = {'id': 'synth-10-1', 'start_ms': now - 3600000,
               'end_ms': now + 3600000, 'pic': '',
               'activities': [
                   {'id': 'm-near', 'order': 1, 'need_level': 1,
                    'need_pay_yb': 0, 'day_count': 5, 'max_count': 5,
                    'con1': '1', 'functiontype': 50, 'currencies': {},
                    'item_views': [], 'choose_awards': {}},
                   {'id': 'm-far', 'order': 2, 'need_level': 1,
                    'need_pay_yb': 0, 'day_count': 5, 'max_count': 5,
                    'con1': '5', 'functiontype': 50, 'currencies': {},
                    'item_views': [], 'choose_awards': {}},
               ]}
        sess = self.make_sess(config=_SynthTable(self.cfg, 10, cat))
        got = self.feed(sess, 33004, None)
        self.assertEqual(got[-1], ['70520', ['m-near', 1]])
        self.assertEqual(self.pushes(got), [['70520', ['m-near', 1]]])
        # A repeated check finds nothing new: the claim gate is
        # silent and the rank did not move.
        self.assertEqual(self.feed(sess, 33004, None), [])

    def test_mount_jinjie_crossing_via_feed(self):
        sess = self.make_sess(
            config=self.synth(10, 'm-jin', 2, 50))
        self.store.save_role_zuoqi(self.rid, 1, 1, 0, 0, 1, 0, 0,
                                   None, 0, 0)
        self.store.insert_role_bag_slot(
            self.rid, {'slot_num': 10, 'goods_id': 'jinjiedan001',
                       'count': 1, 'bind': 0})
        got = self.feed(sess, 33003, 0)
        self.assertEqual(
            self.store.get_role_zuoqi(self.rid)['zuoqi_rank'], 2)
        self.assertEqual(self.pushes(got), [['70520', ['m-jin', 1]]])

    def test_mount_completed_state_is_silent(self):
        sess = self.make_sess(
            config=self.synth(10, 'm-done', 1, 50))
        self.store.save_role_huodong(
            self.rid, day_count=json.dumps({'m-done': 5}),
            max_count=json.dumps({'m-done': 5}))
        got = self.feed(sess, 33004, None)
        # Rank still rises 0 -> 1 over con 1, but the maxed
        # counters mark the activity done.
        self.assertEqual(self.pushes(got), [])

    # -- gem progression (baoshiLevelUp, ct-22) ---------------------------
    def test_gem_jihuo_crossing_via_feed(self):
        sess = self.make_sess(
            config=self.synth(22, 'g-near', 1, 51))
        self.store.insert_role_bag_slot(
            self.rid, {'slot_num': 10, 'goods_id': 'bscl',
                       'count': 3, 'bind': 0})
        got = self.feed(sess, 37001, [70, 1])
        self.assertEqual(got[0], ['37001', [1, 70, 1]])
        self.assertEqual(self.pushes(got), [['70520', ['g-near', 1]]])
        # The retry answers already-owned with no sum change, so no
        # second push fires.
        again = self.feed(sess, 37001, [70, 1])
        self.assertEqual(again, [['37001', [0, 530001]]])

    def test_gem_completed_state_is_silent(self):
        sess = self.make_sess(
            config=self.synth(22, 'g-done', 1, 51))
        self.store.save_role_huodong(
            self.rid, day_count=json.dumps({'g-done': 5}),
            max_count=json.dumps({'g-done': 5}))
        self.store.insert_role_bag_slot(
            self.rid, {'slot_num': 10, 'goods_id': 'bscl',
                       'count': 3, 'bind': 0})
        got = self.feed(sess, 37001, [70, 1])
        self.assertEqual(got[0], ['37001', [1, 70, 1]])
        self.assertEqual(self.pushes(got), [])

    # -- VIP progression (vipLevel, ct-32) --------------------------------
    def test_vip_crossing_via_recharge_producer(self):
        # Recharge enters through the web producer, not the game
        # socket, so no feed command can raise VIP: the genuine
        # trigger is recharge_commit's grant fan-out, which carries
        # the 70520 on its synchronous return path.
        sess = self.make_sess(
            config=self.synth(32, 'v-near', 1, 20))
        levels = {lv: self.cfg.vip_need_gold(lv)
                  for lv in self.cfg.vip_table()}
        lv1 = min((n, lv) for lv, n in levels.items() if n > 0)[1]
        need = self.cfg.vip_need_gold(lv1)
        code, frames = sess.recharge_commit(
            'fu1304', 'hero', self.rid, 'vip-n1', float(need), need,
            False, 'web', '1')
        self.assertEqual(code, '1')
        got = [decode(bytes(f)[4:]) for f in frames]
        self.assertIn(['70520', ['v-near', 1]], got)
        # The level holds on the next grant: no new crossing, no
        # second push.
        code, frames = sess.recharge_commit(
            'fu1304', 'hero', self.rid, 'vip-n2', 1.0, 1,
            False, 'web', '1')
        self.assertEqual(code, '1')
        got = [decode(bytes(f)[4:]) for f in frames]
        self.assertNotIn(['70520', ['v-near', 1]], got)

    # -- qibing progression (qibingJinjie, ct-30) --------------------------
    def test_qibing_crossing_via_upgrade_producer(self):
        # Pity-ready rank: fail_count past the band ceiling forces
        # the 1 -> 2 crossing over con 2, queuing 70520 once.
        sess = self.make_sess(
            config=self.synth(30, 'q-near', 2, 80))
        self.store.save_role_vip(self.rid, vip_level=1)
        self.feed(sess, 87002, None)
        self.store.insert_role_bag_slot(
            self.rid, {'slot_num': 10, 'goods_id': 'qibing001',
                       'count': 2, 'bind': 0})
        self.store.save_role_qibing(
            self.rid, fail_count=43, lucky_value=0)
        got = self.feed(sess, 87001, False)
        self.assertEqual(
            self.store.get_role_qibing(self.rid)['binqi_level'], 2)
        self.assertEqual(self.pushes(got), [['70520', ['q-near', 1]]])
        # The level holds at 2 with no fresh pills: nothing re-fires.
        self.store.save_role_qibing(self.rid, fail_count=43)
        again = self.feed(sess, 87001, False)
        self.assertEqual(again, [['87001', [0, 1005, None]]])
        self.assertEqual(self.pushes(again), [])

    # -- edges -------------------------------------------------------------
    def test_no_live_category_is_silent(self):
        sess = self.make_sess()
        role = self.role()
        self.assertEqual(
            sess._zonghe_notify_frames(role, self.rid, 10, 0, 9), [])
        self.assertEqual(
            sess._zonghe_notify_frames(role, self.rid, 99, 0, 9), [])


if __name__ == '__main__':
    unittest.main()

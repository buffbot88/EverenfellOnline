"""Recharge producer + login-finish wiring (RechargeRecordServiceImpl).

End to end through real persisted rows: the online producer entry
grants, credits and fans out; duplicates and bad entries are gated
with the endpoint codes; the offline login path finishes pending
rows with the 12301 gate; and YB debits feed the per-activity
consumption ledger atomically. ct-1/ct-7/ct-3 claims then succeed
off those rows instead of injected totals.
"""
import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session, frame  # noqa: E402

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
ACC_ACT = '201400001-zuixinleiji101-2'


class _SynthTable:
    """Wrap a GameConfig appending one synthetic zonghe category."""

    def __init__(self, real, clienttype, cat):
        self._real = real
        self._ct = clienttype
        self._cat = cat

    def __getattr__(self, name):
        return getattr(self._real, name)

    def zonghe(self, server_id='fu0', kaifu_ms=0):
        table = copy.deepcopy(self._real.zonghe(
            server_id=server_id, kaifu_ms=kaifu_ms))
        table.setdefault(self._ct, {'categories': [], 'by_activity': {}})
        table[self._ct]['categories'].append(copy.deepcopy(self._cat))
        return table


@unittest.skipUnless(HAVE_REAL and HAVE_SNAPSHOT,
                     'legacy config tree not present')
class RechargeWireTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, 'w.db')
        self.store = Store(self.db_path)
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.rid = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56)
        self.store.save_role_bag_state(self.rid, bag_capacity=144,
                                       storage_capacity=144)
        self.sess = self.make_sess()
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'

    def make_sess(self, config=None):
        return Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=PROD_KAIFU,
            get_role_zuoqi=self.store.get_role_zuoqi,
            save_role_zuoqi=self.store.save_role_zuoqi,
            get_role_baoshi=self.store.get_role_baoshi,
            save_role_bag_state=self.store.save_role_bag_state,
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
            get_huodong_info=self.store.get_huodong_info,
            huodong_exchange_tx=self.store.huodong_exchange_tx,
            huodong_mall_buy_tx=self.store.huodong_mall_buy_tx,
            charge_total_in_time=self.store.recharge_charge_total_in_time,
            charge_total=self.store.recharge_charge_total,
            charge_today=self.store.recharge_charge_today,
            save_recharge_yb=self.store.save_recharge_yb,
            recharge_check_order_repeat=
            self.store.recharge_check_order_repeat,
            recharge_grant_save_tx=self.store.recharge_grant_save_tx,
            recharge_finish_tx=self.store.recharge_finish_tx,
            yb_consume_tx=self.store.yb_consume_tx,
            config=config if config is not None else self.cfg)

    # -- helpers ------------------------------------------------------
    def role(self):
        return dict(self.store.list_roles('hero', 'fu1304')[0])

    def cmds(self, frames):
        return [decode(bytes(f)[4:]) for f in frames]

    def claim(self, data, now_ms):
        out = self.sess.huodong_exchange_claim([70551, data],
                                               now_ms=now_ms)
        return decode(bytes(out)[4:]) if out is not None else None

    def commit(self, order, num, rtype='1', online=True, **kw):
        args = dict(server_id='fu1304', user_guid='hero',
                    role_id=self.rid, order_id=order, rmb=float(num),
                    money_num=num, is_calc=False, platform_type='web',
                    recharge_type=rtype, online=online)
        args.update(kw)
        return self.sess.recharge_commit(**args)

    def synth(self, ctype, act, con, functiontype, day=1, maximum=1):
        return {
            'id': 'synth-%d-1' % ctype,
            'start_ms': EX_NOW - 1000,
            'end_ms': EX_NOW + 3600000, 'pic': '',
            'activities': [{
                'id': act, 'order': 1, 'need_level': 1,
                'need_pay_yb': 0, 'day_count': day,
                'max_count': maximum, 'con1': con,
                'functiontype': functiontype,
                'currencies': {'jb': 0, 'lijin': 0, 'zhenqi': 0,
                               'shengwang': 0, 'exp': 0},
                'item_views': [{
                    'goods_id': 'kangxing2', 'count': 1, 'bind': 1,
                    'hours': 0.0, 'effect': None, 'unsale': 0,
                    'lost': None}],
                'choose_awards': {},
            }],
        }

    # -- producer entry ----------------------------------------------
    def test_commit_online_grants_credits_and_pushes(self):
        code, frames = self.commit('w1', 500)
        self.assertEqual(code, '1')
        got = dict(self.cmds(frames))
        self.assertEqual(got['12301'], [500.0])
        self.assertIn('32010', got)
        self.assertEqual(self.role()['lingshi'], 500)
        self.assertEqual(self.store.recharge_charge_total(self.rid),
                         500)
        self.assertTrue(
            self.store.recharge_check_order_repeat('w1'))

    def test_commit_duplicate_answers_1004_without_double_credit(self):
        self.assertEqual(self.commit('w2', 500)[0], '1')
        code, frames = self.commit('w2', 500)
        self.assertEqual(code, '1004')
        self.assertEqual(frames, [])
        self.assertEqual(self.role()['lingshi'], 500)
        self.assertEqual(self.store.recharge_charge_total(self.rid),
                         500)

    def test_commit_bad_amount_is_1001_without_side_effects(self):
        code, frames = self.commit('w3', 0)
        self.assertEqual(code, '1001')
        self.assertEqual(frames, [])
        self.assertEqual(self.store.recharge_charge_total(self.rid), 0)

    def test_commit_unknown_role_is_1005(self):
        code, frames = self.sess.recharge_commit(
            'fu1304', 'ghost', 99999, 'w4', 10.0, 100, False,
            'web', '1')
        self.assertEqual(code, '1005')
        self.assertEqual(frames, [])
        self.assertEqual(self.store.recharge_charge_total(99999), 0)

    def test_commit_is_calc_converts_rmb(self):
        code, _frames = self.commit('w5', 0, is_calc=True, rmb=10.0)
        self.assertEqual(code, '1')
        self.assertEqual(self.role()['lingshi'], 100)
        self.assertEqual(self.store.recharge_charge_total(self.rid),
                         100)

    # -- real-row claims -----------------------------------------------
    def test_ct1_claim_succeeds_from_real_rows(self):
        code, _frames = self.commit(
            'ct1', 500, create_ms=PROD_KAIFU + 1800000)
        self.assertEqual(code, '1')
        body = self.claim([1, ACC_ACT, ''], EX_NOW)
        self.assertEqual(
            body,
            ['70551', [1, ACC_ACT, '', 2, 1, 1, 1, 1, None]])

    def test_ct1_repeat_order_stays_single_counted(self):
        self.commit('ct1b', 500, create_ms=PROD_KAIFU + 1800000)
        self.assertEqual(self.commit('ct1b', 500)[0], '1004')
        body = self.claim([1, ACC_ACT, ''], EX_NOW)
        self.assertEqual(body[1][0], 1)
        self.assertEqual(self.store.recharge_charge_total(self.rid),
                         500)

    def test_ct7_claim_succeeds_from_real_rows(self):
        sess = self.make_sess(
            config=_SynthTable(
                self.cfg, 7,
                self.synth(7, 'synth-f-1', '500', 14,
                           day=5, maximum=5)))
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        self.sess = sess
        code, _frames = self.commit('ct7', 1000)
        self.assertEqual(code, '1')
        out = sess.huodong_exchange_claim(
            [70551, [7, 'synth-f-1', '']], now_ms=EX_NOW)
        self.assertEqual(
            decode(bytes(out)[4:]),
            ['70551', [1, 'synth-f-1', 1, 1, 5, 1, 5, None]])

    def test_ct3_claim_succeeds_from_real_consume(self):
        sess = self.make_sess(
            config=_SynthTable(
                self.cfg, 3,
                self.synth(3, 'synth-c-1', '200', 92)))
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        self.sess = sess
        self.store.update_character_state(self.rid, lingshi=100000)
        self.assertTrue(
            sess._bag_money_decr(self.rid, 'YB', 200,
                                 now_ms=EX_NOW))
        row = self.store.get_role_huodong(self.rid) or {}
        self.assertEqual(json.loads(row.get('pay_yb') or '{}'),
                         {'synth-c-1': 200})
        out = sess.huodong_exchange_claim(
            [70551, [3, 'synth-c-1', '']], now_ms=EX_NOW)
        self.assertEqual(
            decode(bytes(out)[4:]),
            ['70551', [1, 'synth-c-1', '', 2, 1, 1, 1, 1, None]])
        self.assertEqual(self.role()['lingshi'], 99800)

    # -- in-tx consume routing (mall + exchange) ------------------------
    MALL_ACT = '201400001-xxsd001-2'
    MALL_GOOD = 'shenmu'

    def buy(self, data, now_ms):
        out = self.sess.huodong_mall_buy([70550, data], now_ms=now_ms)
        if out is None:
            return None
        if isinstance(out, list):
            return [decode(bytes(f)[4:]) for f in out]
        return decode(bytes(out)[4:])

    def synth_mall(self, act, good, npay, gifts, day=5, maximum=9999):
        return {
            'id': 'synth-5-1',
            'start_ms': EX_NOW - 1000,
            'end_ms': EX_NOW + 3600000, 'pic': '',
            'activities': [{
                'id': act, 'order': 1, 'need_level': 1,
                'need_pay_yb': 0, 'day_count': day,
                'max_count': maximum,
                'mall_goods': [{
                    'item_id': good, 'npay_yb': npay,
                    'max_buy': 9999, 'max_sell': 9999,
                    'buy_bind': 0, 'gifts': gifts}],
            }],
        }

    def synth_exchange(self, act, con, parcels, functiontype=9):
        return {
            'id': 'synth-9-1',
            'start_ms': EX_NOW - 1000,
            'end_ms': EX_NOW + 3600000, 'pic': '',
            'activities': [{
                'id': act, 'order': 1, 'need_level': 1,
                'need_pay_yb': 0, 'day_count': 5,
                'max_count': 5, 'con1': con,
                'functiontype': functiontype,
                'currencies': {'jb': 0, 'lijin': 0, 'zhenqi': 0,
                               'shengwang': 0, 'exp': 0},
                'item_views': [{
                    'goods_id': gid, 'count': count, 'bind': bind,
                    'hours': 0.0, 'effect': None, 'unsale': 0,
                    'lost': None}
                    for gid, count, bind in parcels],
                'choose_awards': {},
            }],
        }

    def nested_sess(self, *pairs):
        cfg = self.cfg
        for ctype, cat in pairs:
            cfg = _SynthTable(cfg, ctype, cat)
        sess = self.make_sess(config=cfg)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        self.sess = sess
        return sess

    def pay_yb(self):
        row = self.store.get_role_huodong(self.rid) or {}
        return json.loads(row.get('pay_yb') or '{}')

    def test_ct3_counts_mall_spend(self):
        self.nested_sess(
            (3, self.synth(3, 'synth-c-1', '20', 92)))
        self.store.update_character_state(self.rid, lingshi=100000)
        body = self.buy([5, self.MALL_ACT, self.MALL_GOOD, 1],
                        EX_NOW)
        self.assertEqual(body[0],
                         ['70550', [1, self.MALL_ACT, self.MALL_GOOD,
                                   1, 1, 9999, 1, 9999]])
        self.assertEqual(self.role()['lingshi'], 99980)
        self.assertEqual(self.pay_yb(), {'synth-c-1': 20})
        out = self.sess.huodong_exchange_claim(
            [70551, [3, 'synth-c-1', '']], now_ms=EX_NOW)
        self.assertEqual(
            decode(bytes(out)[4:]),
            ['70551', [1, 'synth-c-1', '', 2, 1, 1, 1, 1, None]])

    def test_mall_exact_purse_counts_consume(self):
        # Boundary: purse == total still buys (the gate is strict <).
        self.nested_sess(
            (3, self.synth(3, 'synth-c-1', '20', 92)))
        self.store.update_character_state(self.rid, lingshi=20)
        body = self.buy([5, self.MALL_ACT, self.MALL_GOOD, 1],
                        EX_NOW)
        self.assertEqual(body[0][1][0], 1)
        self.assertEqual(self.role()['lingshi'], 0)
        self.assertEqual(self.pay_yb(), {'synth-c-1': 20})

    def test_mall_abort_reverts_debit_and_consume(self):
        # Two parcels into one empty slot: fits passes, the tx
        # grant aborts, and the rollback takes the debit and the
        # consume bump back together.
        self.nested_sess(
            (5, self.synth_mall(
                'synth-m-1', 'mg1', 20,
                [{'goods_id': 'kangxing2', 'count': 1,
                  'bind': 1}])),
            (3, self.synth(3, 'synth-c-1', '20', 92)))
        self.store.save_role_bag_state(self.rid, bag_capacity=1,
                                       storage_capacity=144)
        self.store.update_character_state(self.rid, lingshi=1000)
        body = self.buy([5, 'synth-m-1', 'mg1', 1], EX_NOW)
        self.assertEqual(body, ['70550', [0, 792001]])
        self.assertEqual(self.role()['lingshi'], 1000)
        self.assertEqual(self.pay_yb(), {})

    def test_ct3_counts_exchange_yb_cost(self):
        self.nested_sess(
            (9, self.synth_exchange(
                'synth-ex-1', 'yuanbao|50',
                [('kangxing2', 1, 1)])),
            (3, self.synth(3, 'synth-c-1', '50', 92)))
        self.store.update_character_state(self.rid, lingshi=1000)
        out = self.sess.huodong_exchange_claim(
            [70551, [9, 'synth-ex-1', '']], now_ms=EX_NOW)
        self.assertEqual(decode(bytes(out)[4:])[1][0], 1)
        self.assertEqual(self.role()['lingshi'], 950)
        self.assertEqual(self.pay_yb(), {'synth-c-1': 50})
        out = self.sess.huodong_exchange_claim(
            [70551, [3, 'synth-c-1', '']], now_ms=EX_NOW)
        self.assertEqual(
            decode(bytes(out)[4:]),
            ['70551', [1, 'synth-c-1', '', 2, 1, 1, 1, 1, None]])

    def test_exchange_abort_reverts_debit_and_consume(self):
        self.nested_sess(
            (9, self.synth_exchange(
                'synth-ex-1', 'yuanbao|50',
                [('kangxing2', 1, 1), ('duihuan2', 15, 1)])),
            (3, self.synth(3, 'synth-c-1', '50', 92)))
        self.store.save_role_bag_state(self.rid, bag_capacity=1,
                                       storage_capacity=144)
        self.store.update_character_state(self.rid, lingshi=1000)
        out = self.sess.huodong_exchange_claim(
            [70551, [9, 'synth-ex-1', '']], now_ms=EX_NOW)
        self.assertEqual(decode(bytes(out)[4:]),
                         ['70551', [0, 792001]])
        self.assertEqual(self.role()['lingshi'], 1000)
        self.assertEqual(self.pay_yb(), {})

    def test_yxb_cost_excluded_from_consume(self):
        # The carved-out exclusion: a tongqian debit is real spend
        # but never feeds the YB consume ledger.
        self.nested_sess(
            (9, self.synth_exchange(
                'synth-ex-1', 'money|50',
                [('kangxing2', 1, 1)])),
            (3, self.synth(3, 'synth-c-1', '50', 92)))
        self.store.update_character_state(
            self.rid, lingshi=1000, tongqian=1000)
        out = self.sess.huodong_exchange_claim(
            [70551, [9, 'synth-ex-1', '']], now_ms=EX_NOW)
        self.assertEqual(decode(bytes(out)[4:])[1][0], 1)
        self.assertEqual(self.role()['tongqian'], 950)
        self.assertEqual(self.role()['lingshi'], 1000)
        self.assertEqual(self.pay_yb(), {})

    def test_grant_only_claim_writes_no_consume(self):
        self.commit('ct1x', 500, create_ms=PROD_KAIFU + 1800000)
        body = self.claim([1, ACC_ACT, ''], EX_NOW)
        self.assertEqual(body[1][0], 1)
        self.assertEqual(self.pay_yb(), {})

    def test_consume_without_live_acts_keeps_legacy_debit(self):
        # Empty live set: the debit lands, the ledger stays blank.
        self.nested_sess(
            (9, self.synth_exchange(
                'synth-ex-1', 'yuanbao|50',
                [('kangxing2', 1, 1)])))
        self.store.update_character_state(self.rid, lingshi=1000)
        out = self.sess.huodong_exchange_claim(
            [70551, [9, 'synth-ex-1', '']], now_ms=EX_NOW)
        self.assertEqual(decode(bytes(out)[4:])[1][0], 1)
        self.assertEqual(self.role()['lingshi'], 950)
        self.assertEqual(self.pay_yb(), {})

    # -- consumption accounting -----------------------------------------
    def test_consume_short_purse_refuses_without_side_effects(self):
        sess = self.make_sess(
            config=_SynthTable(
                self.cfg, 3,
                self.synth(3, 'synth-c-1', '200', 92)))
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        self.store.update_character_state(self.rid, lingshi=50)
        self.assertFalse(
            sess._bag_money_decr(self.rid, 'YB', 200,
                                 now_ms=EX_NOW))
        self.assertEqual(self.role()['lingshi'], 50)
        self.assertIsNone(self.store.get_role_huodong(self.rid))

    def test_consume_without_live_acts_keeps_legacy_debit(self):
        self.store.update_character_state(self.rid, lingshi=1000)
        self.assertTrue(self.sess._bag_money_decr(self.rid, 'YB', 200))
        self.assertEqual(self.role()['lingshi'], 800)
        self.assertIsNone(self.store.get_role_huodong(self.rid))

    # -- login finish ----------------------------------------------------
    def test_finish_login_grants_pending_with_12301(self):
        code, frames = self.commit('off1', 500, online=False)
        self.assertEqual(code, '1')
        self.assertEqual(frames, [])
        self.assertEqual(self.role()['lingshi'] or 0, 0)
        self.assertEqual(self.store.recharge_charge_total(self.rid), 0)
        got = dict(self.cmds(
            self.sess.recharge_finish_login(self.role())))
        self.assertEqual(got['12301'], [500.0])
        self.assertIn('32010', got)
        self.assertEqual(self.role()['lingshi'], 500)
        self.assertEqual(self.store.recharge_charge_total(self.rid),
                         500)
        self.assertEqual(
            self.sess.recharge_finish_login(self.role()), [])

    def test_finish_login_gates_12301_on_recharge_type(self):
        self.commit('off3', 100, rtype='3', online=False)
        got = dict(self.cmds(
            self.sess.recharge_finish_login(self.role())))
        self.assertNotIn('12301', got)
        self.assertIn('32010', got)
        self.assertEqual(self.role()['lingshi'], 100)
        # Type 3 never joins charge totals.
        self.assertEqual(self.store.recharge_charge_total(self.rid), 0)

    def test_enter_world_finishes_pending_and_reports_pair(self):
        self.commit('off2', 500, online=False,
                    create_ms=int(__import__('time').time() * 1000))
        out = self.sess.enter_world(['10003', str(self.rid)])
        self.assertIsNotNone(out)
        bodies = self.cmds(out)
        by_cmd = dict(bodies)
        self.assertEqual(by_cmd['12301'], [500.0])
        state = by_cmd['10003'][1]
        self.assertEqual(state[8], [500.0, 500.0])
        self.assertEqual(self.role()['lingshi'], 500)
        # A second login grants nothing new.
        out = self.sess.enter_world(['10003', str(self.rid)])
        again = dict(self.cmds(out))
        self.assertNotIn('12301', again)
        self.assertEqual(again['10003'][1][8], [500.0, 500.0])


if __name__ == '__main__':
    unittest.main()

"""Qibing progression: 87000 getData, 87001 upgrade, 87002 getbinqi.

Evidence: QiZhanBinQiServiceImpl bytecode (getData/upgrade/getbinqi/
insertQb/clear/schedule), the qizhanbingqi.jat bands, RoleQizhanbinqi.xml
storage, and the ZhanDouLiServiceImpl fight readers. Every test below
feeds the real encrypted wire; costs, pity windows, expiry and the
87102/70520 fan-outs pin the jar shapes.
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

INITKEY = bytes.fromhex('00000009060f494e49544b4559')

QIBING_COST = 2  # band-1 needthingsvalue (qibing001 x2)


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


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class QibingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, 'q.db')
        self.store = Store(self.db_path)
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.rid = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = self.make_sess(self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'

    def make_sess(self, config):
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            save_role_state=self.store.update_character_state,
            get_role_vip=self.store.get_role_vip,
            save_role_vip=self.store.save_role_vip,
            get_role_qibing=self.store.get_role_qibing,
            save_role_qibing=self.store.save_role_qibing,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_slot_by_bag_id=
            self.store.get_role_bag_slot_by_bag_id,
            get_role_bag_slot=self.store.get_role_bag_slot,
            get_role_skillbook_slots=self.store.get_role_skillbook_slots,
            get_role_skillbook_slot=self.store.get_role_skillbook_slot,
            insert_role_skillbook_slot=
            self.store.insert_role_skillbook_slot,
            update_role_skillbook_slot=
            self.store.update_role_skillbook_slot,
            delete_role_skillbook_slot=
            self.store.delete_role_skillbook_slot,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            get_role_huodong=self.store.get_role_huodong,
            save_role_huodong=self.store.save_role_huodong,
            get_huodong_info=self.store.get_huodong_info,
            huodong_exchange_tx=self.store.huodong_exchange_tx,
            huodong_mall_buy_tx=self.store.huodong_mall_buy_tx,
            charge_total_in_time=self.store.recharge_charge_total_in_time,
            charge_total=self.store.recharge_charge_total,
            charge_today=self.store.recharge_charge_today,
            config=config)
        sess.feed(INITKEY)
        return sess

    # -- helpers ---------------------------------------------------------
    def feed(self, cmd, data):
        req = self.sess.cipher.encode(encode([cmd, data]))
        out = self.sess.feed(struct.pack('>I', len(req)) + req)
        return [decode(bytes(f)[4:]) for f in out]

    def synth(self, act_id, con):
        now = int(time.time() * 1000)
        return _SynthTable(self.cfg, 30, {
            'id': 'synth-30-1', 'start_ms': now - 3600000,
            'end_ms': now + 3600000, 'pic': '',
            'activities': [{
                'id': act_id, 'order': 1, 'need_level': 1,
                'need_pay_yb': 0, 'day_count': 5, 'max_count': 5,
                'con1': str(con), 'functiontype': 80,
                'currencies': {}, 'item_views': [], 'choose_awards': {}}]})

    def grant(self):
        self.store.save_role_vip(self.rid, vip_level=1)
        return self.feed(87002, None)

    def stock(self, count):
        self.store.insert_role_bag_slot(
            self.rid, {'slot_num': 10, 'goods_id': 'qibing001',
                       'count': count, 'bind': 0})

    def level1_row(self, **over):
        now = int(time.time() * 1000)
        row = {'binqi_level': 1, 'fail_count': 0, 'lucky_value': 0,
               'upgrade_time': now, 'lingqu_time': now,
               'update_time': now, 'attribute_dan': None}
        row.update(over)
        self.store.save_role_qibing(self.rid, **row)

    # -- getData lifecycle ------------------------------------------------
    def test_getdata_without_row_is_null(self):
        self.assertEqual(self.feed(87000, None), [['87000', None]])

    def test_upgrade_without_row_is_null(self):
        self.assertEqual(self.feed(87001, False), [['87001', None]])

    def test_upgrade_non_bool_is_silent(self):
        self.assertEqual(self.feed(87001, 1), [])
        self.assertEqual(self.feed(87001, None), [])
        self.assertIsNone(self.store.get_role_qibing(self.rid))

    def test_getbinqi_without_vip_answers_1013(self):
        self.assertEqual(self.feed(87002, None),
                         [['87002', [0, 1013]]])
        self.assertIsNone(self.store.get_role_qibing(self.rid))

    def test_getbinqi_grants_pair_then_silent(self):
        before = int(time.time() * 1000)
        got = self.grant()
        # The pair, then the qizhanbinqi_lingqu fight refresh (ZDL).
        self.assertEqual(len(got), 3)
        self.assertEqual(got[0], ['87002', [1, 1, 0]])
        self.assertEqual(got[1], ['87002', None])
        self.assertEqual(got[2][0], '12010')
        self.assertEqual(got[2][1][10],
                         [self.cfg.qibing_fight('1'), 0])
        row = self.store.get_role_qibing(self.rid)
        self.assertEqual((row['binqi_level'], row['fail_count'],
                          row['lucky_value'], row['attribute_dan']),
                         (1, 0, 0, None))
        self.assertGreaterEqual(row['lingqu_time'], before)
        self.assertEqual(row['upgrade_time'], row['lingqu_time'])
        self.assertEqual(row['update_time'], row['lingqu_time'])
        # Claimed: the jar's insertQb early-returns, so one null.
        self.assertEqual(self.feed(87002, None), [['87002', None]])

    def test_getdata_after_grant(self):
        self.grant()
        (frame,) = self.feed(87000, None)
        self.assertEqual(frame[0], '87000')
        level, lucky, expiry, _blank, dans = frame[1]
        self.assertEqual((level, lucky, dans), (1, 0, []))
        row = self.store.get_role_qibing(self.rid)
        self.assertEqual(expiry,
                         row['lingqu_time'] + 720 * 3600 * 1000)

    def test_getdata_above_trial_has_zero_expiry(self):
        self.level1_row(binqi_level=3)
        (frame,) = self.feed(87000, None)
        self.assertEqual(frame[1][0], 3)
        self.assertEqual(frame[1][2], 0)

    # -- upgrade lifecycle -------------------------------------------------
    def test_upgrade_short_goods_no_autobuy(self):
        self.grant()
        got = self.feed(87001, False)
        self.assertEqual(got, [['87001', [0, 1005, None]]])
        row = self.store.get_role_qibing(self.rid)
        self.assertEqual((row['fail_count'], row['lucky_value']), (0, 0))

    def test_upgrade_fail_banks_pity(self):
        self.grant()
        self.stock(QIBING_COST)
        self.level1_row(fail_count=0)
        (frame,) = self.feed(87001, False)
        self.assertEqual(frame[0], '87001')
        self.assertEqual(frame[1][0], -1)
        self.assertEqual(frame[1][1], 1)
        self.assertIn(frame[1][2], (5, 6))
        row = self.store.get_role_qibing(self.rid)
        self.assertEqual((row['fail_count'], row['lucky_value']),
                         (1, frame[1][2]))
        self.assertEqual(self.sess._task_goods_count(
            self.rid, 'qibing001'), 0)

    def test_upgrade_success_broadcasts_and_resets(self):
        self.grant()
        self.stock(QIBING_COST)
        self.level1_row(fail_count=43)
        got = self.feed(87001, False)
        cfg2 = self.cfg.qibing_config(2)
        self.assertEqual(got[:2], [
            ['11101', [87102, ['Wukong', 2, cfg2['name']]]],
            ['87001', [1, 2, 0]]])
        # qizhanbinqi_upgrade -> ZDL:QIZHANBINQI, after the reply.
        self.assertEqual(got[2][0], '12010')
        self.assertEqual(got[2][1][10],
                         [self.cfg.qibing_fight('2'), 0])
        row = self.store.get_role_qibing(self.rid)
        self.assertEqual((row['binqi_level'], row['fail_count'],
                          row['lucky_value']),
                         (2, 0, 0))
        self.assertGreater(row['upgrade_time'], row['lingqu_time'])
        self.assertEqual(self.sess._task_goods_count(
            self.rid, 'qibing001'), 0)

    def test_upgrade_at_max_answers_1001(self):
        self.level1_row(binqi_level=7)
        self.assertEqual(self.feed(87001, False),
                         [['87001', [0, 1001]]])

    def test_upgrade_autobuy_debits_mall_yb(self):
        self.grant()
        self.store.update_character_state(self.rid, lingshi=1000)
        self.level1_row(fail_count=43)
        got = self.feed(87001, True)
        self.assertEqual([f[0] for f in got], ['11101', '87001', '12010'])
        self.assertEqual(got[1], ['87001', [1, 2, 0]])
        roles = self.store.list_roles('hero', 'fu1304')
        self.assertEqual(roles[0]['lingshi'], 1000 - 2 * 30)
        self.assertEqual(
            self.store.get_role_qibing(self.rid)['binqi_level'], 2)

    # -- daily decay and trial expiry --------------------------------------
    def test_stale_day_clears_pity(self):
        stale = int(time.time() * 1000) - 2 * 86400 * 1000
        self.level1_row(fail_count=5, lucky_value=50,
                        update_time=stale)
        (frame,) = self.feed(87000, None)
        self.assertEqual(frame[1][1], 0)
        row = self.store.get_role_qibing(self.rid)
        self.assertEqual((row['lucky_value'], row['fail_count']),
                         (0, 0))

    def test_expired_trial_drops_fight_but_keeps_level(self):
        old = int(time.time() * 1000) - 721 * 3600 * 1000
        self.level1_row(lingqu_time=old)
        (frame,) = self.feed(87000, None)
        self.assertLess(frame[1][2], int(time.time() * 1000))
        self.assertEqual(self.feed(12010, None)[0][1][10], [0, 0])
        # getQizhanBinLevel reads the raw row, expiry aside.
        self.assertEqual(self.sess._zonghe_qibing_level(self.rid), 1)

    # -- stat recalculation -------------------------------------------------
    def test_12010_carries_qibing_fight(self):
        self.assertEqual(self.feed(12010, None)[0][1][10], [0, 0])
        self.grant()
        body = self.feed(12010, None)[0][1]
        self.assertEqual(body[10],
                         [self.cfg.qibing_fight('1'), 0])

    def test_12010_carries_dan_fight(self):
        self.store.save_role_qibing(
            self.rid, binqi_level=3, fail_count=0, lucky_value=0,
            upgrade_time=0, lingqu_time=0, update_time=0,
            attribute_dan=json.dumps({'binghun': 1}))
        (data,) = self.feed(87000, None)
        self.assertEqual(data[1][4], [['binghun', 1]])
        body = self.feed(12010, None)[0][1]
        self.assertEqual(body[10], [self.cfg.qibing_fight('3'),
                                    self.cfg.qibing_dan_fight(
                                        '3', {'binghun': 1})])
        self.assertEqual(body[10][1], 230)

    # -- persistence ---------------------------------------------------------
    def test_level_survives_reopen(self):
        self.grant()
        self.stock(QIBING_COST)
        self.level1_row(fail_count=43)
        self.feed(87001, False)
        self.store.close()
        self.store = Store(self.db_path)
        self.addCleanup(self.store.close)
        self.sess = self.make_sess(self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        (frame,) = self.feed(87000, None)
        self.assertEqual(frame[1][0], 2)
        self.assertEqual(self.feed(12010, None)[0][1][10][0],
                         self.cfg.qibing_fight('2'))

    # -- ct-30 fan-out ---------------------------------------------------------
    def test_upgrade_crossing_queues_70520_once(self):
        self.sess = self.make_sess(self.synth('q-near', 2))
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.grant()
        self.stock(QIBING_COST)
        self.level1_row(fail_count=43)
        got = self.feed(87001, False)
        # 70520 rides the huodong queue, then the coalesced 12010.
        self.assertEqual(got[-1][0], '12010')
        self.assertEqual([f for f in got if f[0] == '70520'],
                         [['70520', ['q-near', 1]]])
        # Level holds at 2: the repeat attempt spends nothing new.
        self.stock(QIBING_COST)
        again = self.feed(87001, False)
        self.assertEqual([f for f in again if f[0] == '70520'], [])

    def test_grant_crossing_queues_70520(self):
        self.sess = self.make_sess(self.synth('q-grant', 1))
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        got = self.grant()
        self.assertIn(['70520', ['q-grant', 1]], got)

    def test_completed_state_is_silent(self):
        self.sess = self.make_sess(self.synth('q-done', 1))
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.store.save_role_huodong(
            self.rid, day_count=json.dumps({'q-done': 5}),
            max_count=json.dumps({'q-done': 5}))
        self.assertNotIn(['70520', ['q-done', 1]], self.grant())


    # -- dan consumption (30301 skills 45/46 -> useAttributeDan) -----------
    def use(self, guid):
        out = self.sess.prop_use(guid)
        if out is None:
            return None
        if isinstance(out, tuple):
            return [decode(bytes(f)[4:]) for f in out]
        return [decode(bytes(out)[4:])]

    def pill(self, slot, goods, count=1):
        self.store.insert_role_bag_slot(
            self.rid, {'slot_num': slot, 'bag_id': f'dan{slot}',
                       'goods_id': goods, 'count': count, 'bind': 0})

    def test_dan_without_row_answers_87103(self):
        self.pill(20, 'binghun')
        self.assertEqual(self.use('dan20'), [['30301', [0, 87103]]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.rid, 20)['count'], 1)

    def test_binhun_success_bumps_map_and_fight(self):
        self.level1_row(binqi_level=3)
        self.pill(21, 'binghun')
        self.assertEqual(self.use('dan21'), [['30301', [1, 'dan21']]])
        self.assertIsNone(self.store.get_role_bag_slot(self.rid, 21))
        # Direct handler call: drain the BingHun fight refresh here.
        (refresh,) = [decode(f[4:]) for f in
                      self.sess._fight_refresh_frames()]
        self.assertEqual(refresh[0], '12010')
        self.assertEqual(refresh[1][10][1],
                         self.cfg.qibing_dan_fight('3', {'binghun': 1}))
        (data,) = self.feed(87000, None)
        self.assertEqual(data[1][4], [['binghun', 1]])
        body = self.feed(12010, None)[0][1]
        self.assertEqual(body[10], [self.cfg.qibing_fight('3'),
                                    self.cfg.qibing_dan_fight(
                                        '3', {'binghun': 1})])

    def test_bingling_cap_zero_answers_87104(self):
        # Level 3 caps bingling at 0: the pill is kept.
        self.level1_row(binqi_level=3)
        self.pill(22, 'bingling')
        self.assertEqual(self.use('dan22'), [['30301', [0, 87104]]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.rid, 22)['count'], 1)

    def test_binhun_cap_full_answers_87104(self):
        self.level1_row(binqi_level=3, attribute_dan=json.dumps(
            {'binghun': 100}))
        self.pill(23, 'binghun')
        self.assertEqual(self.use('dan23'), [['30301', [0, 87104]]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.rid, 23)['count'], 1)

    def test_bingling_success_at_level4(self):
        self.level1_row(binqi_level=4)
        self.pill(24, 'bingling', count=2)
        self.assertEqual(self.use('dan24'), [['30301', [1, 'dan24']]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.rid, 24)['count'], 1)
        self.assertEqual(
            json.loads(self.store.get_role_qibing(
                self.rid)['attribute_dan']),
            {'bingling': 1})

    # -- skill books (99000/99001) in the 10031..10036 band ----------------
    def stock_book(self, slot, goods):
        self.store.insert_role_bag_slot(
            self.rid, {'slot_num': slot, 'bag_id': f'bk{slot}',
                       'goods_id': goods, 'count': 1, 'bind': 0,
                       'attributes': '{"exp":0}'})

    def move(self, frm, to):
        return self.feed(99001, [frm, to])

    def drain(self):
        return [decode(bytes(f)[4:]) for f in
                self.sess._fight_refresh_frames()]

    def fight_body(self, sess=None):
        sess = sess or self.sess
        return decode(bytes(sess.fighting_info())[4:])[1]

    def test_skillbook_slot_locked_at_qibing_level_one(self):
        self.level1_row(binqi_level=1)
        self.stock_book(30, 'qblvsegongji1')
        self.assertEqual(self.move(30, 10031), [['99001', [0, 99004]]])
        self.assertIsNotNone(
            self.store.get_role_bag_slot(self.rid, 30))
        self.assertIsNone(
            self.store.get_role_skillbook_slot(self.rid, 10031))
        self.assertFalse(self.sess._fight_dirty)

    def test_skillbook_slot_opens_at_qibing_level_two(self):
        self.level1_row(binqi_level=2)
        self.stock_book(30, 'qblvsegongji1')
        got = self.move(30, 10031)
        self.assertEqual(got[0][0], '99001')
        self.assertEqual(got[0][1][0], 1)
        self.assertEqual(got[0][1][1][0], 10031)
        self.assertIsNone(got[0][1][2])
        self.assertIsNone(self.store.get_role_bag_slot(self.rid, 30))
        worn = self.store.get_role_skillbook_slot(self.rid, 10031)
        self.assertEqual(worn['goods_id'], 'qblvsegongji1')

    def test_skillbook_only_first_slot_opens_at_level_two(self):
        self.level1_row(binqi_level=2)
        self.stock_book(30, 'qblvsegongji1')
        self.assertEqual(self.move(30, 10032), [['99001', [0, 99004]]])
        self.assertIsNotNone(
            self.store.get_role_bag_slot(self.rid, 30))

    def test_skillbook_wear_emits_one_coalesced_refresh(self):
        self.level1_row(binqi_level=2)
        self.stock_book(30, 'qblvsegongji1')
        got = self.move(30, 10031)
        self.assertEqual([f[0] for f in got], ['99001', '12010'])
        self.assertEqual(got[1][1][14], 50)
        self.assertFalse(self.sess._fight_dirty)
        self.assertEqual(self.drain(), [])

    def test_skillbook_level_requirement_reports_99006(self):
        self.level1_row(binqi_level=2)
        self.stock_book(30, 'qbzisegongji1')
        self.assertEqual(self.move(30, 10031), [['99001', [0, 99006]]])
        self.assertIsNotNone(
            self.store.get_role_bag_slot(self.rid, 30))
        self.assertIsNone(
            self.store.get_role_skillbook_slot(self.rid, 10031))
        self.assertFalse(self.sess._fight_dirty)

    def test_skillbook_level_requirement_allows_equal(self):
        self.level1_row(binqi_level=3)
        self.stock_book(30, 'qbzisegongji1')
        got = self.move(30, 10031)
        self.assertEqual(got[0][1][0], 1)
        worn = self.store.get_role_skillbook_slot(self.rid, 10031)
        self.assertEqual(worn['goods_id'], 'qbzisegongji1')
        self.assertEqual(got[-1][1][14], 180)

    def test_skillbook_replacement_returns_old_book(self):
        self.level1_row(binqi_level=3)
        self.stock_book(30, 'qblvsegongji1')
        self.stock_book(31, 'qbchengsegongji1')
        self.move(30, 10031)
        got = self.move(31, 10031)
        self.assertEqual(got[0][1][0], 1)
        self.assertEqual(got[0][1][1][0], 10031)
        self.assertEqual(got[0][1][2], None)
        self.assertEqual(
            self.store.get_role_skillbook_slot(
                self.rid, 10031)['goods_id'], 'qbchengsegongji1')
        back = self.store.get_role_bag_slot(self.rid, 31)
        self.assertEqual(back['goods_id'], 'qblvsegongji1')
        self.assertIsNone(self.store.get_role_bag_slot(self.rid, 30))
        self.assertEqual(got[-1][1][14], 300)

    def test_skillbook_mutex_blocks_same_type_in_band(self):
        self.level1_row(binqi_level=3)
        self.stock_book(30, 'qblvsegongji1')
        self.stock_book(31, 'qblvsegongji2')
        self.move(30, 10031)
        got = self.move(31, 10032)
        self.assertEqual(got, [['99001', [0, 99007]]])
        self.assertIsNotNone(
            self.store.get_role_bag_slot(self.rid, 31))
        self.assertIsNone(
            self.store.get_role_skillbook_slot(self.rid, 10032))

    def test_skillbook_mutex_allows_other_type(self):
        self.level1_row(binqi_level=3)
        self.stock_book(30, 'qblvsegongji1')
        self.stock_book(31, 'qblvsefangyu1')
        self.move(30, 10031)
        got = self.move(31, 10032)
        self.assertEqual(got[0][1][0], 1)
        self.assertEqual(
            self.store.get_role_skillbook_slot(
                self.rid, 10032)['goods_id'], 'qblvsefangyu1')
        self.assertEqual(got[-1][1][14], 100)

    def test_skillbook_strip_refreshes_and_persists(self):
        self.level1_row(binqi_level=2)
        self.stock_book(30, 'qblvsegongji1')
        self.move(30, 10031)
        got = self.move(10031, 40)
        self.assertEqual(got[0], ['99001', [1, [10031, None], None]])
        self.assertIsNone(
            self.store.get_role_skillbook_slot(self.rid, 10031))
        self.assertEqual(
            self.store.get_role_bag_slot(self.rid, 40)['goods_id'],
            'qblvsegongji1')
        self.assertEqual(got[-1][1][14], 0)
        # Reconnect: a fresh session over the same rows still answers
        # from the persisted slot table.
        other = self.make_sess(self.cfg)
        other.authed_user, other.server_id = 'hero', 'fu1304'
        self.assertEqual(decode(bytes(other.skillbook_info())[4:]),
                         ['99000', []])
        self.assertEqual(self.fight_body(other)[14], 0)

    def test_skillbook_worn_book_survives_reconnect(self):
        self.level1_row(binqi_level=3)
        self.stock_book(30, 'qblvsegongji1')
        self.move(30, 10031)
        other = self.make_sess(self.cfg)
        other.authed_user, other.server_id = 'hero', 'fu1304'
        info = decode(bytes(other.skillbook_info())[4:])
        self.assertEqual(len(info[1]), 1)
        cell = info[1][0]
        cell = cell.get('__assoc__', cell)
        self.assertEqual(cell['0'], 'qblvsegongji1')
        body = self.fight_body(other)
        self.assertEqual(body[14], 50)
        self.assertEqual(body[16][2], 0)

    def test_skillbook_wrong_band_reports_type(self):
        self.level1_row(binqi_level=3)
        self.stock_book(30, 'qblvsegongji1')
        self.assertEqual(self.move(30, 10001), [['99001', [0, 99003]]])
        self.assertIsNotNone(
            self.store.get_role_bag_slot(self.rid, 30))

    def test_skillbook_wing_band_does_not_feed_qibing_bucket(self):
        self.level1_row(binqi_level=3)
        self.store.save_role_guangyi(
            self.rid, level=5, lucky=0, fail_count=0, ispeidai=1,
            update_time=0, attr_dan=None, lingqu_time=0)
        self.stock_book(30, 'gylvsegongji1')
        worn = dict(self.store.get_role_bag_slot(self.rid, 30),
                    slot_num=10051)
        self.store.delete_role_bag_slot(self.rid, 30)
        self.store.insert_role_skillbook_slot(self.rid, worn)
        body = self.fight_body()
        self.assertEqual(body[14], 0)
        self.assertEqual(body[16][2], 50)
        self.assertEqual(self.drain(), [])


if __name__ == '__main__':
    unittest.main()

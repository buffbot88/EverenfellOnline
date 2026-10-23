"""Player stalls (BoothAction/BoothServiceImpl): list, buy, delist, reprice,
money market, settlement, atomicity and reconnect persistence.

Every trade path runs through the real protocol handlers and the real
SQLite store; the tx helpers settle each purchase inside one
BEGIN IMMEDIATE transaction, so a competing buyer either wins cleanly
or sees gone/changed, and a mid-trade failure rolls everything back.
"""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.monster_world import MonsterWorld  # noqa: E402
from game.protocol import Session  # noqa: E402

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..',
                           'reference', 'TonNgoKhong', 'server', 'config',
                           'game')
HAVE_REAL = os.path.isdir(REAL_CONFIG)


class BoothConfig:
    """Deterministic stand-in: fee rate, stacks, categories, no exp."""

    def __init__(self, fee=0.0):
        self._fee = fee

    def trade_fee_rate(self):
        return self._fee

    def goods_max_stack(self, goods_id):
        return 99

    def goods_category(self, goods_id):
        return None

    def role_attribute_row(self, level):
        return {'dealaddexp': 0}


def frames(out):
    if out is None:
        return []
    if isinstance(out, (bytes, bytearray)):
        return [decode(bytes(out)[4:])]
    return [decode(bytes(f)[4:]) for f in out]


def last_cmd(out):
    got = frames(out)
    assert got, 'handler answered nothing'
    return got[-1]


def assoc(m):
    """Unwrap a decoded AMF3 associative array to its plain map."""
    if isinstance(m, dict) and set(m) == {'__assoc__', 'items'}:
        return m['__assoc__']
    return m


def close_quietly(store):
    """Teardown closer that tolerates a mid-test manual close."""
    try:
        store.close()
    except Exception:
        pass


def make_registry(live):
    """Registry surface Session init plus _booth_session_of need."""
    return SimpleNamespace(
        monsters=MonsterWorld(),
        session_of=lambda key: live.get(str(key)))


def make_world(tmpdir, fee=0.0, buyer_money=(1000, 500)):
    """Temp store, seller+buyer roles with bags, live sessions, registry."""
    store = Store(os.path.join(tmpdir, 'm.db'))
    store.create_account('s_acct', hash_password('pw'))
    store.create_account('b_acct', hash_password('pw'))
    seller_id = store.create_character(
        's_acct', 'fu1304', 'SellerHero', job='C', level=56,
        tongqian=1000, lingshi=500)
    buyer_id = store.create_character(
        'b_acct', 'fu1304', 'BuyerHero', job='C', level=56,
        tongqian=buyer_money[0], lingshi=buyer_money[1])
    for rid in (seller_id, buyer_id):
        store.save_role_bag_state(rid, bag_capacity=40, storage_capacity=31)
    seller_bag_id = store.insert_role_bag_slot(
        seller_id, {'slot_num': 1, 'goods_id': 'silver50',
                    'count': 10, 'bind': 0})
    live = {}
    registry = make_registry(live)
    world = SimpleNamespace(
        store=store, seller_id=seller_id, buyer_id=buyer_id,
        seller_bag_id=seller_bag_id, live=live)
    try:
        world.seller = make_world_sess(
            store, live, fee, 's_acct', 1, registry)
        world.buyer = make_world_sess(
            store, live, fee, 'b_acct', 2, registry)
    except Exception:
        store.close()
        raise
    return world


def make_world_sess(store, live, fee, user, conn, registry):
    sess = Session(
        conn_id=conn, check_sign=lambda *a: False,
        get_roles=lambda u, s: [dict(r) for r in store.list_roles(u, s)],
        server_start_ms=0,
        save_role_state=store.update_character_state,
        get_role_bag_slots=store.get_role_bag_slots,
        get_role_bag_state=store.get_role_bag_state,
        get_role_bag_slot_by_bag_id=store.get_role_bag_slot_by_bag_id,
        update_role_bag_slot=store.update_role_bag_slot,
        insert_role_bag_slot=store.insert_role_bag_slot,
        delete_role_bag_slot=store.delete_role_bag_slot,
        save_role_bag_state=store.save_role_bag_state,
        get_booth=store.get_booth, save_booth=store.save_booth,
        get_booth_sell=store.get_booth_sell,
        get_booth_sell_by_slot=store.get_booth_sell_by_slot,
        list_booth_sells=store.list_booth_sells,
        save_booth_sell=store.save_booth_sell,
        delete_booth_sell=store.delete_booth_sell,
        list_public_booths=store.list_public_booths,
        list_booth_trade_logs=store.list_booth_trade_logs,
        save_booth_trade_log=store.save_booth_trade_log,
        get_role_brief=store.get_role_brief,
        find_roles_by_name=store.find_roles_by_name,
        booth_list_goods_tx=store.booth_list_goods_tx,
        booth_delist_goods_tx=store.booth_delist_goods_tx,
        booth_buy_goods_tx=store.booth_buy_goods_tx,
        booth_money_position_tx=store.booth_money_position_tx,
        booth_money_buy_tx=store.booth_money_buy_tx,
        booth_claim_tx=store.booth_claim_tx,
        config=BoothConfig(fee=fee), stage_registry=registry)
    sess.authed_user, sess.server_id = user, 'fu1304'
    (role,) = store.list_roles(user, 'fu1304')
    live[str(role['id'])] = sess
    return sess


class BoothHarness(unittest.TestCase):
    fee = 0.0
    buyer_money = (1000, 500)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        world = make_world(self.tmp.name, fee=self.fee,
                           buyer_money=self.buyer_money)
        self.store = world.store
        self.addCleanup(close_quietly, self.store)
        self.seller_id = world.seller_id
        self.buyer_id = world.buyer_id
        self.seller_bag_id = world.seller_bag_id
        self.seller = world.seller
        self.buyer = world.buyer
        self.live = world.live

    def money(self, rid, user='b_acct'):
        (role,) = [r for r in self.store.list_roles(user, 'fu1304')
                   if str(r['id']) == str(rid)]
        return int(role['tongqian'] or 0), int(role['lingshi'] or 0)

    def bag(self, rid):
        return {s['goods_id']: s['count'] for s in
                self.store.get_role_bag_slots(rid, 1, 150)}

    def list_goods(self, sell_yb=50, sell_jb=30, count=4, sess=None):
        sess = sess or self.seller
        out = sess.booth_in([35101, [self.seller_bag_id, sell_yb,
                                     sell_jb, count]])
        got = last_cmd(out)
        self.assertEqual(got[0], '35101')
        self.assertEqual(got[1][0], 1)
        return got[1][1][0]


class BoothTradeTest(BoothHarness):
    """Goods lifecycle at the genuine zero-fee rate."""

    def test_list_then_buy_goods_success(self):
        sell_id = self.list_goods()
        self.assertEqual(self.bag(self.seller_id).get('silver50'), 6)
        out = self.buyer.booth_buy([35107, [str(self.seller_id), sell_id]])
        got = last_cmd(out)
        self.assertEqual(got[0], '35107')
        self.assertEqual(got[1][0], 1)
        self.assertEqual(got[1][2], 50.0)
        self.assertEqual(got[1][3], 30.0)
        self.assertEqual(got[1][4], sell_id)
        self.assertEqual(self.money(self.buyer_id), (970, 450))
        self.assertEqual(self.bag(self.buyer_id).get('silver50'), 4)
        self.assertIsNone(
            self.store.get_booth_sell(sell_id, self.seller_id))
        booth = self.store.get_booth(str(self.seller_id))
        self.assertEqual(int(booth['booth_jb']), 30)
        self.assertEqual(int(booth['booth_yb']), 50)
        seller_got = frames(self.seller.outbox)
        self.assertTrue(any(f[0] == '35108' for f in seller_got),
                        'seller sees the 35108 sale notify')

    def test_second_buy_of_same_listing_is_gone(self):
        sell_id = self.list_goods()
        self.buyer.booth_buy([35107, [str(self.seller_id), sell_id]])
        before = self.money(self.buyer_id)
        out = self.buyer.booth_buy([35107, [str(self.seller_id), sell_id]])
        self.assertEqual(last_cmd(out), ['35107', [0, 424049]])
        self.assertEqual(self.money(self.buyer_id), before)
        booth = self.store.get_booth(str(self.seller_id))
        self.assertEqual(int(booth['booth_yb']), 50)

    def test_buy_missing_listing_is_gone(self):
        # A booth row with no such listing answers gone, not silence.
        self.seller.booth_money()
        out = self.buyer.booth_buy([35107, [str(self.seller_id),
                                           'bsmissing00']])
        self.assertEqual(last_cmd(out), ['35107', [0, 424049]])
        self.assertEqual(self.money(self.buyer_id), self.buyer_money)

    def test_buy_insufficient_yb(self):
        sell_id = self.list_goods(sell_yb=600, sell_jb=0)
        out = self.buyer.booth_buy([35107, [str(self.seller_id), sell_id]])
        self.assertEqual(last_cmd(out), ['35107', [0, 1002]])
        self.assertEqual(self.money(self.buyer_id), self.buyer_money)
        self.assertIsNotNone(
            self.store.get_booth_sell(sell_id, self.seller_id))

    def test_buy_insufficient_yxb(self):
        sell_id = self.list_goods(sell_yb=2, sell_jb=2000)
        out = self.buyer.booth_buy([35107, [str(self.seller_id), sell_id]])
        self.assertEqual(last_cmd(out), ['35107', [0, 1003]])
        self.assertEqual(self.money(self.buyer_id), self.buyer_money)

    def test_competing_buyers_single_winner(self):
        self.store.create_account('c_acct', hash_password('pw'))
        rival_id = self.store.create_character(
            'c_acct', 'fu1304', 'RivalHero', job='C', level=56,
            tongqian=1000, lingshi=500)
        self.store.save_role_bag_state(rival_id, bag_capacity=40,
                                       storage_capacity=31)
        rival = make_world_sess(self.store, self.live, self.fee,
                                'c_acct', 3, make_registry(self.live))
        sell_id = self.list_goods()
        first = last_cmd(
            self.buyer.booth_buy([35107, [str(self.seller_id), sell_id]]))
        self.assertEqual(first[1][0], 1)
        out = rival.booth_buy([35107, [str(self.seller_id), sell_id]])
        self.assertEqual(last_cmd(out), ['35107', [0, 424049]])
        self.assertEqual(self.money(rival_id, 'c_acct'), (1000, 500))
        self.assertNotIn('silver50', self.bag(rival_id))
        booth = self.store.get_booth(str(self.seller_id))
        self.assertEqual(int(booth['booth_jb']), 30)
        self.assertEqual(int(booth['booth_yb']), 50)

    def test_delist_restores_goods(self):
        sell_id = self.list_goods()
        out = self.seller.booth_out([35102, sell_id])
        self.assertEqual(last_cmd(out), ['35102', [1, sell_id]])
        self.assertEqual(self.bag(self.seller_id).get('silver50'), 10)
        self.assertIsNone(
            self.store.get_booth_sell(sell_id, self.seller_id))
        out = self.seller.booth_out([35102, sell_id])
        self.assertEqual(last_cmd(out), ['35102', [0, 424049]])

    def test_delist_full_bag_keeps_listing(self):
        self.store.save_role_bag_state(self.seller_id, bag_capacity=1,
                                       storage_capacity=31)
        sell_id = self.list_goods(count=10)
        self.store.insert_role_bag_slot(
            self.seller_id, {'slot_num': 1, 'goods_id': 'filler01',
                             'count': 1, 'bind': 0})
        out = self.seller.booth_out([35102, sell_id])
        self.assertEqual(last_cmd(out), ['35102', [0, 1006]])
        self.assertIsNotNone(
            self.store.get_booth_sell(sell_id, self.seller_id))

    def test_change_price_reprices_sale(self):
        sell_id = self.list_goods()
        out = self.seller.booth_change_price([35103, [sell_id, 60, 40]])
        self.assertEqual(last_cmd(out),
                         ['35103', [1, [sell_id, None, 60.0, 40.0]]])
        self.buyer.booth_buy([35107, [str(self.seller_id), sell_id]])
        self.assertEqual(self.money(self.buyer_id), (960, 440))

    def test_change_price_empty_is_rejected(self):
        sell_id = self.list_goods()
        out = self.seller.booth_change_price([35103, [sell_id, 0, 0]])
        self.assertEqual(last_cmd(out), ['35103', [0, 424048]])

    def test_settlement_and_claim(self):
        self.assertEqual(last_cmd(self.seller.booth_money()),
                         ['35115', [0.0, 0.0]])
        sell_id = self.list_goods(sell_yb=70, sell_jb=20)
        self.buyer.booth_buy([35107, [str(self.seller_id), sell_id]])
        self.assertEqual(last_cmd(self.seller.booth_money()),
                         ['35115', [20.0, 70.0]])
        out = self.seller.booth_money_claim()
        self.assertEqual(last_cmd(out), ['35116', [1, 20.0, 70.0]])
        self.assertEqual(self.money(self.seller_id, 's_acct'),
                         (1020, 570))
        self.assertEqual(last_cmd(self.seller.booth_money()),
                         ['35115', [0.0, 0.0]])
        self.assertEqual(last_cmd(self.seller.booth_money_claim()),
                         ['35116', [1, 0.0, 0.0]])

    def test_money_market_yb_round_trip(self):
        out = self.seller.booth_yb_sell([35111, [100, 250]])
        self.assertEqual(last_cmd(out), ['35111', [1, 100.0, 250.0]])
        self.assertEqual(self.money(self.seller_id, 's_acct'),
                         (1000, 400))
        out = self.buyer.booth_buy_yb(
            [35113, [str(self.seller_id), 100, 250]])
        got = last_cmd(out)
        self.assertEqual(got[0], '35113')
        self.assertEqual(got[1][0], 1)
        self.assertEqual(self.money(self.buyer_id), (750, 500))
        out = self.buyer.booth_money_claim()
        self.assertEqual(last_cmd(out), ['35116', [1, 0.0, 100.0]])
        out = self.seller.booth_money_claim()
        self.assertEqual(last_cmd(out), ['35116', [1, 250.0, 0.0]])

    def test_money_market_mismatch_is_change_refresh(self):
        self.seller.booth_yb_sell([35111, [100, 250]])
        out = self.buyer.booth_buy_yb(
            [35113, [str(self.seller_id), 100, 249]])
        self.assertEqual(last_cmd(out), ['35113', [0, 424067]])
        self.assertEqual(self.money(self.buyer_id), self.buyer_money)

    def test_money_market_jb_round_trip(self):
        out = self.seller.booth_jb_sell([35112, [80, 40]])
        self.assertEqual(last_cmd(out), ['35112', [1, 80.0, 40.0]])
        self.assertEqual(self.money(self.seller_id, 's_acct'),
                         (920, 500))
        out = self.buyer.booth_buy_jb(
            [35114, [str(self.seller_id), 80, 40]])
        self.assertEqual(last_cmd(out)[0], '35114')
        self.assertEqual(last_cmd(out)[1][0], 1)
        # The buyer pays 40 YB; the 80 YXB lands in the booth balance.
        self.assertEqual(self.money(self.buyer_id), (1000, 460))
        out = self.buyer.booth_money_claim()
        self.assertEqual(last_cmd(out), ['35116', [1, 80.0, 0.0]])

    def test_listing_guards(self):
        bound_id = self.store.insert_role_bag_slot(
            self.seller_id, {'slot_num': 2, 'goods_id': 'bound01',
                             'count': 1, 'bind': 1})
        out = self.seller.booth_in([35101, [bound_id, 50, 30, 1]])
        self.assertEqual(last_cmd(out), ['35101', [0, 424046]])
        out = self.seller.booth_in(
            [35101, [self.seller_bag_id, 50, 30, 99]])
        self.assertEqual(last_cmd(out), ['35101', [0, 424068]])
        out = self.seller.booth_in(
            [35101, [self.seller_bag_id, 1, 0, 1]])
        self.assertEqual(last_cmd(out), ['35101', [0, 424048]])
        out = self.seller.booth_in(
            [35101, [self.seller_bag_id, 0, 0, 1]])
        self.assertEqual(last_cmd(out), ['35101', [0, 424048]])

    def test_listing_cap_is_eight(self):
        for slot in range(2, 10):
            self.store.insert_role_bag_slot(
                self.seller_id, {'slot_num': slot,
                                 'goods_id': f'cap{slot:02d}',
                                 'count': 1, 'bind': 0})
        rows = {s['slot_num']: s for s in
                self.store.get_role_bag_slots(self.seller_id, 1, 150)}
        ids = [rows[n].get('bag_id') for n in range(1, 10)]
        for bag_id in ids[:8]:
            out = self.seller.booth_in([35101, [bag_id, 50, 30, 1]])
            self.assertEqual(last_cmd(out)[1][0], 1)
        out = self.seller.booth_in([35101, [ids[8], 50, 30, 1]])
        self.assertEqual(last_cmd(out), ['35101', [0, 424047]])

    def test_change_index_swaps_slots(self):
        first = self.list_goods()
        second = self.list_goods()
        out = self.seller.booth_change_index([35104, [first, 1]])
        self.assertEqual(last_cmd(out), ['35104', [1, first, 1]])
        self.assertEqual(
            self.store.get_booth_sell(first, self.seller_id)['slot'], 1)
        self.assertEqual(
            self.store.get_booth_sell(second, self.seller_id)['slot'], 0)
        out = self.seller.booth_change_index([35104, [first, 1]])
        self.assertEqual(last_cmd(out), ['35104', [0, 424053]])
        out = self.seller.booth_change_index([35104, ['bsmissing00', 2]])
        self.assertEqual(last_cmd(out), ['35104', [0, 424049]])

    def test_detail_infos_map(self):
        self.list_goods()
        out = self.seller.booth_detail_infos(
            [35120, [str(self.seller_id), 'nobody']])
        got = last_cmd(out)
        self.assertEqual(got[0], '35120')
        detail = assoc(got[1][0])
        self.assertEqual(detail['3'], 'SellerHero')
        self.assertEqual(detail['4'], 56)
        self.assertEqual(detail['5'], 1)
        self.assertEqual(detail['7'], 1)
        self.assertIsNone(got[1][1])

    def test_discovery_and_logs(self):
        sell_id = self.list_goods()
        online = last_cmd(self.seller.booth_online_list())
        self.assertEqual(online[0], '35100')
        self.assertTrue(any(str(assoc(s).get('0')) == str(self.seller_id)
                            for s in online[1][1]))
        info = last_cmd(self.seller.booth_info([35106, str(
            self.seller_id)]))
        self.assertEqual(info[0], '35106')
        self.assertEqual(info[1][0], str(self.seller_id))
        self.assertTrue(info[1][1])
        found = last_cmd(
            self.buyer.booth_seach([35105, ['SellerHero']]))
        self.assertEqual(found[0], '35105')
        self.assertTrue(any(str(assoc(s).get('0')) == str(self.seller_id)
                            for s in found[1]))
        by_goods = last_cmd(
            self.buyer.booth_seach([35105, ['SellerHero', ['silver50']]]))
        self.assertEqual(by_goods[0], '35105')
        self.assertTrue(any(str(assoc(s).get('0')) == str(self.seller_id)
                            for s in by_goods[1]))
        self.buyer.booth_buy([35107, [str(self.seller_id), sell_id]])
        logs = last_cmd(self.seller.booth_log())
        self.assertEqual(logs[0], '35109')
        self.assertTrue(logs[1])
        trade = last_cmd(self.seller.booth_trade_log())
        self.assertEqual(trade, ['35013', logs[1]])

    def test_modify_name(self):
        out = self.seller.booth_modify_name([35110, '神龙宝摊'])
        self.assertEqual(last_cmd(out), ['35110', [1, '神龙宝摊']])
        out = self.seller.booth_modify_name([35110, 'abc'])
        self.assertEqual(last_cmd(out), ['35110', [0, 424044]])

    def test_failed_trade_rolls_back(self):
        sell_id = self.list_goods()
        buyer_before = self.money(self.buyer_id)
        def fail_log(*a, **k):
            raise RuntimeError('log write failed')
        real_log = Store._tx_trade_log
        Store._tx_trade_log = staticmethod(fail_log)
        try:
            out = self.buyer.booth_buy(
                [35107, [str(self.seller_id), sell_id]])
        finally:
            Store._tx_trade_log = staticmethod(real_log)
        self.assertEqual(frames(out), [])
        self.assertEqual(self.money(self.buyer_id), buyer_before)
        self.assertNotIn('silver50', self.bag(self.buyer_id))
        self.assertIsNotNone(
            self.store.get_booth_sell(sell_id, self.seller_id))
        booth = self.store.get_booth(str(self.seller_id))
        self.assertEqual(int(booth['booth_jb'] or 0), 0)
        self.assertEqual(int(booth['booth_yb'] or 0), 0)
        self.assertEqual(
            self.store.list_booth_trade_logs(str(self.seller_id)), [])

    def test_trade_persists_across_reconnect(self):
        sell_id = self.list_goods()
        self.buyer.booth_buy([35107, [str(self.seller_id), sell_id]])
        path = os.path.join(self.tmp.name, 'm.db')
        self.store.close()
        reopened = Store(path)
        self.addCleanup(reopened.close)
        self.assertIsNone(
            reopened.get_booth_sell(sell_id, str(self.seller_id)))
        booth = reopened.get_booth(str(self.seller_id))
        self.assertEqual(int(booth['booth_jb']), 30)
        self.assertEqual(int(booth['booth_yb']), 50)
        (role,) = [r for r in reopened.list_roles('b_acct', 'fu1304')]
        self.assertEqual(int(role['tongqian']), 970)
        goods = {s['goods_id']: s['count'] for s in
                 reopened.get_role_bag_slots(self.buyer_id, 1, 150)}
        self.assertEqual(goods.get('silver50'), 4)


class BoothFeeTest(BoothHarness):
    """Fee math with a 10% trade_shui-style rate (absent in legacy data)."""

    fee = 0.1

    def test_yb_fee_is_withheld_from_seller(self):
        sell_id = self.list_goods(sell_yb=100, sell_jb=0)
        self.buyer.booth_buy([35107, [str(self.seller_id), sell_id]])
        self.assertEqual(self.money(self.buyer_id), (1000, 400))
        booth = self.store.get_booth(str(self.seller_id))
        self.assertEqual(int(booth['booth_yb']), 90)

    def test_small_amount_fee_is_one(self):
        sell_id = self.list_goods(sell_yb=10, sell_jb=0)
        self.buyer.booth_buy([35107, [str(self.seller_id), sell_id]])
        booth = self.store.get_booth(str(self.seller_id))
        self.assertEqual(int(booth['booth_yb']), 9)


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class BoothGenuineConfigTest(unittest.TestCase):
    def test_trade_records_against_java_tables(self):
        cfg = GameConfig(str(REAL_CONFIG))
        # dealaddexp drives the trade-exp award (tradeSuccessAddExp).
        self.assertEqual(
            int(cfg.role_attribute_row(1)['dealaddexp']), 5)
        self.assertEqual(
            int(cfg.role_attribute_row(56)['dealaddexp']), 60)
        # trade_shui is absent from the legacy tree, so the fee is off.
        self.assertEqual(cfg.trade_fee_rate(), 0.0)


if __name__ == '__main__':
    unittest.main()

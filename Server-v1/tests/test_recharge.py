"""Recharge-record persistence (RechargeRecordServiceImpl/DaoImpl, sqlmap).

Every path runs against the real SQLite store: jar-exact columns and
state machine ('0' granted, '1' pending, '9' revoked, 100x failed),
lifetime and windowed totals, order-duplicate prevention, the pending
finishRecharge login list, and restart persistence.
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402


class RechargeRecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'r.db')
        self.store = Store(self.path)
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.store.create_account('alt', hash_password('pw'))
        self.rid = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56)
        self.now = int(time.time() * 1000)

    # -- helpers ----------------------------------------------------
    def save(self, order='o1', num=100, state='0', rtype='1', role=None,
             account='hero', server='fu1304', when=None, platform='web'):
        return self.store.save_recharge_yb(
            server, account, role if role is not None else self.rid,
            order, num, num, False, platform, rtype, state,
            create_ms=self.now if when is None else when)

    # -- duplicate prevention ---------------------------------------
    def test_fresh_order_not_repeat(self):
        self.assertFalse(self.store.recharge_check_order_repeat('new'))

    def test_live_and_success_orders_repeat(self):
        self.save(order='pend', state='1')
        self.save(order='done', state='0')
        self.assertTrue(self.store.recharge_check_order_repeat('pend'))
        self.assertTrue(self.store.recharge_check_order_repeat('done'))

    def test_failed_and_revoked_orders_do_not_block(self):
        for state in ('1001', '1003', '1004', '1005', '9'):
            self.save(order=f'order-{state}', state=state)
            self.assertFalse(
                self.store.recharge_check_order_repeat(f'order-{state}'),
                state)

    def test_repeat_matches_regardless_of_role(self):
        self.save(order='shared', state='0')
        other = self.store.create_character(
            'alt', 'fu1304', 'Bajie', job='C', level=1)
        self.save(order='shared-2', state='1', role=other, account='alt')
        # The jar keys the repeat check on order_id alone.
        self.assertTrue(self.store.recharge_check_order_repeat('shared'))
        self.assertTrue(self.store.recharge_check_order_repeat('shared-2'))

    # -- lifetime total ---------------------------------------------
    def test_total_sums_success_only(self):
        self.save(order='a', num=100, state='0')
        self.save(order='b', num=50, state='0')
        self.save(order='c', num=1000, state='1')  # pending excluded
        self.save(order='d', num=1000, state='1003')  # failed excluded
        self.save(order='e', num=1000, state='9')  # revoked excluded
        self.save(order='f', num=1000, state='0',
                  rtype='3')  # gm-type excluded
        self.save(order='g', num=1000, state='0',
                  rtype='4')  # gm-type excluded
        self.assertEqual(self.store.recharge_charge_total(self.rid), 150)

    def test_total_scopes_to_account_server(self):
        self.save(order='a', num=100, state='0')
        self.save(order='b', num=1000, state='0', server='other')
        self.save(order='c', num=1000, state='0', account='alt')
        other = self.store.create_character(
            'hero', 'fu1304', 'Bajie', job='C', level=1)
        self.save(order='d', num=25, state='0', role=other)
        # Same account+server totals across roles, like the jar's
        # userGuid+serverId scoping.
        self.assertEqual(self.store.recharge_charge_total(self.rid), 125)
        self.assertEqual(self.store.recharge_charge_total(other), 125)

    def test_total_unknown_role_is_zero(self):
        self.assertEqual(self.store.recharge_charge_total(99999), 0)

    # -- windowed total ----------------------------------------------
    def test_window_counts_pending_and_edges(self):
        start, end = self.now - 1000, self.now + 1000
        self.save(order='in', num=60, state='0', when=self.now)
        self.save(order='pend', num=40, state='1', when=self.now)
        self.save(order='lo', num=1000, state='0', when=start)
        self.save(order='hi', num=1000, state='0', when=end)
        self.save(order='old', num=1000, state='0', when=start - 1)
        self.save(order='new', num=1000, state='0', when=end + 1)
        self.save(order='fail', num=1000, state='1003', when=self.now)
        self.assertEqual(
            self.store.recharge_charge_total_in_time(
                self.rid, start, end), 60 + 40 + 1000 + 1000)

    def test_window_none_bounds_unbounded(self):
        self.save(order='a', num=30, state='0', when=self.now - 10 ** 9)
        self.save(order='b', num=20, state='1', when=self.now + 10 ** 9)
        self.assertEqual(
            self.store.recharge_charge_total_in_time(
                self.rid, None, None), 50)
        self.assertEqual(
            self.store.recharge_charge_total_in_time(
                self.rid, self.now, None), 20)

    def test_window_unknown_role_is_zero(self):
        self.assertEqual(
            self.store.recharge_charge_total_in_time(99999, 0, self.now), 0)

    # -- pending finish on login --------------------------------------
    def test_pending_lists_exact_state_oldest_first(self):
        first = self.save(order='first', num=10, state='1',
                          when=self.now - 5)
        self.save(order='second', num=20, state='1', when=self.now)
        self.save(order='done', num=1000, state='0', when=self.now - 9)
        pending = self.store.recharge_pending(self.rid)
        self.assertEqual([r['order_id'] for r in pending],
                         ['first', 'second'])
        self.assertEqual(pending[0]['id'], first)
        self.assertEqual(pending[0]['money_num'], 10)

    def test_finish_marks_granted_and_total_follows(self):
        self.save(order='off', num=70, state='1')
        self.assertEqual(self.store.recharge_charge_total(self.rid), 0)
        pending = self.store.recharge_pending(self.rid)
        self.assertEqual(len(pending), 1)
        self.assertTrue(
            self.store.recharge_mark_state(pending[0]['id'], '0'))
        self.assertEqual(self.store.recharge_pending(self.rid), [])
        self.assertEqual(self.store.recharge_charge_total(self.rid), 70)
        self.assertTrue(self.store.recharge_check_order_repeat('off'))

    def test_mark_unknown_record_is_false(self):
        self.assertFalse(self.store.recharge_mark_state('nope', '0'))

    # -- atomic grant-on-save -----------------------------------------
    def test_grant_save_credits_and_returns_id(self):
        rid = self.store.recharge_grant_save_tx(
            'fu1304', 'hero', self.rid, 'g1', 50.0, 500, False,
            'web', '1', create_ms=self.now)
        self.assertTrue(rid)
        role = self.store.list_roles('hero', 'fu1304')[0]
        self.assertEqual(role['lingshi'], 500)
        self.assertEqual(self.store.recharge_charge_total(self.rid),
                         500)

    def test_grant_save_duplicate_returns_none_without_credit(self):
        self.save(order='dup', num=500, state='0')
        before = self.store.list_roles('hero', 'fu1304')[0]['lingshi']
        self.assertIsNone(self.store.recharge_grant_save_tx(
            'fu1304', 'hero', self.rid, 'dup', 50.0, 500, False,
            'web', '1', create_ms=self.now))
        role = self.store.list_roles('hero', 'fu1304')[0]
        self.assertEqual(role['lingshi'], before)

    def test_grant_save_pending_duplicate_returns_none(self):
        self.save(order='pend', num=500, state='1')
        self.assertIsNone(self.store.recharge_grant_save_tx(
            'fu1304', 'hero', self.rid, 'pend', 50.0, 500, False,
            'web', '1', create_ms=self.now))
        self.assertEqual(self.store.recharge_charge_total(self.rid), 0)

    # -- atomic finish ------------------------------------------------
    def test_finish_grants_and_marks_in_one_commit(self):
        self.save(order='off', num=70, state='1')
        granted = self.store.recharge_finish_tx(self.rid)
        self.assertEqual(len(granted), 1)
        self.assertEqual(granted[0]['order_id'], 'off')
        self.assertEqual(granted[0]['credit_col'], 'lingshi')
        self.assertEqual(granted[0]['credit_num'], 70)
        role = self.store.list_roles('hero', 'fu1304')[0]
        self.assertEqual(role['lingshi'], 70)
        self.assertEqual(self.store.recharge_pending(self.rid), [])
        self.assertEqual(self.store.recharge_charge_total(self.rid), 70)
        self.assertEqual(self.store.recharge_finish_tx(self.rid), [])

    def test_finish_dedups_same_order_granting_once(self):
        self.save(order='twice', num=40, state='1',
                  when=self.now - 5)
        self.save(order='twice', num=40, state='1', when=self.now)
        granted = self.store.recharge_finish_tx(self.rid)
        self.assertEqual(len(granted), 1)
        role = self.store.list_roles('hero', 'fu1304')[0]
        self.assertEqual(role['lingshi'], 40)
        self.assertEqual(self.store.recharge_charge_total(self.rid), 40)
        self.assertEqual(self.store.recharge_pending(self.rid), [])

    def test_finish_credits_yxb_and_bind_yb_columns(self):
        self.store.db.execute(
            'INSERT INTO recharge_record(id, user_role_id, rmb,'
            ' money_type, money_num, is_calc, recharge_type,'
            ' platform_type, recharge_state, order_id, create_time,'
            ' server_id, user_guid)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('yxb1', str(self.rid), 0.0, 1, 30, 0, '1', '', '1',
             'yxb-ord', self.now, 'fu1304', 'hero'))
        self.store.db.execute(
            'INSERT INTO recharge_record(id, user_role_id, rmb,'
            ' money_type, money_num, is_calc, recharge_type,'
            ' platform_type, recharge_state, order_id, create_time,'
            ' server_id, user_guid)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('byb1', str(self.rid), 0.0, 3, 20, 0, '1', '', '1',
             'byb-ord', self.now, 'fu1304', 'hero'))
        self.store.db.commit()
        granted = self.store.recharge_finish_tx(self.rid)
        cols = {g['order_id']: g['credit_col'] for g in granted}
        self.assertEqual(cols, {'yxb-ord': 'tongqian',
                                'byb-ord': 'bind_lingshi'})
        role = self.store.list_roles('hero', 'fu1304')[0]
        self.assertEqual(role['tongqian'], 30)
        self.assertEqual(role['bind_lingshi'], 20)
        self.assertEqual(role['lingshi'] or 0, 0)

    def test_finish_leaves_unknown_money_type_pending(self):
        self.store.db.execute(
            'INSERT INTO recharge_record(id, user_role_id, rmb,'
            ' money_type, money_num, is_calc, recharge_type,'
            ' platform_type, recharge_state, order_id, create_time,'
            ' server_id, user_guid)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('frz1', str(self.rid), 0.0, 4, 999, 0, '1', '', '1',
             'frz-ord', self.now, 'fu1304', 'hero'))
        self.store.db.commit()
        self.assertEqual(self.store.recharge_finish_tx(self.rid), [])
        self.assertEqual(
            [r['order_id']
             for r in self.store.recharge_pending(self.rid)],
            ['frz-ord'])
        role = self.store.list_roles('hero', 'fu1304')[0]
        self.assertEqual(role['lingshi'] or 0, 0)

    # -- today's total --------------------------------------------------
    def test_charge_today_counts_local_day_only(self):
        loc = time.localtime(self.now // 1000)
        day_start = int(time.mktime(
            (loc.tm_year, loc.tm_mon, loc.tm_mday, 0, 0, 0, 0, 0,
             -1)) * 1000)
        self.save(order='today', num=60, state='0', when=self.now)
        self.save(order='yest', num=40, state='0',
                  when=day_start - 1000)
        self.save(order='pend', num=1000, state='1', when=self.now)
        self.assertEqual(
            self.store.recharge_charge_today(self.rid, self.now), 60)
        self.assertEqual(
            self.store.recharge_charge_total(self.rid), 100)
        self.assertEqual(
            self.store.recharge_charge_today(99999, self.now), 0)

    # -- atomic consume ---------------------------------------------------
    def test_consume_debits_and_bumps_atomically(self):
        self.store.update_character_state(self.rid, lingshi=1000)
        self.assertTrue(
            self.store.yb_consume_tx(self.rid, 200, ['a1', 'a2']))
        role = self.store.list_roles('hero', 'fu1304')[0]
        self.assertEqual(role['lingshi'], 800)
        row = self.store.get_role_huodong(self.rid) or {}
        import json as _json
        self.assertEqual(_json.loads(row.get('pay_yb') or '{}'),
                         {'a1': 200, 'a2': 200})

    def test_consume_short_writes_nothing(self):
        self.store.update_character_state(self.rid, lingshi=50)
        self.assertFalse(
            self.store.yb_consume_tx(self.rid, 200, ['a1']))
        role = self.store.list_roles('hero', 'fu1304')[0]
        self.assertEqual(role['lingshi'], 50)
        self.assertIsNone(self.store.get_role_huodong(self.rid))

    def test_consume_rejects_bad_amounts(self):
        self.store.update_character_state(self.rid, lingshi=1000)
        self.assertFalse(self.store.yb_consume_tx(self.rid, 0, ['a1']))
        self.assertFalse(
            self.store.yb_consume_tx(self.rid, -5, ['a1']))
        self.assertFalse(
            self.store.yb_consume_tx(self.rid, 10, []))
        role = self.store.list_roles('hero', 'fu1304')[0]
        self.assertEqual(role['lingshi'], 1000)
        self.assertIsNone(self.store.get_role_huodong(self.rid))

    # -- persistence ----------------------------------------------------
    def test_rows_survive_reopen(self):
        self.save(order='keep', num=90, state='0')
        self.save(order='wait', num=10, state='1')
        self.store.close()
        reopened = Store(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.recharge_charge_total(self.rid), 90)
        self.assertEqual(
            [r['order_id'] for r in reopened.recharge_pending(self.rid)],
            ['wait'])
        self.assertTrue(reopened.recharge_check_order_repeat('keep'))


if __name__ == '__main__':
    unittest.main()

"""Battle-formation (PoZhenAction/RolePozhenServiceImpl).

Evidence: action javap (11 inbound 48001-48011; 48011 getGoods is a void
grant), impl bytecode (gates, sweep math, double-charge refresh, buffed
awards), PoZhenConfig(ShuaXin) loader mapping, and the shipped
PoZhenBiao (150 rows, 10 layers), PoZhenShuaXin, PoZhenXinXi,
vipbiao (pozhen/pozhentime) and ZuBaoDiaoLuoBiao (@pozhen001-110).

Every path runs through the real handlers and the real SQLite store.
"""
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
from game.protocol import (CMD_POZHEN_GET_GOODS, CMD_POZHEN_INFO,  # noqa: E402
                            CMD_POZHEN_MOVE, CMD_POZHEN_SAODANG,
                            CMD_POZHEN_START, POZHEN_ERR_CANNT_SD,
                            POZHEN_ERR_DIANSHU_LESS, POZHEN_ERR_FULL_BUY,
                            POZHEN_ERR_FULL_COUNT, POZHEN_ERR_JIASU_YB_LESS,
                            POZHEN_ERR_LEVEL_GATE, POZHEN_ERR_LEVEL_LESS,
                            POZHEN_ERR_NO_REFRESH, POZHEN_ERR_NO_SAODANG,
                            POZHEN_ERR_NOT_EXIST, POZHEN_ERR_SAODANGING,
                            POZHEN_ERR_TIME_LESS, POZHEN_ERR_TOP,
                            POZHEN_ERR_YB_SHORT, POZHEN_ERR_YUEJI)

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..',
                           'reference', 'TonNgoKhong', 'server', 'config',
                           'game')
HAVE_REAL = os.path.isdir(REAL_CONFIG)
OPEN_LEVEL = 55


def frames(out):
    if isinstance(out, (bytes, bytearray)):
        return [decode(bytes(out)[4:])]
    return [decode(bytes(f)[4:]) for f in out]


def assoc(cell):
    """Normalize an AMF map cell ([] empty, __assoc__ otherwise)."""
    if isinstance(cell, dict) and '__assoc__' in cell:
        return {int(k): v for k, v in cell['__assoc__'].items()}
    if cell == []:
        return {}
    return cell


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class PozhenInfoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'p.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.cfg = GameConfig(str(REAL_CONFIG))

    def make_session(self, level=56, **state):
        rid = self.store.create_character(
            'hero', 'fu1304', f'Wukong{level}', job='C', level=level,
            **state)
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_vip=self.store.get_role_vip,
            save_role_state=self.store.update_character_state,
            get_role_pozhen=self.store.get_role_pozhen,
            save_role_pozhen=self.store.save_role_pozhen,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            config=self.cfg)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return rid, sess

    def role(self, rid=None):
        rows = self.store.list_roles('hero', 'fu1304')
        if rid is not None:
            rows = [r for r in rows if r['id'] == rid]
        return dict(rows[0])

    def reply(self, out):
        self.assertIsNotNone(out)
        got = frames(out)
        return got[-1] if len(got) == 1 else got[0]

    def test_below_open_level_errors(self):
        _, sess = self.make_session(level=OPEN_LEVEL - 1)
        self.assertEqual(sess.pozhen_info(),
                         frame(encode(
                             ['48001', [0, POZHEN_ERR_LEVEL_LESS]])))

    def test_info_creates_row_with_full_bar(self):
        rid, sess = self.make_session()
        out = sess.pozhen_info()
        got = self.reply(out)
        self.assertEqual(got[0], '48001')
        self.assertEqual(got[1][0], 1)
        body = got[1][1]
        self.assertEqual(body[:2], [1, 0])
        self.assertEqual(assoc(body[2]), {})
        self.assertEqual(body[4], 10)  # vip 0 daily cap
        self.assertEqual(body[5], 0)
        self.assertEqual(body[6], 0)
        self.assertIsNone(body[7])
        self.assertIsNone(body[8])
        self.assertEqual(body[9], 10)
        row = self.store.get_role_pozhen(rid)
        self.assertEqual(row['can_use_count'], 10)

    def test_second_info_reuses_row(self):
        _, sess = self.make_session()
        sess.pozhen_info()
        row = self.store.get_role_pozhen(
            self.store.list_roles('hero', 'fu1304')[0]['id'])
        first = row['refresh_time']
        sess.pozhen_info()
        row2 = self.store.get_role_pozhen(
            self.store.list_roles('hero', 'fu1304')[0]['id'])
        self.assertEqual(row2['refresh_time'], first)

    def test_stale_day_refills_bar(self):
        rid, sess = self.make_session()
        sess.pozhen_info()
        self.store.save_role_pozhen(
            rid, can_use_count=3, buy_count=2, refresh_count=1,
            refresh_time=int(time.time() * 1000) - 2 * 86400000)
        got = self.reply(sess.pozhen_info())
        self.assertEqual(got[1][1][4], 10)
        row = self.store.get_role_pozhen(rid)
        self.assertEqual(
            (row['buy_count'], row['refresh_count'],
             row['can_use_count']),
            (0, 0, 10))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class PozhenActionTest(unittest.TestCase):
    """48002-48011 gates, costs, sweep math and persistence."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'pa.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.rid = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56,
            tongqian=100000, lingshi=10000, bind_lingshi=0)
        self.store.save_role_bag_state(self.rid, bag_capacity=144,
                                       storage_capacity=144)
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_vip=self.store.get_role_vip,
            save_role_state=self.store.update_character_state,
            get_role_pozhen=self.store.get_role_pozhen,
            save_role_pozhen=self.store.save_role_pozhen,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.sess.pozhen_info()  # creates the formation row

    def role(self):
        return dict(self.store.list_roles('hero', 'fu1304')[0])

    def row(self):
        return self.store.get_role_pozhen(self.rid)

    def reply(self, out):
        self.assertIsNotNone(out)
        got = frames(out)
        return got[0] if isinstance(got, list) else got

    def start(self, main_id, idx):
        return self.sess.pozhen_start(['48002', [main_id, idx]])

    # -- 48002 start -------------------------------------------------
    def test_start_negative_is_silent(self):
        self.assertIsNone(self.sess.pozhen_start(['48002', [-1, 0]]))
        self.assertIsNone(self.sess.pozhen_start(['48002', [1, -1]]))

    def test_start_advances_and_spends_a_point(self):
        self.assertIsNone(self.start(1, 1))
        self.assertEqual(
            (self.row()['max_location'], self.row()['locations'],
             self.row()['can_use_count']),
            ('1-1', '1-1', 9))

    def test_start_skipping_ahead_is_yueji(self):
        self.assertEqual(
            self.reply(self.start(1, 2)),
            ['48002', [0, POZHEN_ERR_YUEJI]])

    def test_start_unknown_layer_is_not_exist(self):
        self.assertEqual(
            self.reply(self.start(99, 1)),
            ['48002', [0, POZHEN_ERR_NOT_EXIST]])

    def test_start_replay_needs_refresh(self):
        self.store.save_role_pozhen(
            self.rid, max_location='1-1', locations='1-2')
        self.assertEqual(
            self.reply(self.start(1, 1)),
            ['48002', [0, POZHEN_ERR_NO_REFRESH]])

    def test_start_without_points_is_dianshu_less(self):
        self.store.save_role_pozhen(self.rid, can_use_count=0)
        self.assertEqual(
            self.reply(self.start(1, 1)),
            ['48002', [0, POZHEN_ERR_DIANSHU_LESS]])

    def test_start_without_row_is_level_less(self):
        rid = self.store.create_character(
            'hero', 'fu1304', 'Alt', job='C', level=56)
        sess2_row = self.store.get_role_pozhen(rid)
        self.assertIsNone(sess2_row)
        self.sess.authed_user = 'hero'
        # fresh role id resolves via its own session below
        sess_b = Session(
            conn_id=2, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)
                                    if r['id'] == rid],
            server_start_ms=0,
            get_role_pozhen=self.store.get_role_pozhen,
            save_role_pozhen=self.store.save_role_pozhen,
            config=self.cfg)
        sess_b.authed_user, sess_b.server_id = 'hero', 'fu1304'
        self.assertEqual(
            frames(sess_b.pozhen_start(['48002', [1, 1]]))[0],
            ['48002', [0, POZHEN_ERR_LEVEL_LESS]])

    def test_clearing_layer_advances_next_and_fight(self):
        for idx in range(1, 7):
            self.assertIsNone(self.start(1, idx))
        self.assertEqual(self.row()['max_location'], '1-6')
        self.assertIsNone(self.start(2, 1))
        self.assertEqual(self.row()['max_location'], '2-1')
        got = frames(self.sess.fighting_info())[0]
        self.assertEqual(got[1][7], 270)

    def test_fresh_fight_is_zero(self):
        got = frames(self.sess.fighting_info())[0]
        self.assertEqual(got[1][7], 0)

    # -- 48005 move --------------------------------------------------
    def test_move_view(self):
        self.assertEqual(
            self.reply(self.sess.pozhen_move(['48005', 1])),
            ['48005', [1, 1, 0, 1800000]])
        self.assertIsNone(self.sess.pozhen_move(['48005', 0]))
        self.assertIsNone(self.sess.pozhen_move(['48005', 'x']))
        self.start(1, 1)
        self.start(1, 2)
        self.assertEqual(
            self.reply(self.sess.pozhen_move(['48005', 1])),
            ['48005', [1, 1, 2, 1800000]])
        self.assertEqual(
            self.reply(self.sess.pozhen_move(['48005', 9]))[1][2], 0)

    def test_move_without_row_is_level_less(self):
        rid = self.store.create_character(
            'hero', 'fu1304', 'Alt2', job='C', level=56)
        sess_b = Session(
            conn_id=3, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)
                                    if r['id'] == rid],
            server_start_ms=0,
            get_role_pozhen=self.store.get_role_pozhen,
            save_role_pozhen=self.store.save_role_pozhen,
            config=self.cfg)
        sess_b.authed_user, sess_b.server_id = 'hero', 'fu1304'
        self.assertEqual(
            frames(sess_b.pozhen_move(['48005', 1]))[0],
            ['48005', [0, POZHEN_ERR_LEVEL_LESS]])

    # -- 48003/48007 sweep -------------------------------------------
    def test_saodang_gate_no_cleared_layer(self):
        self.assertEqual(
            self.reply(self.sess.pozhen_saodang(['48003', 1])),
            ['48003', [0, POZHEN_ERR_CANNT_SD]])
        self.assertEqual(
            self.reply(self.sess.pozhen_saodang(['48003', 2])),
            ['48003', [0, POZHEN_ERR_YUEJI]])

    def test_saodang_opens_and_reentry_is_saodanging(self):
        self.start(1, 1)
        self.store.save_role_pozhen(self.rid, locations='1-0')
        got = self.reply(self.sess.pozhen_saodang(['48003', 1]))
        self.assertEqual(got[0], '48003')
        self.assertEqual(got[1][0], 1)
        self.assertEqual(got[1][1], 1800000)
        self.assertEqual(got[1][2], 1800000)
        self.assertEqual(self.row()['in_mopup'], 1)
        self.assertEqual(
            self.reply(self.sess.pozhen_saodang(['48003', 1])),
            ['48003', [0, POZHEN_ERR_SAODANGING]])

    def test_sdover_grants_next_cell(self):
        self.store.save_role_pozhen(
            self.rid, max_location='1-3', locations='1-1',
            can_use_count=10, in_mopup=1, sd_main_id=1,
            mopup_time=int(time.time() * 1000) - 1900000)
        before_exp = self.role()['exp'] or 0
        got = self.reply(self.sess.pozhen_sdover())
        self.assertEqual(got[0], '48007')
        self.assertEqual(got[1][0], 1)
        inner = got[1][1]
        self.assertEqual(inner[5], 0)
        self.assertEqual(inner[6], [1, 2])
        self.assertEqual(self.row()['locations'], '1-2')
        self.assertEqual(self.row()['can_use_count'], 9)
        self.assertEqual(self.row()['in_mopup'], 0)
        self.assertGreater(self.role()['exp'], before_exp)

    def test_sdover_too_early_cancels(self):
        self.start(1, 1)
        self.store.save_role_pozhen(self.rid, locations='1-0')
        self.sess.pozhen_saodang(['48003', 1])
        self.assertEqual(
            self.reply(self.sess.pozhen_sdover()),
            ['48007', [0, POZHEN_ERR_TIME_LESS]])
        self.assertEqual(self.row()['in_mopup'], 0)

    def test_sdover_at_top_errors(self):
        self.store.save_role_pozhen(
            self.rid, max_location='1-3', locations='1-3',
            can_use_count=10, in_mopup=1, sd_main_id=1,
            mopup_time=int(time.time() * 1000) - 1900000)
        self.assertEqual(
            self.reply(self.sess.pozhen_sdover()),
            ['48007', [0, POZHEN_ERR_TOP]])

    def test_info_settles_elapsed_sweep(self):
        self.store.save_role_pozhen(
            self.rid, max_location='1-6', locations='1-0',
            can_use_count=10, in_mopup=1, sd_main_id=1,
            mopup_time=int(time.time() * 1000) - 11 * 1800000 - 1000)
        got = frames(self.sess.pozhen_info())
        self.assertEqual(got[0][0], '48001')
        awards = got[0][1][1][7]
        self.assertEqual([a[4] for a in awards], [1, 2, 3, 4, 5, 6])
        self.assertEqual(self.row()['locations'], '1-6')
        self.assertEqual(self.row()['can_use_count'], 4)
        self.assertEqual(self.row()['in_mopup'], 0)

    def test_mid_sweep_repill_grants_cumulatively(self):
        # The jar feeds the cumulative elapsed count against the moving
        # cursor, so a second mid-sweep poll grants from the new cursor
        # again; the formula is reproduced verbatim.
        self.store.save_role_pozhen(
            self.rid, max_location='1-6', locations='1-0',
            can_use_count=10, in_mopup=1, sd_main_id=1,
            mopup_time=int(time.time() * 1000) - 4500000)
        self.sess.pozhen_info()
        self.assertEqual(self.row()['locations'], '1-2')
        self.assertEqual(self.row()['can_use_count'], 8)
        self.sess.pozhen_info()
        self.assertEqual(self.row()['locations'], '1-4')
        self.assertEqual(self.row()['can_use_count'], 6)

    def test_stop_abandons_sweep(self):
        self.start(1, 1)
        self.store.save_role_pozhen(self.rid, locations='1-0')
        self.sess.pozhen_saodang(['48003', 1])
        self.assertEqual(self.reply(self.sess.pozhen_stop()),
                         ['48010', [1]])
        self.assertEqual(
            (self.row()['in_mopup'], self.row()['mopup_time']), (0, 0))

    # -- 48008 quickly -----------------------------------------------
    def test_quickly_idle_is_no_saodang(self):
        self.assertEqual(
            self.reply(self.sess.pozhen_quickly()),
            ['48008', [0, POZHEN_ERR_NO_SAODANG]])

    def test_quickly_short_yb_reports_cost(self):
        self.store.save_role_pozhen(
            self.rid, max_location='1-6', locations='1-0',
            can_use_count=10, in_mopup=1, sd_main_id=1,
            mopup_time=int(time.time() * 1000) - 1900000)
        self.store.update_character_state(self.rid, lingshi=0)
        got = self.reply(self.sess.pozhen_quickly())
        self.assertEqual(got[0], '48008')
        self.assertEqual(got[1][0], 0)
        self.assertEqual(got[1][1], POZHEN_ERR_JIASU_YB_LESS)
        self.assertGreater(got[1][2], 0)

    def test_quickly_pays_and_clears(self):
        self.store.save_role_pozhen(
            self.rid, max_location='1-6', locations='1-0',
            can_use_count=10, in_mopup=1, sd_main_id=1,
            mopup_time=int(time.time() * 1000) - 1900000)
        before = self.role()['lingshi']
        got = self.reply(self.sess.pozhen_quickly())
        self.assertEqual(got[1][0], 1)
        self.assertEqual(len(got[1][1]), 6)
        self.assertEqual(self.row()['in_mopup'], 0)
        self.assertEqual(self.row()['locations'], '1-6')
        self.assertEqual(self.row()['can_use_count'], 4)
        self.assertLess(self.role()['lingshi'], before)

    # -- 48006 buy ----------------------------------------------------
    def test_buy_at_full_bar_is_full_count(self):
        self.assertEqual(
            self.reply(self.sess.pozhen_buy()),
            ['48006', [0, POZHEN_ERR_FULL_COUNT]])

    def test_buy_adds_a_point(self):
        self.start(1, 1)
        before = self.role()['lingshi']
        self.assertEqual(
            self.reply(self.sess.pozhen_buy()),
            ['48006', [1, 10, 1, 0]])
        self.assertEqual(self.role()['lingshi'], before - 2)

    def test_buy_past_last_config_is_full_buy(self):
        self.store.save_role_pozhen(
            self.rid, can_use_count=0, buy_count=998)
        self.assertEqual(
            self.reply(self.sess.pozhen_buy()),
            ['48006', [0, POZHEN_ERR_FULL_BUY]])

    def test_buy_short_yb_is_1003(self):
        self.start(1, 1)
        self.store.update_character_state(self.rid, lingshi=0)
        self.assertEqual(
            self.reply(self.sess.pozhen_buy()),
            ['48006', [0, POZHEN_ERR_YB_SHORT]])

    # -- 48004 refresh -------------------------------------------------
    def test_refresh_resets_and_charges_twice(self):
        self.start(1, 2)
        before = self.role()['lingshi']
        self.assertEqual(self.reply(self.sess.pozhen_refresh()),
                         ['48004', [1, 1]])
        # The jar decr()s the refresh gold twice; reproduced verbatim.
        self.assertEqual(self.role()['lingshi'], before - 2 * 5)
        self.assertEqual(self.row()['locations'], '1-0')
        self.assertEqual(self.row()['refresh_count'], 1)

    def test_refresh_without_row_is_level_less(self):
        rid = self.store.create_character(
            'hero', 'fu1304', 'Alt3', job='C', level=56)
        sess_b = Session(
            conn_id=4, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)
                                    if r['id'] == rid],
            server_start_ms=0,
            get_role_pozhen=self.store.get_role_pozhen,
            save_role_pozhen=self.store.save_role_pozhen,
            config=self.cfg)
        sess_b.authed_user, sess_b.server_id = 'hero', 'fu1304'
        self.assertEqual(
            frames(sess_b.pozhen_refresh())[0],
            ['48004', [0, POZHEN_ERR_LEVEL_LESS]])

    def test_refresh_level_gate_is_50006(self):
        rid = self.store.create_character(
            'hero', 'fu1304', 'Low', job='C', level=54,
            tongqian=100000, lingshi=10000)
        self.store.save_role_pozhen(
            rid, max_location='1-1', locations='1-1',
            can_use_count=10, refresh_time=int(time.time() * 1000))
        sess_b = Session(
            conn_id=5, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)
                                    if r['id'] == rid],
            server_start_ms=0,
            save_role_state=self.store.update_character_state,
            get_role_pozhen=self.store.get_role_pozhen,
            save_role_pozhen=self.store.save_role_pozhen,
            config=self.cfg)
        sess_b.authed_user, sess_b.server_id = 'hero', 'fu1304'
        self.assertEqual(
            frames(sess_b.pozhen_refresh())[0],
            ['48004', [0, POZHEN_ERR_LEVEL_GATE]])

    # -- 48009 recovery ------------------------------------------------
    def test_recovery_full_bar_succeeds(self):
        self.assertEqual(self.reply(self.sess.pozhen_recovery()),
                         ['48009', [1, [10, 0]]])

    def test_recovery_early_is_time_less(self):
        self.start(1, 1)
        self.assertEqual(
            self.reply(self.sess.pozhen_recovery()),
            ['48009', [0, POZHEN_ERR_TIME_LESS]])

    def test_recovery_after_timer_refills(self):
        self.start(1, 1)
        self.store.save_role_pozhen(
            self.rid, recovery_time=int(time.time() * 1000) -
            self.cfg.pozhen_recovery_ms() - 1000)
        self.assertEqual(self.reply(self.sess.pozhen_recovery()),
                         ['48009', [1, [10, 0]]])
        self.assertEqual(self.row()['recovery_time'], 0)

    # -- 48011 getGoods ------------------------------------------------
    def test_get_goods_is_a_silent_grant(self):
        before = self.role()['exp'] or 0
        self.assertIsNone(
            self.sess.pozhen_get_goods(['48011', [1, 999]]))
        self.assertGreater(self.role()['exp'], before)
        slots = self.store.get_role_bag_slots(self.rid, -1000000,
                                              1000000)
        self.assertTrue(any(str(s.get('goods_id')).startswith('lingshi')
                            for s in slots))

    def test_get_goods_missing_row_is_silent(self):
        rid = self.store.create_character(
            'hero', 'fu1304', 'Alt4', job='C', level=56)
        sess_b = Session(
            conn_id=6, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)
                                    if r['id'] == rid],
            server_start_ms=0,
            get_role_pozhen=self.store.get_role_pozhen,
            save_role_pozhen=self.store.save_role_pozhen,
            config=self.cfg)
        sess_b.authed_user, sess_b.server_id = 'hero', 'fu1304'
        self.assertIsNone(sess_b.pozhen_get_goods(['48011', [1, 1]]))

    # -- buff prop ------------------------------------------------------
    def test_award_buff_doubles_exp_only(self):
        # Shipped money/zhenqi factors are all zero, so only exp scales.
        sub = self.cfg.pozhen_sub(1, 1)
        plain = [56 * sub['jb'] + sub['jb1'],
                 56 * sub['exp'] + sub['exp1'],
                 56 * sub['zhenqi'] + sub['zhenqi1']]
        self.assertGreater(plain[1], 0)
        self.sess.pozhen_use_award_prop(self.rid, 10, 2.0)
        exp_ms = self.sess.pozhen_prop_expire_time(self.rid)
        self.assertGreater(exp_ms, int(time.time() * 1000))
        row = self.store.get_role_pozhen(self.rid)
        result, _extra = self.sess._pozhen_win_and_add(
            self.role(), self.rid, sub, dict(row))
        self.assertEqual(result[0], plain[0] * 2)
        self.assertEqual(result[1], plain[1] * 2)
        # zhenqi rides unscaled, like the jar.
        self.assertEqual(result[2], plain[2])

    def test_buff_expiry_reads_zero(self):
        self.assertEqual(self.sess.pozhen_prop_expire_time(self.rid), 0)

    # -- wire dispatch ---------------------------------------------------
    def test_wire_dispatch(self):
        self.sess.feed(bytes.fromhex('00000009060f494e49544b4559'))
        out = self.sess.feed(frame(self.sess.cipher.encode(
            encode([CMD_POZHEN_INFO]))))
        self.assertEqual(frames(out)[0][0], '48001')
        out = self.sess.feed(frame(self.sess.cipher.encode(
            encode([CMD_POZHEN_START, [1, 1]]))))
        self.assertEqual(out, [])
        out = self.sess.feed(frame(self.sess.cipher.encode(
            encode([CMD_POZHEN_SAODANG, 1]))))
        self.assertEqual(frames(out)[0][0], '48003')
        out = self.sess.feed(frame(self.sess.cipher.encode(
            encode([CMD_POZHEN_MOVE, 1]))))
        self.assertEqual(frames(out)[0][0], '48005')
        out = self.sess.feed(frame(self.sess.cipher.encode(
            encode([CMD_POZHEN_GET_GOODS, [1, 1]]))))
        self.assertEqual(out, [])


if __name__ == '__main__':
    unittest.main()

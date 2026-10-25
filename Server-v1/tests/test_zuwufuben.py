"""ZuwuFuBen (clan-dungeon) batch: codec, gates, lifecycle, persistence.

Evidence: ZuwufubenServiceImpl + SaoDangVo + ZuWuFuBenConfigExportServiceImpl
+ ZuWuStageCopyServiceImpl recovered from dntg_start.jar javap (see
Server-v1/docs/zuwufuben-ledger.md). Wire tests seed the real
ZuWuFuBen/ZuWuCiShuGouMai/ZuWuShuxing/Vip/goods tables (skipped when the
legacy tree is absent) and drive 108001/2/4/6/9/10/11 plus the kill,
scheduler, login and disconnect hooks.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pathlib import Path  # noqa: E402

from game import amf3  # noqa: E402
from game import zuwu as zuwu_lib  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session, _wire_id, frame  # noqa: E402
from db import Store  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2] / 'reference' /
               'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config' / 'ZuWuFuBen.jat').is_file()


class CodecTest(unittest.TestCase):
    def test_sao_round_trip(self):
        cell = zuwu_lib.encode_sao(3, 1000, 2000, True, True)
        self.assertEqual(zuwu_lib.decode_sao(cell),
                         {'sdid': 3, 'start': 1000, 'chixu': 2000,
                          'autopass': True, 'center': True})

    def test_sao_empty_and_broken_are_none(self):
        self.assertIsNone(zuwu_lib.decode_sao(''))
        self.assertIsNone(zuwu_lib.decode_sao(None))
        self.assertIsNone(zuwu_lib.decode_sao('not json'))

    def test_counts_round_trip(self):
        cell = zuwu_lib.format_counts({1: 1})
        self.assertEqual(zuwu_lib.parse_counts(cell), {1: 1})
        self.assertEqual(zuwu_lib.parse_counts('junk'), {})

    def test_used_total_math(self):
        self.assertEqual(zuwu_lib.used_total({1: 1}, {1: 0}, 1), (0, 1))
        self.assertEqual(zuwu_lib.used_total({1: 0}, {1: 2}, 1), (3, 3))

    def test_enter_gate_order(self):
        everyday = {1: 1}
        self.assertEqual(
            zuwu_lib.check_enter(True, False, 30, 1, 1, 0, everyday),
            zuwu_lib.ERR_IN_FUBEN)
        self.assertEqual(
            zuwu_lib.check_enter(False, True, 30, 1, 1, 0, everyday),
            zuwu_lib.ERR_SAODANGING)
        self.assertEqual(
            zuwu_lib.check_enter(False, False, 0, 30, 1, 0, everyday),
            zuwu_lib.ERR_LEVEL_NOT_ENOUGH)
        self.assertEqual(
            zuwu_lib.check_enter(False, False, 30, 1, 5, 0, everyday),
            zuwu_lib.ERR_NOT_OPEN)
        self.assertEqual(
            zuwu_lib.check_enter(False, False, 30, 1, 1, 0, {1: 0}),
            zuwu_lib.ERR_NO_COUNT)
        self.assertIsNone(
            zuwu_lib.check_enter(False, False, 30, 1, 1, 0, everyday))

    def test_offline_floor(self):
        vo = {'start': 1000, 'chixu': 2000}
        self.assertEqual(zuwu_lib.offline_chixu(vo, 2000), 1000)
        self.assertEqual(zuwu_lib.offline_chixu(vo, 5000),
                         zuwu_lib.OFFLINE_SWEEP_FLOOR_MS)


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class DungeonConfigTest(unittest.TestCase):
    def setUp(self):
        self.cfg = GameConfig(str(REAL_CONFIG))

    def test_dungeon_one_uses_real_record(self):
        row = self.cfg.zuwu_fuben_row(1)
        self.assertEqual(row['map'], '91')
        self.assertEqual(row['pos'], [8, 58])
        self.assertEqual(row['level'], 1)
        self.assertEqual(row['gold'], 5)
        self.assertEqual(dict(row['wanted'])['Z800001'], 1)
        self.assertEqual(row['fixed_goods'], [['wuhunsuipian', 30, 0]])
        self.assertEqual(row['wuhunid'], 'zwgg4_1')

    def test_goumai_and_vip_tables_are_real(self):
        self.assertEqual(self.cfg.zuwu_goumai_price(1), 20)
        self.assertEqual(self.cfg.vip_zuwu_cishu(1), 1)
        self.assertEqual(self.cfg.vip_zuwu_time_ms(1), 2000)
        self.assertEqual(self.cfg.vip_zuwu_cishu(0), 0)

    def test_unknown_dungeon_is_none(self):
        self.assertIsNone(self.cfg.zuwu_fuben_row(9999))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', 'pw')
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=30,
            lingshi=1000, tongqian=0)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = self.session()
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=30)

    def session(self):
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_zuwufuben=self.store.get_role_zuwufuben,
            save_role_zuwufuben=self.store.save_role_zuwufuben,
            get_role_zuwu=self.store.get_role_zuwu,
            list_role_zuwu=self.store.list_role_zuwu,
            save_role_zuwu=self.store.save_role_zuwu,
            get_role_bag_dummy=self.store.get_role_bag_dummy,
            add_role_bag_dummy=self.store.add_role_bag_dummy,
            get_role_vip=self.store.get_role_vip,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            get_role_bag_slot=self.store.get_role_bag_slot,
            update_role_bag_slot=self.store.update_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            get_role_email=self.store.get_role_email,
            save_role_email=self.store.save_role_email,
            save_role_state=self.store.update_character_state,
            config=self.cfg)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return sess

    def role(self):
        return self.store.list_roles('hero', 'fu1304')[0]

    def rid(self):
        return _wire_id(self.role())

    def call(self, method, *args):
        out = getattr(self.sess, method)(*args) if args \
            else getattr(self.sess, method)()
        self.assertIsNotNone(out)
        frames = out if isinstance(out, tuple) else (out,)
        return [amf3.decode(bytes(f)[4:]) for f in frames]

    def kill_all(self, did):
        """Drive every wanted kill of a dungeon through the kill hook."""
        cfg = self.cfg.zuwu_fuben_row(did)
        out = []
        for mid, count in cfg['wanted']:
            for _ in range(count):
                out.extend(self.sess._zuwu_kill_progress(
                    self.role(), mid))
        return [amf3.decode(bytes(f)[4:]) for f in out]

    def test_info_fresh_role(self):
        self.assertEqual(self.call('zuwufuben_info'),
                         [['108001', [1, [0, [['1', 0, 1]], None]]]])

    def test_enter_unknown_config_is_silent(self):
        self.assertIsNone(self.sess.zuwu_enter([108002, [9999]]))

    def test_enter_level_gate(self):
        self.store.update_character_state(self.role_id, level=0)
        try:
            self.assertEqual(self.call('zuwu_enter', [108002, [1]]),
                             [['108002', [0, 1000]]])
        finally:
            self.store.update_character_state(self.role_id, level=30)

    def test_enter_quit_reenter(self):
        entered = self.call('zuwu_enter', [108002, [1]])
        self.assertEqual(entered[-1], ['108002', [1, 1]])
        self.assertEqual(entered[-2][0], '108007')
        self.assertEqual(self.call('zuwu_enter', [108002, [1]]),
                         [['108002', [0, 114008]]])
        quit = self.call('zuwu_quit')
        self.assertEqual(quit[-1], ['108006', [1]])
        self.assertTrue(any(f[0] == '20000' for f in quit))
        entered = self.call('zuwu_enter', [108002, [1]])
        self.assertEqual(entered[-1], ['108002', [1, 1]])

    def test_victory_unlocks_next_and_activates_guardian(self):
        self.call('zuwu_enter', [108002, [1]])
        frames = self.kill_all(1)
        self.assertTrue(any(f[0] == '108008' for f in frames))
        self.assertEqual(frames[-1][0], '108003')
        self.assertEqual(frames[-1][1][0], 1)
        row = self.store.get_role_zuwufuben(self.rid())
        self.assertEqual(row['pass_max_id'], 1)
        everyday = zuwu_lib.parse_counts(row['everyday_pass_data'])
        self.assertEqual(everyday.get(1), 0)
        self.assertEqual(everyday.get(2), 1)
        guardian = self.store.get_role_zuwu(self.rid(), 'zwgg4_1')
        self.assertIsNotNone(guardian)
        self.assertEqual(guardian['level'], 1)
        dummy = {r['goods_id']: r['goods_count']
                 for r in self.store.get_role_bag_dummy(self.rid())}
        self.assertEqual(dummy.get('wuhunsuipian'), 30)
        info = self.call('zuwu_info')[0][1]
        self.assertTrue(any(e[0] == 'zwgg4_1' and e[1] == 1 for e in info[0]))
        self.assertEqual(info[1], 30)
        again = self.call('zuwufuben_info')
        self.assertEqual(again[0][1][1][0], 1)

    def test_victory_needs_every_template(self):
        self.call('zuwu_enter', [108002, [1]])
        cfg = self.cfg.zuwu_fuben_row(1)
        first_mid, first_need = cfg['wanted'][0]
        frames = []
        for _ in range(first_need + 3):
            frames.extend(self.sess._zuwu_kill_progress(
                self.role(), first_mid))
        kinds = [amf3.decode(bytes(f)[4:])[0] for f in frames]
        self.assertIn('108008', kinds)
        self.assertNotIn('108003', kinds)
        rest = self.kill_all(1)
        # The overkilled first template was already banked, so the
        # remaining templates still complete the copy.
        self.assertEqual(rest[-1][0], '108003')

    def test_no_count_after_clear(self):
        self.call('zuwu_enter', [108002, [1]])
        self.kill_all(1)
        self.assertEqual(self.call('zuwu_enter', [108002, [1]]),
                         [['108002', [0, 114002]]])

    def test_sweep_locked_without_clear(self):
        self.assertEqual(
            self.call('zuwu_saodang', [108004, [1]]),
            [['108004', [0, 114009]]])

    def test_manual_sweep_settles_once(self):
        self.call('zuwu_enter', [108002, [1]])
        self.kill_all(1)
        self.store.save_role_vip(self.role_id, vip_level=1)
        self.call('zuwu_buy', [108009, [1]])
        start = self.call('zuwu_saodang', [108004, [1]])
        self.assertEqual(start[0][0], '108004')
        self.assertEqual(start[0][1][0], 1)
        end = start[0][1][2]
        self.sess._world_now_ms = lambda: end + 1
        try:
            done = self.sess._zuwu_sweep_timer(self.rid())
        finally:
            del self.sess._world_now_ms
        self.assertIsNotNone(done)
        bodies = [amf3.decode(bytes(f)[4:]) for f in done]
        self.assertEqual(bodies[0][0], '108003')
        repeat = self.sess._zuwu_sweep_timer(self.rid())
        self.assertIsNone(repeat)
        dummy = {r['goods_id']: r['goods_count']
                 for r in self.store.get_role_bag_dummy(self.rid())}
        # Victory granted 30, the sweep grants 30 more.
        self.assertEqual(dummy.get('wuhunsuipian'), 60)

    def test_refresh_finishes_early_for_gold(self):
        self.call('zuwu_enter', [108002, [1]])
        self.kill_all(1)
        self.store.save_role_vip(self.role_id, vip_level=1)
        self.call('zuwu_buy', [108009, [1]])
        before = self.role()['lingshi']
        self.call('zuwu_saodang', [108004, [1]])
        out = self.call('zuwu_refresh', [108010, [1]])
        self.assertEqual(out[-1], ['108010', [1]])
        self.assertEqual(out[0][0], '108003')
        self.assertEqual(self.role()['lingshi'], before - 5)
        self.assertEqual(self.call('zuwu_refresh', [108010, [1]]),
                         [['108010', [0, 114007]]])

    def test_refresh_wrong_id_and_autopass_gates(self):
        self.call('zuwu_enter', [108002, [1]])
        self.kill_all(1)
        self.store.save_role_vip(self.role_id, vip_level=1)
        self.call('zuwu_buy', [108009, [1]])
        self.call('zuwu_saodang', [108004, [1]])
        self.assertEqual(self.call('zuwu_refresh', [108010, [2]]),
                         [['108010', [0, 0.0]]])

    def test_buy_cap_locked_then_success(self):
        self.call('zuwu_enter', [108002, [1]])
        self.kill_all(1)
        self.assertEqual(self.call('zuwu_buy', [108009, [1]]),
                         [['108009', [0, 114006]]])
        self.store.save_role_vip(self.role_id, vip_level=1)
        before = self.role()['lingshi']
        self.assertEqual(self.call('zuwu_buy', [108009, [1]]),
                         [['108009', [1, 1, 1, 2]]])
        self.assertEqual(self.role()['lingshi'], before - 20)
        self.assertEqual(self.call('zuwu_buy', [108009, [1]]),
                         [['108009', [0, 114006]]])
        self.assertEqual(self.call('zuwu_buy', [108009, [99]]),
                         [['108009', [0, 114004]]])

    def test_expiry_releases_the_copy(self):
        self.call('zuwu_enter', [108002, [1]])
        self.assertIn('zuwu_expire:%s' % self.rid(),
                      self.sess.stage_scheduler.pending())
        self.sess._zuwu_expire(self.rid())
        self.assertNotIn(self.rid(), self.sess._zuwu_attempt)
        again = self.call('zuwu_enter', [108002, [1]])
        self.assertEqual(again[-1], ['108002', [1, 1]])

    def test_disconnect_banks_sweep_and_login_restarts_clock(self):
        self.call('zuwu_enter', [108002, [1]])
        self.kill_all(1)
        self.store.save_role_vip(self.role_id, vip_level=1)
        self.call('zuwu_buy', [108009, [1]])
        self.call('zuwu_saodang', [108004, [1]])
        row = self.store.get_role_zuwufuben(self.rid())
        vo = zuwu_lib.decode_sao(row['saodang_data'])
        self.sess._world_now_ms = lambda: vo['start'] + 500
        try:
            self.sess._zuwu_on_disconnect()
        finally:
            del self.sess._world_now_ms
        row = self.store.get_role_zuwufuben(self.rid())
        vo = zuwu_lib.decode_sao(row['saodang_data'])
        self.assertFalse(vo['center'])
        remain = vo['chixu']
        self.assertGreater(remain, 0)
        self.sess._world_now_ms = lambda: vo['start'] + 9000
        try:
            self.sess._zuwu_on_enter(self.rid())
        finally:
            del self.sess._world_now_ms
        row = self.store.get_role_zuwufuben(self.rid())
        vo2 = zuwu_lib.decode_sao(row['saodang_data'])
        self.assertEqual(vo2['chixu'], remain)
        self.assertEqual(self.sess._zuwu_attempt, {})


if __name__ == '__main__':
    unittest.main()

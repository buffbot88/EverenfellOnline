"""Direct-item monster drops against the genuine D040001 configuration.

Expected values come from the Java bytecode, not from game/loot.py:
- Lottery.roll(rate, TENTHOUSAND): fires when nextInt(10000) <= (int)(rate * 10000).
  hpadd002 at odds 0.01 gives threshold 100, so rolls 0..100 (101 values) succeed.
- calNormalDropRule: skipped when roleLevel - monsterLevel > levelDifference, where
  DiaoLuoShuaiJianBiao gives levelDifference 10 for monstertype 1.
- calDropRule: the daily gate needs monster countlimit != 0 AND goods count > 0.
  D040001 has countlimit 1, and hpadd002 has blank count, so the gate is off.
- A direct item always drops count 1.
"""
import unittest
from unittest import mock

from game import loot
from game.config import GameConfig
from game.ground_items import can_pick_up
from game.protocol import Session
from game.stage_registry import StageRegistry

MID = 'm_7_0'
MAP = '7'


class DirectDropRowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = GameConfig()
        cls.tpl = cls.cfg.monster_template('D040001')

    def test_config_row_matches_reported_slot(self):
        self.assertEqual(self.tpl['level'], 31)
        self.assertEqual(self.tpl['monstertype'], 1)
        self.assertEqual(self.tpl['drop2'], 'hpadd002')
        self.assertEqual(self.tpl['drop2odds'], 0.01)
        self.assertEqual(self.tpl['drop2sp'], '')

    def test_direct_slots_include_hpadd002_and_skip_groups(self):
        slots = loot.direct_slots(self.tpl)
        ids = [s['goods_id'] for s in slots]
        self.assertIn('hpadd002', ids)
        self.assertIn('mpadd002', ids)
        self.assertNotIn('@zhuangbei2', ids)  # zubao group, out of scope

    def test_hpadd002_goods_identity(self):
        row = self.cfg._goods_table()['hpadd002']
        self.assertEqual(row['category'], 11)
        self.assertEqual(row['maxstack'], 200)
        self.assertEqual(row['levelreq'], 20)
        self.assertEqual(self.cfg.goods_count('hpadd002'), 0)

    def test_level_difference_for_monstertype_one(self):
        self.assertEqual(self.cfg.drop_level_difference(1), 10)
        self.assertIsNone(self.cfg.drop_level_difference(99))


class LotteryBoundaryTest(unittest.TestCase):
    """Java nextInt(10000) <= (int)(rate*10000), so the boundary is inclusive."""

    def test_threshold_for_one_percent(self):
        self.assertEqual(loot.lottery_threshold(0.01), 100)

    def test_last_success_roll_is_inclusive(self):
        self.assertTrue(loot.lottery_fires(0.01, 100))

    def test_first_failing_roll(self):
        self.assertFalse(loot.lottery_fires(0.01, 101))

    def test_zero_rate_never_fires(self):
        self.assertFalse(loot.lottery_fires(0.0, 0))

    def test_rate_zero_is_not_positive(self):
        self.assertFalse(loot.lottery_fires(-0.5, 0))


class EvaluateHpadd002Test(unittest.TestCase):
    def setUp(self):
        cfg = GameConfig()
        self.tpl = cfg.monster_template('D040001')
        self.slot = next(s for s in loot.direct_slots(self.tpl)
                         if s['goods_id'] == 'hpadd002')

    def eval(self, roll, role_level=31, daily=False, slot=None):
        return loot.evaluate_direct_drop(
            self.tpl, slot or self.slot, role_level=role_level,
            level_difference=10, daily_limit=daily, roll=roll)

    def test_successful_roll_drops_one_hpadd002(self):
        out = self.eval(roll=100)
        self.assertEqual(out['outcome'], loot.OUTCOME_DROPPED)
        self.assertEqual(out['goods_id'], 'hpadd002')
        self.assertEqual(out['count'], 1)

    def test_failed_roll_drops_nothing(self):
        out = self.eval(roll=101)
        self.assertEqual(out['outcome'], loot.OUTCOME_MISSED)
        self.assertEqual(out['count'], 0)

    def test_level_gate_boundary_is_inclusive(self):
        # roleLevel - monsterLevel == levelDifference (41 - 31 = 10) still drops.
        self.assertEqual(self.eval(roll=0, role_level=41)['outcome'],
                         loot.OUTCOME_DROPPED)

    def test_level_gate_skips_when_role_is_too_high(self):
        # 42 - 31 = 11 > 10, so the slot is skipped before the lottery runs.
        out = self.eval(roll=0, role_level=42)
        self.assertEqual(out['outcome'], loot.OUTCOME_SKIPPED_LEVEL)
        self.assertEqual(out['count'], 0)

    def test_daily_limit_gate_reports_unsupported_after_success(self):
        out = self.eval(roll=0, daily=True)
        self.assertEqual(out['outcome'], loot.OUTCOME_UNSUPPORTED)
        self.assertEqual(out['count'], 0)

    def test_daily_limit_not_checked_when_lottery_fails(self):
        out = self.eval(roll=101, daily=True)
        self.assertEqual(out['outcome'], loot.OUTCOME_MISSED)

    def test_flagged_slot_is_unsupported(self):
        flagged = dict(self.slot, flags='$')
        self.assertEqual(self.eval(roll=0, slot=flagged)['outcome'],
                         loot.OUTCOME_UNSUPPORTED)

    def test_daily_gate_requires_both_flags(self):
        self.assertTrue(loot.daily_limit_applies('1', '5'))
        self.assertFalse(loot.daily_limit_applies('1', ''))   # goods blank
        self.assertFalse(loot.daily_limit_applies('0', '5'))  # monster no limit
        self.assertFalse(loot.daily_limit_applies(None, None))


class KillLifecycleTest(unittest.TestCase):
    """One-time evaluation at the authoritative death, through two real sessions."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = GameConfig()
        cls.tpl = cls.cfg.monster_template('D040001')

    def setUp(self):
        self.reg = StageRegistry()
        self.role = {'id': 1, 'name': 'R1', 'map_id': MAP, 'map_x': 10,
                     'map_y': 10, 'level': 31, 'exp': 0, 'zhenqi': 0,
                     'hp': 500, 'max_hp': 500, 'mp': 100, 'max_mp': 100}
        self.a = self._session(1, self.role)
        self.b = self._session(2, None)

    def _session(self, conn_id, role):
        roles = [role] if role else []
        sess = Session(conn_id=conn_id, check_sign=lambda *a: False,
                       get_roles=lambda u, s, r=roles: list(r),
                       server_start_ms=0, config=self.cfg, stage_registry=self.reg,
                       save_role_state=lambda *a, **k: None)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        if role:
            self.reg.register(str(role['id']), MAP, sess, x=10, y=10)
        return sess

    def seed(self, hp):
        # (27, 28) is walkable on map 7, so Java places the drop there.
        self.a._monster_reg[MID] = {'template': self.tpl, 'map': MAP,
                                    'born': [27, 28], 'pos': [27, 28]}
        self.a._monster_hp[MID] = hp

    def swing(self, sess, role):
        me = {'kind': 'role', 'id': str(role['id']), 'role': role}
        with mock.patch('random.random', return_value=0.5):
            return sess._resolve_fire(me, 'normal003', 0, [MID], None, 1)

    def test_kill_records_one_result_set_with_no_packets_added(self):
        self.seed(hp=50.0)
        with mock.patch('game.protocol.random.randrange', return_value=100):
            frames = self.swing(self.a, self.role)
        self.assertIn(MID, self.a._world.drop_done)
        results = self.a._world.drop_results[MID]
        # Both 1% slots (hpadd002, mpadd002) fire on roll 100 (threshold 100).
        dropped = [r['goods_id'] for r in results if r['outcome'] == 'dropped']
        self.assertEqual(dropped, ['hpadd002', 'mpadd002'])
        # No S:DROP_GOODS or other invented frame is emitted by the drop step.
        self.assertFalse(any(f for f in frames if b'DROP_GOODS' in f))
        # Exactly one shared ground item per successful drop, visible to both sessions.
        items = self.a._world.ground_items.on_map(MAP)
        self.assertEqual(sorted(i.goods_id for i in items), ['hpadd002', 'mpadd002'])
        # Java placement: monster tile free, so hpadd002 lands on it and
        # mpadd002 takes the first free surround in AExtend order, (28, 28).
        by_goods = {i.goods_id: (i.x, i.y) for i in items}
        self.assertEqual(by_goods['hpadd002'], (27, 28))
        self.assertEqual(by_goods['mpadd002'], (28, 28))
        self.assertEqual({r['goods_id']: r['point'] for r in results},
                         {'hpadd002': (27, 28), 'mpadd002': (28, 28)})
        self.assertIs(self.b._world.ground_items, self.a._world.ground_items)
        self.assertEqual(len({i.id for i in items}), 2)
        self.assertTrue(all(i.count == 1 for i in items))
        self.assertTrue(all(i.owner_id == str(self.role['id']) for i in items))

    def test_failed_roll_through_death_hook_records_no_item(self):
        self.seed(hp=50.0)
        with mock.patch('game.protocol.random.randrange', return_value=101):
            self.swing(self.a, self.role)
        results = self.a._world.drop_results[MID]
        self.assertEqual([r['goods_id'] for r in results if r['outcome'] == 'dropped'], [])
        self.assertEqual({r['goods_id']: r['outcome'] for r in results},
                         {'hpadd002': 'missed', 'mpadd002': 'missed'})
        self.assertEqual(self.a._world.ground_items.on_map(MAP), [])

    def test_second_attack_on_corpse_does_not_reevaluate(self):
        self.seed(hp=50.0)
        with mock.patch('game.protocol.random.randrange', return_value=100):
            self.swing(self.a, self.role)
        first = self.a._world.drop_results[MID]
        created = len(self.a._world.ground_items.on_map(MAP))
        with mock.patch('game.protocol.random.randrange', return_value=0) as rr:
            self.swing(self.b, self.role)
        self.assertEqual(rr.call_count, 0)
        self.assertIs(self.a._world.drop_results[MID], first)
        self.assertEqual(len(self.a._world.ground_items.on_map(MAP)), created)

    def test_too_high_role_level_skips_drops_through_hook(self):
        # 42 - 31 = 11 > levelDifference 10: both slots skip, no items.
        self.role['level'] = 42
        self.seed(hp=50.0)
        with mock.patch('game.protocol.random.randrange', return_value=0):
            self.swing(self.a, self.role)
        results = self.a._world.drop_results[MID]
        self.assertEqual({r['outcome'] for r in results}, {'skipped_level'})
        self.assertEqual(self.a._world.ground_items.on_map(MAP), [])

    def test_dropitemlast_sets_item_lifetime(self):
        self.assertEqual(self.cfg.drop_goods_duration(self.tpl), 60)
        self.seed(hp=50.0)
        with mock.patch('game.protocol.random.randrange', return_value=100):
            with mock.patch.object(Session, '_world_now_ms', return_value=5000):
                self.swing(self.a, self.role)
        for item in self.a._world.ground_items.on_map(MAP):
            self.assertEqual(item.expires_at_ms, 5000 + 60 * 1000)

    def test_owner_window_then_open_through_hook(self):
        self.seed(hp=50.0)
        with mock.patch('game.protocol.random.randrange', return_value=100):
            with mock.patch.object(Session, '_world_now_ms', return_value=9000):
                self.swing(self.a, self.role)
        (item,) = [i for i in self.a._world.ground_items.on_map(MAP)
                   if i.goods_id == 'hpadd002']
        self.assertEqual(item.owner_id, '1')
        self.assertIsNone(item.owner_team_id)
        self.assertFalse(can_pick_up(item, '2', None, 9000 + 19999))
        self.assertTrue(can_pick_up(item, '2', None, 9000 + 20001))
        self.assertTrue(can_pick_up(item, '1', None, 9000 + 1))

    def test_expiry_runs_once_through_world_rounds(self):
        self.seed(hp=50.0)
        with mock.patch('game.protocol.random.randrange', return_value=100):
            with mock.patch.object(Session, '_world_now_ms', return_value=1000):
                self.swing(self.a, self.role)
        self.assertEqual(len(self.a._world.ground_items.on_map(MAP)), 2)
        dropped_at = 1000
        end = dropped_at + 60 * 1000
        with mock.patch.object(Session, '_world_now_ms', return_value=end - 1):
            self.a.ai_tick()
            self.assertEqual(len(self.a._world.ground_items.on_map(MAP)), 2)
            # The peer's round in the same tick cycle changes nothing early.
            self.b.ai_tick()
            self.assertEqual(len(self.a._world.ground_items.on_map(MAP)), 2)
        with mock.patch.object(Session, '_world_now_ms', return_value=end):
            self.a.ai_tick()
            self.assertEqual(self.a._world.ground_items.on_map(MAP), [])
            # A second session's round cannot remove anything twice.
            self.b.ai_tick()
            self.assertEqual(self.a._world.ground_items.on_map(MAP), [])

    def test_disconnecting_killer_keeps_shared_loot(self):
        self.seed(hp=50.0)
        with mock.patch('game.protocol.random.randrange', return_value=100):
            self.swing(self.a, self.role)
        self.reg.unregister_session(self.a)
        self.assertEqual(len(self.a._world.ground_items.on_map(MAP)), 2)

    def test_loot_is_isolated_from_other_maps(self):
        self.seed(hp=50.0)
        with mock.patch('game.protocol.random.randrange', return_value=100):
            self.swing(self.a, self.role)
        self.assertEqual(self.a._world.ground_items.on_map('8'), [])


if __name__ == '__main__':
    unittest.main()

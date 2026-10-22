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
        self.a._monster_reg[MID] = {'template': self.tpl, 'map': MAP,
                                    'born': [11, 10], 'pos': [11, 10]}
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

    def test_second_attack_on_corpse_does_not_reevaluate(self):
        self.seed(hp=50.0)
        with mock.patch('game.protocol.random.randrange', return_value=100):
            self.swing(self.a, self.role)
        first = self.a._world.drop_results[MID]
        with mock.patch('game.protocol.random.randrange', return_value=0) as rr:
            self.swing(self.b, self.role)
        self.assertEqual(rr.call_count, 0)
        self.assertIs(self.a._world.drop_results[MID], first)


if __name__ == '__main__':
    unittest.main()

"""Isolated skill preparation (game/preparation.py), from FightServiceImpl.skillReadyFire.

Uses explicit clock values, never sleeps. Error payloads are Java's:
[0] for a rejected skill, [-1, category, remainMs] for an active cooldown.
"""
import unittest

from game.cooldown import PublicCooldowns
from game.preparation import Preparation
from game.readiness import SkillReadiness

CD_TABLE = {'t070': 700, 't050': 500}


def fighter(cur_mp=100.0, max_mp=200.0, tili=50, gongjisudu=0.0, dead=False, forbidden=False):
    return {'id': 'f1', 'cur_mp': float(cur_mp), 'max_mp': float(max_mp), 'tili': int(tili),
            'gongjisudu': float(gongjisudu), 'dead': dead, 'attack_forbidden': forbidden}


def skill(sid, category, consumetype=1, consume1=30, cd1='t070', cd2=None,
          casttime=0, jinengboshu=None, skillnum=None):
    cfg = {'consumetype': consumetype, 'consume1': consume1, 'cd1': cd1, 'cd2': cd2,
           'casttime': casttime, 'jinengboshu': jinengboshu, 'skillnum': skillnum}
    return {'id': sid, 'category': category, 'config': cfg}


def new_prep(readiness=None):
    cd = PublicCooldowns()
    return Preparation(cd, CD_TABLE, readiness), cd


class RecordingReadiness(SkillReadiness):
    """Snapshots cooldown and MP at the moment readiness is stored, to check order."""

    def __init__(self, cooldowns, fighter_ref, cd_name, now):
        super().__init__()
        self.snapshot = None
        self._cooldowns = cooldowns
        self._fighter = fighter_ref
        self._cd_name = cd_name
        self._now = now

    def set_ready(self, skill, now_ms):
        self.snapshot = {
            'cooldown_registered': self._cooldowns.remain_cd(self._cd_name, self._now) > 0,
            'mp_before_consume': self._fighter['cur_mp'],
        }
        return super().set_ready(skill, now_ms)


class TestSuccessfulPreparation(unittest.TestCase):
    def test_success_registers_cooldown_readiness_and_consumes_once(self):
        prep, cd = new_prep()
        f = fighter(cur_mp=100)
        s = skill('gj1', 'catA')
        ok, err, events = prep.prepare(f, s, now_ms=1000)
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(cd.remain_cd('t070', 1000), 700)
        self.assertEqual(prep.readiness.get('catA').fire_time_ms, 1000)
        self.assertEqual(f['cur_mp'], 70.0)

    def test_event_order_attr_change_then_skill_ready(self):
        prep, _ = new_prep()
        _, _, events = prep.prepare(fighter(cur_mp=100), skill('gj1', 'catA'), now_ms=0)
        self.assertEqual([e['type'] for e in events], ['attr_change', 'skill_ready'])
        self.assertEqual(events[1]['scope'], 'surrounding')

    def test_self_cast_adds_dynamic_cd_with_cd1_remaining(self):
        prep, _ = new_prep()
        _, _, events = prep.prepare(fighter(cur_mp=100), skill('gj1', 'catA'), now_ms=0, self_cast=True)
        self.assertEqual(events[-1], {'type': 'dynamic_cd', 'category': 'catA', 'remain_ms': 700})

    def test_dynamic_cooldown_uses_attack_speed(self):
        prep, cd = new_prep()
        f = fighter(cur_mp=100, gongjisudu=147.4)
        prep.prepare(f, skill('gj1', 'catA'), now_ms=0)
        self.assertEqual(cd.remain_cd('t070', 0), 651)

    def test_zero_cost_skill_emits_no_attr_change(self):
        prep, _ = new_prep()
        f = fighter(cur_mp=100)
        _, _, events = prep.prepare(f, skill('gj1', 'catA', consume1=0), now_ms=0)
        self.assertEqual([e['type'] for e in events], ['skill_ready'])
        self.assertEqual(f['cur_mp'], 100.0)

    def test_empty_consume_type_consumes_nothing(self):
        prep, _ = new_prep()
        f = fighter(cur_mp=0, tili=0)
        ok, _, events = prep.prepare(f, skill('gj1', 'catA', consumetype=0, consume1=99), now_ms=0)
        self.assertTrue(ok)
        self.assertEqual(f['cur_mp'], 0.0)
        self.assertEqual(f['tili'], 0)

    def test_tili_consumption(self):
        prep, _ = new_prep()
        f = fighter(tili=10)
        ok, _, _ = prep.prepare(f, skill('gj1', 'catA', consumetype=2, consume1=4, cd1=None), now_ms=0)
        self.assertTrue(ok)
        self.assertEqual(f['tili'], 6)

    def test_missing_cd_table_entry_stores_no_cooldown(self):
        prep, cd = new_prep()
        ok, _, _ = prep.prepare(fighter(cur_mp=100), skill('gj1', 'catA', cd1='unknown'), now_ms=0)
        self.assertTrue(ok)
        self.assertEqual(cd.remain_cd('unknown', 0), 0)


class TestRejectedPreparationLeavesNoState(unittest.TestCase):
    def assert_untouched(self, prep, cd, f, before_mp, before_tili):
        self.assertEqual(cd._expiry, {})
        self.assertEqual(prep.readiness._by_category, {})
        self.assertEqual(f['cur_mp'], before_mp)
        self.assertEqual(f['tili'], before_tili)

    def test_null_skill_returns_zero(self):
        prep, cd = new_prep()
        f = fighter(cur_mp=100)
        ok, err, events = prep.prepare(f, None, now_ms=0)
        self.assertFalse(ok)
        self.assertEqual(err, [0])
        self.assertEqual(events, [])
        self.assert_untouched(prep, cd, f, 100.0, 50)

    def test_insufficient_mp_returns_zero_and_changes_nothing(self):
        prep, cd = new_prep()
        f = fighter(cur_mp=29)
        ok, err, events = prep.prepare(f, skill('gj1', 'catA', consume1=30), now_ms=0)
        self.assertFalse(ok)
        self.assertEqual(err, [0])
        self.assert_untouched(prep, cd, f, 29.0, 50)

    def test_exact_mp_balance_is_accepted(self):
        prep, _ = new_prep()
        f = fighter(cur_mp=30)
        ok, _, _ = prep.prepare(f, skill('gj1', 'catA', consume1=30), now_ms=0)
        self.assertTrue(ok)
        self.assertEqual(f['cur_mp'], 0.0)

    def test_insufficient_tili_returns_zero(self):
        prep, cd = new_prep()
        f = fighter(tili=1)
        ok, err, _ = prep.prepare(f, skill('gj1', 'catA', consumetype=2, consume1=5), now_ms=0)
        self.assertFalse(ok)
        self.assertEqual(err, [0])
        self.assert_untouched(prep, cd, f, 100.0, 1)

    def test_dead_fighter_returns_zero(self):
        prep, cd = new_prep()
        f = fighter(cur_mp=100, dead=True)
        ok, err, _ = prep.prepare(f, skill('gj1', 'catA'), now_ms=0)
        self.assertFalse(ok)
        self.assertEqual(err, [0])
        self.assert_untouched(prep, cd, f, 100.0, 50)

    def test_attack_forbidden_fighter_returns_zero(self):
        prep, cd = new_prep()
        f = fighter(cur_mp=100, forbidden=True)
        ok, err, _ = prep.prepare(f, skill('gj1', 'catA'), now_ms=0)
        self.assertFalse(ok)
        self.assertEqual(err, [0])
        self.assert_untouched(prep, cd, f, 100.0, 50)


class TestCooldownGate(unittest.TestCase):
    def test_active_cooldown_returns_remaining_payload(self):
        prep, _ = new_prep()
        f = fighter(cur_mp=100)
        s = skill('gj1', 'catA')
        prep.prepare(f, s, now_ms=0)  # cooldown 700 ms
        ok, err, events = prep.prepare(f, s, now_ms=200)
        self.assertFalse(ok)
        self.assertEqual(err, [-1, 'catA', 500])
        self.assertEqual(events, [])

    def test_rejected_by_cooldown_does_not_consume_or_reset_readiness(self):
        prep, _ = new_prep()
        f = fighter(cur_mp=100)
        s = skill('gj1', 'catA')
        prep.prepare(f, s, now_ms=0)
        mp_after_first = f['cur_mp']
        prep.prepare(f, s, now_ms=200)
        self.assertEqual(f['cur_mp'], mp_after_first)
        self.assertEqual(prep.readiness.get('catA').fire_time_ms, 0)

    def test_cooldown_boundary_allows_preparation(self):
        prep, _ = new_prep()
        f = fighter(cur_mp=100)
        s = skill('gj1', 'catA')
        prep.prepare(f, s, now_ms=0)
        ok, _, _ = prep.prepare(f, s, now_ms=700)
        self.assertTrue(ok)


class TestOrderAndReplacement(unittest.TestCase):
    def test_cooldown_then_readiness_then_consumption(self):
        cd = PublicCooldowns()
        f = fighter(cur_mp=100)
        spy = RecordingReadiness(cd, f, 't070', 0)
        prep = Preparation(cd, CD_TABLE, spy)
        prep.prepare(f, skill('gj1', 'catA'), now_ms=0)
        self.assertTrue(spy.snapshot['cooldown_registered'])
        self.assertEqual(spy.snapshot['mp_before_consume'], 100.0)
        self.assertEqual(f['cur_mp'], 70.0)

    def test_repeated_preparation_consumes_once_per_success(self):
        prep, _ = new_prep()
        f = fighter(cur_mp=100)
        s = skill('gj1', 'catA', cd1='t050')
        prep.prepare(f, s, now_ms=0)          # ok, cooldown 500
        prep.prepare(f, s, now_ms=100)        # rejected by cooldown
        prep.prepare(f, s, now_ms=500)        # ok again
        self.assertEqual(f['cur_mp'], 40.0)   # two successes at 30 each

    def test_second_preparation_replaces_category_entry(self):
        prep, _ = new_prep()
        f = fighter(cur_mp=100)
        s = skill('gj1', 'catA', cd1='t050')
        prep.prepare(f, s, now_ms=0)
        prep.prepare(f, s, now_ms=600)
        self.assertEqual(prep.readiness.get('catA').fire_time_ms, 600)

    def test_multiple_categories_are_independent(self):
        prep, _ = new_prep()
        f = fighter(cur_mp=100)
        a = skill('a', 'catA', cd1='t050', casttime=300)
        b = skill('b', 'catB', cd1=None, consume1=0, casttime=0)
        prep.prepare(f, a, now_ms=0)
        prep.prepare(f, b, now_ms=0)
        self.assertFalse(prep.readiness.is_ready(a, 100))
        self.assertTrue(prep.readiness.is_ready(a, 300))
        self.assertTrue(prep.readiness.is_ready(b, 0))


class TestLastingIdentityAndWaves(unittest.TestCase):
    def test_lasting_instance_is_ready_but_a_copy_is_not(self):
        prep, _ = new_prep()
        f = fighter(cur_mp=100)
        lasting = skill('L1', 'catL', cd1='t050', casttime=99999, skillnum=2)
        copy = skill('L1', 'catL', cd1='t050', casttime=99999, skillnum=2)
        prep.prepare(f, lasting, now_ms=0)
        self.assertTrue(prep.readiness.is_ready(lasting, 1))
        self.assertFalse(prep.readiness.is_ready(copy, 1))

    def test_wave_count_from_jinengboshu_then_removal(self):
        prep, _ = new_prep()
        f = fighter(cur_mp=500)
        s = skill('w', 'catW', cd1='t050', jinengboshu=2)
        prep.prepare(f, s, now_ms=0)
        self.assertTrue(prep.readiness.wave_check(s))
        self.assertTrue(prep.readiness.wave_check(s))
        self.assertFalse(prep.readiness.wave_check(s))
        self.assertIsNone(prep.readiness.get('catW'))


if __name__ == '__main__':
    unittest.main()

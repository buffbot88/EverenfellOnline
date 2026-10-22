"""Isolated skill fire (game/firing.py), from FightServiceImpl.skillFire.

Uses explicit clock values, never sleeps. Rejections are silent in Java:
no payload, no state change except where skillWaveCheck decrements.
"""
import unittest

from game.cooldown import PublicCooldowns
from game.firing import Firing
from game.preparation import Preparation

CD_TABLE = {'t070': 700, 't050': 500}


def fighter(cur_mp=100.0, tili=50, dead=False, forbidden=False):
    return {'id': 'f1', 'cur_mp': float(cur_mp), 'max_mp': 200.0, 'tili': int(tili),
            'gongjisudu': 0.0, 'dead': dead, 'attack_forbidden': forbidden}


def skill(sid, category, consume1=30, consumetype=1, cd1='t070', casttime=0,
          jinengboshu=None, skillnum=None):
    cfg = {'consumetype': consumetype, 'consume1': consume1, 'cd1': cd1, 'cd2': None,
           'casttime': casttime, 'jinengboshu': jinengboshu, 'skillnum': skillnum}
    return {'id': sid, 'category': category, 'config': cfg}


class RecordingEffects:
    """Effects boundary spy: records the state visible at the moment fight runs."""

    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def fight(self, fighter, skill, index, targets):
        self.calls.append({
            'wave_at_call': None,
            'index_at_call': skill.get('index'),
            'targets': targets,
        })
        return self.result


def make(effects=None):
    cd = PublicCooldowns()
    prep = Preparation(cd, CD_TABLE)
    eff = effects or RecordingEffects()
    return Firing(prep, eff), prep, cd, eff


class TestRejectedWithoutPreparation(unittest.TestCase):
    def test_fire_without_preparation_is_silently_rejected(self):
        firing, prep, _, eff = make()
        f = fighter()
        ok, events = firing.fire(f, skill('gj1', 'catA'), 1, ['t'], now_ms=0)
        self.assertFalse(ok)
        self.assertEqual(events, [])
        self.assertEqual(eff.calls, [])
        self.assertIsNone(prep.readiness.get('catA'))

    def test_null_fighter_or_skill_is_rejected(self):
        firing, _, _, eff = make()
        self.assertEqual(firing.fire(None, skill('gj1', 'catA'), 1, [], 0), (False, []))
        self.assertEqual(firing.fire(fighter(), None, 1, [], 0), (False, []))
        self.assertEqual(eff.calls, [])


class TestReadinessGate(unittest.TestCase):
    def test_casttime_blocks_fire_until_threshold(self):
        firing, prep, _, eff = make()
        f = fighter()
        s = skill('gj1', 'catA', casttime=300, cd1=None, consume1=0)
        prep.prepare(f, s, now_ms=0)
        self.assertEqual(firing.fire(f, s, 1, [], now_ms=299), (False, []))
        ok, events = firing.fire(f, s, 1, [], now_ms=300)
        self.assertTrue(ok)
        self.assertEqual(len(eff.calls), 1)

    def test_rejected_by_readiness_does_not_decrement_waves(self):
        firing, prep, _, _ = make()
        f = fighter()
        s = skill('gj1', 'catA', casttime=300, cd1=None, consume1=0, jinengboshu=2)
        prep.prepare(f, s, now_ms=0)
        firing.fire(f, s, 1, [], now_ms=10)
        self.assertEqual(prep.readiness.get('catA').remain_wave_num, 2)


class TestDeadAndForbidden(unittest.TestCase):
    def test_dead_fighter_rejected_without_wave_decrement(self):
        firing, prep, _, eff = make()
        f = fighter()
        s = skill('gj1', 'catA', cd1=None, consume1=0, jinengboshu=2)
        prep.prepare(f, s, now_ms=0)
        f['dead'] = True
        self.assertEqual(firing.fire(f, s, 1, [], now_ms=0), (False, []))
        self.assertEqual(prep.readiness.get('catA').remain_wave_num, 2)
        self.assertEqual(eff.calls, [])

    def test_attack_forbidden_fighter_rejected(self):
        firing, prep, _, eff = make()
        f = fighter()
        s = skill('gj1', 'catA', cd1=None, consume1=0)
        prep.prepare(f, s, now_ms=0)
        f['attack_forbidden'] = True
        self.assertEqual(firing.fire(f, s, 1, [], now_ms=0), (False, []))
        self.assertEqual(eff.calls, [])


class TestWaveBoundary(unittest.TestCase):
    def test_three_waves_permit_three_fires_then_fourth_removes_and_fails(self):
        effects = RecordingEffects()
        firing, prep, _, eff = make(effects)
        f = fighter(cur_mp=500)
        s = skill('gj1', 'catA', cd1=None, consume1=0, jinengboshu=3)
        prep.prepare(f, s, now_ms=0)
        self.assertTrue(firing.fire(f, s, 1, [], now_ms=0)[0])
        self.assertTrue(firing.fire(f, s, 1, [], now_ms=0)[0])
        self.assertTrue(firing.fire(f, s, 1, [], now_ms=0)[0])
        # Final success leaves the entry in place at zero waves.
        self.assertIsNotNone(prep.readiness.get('catA'))
        self.assertEqual(prep.readiness.get('catA').remain_wave_num, 0)
        self.assertEqual(len(eff.calls), 3)
        # Fourth attempt: zero waves, entry removed, rejected silently.
        self.assertEqual(firing.fire(f, s, 1, [], now_ms=0), (False, []))
        self.assertIsNone(prep.readiness.get('catA'))
        self.assertEqual(len(eff.calls), 3)

    def test_single_wave_skill_fires_once(self):
        firing, prep, _, eff = make()
        f = fighter()
        s = skill('gj1', 'catA', cd1=None, consume1=0, jinengboshu=1)
        prep.prepare(f, s, now_ms=0)
        self.assertTrue(firing.fire(f, s, 1, [], now_ms=0)[0])
        self.assertFalse(firing.fire(f, s, 1, [], now_ms=0)[0])
        self.assertEqual(len(eff.calls), 1)


class TestLastingIdentity(unittest.TestCase):
    def test_lasting_instance_fires_repeatedly_until_waves_exhausted(self):
        firing, prep, _, eff = make()
        f = fighter(cur_mp=500)
        s = skill('L1', 'catL', cd1=None, consume1=0, casttime=99999, skillnum=2, jinengboshu=2)
        prep.prepare(f, s, now_ms=0)
        # Lasting exemption ignores casttime, but the category entry is still required.
        self.assertTrue(firing.fire(f, s, 1, [], now_ms=1)[0])
        self.assertTrue(firing.fire(f, s, 1, [], now_ms=1)[0])
        self.assertFalse(firing.fire(f, s, 1, [], now_ms=1)[0])
        self.assertIsNone(prep.readiness.get('catL'))

    def test_copy_of_lasting_skill_is_not_exempt(self):
        firing, prep, _, eff = make()
        f = fighter()
        lasting = skill('L1', 'catL', cd1=None, consume1=0, casttime=99999, skillnum=2, jinengboshu=5)
        copy = skill('L1', 'catL', cd1=None, consume1=0, casttime=99999, skillnum=2, jinengboshu=5)
        prep.prepare(f, lasting, now_ms=0)
        self.assertEqual(firing.fire(f, copy, 1, [], now_ms=1), (False, []))
        self.assertEqual(eff.calls, [])


class TestNoDuplicateChargeOrCooldownReset(unittest.TestCase):
    def test_firing_does_not_consume_resources_or_touch_cooldowns(self):
        firing, prep, cd, eff = make()
        f = fighter(cur_mp=100, tili=50)
        s = skill('gj1', 'catA', consume1=30, cd1='t050', jinengboshu=3)
        prep.prepare(f, s, now_ms=0)
        self.assertEqual(f['cur_mp'], 70.0)
        cd_before = cd.remain_cd('t050', 0)
        fire_time_before = prep.readiness.get('catA').fire_time_ms

        firing.fire(f, s, 1, [], now_ms=10)
        firing.fire(f, s, 1, [], now_ms=20)

        self.assertEqual(f['cur_mp'], 70.0)
        self.assertEqual(f['tili'], 50)
        self.assertEqual(cd.remain_cd('t050', 0), cd_before)
        self.assertEqual(prep.readiness.get('catA').fire_time_ms, fire_time_before)


class TestEffectsOrderAndEvents(unittest.TestCase):
    def test_index_is_set_before_effects_and_targets_pass_through(self):
        effects = RecordingEffects(result=['hit-1'])
        firing, prep, _, eff = make(effects)
        f = fighter()
        s = skill('gj1', 'catA', cd1=None, consume1=0)
        prep.prepare(f, s, now_ms=0)
        ok, events = firing.fire(f, s, 7, ['t1'], now_ms=0)
        self.assertTrue(ok)
        self.assertEqual(eff.calls[0]['index_at_call'], 7)
        self.assertEqual(eff.calls[0]['targets'], ['t1'])
        self.assertEqual(events, [{'type': 'skill_fire', 'category': 'catA', 'skill_id': 'gj1',
                                   'index': 7, 'targets': ['hit-1'], 'scope': 'surrounding'}])

    def test_null_effects_result_is_reported_as_none(self):
        firing, prep, _, _ = make(RecordingEffects(result=None))
        f = fighter()
        s = skill('gj1', 'catA', cd1=None, consume1=0)
        prep.prepare(f, s, now_ms=0)
        ok, events = firing.fire(f, s, 1, [], now_ms=0)
        self.assertIsNone(events[0]['targets'])


if __name__ == '__main__':
    unittest.main()

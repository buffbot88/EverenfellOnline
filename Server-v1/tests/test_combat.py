"""Player-vs-monster damage (game/combat.py), from ShanghaiResultCalculator.harmCalculate.

Randomness is injected: each lottery draws one roll() value in [0, 1). The
tests pass explicit rolls so every outcome is deterministic.
"""
import unittest

from game import combat

PUTONG = combat.HARM_PUTONG
SHANBI = combat.HARM_SHANBI
BAOJI = combat.HARM_BAOJI
BIHU = combat.HARM_BIHU
BAOJIBIHU = combat.HARM_BAOJIBIHU

NORMAL003 = {'damageformule': 'T21', 'formulea': 2.0, 'formuleb': 10.0,
             'formulec': 0.0, 'formuleg': 0.0,
             'voltcalculate': False, 'criticalcalculate': False}


def role(**kw):
    a = {'wuli': 100.0, 'level': 10, 'max_hp': 0.0, 'shishen': 0.0,
         'damage': 0.0, 'pojia': 0.0, 'qiege': 0.0, 'shanbi': 0.0,
         'baoji': 0.0, 'poji': 0.0, 'is_role': True}
    a.update(kw)
    return a


def monster(**kw):
    t = {'fangyu': 0.0, 'defence': 0.0, 'level': 10, 'shanbi': 0.0,
         'baoji': 0.0, 'gedang': 0.0, 'is_monster': True, 'is_role': False}
    t.update(kw)
    return t


def no_roll():
    raise AssertionError('no lottery should be drawn')


class TestChanceFormulas(unittest.TestCase):
    def test_crit_chance_role_vs_monster(self):
        # ratio 30/40 * lvRatio 10/20 * 0.7
        self.assertAlmostEqual(combat.crit_chance(30, 10, 10, 10, True, True), 0.2625)

    def test_miss_chance_role_vs_monster(self):
        # ratio tgt 30/40 * lvRatio tgt 10/20 * 0.5
        self.assertAlmostEqual(combat.miss_chance(10, 30, 10, 10, True, True), 0.1875)

    def test_chances_are_clamped_to_005_095(self):
        self.assertAlmostEqual(combat.crit_chance(0, 0, 10, 10, True, True), 0.05)
        self.assertAlmostEqual(combat.miss_chance(1000, 0, 10, 10, True, True), 0.05)
        self.assertAlmostEqual(combat.crit_chance(1000, 0, 100, 0, True, True), 0.7)
        self.assertAlmostEqual(combat.crit_chance(1000, 0, 100, 0, False, True), 0.7)



class TestHarmFormula(unittest.TestCase):
    def test_basic_hit_is_skill_harm(self):
        # a * max(wuli - 0, 0) + b, multiplier 1 -> 2*100 + 10
        self.assertEqual(combat.resolve_hit(role(), monster(), NORMAL003,
                                            force='hit'), (210, PUTONG))

    def test_defence_discount_and_level_gap(self):
        # disc = max(50*(1-0) - 10, 0) = 40; eff = 100 - 40 = 60; 2*60 + 10
        att = role(qiege=10.0)
        tgt = monster(fangyu=50.0, level=10)
        self.assertEqual(combat.resolve_hit(att, tgt, NORMAL003, force='hit'),
                         (130, PUTONG))

    def test_damage_multiplier_scales_harm(self):
        # multiplier max(1 + 0 + damage 60 - defence 50 - 0, 0) = 11 -> 210 * 11
        att = role(damage=60.0)
        tgt = monster(defence=50.0)
        self.assertEqual(combat.resolve_hit(att, tgt, NORMAL003, force='hit'),
                         (2310, PUTONG))

    def test_level_term_is_floor(self):
        # max(skill 210, level 10 * formuleg 50 = 500)
        skill = dict(NORMAL003, formuleg=50.0)
        self.assertEqual(combat.resolve_hit(role(), monster(), skill, force='hit'),
                         (500, PUTONG))

    def test_elemental_terms_add_formulea_times_difference(self):
        # + formulea * (10 - 4) = 12 on top of 210
        att = role(elem_damage=(10.0, 0.0, 0.0, 0.0, 0.0))
        tgt = monster(elem_defence=(4.0, 0.0, 0.0, 0.0, 0.0))
        self.assertEqual(combat.resolve_hit(att, tgt, NORMAL003, force='hit'),
                         (222, PUTONG))

    def test_putong_scale_uses_level_power(self):
        # formulec 2 ^ (level 3 - 1) = 4 -> 210 * 4
        skill = dict(NORMAL003, formulec=2.0)
        att = role(level=3)
        self.assertEqual(combat.resolve_hit(att, monster(level=3), skill, force='hit'),
                         (840, PUTONG))

    def test_pvp_scale_applies_to_role_vs_role(self):
        tgt = {'fangyu': 0.0, 'defence': 0.0, 'level': 10, 'shanbi': 0.0,
               'baoji': 0.0, 'gedang': 0.0, 'is_monster': False, 'is_role': True}
        self.assertEqual(combat.resolve_hit(role(), tgt, NORMAL003, force='hit'),
                         (168, PUTONG))

    def test_clamp_above_java_limit(self):
        # 5 * 1e9 + 10 exceeds 2147483648 -> 2047483648
        att = role(wuli=1e9)
        skill = dict(NORMAL003, formulea=5.0)
        self.assertEqual(combat.resolve_hit(att, monster(), skill, force='hit'),
                         (2047483648, PUTONG))


class TestMiss(unittest.TestCase):
    def test_roll_below_chance_is_a_miss(self):
        # chance clamps to 0.05 for zero shanbi; isMingZhong is !isSuccess.
        skill = dict(NORMAL003, voltcalculate=True)
        self.assertEqual(combat.resolve_hit(role(), monster(), skill,
                                            roll=lambda: 0.04), (0, SHANBI))

    def test_roll_above_chance_hits(self):
        skill = dict(NORMAL003, voltcalculate=True)
        self.assertEqual(combat.resolve_hit(role(), monster(), skill,
                                            roll=lambda: 0.9)[1], PUTONG)

    def test_without_voltcalculate_no_lottery(self):
        self.assertEqual(combat.resolve_hit(role(), monster(), NORMAL003,
                                            roll=no_roll)[1], PUTONG)


class TestCritical(unittest.TestCase):
    def test_critical_multiplier_floor_is_one(self):
        # max(1.5 + 0 - 2 - 0, 1) = 1.0, so harm 210 is unchanged
        skill = dict(NORMAL003, criticalcalculate=True)
        rolls = iter([0.01])
        self.assertEqual(combat.resolve_hit(role(), monster(criticalc=2.0), skill,
                                            roll=lambda: next(rolls)),
                         (210, BAOJI))

    def test_critical_multiplier_is_one_and_a_half_at_zero_modifiers(self):
        # baojiHarmCalculate: harm * max(1.5 + 0 + 0 - 0 - 0, 1) = 210 * 1.5
        skill = dict(NORMAL003, criticalcalculate=True)
        rolls = iter([0.01])  # crit lottery: 0.01 < chance 0.05 -> crit
        self.assertEqual(combat.resolve_hit(role(), monster(), skill,
                                            roll=lambda: next(rolls)),
                         (315, BAOJI))

    def test_critical_uses_criticalb_and_criticalc(self):
        # max(1.5 + 0.5 criticalb - 0 criticalc, 1) = 2.0 -> 420
        skill = dict(NORMAL003, criticalcalculate=True)
        att = role(criticalb=0.5)
        rolls = iter([0.01])
        self.assertEqual(combat.resolve_hit(att, monster(), skill,
                                            roll=lambda: next(rolls)),
                         (420, BAOJI))

    def test_roll_above_crit_chance_is_not_critical(self):
        skill = dict(NORMAL003, criticalcalculate=True)
        self.assertEqual(combat.resolve_hit(role(), monster(), skill,
                                            roll=lambda: 0.5), (210, PUTONG))

    def test_forced_crit_skips_lottery(self):
        skill = dict(NORMAL003, criticalcalculate=True)
        self.assertEqual(combat.resolve_hit(role(), monster(), skill,
                                            force='crit'), (315, BAOJI))


class TestBlock(unittest.TestCase):
    def test_block_halves_harm(self):
        self.assertEqual(combat.resolve_hit(role(), monster(), NORMAL003,
                                            force='bihu'), (105, BIHU))

    def test_block_after_critical_gives_baojibihu(self):
        # crit 210 * 1.5 = 315, then block halves to 157 (int), type BAOJIBIHU
        skill = dict(NORMAL003, criticalcalculate=True)
        rolls = iter([0.01, 0.0])  # crit roll 0.01 < 0.05; block roll 0 -> nextInt 0 <= 500
        tgt = monster(gedang=0.5)
        self.assertEqual(combat.resolve_hit(role(), tgt, skill,
                                            roll=lambda: next(rolls)),
                         (157, BAOJIBIHU))

    def test_block_roll_uses_int_thousand_scale(self):
        # Lottery.roll(0.05, THOUSAND): nextInt(1000) <= (int)(50.0) -> 0..50 succeed
        tgt = monster(gedang=0.05)
        self.assertEqual(combat.resolve_hit(role(), tgt, NORMAL003,
                                            roll=lambda: 0.05)[1], BIHU)
        self.assertEqual(combat.resolve_hit(role(), tgt, NORMAL003,
                                            roll=lambda: 0.052)[1], PUTONG)

    def test_block_needs_positive_odds(self):
        self.assertEqual(combat.resolve_hit(role(), monster(gedang=0.0), NORMAL003,
                                            roll=no_roll)[1], PUTONG)


class TestRealRecordBasicAttack(unittest.TestCase):
    """normal003 (level 1, JiNengBiao.jat) against GuaiWuBiao D000006, end to end.

    Source records (loaded from the server config, not hard-coded here):
      skill normal003 lvl1: formulea 0.8, formuleb 10, formuleg 0.75, formulec '' (no
        putong scale), formuleh '' (unused by putong), voltcalculate 1,
        criticalcalculate 1, damageformule T21.
      monster D000006: level 5, hitpoints 200, physicdamage 52, physicdefence 0,
        critical 21, volt 21. No elemental or gedang/poji fields in the record.
    Player state is a CONTROLLED FIXTURE, not a reconstructed original character:
      wuli 60, level 5, baoji 21, shanbi 21, all effect/elemental/buff values 0.
    Expected values are computed by hand in the comments below.
    """

    NAMES = {0: 'PUTONG', 1: 'SHANBI', 2: 'BAOJI', 9: 'BIHU', 10: 'BAOJIBIHU'}

    @classmethod
    def setUpClass(cls):
        from game.config import GameConfig
        cfg = GameConfig()
        cls.skill = cfg.skill_row('normal003')
        cls.monster = cfg.monster_template('D000006')

    def test_loaded_records_match_the_verified_source_values(self):
        s, m = self.skill, self.monster
        self.assertEqual(s['damageformule'], 'T21')
        self.assertEqual(float(s['formulea']), 0.8)
        self.assertEqual(int(s['formuleb']), 10)
        self.assertEqual(float(s['formuleg']), 0.75)
        self.assertEqual(s['formulec'], '')
        self.assertEqual(int(s['voltcalculate']), 1)
        self.assertEqual(int(s['criticalcalculate']), 1)
        self.assertEqual(int(m['level']), 5)
        self.assertEqual(int(m['hitpoints']), 200)
        self.assertEqual(int(m['physicdamage']), 52)
        self.assertEqual(int(m['physicdefence']), 0)
        self.assertEqual(int(m['critical']), 21)
        self.assertEqual(int(m['volt']), 21)

    def fighters(self):
        m = self.monster
        attacker = {'wuli': 60.0, 'fangyu': 0.0, 'baoji': 21.0, 'shanbi': 21.0,
                    'level': 5, 'max_hp': 0.0, 'is_role': True, 'is_monster': False}
        target = {'wuli': float(m['physicdamage']), 'fangyu': float(m['physicdefence']),
                  'baoji': float(m['critical']), 'shanbi': float(m['volt']),
                  'level': int(m['level']), 'max_hp': float(m['hitpoints']),
                  'is_role': False, 'is_monster': True}
        return attacker, target

    def skill_for_test(self):
        # Real row values; the attack selects its own lotteries through roll().
        return self.skill

    def swing(self, roll, monster_hp=200.0):
        attacker, target = self.fighters()
        harm_val, harm_type = combat.resolve_hit(attacker, target, self.skill_for_test(),
                                                 roll=roll)
        mon = {'id': 'D000006', 'cur_hp': monster_hp}
        from game.harm import accept_harm
        accept_harm(mon, self.NAMES[harm_type], harm_val)
        return harm_val, harm_type, mon['cur_hp']

    def test_normal_hit_damage_and_hp(self):
        # Lotteries: miss chance = 21/42 * 5/10 * 0.5 = 0.125 -> roll 0.5 hits.
        #            crit chance = 21/42 * 5/10 * 0.7 = 0.175 -> roll 0.5 no crit.
        # Block: gedang absent (0) -> no draw.
        # Skill: 0.8 * max(60 - 0, 0) + 10 + 0 = 58; multiplier 1 -> 58.
        # Monster HP 200 - 58 = 142.
        self.assertEqual(self.swing(lambda: 0.5), (58, combat.HARM_PUTONG, 142.0))

    def test_miss_leaves_hp_unchanged(self):
        # roll 0.05 < miss chance 0.125 -> miss -> SHANBI with value 0.
        self.assertEqual(self.swing(lambda: 0.05), (0, combat.HARM_SHANBI, 200.0))

    def test_critical_multiplier_and_hp(self):
        # Miss roll 0.5 hits; crit roll 0.01 < 0.175 -> crit.
        # 58 * max(1.5 + 0 + 0 - 0 - 0, 1) = 87; HP 200 - 87 = 113.
        rolls = iter([0.5, 0.01])
        self.assertEqual(self.swing(lambda: next(rolls)),
                         (87, combat.HARM_BAOJI, 113.0))


class TestUnsupported(unittest.TestCase):
    def test_non_t21_formula_is_rejected(self):
        with self.assertRaises(ValueError):
            combat.resolve_hit(role(), monster(), dict(NORMAL003, damageformule='T7'),
                               force='hit')


if __name__ == '__main__':
    unittest.main()

"""Isolated public cooldowns (game/cooldown.py), from PublicCdManager and Skill bytecode.

Uses explicit clock values, never sleeps. Expected dynamic values are the
float32 results of the JVM expression (int)((float)cdTime / (1f + g/2000f)).
"""
import os
import unittest

from game.cooldown import PublicCooldowns, SkillCooldowns, dynamic_cd, f32


class TestRegistrationAndExpiry(unittest.TestCase):
    def test_unknown_or_blank_name_has_no_cooldown(self):
        cd = PublicCooldowns()
        self.assertEqual(cd.remain_cd('nope', 1000), 0)
        self.assertEqual(cd.remain_cd('', 1000), 0)
        self.assertEqual(cd.remain_cd(None, 1000), 0)
        self.assertEqual(cd.get_cd('nope', 1000), 0)

    def test_registration_stores_absolute_expiry(self):
        cd = PublicCooldowns()
        cd.to_cd('t050', 500, now_ms=10000)
        self.assertEqual(cd.remain_cd('t050', 10000), 500)

    def test_remaining_before_expiry(self):
        cd = PublicCooldowns()
        cd.to_cd('t050', 500, now_ms=10000)
        self.assertEqual(cd.remain_cd('t050', 10499), 1)
        self.assertEqual(cd.get_cd('t050', 10499), 1)

    def test_exact_expiry_boundary_is_zero_remaining(self):
        cd = PublicCooldowns()
        cd.to_cd('t050', 500, now_ms=10000)
        self.assertEqual(cd.remain_cd('t050', 10500), 0)
        self.assertEqual(cd.get_cd('t050', 10500), 0)

    def test_after_expiry_remain_is_negative_but_get_is_zero(self):
        cd = PublicCooldowns()
        cd.to_cd('t050', 500, now_ms=10000)
        self.assertEqual(cd.remain_cd('t050', 10600), -100)
        self.assertEqual(cd.get_cd('t050', 10600), 0)

    def test_reregistering_overwrites_expiry(self):
        cd = PublicCooldowns()
        cd.to_cd('t050', 500, now_ms=10000)
        cd.to_cd('t050', 200, now_ms=10300)
        self.assertEqual(cd.remain_cd('t050', 10300), 200)

    def test_independent_names(self):
        cd = PublicCooldowns()
        cd.to_cd('a', 1000, now_ms=0)
        cd.to_cd('b', 100, now_ms=0)
        self.assertEqual(cd.remain_cd('a', 500), 500)
        self.assertEqual(cd.remain_cd('b', 500), -400)
        self.assertEqual(cd.remain_cd('c', 500), 0)


class TestDynamicCooldown(unittest.TestCase):
    def test_golden_captured_value(self):
        # CdBiao t070 = 700 with live attack speed 147.4 -> 651 (captured 42005).
        self.assertEqual(dynamic_cd(700, 147.4), 651)

    def test_zero_speed_is_base_cdtime(self):
        self.assertEqual(dynamic_cd(700, 0), 700)

    def test_float32_differs_from_float64_at_truncation_boundary(self):
        # Found by sweep: float32 (Java) and float64 disagree here.
        self.assertEqual(dynamic_cd(18, 400.0), 14)
        self.assertEqual(int(18.0 / (1.0 + 400.0 / 2000.0)), 15)

    def test_truncates_toward_zero(self):
        self.assertEqual(dynamic_cd(27, 160.0), 24)
        self.assertEqual(dynamic_cd(28, 240.0), 25)

    def test_f32_rounds_to_single_precision(self):
        self.assertEqual(f32(0.1), 0.10000000149011612)
        self.assertEqual(f32(16777217), 16777216.0)

    def test_dynamic_registration_stores_computed_value(self):
        cd = PublicCooldowns()
        value = cd.dynamic_to_cd('t070', 700, 147.4, now_ms=5000)
        self.assertEqual(value, 651)
        self.assertEqual(cd.remain_cd('t070', 5000), 651)

    def test_dynamic_with_blank_or_missing_stores_nothing(self):
        cd = PublicCooldowns()
        self.assertEqual(cd.dynamic_to_cd('', 700, 0, now_ms=0), 0)
        self.assertEqual(cd.dynamic_to_cd('t070', None, 0, now_ms=0), 0)
        self.assertEqual(cd.remain_cd('t070', 0), 0)


class TestSkillCooldowns(unittest.TestCase):
    def test_remaining_is_max_of_both_types(self):
        mgr = PublicCooldowns()
        skill = SkillCooldowns(mgr, 'cdA', 'cdB')
        mgr.to_cd('cdA', 300, now_ms=0)
        mgr.to_cd('cdB', 800, now_ms=0)
        self.assertEqual(skill.remain_cd(0), 800)
        self.assertEqual(skill.remain_cd(900), -100)

    def test_to_cd_uses_dynamic_for_type1_and_static_for_type2(self):
        mgr = PublicCooldowns()
        skill = SkillCooldowns(mgr, 'cdA', 'cdB')
        skill.to_cd(cdtime1=700, cdtime2=900, gongjisudu=147.4, now_ms=1000)
        self.assertEqual(mgr.remain_cd('cdA', 1000), 651)
        self.assertEqual(mgr.remain_cd('cdB', 1000), 900)

    def test_missing_second_type_is_skipped(self):
        mgr = PublicCooldowns()
        skill = SkillCooldowns(mgr, 'cdA', None)
        skill.to_cd(cdtime1=700, cdtime2=None, gongjisudu=0, now_ms=0)
        self.assertEqual(mgr.remain_cd('cdA', 0), 700)
        self.assertEqual(skill.remain_cd(0), 700)


class TestRealConfig(unittest.TestCase):
    def test_real_cdbiao_and_skill_cd_names(self):
        from game.config import load_cd_table, load_jineng_table
        base = os.path.join(os.path.dirname(__file__), '..', '..', 'reference',
                            'TonNgoKhong', 'server', 'config', 'game', 'sys_config')
        cd_path = os.path.join(base, 'CdBiao.jat')
        skill_path = os.path.join(base, 'JiNengBiao.jat')
        if not (os.path.isfile(cd_path) and os.path.isfile(skill_path)):
            self.skipTest('config tables not present')
        cdtable = load_cd_table(cd_path)
        self.assertEqual(cdtable.get('t070'), 700)
        rows = [r for r in load_jineng_table(skill_path) if r.get('cd1') in cdtable]
        self.assertTrue(rows)
        name = rows[0]['cd1']
        cdtime = cdtable[name]
        mgr = PublicCooldowns()
        self.assertEqual(mgr.dynamic_to_cd(name, cdtime, 0, now_ms=0), cdtime)


if __name__ == '__main__':
    unittest.main()

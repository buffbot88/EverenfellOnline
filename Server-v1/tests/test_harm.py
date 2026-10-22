"""Isolated HP change (game/harm.py), from SkillProcessHelper.acceptHarm and HarmType."""
import unittest

from game.harm import accept_harm, is_healing


def fighter(cur_hp=100.0):
    return {'id': 'm1', 'cur_hp': float(cur_hp)}


class TestHealingClassification(unittest.TestCase):
    def test_only_zhiliao_types_heal(self):
        self.assertTrue(is_healing('ZHILIAO'))
        self.assertTrue(is_healing('ZHILIAOBAOJI'))

    def test_other_types_do_not_heal(self):
        for t in ('PUTONG', 'BAOJI', 'SHANBI', 'GEDANG', 'FANSHAN', 'POJI', 'BIHU', 'DIDANG', None):
            self.assertFalse(is_healing(t), t)


class TestAcceptHarm(unittest.TestCase):
    def test_damage_subtracts_value(self):
        f = fighter(100)
        change = accept_harm(f, 'PUTONG', 30)
        self.assertEqual(f['cur_hp'], 70.0)
        self.assertEqual(change, {'fighter': 'm1', 'cur_hp': 70.0})

    def test_healing_adds_value(self):
        f = fighter(50)
        accept_harm(f, 'ZHILIAO', 25)
        self.assertEqual(f['cur_hp'], 75.0)

    def test_zero_or_negative_value_is_no_op(self):
        f = fighter(50)
        self.assertIsNone(accept_harm(f, 'PUTONG', 0))
        self.assertIsNone(accept_harm(f, 'PUTONG', -5))
        self.assertIsNone(accept_harm(f, 'ZHILIAO', None))
        self.assertEqual(f['cur_hp'], 50.0)

    def test_no_clamp_at_zero(self):
        # acceptHarm does not clamp; death is decided elsewhere.
        f = fighter(5)
        accept_harm(f, 'PUTONG', 10)
        self.assertEqual(f['cur_hp'], -5.0)

    def test_float32_rounding_differs_from_float64(self):
        # float32(16777217) == 16777216, so the result is 16777215 in Java.
        f = fighter(16777217)
        accept_harm(f, 'PUTONG', 1)
        self.assertEqual(f['cur_hp'], 16777215.0)
        self.assertNotEqual(16777217.0 - 1, f['cur_hp'])

    def test_no_change_when_val_is_nonpositive_even_for_healing(self):
        f = fighter(40)
        self.assertIsNone(accept_harm(f, 'ZHILIAOBAOJI', 0))
        self.assertEqual(f['cur_hp'], 40.0)


if __name__ == '__main__':
    unittest.main()

"""Isolated skill resource consumption (game/consume.py), from ConsumeCalRule* bytecode.

Expected values follow the JVM float32 formulas, not Python float64.
"""
import unittest

from game.consume import (
    CONSUME_TYPE_EMPTY,
    CONSUME_TYPE_MP,
    CONSUME_TYPE_MP_PERCENT,
    CONSUME_TYPE_TILI,
    consume,
    is_satisfied,
    special_effect_mp,
)


def fighter(cur_mp=100.0, max_mp=200.0, tili=50):
    return {'cur_mp': float(cur_mp), 'max_mp': float(max_mp), 'tili': int(tili)}


def skill(consume1):
    return {'config': {'consume1': consume1}}


class TestConstants(unittest.TestCase):
    def test_type_values_match_skillconsumes(self):
        self.assertEqual(CONSUME_TYPE_EMPTY, 0)
        self.assertEqual(CONSUME_TYPE_MP, 1)
        self.assertEqual(CONSUME_TYPE_TILI, 2)
        self.assertEqual(CONSUME_TYPE_MP_PERCENT, 4)


class TestMpCheck(unittest.TestCase):
    def test_sufficient_mp(self):
        self.assertTrue(is_satisfied(CONSUME_TYPE_MP, fighter(cur_mp=100), skill(60)))

    def test_insufficient_mp(self):
        self.assertFalse(is_satisfied(CONSUME_TYPE_MP, fighter(cur_mp=59), skill(60)))

    def test_exact_mp_boundary_passes(self):
        self.assertTrue(is_satisfied(CONSUME_TYPE_MP, fighter(cur_mp=60), skill(60)))

    def test_zero_cost_always_passes(self):
        self.assertTrue(is_satisfied(CONSUME_TYPE_MP, fighter(cur_mp=0), skill(0)))


class TestMpPercentCheck(unittest.TestCase):
    def test_threshold_is_max_mp_times_fraction(self):
        # 200 max * 0.25 = 50 required.
        self.assertTrue(is_satisfied(CONSUME_TYPE_MP_PERCENT, fighter(cur_mp=50, max_mp=200), skill(0.25)))
        self.assertFalse(is_satisfied(CONSUME_TYPE_MP_PERCENT, fighter(cur_mp=49.99, max_mp=200), skill(0.25)))


class TestTiLiCheck(unittest.TestCase):
    def test_tili_compares_truncated_cost(self):
        # Java: tiLi >= (int) consume1; 2.9 -> 2.
        self.assertTrue(is_satisfied(CONSUME_TYPE_TILI, fighter(tili=2), skill(2.9)))
        self.assertFalse(is_satisfied(CONSUME_TYPE_TILI, fighter(tili=1), skill(2.9)))


class TestEmpty(unittest.TestCase):
    def test_empty_is_always_satisfied_and_consumes_nothing(self):
        f = fighter(cur_mp=0, tili=0)
        self.assertTrue(is_satisfied(CONSUME_TYPE_EMPTY, f, skill(999)))
        self.assertFalse(consume(CONSUME_TYPE_EMPTY, f, skill(999)))
        self.assertEqual(f, fighter(cur_mp=0, tili=0))


class TestFlatMpDeduction(unittest.TestCase):
    def test_flat_deduction(self):
        f = fighter(cur_mp=100)
        self.assertTrue(consume(CONSUME_TYPE_MP, f, skill(30)))
        self.assertEqual(f['cur_mp'], 70.0)

    def test_exact_balance_goes_to_zero(self):
        f = fighter(cur_mp=60)
        consume(CONSUME_TYPE_MP, f, skill(60))
        self.assertEqual(f['cur_mp'], 0.0)

    def test_clamps_at_zero_not_negative(self):
        f = fighter(cur_mp=10)
        consume(CONSUME_TYPE_MP, f, skill(60))
        self.assertEqual(f['cur_mp'], 0.0)

    def test_repeated_consumption_accumulates(self):
        f = fighter(cur_mp=100)
        consume(CONSUME_TYPE_MP, f, skill(30))
        consume(CONSUME_TYPE_MP, f, skill(30))
        self.assertEqual(f['cur_mp'], 40.0)

    def test_zero_cost_is_no_state_change(self):
        f = fighter(cur_mp=100)
        self.assertFalse(consume(CONSUME_TYPE_MP, f, skill(0)))
        self.assertEqual(f['cur_mp'], 100.0)


class TestPercentMpDeduction(unittest.TestCase):
    def test_deducts_max_mp_fraction(self):
        f = fighter(cur_mp=200, max_mp=200)
        consume(CONSUME_TYPE_MP_PERCENT, f, skill(0.25))
        self.assertEqual(f['cur_mp'], 150.0)

    def test_percent_clamps_at_zero(self):
        f = fighter(cur_mp=10, max_mp=200)
        consume(CONSUME_TYPE_MP_PERCENT, f, skill(0.5))
        self.assertEqual(f['cur_mp'], 0.0)


class TestFloat32Arithmetic(unittest.TestCase):
    def test_float32_cost_differs_from_float64(self):
        # 0.1 is not exact in float32; cur_mp - 200*0.1 must match float32 rounding.
        from game.cooldown import f32
        f = fighter(cur_mp=20.0, max_mp=200.0)
        consume(CONSUME_TYPE_MP_PERCENT, f, skill(0.1))
        expected = f32(f32(20.0) - f32(f32(200.0) * f32(0.1)))
        self.assertEqual(f['cur_mp'], max(expected, 0.0))

    def test_special_effect_no_op_when_both_zero(self):
        f = fighter(cur_mp=77)
        self.assertIsNone(special_effect_mp(f, 0.0, 0.0))
        self.assertEqual(f['cur_mp'], 77.0)


class TestTiLiDeduction(unittest.TestCase):
    def test_decrement_truncates_cost(self):
        f = fighter(tili=50)
        consume(CONSUME_TYPE_TILI, f, skill(2.9))
        self.assertEqual(f['tili'], 48)

    def test_clamps_at_zero(self):
        f = fighter(tili=1)
        consume(CONSUME_TYPE_TILI, f, skill(5))
        self.assertEqual(f['tili'], 0)


class TestBroadcastAndFailure(unittest.TestCase):
    def test_attribute_change_called_once_on_mp_change(self):
        seen = []
        f = fighter(cur_mp=100)
        consume(CONSUME_TYPE_MP, f, skill(30), on_attribute_change=lambda x: seen.append(x['cur_mp']))
        self.assertEqual(seen, [70.0])

    def test_no_attribute_change_on_zero_cost(self):
        seen = []
        f = fighter(cur_mp=100)
        consume(CONSUME_TYPE_MP, f, skill(0), on_attribute_change=lambda x: seen.append(x))
        self.assertEqual(seen, [])

    def test_failed_check_leaves_state_unchanged(self):
        f = fighter(cur_mp=10, tili=1)
        before = dict(f)
        self.assertFalse(is_satisfied(CONSUME_TYPE_MP, f, skill(60)))
        self.assertFalse(is_satisfied(CONSUME_TYPE_TILI, f, skill(5)))
        self.assertEqual(f, before)


if __name__ == '__main__':
    unittest.main()

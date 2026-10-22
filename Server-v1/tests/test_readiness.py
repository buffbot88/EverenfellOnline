"""Isolated skill readiness (game/readiness.py), from SkillManager bytecode.

Covers: missing casttime -> 0 (ConvertObjectUtil.object2int), wave default from
jinengboshu (SkillConfigExportServiceImpl), category-keyed storage and
replacement (setReadyForFire), elapsed-time readiness (isReadyForFire), the
lasting-skill exception, and that querying readiness mutates nothing.
Uses an explicit clock value, never sleeps.
"""
import unittest

from game.readiness import SkillReadiness, is_lasting, object2int, wave_num


def skill(sid, category, casttime=None, jinengboshu=None, skillnum=None):
    cfg = {'casttime': casttime, 'jinengboshu': jinengboshu, 'skillnum': skillnum}
    return {'id': sid, 'category': category, 'config': cfg}


class TestObject2Int(unittest.TestCase):
    def test_missing_null_blank_are_zero(self):
        for v in (None, '', '   '):
            self.assertEqual(object2int(v), 0, repr(v))

    def test_numeric_and_text(self):
        self.assertEqual(object2int(200), 200)
        self.assertEqual(object2int('300'), 300)
        self.assertEqual(object2int('12.9'), 12)
        self.assertEqual(object2int('true'), 1)
        self.assertEqual(object2int('false'), 0)

    def test_unparseable_is_zero(self):
        self.assertEqual(object2int('abc'), 0)


class TestWaveCheck(unittest.TestCase):
    def test_no_entry_is_false(self):
        r = SkillReadiness()
        self.assertFalse(r.wave_check(skill('x', 'catA', jinengboshu=3)))

    def test_consumes_one_wave_per_check(self):
        r = SkillReadiness()
        s = skill('x', 'catA', jinengboshu=3)
        r.set_ready(s, 0)
        self.assertTrue(r.wave_check(s))
        self.assertEqual(r.get('catA').remain_wave_num, 2)
        self.assertTrue(r.wave_check(s))
        self.assertTrue(r.wave_check(s))
        self.assertEqual(r.get('catA').remain_wave_num, 0)

    def test_entry_survives_final_success_and_is_removed_on_next_attempt(self):
        # Java skillWaveCheck: ifle 58 jumps to removal only when remainWaveNum <= 0.
        r = SkillReadiness()
        s = skill('x', 'catA', jinengboshu=3)
        r.set_ready(s, 0)
        self.assertTrue(r.wave_check(s))
        self.assertTrue(r.wave_check(s))
        self.assertTrue(r.wave_check(s))
        # Third success leaves the entry in place at zero waves.
        self.assertIsNotNone(r.get('catA'))
        self.assertEqual(r.get('catA').remain_wave_num, 0)
        self.assertTrue(r.is_ready(s, 0))
        # Fourth attempt finds zero, removes the entry, and fails.
        self.assertFalse(r.wave_check(s))
        self.assertIsNone(r.get('catA'))
        self.assertFalse(r.is_ready(s, 0))

    def test_exhausted_entry_is_removed_and_false(self):
        r = SkillReadiness()
        s = skill('x', 'catA', jinengboshu=1)
        r.set_ready(s, 0)
        self.assertTrue(r.wave_check(s))
        self.assertFalse(r.wave_check(s))
        self.assertIsNone(r.get('catA'))
        self.assertFalse(r.is_ready(s, 10**9))

    def test_default_wave_of_one_when_column_blank(self):
        r = SkillReadiness()
        s = skill('x', 'catA', jinengboshu=None)
        r.set_ready(s, 0)
        self.assertTrue(r.wave_check(s))
        self.assertFalse(r.wave_check(s))

    def test_other_category_untouched(self):
        r = SkillReadiness()
        a = skill('a', 'catA', jinengboshu=1)
        b = skill('b', 'catB', jinengboshu=5)
        r.set_ready(a, 0)
        r.set_ready(b, 0)
        r.wave_check(a)
        r.wave_check(a)
        self.assertEqual(r.get('catB').remain_wave_num, 5)


class TestWaveDefault(unittest.TestCase):
    def test_positive_kept_else_one(self):
        self.assertEqual(wave_num(3), 3)
        self.assertEqual(wave_num(0), 1)
        self.assertEqual(wave_num(-2), 1)
        self.assertEqual(wave_num(None), 1)


class TestReadiness(unittest.TestCase):
    def test_no_entry_is_not_ready(self):
        r = SkillReadiness()
        self.assertFalse(r.is_ready(skill('gj0003', 'normal003'), 1000))

    def test_missing_casttime_is_immediately_ready_after_prepare(self):
        r = SkillReadiness()
        s = skill('gj0003', 'normal003')
        r.set_ready(s, 5000)
        self.assertTrue(r.is_ready(s, 5000))

    def test_positive_casttime_blocks_then_releases(self):
        r = SkillReadiness()
        s = skill('x1', 'catA', casttime=800)
        r.set_ready(s, 10000)
        self.assertFalse(r.is_ready(s, 10799))
        self.assertTrue(r.is_ready(s, 10800))

    def test_replacing_category_entry_resets_time(self):
        r = SkillReadiness()
        s = skill('x1', 'catA', casttime=500)
        r.set_ready(s, 1000)
        r.set_ready(s, 4000)
        self.assertFalse(r.is_ready(s, 4499))
        self.assertTrue(r.is_ready(s, 4500))
        self.assertEqual(r.get('catA').fire_time_ms, 4000)

    def test_categories_are_independent(self):
        r = SkillReadiness()
        a = skill('a', 'catA', casttime=0)
        b = skill('b', 'catB', casttime=0)
        r.set_ready(a, 100)
        self.assertTrue(r.is_ready(a, 100))
        self.assertFalse(r.is_ready(b, 100))

    def test_lasting_skill_is_always_ready(self):
        r = SkillReadiness()
        s = skill('lz', 'catL', casttime=99999, skillnum=2)
        r.set_ready(s, 0)
        self.assertTrue(r.is_ready(s, 1))

    def test_lasting_is_skillnum_above_one(self):
        self.assertFalse(is_lasting({'skillnum': None}))
        self.assertFalse(is_lasting({'skillnum': ''}))
        self.assertFalse(is_lasting({'skillnum': '1'}))
        self.assertTrue(is_lasting({'skillnum': '2'}))
        self.assertTrue(is_lasting({'skillnum': 6}))

    def test_lasting_exemption_is_per_instance_not_category(self):
        r = SkillReadiness()
        lasting = skill('L1', 'catX', casttime=99999, skillnum=2)
        same_cat = skill('N1', 'catX', casttime=99999)
        r.set_ready(lasting, 0)
        # Same category, not the lasting instance: must still wait for casttime.
        self.assertFalse(r.is_ready(same_cat, 1))
        self.assertTrue(r.is_ready(lasting, 1))

    def test_real_table_record_lasting_and_casttime(self):
        from game.config import load_jineng_table
        import os
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'reference',
                            'TonNgoKhong', 'server', 'config', 'game',
                            'sys_config', 'JiNengBiao.jat')
        if not os.path.isfile(path):
            self.skipTest('JiNengBiao.jat not present')
        rows = load_jineng_table(path)
        normal = next(r for r in rows if r.get('skilltype') == 'normal003')
        self.assertFalse(is_lasting(normal))
        self.assertEqual(object2int(normal.get('casttime')), 0)
        lasting_rows = [r for r in rows if object2int(r.get('skillnum')) > 1]
        self.assertTrue(lasting_rows)
        self.assertTrue(all(is_lasting(r) for r in lasting_rows))

    def test_status_stores_wave_and_ms_time(self):
        r = SkillReadiness()
        s = skill('x1', 'catA', jinengboshu=4)
        st = r.set_ready(s, 1234)
        self.assertEqual(st.fire_time_ms, 1234)
        self.assertEqual(st.remain_wave_num, 4)
        self.assertEqual(st.category, 'catA')

    def test_querying_does_not_mutate(self):
        r = SkillReadiness()
        s = skill('x1', 'catA', casttime=300)
        st = r.set_ready(s, 0)
        before = (st.fire_time_ms, st.remain_wave_num, dict(r._by_category), r._lasting)
        r.is_ready(s, 10)
        r.is_ready(s, 999)
        self.assertEqual((st.fire_time_ms, st.remain_wave_num, dict(r._by_category), r._lasting), before)


if __name__ == '__main__':
    unittest.main()

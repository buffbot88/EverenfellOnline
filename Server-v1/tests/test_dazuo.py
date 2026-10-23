"""Meditation goldens: 44001 solo, 44002 pairing across sessions, 44003 exit, 44004 timer.

Oracle: RoleBehaviourServiceImpl.dazuoSingle/dazuoBoth/daZuoExit/dazuoTimingDazuoGet
and StageErrorCode (DAZUO_FIGHT_NO 440001, DA_ZUO_ROLE 440002), from
dntg_start.jar via tools/javap.py. Gain table: sys_config/DaZuoPeiZhiBiao.jat.
"""
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import amf3  # noqa: E402
from game.amf3 import Obj  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402


def dazuo_config(root):
    path = os.path.join(root, 'sys_config', 'DaZuoPeiZhiBiao.jat')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(amf3.encode([
            Obj(level=1, exp1=30, exp2=36, exp3=43, exp4=51,
                zhenqi1=0, zhenqi2=0, zhenqi3=0, zhenqi4=0),
            Obj(level=2, exp1=40, exp2=50, exp3=60, exp4=70,
                zhenqi1=1, zhenqi2=2, zhenqi3=3, zhenqi4=4)]))
    return GameConfig(root)


def decode(frames):
    return [amf3.decode(f[4:]) for f in frames]


class GainTableTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.cfg = dazuo_config(d)

    def test_gain_by_level_and_flag_sum(self):
        self.assertEqual(self.cfg.dazuo_gain(1, 1), (30, 0))
        self.assertEqual(self.cfg.dazuo_gain(2, 2), (50, 2))
        self.assertEqual(self.cfg.dazuo_gain('2', 4), (70, 4))

    def test_unlisted_level_or_flag_is_none(self):
        self.assertIsNone(self.cfg.dazuo_gain(99, 1))
        self.assertIsNone(self.cfg.dazuo_gain(1, 5))


class MeditationTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.cfg = dazuo_config(d)
        self.reg = StageRegistry()
        self.saved = []

    def session(self, conn_id, role_id, x=1, y=3, level=1, exp=0):
        role = {'id': role_id, 'map_id': '7', 'map_x': x, 'map_y': y,
                'level': level, 'exp': exp, 'zhenqi': 0}
        sess = Session(conn_id=conn_id, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [role], server_start_ms=0,
                       save_role_state=lambda rid, **kw: self.saved.append(
                           (rid, kw)) or True,
                       config=self.cfg, stage_registry=self.reg)
        self.reg.register(str(role_id), '7', sess, x=x, y=y)
        return sess

    def test_solo_start_broadcasts_to_self_and_arms_timer(self):
        a = self.session(1, 1)
        out = a.dazuo_single([44001, '1'])
        self.assertEqual(decode([out[0]]), [['44001', [1, '1']]])
        self.assertTrue(a._dazuo['1']['daZuo'])
        self.assertIsNone(a._dazuo['1']['target'])
        self.assertIn('timing_dazuo_get:1', a.stage_scheduler.pending())

    def test_solo_start_while_fighting_is_refused(self):
        a = self.session(1, 1)
        a._hatred = {'m_7_0': '1'}
        out = a.dazuo_single([44001, '1'])
        self.assertEqual(decode([out]), [['44001', [0, 440001]]])
        self.assertFalse(a._dazuo.get('1', {}).get('daZuo', False))

    def test_pair_across_sessions_links_both_roles(self):
        a = self.session(1, 1)
        b = self.session(2, 2, x=2)
        a.dazuo_single([44001, '1'])
        b.dazuo_single([44001, '2'])
        self.assertIsNone(a.dazuo_both([44002, ['1', '2']]))
        b.tick(now_ms=0)   # target accepts on its tick
        a_out = a.tick(now_ms=0)  # requester links and broadcasts
        self.assertEqual(a._dazuo['1']['target'], '2')
        self.assertEqual(b._dazuo['2']['target'], '1')
        self.assertIn(['44002', [1, '1', '2']], decode(a_out))
        self.assertIn(['44002', [1, '1', '2']], decode(b.tick(now_ms=0)))

    def test_pairing_with_a_paired_target_is_refused(self):
        a = self.session(1, 1)
        b = self.session(2, 2, x=2)
        c = self.session(3, 3, x=3)
        for s, rid in ((a, '1'), (b, '2'), (c, '3')):
            s.dazuo_single([44001, rid])
        a.dazuo_both([44002, ['1', '2']])
        b.tick(now_ms=0)
        a.tick(now_ms=0)
        self.assertIsNone(c.dazuo_both([44002, ['3', '1']]))
        a.tick(now_ms=0)  # target 1 already paired on its side
        out = c.tick(now_ms=0)
        self.assertIn(['44002', [0, 440002]], decode(out))
        self.assertIsNone(c._dazuo['3']['target'])

    def test_pairing_with_offline_target_errors_at_once(self):
        a = self.session(1, 1)
        a.dazuo_single([44001, '1'])
        out = a.dazuo_both([44002, ['1', 'ghost']])
        self.assertEqual(decode([out]), [['44002', [0, 440002]]])

    def test_exit_clears_self_unlinks_partner_and_cancels_timer(self):
        a = self.session(1, 1)
        b = self.session(2, 2, x=2)
        a.dazuo_single([44001, '1'])
        b.dazuo_single([44001, '2'])
        a.dazuo_both([44002, ['1', '2']])
        b.tick(now_ms=0)
        a.tick(now_ms=0)
        out = a.dazuo_exit([44003, '1'])
        # Java daZuoExit addMsg(surround, "44003", roleId): the payload is
        # the exiting role, not null (RoleBehaviourServiceImpl bytecode).
        self.assertEqual(decode(out), [['44003', '1']])
        self.assertFalse(a._dazuo['1']['daZuo'])
        self.assertIsNone(a._dazuo['1']['target'])
        self.assertNotIn('timing_dazuo_get:1', a.stage_scheduler.pending())
        b.tick(now_ms=0)
        self.assertIsNone(b._dazuo['2']['target'])
        self.assertTrue(b._dazuo['2']['daZuo'])

    def test_timer_awards_gain_then_rearms_while_meditating(self):
        a = self.session(1, 1)
        a.dazuo_single([44001, '1'])
        start = int(time.monotonic() * 1000)
        self.assertIsNone(a.tick(now_ms=start + 1000))
        out = a.tick(now_ms=start + 15001)
        self.assertEqual(decode(out), [['44004', [30, 0]]])
        self.assertEqual(self.saved, [('1', {'exp': 30})])
        self.assertIn('timing_dazuo_get:1', a.stage_scheduler.pending())

    def test_timer_stops_after_exit(self):
        a = self.session(1, 1)
        a.dazuo_single([44001, '1'])
        a.dazuo_exit([44003, '1'])
        start = int(time.monotonic() * 1000)
        self.assertIsNone(a.tick(now_ms=start + 60000))
        self.assertEqual(self.saved, [])


if __name__ == '__main__':
    unittest.main()

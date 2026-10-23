"""Movement and combat cancel meditation (44003), like an explicit exit.

The Flash client never sends 44003 for the move itself (live capture):
tile steps (40000), pixel moves (42001), teleports (40100) and swings
(42002) cancel the meditator server-side, including the tick timer.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import amf3  # noqa: E402
from game.protocol import Session  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402
from tests.test_dazuo import dazuo_config, decode  # noqa: E402


class DazuoCancelTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.cfg = dazuo_config(d)
        self.reg = StageRegistry()

    def session(self, conn_id, role_id, x=1, y=3):
        role = {'id': role_id, 'map_id': '7', 'map_x': x, 'map_y': y,
                'level': 1, 'exp': 0, 'zhenqi': 0}
        sess = Session(conn_id=conn_id, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [role], server_start_ms=0,
                       save_role_state=lambda rid, **kw: True,
                       config=self.cfg, stage_registry=self.reg)
        self.reg.register(str(role_id), '7', sess, x=x, y=y)
        return sess, role

    def test_tile_step_cancels_meditation(self):
        s, role = self.session(1, 1)
        s.dazuo_single([44001, '1'])
        self.assertTrue(s._dazuo['1']['daZuo'])
        out = s.tile_step([40000, [2, 3, 0, 0, '1']])
        self.assertFalse(s._dazuo['1']['daZuo'])
        self.assertNotIn('timing_dazuo_get:1', s.stage_scheduler.pending())
        self.assertIn(['44003', '1'], decode(out))

    def test_pixel_move_cancels_but_keeps_echo_shape(self):
        s, _role = self.session(1, 1)
        s.dazuo_single([44001, '1'])
        out = s.skill_move([42001, ['1', 'normal003', [100, 200],
                                    [[110, 200, 0, 0, 1]], 1]])
        self.assertFalse(s._dazuo['1']['daZuo'])
        cmds = decode(out)
        self.assertEqual(cmds[0], ['44003', '1'])
        self.assertEqual(cmds[1][0], '42001')

    def test_pixel_move_without_meditation_stays_single_frame(self):
        s, _role = self.session(1, 1)
        out = s.skill_move([42001, ['1', 'normal003', [100, 200],
                                    [[110, 200, 0, 0, 1]], 1]])
        env = amf3.decode(out[4:])
        self.assertEqual(env[0], '42001')

    def test_teleport_cancels_meditation(self):
        s, _role = self.session(1, 1)
        s.dazuo_single([44001, '1'])
        out = s.teleport([40100, [9, 9, 0, '1']])
        self.assertFalse(s._dazuo['1']['daZuo'])
        self.assertIn(['44003', '1'], decode(out))


if __name__ == '__main__':
    unittest.main()

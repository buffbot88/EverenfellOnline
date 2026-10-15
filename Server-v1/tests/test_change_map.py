"""Goldens for Session.change_map (one-step SC:APPLY_CHANG_MAP).

Oracle: StageControllAction.innerChangeMap -> StageControllServiceImpl.applyChangeMap
(stages readyForPosition, replies '20000' [1, mapId, [x, y]] via send2One) and
changeMap (commit: leave the old stage, enter the new one), from dntg_start.jar via
tools/javap.py. The one-step port collapses the client-ready commit into change_map.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import amf3  # noqa: E402
from game.amf3 import Obj  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402


def make_config():
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, 'sys_config'))
    with open(os.path.join(root, 'sys_config', 'ChuShengZuoBiaoPeiZhibBiao.jat'), 'wb') as f:
        f.write(amf3.encode([Obj(map1=8, map2=9, map2target='20|22', borntype=2, id=2002)]))
    return GameConfig(root), root


def decode(frames):
    return [amf3.decode(f[4:]) for f in frames]


class ChangeMapTest(unittest.TestCase):
    def setUp(self):
        self.cfg, root = make_config()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.reg = StageRegistry()
        self.saved = []

    def session(self, conn_id, role_id, x, y, map_id):
        role = {'id': role_id, 'map_id': map_id, 'map_x': x, 'map_y': y,
                'level': 1, 'exp': 0, 'zhenqi': 0}
        sess = Session(conn_id=conn_id, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [role], server_start_ms=0,
                       config=self.cfg, stage_registry=self.reg,
                       save_role_state=lambda rid, **kw: self.saved.append((rid, kw)))
        self.reg.register(str(role_id), map_id, sess, x=x, y=y)
        return sess

    def test_change_map_returns_entry_frames_and_saves_position(self):
        a = self.session(1, 1, 1, 3, '8')
        out = decode(a.change_map('1', '9', 20, 22))
        self.assertEqual(out[0], ['20000', [1, '9', [20, 22]]])
        self.assertEqual(out[1][0], '21000')
        self.assertEqual(self.saved, [('1', {'map_id': '9', 'map_x': 20, 'map_y': 22})])

    def test_old_map_peer_stops_hearing_the_role(self):
        a = self.session(1, 1, 1, 3, '8')
        b = self.session(2, 2, 2, 3, '8')
        a.change_map('1', '9', 20, 22)
        a.area_chat([10050, ['hi']])
        self.assertIsNone(b.tick(now_ms=0))

    def test_new_map_peer_hears_the_role(self):
        a = self.session(1, 1, 1, 3, '8')
        c = self.session(3, 3, 21, 22, '9')
        a.change_map('1', '9', 20, 22)
        a.area_chat([10050, ['hi']])
        self.assertEqual(decode(c.tick(now_ms=0)), [['10050', ['1', ['hi']]]])


if __name__ == '__main__':
    unittest.main()

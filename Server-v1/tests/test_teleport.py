"""Goldens for 40100 coordinate teleport and 40201 face change.

Oracle: RoleBehaviourAction.teleport (C> data[0]/data[1] ints, data[3] role id)
-> RoleBehaviourServiceImpl.teleport(stage, roleId, x, y) (IStage.teleportTo, then
getSurroundRoleIds of the new position) -> send2Many(surround, '40100', data), and
RoleBehaviourAction.changeFaceTo -> getSurroundRoleId (empty/null -> silent) ->
send2Many(surround, '40201', data), from dntg_start.jar via tools/javap.py.
The client's exact 40201 payload is not in output/orig-stack/tap-decoded.txt, so the
face goldens echo whatever payload the client sends.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import amf3  # noqa: E402
from game.amf3 import Obj, encode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402


def make_config():
    root = tempfile.mkdtemp()
    cfg_dir = os.path.join(root, 'game')
    os.makedirs(cfg_dir)
    with open(os.path.join(root, 'localization.properties'), 'w', encoding='utf-8') as f:
        f.write('chat_level = 1\n')
    return GameConfig(cfg_dir), root


def decode(frames):
    return [amf3.decode(f[4:]) for f in frames]


class TeleportFaceTest(unittest.TestCase):
    def setUp(self):
        self.cfg, root = make_config()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.reg = StageRegistry()
        self.saved = []

    def session(self, conn_id, role_id, x=1, y=3, map_id='7'):
        role = {'id': role_id, 'map_id': map_id, 'map_x': x, 'map_y': y,
                'level': 1, 'exp': 0, 'zhenqi': 0}
        sess = Session(conn_id=conn_id, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [role], server_start_ms=0,
                       config=self.cfg, stage_registry=self.reg,
                       save_role_state=lambda rid, **kw: self.saved.append((rid, kw)))
        self.reg.register(str(role_id), map_id, sess, x=x, y=y)
        return sess

    # 40100 teleport
    def test_teleport_echoes_request_to_self_and_moves_role(self):
        a = self.session(1, 1)
        out = a.teleport([40100, [5, 6, 0, '1']])
        self.assertEqual(decode([out[0]]), [['40100', [5, 6, 0, '1']]])
        self.assertEqual(self.reg._pos['1'], (5, 6))
        self.assertEqual(self.saved, [('1', {'map_x': 5, 'map_y': 6})])

    def test_teleport_reaches_neighbour_at_new_cell(self):
        a = self.session(1, 1, x=1, y=3)
        b = self.session(2, 2, x=50, y=3)
        self.assertIsNone(b.tick(now_ms=0))
        a.teleport([40100, [50, 4, 0, '1']])
        self.assertEqual(decode(b.tick(now_ms=0)), [['40100', [50, 4, 0, '1']]])

    def test_teleport_leaves_old_surround_behind(self):
        a = self.session(1, 1, x=1, y=3)
        b = self.session(2, 2, x=2, y=3)
        a.teleport([40100, [50, 4, 0, '1']])
        self.assertIsNone(b.tick(now_ms=0))

    def test_teleport_unowned_role_is_silent(self):
        a = self.session(1, 1)
        self.assertIsNone(a.teleport([40100, [5, 6, 0, 'ghost']]))
        self.assertEqual(self.saved, [])

    def test_teleport_bad_args_are_silent(self):
        a = self.session(1, 1)
        self.assertIsNone(a.teleport([40100, [5, 6, 0]]))
        self.assertIsNone(a.teleport([40100, ['5', 6, 0, '1']]))
        self.assertIsNone(a.teleport([40100, [True, 6, 0, '1']]))
        self.assertIsNone(a.teleport([40100, None]))
        self.assertEqual(self.saved, [])

    # 40201 face change
    def test_face_echoes_payload_to_self_and_neighbour(self):
        a = self.session(1, 1, x=1, y=3)
        b = self.session(2, 2, x=2, y=3)
        out = a.change_face([40201, ['1', 2]])
        self.assertEqual(decode([out[0]]), [['40201', ['1', 2]]])
        self.assertEqual(decode(b.tick(now_ms=0)), [['40201', ['1', 2]]])

    def test_face_skips_roles_outside_surround(self):
        a = self.session(1, 1, x=1, y=3)
        b = self.session(2, 2, x=50, y=3)
        a.change_face([40201, ['1', 2]])
        self.assertIsNone(b.tick(now_ms=0))

    def test_face_without_placed_role_is_silent(self):
        sess = Session(conn_id=9, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [], server_start_ms=0,
                       config=self.cfg, stage_registry=self.reg)
        self.assertIsNone(sess.change_face([40201, ['1', 2]]))

    def test_face_without_registry_is_silent(self):
        sess = Session(conn_id=9, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [], server_start_ms=0,
                       config=self.cfg)
        self.assertIsNone(sess.change_face([40201, ['1', 2]]))


WAYPOINTS = [
    Obj(id='wp_cross', map='7', toMap='8', toX=79, toY=33, x=23,
        y=185, limit=Obj()),
    Obj(id='wp_same', map='7', toMap='7', toX=50, toY=4, x=1, y=3,
        limit=Obj()),
    Obj(id='wp_high', map='7', toMap='8', toX=79, toY=33, x=1, y=3,
        limit=Obj(minlevel=50)),
]


class WaypointTeleportTest(unittest.TestCase):
    """Goldens for 20001 waypoint portals (RoleBehaviourServiceImpl.applyWayPointTeleport).

    Oracle: dntg_start.jar javap of RoleBehaviourAction (String id payload)
    and the service (unknown id silent; dead 490011 / copy 490013 /
    min-level 490002 gate as ['20001', [0, code]]; same map stages
    teleportTo with a 40100 surround echo; other maps take the
    SC:APPLY_CHANG_MAP path). Table: ChuanSongBiao.jat wayPoint rows.
    """
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cfgdir = os.path.join(tmp.name, 'cfg')
        os.makedirs(os.path.join(cfgdir, 'sys_config'))
        with open(os.path.join(cfgdir, 'sys_config',
                               'ChuanSongBiao.jat'), 'wb') as f:
            f.write(encode(Obj(wayPoint=list(WAYPOINTS))))
        cls.cfgdir = cfgdir

    def setUp(self):
        self.cfg = GameConfig(self.cfgdir)
        self.reg = StageRegistry()
        self.saved = []

    def session(self, conn_id, role_id, x=1, y=3, map_id='7', level=1):
        role = {'id': role_id, 'map_id': map_id, 'map_x': x, 'map_y': y,
                'level': level, 'exp': 0, 'zhenqi': 0}
        sess = Session(conn_id=conn_id, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [role], server_start_ms=0,
                       config=self.cfg, stage_registry=self.reg,
                       save_role_state=lambda rid, **kw: self.saved.append((rid, kw)))
        self.reg.register(str(role_id), map_id, sess, x=x, y=y)
        return sess

    def test_cross_map_hop_changes_map(self):
        a = self.session(1, 1)
        out = a.waypoint_teleport([20001, 'wp_cross'])
        got = decode(out)
        self.assertEqual(got[0], ['20000', [1, '8', [79, 33]]])
        self.assertEqual(got[1][0], '21000')
        self.assertEqual(self.reg.map_of('1'), '8')
        self.assertEqual(self.reg._pos['1'], (79, 33))

    def test_same_map_hop_teleports_in_place(self):
        a = self.session(1, 1)
        out = a.waypoint_teleport([20001, 'wp_same'])
        self.assertEqual(decode(out), [['40100', [50, 4, 0, '1']]])
        self.assertEqual(self.reg._pos['1'], (50, 4))
        self.assertEqual(self.reg.map_of('1'), '7')

    def test_unknown_waypoint_is_silent(self):
        a = self.session(1, 1)
        self.assertIsNone(a.waypoint_teleport([20001, 'wp_nope']))
        self.assertEqual(self.reg.map_of('1'), '7')

    def test_bad_payload_is_silent(self):
        a = self.session(1, 1)
        self.assertIsNone(a.waypoint_teleport([20001, ['wp_cross']]))
        self.assertIsNone(a.waypoint_teleport([20001, None]))

    def test_dead_role_gets_error_frame(self):
        a = self.session(1, 1)
        a._dead.add('1')
        out = a.waypoint_teleport([20001, 'wp_cross'])
        self.assertEqual(decode([out]), [['20001', [0, 490011]]])
        self.assertEqual(self.reg.map_of('1'), '7')

    def test_min_level_gate(self):
        a = self.session(1, 1, level=1)
        out = a.waypoint_teleport([20001, 'wp_high'])
        self.assertEqual(decode([out]), [['20001', [0, 490002]]])
        self.assertEqual(self.reg.map_of('1'), '7')

    def test_level_gate_passes(self):
        a = self.session(1, 1, level=50)
        out = a.waypoint_teleport([20001, 'wp_high'])
        self.assertEqual(decode(out)[0], ['20000', [1, '8', [79, 33]]])


if __name__ == '__main__':
    unittest.main()

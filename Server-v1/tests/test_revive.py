"""Goldens for 43001 town revive.

Oracle: RoleFightAction.townRevive -> FightServiceImpl.townRevive, from dntg_start.jar via
tools/javap.py. A role with no DEAD state gets 43001 [roleId] to its surround. A dead
role gets resetHpMp + outputAttributeChange (12004 to itself), 43001 to the old surround,
then BornZuoBiaoConfig.loadByDead(mapId): same-map birth points teleport the role (40100
[x, y, 0, roleId] to the new surround) and 43001 goes to the new surround. Cross-map
revives need SC:APPLY_CHANG_MAP, which is not ported, so they reset in place.
The birth table is ChuShengZuoBiaoPeiZhibBiao.jat (DEAD rows: map1 -> map2 + 'x|y').
"""
import os
import random
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import amf3  # noqa: E402
from game.amf3 import Obj  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402


def make_config():
    root = tempfile.mkdtemp()
    sys_dir = os.path.join(root, 'sys_config')
    os.makedirs(sys_dir)
    rows = [
        Obj(map1='', map2=7, map2target='1|1', borntype=1, id=1001),
        Obj(map1=7, map2=7, map2target='10|12', borntype=2, id=2001),
        Obj(map1=8, map2=9, map2target='20|22', borntype=2, id=2002),
    ]
    with open(os.path.join(sys_dir, 'ChuShengZuoBiaoPeiZhibBiao.jat'), 'wb') as f:
        f.write(amf3.encode(rows))
    return GameConfig(root), root


def decode(frames):
    return [amf3.decode(f[4:]) for f in frames]


class TownReviveTest(unittest.TestCase):
    def setUp(self):
        self.cfg, root = make_config()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.reg = StageRegistry()
        self.saved = []

    def session(self, conn_id, role_id, x=1, y=3, map_id='7', hp=100, mp=50):
        role = {'id': role_id, 'map_id': map_id, 'map_x': x, 'map_y': y,
                'level': 1, 'exp': 0, 'zhenqi': 0, 'hp': hp, 'max_hp': 100,
                'mp': mp, 'max_mp': 50}
        sess = Session(conn_id=conn_id, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [role], server_start_ms=0,
                       config=self.cfg, stage_registry=self.reg,
                       save_role_state=lambda rid, **kw: self.saved.append((rid, kw)))
        self.reg.register(str(role_id), map_id, sess, x=x, y=y)
        return sess

    def test_living_role_echoes_to_surround(self):
        a = self.session(1, 1)
        out = a.town_revive([43001, None])
        self.assertEqual(decode(out), [['43001', '1']])
        self.assertEqual(self.saved, [])

    def test_dead_role_revives_at_same_map_birth_point(self):
        a = self.session(1, 1, hp=0, mp=0)
        a._dead.add('1')
        out = a.town_revive([43001, None])
        self.assertEqual(decode(out), [
            ['12004', ['1', 100, 100, 50, 50]],
            ['43001', '1'],
            ['40100', [10, 12, 0, '1']],
            ['43001', '1'],
        ])
        self.assertNotIn('1', a._dead)
        self.assertEqual(self.saved, [('1', {'hp': 100, 'mp': 50}),
                                      ('1', {'map_x': 10, 'map_y': 12})])
        self.assertEqual(self.reg._pos['1'], (10, 12))

    def test_old_surround_neighbour_sees_only_the_first_43001(self):
        a = self.session(1, 1, hp=0, mp=0)
        b = self.session(2, 2, x=2, y=3)
        a._dead.add('1')
        a.town_revive([43001, None])
        self.assertEqual(decode(b.tick(now_ms=0)), [['43001', '1'],
                                                   ['40100', [10, 12, 0, '1']],
                                                   ['43001', '1']])

    def test_neighbour_in_both_blocks_sees_all_three_frames(self):
        # (10,12) is AOI cell (2,1), next to the old cell (1,1), so c is in both 3x3 blocks.
        a = self.session(1, 1, hp=0, mp=0)
        c = self.session(3, 3, x=10, y=12)
        a._dead.add('1')
        a.town_revive([43001, None])
        self.assertEqual(decode(c.tick(now_ms=0)), [['43001', '1'],
                                                   ['40100', [10, 12, 0, '1']],
                                                   ['43001', '1']])

    def test_cross_map_revive_moves_role_to_birth_map(self):
        # Dead map 8 -> birth map 9 at (20, 22); the second 43001 still uses the old surround.
        a = self.session(1, 1, map_id='8', hp=0, mp=0)
        a._dead.add('1')
        out = decode(a.town_revive([43001, None]))
        self.assertEqual(out[:3], [['12004', ['1', 100, 100, 50, 50]],
                                   ['43001', '1'], ['43001', '1']])
        self.assertEqual(out[3], ['20000', [1, '9', [20, 22]]])
        self.assertEqual(out[4][0], '21000')
        self.assertNotIn('1', a._dead)
        self.assertEqual(self.reg._pos['1'], (20, 22))
        self.assertEqual(self.reg._where['1'], '9')
        self.assertIn(('1', {'map_id': '9', 'map_x': 20, 'map_y': 22}), self.saved)

    def test_missing_birth_config_resets_in_place(self):
        a = self.session(1, 1, map_id='5', hp=0, mp=0)
        a._dead.add('1')
        out = a.town_revive([43001, None])
        self.assertEqual(decode(out), [['12004', ['1', 100, 100, 50, 50]],
                                       ['43001', '1']])

    def test_random_birth_point_is_picked_from_points(self):
        cfg_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cfg_dir, ignore_errors=True)
        os.makedirs(os.path.join(cfg_dir, 'sys_config'))
        with open(os.path.join(cfg_dir, 'sys_config',
                               'ChuShengZuoBiaoPeiZhibBiao.jat'), 'wb') as f:
            f.write(amf3.encode([Obj(map1=7, map2=7,
                                     map2target='10|12;11|13', borntype=2,
                                     id=2001)]))
        self.cfg = GameConfig(cfg_dir)
        a = self.session(1, 1, hp=0, mp=0)
        a._dead.add('1')
        with mock.patch.object(random, 'choice', return_value=(11, 13)):
            out = a.town_revive([43001, None])
        self.assertIn(['40100', [11, 13, 0, '1']], decode(out))
        self.assertEqual(self.reg._pos['1'], (11, 13))

    def test_unplaced_sender_is_silent(self):
        sess = Session(conn_id=9, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [], server_start_ms=0,
                       config=self.cfg, stage_registry=self.reg)
        self.assertIsNone(sess.town_revive([43001, None]))

    def test_no_registry_is_silent(self):
        sess = Session(conn_id=9, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [], server_start_ms=0,
                       config=self.cfg)
        self.assertIsNone(sess.town_revive([43001, None]))


if __name__ == '__main__':
    unittest.main()

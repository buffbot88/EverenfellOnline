"""Stage offline-save sync, from the Java stage bus/stage split.

Oracle: StageControllServiceImpl.changeMap/logout plus
RoleStageServiceImpl.syncRoleStageData via javap -c on dntg_start.jar:
leaving a map and logging out fold the live element into role_stage, but
map fields persist only on MapType.usedForOfflineSave maps (NORMAL 1,
ZHUCHENG 2, from the MapType clinit); on copies and story maps the row
keeps the previous offline-save position. A dead role persists the
born-config revive roll at full HP/MP instead of the death tile.

The port keeps hp/mp/pos/pk current with incremental writes; these tests
pin the two behaviors the incremental path cannot produce: the map-field
gate and the dead-logout revive rewrite.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game.amf3 import Obj  # noqa: E402
from game import amf3  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402


def make_config():
    root = tempfile.mkdtemp()
    sys_dir = os.path.join(root, 'sys_config')
    os.makedirs(sys_dir)
    with open(os.path.join(sys_dir, 'MapLine.jat'), 'wb') as f:
        f.write(amf3.encode([
            Obj(mapid=2, maptype=1),
            Obj(mapid=7, maptype=1),
            Obj(mapid=8, maptype=3),
            Obj(mapid=91, maptype=15),
        ]))
    with open(os.path.join(sys_dir, 'ChuShengZuoBiaoPeiZhibBiao.jat'),
              'wb') as f:
        f.write(amf3.encode([
            Obj(map1=7, map2=7, map2target='30|31', borntype=2, id=2001),
            Obj(map1=91, map2=91, map2target='50|51', borntype=2,
                id=2002),
        ]))
    return GameConfig(root), root


class SharedStore:
    def __init__(self):
        self.roles = {}

    def add(self, role_id, map_id='2', x=10, y=10):
        self.roles[str(role_id)] = {
            'id': role_id, 'name': 'R%s' % role_id, 'map_id': map_id,
            'map_x': x, 'map_y': y, 'level': 40, 'exp': 0, 'zhenqi': 0,
            'hp': 500, 'max_hp': 500, 'mp': 100, 'max_mp': 100}

    def save(self, rid, **kw):
        self.roles[str(rid)].update(kw)

    def get(self, rid):
        return self.roles[str(rid)]


class StageSyncTest(unittest.TestCase):
    def setUp(self):
        self.cfg, root = make_config()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.reg = StageRegistry()
        self.store = SharedStore()
        self.store.add(1)
        self.saved = []
        self.a = self._session(1, 1)

    def _session(self, conn_id, role_id):
        roles = [self.store.get(role_id)]
        sess = Session(
            conn_id=conn_id, check_sign=lambda *a: False,
            get_roles=lambda u, s, r=roles: list(r),
            server_start_ms=0, config=self.cfg,
            stage_registry=self.reg,
            save_role_state=self._save)
        sess.authed_user, sess.server_id = 'u1', 's1'
        role = self.store.get(role_id)
        self.reg.register(str(role_id), role['map_id'], sess,
                          x=role['map_x'], y=role['map_y'])
        return sess

    def _save(self, rid, **kw):
        self.store.save(rid, **kw)
        self.saved.append((str(rid), dict(kw)))

    def map_saves(self):
        return [kw for _rid, kw in self.saved
                if 'map_id' in kw or 'map_x' in kw]

    # --- 1. The offline-save gate --------------------------------------

    def test_offline_save_map_types(self):
        self.assertTrue(self.cfg.offline_save_map('2'))
        self.assertTrue(self.cfg.offline_save_map('7'))
        self.assertFalse(self.cfg.offline_save_map('8'))
        self.assertFalse(self.cfg.offline_save_map('91'))
        self.assertTrue(self.cfg.offline_save_map('unknown-map'))

    def test_change_map_to_copy_keeps_row_map(self):
        self.a.change_map('1', '91', 5, 5)
        self.assertEqual(self.reg.map_of('1'), '91')
        self.assertEqual(self.map_saves(), [])
        self.assertEqual(self.store.get(1)['map_id'], '2')

    def test_change_map_between_save_maps_persists(self):
        self.a.change_map('1', '7', 30, 31)
        self.assertEqual(self.store.get(1)['map_id'], '7')
        self.assertEqual(
            (self.store.get(1)['map_x'], self.store.get(1)['map_y']),
            (30, 31))

    def test_step_and_teleport_in_copy_do_not_persist(self):
        self.a.change_map('1', '91', 5, 5)
        self.saved.clear()
        self.a.tile_step([40000, [6, 5, 0, 0, '1']])
        self.a.teleport([40100, [6, 6, 0, '1']])
        self.assertEqual(self.map_saves(), [])
        self.assertEqual(
            (self.store.get(1)['map_x'], self.store.get(1)['map_y']),
            (10, 10))
        self.assertEqual(self.reg.position_of('1'), (6, 6))

    def test_apply_stage_to_story_map_does_not_persist(self):
        self.a.apply_stage(['20000', ['1', '8']])
        self.assertEqual(self.reg.map_of('1'), '8')
        self.assertEqual(self.map_saves(), [])
        self.assertEqual(self.store.get(1)['map_id'], '2')

    # --- 2. Logout sync ---------------------------------------------------

    def test_logout_alive_in_copy_keeps_offline_save(self):
        self.a.change_map('1', '7', 30, 31)
        self.a.change_map('1', '91', 5, 5)
        self.a._stage_on_disconnect()
        row = self.store.get(1)
        self.assertEqual(row['map_id'], '7')
        self.assertEqual((row['map_x'], row['map_y']), (30, 31))

    def test_logout_dead_on_save_map_rewrites_revive(self):
        self.a.change_map('1', '7', 30, 31)
        self.store.save(1, hp=0, mp=0)
        self.a._dead.add('1')
        self.a._stage_on_disconnect()
        row = self.store.get(1)
        self.assertEqual(row['map_id'], '7')
        self.assertEqual((row['map_x'], row['map_y']), (30, 31))
        self.assertEqual(row['hp'], 500)
        self.assertEqual(row['mp'], 100)
        self.assertNotIn('1', self.a._dead)

    def test_logout_dead_in_copy_wakes_at_offline_save(self):
        self.a.change_map('1', '7', 30, 31)
        self.a.change_map('1', '91', 5, 5)
        self.store.save(1, hp=0, mp=0)
        self.a._dead.add('1')
        self.a._stage_on_disconnect()
        row = self.store.get(1)
        # The 91 revive point is off the save maps: the row keeps the
        # pre-copy position but carries full HP/MP.
        self.assertEqual(row['map_id'], '7')
        self.assertEqual((row['map_x'], row['map_y']), (30, 31))
        self.assertEqual(row['hp'], 500)
        self.assertNotIn('1', self.a._dead)

    def test_logout_dead_without_born_config_keeps_row(self):
        self.store.save(1, hp=0, mp=0)
        self.a._dead.add('1')
        self.a._stage_on_disconnect()
        row = self.store.get(1)
        self.assertEqual(row['map_id'], '2')
        self.assertEqual(row['hp'], 0)
        self.assertNotIn('1', self.a._dead)

    def test_relogin_returns_to_offline_save(self):
        self.a.change_map('1', '7', 30, 31)
        self.a.change_map('1', '91', 5, 5)
        self.a._stage_on_disconnect()
        b = self._session(2, 1)
        out = b.enter_world(['10003', '1'])
        result = amf3.decode(out[-1][4:])
        self.assertEqual(result[0], '10003')
        self.assertEqual(result[1][2][0], '7')


if __name__ == '__main__':
    unittest.main()

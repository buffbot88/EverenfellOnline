"""Goldens for 40101 innerFly.

Oracle: RoleBehaviourAction.innerFly (data[1] mapId, data[2]/data[3] Integer x/y,
data[4] stageId, role from Message.roleId) -> RoleBehaviourServiceImpl.innerFly
(stage.getMapId() equal: teleportTo, then send '40101' [x, y, 0, roleId] to the
surround; otherwise queue SC:APPLY_CHANG_MAP [mapId, x, y]), from dntg_start.jar via
tools/javap.py.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game import amf3  # noqa: E402
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


class InnerFlyTest(unittest.TestCase):
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

    def test_same_map_teleports_and_echoes_to_self(self):
        a = self.session(1, 1, map_id='7')
        out = a.inner_fly([40101, [None, '7', 5, 6, 'stage']])
        self.assertEqual(decode([out[0]]), [['40101', [5, 6, 0, '1']]])
        self.assertEqual(self.reg._pos['1'], (5, 6))
        self.assertEqual(self.saved, [('1', {'map_x': 5, 'map_y': 6})])

    def test_same_map_reaches_neighbour_in_new_surround(self):
        a = self.session(1, 1, x=1, y=3, map_id='7')
        b = self.session(2, 2, x=5, y=6, map_id='7')
        a.inner_fly([40101, [None, '7', 5, 6, 'stage']])
        self.assertEqual(decode(b.tick(now_ms=0)), [['40101', [5, 6, 0, '1']]])

    def test_cross_map_changes_map_without_echo(self):
        a = self.session(1, 1, x=1, y=3, map_id='7')
        out = a.inner_fly([40101, [None, '9', 2, 4, 'stage']])
        # _feed_unlocked flattens tuples only; a list would kill the
        # live connection at sendall.
        self.assertIsInstance(out, tuple)
        decoded = decode(out)
        self.assertEqual(decoded[0], ['20000', [1, '9', [2, 4]]])
        self.assertEqual(decoded[1], ['21000', [1, 1, a.map_type_for('9')]])
        self.assertNotIn('40101', [m[0] for m in decoded])
        self.assertEqual(self.reg._pos['1'], (2, 4))
        self.assertIn(('1', {'map_id': '9', 'map_x': 2, 'map_y': 4}), self.saved)

    def test_cross_map_leaves_old_surround_behind(self):
        a = self.session(1, 1, x=1, y=3, map_id='7')
        b = self.session(2, 2, x=2, y=3, map_id='7')
        a.inner_fly([40101, [None, '9', 2, 4, 'stage']])
        self.assertIsNone(b.tick(now_ms=0))

    def test_same_map_teleport_persists_position(self):
        # Same-map innerFly persists the landing cell through
        # save_role_state, read back live from the store.
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.store = Store(os.path.join(tmp, 'f.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        rid = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', map_id='7', map_x=1,
            map_y=3)
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0, config=self.cfg, stage_registry=self.reg,
            save_role_state=self.store.update_character_state)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        self.reg.register(str(rid), '7', sess, x=1, y=3)
        out = sess.inner_fly([40101, [None, '7', 5, 6, 'stage']])
        self.assertEqual(decode([out[0]]),
                         [['40101', [5, 6, 0, str(rid)]]])
        row = self.store.list_roles('hero', 'fu1304')[0]
        self.assertEqual((row['map_x'], row['map_y']), (5, 6))

    def test_unowned_sender_is_silent(self):
        sess = Session(conn_id=9, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [], server_start_ms=0,
                       config=self.cfg, stage_registry=self.reg)
        self.assertIsNone(sess.inner_fly([40101, [None, '7', 5, 6, 'stage']]))
        self.assertEqual(self.saved, [])

    def test_bad_args_are_silent(self):
        a = self.session(1, 1, map_id='7')
        self.assertIsNone(a.inner_fly([40101, [None, '7', 5, 6]]))
        self.assertIsNone(a.inner_fly([40101, [None, '7', '5', 6, 'stage']]))
        self.assertIsNone(a.inner_fly([40101, [None, '7', True, 6, 'stage']]))
        self.assertIsNone(a.inner_fly([40101, [None, '', 5, 6, 'stage']]))
        self.assertIsNone(a.inner_fly([40101, [None, '7', 5, 6, '']]))
        self.assertIsNone(a.inner_fly([40101, None]))
        self.assertEqual(self.saved, [])


if __name__ == '__main__':
    unittest.main()

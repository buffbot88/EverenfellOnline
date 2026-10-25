"""Stage-copy instances: isolation, sharing, cleanup (zuwu family).

Verifies the shared StageRegistry instance infrastructure behind
checkStageAndEnter: per-role zuwu copies isolate monsters/AOI/drops,
kills cannot cross copies, quit/expiry return home and destroy the
copy, and ordinary maps keep the shared world.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pathlib import Path  # noqa: E402

from game import amf3  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session, _wire_id  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402
from db import Store  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2] / 'reference' /
               'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config' / 'ZuWuFuBen.jat').is_file()


class RegistryIsolationTest(unittest.TestCase):
    def test_instances_isolate_peers_and_worlds(self):
        reg = StageRegistry()
        k1 = reg.create_instance('91', 'ZUWU', 'r1')
        k2 = reg.create_instance('91', 'ZUWU', 'r2')
        self.assertNotEqual(k1, k2)
        self.assertNotEqual(reg.monster_world_for(k1),
                            reg.monster_world_for(k2))
        self.assertIs(reg.monster_world_for(k1),
                      reg.monster_world_for(k1))
        reg.register('r1', '91', object(), x=8, y=58, stage_key=k1)
        reg.register('r2', '91', object(), x=8, y=58, stage_key=k2)
        # Client-visible map stays the base map for both copies.
        self.assertEqual(reg.map_of('r1'), '91')
        self.assertEqual(reg.map_of('r2'), '91')
        self.assertEqual(reg.stage_of('r1'), k1)
        self.assertEqual(reg.stage_of('r2'), k2)
        # Same base map, different copies: no shared surround.
        self.assertEqual([r for r, _ in reg.surround('r1')], ['r1'])
        self.assertEqual([r for r, _ in reg.surround('r2')], ['r2'])
        self.assertEqual([r for r, _ in reg.peers_in_stage(k1)], ['r1'])
        self.assertEqual([r for r, _ in reg.peers_in_stage(k2)], ['r2'])
        # Ordinary maps still share one bucket.
        reg.register('w1', '100', object(), x=1, y=1)
        reg.register('w2', '100', object(), x=1, y=1)
        self.assertEqual(reg.stage_of('w1'), '100')
        self.assertIs(reg.monster_world_for('100'), reg.monsters)
        # Emptying a copy destroys its runtime state.
        reg.unregister('r1')
        self.assertIsNone(reg.stage_of('r1'))
        self.assertFalse(reg.destroy_instance_if_empty(k1))
        self.assertEqual(reg.stage_of('r2'), k2)


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class ZuwuCopyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero1', 'pw')
        self.store.create_account('hero2', 'pw')
        self.role1 = self.store.create_character(
            'hero1', 'fu1304', 'Wukong', job='C', level=30,
            lingshi=1000, tongqian=0)
        self.role2 = self.store.create_character(
            'hero2', 'fu1304', 'Bajie', job='C', level=30,
            lingshi=1000, tongqian=0)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.reg = StageRegistry()
        self.s1 = self.session('hero1', 1)
        self.s2 = self.session('hero2', 2)
        for sess in (self.s1, self.s2):
            for rid in (self.role1, self.role2):
                self.store.save_role_bag_state(rid, bag_capacity=144,
                                               storage_capacity=30)

    def session(self, user, conn):
        sess = Session(
            conn_id=conn, check_sign=lambda *a: False,
            get_roles=lambda u, s, _u=user: [
                dict(r) for r in self.store.list_roles(_u, s)],
            server_start_ms=0,
            get_role_zuwufuben=self.store.get_role_zuwufuben,
            save_role_zuwufuben=self.store.save_role_zuwufuben,
            get_role_zuwu=self.store.get_role_zuwu,
            list_role_zuwu=self.store.list_role_zuwu,
            save_role_zuwu=self.store.save_role_zuwu,
            get_role_bag_dummy=self.store.get_role_bag_dummy,
            add_role_bag_dummy=self.store.add_role_bag_dummy,
            get_role_vip=self.store.get_role_vip,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            get_role_bag_slot=self.store.get_role_bag_slot,
            update_role_bag_slot=self.store.update_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            save_role_state=self.store.update_character_state,
            config=self.cfg, stage_registry=self.reg)
        sess.authed_user, sess.server_id = user, 'fu1304'
        return sess

    def call(self, sess, method, *args):
        out = getattr(sess, method)(*args) if args else getattr(sess, method)()
        self.assertIsNotNone(out)
        frames = out if isinstance(out, tuple) else (out,)
        return [amf3.decode(bytes(f)[4:]) for f in frames]

    def rid(self, sess):
        roles = self.store.list_roles(sess.authed_user, 'fu1304')
        return _wire_id(roles[0])

    def test_two_copies_are_independent(self):
        e1 = self.call(self.s1, 'zuwu_enter', [108002, [1]])
        e2 = self.call(self.s2, 'zuwu_enter', [108002, [1]])
        self.assertEqual(e1[-1], ['108002', [1, 1]])
        self.assertEqual(e2[-1], ['108002', [1, 1]])
        r1, r2 = self.rid(self.s1), self.rid(self.s2)
        s1key = self.reg.stage_of(r1)
        s2key = self.reg.stage_of(r2)
        self.assertIsNotNone(s1key)
        self.assertIsNotNone(s2key)
        self.assertNotEqual(s1key, s2key)
        self.assertEqual(self.reg.map_of(r1), '91')
        self.assertEqual(self.reg.map_of(r2), '91')
        # Each copy owns an isolated monster world.
        self.assertIsNot(
            self.reg.monster_world_for(s1key),
            self.reg.monster_world_for(s2key))
        self.assertIs(self.s1._world,
                      self.reg.monster_world_for(s1key))
        self.assertIs(self.s2._world,
                      self.reg.monster_world_for(s2key))
        # Kills in copy A do not leak into copy B's attempt.
        cfg = self.cfg.zuwu_fuben_row(1)
        wanted = cfg['wanted'][0][0]
        self.s1._zuwu_kill_progress(
            self.store.list_roles('hero1', 'fu1304')[0], wanted)
        self.assertEqual(
            self.s1._zuwu_attempt[r1]['kills'].get(wanted), 1)
        self.assertEqual(
            self.s2._zuwu_attempt[r2]['kills'].get(wanted, 0), 0)
        # Cross-copy combat targeting is refused.
        target = self.s1._stage_fighter(r2)
        self.assertIsNotNone(target)
        self.assertNotEqual(self.s1._fighter_stage(
            {'kind': 'role', 'id': r1}),
            self.s1._fighter_stage(target))

    def test_quit_returns_home_and_cleans_up(self):
        self.call(self.s1, 'zuwu_enter', [108002, [1]])
        r1 = self.rid(self.s1)
        stage = self.reg.stage_of(r1)
        self.assertTrue(str(stage).startswith('ZUWU-'))
        home = self.s1._zuwu_attempt[r1]['return_map']
        quit = self.call(self.s1, 'zuwu_quit')
        self.assertEqual(quit[-1], ['108006', [1]])
        self.assertTrue(any(f[0] == '20000' for f in quit))
        self.assertEqual(self.reg.map_of(r1), home)
        self.assertNotIn(r1, self.s1._zuwu_attempt)
        # The role is back on the ordinary map; the copy bucket is gone.
        self.assertEqual(self.reg.stage_of(r1), home)
        self.assertNotIn(stage, self.reg._maps)


if __name__ == '__main__':
    unittest.main()

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


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class JuqingCopyTest(unittest.TestCase):
    CHAPTER = 1

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('jq1', 'pw')
        self.store.create_account('jq2', 'pw')
        self.store.create_character(
            'jq1', 'fu1304', 'Wukong', job='C', level=30, exp=0,
            zhenqi=0, tongqian=0, lingshi=0)
        self.store.create_character(
            'jq2', 'fu1304', 'Bajie', job='C', level=30, exp=0,
            zhenqi=0, tongqian=0, lingshi=0)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.reg = StageRegistry()
        self.s1 = self.session('jq1', 1)
        self.s2 = self.session('jq2', 2)

    def session(self, user, conn):
        sess = Session(
            conn_id=conn, check_sign=lambda *a: False,
            get_roles=lambda u, s, _u=user: [
                dict(r) for r in self.store.list_roles(_u, s)],
            server_start_ms=0,
            get_role_juqing=self.store.get_role_juqing,
            save_role_juqing=self.store.save_role_juqing,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            get_role_bag_slot=self.store.get_role_bag_slot,
            update_role_bag_slot=self.store.update_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            get_role_email=self.store.get_role_email,
            save_role_email=self.store.save_role_email,
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
        return _wire_id(self.store.list_roles(sess.authed_user, 'fu1304')[0])

    def role(self, sess):
        return self.store.list_roles(sess.authed_user, 'fu1304')[0]

    def test_two_story_copies_are_independent(self):
        e1 = self.call(self.s1, 'juqing_challenge', [64002, [self.CHAPTER]])
        e2 = self.call(self.s2, 'juqing_challenge', [64002, [self.CHAPTER]])
        self.assertEqual(e1[-1], ['64002', [1, self.CHAPTER]])
        self.assertEqual(e2[-1], ['64002', [1, self.CHAPTER]])
        r1, r2 = self.rid(self.s1), self.rid(self.s2)
        s1key = self.reg.stage_of(r1)
        s2key = self.reg.stage_of(r2)
        self.assertIsNotNone(s1key)
        self.assertNotEqual(s1key, s2key)
        self.assertTrue(str(s1key).startswith('JUQING-'))
        self.assertEqual(self.reg.map_of(r1), '13')
        self.assertEqual(self.reg.map_of(r2), '13')
        self.assertIsNot(
            self.reg.monster_world_for(s1key),
            self.reg.monster_world_for(s2key))
        cfg = self.cfg.juqing_row(self.CHAPTER)
        wanted = cfg['complete'][0][0]
        self.s1._juqing_kill_progress(self.role(self.s1), wanted)
        row1 = self.store.get_role_juqing(r1)
        row2 = self.store.get_role_juqing(r2)
        kills1 = (self.s1._juqing_active(row1) or {}).get('kills', {})
        kills2 = (self.s2._juqing_active(row2) or {}).get('kills', {})
        self.assertEqual(kills1.get(wanted), 1)
        self.assertEqual(kills2.get(wanted, 0), 0)
        # Cross-copy targeting is refused at the combat layer.
        target = self.s1._stage_fighter(r2)
        self.assertIsNotNone(target)
        self.assertNotEqual(
            self.s1._fighter_stage({'kind': 'role', 'id': r1}),
            self.s1._fighter_stage(target))

    def test_victory_returns_home_and_disconnect_abandons(self):
        self.call(self.s1, 'juqing_challenge', [64002, [self.CHAPTER]])
        self.call(self.s2, 'juqing_challenge', [64002, [self.CHAPTER]])
        r1, r2 = self.rid(self.s1), self.rid(self.s2)
        stage1 = self.reg.stage_of(r1)
        home1 = (self.s1._juqing_active(
            self.store.get_role_juqing(r1)) or {}).get('return_map')
        cfg = self.cfg.juqing_row(self.CHAPTER)
        out = []
        for mid, count in cfg['complete']:
            for _ in range(count):
                out.extend(self.s1._juqing_kill_progress(
                    self.role(self.s1), mid))
        bodies = [amf3.decode(bytes(f)[4:]) for f in out]
        self.assertTrue(any(b[0] == '64003' for b in bodies))
        self.assertTrue(any(b[0] == '20000' for b in bodies))
        self.assertEqual(self.reg.map_of(r1), home1)
        self.assertEqual(self.reg.stage_of(r1), home1)
        self.assertNotIn(stage1, self.reg._maps)
        # The other copy keeps its own attempt and world.
        self.assertIsNotNone(self.s2._juqing_active(
            self.store.get_role_juqing(r2)))
        # Disconnect abandons the copy without touching the survivor.
        self.s2._juqing_on_disconnect()
        self.assertIsNone(self.s2._juqing_active(
            self.store.get_role_juqing(r2)))
        self.assertTrue(self.store.get_role_juqing(r1)['pending_award'])


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class GuildCopyTest(unittest.TestCase):
    HOME = '7'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.reg = StageRegistry()
        self.seq = 0

    def session(self, name):
        from auth import hash_password
        self.seq += 1
        acct = 'gcopy%d' % self.seq
        self.store.create_account(acct, hash_password('pw'))
        rid = self.store.create_character(
            acct, 'fu1304', name, job='C', level=56, tongqian=2000000,
            map_id=self.HOME, map_x=10, map_y=10)
        sess = Session(
            conn_id=self.seq, check_sign=lambda *a: False,
            get_roles=lambda u, s, _a=acct: [dict(r) for r in
                                             self.store.list_roles(_a, s)],
            server_start_ms=0,
            save_role_state=self.store.update_character_state,
            get_role_brief=self.store.get_role_brief,
            get_guild_id=self.store.get_guild_id,
            save_guild_member=self.store.save_guild_member,
            get_guild=self.store.get_guild,
            save_guild=self.store.save_guild,
            delete_guild=self.store.delete_guild,
            get_guild_member=self.store.get_guild_member,
            get_guild_members=self.store.get_guild_members,
            delete_guild_member=self.store.delete_guild_member,
            delete_guild_gongxian=self.store.delete_guild_gongxian,
            get_guild_fuben=self.store.get_guild_fuben,
            list_guild_fubens=self.store.list_guild_fubens,
            save_guild_fuben=self.store.save_guild_fuben,
            delete_guild_fubens=self.store.delete_guild_fubens,
            get_guild_fuben_reward=self.store.get_guild_fuben_reward,
            save_guild_fuben_reward=self.store.save_guild_fuben_reward,
            config=self.cfg, stage_registry=self.reg)
        sess.authed_user, sess.server_id = acct, 'fu1304'
        try:
            self.reg.register(str(rid), self.HOME, sess, x=10, y=10)
        except Exception:
            pass
        return str(rid), sess

    def guild(self, name='浩气会', banner='浩气旗'):
        rid, sess = self.session('Master%s' % self.seq)
        raw = sess.guild_create([53000, [name, banner, 1, 0, 1]])
        frames = raw if isinstance(raw, tuple) else (raw,)
        out = [amf3.decode(bytes(f)[4:]) for f in frames]
        gid = str(out[0][1][1][0])
        guild = dict(self.store.get_guild(gid))
        guild['money'] = 10
        self.store.save_guild(guild)
        sess.guildfuben_seal([118007, 1])
        return rid, sess, gid

    def member(self, gid):
        rid, sess = self.session('Member%s' % self.seq)
        self.store.save_guild_member(rid, gid, 3)
        return rid, sess

    def enter(self, sess, mainid=1):
        return [amf3.decode(bytes(f)[4:])
                for f in sess.guildfuben_enter([118003, mainid])]

    def test_members_share_one_guild_copy(self):
        arid, asess, gid = self.guild()
        brid, bsess = self.member(gid)
        self.enter(asess)
        self.enter(bsess)
        sa = self.reg.stage_of(arid)
        sb = self.reg.stage_of(brid)
        self.assertIsNotNone(sa)
        self.assertEqual(sa, sb)
        self.assertTrue(str(sa).startswith('GUILDFUBEN-'))
        self.assertEqual(self.reg.map_of(arid), '92')
        self.assertEqual(self.reg.map_of(brid), '92')
        self.assertIs(asess._world, bsess._world)
        # Cross-copy targeting is refused at the combat layer.
        target = asess._stage_fighter(brid)
        self.assertIsNotNone(target)
        self.assertEqual(asess._fighter_stage(
            {'kind': 'role', 'id': arid}),
            asess._fighter_stage(target))

    def test_two_guilds_are_isolated(self):
        arid, asess, agid = self.guild('恶人会', '恶人旗')
        _brid, bsess, bgid = self.guild('君山会', '君山旗')
        self.enter(asess)
        self.enter(bsess)
        self.assertNotEqual(self.reg.stage_of(arid),
                            self.reg.stage_of(_brid))
        self.assertIsNot(
            self.reg.monster_world_for(self.reg.stage_of(arid)),
            self.reg.monster_world_for(self.reg.stage_of(_brid)))
        asess._guildfuben_kill_progress(
            self.store.list_roles(asess.authed_user, 'fu1304')[0],
            'G200001')
        import json as _json
        self.assertIn('G200001', _json.loads(
            self.store.get_guild_fuben(agid, 1)['killboss']))
        self.assertEqual(_json.loads(
            self.store.get_guild_fuben(bgid, 1)['killboss']), {})

    def test_quit_returns_home_and_disconnect_cleans_up(self):
        arid, asess, gid = self.guild()
        brid, bsess = self.member(gid)
        self.enter(asess)
        self.enter(bsess)
        stage = self.reg.stage_of(arid)
        out = [amf3.decode(bytes(f)[4:])
               for f in asess.guildfuben_quit([118004, '1'])]
        self.assertEqual(out[-1], ['118004', [1]])
        self.assertTrue(any(f[0] == '20000' for f in out))
        self.assertEqual(self.reg.map_of(arid), self.HOME)
        # The copy survives for the remaining member.
        self.assertEqual(self.reg.stage_of(brid), stage)
        bsess._guildfuben_on_disconnect()
        self.assertIsNone(self.reg.stage_of(brid))
        self.assertNotIn(stage, self.reg._maps)

    def test_kick_returns_member_home_cross_session(self):
        arid, asess, gid = self.guild()
        brid, bsess = self.member(gid)
        self.enter(asess)
        self.enter(bsess)
        stage = self.reg.stage_of(brid)
        # The kick runs on the master's session; delivery rides the
        # member's tick like peer pushes.
        self.assertIsNone(asess._guildfuben_on_guild_leave(brid, gid))
        ticked = bsess.tick() or ()
        got = [amf3.decode(bytes(f)[4:]) for f in ticked]
        self.assertTrue(any(f[0] == '20000' for f in got))
        self.assertIn(['118004', [1]], got)
        self.assertEqual(self.reg.map_of(brid), self.HOME)
        self.assertEqual(self.reg.stage_of(brid), self.HOME)
        # The kicker stays inside the surviving copy.
        self.assertEqual(self.reg.stage_of(arid), stage)
        self.assertNotIn(brid, bsess._guildfuben_attempt)

    def test_disband_evicts_members_home(self):
        arid, asess, gid = self.guild()
        brid, bsess = self.member(gid)
        self.enter(asess)
        self.enter(bsess)
        stage = self.reg.stage_of(arid)
        members = [{'role_id': arid}, {'role_id': brid}]
        own = asess._guildfuben_on_guild_disband(gid, members) or []
        flat = []
        for item in own:
            if isinstance(item, (tuple, list)):
                flat.extend(item)
            else:
                flat.append(item)
        own_frames = [amf3.decode(bytes(f)[4:]) for f in flat]
        self.assertTrue(any(f[0] == '20000' for f in own_frames))
        ticked = bsess.tick() or ()
        got = [amf3.decode(bytes(f)[4:]) for f in ticked]
        self.assertTrue(any(f[0] == '20000' for f in got))
        self.assertIn(['118004', [1]], got)
        self.assertEqual(self.reg.map_of(arid), self.HOME)
        self.assertEqual(self.reg.map_of(brid), self.HOME)
        self.assertNotIn(stage, self.reg._maps)

    def test_expire_returns_member_home(self):
        arid, asess, _gid = self.guild()
        self.enter(asess)
        out = asess._guildfuben_expire(arid, 1) or ()
        got = [amf3.decode(bytes(f)[4:]) for f in out]
        self.assertTrue(any(f[0] == '20000' for f in got))
        self.assertIn(['118004', [1]], got)
        self.assertEqual(self.reg.map_of(arid), self.HOME)
        self.assertNotIn(arid, asess._guildfuben_attempt)


if __name__ == '__main__':
    unittest.main()

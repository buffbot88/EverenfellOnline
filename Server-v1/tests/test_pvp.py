"""Player-versus-player combat, from the legacy stage fight pipeline.

Oracle: dntg_start.jar (BattleMode.convert, RoleBattleModeRelation.isEnemy,
SkillTargetFilterFactory.stageProtect, RolePkManager, RoleEventManager
fireDeadEvent/hanlePkIncr/needGray, FightServiceImpl redNameDropYxb,
newerRevive, goodsRevive, changeBattleMode, pkValCheck) recovered through
tools/javap.py, plus the wire captures in Server-v1/docs (43000 kill
notices, 45000/45001 PK pushes).

Two sessions share one role store, one StageRegistry (shared PvpWorld) and
one clock, so every assertion runs across connections the way two clients
would see it. Randomness is pinned to 0.5 (hits land, no crits).
"""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import amf3  # noqa: E402
from game import pvp as pvp_lib  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402
from game.team import TeamState  # noqa: E402

MAP = '7'
AX, AY = 2, 63
VX, VY = 3, 63
NOW = 1700000000000
SKILL = 'normal003'


def decode(frames):
    return [amf3.decode(f[4:]) for f in frames or []]


def cmds(frames):
    return [c for c, _p in decode(frames)]


class SharedStore:
    """Role rows plus the stage/persisted cells every session writes."""

    def __init__(self):
        self.roles = {}
        self.stage = {}
        self.die_logs = []
        self.bag_dels = []

    def add(self, role_id, x, y, hp=500, level=40, tongqian=0,
            pk_info=None, name=None):
        self.roles[str(role_id)] = {
            'id': role_id, 'name': name or 'R%s' % role_id,
            'map_id': MAP, 'map_x': x, 'map_y': y,
            'level': level, 'exp': 0, 'zhenqi': 0,
            'hp': hp, 'max_hp': 500, 'mp': 100, 'max_mp': 100,
            'tongqian': tongqian, 'pk_info': pk_info}

    def save(self, rid, **kw):
        self.roles[str(rid)].update(kw)

    def get(self, rid):
        return self.roles[str(rid)]

    def save_stage(self, rid, **fields):
        self.stage.setdefault(str(rid), {}).update(fields)
        if 'pk_info' in fields and str(rid) in self.roles:
            self.roles[str(rid)]['pk_info'] = fields['pk_info']
        return True

    def insert_die(self, rid, data):
        self.die_logs.append((str(rid), data))
        return True


class PvpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = GameConfig()
        cls.tpl = cls.cfg.monster_template('D000006')

    def setUp(self):
        self.reg = StageRegistry()
        self.store = SharedStore()
        self.guilds = {}
        self.bags = {}
        self.teams = TeamState()
        self.store.add(1, AX, AY, name='Killer')
        self.store.add(2, VX, VY, name='Victim')
        self.a = self._session(1, 1, AX, AY)
        self.b = self._session(2, 2, VX, VY)

    def _session(self, conn_id, role_id, x, y):
        roles = [self.store.get(role_id)]
        sess = Session(
            conn_id=conn_id, check_sign=lambda *a: False,
            get_roles=lambda u, s, r=roles: list(r),
            server_start_ms=0, config=self.cfg,
            stage_registry=self.reg,
            save_role_state=self.store.save,
            save_role_stage=self.store.save_stage,
            insert_role_die=self.store.insert_die,
            get_guild_id=lambda rid: self.guilds.get(str(rid)),
            get_guild=lambda gid: {'id': gid, 'name': 'G%s' % gid},
            get_role_bag_slots=lambda rid: [
                dict(s) for s in self.bags.get(str(rid), [])],
            delete_role_bag_slot=self._bag_del,
            update_role_bag_slot=self._bag_upd,
            team_state=self.teams)
        sess.authed_user, sess.server_id = 'u%s' % role_id, 's1'
        sess._world_now_ms = lambda: NOW
        self.reg.register(str(role_id), MAP, sess, x=x, y=y)
        return sess

    def _bag_del(self, rid, slot_num):
        slots = self.bags.get(str(rid), [])
        self.bags[str(rid)] = [s for s in slots
                               if s.get('slot_num') != slot_num]
        self.store.bag_dels.append((str(rid), slot_num))
        return True

    def _bag_upd(self, rid, slot_num, **kw):
        for s in self.bags.get(str(rid), []):
            if s.get('slot_num') == slot_num:
                s.update(kw)
        return True

    def swing(self, sess, rid, target_id, skill=SKILL):
        with mock.patch('random.random', return_value=0.5):
            return sess.skill_fire(
                [42002, [str(rid), skill, 0, [str(target_id)], None, 1]])

    def mode(self, sess, value):
        sess.change_battle_mode([40600, value])

    # --- 1. Eligibility ----------------------------------------------------

    def test_peace_mode_rejects_role_targets(self):
        out = self.swing(self.a, 1, 2)
        self.assertIsNone(out)
        self.assertEqual(self.store.get(2)['hp'], 500)
        self.assertEqual(self.store.die_logs, [])

    def test_out_of_range_mode_reads_as_peace(self):
        self.mode(self.a, 9)
        self.assertEqual(self.a.battle_mode_of('1'), 0)
        self.assertIsNone(self.swing(self.a, 1, 2))
        self.assertEqual(self.store.get(2)['hp'], 500)

    def test_all_mode_hits_and_victim_sees_hp(self):
        self.mode(self.a, 3)
        out = self.swing(self.a, 1, 2)
        self.assertLess(self.store.get(2)['hp'], 500)
        self.assertIn('42002', cmds(out))
        seen = decode(self.b.tick(now_ms=NOW))
        self.assertIn(['12004', ['2', self.store.get(2)['hp'], 500,
                                 100, 100]], seen)

    def test_safe_node_blocks_role_attacks(self):
        self.mode(self.a, 3)
        with mock.patch.object(self.cfg, 'safe_node', return_value=True):
            out = self.swing(self.a, 1, 2)
        self.assertIsNone(out)
        self.assertEqual(self.store.get(2)['hp'], 500)

    def test_level_floor_protects_low_roles(self):
        self.store.save(2, level=29)
        self.mode(self.a, 3)
        self.assertIsNone(self.swing(self.a, 1, 2))
        self.assertEqual(self.store.get(2)['hp'], 500)

    def test_birth_protection_blocks_and_attack_strips_own(self):
        self.mode(self.a, 3)
        self.b._pvp.protect('2', NOW + 60000)
        self.assertIsNone(self.swing(self.a, 1, 2))
        self.assertEqual(self.store.get(2)['hp'], 500)
        # Starting a fight drops the attacker's own protection instead.
        self.b._pvp.protect('2', NOW + 60000)
        self.mode(self.b, 3)
        self.swing(self.b, 2, 1)
        self.assertFalse(self.b._pvp.protected('2', NOW))
        self.assertLess(self.store.get(1)['hp'], 500)

    def test_entry_buff_registers_birth_protection(self):
        self.b.entry_buff_frame(self.store.get(2))
        self.assertTrue(self.b._pvp.protected('2', NOW))
        self.mode(self.a, 3)
        self.assertIsNone(self.swing(self.a, 1, 2))

    # --- 2. Mode relations ---------------------------------------------------

    def _team(self, tid, members, leader=None):
        for mid in members:
            self.teams.put_role_team(
                {'team_id': tid, 'role_id': str(mid), 'name': 'R%s' % mid,
                 'sex': 1, 'face': 1, 'level': 40, 'job': 1})
        self.teams.put_team(
            {'team_id': tid, 'leader_id': str(leader or members[0]),
             'leader_map_id': MAP, 'next_leader_id': '',
             'member_map': {str(m): NOW for m in members}})

    def test_team_mode_spares_teammates(self):
        self._team('T1', [1, 2])
        self.mode(self.a, 1)
        self.assertIsNone(self.swing(self.a, 1, 2))
        self.assertEqual(self.store.get(2)['hp'], 500)

    def test_team_mode_hits_outsiders(self):
        self._team('T1', [1])
        self._team('T2', [2])
        self.mode(self.a, 1)
        self.swing(self.a, 1, 2)
        self.assertLess(self.store.get(2)['hp'], 500)

    def test_guild_mode_spares_guildmates(self):
        self.guilds.update({'1': '10', '2': '10'})
        self.mode(self.a, 2)
        self.assertIsNone(self.swing(self.a, 1, 2))
        self.assertEqual(self.store.get(2)['hp'], 500)

    def test_guild_mode_hits_other_guilds(self):
        self.guilds.update({'1': '10', '2': '11'})
        self.mode(self.a, 2)
        self.swing(self.a, 1, 2)
        self.assertLess(self.store.get(2)['hp'], 500)

    def test_shane_mode_hits_only_gray_and_red(self):
        self.mode(self.a, 4)
        self.assertIsNone(self.swing(self.a, 1, 2))
        self.b._pvp.state('2').enter_gray(NOW)
        self.swing(self.a, 1, 2)
        self.assertLess(self.store.get(2)['hp'], 500)

    # --- 3. Gray, PK value, kill log ------------------------------------------

    def test_white_on_white_attack_turns_killer_gray(self):
        self.mode(self.a, 3)
        out = self.swing(self.a, 1, 2)
        self.assertIn(['45000', ['1', 1]], decode(out))
        self.assertIn(['45000', ['1', 1]],
                      decode(self.b.tick(now_ms=NOW)))
        self.assertTrue(self.a._pvp.live('1').is_gray(NOW))

    def test_white_kill_writes_91006_and_gains_no_pk(self):
        self.store.save(2, hp=1)
        self.mode(self.a, 3)
        out = decode(self.swing(self.a, 1, 2))
        dead = ['43000', [1, ['2', '1', 'Killer', 0, 'normal003']]]
        self.assertIn(dead, out)
        self.assertIn(dead, decode(self.b.tick(now_ms=NOW)))
        self.assertIn(
            (2, '91006;{map|7};{user|1,Killer}'),
            [(int(r), d) for r, d in self.store.die_logs])
        self.assertEqual(self.a._pvp.live('1').value, 0)
        self.assertNotIn('pkVal:1', self.store.get(1).get('pk_info') or '')

    def test_red_kill_gains_victim_addpk(self):
        self.store.save(1, pk_info='pkVal:7;startTime:0;runTime:0;grayTime:0')
        self.store.save(2, hp=1)
        self.mode(self.a, 3)
        out = decode(self.swing(self.a, 1, 2))
        self.assertIn(['45001', ['1', 8]], out)
        self.assertIn(['45001', ['1', 8]],
                      decode(self.b.tick(now_ms=NOW)))
        saved = self.store.stage['1']['pk_info']
        self.assertIn('pkVal:8', saved)

    def test_pk_decay_tick_clears_one_point(self):
        self.store.save(
            1, pk_info='pkVal:1;startTime:0;runTime:1800000;grayTime:0')
        out = self.a._pvp_check_tick('1')
        self.assertIn(['45001', ['1', 0]], decode(out))
        self.assertIn('pkVal:0', self.store.stage['1']['pk_info'])

    def test_pk_tick_before_span_keeps_value(self):
        self.store.save(
            1, pk_info='pkVal:1;startTime:0;runTime:0;grayTime:0')
        self.assertIsNone(self.a._pvp_check_tick('1'))
        self.assertEqual(self.a._pvp.live('1').value, 1)

    def test_monster_kill_writes_no_log_and_grants_no_pk(self):
        # No verified producer logs a role's death to a monster: the
        # 91007 monster line is written on the killer's own log at
        # monster death (see test_xianjie), never on the victim here.
        self.store.save(2, hp=1)
        mid = 'm_7_0'
        self.a._monster_reg[mid] = {'template': self.tpl, 'map': MAP,
                                    'born': [AX, AY], 'pos': [AX, AY]}
        self.a._monster_hp[mid] = 200.0
        me = {'kind': 'monster', 'id': mid, 'template': self.tpl}
        with mock.patch('random.random', return_value=0.5):
            out = decode(self.a._resolve_fire(me, SKILL, 0, ['2'], None, 1))
        self.assertEqual(self.store.die_logs, [])
        self.assertNotIn('45001', [c for c, _p in out])
        self.assertIn('2', self.a._dead)

    # --- 4. Red-name drop and money pickup -------------------------------------

    def test_red_name_drop_spawns_money_and_empties_purse(self):
        self.store.save(1, tongqian=20000,
                        pk_info='pkVal:8;startTime:0;runTime:0;grayTime:0')
        role = self.store.get(1)
        out = decode(self.a._red_name_drop(role))
        self.assertEqual(self.store.get(1)['tongqian'], 0)
        items = [i for i in self.a._world.ground_items.on_map(MAP)
                 if i.goods_id == 'money']
        self.assertEqual(sorted(i.count for i in items), [5000] * 4)
        self.assertIn('32010', [c for c, _p in out])

    def test_money_pickup_credits_tongqian(self):
        self.store.save(1, tongqian=20000,
                        pk_info='pkVal:8;startTime:0;runTime:0;grayTime:0')
        self.a._red_name_drop(self.store.get(1))
        item = next(i for i in self.a._world.ground_items.on_map(MAP)
                    if i.goods_id == 'money')
        self.store.save(1, tongqian=0)
        out = decode(self.b.pickup_goods([30103, [item.id]]))
        self.assertEqual(out[0], ['30103', [1, 'money', 5000, item.id]])
        self.assertEqual(self.store.get(2)['tongqian'], 5000)

    # --- 5. Revive --------------------------------------------------------------

    def test_newer_revive_restores_in_place(self):
        self.store.save(2, hp=0, mp=0)
        self.b._dead.add('2')
        out = decode(self.b.newer_revive([43002, None]))
        self.assertEqual(out[0], ['43002', [0]])
        self.assertEqual(out[1], ['12004', ['2', 500, 500, 100, 100]])
        self.assertEqual(out[2], ['43002', '2'])
        self.assertNotIn('2', self.b._dead)
        self.assertEqual(self.store.get(2)['hp'], 500)

    def test_goods_revive_needs_a_rose(self):
        self.store.save(2, hp=0)
        self.b._dead.add('2')
        out = decode([self.b.goods_revive([43003, None])])
        self.assertEqual(out, [['43003', [0, 1012]]])
        self.assertIn('2', self.b._dead)

    def test_goods_revive_consumes_rose(self):
        self.store.save(2, hp=0, mp=0)
        self.bags['2'] = [{'goods_id': 'fuhuo', 'count': 1, 'slot_num': 1}]
        self.b._dead.add('2')
        out = decode(self.b.goods_revive([43003, None]))
        self.assertEqual(out[0], ['43002', '2'])
        self.assertEqual(out[1], ['12004', ['2', 500, 500, 100, 100]])
        self.assertNotIn('2', self.b._dead)
        self.assertEqual(self.bags['2'], [])
        self.assertEqual(self.store.bag_dels, [('2', 1)])

    def test_battle_mode_command(self):
        self.mode(self.a, 3)
        self.assertEqual(self.a.battle_mode_of('1'), 3)
        self.mode(self.a, 9)
        self.assertEqual(self.a.battle_mode_of('1'), 0)
        lonely = Session(conn_id=9, check_sign=lambda *a: False,
                         get_roles=lambda u, s: [], server_start_ms=0,
                         config=self.cfg, stage_registry=self.reg,
                         save_role_state=self.store.save)
        self.assertIsNone(lonely.change_battle_mode([40600, 3]))


if __name__ == '__main__':
    unittest.main()

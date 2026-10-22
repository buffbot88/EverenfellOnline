"""Shared monster world: two sessions on one StageRegistry see one monster lifecycle.

Each test builds real Session objects against one StageRegistry (one MonsterWorld).
Expected values follow test_monster_death: D000006 has 200 HP and basicexp 50;
the level-5 role's normal003 hit is 74; a lethal swing from 50 HP kills.
Randomness is pinned to 0.5 (no miss, no crit, no block).
"""
import unittest
from unittest import mock

from game import amf3
from game.config import GameConfig
from game.protocol import Session
from game.stage_registry import StageRegistry

MAP = '7'
MID = 'm_7_0'


def decode(frames):
    return [amf3.decode(f[4:]) for f in frames or []]


class SharedMonsterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = GameConfig()
        cls.tpl = cls.cfg.monster_template('D000006')
        cls.spawn_count = cls.cfg.monster_spawn_count(MAP)

    def make_pair(self, registry=None):
        registry = registry or StageRegistry()
        self.reg = registry
        a, self.role_a = self._session(1, 1, registry)
        b, self.role_b = self._session(2, 2, registry)
        return a, b

    def _session(self, conn_id, role_id, registry):
        role = {'id': role_id, 'name': 'R%d' % role_id, 'map_id': MAP,
                'map_x': 10, 'map_y': 10, 'level': 5, 'exp': 0, 'zhenqi': 0,
                'hp': 500, 'max_hp': 500, 'mp': 100, 'max_mp': 100}
        sess = Session(conn_id=conn_id, check_sign=lambda *a: False,
                       get_roles=lambda u, s, r=role: [r], server_start_ms=0,
                       config=self.cfg, stage_registry=registry)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        registry.register(role_id, MAP, sess, x=10, y=10)
        return sess, role

    def seed_monster(self, sess, mid=MID, hp=200.0):
        sess._monster_reg[mid] = {'template': self.tpl, 'map': MAP,
                                  'born': [12, 12], 'pos': [12, 12]}
        sess._monster_hp[mid] = hp

    def swing(self, sess, role, target=MID):
        me = {'kind': 'role', 'id': role['id'], 'role': role}
        with mock.patch('random.random', return_value=0.5):
            return sess._resolve_fire(me, 'normal003', 0, [target], None, 1)

    # 1. Both players observe the same monster ID.
    def test_both_players_see_the_same_monster_id(self):
        a, b = self.make_pair()
        self.seed_monster(a)
        self.assertIs(a._monster_reg, b._monster_reg)
        self.assertEqual(a._stage_fighter(MID)['id'], b._stage_fighter(MID)['id'])

    # 2. Player A damages a monster; Player B observes the updated state.
    def test_damage_by_a_is_seen_by_b(self):
        a, b = self.make_pair()
        self.seed_monster(a)
        self.swing(a, self.role_a)
        self.assertEqual(b._monster_hp[MID], 126.0)
        self.assertEqual(b._fighter_hp(b._stage_fighter(MID))[0], 126.0)

    # 3 & 4. Player A kills; B cannot kill again; one death transition and reward.
    def test_kill_by_a_blocks_b_and_rewards_once(self):
        a, b = self.make_pair()
        self.seed_monster(a, hp=50.0)
        with mock.patch.object(a, 'save_role_state') as save_a, \
                mock.patch.object(b, 'save_role_state') as save_b:
            first = decode(self.swing(a, self.role_a))
            second = decode(self.swing(b, self.role_b))
        self.assertEqual(sum(1 for d in first if d[0] == '43000'), 1)
        self.assertEqual(second, [])
        self.assertEqual(save_a.call_count, 1)
        save_a.assert_called_once_with(1, exp=50)
        save_b.assert_not_called()
        self.assertIn(MID, b._dead)
        self.assertEqual(b._leaving[MID], 3)

    # 5. A late-joining player does not see an already-dead monster as alive.
    def test_late_joiner_does_not_see_dead_monster(self):
        a, _ = self.make_pair()
        self.seed_monster(a, hp=50.0)
        self.swing(a, self.role_a)
        late, _ = self._session(3, 3, self.reg)
        ids = [r[0] for r in late.world_snapshot_records(MAP)]
        self.assertNotIn(MID, ids)

    # 6. Respawning updates both players consistently.
    def test_respawn_visible_to_both_players(self):
        a, b = self.make_pair()
        self.seed_monster(a, hp=50.0)
        self.swing(a, self.role_a)
        for _ in range(3 + 7):
            self.round_tick(a, b)
        respawned = [m for m in a._monster_reg if m not in self.cfg_ids()]
        self.assertEqual(len(respawned), 1)
        new_id = respawned[0]
        self.assertIn(new_id, b._monster_reg)
        self.assertEqual(b._monster_hp[new_id], 200.0)
        self.assertNotIn(new_id, b._dead)

    # 7. Disconnecting A does not reset the monster for B.
    def test_disconnect_of_a_keeps_monster_state_for_b(self):
        a, b = self.make_pair()
        self.seed_monster(a)
        self.swing(a, self.role_a)
        self.reg.unregister_session(a)
        self.assertEqual(b._monster_hp[MID], 126.0)
        self.assertIn(MID, b._monster_reg)

    # 8. Two independent stage instances do not share monster HP.
    def test_separate_worlds_do_not_share_hp(self):
        a, _ = self.make_pair(StageRegistry())
        other, _ = self.make_pair(StageRegistry())
        self.seed_monster(a)
        self.assertNotIn(MID, other._monster_hp)
        self.assertIsNot(a._monster_reg, other._monster_reg)

    # 9. Multiple sessions do not accelerate AI or respawn timers.
    def test_world_leave_timer_advances_once_per_round(self):
        a, b = self.make_pair()
        self.seed_monster(a, hp=50.0)
        self.swing(a, self.role_a)
        self.assertEqual(a._leaving[MID], 3)
        # Each round: the world steps once, however many sessions tick.
        for _ in range(2):
            a._world.begin_round()
            a.ai_tick()
            b.ai_tick()
        self.assertEqual(a._leaving[MID], 1)
        a._world.begin_round()
        a.ai_tick()
        b.ai_tick()
        self.assertNotIn(MID, a._leaving)
        self.assertNotIn(MID, a._monster_reg)

    # 10. Monster IDs remain unique across deaths and respawns.
    def test_ids_unique_across_deaths_and_respawns(self):
        a, b = self.make_pair()
        self.seed_monster(a, hp=50.0)
        seen = set()
        for _ in range(3):
            live = [m for m in a._monster_reg if m not in a._dead]
            target = live[0]
            self.assertNotIn(target, seen)
            seen.add(target)
            a._monster_hp[target] = 50.0
            self.swing(a, self.role_a, target=target)
            for _ in range(3 + 7):
                self.round_tick(a, b)
        ids = [m for m in a._monster_reg]
        self.assertEqual(len(ids), len(set(ids)))

    # Monster retaliates on a player in another session, ticked by the other session.
    def test_monster_retaliates_on_player_in_other_session(self):
        a, b = self.make_pair()
        self.seed_monster(a, hp=200.0)
        # Adjacent to the role at (10, 10), so the monster attacks rather than walks.
        a._monster_reg[MID]['pos'] = [11, 10]
        with mock.patch('random.random', return_value=0.5):
            self.swing(a, self.role_a)
        self.assertEqual(str(a._hatred[MID]), '1')
        a._world.begin_round()
        # Every session writes through the same store, so the stepping session's
        # writer stands in for the shared HP write to Player A's role.
        with mock.patch.object(b, 'save_role_state') as save_b, \
                mock.patch('random.random', return_value=0.5):
            frames = b.ai_tick()
        self.assertIsNotNone(frames)
        save_b.assert_called_once()
        self.assertEqual(str(save_b.call_args.args[0]), '1')
        self.assertLess(save_b.call_args.kwargs['hp'], 500)

    # A player on another map is not an eligible target.
    def test_monster_drops_hatred_for_player_on_other_map(self):
        a, b = self.make_pair()
        self.seed_monster(a, hp=200.0)
        self.swing(a, self.role_a)
        self.role_a['map_id'] = '8'
        a._world.begin_round()
        b.ai_tick()
        self.assertNotIn(MID, a._hatred)

    def round_tick(self, a, b):
        """One server round: the scheduler starts it, then every session ticks."""
        a._world.begin_round()
        a.ai_tick()
        b.ai_tick()

    def cfg_ids(self):
        return {r[0] for r in self.cfg.monster_snapshot(MAP)}


if __name__ == '__main__':
    unittest.main()

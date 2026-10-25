"""Cross-session combat consistency: one shared role store behind two sessions.

Both sessions read roles from, and write HP to, the same in-memory store, which
stands in for the database (get_roles and save_role_state are the store's
functions in production). Monster AI runs on Session B; the targets are on
Session A. Randomness is pinned to 0.5 (no miss, no crit, no block).
"""
import unittest
from unittest import mock

from game import amf3
from game.config import GameConfig
from game.protocol import Session
from game.stage_registry import StageRegistry

MAP = '7'
MID = 'm_7_0'
REVIVE = [43001, None]


def decode(frames):
    return [amf3.decode(f[4:]) for f in frames or []]


class SharedStore:
    """Role rows keyed by role id, read and written by every session."""

    def __init__(self):
        self.roles = {}

    def add(self, role_id, x, y, hp=500):
        self.roles[str(role_id)] = {
            'id': role_id, 'name': 'R%s' % role_id, 'map_id': MAP,
            'map_x': x, 'map_y': y, 'level': 5, 'exp': 0, 'zhenqi': 0,
            'hp': hp, 'max_hp': 500, 'mp': 100, 'max_mp': 100}

    def save(self, rid, **kw):
        self.roles[str(rid)].update(kw)

    def get(self, rid):
        return self.roles[str(rid)]


class ConsistencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = GameConfig()
        cls.tpl = cls.cfg.monster_template('D000006')

    def setUp(self):
        self.reg = StageRegistry()
        self.store = SharedStore()
        self.store.add(1, 10, 10)
        self.a = self._session(1, 1)
        self.b = self._session(2, None)

    def _session(self, conn_id, role_id):
        roles = [self.store.get(role_id)] if role_id is not None else []
        sess = Session(conn_id=conn_id, check_sign=lambda *a: False,
                       get_roles=lambda u, s, r=roles: list(r),
                       server_start_ms=0, config=self.cfg,
                       stage_registry=self.reg,
                       save_role_state=self.store.save)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        if role_id is not None:
            self.reg.register(str(role_id), MAP, sess, x=10, y=10)
        return sess

    def seed_monster(self, pos=(11, 10), hp=200.0):
        """Monster adjacent to Player A's tile, so it attacks instead of walking."""
        self.a._monster_reg[MID] = {'template': self.tpl, 'map': MAP,
                                    'born': [12, 12], 'pos': list(pos)}
        self.a._monster_hp[MID] = hp

    def swing_as_a(self, hp=200.0):
        me = {'kind': 'role', 'id': '1', 'role': self.store.get(1)}
        with mock.patch('random.random', return_value=0.5):
            return self.a._resolve_fire(me, 'normal003', 0, [MID], None, 1)

    def monster_round(self):
        """One server round: the scheduler starts it, then Session B ticks."""
        self.b._world.begin_round()
        with mock.patch('random.random', return_value=0.5):
            return self.b.ai_tick()

    # --- 1. Cross-session HP persistence -------------------------------------

    def test_monster_hit_on_a_is_persisted_and_read_back_by_a(self):
        self.seed_monster()
        self.swing_as_a()  # plants hatred on Player A
        self.monster_round()
        stored = self.store.get(1)['hp']
        self.assertLess(stored, 500)
        # Session A reads the same authoritative HP the store holds.
        fighter_a = self.a._stage_fighter('1')
        self.assertEqual(self.a._fighter_hp(fighter_a)[0], float(stored))

    def test_successive_hits_accumulate_across_sessions(self):
        self.seed_monster()
        self.swing_as_a()
        self.monster_round()
        after_one = self.store.get(1)['hp']
        self.monster_round()
        after_two = self.store.get(1)['hp']
        hit = 500 - after_one
        self.assertGreater(hit, 0)
        # Each round subtracts from the value the previous round stored.
        self.assertEqual(after_two, after_one - hit)

    # --- 2. Death, revival and re-targeting ----------------------------------

    def test_lethal_hit_marks_role_dead_and_stops_retaliation(self):
        self.store.save(1, hp=1)
        self.seed_monster()
        self.swing_as_a()
        self.monster_round()
        self.assertIn('1', self.a._dead)
        self.assertLessEqual(self.store.get(1)['hp'], 0)
        # A dead role is not a valid target: no further attack, hatred dropped.
        before = self.store.get(1)['hp']
        self.assertIsNone(self.monster_round())
        self.assertEqual(self.store.get(1)['hp'], before)
        self.assertNotIn(MID, self.a._hatred)

    def test_revive_clears_death_and_restores_hp(self):
        self.store.save(1, hp=1)
        self.seed_monster()
        self.swing_as_a()
        self.monster_round()
        self.assertIn('1', self.a._dead)
        self.a.town_revive(REVIVE)
        self.assertNotIn('1', self.a._dead)
        self.assertEqual(self.store.get(1)['hp'], 500)

    def test_revived_role_can_be_targeted_again(self):
        self.store.save(1, hp=1)
        self.seed_monster()
        self.swing_as_a()
        self.monster_round()
        self.a.town_revive(REVIVE)
        self.store.save(1, hp=500)
        # Revive moves the role to a birth point; put the monster beside it.
        role = self.store.get(1)
        beside = [role['map_x'] + 1, role['map_y']]
        self.a._monster_reg[MID]['pos'] = beside
        self.a._monster_reg[MID]['born'] = list(beside)
        # Player A attacks again, so the monster re-acquires hatred and hits.
        self.swing_as_a()
        self.assertEqual(str(self.a._hatred[MID]), '1')
        self.monster_round()
        self.assertLess(self.store.get(1)['hp'], 500)

    # --- 3. Disconnect and map change leave no stale shared state ------------

    def test_disconnect_drops_hatred_on_departed_role(self):
        self.seed_monster()
        self.swing_as_a()
        self.reg.unregister_session(self.a)
        self.monster_round()
        self.assertNotIn(MID, self.a._hatred)

    def test_map_change_drops_hatred_on_role_that_left(self):
        self.seed_monster()
        self.swing_as_a()
        self.store.get(1)['map_id'] = '8'
        self.reg.unregister('1')
        self.reg.register('1', '8', self.a, x=0, y=0)
        self.monster_round()
        self.assertNotIn(MID, self.a._hatred)


if __name__ == '__main__':
    unittest.main()

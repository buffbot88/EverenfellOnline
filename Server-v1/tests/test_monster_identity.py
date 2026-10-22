"""Monster identity: snapshot ids are spawn indices, respawn ids never collide.

Snapshot ids m_<map>_<n> use n = the spawn point's index in the whole map list.
Respawn ids start at the map's spawn-point count, so they never reuse a snapshot id.
All tests use the real map 7 spawn data and the real D000006 template.
"""
import unittest

from game import amf3
from game.config import GameConfig
from game.protocol import Session
from game.stage_registry import StageRegistry

MAP = '7'
SPAWN_ID = 'm_7_0'


def decode(frames):
    return [amf3.decode(f[4:]) for f in frames or []]


class MonsterIdentityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = GameConfig()
        cls.full = cls.cfg.monster_snapshot(MAP)
        cls.by_id = {r[0]: r for r in cls.full}
        cls.spawn_count = cls.cfg.monster_spawn_count(MAP)

    def new_session(self, conn_id, role_id):
        role = {'id': role_id, 'name': 'R%d' % role_id, 'map_id': MAP, 'map_x': 1,
                'map_y': 1, 'level': 5, 'exp': 0, 'zhenqi': 0, 'hp': 500,
                'max_hp': 500, 'mp': 100, 'max_mp': 100}
        sess = Session(conn_id=conn_id, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [role], server_start_ms=0,
                       config=self.cfg, stage_registry=StageRegistry())
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return sess, role

    def test_snapshot_ids_are_stable_across_viewers(self):
        # A viewer near the last spawn gets that spawn's id, not a renumbered m_7_0.
        last = self.full[-1]
        near = self.cfg.monster_snapshot(MAP, last[11], last[12])
        self.assertIn(last[0], [r[0] for r in near])
        for rec in near:
            self.assertEqual((rec[11], rec[12]), (self.by_id[rec[0]][11],
                                                  self.by_id[rec[0]][12]))

    def test_filtered_id_resolves_to_its_own_spawn(self):
        sess, role = self.new_session(1, 1)
        last = self.full[-1]
        target = sess._stage_fighter(last[0])
        self.assertIsNotNone(target)
        self.assertEqual(target['id'], last[0])
        self.assertEqual(target['record'][11:13], [last[11], last[12]])

    def test_respawn_before_any_snapshot_avoids_snapshot_ids(self):
        sess, role = self.new_session(1, 1)
        sess._monster_reg[SPAWN_ID] = {'template': self.cfg.monster_template('D000006'),
                                       'map': MAP, 'born': [5, 5], 'pos': [5, 5]}
        sess._monster_hp[SPAWN_ID] = 1.0
        sess._dead.add(SPAWN_ID)
        sess._leaving[SPAWN_ID] = 1
        sess._respawn_next = {}
        sess.ai_tick()  # leave fires
        for _ in range(6):
            sess.ai_tick()
        respawned = [m for m in sess._monster_reg if m not in self.by_id]
        self.assertEqual(len(respawned), 1)
        new_id = respawned[0]
        self.assertNotIn(new_id, self.by_id)
        self.assertGreaterEqual(int(new_id.rsplit('_', 1)[1]), self.spawn_count)

    def test_multiple_respawns_and_repeated_deaths_stay_unique(self):
        sess, role = self.new_session(1, 1)
        tpl = self.cfg.monster_template('D000006')
        seen = []
        for _ in range(3):
            mid = 'm_%s_%d' % (MAP, self.spawn_count + 50 + len(seen))
            sess._monster_reg[mid] = {'template': tpl, 'map': MAP,
                                      'born': [5, 5], 'pos': [5, 5]}
            sess._monster_hp[mid] = 1.0
            sess._dead.add(mid)
            sess._leaving[mid] = 1
            seen.append(mid)
        for _ in range(3 + 6):
            sess.ai_tick()
        respawned = [m for m in sess._monster_reg if m not in self.by_id]
        self.assertEqual(len(respawned), 3)
        self.assertEqual(len(set(respawned)), 3)
        self.assertFalse(set(respawned) & set(self.by_id))

    def test_two_sessions_see_the_same_ids_for_the_same_spawns(self):
        a, _ = self.new_session(1, 1)
        b, _ = self.new_session(2, 2)
        spawn = self.full[10]
        self.assertEqual(a._stage_fighter(spawn[0])['record'][11:13],
                         b._stage_fighter(spawn[0])['record'][11:13])
        self.assertEqual(a._stage_fighter(spawn[0])['id'],
                         b._stage_fighter(spawn[0])['id'])

    def test_respawn_and_leave_frames_carry_the_registry_id(self):
        sess, role = self.new_session(1, 1)
        sess._monster_reg[SPAWN_ID] = {'template': self.cfg.monster_template('D000006'),
                                       'map': MAP, 'born': [5, 5], 'pos': [5, 5]}
        sess._monster_hp[SPAWN_ID] = 1.0
        sess._dead.add(SPAWN_ID)
        sess._leaving[SPAWN_ID] = 1
        leave = decode(sess.ai_tick())
        leave_frames = [d for d in leave if d[0] == '24002']
        self.assertEqual(len(leave_frames), 1)
        # AoiMsgListener.getLeaveCommand 24002 [[fighterId]] (combat.aoi_leave_frame).
        self.assertEqual(leave_frames[0][1], [[SPAWN_ID]])
        respawn_ids = []
        for _ in range(8):
            for d in decode(sess.ai_tick()):
                if d[0] == '23002':
                    respawn_ids.append(d[1][0][0])
        self.assertEqual(len(respawn_ids), 1)
        self.assertIn(respawn_ids[0], sess._monster_reg)


if __name__ == '__main__':
    unittest.main()

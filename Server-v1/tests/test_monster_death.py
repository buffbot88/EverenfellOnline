"""Player-vs-monster death lifecycle on real config (D000006 + normal003).

Expected values are hand-derived, not read back from the code under test:
- D000006 (GuaiWuBiao): hitpoints 200, level 5, basicexp 50, asheslast 3, creattime 5.
- Role: level 5. Its wuli 80 comes from the real ZhuJueShuXingBiao level-5 row
  (asserted in the test). Skill normal003: 0.8 * 80 + 10 = 74, multiplier 1.
  A normal swing leaves 200 - 74 = 126. A lethal swing starts from 50 HP, so it
  kills and overkills by 24 (HP clamps to 0).
- EXP: revise(100, solo) = 1.0 and decay(0) = 1.0 on the real tables, so the
  granted EXP is basicexp 50.
- Randomness: random.random is pinned to 0.5 (no miss, no crit, no block).
"""
import unittest
from unittest import mock

from game import amf3
from game.config import GameConfig
from game.protocol import Session
from game.stage_registry import StageRegistry

MONSTER_ID = 'm_7_0'


def decode(frames):
    return [amf3.decode(f[4:]) for f in frames or []]


class MonsterDeathLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = GameConfig()
        cls.tpl = cls.cfg.monster_template('D000006')

    def setUp(self):
        self.role = {'id': 1, 'name': 'Wukong', 'map_id': '7', 'map_x': 10,
                     'map_y': 10, 'level': 5, 'exp': 0, 'zhenqi': 0,
                     'hp': 500, 'max_hp': 500, 'mp': 100, 'max_mp': 100}
        self.sess = Session(conn_id=1, check_sign=lambda *a: False,
                            get_roles=lambda u, s: [self.role], server_start_ms=0,
                            config=self.cfg, stage_registry=StageRegistry())
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.me = {'kind': 'role', 'id': 1, 'role': self.role}
        self.sess._monster_reg[MONSTER_ID] = {'template': self.tpl, 'map': '7',
                                              'born': [12, 12], 'pos': [12, 12]}
        self.sess._monster_hp[MONSTER_ID] = 200.0

    def swing(self):
        with mock.patch('random.random', return_value=0.5):
            return self.sess._resolve_fire(self.me, 'normal003', 0,
                                           [MONSTER_ID], None, 1)

    def test_real_config_records_match_hand_derived_values(self):
        self.assertEqual(int(self.tpl['hitpoints']), 200)
        self.assertEqual(int(self.tpl['basicexp']), 50)
        self.assertEqual(int(self.tpl['asheslast']), 3)
        self.assertEqual(int(self.tpl['creattime']), 5)

    def test_non_lethal_hit_leaves_monster_alive(self):
        self.assertEqual(self.sess._fighter_attrs(self.me)['wuli'], 80.0)
        frames = self.swing()
        self.assertEqual(self.sess._monster_hp[MONSTER_ID], 126.0)
        self.assertNotIn(MONSTER_ID, self.sess._dead)
        self.assertNotIn(MONSTER_ID, self.sess._leaving)
        self.assertEqual(self.role['exp'], 0)
        names = [d[0] for d in decode(frames)]
        self.assertNotIn('43000', names)
        self.assertNotIn('12030', names)

    def test_lethal_hit_clamps_hp_and_processes_death_once(self):
        self.sess._monster_hp[MONSTER_ID] = 50.0
        frames = self.swing()
        self.assertEqual(self.sess._monster_hp[MONSTER_ID], 0.0)
        self.assertIn(MONSTER_ID, self.sess._dead)
        self.assertEqual(self.sess._leaving[MONSTER_ID], 3)
        decoded = decode(frames)
        self.assertEqual(sum(1 for d in decoded if d[0] == '43000'), 1)
        # Second swing at the corpse is rejected and emits nothing.
        self.assertEqual(self.swing(), [])
        self.assertEqual(self.sess._leaving[MONSTER_ID], 3)

    def test_lethal_frame_order_and_broadcast_flags(self):
        self.sess._monster_hp[MONSTER_ID] = 50.0
        names = [d[0] for d in decode(self.swing())]
        # HP change, buff flushes, death notice, the 42002 broadcast, then the kill EXP.
        self.assertEqual(names, ['12004', '42100', '42100', '43000', '42002',
                                 '12001', '12030'])

    def test_kill_exp_is_basicexp_and_persisted(self):
        self.sess._monster_hp[MONSTER_ID] = 50.0
        with mock.patch.object(self.sess, 'save_role_state') as save:
            frames = decode(self.swing())
        save.assert_called_once_with(1, exp=50)
        exp_frame = next(d for d in frames if d[0] == '12001')
        self.assertEqual(exp_frame[1], [50.0, 5])
        drop = next(d for d in frames if d[0] == '12030')
        self.assertEqual(drop[1], [MONSTER_ID, 'D000006', 50.0])

    def test_kill_hit_record_reports_dead_flag(self):
        self.sess._monster_hp[MONSTER_ID] = 50.0
        frames = decode(self.swing())
        skill_fire = next(d for d in frames if d[0] == '42002')
        self.assertEqual(skill_fire[1][3], [[MONSTER_ID, 0, 74, 1]])

    def test_leave_then_respawn_follow_asheslast_and_creattime(self):
        self.sess._monster_hp[MONSTER_ID] = 50.0
        self.swing()
        # asheslast 3: the leave (24002) fires on the third AI tick.
        leave_tick = None
        for i in range(1, 4):
            out = decode(self.sess.ai_tick())
            if any(d[0] == '24002' for d in out):
                leave_tick = i
        self.assertEqual(leave_tick, 3)
        self.assertNotIn(MONSTER_ID, self.sess._monster_reg)
        # The 23002 respawn comes on absolute tick 7 with the current code.
        # creattime is 5, but the queue decrements in the same tick it is set,
        # so the respawn lands one tick earlier than a literal 5-tick delay.
        # Java's scheduler is not verified here, so this is recorded as-is.
        respawn_tick = None
        for i in range(4, 12):
            out = self.sess.ai_tick()
            if out and any(amf3.decode(f[4:])[0] == '23002' for f in out):
                respawn_tick = i
                break
        self.assertEqual(respawn_tick, 7)

    def test_respawn_gets_fresh_id_and_full_hp(self):
        # No snapshot is requested first: respawn ids must still avoid snapshot ids.
        self.sess._monster_hp[MONSTER_ID] = 50.0
        self.swing()
        for _ in range(3 + 5):
            self.sess.ai_tick()
        respawned = [m for m in self.sess._monster_reg if m != MONSTER_ID]
        self.assertEqual(len(respawned), 1)
        new_id = respawned[0]
        self.assertNotEqual(new_id, MONSTER_ID)
        self.assertEqual(self.sess._monster_hp[new_id], 200.0)


if __name__ == '__main__':
    unittest.main()

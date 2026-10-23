"""Monster discovery by walking: 23002 enter burst on tile steps (map 2).

AOI rule: the 3x3 stage-cell surround (cells 600x400 px, tiles 60x30 px),
the same audience rule as frame broadcasts. Java evidence: the map-5
entry 23002 at (44,33) carries spawns at dy -9/+8 (legacy tap), outside
any |dy| <= 6 tile box, while the map-2 entry at (10,150) correctly
carries none (session-20261018-040230).

Hand-derived on the real config, not read back from the code under test:
- A role at (10,152) sees none of map 2's 36 spawns (nearest m_2_22 at
  (29,121) is outside the surround).
- Stepping (10,152) -> (11,151) stays in the same cell: silence.
- Stepping (10,152) -> (27,104) newly covers 12 spawns: one 23002 with
  those records (field 15 True on enter; the legacy tap shows False at
  scene entry but True on every movement-enter burst) plus one
  born-flag 40000 tile each, the scene-entry shape.
- A second step to (28,104) covers the same set: silence (no re-push).
- Dead monsters never enter: with m_2_16 dead the burst carries 11.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import amf3  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2]
               / 'reference' / 'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config' / 'KaiGeFeiYongBiao.jat').is_file()

ENTER_IDS = ['m_2_11', 'm_2_13', 'm_2_16', 'm_2_17', 'm_2_18',
             'm_2_19', 'm_2_20', 'm_2_21', 'm_2_23', 'm_2_31',
             'm_2_33', 'm_2_35']
ENTER_TILES = [[39, 81], [38, 83], [27, 104], [30, 106], [27, 107],
               [29, 115], [28, 116], [28, 119], [35, 100], [39, 83],
               [29, 105], [30, 118]]


def cmds(frames):
    return [amf3.decode(f[4:]) for f in frames or []]


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class MovementEnterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = GameConfig(str(REAL_CONFIG))

    def setUp(self):
        self.role = {'id': 7, 'name': 'Wukong', 'map_id': '2',
                     'map_x': 10, 'map_y': 152, 'level': 7}
        self.sess = Session(conn_id=1, check_sign=lambda *a: False,
                            get_roles=lambda u, s: [self.role],
                            server_start_ms=0,
                            config=self.cfg,
                            stage_registry=StageRegistry())

    def step(self, x, y):
        return cmds(self.sess.tile_step(['40000', [x, y, 0, 0, '7']]))

    def test_step_inside_same_cell_is_silent(self):
        self.assertEqual(self.step(11, 151), [])

    def test_step_into_spawn_cells_pushes_enter_burst(self):
        got = self.step(27, 104)
        self.assertEqual([c for c, _b in got],
                         ['23002'] + ['40000'] * len(ENTER_IDS))
        self.assertEqual([r[0] for r in got[0][1]], ENTER_IDS)
        # Enter bursts carry field 15 True; scene-entry snapshots False.
        for rec in got[0][1]:
            self.assertTrue(rec[15])
            self.assertEqual(len(rec), 18)
        tiles = [[b[0], b[1]] for c, b in got[1:]]
        self.assertEqual(tiles, ENTER_TILES)

    def test_second_step_in_same_cells_is_silent(self):
        self.step(27, 104)
        self.role['map_x'], self.role['map_y'] = 27, 104
        self.assertEqual(self.step(28, 104), [])

    def test_dead_monsters_never_enter(self):
        self.sess._dead.add('m_2_16')
        got = self.step(27, 104)
        ids = [r[0] for r in got[0][1]]
        self.assertNotIn('m_2_16', ids)
        self.assertEqual(len(ids), len(ENTER_IDS) - 1)

    def test_scene_snapshot_carries_false_enter_flag(self):
        recs = self.sess.world_snapshot_records('2', 27, 104)
        self.assertEqual([r[0] for r in recs], ENTER_IDS)
        for rec in recs:
            self.assertFalse(rec[15])


if __name__ == '__main__':
    unittest.main()

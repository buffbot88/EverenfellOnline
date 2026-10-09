import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import amf3  # noqa: E402
from game.amf3 import Obj  # noqa: E402
from game.config import GameConfig, load_map_lines, load_monsters  # noqa: E402
from game.protocol import DEFAULT_MAP_TYPE, Session  # noqa: E402

# Real legacy tree, gitignored; tests against it skip when it is absent.
REAL_CONFIG = (Path(__file__).resolve().parents[2]
               / 'reference' / 'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config' / 'MapLine.jat').is_file()


def write_bytes(directory, rel, data):
    path = os.path.join(directory, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    return path


def make_session(config):
    return Session(conn_id=1, check_sign=lambda *a: False,
                   get_roles=lambda u, s: [], server_start_ms=0, config=config)


class SyntheticConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name

    def test_map_line_rows_keyed_by_string_mapid(self):
        rows = [Obj(mapid=5, maptype=1, mapname='a'),
                Obj(mapid='40', maptype=6, mapname='b')]
        path = write_bytes(self.root, 'MapLine.jat', amf3.encode(rows))
        table = load_map_lines(path)
        self.assertEqual(set(table), {'5', '40'})
        self.assertEqual(table['40']['maptype'], 6)

    def test_game_config_reads_map_type_and_reports_unknown(self):
        rows = [Obj(mapid=8, maptype=3)]
        write_bytes(self.root, 'sys_config/MapLine.jat', amf3.encode(rows))
        cfg = GameConfig(self.root)
        self.assertEqual(cfg.map_type(8), 3)
        self.assertIsNone(cfg.map_type(999))

    def test_missing_table_gives_no_types_and_no_monsters(self):
        cfg = GameConfig(self.root)
        self.assertIsNone(cfg.map_type(5))
        self.assertEqual(cfg.monsters(5), [])

    def test_monster_file_loads_spawn_records(self):
        rec = Obj(id='D040008', team=0, createPoints=[[25, 62, 0]],
                  createTime=1, bossCreateTime=None, maxCount=999,
                  name='x', monsterType=1)
        write_bytes(self.root, 'map_config/5/monster.mm', amf3.encode([rec]))
        cfg = GameConfig(self.root)
        monsters = cfg.monsters(5)
        self.assertEqual(monsters[0]['id'], 'D040008')
        self.assertEqual(monsters[0]['createPoints'], [[25, 62, 0]])
        self.assertEqual(load_monsters(os.path.join(
            self.root, 'map_config/5/monster.mm'))[0]['maxCount'], 999)

    def test_session_uses_config_and_falls_back_for_unknown_maps(self):
        write_bytes(self.root, 'sys_config/MapLine.jat',
                    amf3.encode([Obj(mapid=34, maptype=5)]))
        sess = make_session(GameConfig(self.root))
        self.assertEqual(sess.map_type_for('34'), 5)
        with self.assertLogs('game', level='INFO') as logs:
            self.assertEqual(sess.map_type_for('2'), DEFAULT_MAP_TYPE)
        self.assertTrue(any("'2'" in line for line in logs.output))

    def test_session_without_config_uses_logged_default(self):
        sess = make_session(None)
        with self.assertLogs('game', level='INFO'):
            self.assertEqual(sess.map_type_for('5'), DEFAULT_MAP_TYPE)


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class RealConfigTest(unittest.TestCase):
    """Checks against the shipped MapLine.jat and map_config/ files."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = GameConfig(str(REAL_CONFIG))

    def test_map_line_table_is_complete(self):
        # The Java server loads 91 MapLine rows; every byte of the file must decode.
        self.assertEqual(len(self.cfg.map_lines()), 91)

    def test_known_map_types_match_the_table(self):
        expected = {'2': 1, '3': 1, '5': 1, '8': 3, '12': 3, '13': 3,
                    '20': 3, '35': 1, '34': 6, '40': 6}
        for map_id, mt in expected.items():
            self.assertEqual(self.cfg.map_type(map_id), mt, f'map {map_id}')

    def test_monsters_load_for_a_populated_map(self):
        monsters = self.cfg.monsters(5)
        self.assertTrue(monsters)
        self.assertEqual(monsters[0]['id'], 'D040008')
        self.assertEqual(monsters[0]['name'], '入魔的地精')
        self.assertIsInstance(monsters[0]['createPoints'], list)

    def test_every_monster_file_decodes(self):
        base = REAL_CONFIG / 'map_config'
        count = 0
        for mdir in os.listdir(base):
            path = base / mdir / 'monster.mm'
            if path.is_file():
                self.assertIsInstance(load_monsters(str(path)), list)
                count += 1
        self.assertEqual(count, 84)


# One 23002 record captured live from the original Java server (tap-decoded.txt).
CAPTURED_D040011 = ['m_64_91', 'D040011', 'มารวายุคลั่ง[Lv.40]', 40, 3895.0, 3895.0,
                    3895.0, 3895.0, 450.0, 450.0, 0, 41, 24, 0, None, False, None, 0]


def session_with_roles(config, roles):
    sess = Session(conn_id=1, check_sign=lambda *a: False,
                   get_roles=lambda u, s: roles, server_start_ms=0, config=config)
    sess.authed_user, sess.server_id = 'hero', 'fu1304'
    return sess


class MonsterSnapshotTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = self._tmp.name
        write_bytes(root, 'sys_config/GuaiWuBiao.jat', amf3.encode([
            Obj(id='T1', name='mob', level=3, hitpoints=100, mana=50, velocity=200)]))
        write_bytes(root, 'sys_config/MapLine.jat', amf3.encode([Obj(mapid=7, maptype=2)]))
        write_bytes(root, 'map_config/7/monster.mm', amf3.encode([
            Obj(id='T1', team=0, createPoints=[[1, 2, 0], [3, 4, 0]], createTime=1,
                bossCreateTime=None, maxCount=9, name='mob', monsterType=1),
            Obj(id='GONE', team=0, createPoints=[[5, 6, 0]], createTime=1,
                bossCreateTime=None, maxCount=9, name='gone', monsterType=1)]))
        self.cfg = GameConfig(root)

    def test_one_record_per_spawn_point_with_template_stats(self):
        records = self.cfg.monster_snapshot(7)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0], ['m_7_0', 'T1', 'mob', 3, 100, 100, 50, 50,
                                      200, 200, 0, 1, 2, 0, None, False, None, 0])
        self.assertEqual(records[1][0], 'm_7_1')
        self.assertEqual(records[1][11:13], [3, 4])

    def test_spawn_group_without_template_is_skipped_and_logged(self):
        with self.assertLogs('config', level='WARNING') as logs:
            records = self.cfg.monster_snapshot(7)
        self.assertNotIn('GONE', [r[1] for r in records])
        self.assertTrue(any("'GONE'" in line for line in logs.output))

    def test_map_without_monsters_is_empty(self):
        self.assertEqual(self.cfg.monster_snapshot(9), [])

    def test_scene_entry_sends_snapshot_after_21000(self):
        sess = session_with_roles(self.cfg, [{'id': 7, 'map_id': '7'}])
        out = sess.change_stage([21000, '7'])
        self.assertEqual(len(out), 2)
        self.assertEqual(amf3.decode(out[0][4:]), ['21000', [1, 1, 2]])
        self.assertEqual(amf3.decode(out[1][4:]), ['23002', self.cfg.monster_snapshot(7)])

    def test_scene_entry_without_monsters_sends_only_21000(self):
        sess = session_with_roles(self.cfg, [{'id': 7, 'map_id': '9'}])
        out = sess.change_stage([21000, '7'])
        # A single frame comes back as bytes, not a tuple.
        self.assertIsInstance(out, bytes)
        self.assertEqual(amf3.decode(out[4:]), ['21000', [1, 1, DEFAULT_MAP_TYPE]])


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class RealSnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = GameConfig(str(REAL_CONFIG)).monster_snapshot(5)

    def test_map5_snapshot_has_one_record_per_spawn_point(self):
        self.assertEqual(len(self.records), 47)

    def test_d040011_record_matches_captured_java_record(self):
        mine = [r for r in self.records if r[1] == 'D040011']
        self.assertTrue(mine)
        for rec in mine:
            self.assertEqual(rec[2:10], CAPTURED_D040011[2:10])
            self.assertEqual(rec[13:], CAPTURED_D040011[13:])

    def test_captured_positions_are_spawn_points_of_the_group(self):
        # The capture was taken on map 5. Three of its four positions are spawn points;
        # the fourth has moved since spawn, which is expected for live monsters.
        captured = {(41, 24), (44, 34), (45, 31), (48, 35)}
        spawns = {(r[11], r[12]) for r in self.records if r[1] == 'D040011'}
        self.assertGreaterEqual(len(captured & spawns), 3)


if __name__ == '__main__':
    unittest.main()

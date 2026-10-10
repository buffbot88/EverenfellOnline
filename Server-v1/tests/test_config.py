import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import amf3  # noqa: E402
from game.amf3 import Obj  # noqa: E402
from game.attributes import entry_attribute_map  # noqa: E402
from game.config import GameConfig, load_map_lines, load_monsters, load_path_grid  # noqa: E402
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

    def test_zuoji_table_clamps_pet_level_to_maxlv(self):
        # stratum arrives as a string ('001'); Java coerces with object2int.
        write_bytes(self.root, 'sys_config/ZuoJiBiao.jat', amf3.encode([
            Obj(stratum='001', ridelv=1, maxlv=30, meinvhp=200, meinvatt=50),
            Obj(stratum='001', ridelv=20, maxlv=30, meinvhp=400, meinvatt=80),
            Obj(stratum='001', ridelv=30, maxlv=30, meinvhp=500, meinvatt=100),
            Obj(stratum='002', ridelv=1, maxlv=50, meinvhp=900, meinvatt=200),
            Obj(stratum='002', ridelv=50, maxlv=50, meinvhp=1500, meinvatt=300)]))
        cfg = GameConfig(self.root)
        level, row = cfg.zuoqi_pet(1, 56)   # role level clamped by maxlv
        self.assertEqual(level, 30)
        self.assertEqual(row['meinvhp'], 500)
        self.assertEqual(cfg.zuoqi_pet(1, 20)[0], 20)
        self.assertEqual(cfg.zuoqi_pet(2, 99)[0], 50)
        self.assertIsNone(cfg.zuoqi_pet(9, 56))   # unknown rank: no config
        self.assertIsNone(cfg.zuoqi_pet(0, 56))
        # A rank whose clamped level has no row is skipped, not invented.
        self.assertIsNone(cfg.zuoqi_pet(2, 7))

    def test_missing_zuoji_table_gives_no_pet(self):
        self.assertIsNone(GameConfig(self.root).zuoqi_pet(1, 56))

    def write_path_mm(self, map_id, width, height, walkable):
        body = bytes(1 if (x, y) in walkable else 0
                     for y in range(height) for x in range(width))
        write_bytes(self.root, f'map_config/{map_id}/path.mm',
                    struct.pack('>ii', width, height) + body)

    def test_surround_point_follows_aextend_offs_order(self):
        self.write_path_mm('7', 10, 10, {(x, y) for x in range(10)
                                         for y in range(10)})
        cfg = GameConfig(self.root)
        self.assertEqual(cfg.surround_valid_point('7', 5, 5), (4, 4))
        # Taken cells are skipped in the same order (AExtendOffs second is
        # (0, -1), third is (1, -1)).
        self.assertEqual(cfg.surround_valid_point('7', 5, 5, {(4, 4)}),
                         (5, 4))
        self.assertEqual(cfg.surround_valid_point(
            '7', 5, 5, {(4, 4), (5, 4)}), (6, 4))
        # Every surround taken: Java random-walks, Python returns the
        # original point (the wrapper's fallback), never a new invention.
        taken = {(5 + dx, 5 + dy) for dx, dy in
                 ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0),
                  (-1, 1), (0, 1), (1, 1))}
        self.assertEqual(cfg.surround_valid_point('7', 5, 5, taken), (5, 5))

    def test_surround_point_unwalkable_or_missing_is_none(self):
        self.write_path_mm('7', 4, 4, {(1, 1)})
        cfg = GameConfig(self.root)
        self.assertIsNone(cfg.surround_valid_point('7', 2, 2))  # no PathNode
        self.assertIsNone(cfg.surround_valid_point('9', 1, 1))  # no path.mm
        # The only walkable cell has no walkable surround -> original point.
        self.assertEqual(cfg.surround_valid_point('7', 1, 1), (1, 1))

    def test_spawn_cells_only_include_groups_with_templates(self):
        write_bytes(self.root, 'sys_config/GuaiWuBiao.jat', amf3.encode([
            Obj(id='T1', name='mob', level=3, hitpoints=100)]))
        write_bytes(self.root, 'map_config/7/monster.mm', amf3.encode([
            Obj(id='T1', team=0, createPoints=[[1, 2, 0], [3, 4, 0]],
                createTime=1, bossCreateTime=None, maxCount=9, name='mob',
                monsterType=1),
            Obj(id='GONE', team=0, createPoints=[[5, 6, 0]], createTime=1,
                bossCreateTime=None, maxCount=9, name='gone', monsterType=1)]))
        cfg = GameConfig(self.root)
        # The 'GONE' group is skipped by snapshot, so it never takes a cell.
        self.assertEqual(cfg.monster_spawn_cells('7'), {(1, 2), (3, 4)})


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

    def test_zuoji_rank1_goldens_from_the_capture(self):
        # Captured 23009: role level 56 -> pet level 30 (maxlv), maxHp 500
        # (meinvhp) for rank 1, stratum stored as the string '001'.
        level, row = self.cfg.zuoqi_pet(1, 56)
        self.assertEqual((level, row['maxlv'], row['meinvhp'], row['meinvatt']),
                         (30, 30, 500, 100))
        self.assertIsNone(self.cfg.zuoqi_pet(999, 56))

    def test_captured_pet_placement_on_map5(self):
        # Role at 44,33 in the capture; the pet went to 43,32, the first
        # AExtendOffs surround, and 44,32 when 43,32 is already taken.
        self.assertEqual(self.cfg.surround_valid_point('5', 44, 33),
                         (43, 32))
        self.assertEqual(self.cfg.surround_valid_point('5', 44, 33,
                                                       {(43, 32)}),
                         (44, 32))

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


class PathGridTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name

    def write_path(self, body, width=2, height=2):
        return write_bytes(self.root, 'path.mm', struct.pack('>ii', width, height) + body)

    def test_cells_are_row_major_and_walkable_uses_low_five_bits(self):
        grid = load_path_grid(self.write_path(bytes([0x01, 0x20, 0x00, 0x1F])))
        self.assertEqual((grid.width, grid.height), (2, 2))
        self.assertTrue(grid.walkable(0, 0))    # 0x01
        self.assertFalse(grid.walkable(1, 0))   # 0x20: low five bits are zero
        self.assertFalse(grid.walkable(0, 1))   # 0x00
        self.assertTrue(grid.walkable(1, 1))    # 0x1F

    def test_trailing_bytes_past_height_are_kept_like_java(self):
        grid = load_path_grid(self.write_path(bytes([0x01, 0x01, 0x01]), width=2, height=1))
        self.assertEqual(grid.value(0, 1), 0x01)
        self.assertTrue(grid.walkable(0, 1))

    def test_out_of_range_cells_are_absent_and_not_walkable(self):
        grid = load_path_grid(self.write_path(bytes([1, 1, 1, 1])))
        self.assertIsNone(grid.value(2, 0))
        self.assertFalse(grid.walkable(-1, 0))

    def test_short_header_and_zero_width_are_rejected(self):
        short = write_bytes(self.root, 'short.mm', b'\x00\x00')
        with self.assertRaises(ValueError):
            load_path_grid(short)
        with self.assertRaises(ValueError):
            load_path_grid(self.write_path(b'', width=0, height=2))


@unittest.skipUnless(HAVE_REAL, 'real legacy config tree not present')
class RealPathGridGoldenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = sorted((REAL_CONFIG / 'map_config').glob('*/path.mm'))
        cls.sizes = {p.parent.name: p.stat().st_size for p in paths}
        cls.grids = {p.parent.name: load_path_grid(str(p)) for p in paths}

    def test_all_116_path_files_load(self):
        self.assertEqual(len(self.grids), 116)

    def test_every_file_is_consumed_to_eof(self):
        for name, grid in self.grids.items():
            self.assertEqual(len(grid.values), self.sizes[name] - 8, name)

    def test_no_file_has_fewer_cells_than_its_header_declares(self):
        short = [n for n, g in self.grids.items() if len(g.values) < g.width * g.height]
        self.assertEqual(short, [])

    def test_exact_and_trailing_size_split_is_golden(self):
        exact = [n for n, g in self.grids.items() if len(g.values) == g.width * g.height]
        self.assertEqual(len(exact), 74)
        self.assertEqual(len(self.grids) - len(exact), 42)

    def test_each_file_matches_its_golden_entry(self):
        golden_path = Path(__file__).resolve().parent / 'data' / 'path_mm_golden.json'
        with open(golden_path, encoding='utf-8') as f:
            golden = json.load(f)
        self.assertEqual(set(golden), set(self.grids))
        for name, (width, height, cells) in golden.items():
            grid = self.grids[name]
            self.assertEqual((grid.width, grid.height, len(grid.values)),
                             (width, height, cells), name)

    def test_map0_header_and_length_match_the_survey(self):
        grid = self.grids['0']
        self.assertEqual((grid.width, grid.height), (72, 204))
        # File is 14766 bytes: 8-byte header, 14758 cells, of which 72*204 = 14688 are declared by the header.
        self.assertEqual(len(grid.values), 14758)
        walkable = sum(1 for v in grid.values if v & 31)
        self.assertTrue(0 < walkable < len(grid.values))


@unittest.skipUnless(HAVE_REAL, 'real legacy config tree not present')
class RealSpawnWalkabilityTest(unittest.TestCase):
    """Every monster.mm spawn point sits on a walkable path.mm cell, with 9 known exceptions."""

    # (map, x, y) spawn points whose cell value is 0 (blocked), surveyed
    # 2026-10-09: 7160 points on 84 maps, 7151 walkable, 0 out of range.
    # Each sits next to walkable ground inside a group whose other points are
    # walkable, so they read as designer-placed quirks, not an axis mismatch
    # (swapped axes are blocked/out-of-range too). (61, 112) is listed twice
    # in map 25's own data.
    BLOCKED_SPAWNS = sorted([
        ('15', 15, 12), ('15', 17, 18),
        ('25', 67, 99), ('25', 61, 112), ('25', 61, 112),
        ('25', 55, 113), ('25', 53, 115), ('25', 51, 118),
        ('80', 123, 110),
    ])

    def test_spawn_points_agree_with_walkability(self):
        cfg = GameConfig(str(REAL_CONFIG))
        base = REAL_CONFIG / 'map_config'
        maps, blocked, oor, total = 0, [], [], 0
        for mdir in sorted(os.listdir(base)):
            if not (base / mdir / 'path.mm').is_file():
                continue
            if not (base / mdir / 'monster.mm').is_file():
                continue
            maps += 1
            grid = cfg.path_grid(mdir)
            for group in cfg.monsters(mdir):
                for pt in group.get('createPoints') or []:
                    total += 1
                    v = grid.value(pt[0], pt[1])
                    if v is None:
                        oor.append((mdir, pt[0], pt[1]))
                    elif not (v & 31):
                        blocked.append((mdir, pt[0], pt[1]))
        self.assertEqual(maps, 84)
        self.assertEqual(total, 7160)
        self.assertEqual(oor, [])
        self.assertEqual(sorted(blocked), self.BLOCKED_SPAWNS)


class RoleAttributeConfigTest(unittest.TestCase):
    """ZhuJueShuXingBiao loading and the 12000 formula goldens."""

    def test_missing_table_warns_once_and_reports_no_row(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = GameConfig(root)
            with self.assertLogs('config', level='WARNING'):
                self.assertIsNone(cfg.role_attribute_row(1))
            self.assertIsNone(cfg.role_attribute_row(99))  # cached, no repeat

    def test_rows_are_keyed_by_level(self):
        with tempfile.TemporaryDirectory() as root:
            write_bytes(root, 'sys_config/ZhuJueShuXingBiao.jat',
                        amf3.encode([Obj(level=1, mana=10),
                                     Obj(level=10, mana=99)]))
            cfg = GameConfig(root)
            self.assertEqual(cfg.role_attribute_row(1)['mana'], 10)
            self.assertEqual(cfg.role_attribute_row(10)['mana'], 99)
            self.assertIsNone(cfg.role_attribute_row(2))
            self.assertIsNone(cfg.role_attribute_row(None))

    def test_formula_floors_and_dunshudian_int_cast(self):
        row = dict(physicdamage=0, physicdefence=0, critical=-5, volt=-5,
                   attackrate=-1, velocity=-1, mana=50, dunshudian=12.7)
        attrs = entry_attribute_map(row)
        self.assertEqual(attrs['2'], 1.0)    # GongJiFormula floor at 1
        self.assertEqual(attrs['3'], 1.0)    # FangYuFormula floor at 1
        self.assertEqual(attrs['4'], 0.0)    # BaoJiFormula floor at 0
        self.assertEqual(attrs['5'], 0.0)
        self.assertEqual(attrs['6'], 0.0)
        self.assertEqual(attrs['7'], 0.0)
        self.assertEqual(attrs['1'], 50.0)   # falls back to the row's mana
        self.assertEqual(attrs['10'], 12.0)  # int cast, not rounding

    def test_persisted_max_mp_wins_over_the_row(self):
        row = dict(mana=50)
        self.assertEqual(entry_attribute_map(row)['1'], 50.0)
        self.assertEqual(entry_attribute_map(row, max_mp=300)['1'], 300.0)

    @unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
    def test_real_table_level_1_is_a_golden(self):
        cfg = GameConfig(str(REAL_CONFIG))
        row = cfg.role_attribute_row(1)
        self.assertIsNotNone(row)
        self.assertEqual(
            entry_attribute_map(row),
            {'1': 96.0, '2': 48.0, '3': 24.0, '4': 9.0,
             '5': 9.0, '6': 1.0, '7': 550.0, '10': 1.0})
        self.assertIsNotNone(cfg.role_attribute_row(56))


if __name__ == '__main__':
    unittest.main()

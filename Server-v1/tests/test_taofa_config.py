"""Taofa quest table: the loader must read the real taskTaoFaRenWu.jat, not guesses."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game.config import DEFAULT_CONFIG_DIR, GameConfig, config_int, load_taofa_table  # noqa: E402

TABLE = os.path.join(DEFAULT_CONFIG_DIR, 'sys_config', 'taskTaoFaRenWu.jat')


@unittest.skipUnless(os.path.isfile(TABLE), 'legacy config tree not present')
class TaofaTableTest(unittest.TestCase):
    def setUp(self):
        self.table = load_taofa_table(TABLE)

    def test_all_ninety_rows_load_keyed_by_taofaid(self):
        self.assertEqual(len(self.table), 90)
        self.assertIn('TF02001', self.table)
        self.assertIn('TF02002', self.table)

    def test_first_row_matches_the_table(self):
        row = self.table['TF02001']
        self.assertEqual(config_int(row['monsterLv']), 21)
        self.assertEqual(config_int(row['min']), 21)
        self.assertEqual(config_int(row['max']), 30)
        self.assertEqual(config_int(row['exp']), 120000)
        self.assertEqual(config_int(row['gold']), 20000)
        self.assertEqual(row['monster'], '#D030001:20')
        self.assertEqual(row['mapName'], 'แท่นตัดเซียน')

    def test_every_row_carries_its_own_id(self):
        for key, row in self.table.items():
            self.assertEqual(row['taofaid'], key)

    def test_game_config_caches_the_table(self):
        cfg = GameConfig(DEFAULT_CONFIG_DIR)
        first = cfg.taofa_table()
        self.assertEqual(len(first), 90)
        self.assertIs(cfg.taofa_table(), first)


class TaofaLoaderEdgeTest(unittest.TestCase):
    def test_missing_config_dir_gives_an_empty_table(self):
        cfg = GameConfig(os.path.join(os.path.dirname(__file__), 'no-such-config'))
        self.assertEqual(cfg.taofa_table(), {})


if __name__ == '__main__':
    unittest.main()

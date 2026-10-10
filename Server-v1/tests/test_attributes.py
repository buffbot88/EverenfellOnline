"""Equipment attribute chain and 12000 formula tests (evidence: jar bytecode + live oracle)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game.attributes import _gongji, entry_attribute_map
from game.config import (DEFAULT_CONFIG_DIR, GameConfig, parse_item_attributes)

# The captured role fu0UR1-0-1-1's equipped rows, as stored in the legacy
# role_equip_slot table (goods_id, rare_level, attributes blob).
CAPTURED_GEAR = [
    ('zj0021', 1, '{"fjattrstr":"{}","jjfailcount":0,"qhcount":2,'
                  '"qhxingxing":"[[1,1],[2,1]]"}'),
    ('zj0201', 2, '{"fjattrstr":"{}","jjfailcount":0,"qhcount":3,'
                  '"qhxingxing":"[[1,1],[2,1],[3,1]]"}'),
    ('zj0202', 2, '{"fjattrstr":"{}","jjfailcount":0,"qhcount":3,'
                  '"qhxingxing":"[[1,1],[2,1],[3,1]]"}'),
    ('zj0209', 2, '{"fjattrstr":"{}","jjfailcount":0,"qhcount":3,'
                  '"qhxingxing":"[[1,1],[2,1],[3,1]]"}'),
    ('zj0210', 2, '{"fjattrstr":"{}","jjfailcount":0,"qhcount":3,'
                  '"qhxingxing":"[[1,1],[2,1],[3,1]]"}'),
    ('zj0212', 2, '{"fjattrstr":"{}","jjfailcount":0,"qhcount":3,'
                  '"qhxingxing":"[[1,1],[2,1],[3,1]]"}'),
    ('zj0213', 2, '{"fjattrstr":"{}","jjfailcount":0,"qhcount":3,'
                  '"qhxingxing":"[[1,1],[2,1],[3,1]]"}'),
    ('zj0214', 2, '{"fjattrstr":"{}","jjfailcount":0,"qhcount":3,'
                  '"qhxingxing":"[[1,1],[2,1],[3,1]]"}'),
    ('zj0416', 3, '{"fjattrstr":"{\\"1\\":\\"9@5\\",\\"2\\":\\"11@5\\",'
                  '\\"3\\":\\"13@5\\",\\"4\\":\\"15@5\\"}","jjfailcount":0,'
                  '"qhcount":0}'),
    ('zj0615', 4, '{"fjattrstr":"{\\"1\\":\\"8@5\\"}","jjfailcount":0,'
                  '"qhcount":0}'),
]


def config_dir():
    return os.path.normpath(os.path.join(os.path.dirname(__file__), '..',
                                         DEFAULT_CONFIG_DIR))


def gear_items():
    return [{'goods_id': goods, 'rare_level': rare, 'attributes': attrs}
            for goods, rare, attrs in CAPTURED_GEAR]


class ItemAttributeParseTest(unittest.TestCase):
    def test_stars_and_fujia_ids(self):
        stars, fujia = parse_item_attributes(CAPTURED_GEAR[9][2])
        self.assertEqual(stars, [])
        self.assertEqual(fujia, [(8, 5)])
        stars, fujia = parse_item_attributes(CAPTURED_GEAR[8][2])
        self.assertEqual(stars, [])
        self.assertEqual(fujia, [(9, 5), (11, 5), (13, 5), (15, 5)])

    def test_escaped_blob_still_yields_stars(self):
        stars, fujia = parse_item_attributes(CAPTURED_GEAR[1][2])
        self.assertEqual(stars, [1, 2, 3])
        self.assertEqual(fujia, [])

    def test_empty_blob(self):
        self.assertEqual(parse_item_attributes(None), ([], []))
        self.assertEqual(parse_item_attributes(''), ([], []))


class EquipAttributeChainTest(unittest.TestCase):
    """EquipFuJiaAttributeConfig base * Njichubili + starN<attr> * Njichubili over the captured gear."""

    def setUp(self):
        self.cfg = GameConfig(config_dir())
        self.map = self.cfg.equip_attribute_map(gear_items())

    def test_captured_gear_totals(self):
        # Every item resolves in ZhuangBeiFuJiaShuXingBiao (10/10 on the live table).
        self.assertEqual(len(self.cfg.equip_table()) > 0, True)
        self.assertAlmostEqual(self.map['physicdamage'], 127.8, places=6)
        self.assertAlmostEqual(self.map['physicdefence'], 42.8, places=6)
        self.assertAlmostEqual(self.map['critical'], 16.65, places=6)
        self.assertAlmostEqual(self.map['volt'], 16.65, places=6)
        self.assertAlmostEqual(self.map['attackrate'], 130.0, places=6)
        self.assertAlmostEqual(self.map['hitpoints'], 252.0, places=6)
        self.assertNotIn('velocity', self.map)

    def test_rank_rate_scales_the_item(self):
        one = [{'goods_id': 'zj0201', 'rare_level': 2, 'attributes': ''}]
        rate2 = self.cfg.equip_attribute_map(one)['physicdamage']
        one[0]['rare_level'] = 3
        rate3 = self.cfg.equip_attribute_map(one)['physicdamage']
        self.assertAlmostEqual(rate2, rate3 * 0.9, places=6)

    def test_unknown_goods_is_skipped_not_faked(self):
        self.assertEqual(self.cfg.equip_attribute_map([{'goods_id': 'nope'}]), {})

    def test_fujia_random_lookup_keys_on_id_and_level(self):
        affix = self.cfg.fujia_attribute_map([(8, 5)], 4)
        self.assertAlmostEqual(affix.get('mb', 0.0), 0.02, places=6)
        affix = self.cfg.fujia_attribute_map(
            [(9, 5), (11, 5), (13, 5), (15, 5)], 3)
        for key in ('mbdk', 'yxdk', 'bhdk', 'xxdk'):
            self.assertAlmostEqual(affix.get(key, 0.0), 0.015, places=6)
        self.assertEqual(self.cfg.fujia_attribute_map([(8, 5)], 99), {})

    def test_shuxingdan_pill_row(self):
        self.assertEqual(self.cfg.shuxingdan_attribute_map(['sm_001']),
                         {'hitpoints': 20.0})


class FormulaTest(unittest.TestCase):
    def test_gongji_matches_the_jar_arithmetic(self):
        # GongJiFormula.refreshAttribute: base*(1+perdamage+effect6) + effect5.
        self.assertEqual(_gongji(800.0), 800.0)
        self.assertEqual(_gongji(800.0, 0.0, 0.5, 10.0), 800.0 * 1.5 + 10.0)
        self.assertEqual(_gongji(0.0, 0.0, 0.0, 0.0), 1.0)   # floor

    def test_12000_map_adds_bags_to_the_level_row(self):
        row = {'physicdamage': 800, 'physicdefence': 400, 'critical': 150,
               'volt': 150, 'attackrate': 1, 'velocity': 550, 'dunshudian': 1,
               'mana': 100}
        plain = entry_attribute_map(row)
        self.assertEqual(plain['2'], 800.0)
        self.assertEqual(plain['7'], 550.0)
        gear = {'physicdamage': 127.8, 'physicdefence': 42.8, 'critical': 16.65,
                'volt': 16.65, 'attackrate': 130.0}
        with_gear = entry_attribute_map(row, bags=[gear])
        self.assertAlmostEqual(with_gear['2'], 927.8, places=6)
        self.assertAlmostEqual(with_gear['3'], 442.8, places=6)
        self.assertAlmostEqual(with_gear['4'], 166.65, places=6)
        self.assertAlmostEqual(with_gear['5'], 166.65, places=6)
        self.assertAlmostEqual(with_gear['6'], 131.0, places=6)
        self.assertEqual(with_gear['7'], 550.0)

    def test_effect_slots_reach_the_formula(self):
        row = {'physicdamage': 100, 'dunshudian': 1}
        boosted = entry_attribute_map(row, effect={'6': 0.5, '5': 10.0})
        self.assertAlmostEqual(boosted['2'], 100.0 * 1.5 + 10.0, places=6)

    def test_captured_java_attack_is_level_plus_gear_plus_the_other_bags(self):
        """Java sent 2049.8 for this role; level 800 + gear 127.8 leaves 1122.0
        from bags this port does not cover yet (meiren/titles/buffs), the exact
        figure meiren.jat carries for nvwa075."""
        row = {'physicdamage': 800, 'physicdefence': 400, 'critical': 150,
               'volt': 150, 'attackrate': 1, 'velocity': 550, 'dunshudian': 1}
        bags = [{'physicdamage': 127.8}, {'physicdamage': 1122.0}]
        self.assertAlmostEqual(entry_attribute_map(row, bags=bags)['2'],
                               2049.8, places=4)


if __name__ == '__main__':
    unittest.main()

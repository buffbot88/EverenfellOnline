"""Golden tests for game/mapdat.py (client map.dat + EngineVO externalizable)."""
import glob
import json
import os
import unittest

from game.mapdat import ENGINEVO_INTS, ENGINEVO_TAG, load_map_dat

TREE = os.path.join('..', 'reference', 'TonNgoKhong', 'server', 'config', 'game')
GOLDEN = os.path.join(os.path.dirname(__file__), 'data', 'path_mm_golden.json')


def map_dat(mid):
    return os.path.join(TREE, 'map_config', str(mid), 'map.dat')


def needs_tree():
    return os.path.isdir(os.path.join(TREE, 'map_config'))


class TestMap0ExtHeader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not needs_tree():
            raise unittest.SkipTest('legacy config tree absent')
        cls.m = load_map_dat(map_dat(0))

    def test_tag_ints_flag(self):
        self.assertEqual(self.m['enginevo']['tag'], ENGINEVO_TAG)
        self.assertEqual(self.m['enginevo']['flag'], 1)
        self.assertEqual(self.m['enginevo']['ints'], ENGINEVO_INTS)

    def test_grid_matches_path_golden(self):
        with open(GOLDEN) as f:
            golden = json.load(f)
        w, h, _cells = golden['0']
        grid = self.m['enginevo']['items'][0]
        self.assertEqual(set(grid.keys()), {'ba', 'h', 'w'})
        self.assertEqual(len(grid['ba']), w * h)
        self.assertEqual((grid['w'], grid['h']), (w, h))

    def test_layerinfo_section_and_name(self):
        items = self.m['enginevo']['items']
        self.assertIn(('section', 'layerinfo'), items)
        strs = [v for v in items if isinstance(v, str)]
        self.assertIn('凌霄殿外', strs)

    def test_effects_indexed_by_position(self):
        """Effect ids equal their wrapper keys: proves string-table alignment."""
        wraps = [v for v in self.m['enginevo']['items']
                 if isinstance(v, dict) and v and all(
                     k.isdigit() for k in v.keys())]
        self.assertTrue(wraps)
        wrap = wraps[0]
        for k in sorted(wrap, key=int)[:8]:
            self.assertEqual(wrap[k].get('id'), k)

    def test_file_tail_is_ext_not_outer(self):
        """Map 0 has no complete outer tail (only 2 values after the wrapper)."""
        self.assertIsNone(self.m['outer'])
        self.assertFalse(self.m['complete'])
        items = self.m['enginevo']['items']
        self.assertEqual(items[-2], 'com.youbt.game.tbg.map.MapModel')
        self.assertEqual(self.m['ext_end'], self.m['size'])


class TestAllMapDat(unittest.TestCase):
    def test_every_file_parses_past_the_stop_point(self):
        if not needs_tree():
            raise unittest.SkipTest('legacy config tree absent')
        files = sorted(glob.glob(os.path.join(TREE, 'map_config', '*', 'map.dat')))
        self.assertGreaterEqual(len(files), 116)
        bad, outer = [], []
        for f in files:
            try:
                m = load_map_dat(f)
            except Exception as e:  # survey must report, not stop
                bad.append((os.path.basename(os.path.dirname(f)), repr(e)[:80]))
                continue
            if m['outer'] is not None:
                outer.append(os.path.basename(os.path.dirname(f)))
        self.assertEqual(bad, [])
        self.assertEqual(outer, [])


if __name__ == '__main__':
    unittest.main()

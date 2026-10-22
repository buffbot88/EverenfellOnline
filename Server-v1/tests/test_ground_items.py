import unittest

from game.config import GameConfig
from game.ground_items import (GroundItemStore, can_pick_up, OWNER_WINDOW_MS,
                               DEFAULT_DURATION_SECONDS)


class GoodsPlacementTests(unittest.TestCase):
    """AoiStage.getSurroundValidPoint(point, true, GOODS) on real map 7."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = GameConfig()

    def test_free_start_tile_wins(self):
        self.assertEqual(
            self.cfg.surround_valid_point_for_goods('7', 27, 28), (27, 28))

    def test_taken_start_tile_uses_first_free_surround(self):
        self.assertEqual(
            self.cfg.surround_valid_point_for_goods('7', 27, 28, [(27, 28)]),
            (28, 28))

    def test_unwalkable_start_tile_places_nothing(self):
        self.assertIsNone(
            self.cfg.surround_valid_point_for_goods('7', 11, 10))

    def test_unknown_map_places_nothing(self):
        self.assertIsNone(
            self.cfg.surround_valid_point_for_goods('no-such-map', 0, 0))


class CanPickUpTests(unittest.TestCase):
    def test_owner_window_opens_after_20_seconds(self):
        store = GroundItemStore()
        item = store.add('hpadd002', 1, 'map1', 3, 4, now_ms=1000,
                         owner_id='r1', owner_team_id='t1')
        self.assertFalse(can_pick_up(item, 'r2', 'tX', 1000 + OWNER_WINDOW_MS))
        self.assertTrue(can_pick_up(item, 'r2', 'tX', 1000 + OWNER_WINDOW_MS + 1))

    def test_owner_and_team_may_pick_up_inside_window(self):
        store = GroundItemStore()
        item = store.add('hpadd002', 1, 'map1', 3, 4, now_ms=0,
                         owner_id='r1', owner_team_id='t1')
        self.assertTrue(can_pick_up(item, 'r1', None, 5))
        self.assertTrue(can_pick_up(item, 'r9', 't1', 5))
        self.assertFalse(can_pick_up(item, 'r9', 't2', 5))

    def test_null_owner_is_open_to_everyone(self):
        store = GroundItemStore()
        item = store.add('hpadd002', 1, 'map1', 3, 4, now_ms=0)
        self.assertTrue(can_pick_up(item, 'anyone', None, 5))


class GroundItemStoreTests(unittest.TestCase):
    def test_ids_are_unique(self):
        store = GroundItemStore()
        ids = {store.add('hpadd002', 1, 'm', 0, 0, now_ms=0).id for _ in range(50)}
        self.assertEqual(len(ids), 50)

    def test_expiry_uses_default_lifetime_and_removes_once(self):
        store = GroundItemStore()
        item = store.add('hpadd002', 1, 'm', 0, 0, now_ms=0)
        before = DEFAULT_DURATION_SECONDS * 1000 - 1
        self.assertEqual(store.expire(before), [])
        gone = store.expire(DEFAULT_DURATION_SECONDS * 1000)
        self.assertEqual([i.id for i in gone], [item.id])
        self.assertEqual(store.expire(10 ** 9), [])
        self.assertIsNone(store.get(item.id))

    def test_remove_is_one_shot(self):
        store = GroundItemStore()
        item = store.add('hpadd002', 1, 'm', 0, 0, now_ms=0)
        self.assertIsNotNone(store.remove(item.id))
        self.assertIsNone(store.remove(item.id))

    def test_items_are_scoped_to_their_map(self):
        store = GroundItemStore()
        a = store.add('hpadd002', 1, 'map1', 0, 0, now_ms=0)
        store.add('mpadd002', 1, 'map2', 0, 0, now_ms=0)
        self.assertEqual([i.id for i in store.on_map('map1')], [a.id])

    def test_custom_duration_overrides_default(self):
        store = GroundItemStore()
        item = store.add('hpadd002', 1, 'm', 0, 0, now_ms=0, duration_seconds=5)
        self.assertEqual(item.expires_at_ms, 5000)


if __name__ == '__main__':
    unittest.main()

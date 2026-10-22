"""Ground-item pickup to inventory (RoleBehaviourServiceImpl.goodsPickUp).

Evidence: dntg_start.jar bytecode (RoleBehaviourAction.pickUp,
RoleBehaviourServiceImpl.goodsPickUp, Goods.checkIdentity,
GoodsFactory/Goods.getMsgData, Goods.enterStageHandle, StageServiceImpl
.goodsEnterStage/goodsDisappear, StageDropOutput.formatDrop,
StageContainer.add/removeItemModel, BagExportServiceImpl
checkPutInBag1/putInBag1/notifyClient, BagServiceImpl.checkBagSlots1,
putOneGoodsInBag1/canStack/getOneSlotNum, ItemCreatorServiceImpl
getBind/calGoodsExpireTime/getGoodsRareLevel, MonsterConfigExportServiceImpl
.createRule, IBagExportService/IBagService signatures).

Verified Java rules reproduced here:
- C:30103 carries [itemId string]; S:30103 answers [0] on any failure and
  [1, goodsId, count, itemId] on success (money branch included).
- No distance, alive-state, or extra expiry pre-check exists in the service:
  a missing element (picked up, or removed by the S:GOODS_DIS leave) fails.
- checkIdentity: open after 20s (strictly greater), else owner id or owner
  team id must match; null owner is open to everyone.
- The lookup is stage-scoped (this port: the item's map must equal the
  role's map).
- checkPutInBag1: an empty bag slot (capacity minus rows in 1..150) always
  fits; otherwise remaining count must stack into same
  goods/bind/expire rows with room under maxstack.
- putOneGoodsInBag1: stack into same-goods rows in slot order up to
  maxstack, then one new row at the first free slot in 1..capacity.
- putInBag1(..., true) notifies: 30105 [formartMap] for the new row, then
  30104 [[[bagId, count]]] per stacked row (notifyClient order).
- Drop bind for hpadd002 is 0 (drop2sp has no bind marker, so DropRule
  .isBind is false; obtainLocked is 0, so getBind yields 0); expire 0
  (duration 0), rare 0 and itemLevel 20 come from the goods row, and a
  non-equip item carries no attributes blob.

Deliberate deviation: Java removes the ground item (stage.leave) before
putInBag1, so an unknown goods config destroys the drop; this port keeps
the item when the goods id has no config row, so a config gap cannot eat
a drop. Failures anywhere else restore the claimed item to the world.
"""
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2]
               / 'reference' / 'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config' / 'KaiGeFeiYongBiao.jat').is_file()

MID = 'm_7_0'
MAP = '7'


def cmds(frames):
    return [decode(f[4:]) for f in frames]


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class PickupLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = GameConfig(str(REAL_CONFIG))
        cls.tpl = cls.cfg.monster_template('D040001')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, 't.db')
        self.store = Store(self.db_path)
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.store.create_account('foe', hash_password('pw'))
        self.killer_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=31,
            map_id=MAP, map_x=10, map_y=10)
        self.foe_id = self.store.create_character(
            'foe', 'fu1304', 'Foe', job='C', level=31,
            map_id=MAP, map_x=12, map_y=10)
        for rid in (self.killer_id, self.foe_id):
            self.store.save_role_bag_state(rid, bag_capacity=34,
                                           storage_capacity=30)
        self.reg = StageRegistry()
        self.a = self._session('hero', self.killer_id, 1)
        self.b = self._session('foe', self.foe_id, 2)
        self.reg.register(str(self.killer_id), MAP, self.a, x=10, y=10)
        self.reg.register(str(self.foe_id), MAP, self.b, x=12, y=10)

    def _session(self, user, rid, conn_id):
        sess = Session(
            conn_id=conn_id, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0, config=self.cfg, stage_registry=self.reg,
            save_role_state=self.store.update_character_state,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            get_role_bag_slot=self.store.get_role_bag_slot,
            get_role_bag_slot_by_bag_id=
            self.store.get_role_bag_slot_by_bag_id,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            move_role_bag_slot=self.store.move_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            rewrite_role_bag_slots=self.store.rewrite_role_bag_slots,
            save_role_bag_state=self.store.save_role_bag_state)
        sess.authed_user, sess.server_id = user, 'fu1304'
        return sess

    def role(self, sess, user):
        (role,) = self.store.list_roles(user, 'fu1304')
        return dict(role)

    def seed(self, hp=50.0):
        self.a._monster_reg[MID] = {'template': self.tpl, 'map': MAP,
                                    'born': [27, 28], 'pos': [27, 28]}
        self.a._monster_hp[MID] = hp

    def swing(self, sess, role):
        me = {'kind': 'role', 'id': str(role['id']), 'role': role}
        with mock.patch('random.random', return_value=0.5):
            return sess._resolve_fire(me, 'normal003', 0, [MID], None, 1)

    def kill(self, drop_ms=1000):
        """Kill D040001 with both 1% slots firing; returns the hpadd002 item."""
        self.seed()
        with mock.patch('game.protocol.random.randrange', return_value=100):
            with mock.patch.object(Session, '_world_now_ms',
                                   return_value=drop_ms):
                self.swing(self.a, self.role(self.a, 'hero'))
        (item,) = [i for i in self.a._world.ground_items.on_map(MAP)
                   if i.goods_id == 'hpadd002']
        return item

    def bag(self, rid):
        return self.store.get_role_bag_slots(rid, 1, 150)

    def test_kill_pickup_persists_clears_and_cannot_repeat(self):
        item = self.kill()
        self.assertEqual(item.owner_id, str(self.killer_id))
        self.assertEqual(item.bind, 0)
        ok, frames = self.a.pickup_item(self.role(self.a, 'hero'), item.id,
                                        now_ms=2000)
        self.assertTrue(ok)
        got = cmds(frames)
        self.assertEqual(got[0], ['30103', [1, 'hpadd002', 1, item.id]])
        # New-slot award: exactly the 30103 reply plus one 30105 push,
        # and no invented packet ids.
        self.assertEqual([c for c, _b in got], ['30103', '30105'])
        formart = got[1][1][0]
        assoc = formart.get('__assoc__', formart)
        self.assertEqual(assoc['0'], 'hpadd002')
        self.assertEqual(assoc['3'], 1)
        self.assertEqual(assoc['7'], 0)
        rows = self.bag(self.killer_id)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row['goods_id'], row['count'], row['bind'],
                          row['rare_level'], row['item_level'],
                          row['attributes'], row['expire_time']),
                         ('hpadd002', 1, 0, 0, 20, None, 0))
        # The shared item is gone: a repeat pickup fails and adds nothing.
        self.assertIsNone(self.a._world.ground_items.get(item.id))
        ok2, frames2 = self.a.pickup_item(self.role(self.a, 'hero'),
                                          item.id, now_ms=2001)
        self.assertFalse(ok2)
        self.assertEqual(cmds(frames2), [['30103', [0]]])
        self.assertEqual(len(self.bag(self.killer_id)), 1)
        # Reopen the database: the award survives the process boundary.
        self.store.close()
        reopened = Store(self.db_path)
        self.addCleanup(reopened.close)
        back = reopened.get_role_bag_slots(self.killer_id, 1, 150)
        self.assertEqual([(r['goods_id'], r['count']) for r in back],
                         [('hpadd002', 1)])

    def test_stranger_blocked_inside_window_open_after(self):
        item = self.kill(drop_ms=9000)
        foe = self.role(self.b, 'foe')
        ok, frames = self.b.pickup_item(foe, item.id, now_ms=9000 + 19999)
        self.assertFalse(ok)
        self.assertEqual(cmds(frames), [['30103', [0]]])
        # The failed attempt leaves the item for the owner.
        self.assertIsNotNone(self.a._world.ground_items.get(item.id))
        # The 20s window is strict: still protected exactly at the mark.
        ok, _frames = self.b.pickup_item(foe, item.id, now_ms=9000 + 20000)
        self.assertFalse(ok)
        ok, _frames = self.b.pickup_item(foe, item.id, now_ms=9000 + 20001)
        self.assertTrue(ok)
        self.assertEqual(self.bag(self.foe_id)[0]['goods_id'], 'hpadd002')

    def test_wrong_map_and_expired_items_stay_unclaimed(self):
        item = self.kill()
        far = dict(self.role(self.b, 'foe'), map_id='8')
        ok, _frames = self.b.pickup_item(far, item.id, now_ms=2000)
        self.assertFalse(ok)
        self.assertIsNotNone(self.a._world.ground_items.get(item.id))
        end = 1000 + 60 * 1000
        ok, frames = self.a.pickup_item(self.role(self.a, 'hero'), item.id,
                                        now_ms=end)
        self.assertFalse(ok)
        self.assertEqual(cmds(frames), [['30103', [0]]])
        # Lazy expiry removes the item exactly as the S:GOODS_DIS leave would.
        self.assertIsNone(self.a._world.ground_items.get(item.id))

    def test_stack_onto_existing_row_uses_30104_only(self):
        self.store.insert_role_bag_slot(
            self.killer_id, {'slot_num': 3, 'goods_id': 'hpadd002',
                             'count': 5, 'bind': 0, 'expire_time': 0,
                             'rare_level': 0, 'item_level': 20,
                             'attributes': None})
        item = self.kill()
        ok, frames = self.a.pickup_item(self.role(self.a, 'hero'), item.id,
                                        now_ms=2000)
        self.assertTrue(ok)
        got = cmds(frames)
        self.assertEqual([c for c, _b in got], ['30103', '30104'])
        self.assertEqual(got[0], ['30103', [1, 'hpadd002', 1, item.id]])
        rows = self.bag(self.killer_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['count'], 6)
        self.assertEqual(got[1], ['30104', [[[rows[0]['bag_id'], 6]]]])

    def test_full_bag_keeps_the_item(self):
        self.store.save_role_bag_state(self.killer_id, bag_capacity=1,
                                       storage_capacity=30)
        self.store.insert_role_bag_slot(
            self.killer_id, {'slot_num': 1, 'goods_id': 'mpadd002',
                             'count': 1, 'bind': 0, 'expire_time': 0,
                             'rare_level': 0, 'item_level': 20,
                             'attributes': None})
        item = self.kill()
        ok, frames = self.a.pickup_item(self.role(self.a, 'hero'), item.id,
                                        now_ms=2000)
        self.assertFalse(ok)
        self.assertEqual(cmds(frames), [['30103', [0]]])
        kept = self.a._world.ground_items.get(item.id)
        self.assertIsNotNone(kept)
        self.assertEqual(kept.goods_id, 'hpadd002')
        self.assertEqual(self.bag(self.killer_id)[0]['goods_id'], 'mpadd002')

    def test_concurrent_pickups_award_exactly_once(self):
        item = self.kill(drop_ms=5000)
        at = 5000 + 20001  # both eligible: killer by ownership, foe by window
        results = {}
        barrier = threading.Barrier(2)

        def grab(sess, user, key):
            barrier.wait()
            results[key] = sess.pickup_item(
                dict(self.store.list_roles(user, 'fu1304')[0]), item.id,
                now_ms=at)

        threads = [threading.Thread(target=grab, args=(self.a, 'hero', 'a')),
                   threading.Thread(target=grab, args=(self.b, 'foe', 'b'))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), ['a', 'b'])
        oks = [k for k, (ok, _f) in results.items() if ok]
        self.assertEqual(len(oks), 1)
        total = sum(r['count'] for rid in (self.killer_id, self.foe_id)
                    for r in self.bag(rid)
                    if r['goods_id'] == 'hpadd002')
        self.assertEqual(total, 1)
        self.assertIsNone(self.a._world.ground_items.get(item.id))

    def test_failed_write_restores_the_item(self):
        self.store.insert_role_bag_slot(
            self.killer_id, {'slot_num': 3, 'goods_id': 'hpadd002',
                             'count': 198, 'bind': 0, 'expire_time': 0,
                             'rare_level': 0, 'item_level': 20,
                             'attributes': None})
        before = {r['slot_num']: r['count'] for r in
                  self.bag(self.killer_id)}
        world = self.a._world.ground_items
        item = world.add('hpadd002', 5, MAP, 27, 28, now_ms=1000,
                         owner_id=str(self.killer_id), bind=0,
                         duration_seconds=60)
        with mock.patch.object(self.a, 'insert_role_bag_slot',
                               side_effect=RuntimeError('db down')):
            ok, frames = self.a.pickup_item(self.role(self.a, 'hero'),
                                            item.id, now_ms=2000)
        self.assertFalse(ok)
        self.assertEqual(cmds(frames), [['30103', [0]]])
        # Partial stacks rolled back, the item restored under its old id.
        self.assertEqual({r['slot_num']: r['count'] for r in
                          self.bag(self.killer_id)}, before)
        kept = world.get(item.id)
        self.assertIsNotNone(kept)
        self.assertEqual((kept.goods_id, kept.count), ('hpadd002', 5))

    def test_pickup_route_answers_30103_shapes(self):
        # The wire shape nests args: ['30103', [itemId]], like bag_move.
        item = self.kill()
        with mock.patch.object(Session, '_world_now_ms', return_value=2000):
            out = self.a.pickup_goods(['30103', [item.id + 'nope']])
            self.assertEqual(cmds(out), [['30103', [0]]])
            out = self.a.pickup_goods(['30103', [item.id]])
            got = cmds(out)
        self.assertEqual(got[0][0], '30103')
        self.assertEqual(got[0][1][0], 1)
        self.assertIsNone(self.a.pickup_goods(['30103', [123]]))
        self.assertIsNone(self.a.pickup_goods(['30103']))


if __name__ == '__main__':
    unittest.main()

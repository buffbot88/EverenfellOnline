"""Ground-loot network protocol against the original Java wire rules.

Evidence: dntg_start.jar bytecode (RoleBehaviourAction.pickUp,
RoleBehaviourServiceImpl.goodsPickUp, StageServiceImpl.goodsEnterStage /
goodsDisappear, StageDropOutput.formatDrop, Goods.getMsgData /
enterStageHandle / checkIdentity / GoodsFactory.createGoods,
AbsAoiStage.addHandle/deleteHandle, AbsAoiMsgListener.elementEnter /
elementLeave, AoiMsgListener enter/leave commands, StageMsgQueue
StageMsg/ClientMsg, IBagExportService/IBagService, ItemCreatorServiceImpl,
MonsterConfigExportServiceImpl.createRule).

Verified wire rules reproduced here:
- S:DROP_GOODS / S:GOODS_DIS are internal stage messages (StageMsg ->
  send2StageInner), never client packets.
- Appearance is 23004 [goodsMsgData] to the item's 3x3 AOI surround.
- Disappearance (pickup leave, expiry) is 24004 [itemId] to the surround.
- goodsMsgData is the 13-field Goods.getMsgData array: [x, y, goodsId,
  name, itemId, rareLevel, count, ownerId, ownTeamId, dropTimeMs,
  itemLevel, firstDrop, displayName]. Fresh drops report firstDrop 1
  (AOI.add notifies before enterStageHandle clears it); scene snapshots
  of settled items report 0.
- Item ids are opaque unique strings ('goods_' + IdUtil.nextString in
  Java, echoed verbatim by C:30103); ours are process-unique under the
  same contract.
- Pickup replies S:30103 [0] / [1, goodsId, count, itemId], then the bag
  pushes 30105 (new row) / 30104 (stacked row), in notifyClient order.
"""
import os
import sys
import tempfile
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
    return [decode(f[4:]) for f in frames or []]


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class GroundWireTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = GameConfig(str(REAL_CONFIG))
        cls.tpl = cls.cfg.monster_template('D040001')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.store.create_account('foe', hash_password('pw'))
        self.store.create_account('far', hash_password('pw'))
        self.killer_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=31,
            map_id=MAP, map_x=27, map_y=27)
        self.foe_id = self.store.create_character(
            'foe', 'fu1304', 'Foe', job='C', level=31,
            map_id=MAP, map_x=28, map_y=27)
        self.far_id = self.store.create_character(
            'far', 'fu1304', 'Far', job='C', level=31,
            map_id='8', map_x=5, map_y=5)
        for rid in (self.killer_id, self.foe_id, self.far_id):
            self.store.save_role_bag_state(rid, bag_capacity=34,
                                           storage_capacity=30)
        self.reg = StageRegistry()
        self.a = self._session('hero', 1)
        self.b = self._session('foe', 2)
        self.c = self._session('far', 3)
        self.reg.register(str(self.killer_id), MAP, self.a, x=27, y=27)
        self.reg.register(str(self.foe_id), MAP, self.b, x=28, y=27)
        self.reg.register(str(self.far_id), '8', self.c, x=5, y=5)

    def _session(self, user, conn_id):
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

    def role(self, user):
        (role,) = self.store.list_roles(user, 'fu1304')
        return dict(role)

    def drain(self, sess):
        """Raw pushed frames since the last drain (decode with cmds)."""
        with sess.outbox_lock:
            pending, sess.outbox = sess.outbox, []
        return pending

    def kill(self, drop_ms=1000):
        self.a._monster_reg[MID] = {'template': self.tpl, 'map': MAP,
                                    'born': [27, 28], 'pos': [27, 28]}
        self.a._monster_hp[MID] = 50.0
        me = {'kind': 'role', 'id': str(self.killer_id),
              'role': self.role('hero')}
        with mock.patch('random.random', return_value=0.5):
            with mock.patch('game.protocol.random.randrange',
                            return_value=100):
                with mock.patch.object(Session, '_world_now_ms',
                                       return_value=drop_ms):
                    return self.a._resolve_fire(me, 'normal003', 0, [MID],
                                                None, 1)

    def appeard(self, frames):
        return [b for c, b in cmds(frames) if c == '23004']

    def test_kill_appearance_carries_verified_msgdata(self):
        frames = self.kill()
        bodies = self.appeard(frames)
        self.assertEqual(len(bodies), 2)
        (hp,) = [b[0] for b in bodies if b[0][2] == 'hpadd002']
        item = self.a._world.ground_items.get(hp[4])
        self.assertIsNotNone(item)
        # The 13 getMsgData fields, in order, off the live item and config.
        self.assertEqual(hp, [27, 28, 'hpadd002', item and
                              self.cfg.goods_name('hpadd002'),
                              item.id, 0, 1, str(self.killer_id), None,
                              1000, 20, 1, 0])
        self.assertEqual(len(hp), 13)
        self.assertEqual(self.cfg.goods_display_name('hpadd002'), 0)

    def test_peer_sees_same_id_other_map_sees_nothing(self):
        frames = self.kill()
        mine = {b[0][4] for b in self.appeard(frames)}
        pushed = {b[0][4] for b in self.appeard(self.drain(self.b))}
        world = {i.id for i in
                 self.a._world.ground_items.on_map(MAP)}
        # One id per item, identical for killer, peer and authority.
        self.assertEqual(mine, pushed)
        self.assertEqual(mine, world)
        self.assertEqual(len(mine), 2)
        self.assertEqual(cmds(self.drain(self.c)), [])
        self.assertEqual(self.a._world.ground_items.on_map('8'), [])

    def test_pickup_removal_reaches_picker_and_peer_once(self):
        self.kill()
        self.drain(self.b)
        item = next(i for i in
                    self.a._world.ground_items.on_map(MAP)
                    if i.goods_id == 'hpadd002')
        ok, frames = self.a.pickup_item(self.role('hero'), item.id,
                                        now_ms=2000)
        self.assertTrue(ok)
        got = cmds(frames)
        # 30103 reply, 30105 new-row push, then the 24004 removal.
        self.assertEqual([c for c, _b in got],
                         ['30103', '30105', '24004'])
        self.assertEqual(got[0], ['30103', [1, 'hpadd002', 1, item.id]])
        self.assertEqual(got[2], ['24004', [item.id]])
        peer = cmds(self.drain(self.b))
        self.assertEqual(peer, [['24004', [item.id]]])
        # A repeat pickup fails silently: [0] only, no second removal.
        ok, frames = self.a.pickup_item(self.role('hero'), item.id,
                                        now_ms=2001)
        self.assertFalse(ok)
        self.assertEqual(cmds(frames), [['30103', [0]]])
        self.assertEqual(self.drain(self.b), [])

    def test_unknown_pickup_id_fails_without_removal(self):
        self.kill()
        self.drain(self.b)
        ok, frames = self.a.pickup_item(self.role('hero'), 'g9999',
                                        now_ms=2000)
        self.assertFalse(ok)
        self.assertEqual(cmds(frames), [['30103', [0]]])
        self.assertEqual(cmds(self.drain(self.b)), [])
        self.assertEqual(len(self.a._world.ground_items.on_map(MAP)), 2)

    def test_expiry_removal_fires_exactly_once(self):
        self.kill(drop_ms=1000)
        end = 1000 + 60 * 1000
        with mock.patch.object(Session, '_world_now_ms', return_value=end):
            mine = cmds(self.a.ai_tick() or ())
        gone = [b[0] for c, b in mine if c == '24004']
        self.assertEqual(len(gone), 2)
        peer = [b[0] for c, b in cmds(self.drain(self.b)) if c == '24004']
        # Both sessions saw the same two authoritative ids, exactly once.
        self.assertEqual(sorted(peer), sorted(gone))
        self.assertEqual(sorted(set(gone)), sorted(gone))
        # The peer's round in the same cycle removes nothing twice.
        with mock.patch.object(Session, '_world_now_ms', return_value=end):
            rest = cmds(self.b.ai_tick() or ())
        self.assertFalse([1 for c, _b in rest if c == '24004'])
        self.assertEqual(self.a._world.ground_items.on_map(MAP), [])

    def test_late_joiner_sees_settled_items_only(self):
        self.kill(drop_ms=1000)
        late = dict(self.role('foe'), map_x=27, map_y=27)
        with mock.patch.object(Session, '_world_now_ms', return_value=2000):
            frames = self.b.scene_tail_frames(late, MAP)
        bodies = [b for c, b in cmds(frames) if c == '23004']
        self.assertEqual(len(bodies), 2)
        for body in bodies:
            # Settled items no longer report firstDrop.
            self.assertEqual(body[0][11], 0)
            self.assertIsNotNone(
                self.a._world.ground_items.get(body[0][4]))
        with mock.patch.object(Session, '_world_now_ms',
                               return_value=1000 + 60 * 1000):
            frames = self.b.scene_tail_frames(late, MAP)
        self.assertFalse([1 for c, _b in cmds(frames) if c == '23004'])

    def test_failed_write_emits_no_removal_and_keeps_item(self):
        self.kill()
        self.drain(self.b)  # appearance pushes are not removal events
        item = next(i for i in
                    self.a._world.ground_items.on_map(MAP)
                    if i.goods_id == 'hpadd002')
        with mock.patch.object(self.a, 'insert_role_bag_slot',
                               side_effect=RuntimeError('db down')):
            ok, frames = self.a.pickup_item(self.role('hero'), item.id,
                                            now_ms=2000)
        self.assertFalse(ok)
        self.assertEqual(cmds(frames), [['30103', [0]]])
        self.assertEqual(cmds(self.drain(self.b)), [])
        kept = self.a._world.ground_items.get(item.id)
        self.assertIsNotNone(kept)
        self.assertEqual(self.store.get_role_bag_slots(
            self.killer_id, 1, 150), [])

    def test_stacked_pickup_orders_30104_before_removal(self):
        self.store.insert_role_bag_slot(
            self.killer_id, {'slot_num': 3, 'goods_id': 'hpadd002',
                             'count': 5, 'bind': 0, 'expire_time': 0,
                             'rare_level': 0, 'item_level': 20,
                             'attributes': None})
        self.kill()
        self.drain(self.b)
        item = next(i for i in
                    self.a._world.ground_items.on_map(MAP)
                    if i.goods_id == 'hpadd002')
        ok, frames = self.a.pickup_item(self.role('hero'), item.id,
                                        now_ms=2000)
        self.assertTrue(ok)
        got = cmds(frames)
        self.assertEqual([c for c, _b in got],
                         ['30103', '30104', '24004'])
        self.assertEqual(got[2], ['24004', [item.id]])


if __name__ == '__main__':
    unittest.main()

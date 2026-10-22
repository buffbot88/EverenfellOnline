"""Command 30000 getBagGoods: BagServiceImpl.getBagGoods -> Object[5].

Evidence: jar bytecode (BagEasyAction.getBagGoods, BagServiceImpl.getBagGoods,
getBagLockIndexVos/getStorageLockIndexVos/getBagGrowUpTime,
StoreGoodsOutput.formart, GoodsCategoryUtil, OpenSlotConfigExportServiceImpl)
plus live MySQL rows for role fu0UR1-0-1-1 (36 bag rows, state 144/31) and the
fresh-role state (34/30). No 30000 capture exists, so expectations are the
bytecode shape filled with real data, never invented numbers.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode  # noqa: E402
from game.amf3 import encode as amf3_encode  # noqa: E402
from game.cipher import SimpleEncrypt  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session, frame  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2]
               / 'reference' / 'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config' / 'KaiGeFeiYongBiao.jat').is_file()

# Live role_bag_slot rows for fu0UR1-0-1-1 (bag_id, slot, goods, count, bind,
# expire, rare, item, attributes).
SILVER50 = {'bag_id': 'fu0RBS1-0-1-77', 'slot_num': 36, 'goods_id': 'silver50',
            'count': 1, 'bind': 1, 'expire_time': 0, 'rare_level': 3,
            'item_level': 1, 'attributes': None}
SKILLBOOK = {'bag_id': 'b1', 'slot_num': 40, 'goods_id': 'zuoqijineng1',
             'count': 1, 'bind': 1, 'expire_time': 0, 'rare_level': 0,
             'item_level': 1, 'attributes': '{"exp":0}'}
GEAR = {'bag_id': 'b2', 'slot_num': 41, 'goods_id': 'zj0210',
        'count': 1, 'bind': 0, 'expire_time': 0, 'rare_level': 2,
        'item_level': 1,
        'attributes': '{"fjattrstr":"{}","jjfailcount":0,"qhcount":2,'
                      '"qhxingxing":"[[1,1],[2,1]]"}'}


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class BagConfigTest(unittest.TestCase):
    def setUp(self):
        self.cfg = GameConfig(str(REAL_CONFIG))

    def test_goods_categories_match_bytecode_branches(self):
        self.assertEqual(self.cfg.goods_category('zj0415'), '20')
        self.assertEqual(self.cfg.goods_category('zuoqijineng1'), '100')
        self.assertEqual(self.cfg.goods_category('silver50'), '16')
        self.assertIsNone(self.cfg.goods_category('no-such-goods'))

    def test_kaige_max_slots(self):
        self.assertEqual(self.cfg.kaige_max_slot_num('B'), 144)
        self.assertEqual(self.cfg.kaige_max_slot_num('C'), 200)

    def test_kaige_init_slots_match_fresh_live_rows(self):
        # Live role_bag_state for an untouched role carries 34/30.
        self.assertEqual(self.cfg.kaige_init_slot_num('B'), 34)
        self.assertEqual(self.cfg.kaige_init_slot_num('C'), 30)

    def test_kaige_row_carries_num_and_open_time(self):
        row = self.cfg.kaige_row('B', 35)
        self.assertEqual(int(row['id']), 35)
        self.assertTrue(float(row['needtime']) > 0)


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class BagGoodsFrameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            get_role_bag_slot=self.store.get_role_bag_slot,
            get_role_bag_slot_by_bag_id=
            self.store.get_role_bag_slot_by_bag_id,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            move_role_bag_slot=self.store.move_role_bag_slot,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'

    def reply(self):
        out = self.sess.bag_goods()
        self.assertIsNotNone(out)
        return decode(out[4:])

    @staticmethod
    def assoc(m):
        """Unwrap the decoder's dynamic-object envelope around formart maps."""
        return m.get('__assoc__', m)

    def test_capped_role_envelope_matches_live_state(self):
        self.store.save_role_bag_slots(self.role_id, [SILVER50])
        # Live state for fu0UR1-0-1-1: capacities at the maxes.
        self.store.save_role_bag_state(
            self.role_id, bag_capacity=144, bag_slot_time=1548096,
            bag_update_slot_time=1394468956781, storage_capacity=31,
            storage_slot_time=2428331,
            storage_update_slot_time=1394468076546)
        cmd, obj = self.reply()
        self.assertEqual(cmd, '30000')
        self.assertEqual(len(obj), 5)
        obj[0] = [self.assoc(m) for m in obj[0]]
        self.assertEqual(len(obj[0]), 1)
        self.assertIsNone(obj[1])    # bag lock VO: 144 >= max 144
        self.assertEqual(obj[2], 144)
        self.assertEqual(obj[3][0], 32)   # storage 31 < max 200
        self.assertEqual(obj[4], 200)

    def test_maxed_storage_sends_null_lock_vo(self):
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=200)
        _, obj = self.reply()
        self.assertIsNone(obj[1])
        self.assertIsNone(obj[3])

    def test_consumable_map_is_exact(self):
        self.store.save_role_bag_slots(self.role_id, [SILVER50])
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=200)
        _, obj = self.reply()
        self.assertEqual(self.assoc(obj[0][0]), {
            '0': 'silver50', '1': 'fu0RBS1-0-1-77', '2': 36, '3': 1,
            '4': str(self.role_id), '5': 1, '6': 3, '7': 1, '8': 0,
            '9': None, '10': 0, '11': None, '12': 0, '13': '',
            '14': None, '15': 0, '16': 0, '17': 0})

    def test_skillbook_exp_cell_defaults_to_zero(self):
        self.store.save_role_bag_slots(self.role_id, [SKILLBOOK])
        _, obj = self.reply()
        m = self.assoc(obj[0][0])
        self.assertEqual(m['15'], 0)
        self.assertEqual(m['17'], 0)

    def test_gear_map_carries_qianghua_cells(self):
        self.store.save_role_bag_slots(self.role_id, [GEAR])
        _, obj = self.reply()
        m = self.assoc(obj[0][0])
        self.assertEqual(m['0'], 'zj0210')
        self.assertEqual(m['10'], 2)   # two [*,1] star pairs
        self.assertEqual(m['14'], [1, 1])   # star values, qhcount-length
        self.assertIsInstance(m['12'], int)   # zhanli via equip fight

    def test_empty_bag_sends_null_goods(self):
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=200)
        _, obj = self.reply()
        self.assertIsNone(obj[0])
        self.assertIsNone(obj[1])
        self.assertIsNone(obj[3])

    def test_storage_goods_frame(self):
        row = dict(SILVER50, slot_num=301, bag_id='s1')
        self.store.save_role_bag_slots(self.role_id, [SILVER50, row])
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=31)
        out = self.sess.storage_goods()
        self.assertIsNotNone(out)
        cmd, obj = decode(out[4:])
        self.assertEqual(cmd, '30002')
        self.assertEqual(len(obj), 3)
        # Only the 301..500 slot is listed; the bag slot is excluded.
        self.assertEqual(len(obj[0]), 1)
        self.assertEqual(self.assoc(obj[0][0])['2'], 301)
        self.assertEqual(obj[1][0], 32)
        self.assertEqual(obj[2], 200)

    def test_empty_storage_sends_null_goods(self):
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=200)
        out = self.sess.storage_goods()
        cmd, obj = decode(out[4:])
        self.assertEqual(cmd, '30002')
        self.assertEqual(obj, [None, None, 200])

    def test_fresh_role_lock_vos_point_at_next_slot(self):
        # Untouched live rows carry 34/30 with old timers: the countdown is
        # long over, so unlockAt is ~now for slots 35 and 31.
        self.store.save_role_bag_state(
            self.role_id, bag_capacity=34, bag_slot_time=6114,
            bag_update_slot_time=1791513150973, storage_capacity=30,
            storage_slot_time=6114, storage_update_slot_time=1791513150973)
        before = int(time.time() * 1000)
        _, obj = self.reply()
        self.assertEqual(obj[1][0], 35)
        self.assertEqual(obj[3][0], 31)
        self.assertTrue(before - 60000 <= obj[1][1] <= before + 60000)
        self.assertTrue(before - 60000 <= obj[3][1] <= before + 60000)


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class BagMoveTest(unittest.TestCase):
    """Command 30004 moveGoodses: zones, stack merge, swap, error codes.

    Shapes from BagServiceImpl.moveGoodses/checkCanMove/checkBagSlotIsActived
    bytecode; BagErroeCodes 430206/430202 from the jar; slot zones from
    BagUtil (bag 1..150, storage 301..500, zuoqi -104..-101, xunbao
    1001..2000); maxstack from goods.jat (bscl2 2000, feixie 999).
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            get_role_bag_slot=self.store.get_role_bag_slot,
            get_role_bag_slot_by_bag_id=
            self.store.get_role_bag_slot_by_bag_id,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            move_role_bag_slot=self.store.move_role_bag_slot,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        # Live-like state: bag full, storage nearly shut (only 301..331 open).
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=31)

    def row(self, slot, goods, count=1, bag_id=None, bind=1):
        return {'slot_num': slot, 'goods_id': goods, 'count': count,
                'bag_id': bag_id or f'id{slot}', 'bind': bind,
                'expire_time': 0, 'rare_level': 0, 'item_level': 1,
                'attributes': None}

    def move(self, bag_id, frm, to):
        out = self.sess.bag_move([30004, [bag_id, frm, to]])
        return decode(out[4:]) if out is not None else None

    def test_move_to_empty_slot(self):
        self.store.save_role_bag_slots(self.role_id, [self.row(36, 'silver50')])
        self.assertEqual(self.move('id36', 36, 37),
                         ['30004', [1, ['id36', 37, 1, 1], None]])
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 36))
        got = self.store.get_role_bag_slot(self.role_id, 37)
        self.assertEqual(got['goods_id'], 'silver50')

    def test_swap_with_occupied_slot(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(36, 'silver50'), self.row(37, 'feixie')])
        self.assertEqual(self.move('id36', 36, 37),
                         ['30004', [1, ['id36', 37, 1, 1],
                                   ['id37', 36, 1, 1]]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 36)['goods_id'],
            'feixie')

    def test_full_stack_merge_deletes_source(self):
        # bscl2 maxstack 2000: 800 + 800 fits, source row is deleted.
        self.store.save_role_bag_slots(
            self.role_id, [self.row(36, 'bscl2', 800),
                           self.row(37, 'bscl2', 800)])
        self.assertEqual(self.move('id36', 36, 37),
                         ['30004', [1, ['id36', 36, 0, 1],
                                   ['id37', 37, 1600, 1]]])
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 36))
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 37)['count'], 1600)

    def test_partial_stack_fill_leaves_remainder(self):
        # feixie maxstack 999: 800 + 800 overflows, target tops up.
        self.store.save_role_bag_slots(
            self.role_id, [self.row(36, 'feixie', 800),
                           self.row(37, 'feixie', 800)])
        self.assertEqual(self.move('id36', 36, 37),
                         ['30004', [1, ['id36', 36, 601, 1],
                                   ['id37', 37, 999, 1]]])

    def test_same_slot_is_silent(self):
        self.store.save_role_bag_slots(self.role_id, [self.row(36, 'silver50')])
        self.assertIsNone(self.move('id36', 36, 36))

    def test_cross_zone_move_is_invalid(self):
        self.store.save_role_bag_slots(self.role_id, [self.row(36, 'silver50')])
        self.assertEqual(self.move('id36', 36, 600),
                         ['30004', [0, 430206]])

    def test_unknown_row_is_invalid(self):
        self.assertEqual(self.move('nope', 36, 37),
                         ['30004', [0, 430206]])

    def test_slot_mismatch_is_invalid(self):
        self.store.save_role_bag_slots(self.role_id, [self.row(36, 'silver50')])
        self.assertEqual(self.move('id36', 37, 38),
                         ['30004', [0, 430206]])

    def test_locked_storage_slot_is_rejected(self):
        self.store.save_role_bag_slots(self.role_id, [self.row(301, 'silver50')])
        # Storage 31 opens 301..331; slot 400 is locked.
        self.assertEqual(self.move('id301', 301, 400),
                         ['30004', [0, 430202]])

    def test_bag_to_storage_move(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(36, 'silver50'), self.row(301, 'feixie')])
        self.assertEqual(self.move('id36', 36, 302),
                         ['30004', [1, ['id36', 302, 1, 1], None]])


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class BagSplitDeleteTest(unittest.TestCase):
    """Commands 30100 splitGoods and 30102 deleteBagGoods.

    Split shapes from splitGoods/checkSplitGoods bytecode (30104 count
    push, 30105 formart push, null 30100 reply) and BagErroeCodes; delete
    from deleteBagGoods/removeGoodsById (missing rows still reply [1, []]).
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            get_role_bag_slot=self.store.get_role_bag_slot,
            get_role_bag_slot_by_bag_id=
            self.store.get_role_bag_slot_by_bag_id,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            move_role_bag_slot=self.store.move_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=31)

    def row(self, slot, goods, count=1, bag_id=None, bind=1):
        return {'slot_num': slot, 'goods_id': goods, 'count': count,
                'bag_id': bag_id or f'id{slot}', 'bind': bind,
                'expire_time': 0, 'rare_level': 0, 'item_level': 1,
                'attributes': None}

    def split(self, *args):
        out = self.sess.bag_split([30100, list(args)])
        if out is None:
            return None
        if isinstance(out, tuple):
            return [decode(f[4:]) for f in out]
        return decode(out[4:])

    def test_split_pushes_count_formart_and_null_reply(self):
        self.store.save_role_bag_slots(self.role_id,
                                       [self.row(36, 'bscl2', 800)])
        frames = self.split('id36', 37, 37, 300)
        self.assertEqual([f[0] for f in frames], ['30104', '30105', '30100'])
        self.assertEqual(frames[0][1], [[['id36', 500]]])
        new_map = frames[1][1][0]
        new_map = new_map.get('__assoc__', new_map)
        self.assertEqual(new_map['0'], 'bscl2')
        self.assertEqual(new_map['2'], 37)
        self.assertEqual(frames[2][1], None)
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 36)['count'], 500)
        new_row = self.store.get_role_bag_slot(self.role_id, 37)
        self.assertEqual(new_row['count'], 300)
        self.assertEqual(new_row['goods_id'], 'bscl2')

    def test_split_guards_and_errors(self):
        self.store.save_role_bag_slots(self.role_id,
                                       [self.row(36, 'bscl2', 800)])
        # Silent guards: short args, empty id, bad toSlot/count.
        self.assertIsNone(self.sess.bag_split([30100, ['id36', 37]]))
        self.assertIsNone(self.split('', 37, 37, 300))
        self.assertIsNone(self.split('id36', 37, 0, 300))
        self.assertIsNone(self.split('id36', 37, 37, -1))
        # Unknown row, slot-arg mismatch, over-count, occupied, locked.
        self.assertEqual(self.split('nope', 37, 37, 300),
                         ['30100', [0, 430201]])
        self.assertEqual(self.split('id36', 36, 37, 300),
                         ['30100', [0, 430206]])
        self.assertEqual(self.split('id36', 37, 37, 800),
                         ['30100', [0, 430205]])
        self.store.save_role_bag_slots(
            self.role_id, [self.row(36, 'bscl2', 800),
                           self.row(37, 'feixie', 1)])
        self.assertEqual(self.split('id36', 37, 37, 300),
                         ['30100', [0, 430204]])
        self.store.save_role_bag_slots(self.role_id,
                                       [self.row(301, 'bscl2', 800)])
        self.assertEqual(self.split('id301', 400, 400, 300),
                         ['30100', [0, 430202]])

    def test_delete_removes_row_and_reports_id(self):
        self.store.save_role_bag_slots(self.role_id,
                                       [self.row(36, 'silver50')])
        out = self.sess.bag_delete([30102, ['id36', 36]])
        self.assertEqual(decode(out[4:]), ['30102', [1, ['id36']]])
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 36))

    def test_delete_missing_row_still_replies_success_empty(self):
        out = self.sess.bag_delete([30102, ['nope', 36]])
        self.assertEqual(decode(out[4:]), ['30102', [1, []]])

    def test_delete_guards(self):
        self.assertIsNone(self.sess.bag_delete([30102, ['id36']]))
        self.assertIsNone(self.sess.bag_delete([30102, ['id36', -1]]))
        self.assertIsNone(self.sess.bag_delete([30102, ['', 36]]))

    def test_discard_removes_row_and_reports_via_30102(self):
        # discardGoods success queues 30102 [1, [rowId]] (no 30101 reply).
        self.store.save_role_bag_slots(self.role_id,
                                       [self.row(36, 'silver50', bind=0)])
        out = self.sess.bag_discard([30101, ['id36', 36]])
        self.assertEqual(decode(out[4:]), ['30102', [1, ['id36']]])
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 36))

    def test_discard_bound_row_reports_430218_and_keeps_row(self):
        self.store.save_role_bag_slots(self.role_id,
                                       [self.row(36, 'silver50', bind=1)])
        out = self.sess.bag_discard([30101, ['id36', 36]])
        self.assertEqual(decode(out[4:]), ['30101', [0, 430218]])
        self.assertIsNotNone(
            self.store.get_role_bag_slot(self.role_id, 36))

    def test_discard_null_bind_proceeds(self):
        # Java's ifnull branch skips the bind check (bind is unboxed).
        self.store.save_role_bag_slots(self.role_id,
                                       [self.row(36, 'silver50', bind=0)])
        with self.store.lock:
            self.store.db.execute(
                'UPDATE role_bag_slot SET bind=NULL'
                ' WHERE role_id=? AND slot_num=?',
                (str(self.role_id), 36))
            self.store.db.commit()
        out = self.sess.bag_discard([30101, ['id36', 36]])
        self.assertEqual(decode(out[4:]), ['30102', [1, ['id36']]])

    def test_discard_missing_row_is_silent(self):
        self.assertIsNone(self.sess.bag_discard([30101, ['nope', 36]]))

    def test_discard_guards(self):
        self.assertIsNone(self.sess.bag_discard([30101, ['id36']]))
        self.assertIsNone(self.sess.bag_discard([30101, ['id36', -1]]))
        self.assertIsNone(self.sess.bag_discard([30101, ['', 36]]))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class BagSlotUnlockTest(unittest.TestCase):
    """Commands 30005, 30201/30202, 30203/30204, 30302.

    Activation/growth from activationSlot/activationSlotStorage/
    bagSlotGrowUp/storageSlotChengZhang/getActivationSlotParam bytecode
    (kaige costs needtime/expadd from KaiGeFeiYongBiao.jat: B35 costs 1
    YB + 1750 exp, C31 costs 4 YB + 1860 exp); money walk from
    AccountServiceImpl (bind first, YB x5 / bind ceil(/5) conversion);
    xunbao read and selGoods shapes from getXunBao/BagOutput bytecode.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56, tongqian=0,
            bind_lingshi=0, lingshi=50)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
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
            save_role_bag_state=self.store.save_role_bag_state,
            save_role_state=self.store.update_character_state,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'

    def row(self, slot, goods, count=1, bag_id=None, bind=1):
        return {'slot_num': slot, 'goods_id': goods, 'count': count,
                'bag_id': bag_id or f'id{slot}', 'bind': bind,
                'expire_time': 0, 'rare_level': 0, 'item_level': 1,
                'attributes': None}

    def frames(self, out):
        self.assertIsNotNone(out)
        if not isinstance(out, tuple):
            return [decode(out[4:])]
        return [decode(f[4:]) for f in out]

    def test_activate_bag_deducts_pushes_and_unlocks(self):
        # Fresh role: state materializes at 34/30; slot 35 costs 1 YB
        # (no grown time, full price) + 1750 exp.
        before = int(time.time() * 1000)
        got = self.frames(self.sess.bag_activate('bag', [30201, 1]))
        self.assertEqual([f[0] for f in got], ['32010', '12001', '30201'])
        self.assertEqual(got[0][1], [0.0, 49.0, 0.0, 1])
        self.assertEqual(got[1], ['12001', [1750.0, 56]])
        self.assertEqual(got[2][0], '30201')
        self.assertEqual(got[2][1][0], 1)
        lock = got[2][1][1]
        self.assertEqual(lock[0], 36)   # next slot past the new capacity
        self.assertTrue(before + 2400000 - 60000 <= lock[1]
                        <= before + 2400000 + 60000)
        state = self.store.get_role_bag_state(self.role_id)
        self.assertEqual(state['bag_capacity'], 35)
        self.assertEqual(state['bag_slot_time'], 0)
        roles = self.store.list_roles('hero', 'fu1304')
        self.assertEqual(roles[0]['lingshi'], 49)
        self.assertEqual(roles[0]['exp'], 1750)

    def test_activate_storage(self):
        got = self.frames(self.sess.bag_activate('storage', [30202, 1]))
        self.assertEqual([f[0] for f in got], ['32010', '12001', '30202'])
        # Slot 31 costs 4 with no bind balance: bind fails, ceil(4/5) = 1 YB.
        self.assertEqual(got[0][1], [0.0, 49.0, 0.0, 1])
        self.assertEqual(got[2][1][0], 1)
        self.assertEqual(got[2][1][1][0], 32)
        state = self.store.get_role_bag_state(self.role_id)
        self.assertEqual(state['storage_capacity'], 31)

    def test_activate_prefers_bind_lingshi(self):
        self.store.update_character_state(self.role_id, bind_lingshi=10,
                                          lingshi=0)
        got = self.frames(self.sess.bag_activate('bag', [30201, 1]))
        self.assertEqual(got[0][1], [0.0, 0.0, 9.0, 1])

    def test_activate_exceed_max(self):
        self.store.save_role_bag_state(self.role_id, bag_capacity=143,
                                       bag_slot_time=0,
                                       bag_update_slot_time=0,
                                       storage_capacity=30,
                                       storage_slot_time=0,
                                       storage_update_slot_time=0)
        out = self.sess.bag_activate('bag', [30201, 2])
        self.assertEqual(decode(out[4:]), ['30201', [0, 430207]])

    def test_activate_poor(self):
        self.store.update_character_state(self.role_id, lingshi=0)
        out = self.sess.bag_activate('bag', [30201, 1])
        self.assertEqual(decode(out[4:]), ['30201', [0, 430209]])
        # Checks run before any write, but the state row materializes first
        # (Java always has it via the creation event).
        state = self.store.get_role_bag_state(self.role_id)
        self.assertEqual(state['bag_capacity'], 34)
        roles = self.store.list_roles('hero', 'fu1304')
        self.assertEqual(roles[0]['lingshi'], 0)

    def test_activate_guards(self):
        self.assertIsNone(self.sess.bag_activate('bag', [30201, 0]))
        self.assertIsNone(self.sess.bag_activate('bag', [30201, -1]))
        self.assertIsNone(self.sess.bag_activate('bag', [30201, '1']))
        self.assertIsNone(self.sess.bag_activate('bag', [30201]))

    def test_money_walk_conversion(self):
        role = {'tongqian': 0, 'bind_lingshi': 3, 'lingshi': 2}
        first = self.sess._bag_money_first
        self.assertEqual(first(role, 50, ['YXB']), None)   # no conversion
        self.assertEqual(first(role, 10, ['BIND_YB', 'YB']), ('YB', 2))
        self.assertEqual(first(role, 3, ['BIND_YB', 'YB']),
                         ('BIND_YB', 3))
        self.assertIsNone(first(role, -1, ['YXB']))

    def test_growup_waits(self):
        self.store.save_role_bag_state(self.role_id, bag_capacity=34,
                                       bag_slot_time=0,
                                       bag_update_slot_time=int(
                                           time.time() * 1000),
                                       storage_capacity=30,
                                       storage_slot_time=0,
                                       storage_update_slot_time=0)
        before = int(time.time() * 1000)
        out = self.sess.bag_growup('bag')
        cmd, obj = decode(out[4:])
        self.assertEqual(cmd, '30203')
        self.assertEqual(obj[0], -1)
        self.assertTrue(before <= obj[1] <= before + 60000)

    def test_growup_unlocks_free_when_grown(self):
        old = int(time.time() * 1000) - 2000000
        self.store.save_role_bag_state(self.role_id, bag_capacity=34,
                                       bag_slot_time=0,
                                       bag_update_slot_time=old,
                                       storage_capacity=30,
                                       storage_slot_time=0,
                                       storage_update_slot_time=old)
        got = self.frames(self.sess.bag_growup('bag'))
        self.assertEqual([f[0] for f in got], ['12001', '30203'])
        self.assertEqual(got[0], ['12001', [1750.0, 56]])
        self.assertEqual(got[1][1][0], 1)
        self.assertEqual(got[1][1][1][0], 36)
        state = self.store.get_role_bag_state(self.role_id)
        self.assertEqual(state['bag_capacity'], 35)
        roles = self.store.list_roles('hero', 'fu1304')
        self.assertEqual(roles[0]['lingshi'], 50)   # free: no deduct

    def test_growup_storage(self):
        old = int(time.time() * 1000) - 2000000
        self.store.save_role_bag_state(self.role_id, bag_capacity=34,
                                       bag_slot_time=0,
                                       bag_update_slot_time=old,
                                       storage_capacity=30,
                                       storage_slot_time=0,
                                       storage_update_slot_time=old)
        got = self.frames(self.sess.bag_growup('storage'))
        self.assertEqual([f[0] for f in got], ['12001', '30204'])
        self.assertEqual(got[0], ['12001', [1860.0, 56]])
        self.assertEqual(got[1][1][0], 1)
        self.assertEqual(got[1][1][1][0], 32)
        state = self.store.get_role_bag_state(self.role_id)
        self.assertEqual(state['storage_capacity'], 31)

    def test_growup_maxed(self):
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       bag_slot_time=0,
                                       bag_update_slot_time=0,
                                       storage_capacity=200,
                                       storage_slot_time=0,
                                       storage_update_slot_time=0)
        out = self.sess.bag_growup('bag')
        self.assertEqual(decode(out[4:]), ['30203', [0, 0, -1]])

    def test_xunbao_read(self):
        out = self.sess.xunbao_goods()
        self.assertEqual(decode(out[4:]), ['30005', None])
        self.store.save_role_bag_slots(self.role_id,
                                       [self.row(1005, 'silver50')])
        cmd, obj = decode(self.sess.xunbao_goods()[4:])
        self.assertEqual(cmd, '30005')
        maps = [m.get('__assoc__', m) for m in obj]
        self.assertEqual([(m['0'], m['2']) for m in maps],
                         [('silver50', 1005)])

    def test_inspect_own_row(self):
        self.store.save_role_bag_slots(self.role_id,
                                       [self.row(36, 'silver50')])
        out = self.sess.bag_inspect(
            [30302, ['id36', str(self.role_id)]])
        cmd, obj = decode(out[4:])
        self.assertEqual(cmd, '30302')
        self.assertEqual(obj[0], 1)
        self.assertEqual(obj[1].get('__assoc__', obj[1])['0'], 'silver50')

    def test_inspect_missing_row_reports_goods_not(self):
        out = self.sess.bag_inspect([30302, ['nope', str(self.role_id)]])
        self.assertEqual(decode(out[4:]), ['30302', [0, 430251]])

    def test_inspect_unknown_target_is_silent(self):
        self.assertIsNone(self.sess.bag_inspect([30302, ['id36', '99']]))
        self.assertIsNone(self.sess.bag_inspect([30302, ['id36']]))
        self.assertIsNone(self.sess.bag_inspect([30302, [36, '1']]))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class BagClearUpTest(unittest.TestCase):
    """Commands 30001/30003/30006 clearUp/clearUpStorage/clearUpXunBaoBag.

    Flow from BagServiceImpl.clearUp/clearUpStorage/clearUpXunBaoBag
    bytecode (empty zone replies null, one row moves to the zone base,
    else pickup merges/sorts/renumbers) and BagClearUpUtil pickup/merge/
    bindSort/expireTimeSort/goodsCountSort bytecode. sortNum is never set
    by the jar, so every goods groups into 0; maxstack from goods.jat
    (bscl2 2000, feixie 999).
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
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
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=31)

    def row(self, slot, goods, count=1, bag_id=None, bind=1, expire=0):
        return {'slot_num': slot, 'goods_id': goods, 'count': count,
                'bag_id': bag_id or f'id{slot}', 'bind': bind,
                'expire_time': expire, 'rare_level': 0, 'item_level': 1,
                'attributes': None}

    def clearup(self, zone):
        out = self.sess.bag_clearup(zone)
        self.assertIsNotNone(out)
        cmd, obj = decode(out[4:])
        if isinstance(obj, list):
            obj = [m.get('__assoc__', m) for m in obj]
        return cmd, obj

    def test_empty_zone_replies_null(self):
        cmd, obj = self.clearup('bag')
        self.assertEqual([cmd, obj], ['30001', None])

    def test_single_row_moves_to_base(self):
        self.store.save_role_bag_slots(self.role_id,
                                       [self.row(40, 'bscl2', 7)])
        cmd, obj = self.clearup('bag')
        self.assertEqual(cmd, '30001')
        self.assertEqual([(m['2'], m['3']) for m in obj], [(1, 7)])
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 40))
        got = self.store.get_role_bag_slot(self.role_id, 1)
        self.assertEqual(got['bag_id'], 'id40')
        self.assertEqual(got['count'], 7)

    def test_merge_into_one_row(self):
        # feixie maxstack 999: 100 + 800 fits; the source row disappears.
        self.store.save_role_bag_slots(
            self.role_id, [self.row(3, 'feixie', 100),
                           self.row(5, 'feixie', 800)])
        cmd, obj = self.clearup('bag')
        self.assertEqual(cmd, '30001')
        self.assertEqual([(m['1'], m['2'], m['3']) for m in obj],
                         [('id3', 1, 900)])
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 5))
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 1)['count'], 900)

    def test_overflow_keeps_two_rows(self):
        # 800 + 800 overflows 999: target tops up, source keeps the rest.
        self.store.save_role_bag_slots(
            self.role_id, [self.row(3, 'feixie', 800),
                           self.row(5, 'feixie', 800)])
        _, obj = self.clearup('bag')
        self.assertEqual([(m['2'], m['3']) for m in obj],
                         [(1, 999), (2, 601)])

    def test_bound_sorts_before_unbound(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(3, 'bscl2', 1, bind=0),
                           self.row(5, 'bscl2', 1, bind=1)])
        _, obj = self.clearup('bag')
        self.assertEqual([(m['7'], m['2']) for m in obj], [(1, 1), (0, 2)])

    def test_count_desc_beats_expire_asc(self):
        # Different future expires block the merge; the count pass runs
        # last, so the bigger stack still lands first.
        base = int(time.time() * 1000)
        exp_a = (base // 1000 + 100) * 1000
        exp_b = (base // 1000 + 200) * 1000
        self.store.save_role_bag_slots(
            self.role_id, [self.row(3, 'feixie', 100, expire=exp_a),
                           self.row(5, 'feixie', 800, expire=exp_b)])
        _, obj = self.clearup('bag')
        self.assertEqual([(m['3'], m['2']) for m in obj],
                         [(800, 1), (100, 2)])

    def test_zero_count_row_is_deleted(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(3, 'bscl2', 5),
                           self.row(4, 'bscl2', 0)])
        _, obj = self.clearup('bag')
        self.assertEqual([(m['1'], m['3']) for m in obj], [('id3', 5)])
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 4))

    def test_goods_id_order(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(5, 'bscl2', 1),
                           self.row(3, 'feixie', 1)])
        _, obj = self.clearup('bag')
        self.assertEqual([(m['0'], m['2']) for m in obj],
                         [('bscl2', 1), ('feixie', 2)])

    def test_storage_zone_renumbers_from_301(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(310, 'feixie', 100),
                           self.row(305, 'feixie', 200)])
        cmd, obj = self.clearup('storage')
        self.assertEqual(cmd, '30003')
        self.assertEqual([(m['1'], m['2'], m['3']) for m in obj],
                         [('id305', 301, 300)])
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 310))

    def test_xunbao_zone_renumbers_from_1001(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(1005, 'silver50', 1)])
        cmd, obj = self.clearup('xunbao')
        self.assertEqual(cmd, '30006')
        self.assertEqual([(m['1'], m['2']) for m in obj], [('id1005', 1001)])

    def test_unknown_goods_is_silent(self):
        # Java's sort-config lookup throws, so the op dies with no reply.
        self.store.save_role_bag_slots(
            self.role_id, [self.row(3, 'nope', 1),
                           self.row(4, 'nope', 1)])
        self.assertIsNone(self.sess.bag_clearup('bag'))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class PropUseTest(unittest.TestCase):
    """Command 30301 consumeGoods/useProp plus the 30104/30105 pushes.

    Entry, skill tableswitch, PropType pipeline (useCheck gates,
    consumePrior, decr, getStuData [1, guid]), and the Exp/Yxb/ZhenQi
    effects from PropServiceImpl bytecode; HpMp only gates (1500ms hpcd)
    since its heal is a stage-side prop buff. 30104/30105 are server
    pushes, so the ledger honestly keeps them not-started; the split test
already proves their shapes and this class pins their command ids.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56, tongqian=100,
            bind_lingshi=0, lingshi=50)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            get_role_bag_slot=self.store.get_role_bag_slot,
            get_role_bag_slot_by_bag_id=
            self.store.get_role_bag_slot_by_bag_id,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            get_role_zuoqi=self.store.get_role_zuoqi,
            save_role_state=self.store.update_character_state,
            get_role_skills=self.store.get_role_skills,
            save_role_skill=self.store.save_role_skill,
            get_role_attr_buffs=self.store.get_role_attr_buffs,
            save_role_attr_buffs=self.store.save_role_attr_buffs,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=30)

    def row(self, slot, goods, count=1, bag_id=None):
        return {'slot_num': slot, 'goods_id': goods, 'count': count,
                'bag_id': bag_id or f'p{slot}', 'bind': 0,
                'expire_time': 0, 'rare_level': 0, 'item_level': 1,
                'attributes': None}

    def use(self, guid):
        out = self.sess.prop_use(guid)
        if out is None:
            return None
        if isinstance(out, tuple):
            return [decode(f[4:]) for f in out]
        return [decode(out[4:])]

    def frames(self, out):
        self.assertIsNotNone(out)
        if not isinstance(out, tuple):
            return [decode(out[4:])]
        return [decode(f[4:]) for f in out]

    def role(self):
        return self.store.list_roles('hero', 'fu1304')[0]

    def test_exp_pill_persists_pushes_and_consumes(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(10, 'exppill_0001', 2)])
        before = self.role()['exp'] or 0
        got = self.use('p10')
        self.assertEqual([f[0] for f in got], ['12001', '30301'])
        self.assertEqual(got[1][1], [1, 'p10'])
        self.assertEqual(self.role()['exp'], before + 50000)
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 10)['count'], 1)

    def test_zhenqi_pill_persists_and_consumes(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(11, 'zhenqipill_0001', 1)])
        before = self.role()['zhenqi'] or 0
        got = self.use('p11')
        self.assertEqual([f[0] for f in got], ['30301'])
        self.assertEqual(got[0][1], [1, 'p11'])
        self.assertEqual(self.role()['zhenqi'], before + 2500)
        self.assertIsNone(
            self.store.get_role_bag_slot(self.role_id, 11))

    def test_copper_pill_grants_config_zero(self):
        # All skill-14 rows have empty addgold, so Java incrs 0; the row
        # is still consumed and the reply still arrives.
        self.store.save_role_bag_slots(
            self.role_id, [self.row(12, 'tongqian001', 1)])
        got = self.use('p12')
        self.assertEqual([f[0] for f in got], ['32010', '30301'])
        self.assertEqual(self.role()['tongqian'], 100)
        self.assertIsNone(
            self.store.get_role_bag_slot(self.role_id, 12))

    def test_hp_pill_gates_cooldown_then_consumes(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(13, 'hpadd001', 2)])
        got = self.use('p13')
        self.assertEqual([f[0] for f in got], ['30301'])
        # Second use inside 1500ms is silent (PROP_ERROR_100017 path).
        self.assertIsNone(self.use('p13'))
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 13)['count'], 1)

    def test_empty_unknown_and_unported_are_silent(self):
        self.assertIsNone(self.sess.prop_use(''))
        self.assertIsNone(self.sess.prop_use('missing'))
        self.store.save_role_bag_slots(
            self.role_id, [self.row(14, 'nope', 1)])
        self.assertIsNone(self.sess.prop_use('p14'))

    def test_level_gate_reports_100003(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(15, 'exppill_0001', 1)])
        low = Session(
            conn_id=2, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(self.role(), level=0)],
            server_start_ms=0,
            get_role_bag_slot_by_bag_id=
            self.store.get_role_bag_slot_by_bag_id,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            save_role_state=self.store.update_character_state,
            config=self.cfg)
        low.authed_user, low.server_id = 'hero', 'fu1304'
        out = low.prop_use('p15')
        self.assertEqual(decode(out[4:]), ['30301', [0, 100003]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 15)['count'], 1)

    def sess_as(self, **override):
        role = dict(self.role(), **override)
        sess = Session(
            conn_id=2, check_sign=lambda *a: False,
            get_roles=lambda u, s: [role],
            server_start_ms=0,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            get_role_bag_slot=self.store.get_role_bag_slot,
            get_role_bag_slot_by_bag_id=
            self.store.get_role_bag_slot_by_bag_id,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            get_role_zuoqi=self.store.get_role_zuoqi,
            save_role_state=self.store.update_character_state,
            get_role_skills=self.store.get_role_skills,
            save_role_skill=self.store.save_role_skill,
            get_role_attr_buffs=self.store.get_role_attr_buffs,
            save_role_attr_buffs=self.store.save_role_attr_buffs,
            config=self.cfg)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return sess

    def test_skillbook_learns_consumes_and_notifies(self):
        # Empty-job equality passes the literal job gate; level 100 opens
        # the insert path (kangxing1 info level 100 <= role 100).
        self.store.save_role_bag_slots(
            self.role_id, [self.row(20, 'kangxing1', 2)])
        got = self.frames(self.sess_as(level=100, job='').prop_use('p20'))
        self.assertEqual([f[0] for f in got], ['42004', '30301'])
        self.assertEqual(got[0][1], ['kangxing1', 1])
        self.assertEqual(got[1][1], [1, 'p20'])
        learned = [s for s in self.store.get_role_skills(self.role_id)
                   if s['category'] == 'kangxing1']
        self.assertEqual(len(learned), 1)
        self.assertEqual(learned[0]['level'], 1)
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 20)['count'], 1)

    def test_skillbook_repeat_reports_study_skill(self):
        self.store.save_role_skill(self.role_id, 'kangxing1', 1)
        self.store.save_role_bag_slots(
            self.role_id, [self.row(22, 'kangxing1', 1)])
        out = self.sess_as(level=100, job='').prop_use('p22')
        got = [decode(f[4:]) for f in out]
        self.assertEqual(got,
                         [['42004', [0, 420007]], ['30301', [0, 100008]]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 22)['count'], 1)

    def test_skillbook_gates_report_without_consume(self):
        cases = [({'level': 0, 'job': ''}, 420008),
                 ({'level': 56, 'job': 'C'}, 420009)]
        for slot, (shape, code) in enumerate(cases, start=23):
            with self.subTest(shape=shape):
                self.store.save_role_bag_slots(
                    self.role_id, [self.row(slot, 'kangxing1', 1)])
                out = self.sess_as(**shape).prop_use(f'p{slot}')
                got = [decode(f[4:]) for f in out]
                self.assertEqual(got, [['42004', [0, code]],
                                       ['30301', [0, 100008]]])
                self.assertEqual(
                    self.store.get_role_bag_slot(
                        self.role_id, slot)['count'], 1)

    def test_skillbook_unknown_info_is_silent_error(self):
        # fangyu has no JiNengBiao row: no 42004, book intact.
        self.store.save_role_bag_slots(
            self.role_id, [self.row(25, 'fangyu', 1)])
        got = self.use('p25')
        self.assertEqual(got, [['30301', [0, 100008]]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 25)['count'], 1)

    def test_dan_first_eat_inserts_buff_and_double_consumes(self):
        # Pipeline pre-decr plus eatShuxinDan's internal decr consume 2
        # per use exactly like Java; the buff lands at count 1.
        self.store.save_role_bag_slots(
            self.role_id, [self.row(30, 'sm_001', 3)])
        got = self.use('p30')
        self.assertEqual([f[0] for f in got], ['85010', '30301'])
        self.assertEqual(got[0][1], ['sm_001', 1])
        self.assertEqual(got[1][1], [1, 'p30'])
        self.assertEqual(self.store.get_role_attr_buffs(self.role_id),
                         [{'attribute_id': 'sm_001', 'count': 1}])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 30)['count'], 1)

    def test_dan_capped_returns_error_but_keeps_pre_decr(self):
        # The cap check runs after the pipeline pre-consume, so the bag
        # still loses 1 while the buff stays put and no 85010 arrives.
        self.store.save_role_attr_buffs(
            self.role_id, [{'attribute_id': 'sm_001', 'count': 50}])
        self.store.save_role_bag_slots(
            self.role_id, [self.row(31, 'sm_001', 2)])
        got = self.use('p31')
        self.assertEqual(got, [['30301', [0, 851003]]])
        self.assertEqual(self.store.get_role_attr_buffs(self.role_id),
                         [{'attribute_id': 'sm_001', 'count': 50}])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 31)['count'], 1)

    def test_dan_partial_fit_clamps_to_cap(self):
        self.store.save_role_attr_buffs(
            self.role_id, [{'attribute_id': 'sm_001', 'count': 49}])
        self.store.save_role_bag_slots(
            self.role_id, [self.row(32, 'sm_001', 2)])
        got = self.use('p32')
        self.assertEqual([f[0] for f in got], ['85010', '30301'])
        self.assertEqual(got[0][1], ['sm_001', 50])
        self.assertEqual(self.store.get_role_attr_buffs(self.role_id),
                         [{'attribute_id': 'sm_001', 'count': 50}])
        self.assertIsNone(
            self.store.get_role_bag_slot(self.role_id, 32))

    def test_lihe_open_grants_previews_and_consumes(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(40, 'zuiqilibao', 1)])
        got = self.use('p40')
        self.assertEqual([f[0] for f in got], ['30304', '30301'])
        self.assertEqual(got[0][1],
                         ['zuiqilibao', [['jinjiedan001', 100]]])
        self.assertEqual(got[1][1], [0, [['zuiqilibao', 1]]])
        pills = [s for s in
                 self.store.get_role_bag_slots(self.role_id, 1, 150)
                 if s['goods_id'] == 'jinjiedan001']
        self.assertEqual(sum(s['count'] for s in pills), 100)
        self.assertEqual(pills[0]['bind'], 1)
        self.assertIsNone(
            self.store.get_role_bag_slot(self.role_id, 40))

    def test_lihe_gates_report_without_consume(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(41, 'zuiqilibao', 1),
                           self.row(42, 'ts_shenshou', 1)])
        out = self.sess_as(level=0).prop_use('p41')
        self.assertEqual(decode(out[4:]), ['30301', [0, 1000]])
        out = self.sess.prop_use('p42')
        self.assertEqual(decode(out[4:]), ['30301', [0, 100014]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 41)['count'], 1)
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 42)['count'], 1)

    def test_lihe_full_bag_reports_no_slot(self):
        self.store.save_role_bag_state(self.role_id, bag_capacity=2,
                                       storage_capacity=30)
        self.store.save_role_bag_slots(
            self.role_id, [self.row(1, 'zuiqilibao', 1),
                           self.row(2, 'bscl2', 1)])
        got = self.use('p1')
        self.assertEqual(got, [['30301', [0, 1006]]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 1)['count'], 1)

    def test_lihe_lottery_and_vip_boxes_stay_silent(self):
        # lihe_001 rolls zubao odds (RNG chain untraced); the six
        # suijijinengshu boxes need the unmigrated role_prop caps.
        self.store.save_role_bag_slots(
            self.role_id, [self.row(43, 'lihe_001', 1),
                           self.row(44, 'suijijinengshu01', 1)])
        self.assertIsNone(self.sess.prop_use('p43'))
        self.assertIsNone(self.sess.prop_use('p44'))
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 43)['count'], 1)

    def test_lihe_cost_branches_against_real_rows(self):
        # No fixed-only box carries costs, so the gate/pay/take code is
        # pinned white-box with the traced branch shapes (gates first).
        box = dict(self.cfg.lihe_box('zuiqilibao'), jb=50,
                   itemneed={'bscl2': 3})
        role = dict(self.role(), tongqian=100)
        self.assertIsNone(
            self.sess._prop_lihe_gate(role, self.role_id, box))
        self.assertEqual(
            self.sess._prop_lihe_gate(dict(role, tongqian=10),
                                      self.role_id, box), 1003)
        self.store.save_role_bag_slots(
            self.role_id, [self.row(45, 'bscl2', 5)])
        self.sess._prop_take(self.role_id, 'bscl2', 3)
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 45)['count'], 2)
        self.sess._prop_pay(self.role_id, role, box)
        self.assertEqual(self.role()['tongqian'], 50)

    def test_split_push_ids_match_commands(self):
        from game.protocol import (CMD_BAG_SPLIT_COUNT, CMD_BAG_SPLIT_NEW,
                                   CMD_PROP_USE)
        self.assertEqual(
            (CMD_BAG_SPLIT_COUNT, CMD_BAG_SPLIT_NEW, CMD_PROP_USE),
            (30104, 30105, 30301))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class PropBoxTest(unittest.TestCase):
    """Commands 30305/30306/30307: duoXuanLiBao/youHuiQuanLiBao/getTeShuTypeCount.

    Shapes from PropStageAction (C> layouts, 30305/30306 queue replies,
    30307 direct send) plus PropServiceImpl.duoXuanLiBao/youHuiQuanLiBao
    (missing slot [0, 1005], short YB [0, 1002], full bag [0, 1006],
    failed takes [0, 100009]/[0, 100008], silent unknown boxes/choices,
    the 30304 [configId, [[goodsId, count]]] push ahead of [1, bagId])
    and getTeShuTypeCount (stale-day reset, missing rows answer 0).
    30303 is registered in PropModuleInit.getInCmd but has no Action
    method jar-wide, so it stays unrouted and silent.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56, tongqian=100,
            bind_lingshi=0, lingshi=50)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            get_role_bag_slot=self.store.get_role_bag_slot,
            get_role_bag_slot_by_bag_id=
            self.store.get_role_bag_slot_by_bag_id,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            get_role_prop=self.store.get_role_prop,
            save_role_prop=self.store.save_role_prop,
            save_role_state=self.store.update_character_state,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=30)

    def row(self, slot, goods, count=1, bag_id=None):
        return {'slot_num': slot, 'goods_id': goods, 'count': count,
                'bag_id': bag_id or f'x{slot}', 'bind': 0,
                'expire_time': 0, 'rare_level': 0, 'item_level': 1,
                'attributes': None}

    def frames(self, out):
        self.assertIsNotNone(out)
        if not isinstance(out, tuple):
            return [decode(out[4:])]
        return [decode(f[4:]) for f in out]

    def role(self):
        return self.store.list_roles('hero', 'fu1304')[0]

    def test_command_ids(self):
        from game.protocol import (CMD_PROP_DUOXUAN, CMD_PROP_YOUHUI,
                                   CMD_PROP_TESHU)
        self.assertEqual(
            (CMD_PROP_DUOXUAN, CMD_PROP_YOUHUI, CMD_PROP_TESHU),
            (30305, 30306, 30307))

    def test_duoxuan_free_choice_pushes_grants_and_consumes(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(50, 'zuoqizhenbao', 1)])
        got = self.frames(self.sess.prop_duoxuan([50, 'libao4']))
        self.assertEqual([f[0] for f in got], ['30304', '30305'])
        self.assertEqual(got[0][1],
                         ['zuoqizhenbao', [['jinjiedan001', 3]]])
        self.assertEqual(got[1][1], [1, 'x50'])
        self.assertIsNone(
            self.store.get_role_bag_slot(self.role_id, 50))
        pills = [s for s in
                 self.store.get_role_bag_slots(self.role_id, 1, 150)
                 if s['goods_id'] == 'jinjiedan001']
        self.assertEqual(sum(s['count'] for s in pills), 3)
        self.assertEqual(self.role()['lingshi'], 50)

    def test_duoxuan_paid_choice_decrs_yb(self):
        self.store.update_character_state(self.role_id, lingshi=1000)
        self.store.save_role_bag_slots(
            self.role_id, [self.row(51, 'zuoqizhenbao', 1)])
        got = self.frames(self.sess.prop_duoxuan([51, 'libao1']))
        self.assertEqual([f[0] for f in got], ['30304', '30305'])
        self.assertEqual(got[1][1], [1, 'x51'])
        self.assertEqual(self.role()['lingshi'], 1000 - 688)
        self.assertIsNone(
            self.store.get_role_bag_slot(self.role_id, 51))

    def test_duoxuan_errors_and_silence(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(52, 'zuoqizhenbao', 1)])
        out = self.sess.prop_duoxuan([99, 'libao4'])
        self.assertEqual(decode(out[4:]), ['30305', [0, 1005]])
        out = self.sess.prop_duoxuan([52, 'libao1'])
        self.assertEqual(decode(out[4:]), ['30305', [0, 1002]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 52)['count'], 1)
        self.assertIsNone(self.sess.prop_duoxuan([52, 'libao9']))
        self.store.save_role_bag_slots(
            self.role_id, [self.row(53, 'nope', 1)])
        self.assertIsNone(self.sess.prop_duoxuan([53, 'libao4']))
        self.assertIsNone(self.sess.prop_duoxuan('nope'))
        self.assertIsNone(self.sess.prop_duoxuan([52]))
        self.assertIsNone(self.sess.prop_duoxuan(['52', 'libao4']))
        self.assertIsNone(self.sess.prop_duoxuan([52, 4]))
        self.assertIsNone(self.sess.prop_duoxuan([52, '']))

    def test_duoxuan_full_bag_reports_no_slot(self):
        self.store.save_role_bag_state(self.role_id, bag_capacity=2,
                                       storage_capacity=30)
        self.store.save_role_bag_slots(
            self.role_id, [self.row(1, 'zuoqizhenbao', 1),
                           self.row(2, 'bscl2', 1)])
        out = self.sess.prop_duoxuan([1, 'libao4'])
        self.assertEqual(decode(out[4:]), ['30305', [0, 1006]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 1)['count'], 1)

    def test_duoxuan_empty_row_reports_take_error(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(54, 'zuoqizhenbao', 0)])
        out = self.sess.prop_duoxuan([54, 'libao4'])
        self.assertEqual(decode(out[4:]), ['30305', [0, 100009]])

    def test_youhui_success_and_errors(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.row(60, 'zuoqiyouhui', 1),
                           self.row(61, 'zuoqiyouhui', 1)])
        out = self.sess.prop_youhui([60])
        self.assertEqual(decode(out[4:]), ['30306', [0, 1002]])
        self.store.update_character_state(self.role_id, lingshi=1000)
        got = self.frames(self.sess.prop_youhui([61]))
        self.assertEqual([f[0] for f in got], ['30304', '30306'])
        self.assertEqual(got[0][1],
                         ['zuoqiyouhui', [['jinjiedan001', 34]]])
        self.assertEqual(got[1][1], [1, 'x61'])
        self.assertEqual(self.role()['lingshi'], 1000 - 850)
        self.assertIsNone(
            self.store.get_role_bag_slot(self.role_id, 61))
        out = self.sess.prop_youhui([99])
        self.assertEqual(decode(out[4:]), ['30306', [0, 1005]])
        self.assertIsNone(self.sess.prop_youhui('nope'))
        self.assertIsNone(self.sess.prop_youhui([]))
        self.assertIsNone(self.sess.prop_youhui([True]))

    def test_youhui_empty_row_reports_take_error(self):
        self.store.update_character_state(self.role_id, lingshi=1000)
        self.store.save_role_bag_slots(
            self.role_id, [self.row(62, 'zuoqiyouhui', 0)])
        out = self.sess.prop_youhui([62])
        self.assertEqual(decode(out[4:]), ['30306', [0, 100008]])

    def test_teshu_count_missing_today_and_stale(self):
        out = self.sess.prop_teshu_count('teshu_fire')
        self.assertEqual(decode(out[4:]), ['30307', 0])
        now = int(time.time() * 1000)
        self.store.save_role_prop(self.role_id, 'teshu_fire',
                                  use_count=3, use_start_time=now)
        out = self.sess.prop_teshu_count('teshu_fire')
        self.assertEqual(decode(out[4:]), ['30307', 3])
        stale = now - 2 * 86400 * 1000
        self.store.save_role_prop(self.role_id, 'teshu_ice',
                                  use_count=5, use_start_time=stale)
        out = self.sess.prop_teshu_count('teshu_ice')
        self.assertEqual(decode(out[4:]), ['30307', 0])
        row = self.store.get_role_prop(self.role_id, 'teshu_ice')
        self.assertEqual(row['use_count'], 0)
        self.assertTrue(abs(int(time.time() * 1000) -
                            row['use_start_time']) < 60000)
        self.assertIsNone(self.sess.prop_teshu_count(5))
        self.assertIsNone(self.sess.prop_teshu_count(None))

    def test_teshu_count_through_dispatch(self):
        # Live path: client [30307, id] -> handle -> prop_teshu_count(id).
        self.store.save_role_prop(self.role_id, 'teshu_fire', use_count=3,
                                  use_start_time=int(time.time() * 1000))
        self.sess.cipher = SimpleEncrypt('testkey')
        payload = self.sess.cipher.encode(amf3_encode([30307, 'teshu_fire']))
        out = self.sess.handle(payload)
        self.assertEqual(decode(bytes(out)[4:]), ['30307', 3])


class HornChatTest(unittest.TestCase):
    def test_horn_chat_is_silent_and_routed(self):
        import struct
        from game import amf3
        sess = Session(conn_id=1, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [], server_start_ms=0)
        hello = amf3.encode('INITKEY')
        sess.feed(struct.pack('>I', len(hello)) + hello)
        req = [11005, 'hello horn']
        self.assertEqual(sess.feed(frame(sess.cipher.encode(amf3.encode(req)))), [])


class GiftCodeStubTest(unittest.TestCase):
    def test_gift_code_stub_is_silent_and_routed(self):
        import struct
        from game import amf3
        sess = Session(conn_id=1, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [], server_start_ms=0)
        hello = amf3.encode('INITKEY')
        sess.feed(struct.pack('>I', len(hello)) + hello)
        req = [57000, 'ABCD1234']
        self.assertEqual(sess.feed(frame(sess.cipher.encode(amf3.encode(req)))), [])


class BagDummyTest(unittest.TestCase):
    """Command 93002 bagdummyService.getInfo: [[goodsId, count], ...] or []."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56)
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_bag_dummy=self.store.get_role_bag_dummy,
            config=GameConfig(str(REAL_CONFIG)))
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'

    def seed(self, row_id, goods, count):
        with self.store.lock:
            self.store.db.execute(
                'INSERT INTO role_bag_dummy(id, role_id, goods_id, goods_count)'
                ' VALUES (?, ?, ?, ?)', (row_id, self.role_id, goods, count))
            self.store.db.commit()

    def info(self):
        out = self.sess.bagdummy_info()
        return decode(out[4:])

    def test_empty_role_gets_empty_array(self):
        self.assertEqual(self.info(), ['93002', []])

    def test_rows_listed_in_insert_order_as_pairs(self):
        self.seed('d1', 'silver50', 3)
        self.seed('d2', 'zj0013', 1)
        self.assertEqual(self.info(),
                         ['93002', [['silver50', 3], ['zj0013', 1]]])

    def test_other_roles_rows_are_not_listed(self):
        other = self.store.create_character(
            'hero', 'fu1305', 'Bajie', job='C', level=10)
        with self.store.lock:
            self.store.db.execute(
                'INSERT INTO role_bag_dummy(id, role_id, goods_id, goods_count)'
                ' VALUES (?, ?, ?, ?)', ('x1', other, 'silver50', 9))
            self.store.db.commit()
        self.assertEqual(self.info(), ['93002', []])


if __name__ == '__main__':
    unittest.main()

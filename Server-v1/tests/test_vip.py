"""Goldens for the vip gift + kaifu + huodong slice
(62001/62002/62004/62020/62021/62022/88000/88001/88002).

Oracle: VipServiceImpl.getVipDay/getVipWeek/getVipTeJia/getKaiFuInfo/
lotterReward/lingQuReward/getVipHuoDongState/getVipHuoDongJiangLi/
getVipHuoDongChouJiang plus VipAction request parsing, traced via
tools/javap.py against dntg_start.jar. 621001-621005, 621007-621009
and 621010-621013 equal their names; day/week staleness mirrors
clearTimes; kaifu days count from the session server start. The
lottery tail ([items], [], []) and putInBag1-as-bag are documented
approximations. 62003/62006 are service-internal (recharge event +
prop pipeline; VipCommands push names VIP_CHANGE/VIP_PROP) and 62005
is a stage push (vipChange): no ModuleInit routes them inbound, so
they stay push-only. Live kaifuchoujiang windows ([99999,3],
[99999,7]) never open, so the time gate always fires on real data
and success paths use a synthetic table.
"""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from auth import hash_password
from db import Store
from game.amf3 import Obj, decode, encode
from game.config import GameConfig
from game.protocol import Session

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..', 'reference',
                           'TonNgoKhong', 'server', 'config', 'game')

HAVE_REAL = os.path.isfile(os.path.join(REAL_CONFIG, 'sys_config',
                                        'vipbiao.jat'))

DAY_MS = 86400000


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class VipGiftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56, tongqian=1000000,
            bind_lingshi=0, lingshi=1000000)
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
            get_role_vip=self.store.get_role_vip,
            save_role_vip=self.store.save_role_vip,
            get_role_vip_kaifu=self.store.get_role_vip_kaifu,
            save_role_vip_kaifu=self.store.save_role_vip_kaifu,
            get_role_vip_huodong_all=self.store.get_role_vip_huodong_all,
            get_role_vip_huodong=self.store.get_role_vip_huodong,
            save_role_vip_huodong=self.store.save_role_vip_huodong,
            save_role_state=self.store.update_character_state,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=30)

    def frames(self, out):
        self.assertIsNotNone(out)
        if not isinstance(out, tuple):
            return [decode(out[4:])]
        return [decode(f[4:]) for f in out]

    def call(self, cmd, *args):
        if cmd == 62001:
            return self.frames(self.sess.vip_day([cmd, list(args)]))
        if cmd == 62002:
            return self.frames(self.sess.vip_week([cmd, list(args)]))
        if cmd == 62004:
            return self.frames(self.sess.vip_tejia([cmd, args[0]]))
        if cmd == 62020:
            return self.frames(self.sess.vip_kaifu([cmd, list(args)]))
        if cmd == 62021:
            return self.frames(self.sess.vip_lottery([cmd, list(args)]))
        if cmd == 62022:
            return self.frames(self.sess.vip_lingjiang([cmd, args[0]]))
        if cmd == 88000:
            return self.frames(self.sess.vip_huodong([cmd, list(args)]))
        if cmd == 88001:
            return self.frames(self.sess.vip_huodong_guding([cmd, args[0]]))
        return self.frames(self.sess.vip_huodong_choujiang([cmd, args[0]]))

    def vip(self, **fields):
        self.store.save_role_vip(self.role_id, **fields)

    def counts(self, goods):
        return sum(s['count'] for s in
                   self.store.get_role_bag_slots(self.role_id, 1, 150)
                   if s['goods_id'] == goods)

    def test_day_no_row_silent(self):
        self.assertIsNone(self.sess.vip_day([62001, []]))

    def test_day_needs_vip(self):
        self.vip(vip_level=0, state_day=1)
        self.assertEqual(self.call(62001), [['62001', [0, 621002]]])

    def test_day_claimed(self):
        self.vip(vip_level=1, state_day=2, day_time=int(time.time() * 1000))
        self.assertEqual(self.call(62001), [['62001', [0, 621001]]])
        self.assertEqual(self.counts('qianghuashi'), 0)

    def test_day_success(self):
        # Lv1 daybag: jinjiedan001/qianghuashi/bscl x2 + silver50 x1.
        self.vip(vip_level=1, state_day=1)
        self.assertEqual(self.call(62001), [['62001', [1]]])
        self.assertEqual(
            (self.counts('jinjiedan001'), self.counts('qianghuashi'),
             self.counts('bscl'), self.counts('silver50')), (2, 2, 2, 1))
        row = self.store.get_role_vip(str(self.role_id))
        self.assertEqual(row['state_day'], 2)
        self.assertGreater(row['day_time'], 0)

    def test_day_full_bag(self):
        # Zero free slots fails the stack-aware room check up front.
        self.vip(vip_level=1, state_day=1)
        self.store.save_role_bag_state(self.role_id, bag_capacity=0)
        self.assertEqual(self.call(62001), [['62001', [0, 1006]]])
        self.assertEqual(self.counts('silver50'), 0)

    def test_week_claimed_and_success(self):
        self.vip(vip_level=1, state_week=2,
                 week_time=int(time.time() * 1000))
        self.assertEqual(self.call(62002), [['62002', [0, 621003]]])
        self.vip(vip_level=1, state_week=1)
        self.assertEqual(self.call(62002), [['62002', [1]]])
        self.assertEqual(
            (self.counts('tongqian003'), self.counts('jinjiedan006'),
             self.counts('expfold_002')), (5, 5, 2))

    def test_tejia_above_level(self):
        self.vip(vip_level=1)
        self.assertEqual(self.call(62004, 2), [['62004', [0, 621004]]])

    def test_tejia_claimed(self):
        self.vip(vip_level=1, state_tejia='{\"1\":2}')
        self.assertEqual(self.call(62004, 1), [['62004', [0, 621005]]])

    def test_tejia_success_marks(self):
        # No libaoid row exists at any level, so nothing grants but the
        # claim still marks and replies.
        self.vip(vip_level=1)
        self.assertEqual(self.call(62004, 1), [['62004', [1, 1]]])
        row = self.store.get_role_vip(str(self.role_id))
        self.assertEqual(json.loads(row['state_tejia']), {'1': 2})

    def test_kaifu_empty(self):
        self.assertEqual(self.call(62020), [['62020', [1, 0, []]]])

    def test_lottery_vip_floor(self):
        self.vip(vip_level=0)
        self.assertEqual(self.call(62021), [['62021', [0, 1011]]])

    def test_lottery_day_window(self):
        # Server start epoch means kaifu days are huge: outside 4-6.
        self.vip(vip_level=1)
        self.assertEqual(self.call(62021), [['62021', [0, 621012]]])

    def test_lottery_win(self):
        self.vip(vip_level=1)
        self.sess.server_start_ms = int(time.time() * 1000) - 4 * DAY_MS
        with mock.patch.object(Session, '_lottery_weighted_key',
                               return_value=1):
            got = self.call(62021)
        self.assertEqual(
            got, [['62021', [1, 1, [['expfold_003', 2]], [], []]]])
        self.assertEqual(self.counts('expfold_003'), 2)
        self.assertEqual(self.call(62020), [['62020', [1, 1, []]]])

    def test_lottery_spent(self):
        # Used == day span (3) trips the literal zero-count guard.
        self.vip(vip_level=1)
        self.sess.server_start_ms = int(time.time() * 1000) - 4 * DAY_MS
        self.store.save_role_vip_kaifu(str(self.role_id), lotter_reward=3)
        self.assertEqual(self.call(62021), [['62021', [0, 621013]]])

    def test_lingjiang_claimed(self):
        self.store.save_role_vip_kaifu(str(self.role_id),
                                       lingqu_reward='{\"1\":1}')
        self.assertEqual(self.call(62022, '1'), [['62022', [0, 621010]]])

    def test_lingjiang_day_mismatch(self):
        # Reward 1 lands on kaifu day 4; day 5 is the wrong day.
        self.vip(vip_level=1)
        self.sess.server_start_ms = int(time.time() * 1000) - 5 * DAY_MS
        self.assertEqual(self.call(62022, '1'), [['62022', [0, 621011]]])

    def test_lingjiang_success(self):
        self.vip(vip_level=1)
        self.sess.server_start_ms = int(time.time() * 1000) - 4 * DAY_MS
        self.assertEqual(self.call(62022, '1'), [['62022', [1, 1, 1]]])
        self.assertEqual(self.counts('jinjiedan006'), 100)
        self.assertEqual(
            self.call(62020), [['62020', [1, 0, [[1, 1]]]]])

    def test_huodong_empty(self):
        self.assertEqual(self.call(88000), [['88000', [[], []]]])

    def test_huodong_state_partition(self):
        self.store.save_role_vip_huodong(str(self.role_id), 5,
                                         choujiang_state=1, lingqu_state=1)
        self.store.save_role_vip_huodong(str(self.role_id), 7,
                                         choujiang_state=0, lingqu_state=1)
        self.assertEqual(self.call(88000), [['88000', [[5, 7], [5]]]])

    def test_huodong_guding_claimed(self):
        self.store.save_role_vip_huodong(str(self.role_id), 5,
                                         lingqu_state=1)
        self.assertEqual(self.call(88001, 5), [['88001', [0, 621008]]])

    def test_huodong_guding_floor(self):
        self.vip(vip_level=0)
        self.assertEqual(self.call(88001, 5), [['88001', [0, 1011]]])

    def test_huodong_guding_window_shut(self):
        # Live window [99999, 3] never opens at any kaifu day.
        self.vip(vip_level=5)
        self.assertEqual(self.call(88001, 5), [['88001', [0, 621007]]])

    def test_huodong_guding_unknown_tier_silent(self):
        self.vip(vip_level=9)
        self.assertIsNone(self.sess.vip_huodong_guding([88001, 9]))

    def test_huodong_guding_bad_arg_silent(self):
        self.assertIsNone(self.sess.vip_huodong_guding([88001, 'x']))

    def test_huodong_choujiang_claimed(self):
        self.store.save_role_vip_huodong(str(self.role_id), 5,
                                         choujiang_state=1)
        self.assertEqual(self.call(88002, 5), [['88002', [0, 621009]]])

    def test_huodong_choujiang_floor(self):
        self.vip(vip_level=4)
        self.assertEqual(self.call(88002, 5), [['88002', [0, 1011]]])

    def test_huodong_choujiang_window_shut(self):
        self.vip(vip_level=5)
        self.assertEqual(self.call(88002, 5), [['88002', [0, 621007]]])

    def synthetic_huodong_session(self):
        root = os.path.join(self.tmp.name, 'huodong')
        path = os.path.join(root, 'sys_config')
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, 'kaifuchoujiang.jat'), 'wb') as f:
            f.write(encode([
                Obj(vip=5, time='1;30', bisong='jinjiedan001:2:1',
                    jilv1=1.0, jiangpin1='qianghuashi:3:0')]))
        sess = Session(
            conn_id=2, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=int(time.time() * 1000) - 5 * DAY_MS,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            get_role_bag_slot=self.store.get_role_bag_slot,
            get_role_bag_slot_by_bag_id=
            self.store.get_role_bag_slot_by_bag_id,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            get_role_vip=self.store.get_role_vip,
            save_role_vip=self.store.save_role_vip,
            get_role_vip_huodong_all=self.store.get_role_vip_huodong_all,
            get_role_vip_huodong=self.store.get_role_vip_huodong,
            save_role_vip_huodong=self.store.save_role_vip_huodong,
            save_role_state=self.store.update_character_state,
            config=GameConfig(str(root)))
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return sess

    def test_huodong_guding_success(self):
        sess = self.synthetic_huodong_session()
        self.vip(vip_level=5)
        out = decode(sess.vip_huodong_guding([88001, 5])[4:])
        self.assertEqual(out, ['88001', [1, 5]])
        self.assertEqual(self.counts('jinjiedan001'), 2)
        row = self.store.get_role_vip_huodong(str(self.role_id), 5)
        self.assertEqual(row['lingqu_state'], 1)
        self.assertEqual(row['choujiang_state'], 0)
        self.assertEqual(decode(sess.vip_huodong([88000, []])[4:]),
                         ['88000', [[5], []]])

    def test_huodong_guding_full_bag(self):
        sess = self.synthetic_huodong_session()
        self.vip(vip_level=5)
        self.store.save_role_bag_state(self.role_id, bag_capacity=0)
        out = decode(sess.vip_huodong_guding([88001, 5])[4:])
        self.assertEqual(out, ['88001', [0, 1006]])
        self.assertEqual(self.counts('jinjiedan001'), 0)

    def test_huodong_choujiang_success(self):
        sess = self.synthetic_huodong_session()
        self.vip(vip_level=5)
        with mock.patch.object(Session, '_lottery_weighted_key',
                               return_value=1):
            out = decode(sess.vip_huodong_choujiang([88002, 5])[4:])
        self.assertEqual(out, ['88002', [1, 5, 1]])
        self.assertEqual(self.counts('qianghuashi'), 3)
        row = self.store.get_role_vip_huodong(str(self.role_id), 5)
        self.assertEqual(row['choujiang_state'], 1)
        self.assertEqual(row['lingqu_state'], 0)
        self.assertEqual(decode(sess.vip_huodong([88000, []])[4:]),
                         ['88000', [[], [5]]])

    def test_vip_ids_match_map(self):
        from game.protocol import (CMD_VIP_DAY, CMD_VIP_WEEK, CMD_VIP_TEJIA,
                                   CMD_VIP_KAIFU, CMD_VIP_LOTTERY,
                                   CMD_VIP_LINGJIANG, CMD_VIP_HUODONG,
                                   CMD_VIP_HUODONG_GUDING,
                                   CMD_VIP_HUODONG_CHOUJIANG,
                                   VIP_ERR_CLAIMED_DAY,
                                   VIP_ERR_NOVIP, VIP_ERR_CLAIMED_WEEK,
                                   VIP_ERR_ABOVE_LEVEL, VIP_ERR_CLAIMED_TEJIA,
                                   VIP_ERR_CLAIMED_KAIFU, VIP_ERR_DAY_MISMATCH,
                                   VIP_ERR_NO_LOTTERY, VIP_ERR_NO_COUNT,
                                   VIP_ERR_HUODONG_TIME,
                                   VIP_ERR_HUODONG_CLAIMED,
                                   VIP_ERR_HUODONG_DRAWN,
                                   GENERAL_VIP_LEVEL)
        self.assertEqual(
            (CMD_VIP_DAY, CMD_VIP_WEEK, CMD_VIP_TEJIA, CMD_VIP_KAIFU,
             CMD_VIP_LOTTERY, CMD_VIP_LINGJIANG, CMD_VIP_HUODONG,
             CMD_VIP_HUODONG_GUDING, CMD_VIP_HUODONG_CHOUJIANG),
            (62001, 62002, 62004, 62020, 62021, 62022, 88000, 88001,
             88002))
        self.assertEqual(
            (VIP_ERR_CLAIMED_DAY, VIP_ERR_NOVIP, VIP_ERR_CLAIMED_WEEK,
             VIP_ERR_ABOVE_LEVEL, VIP_ERR_CLAIMED_TEJIA,
             VIP_ERR_CLAIMED_KAIFU, VIP_ERR_DAY_MISMATCH, VIP_ERR_NO_LOTTERY,
             VIP_ERR_NO_COUNT, VIP_ERR_HUODONG_TIME,
             VIP_ERR_HUODONG_CLAIMED, VIP_ERR_HUODONG_DRAWN,
             GENERAL_VIP_LEVEL),
            (621001, 621002, 621003, 621004, 621005, 621010, 621011,
             621012, 621013, 621007, 621008, 621009, 1011))


if __name__ == '__main__':
    unittest.main()

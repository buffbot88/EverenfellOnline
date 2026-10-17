"""Goldens for the vip gift + kaifu + huodong + vipqq slice
(62001/62002/62004/62020/62021/62022/88000/88001/88002/88003/88004/88005).

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
import sqlite3
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


class FakeRegistry:
    """Records role pushes the way StageRegistry.push receives them."""

    def __init__(self):
        self.pushed = []

    def push(self, role_id, frames):
        self.pushed.append((role_id, frames))
        return True


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class VipPushTest(VipGiftTest):
    """62003 level change and 62006 prop push, golden against upgradeVipLevel
    and addPropValue bytecode (prop use time is not persisted yet)."""

    def setUp(self):
        super().setUp()
        self.reg = FakeRegistry()
        self.sess.stage_registry = self.reg
        self.role = {'id': self.role_id}

    def _levels(self):
        return {lv: self.cfg.vip_need_gold(lv) for lv in self.cfg.vip_table()}

    def test_level_for_gold_matches_real_thresholds(self):
        for lv, need in self._levels().items():
            if need <= 0:
                continue
            self.assertEqual(self.cfg.vip_level_for_gold(need), lv)
            self.assertLess(self.cfg.vip_level_for_gold(need - 1), lv)
        top = max(self._levels().values())
        self.assertEqual(self.cfg.vip_level_for_gold(top * 10 + 1),
                         max(self.cfg.vip_table()))
        self.assertEqual(self.cfg.vip_level_for_gold(0), 0)
        self.assertEqual(self.cfg.vip_level_for_gold(None), 0)

    def test_upgrade_creates_row_silently_at_level_zero(self):
        self.assertEqual(self.sess.vip_upgrade_level(self.role, 0), [])
        row = self.store.get_role_vip(self.role_id)
        self.assertEqual(row['vip_level'], 0)
        self.assertEqual(json.loads(row['state_tejia']), {'0': 0})
        self.assertEqual(self.reg.pushed, [])

    def test_upgrade_pushes_62003_with_new_level(self):
        lv1 = min((n, lv) for lv, n in self._levels().items() if n > 0)[1]
        need = self.cfg.vip_need_gold(lv1)
        out = self.sess.vip_upgrade_level(self.role, need)
        self.assertEqual(decode(out[0][4:]), ['62003', lv1])
        self.assertEqual(self.reg.pushed, [(str(self.role_id), out)])
        self.assertEqual(self.store.get_role_vip(self.role_id)['vip_level'], lv1)

    def test_upgrade_moves_prop_value_into_charge_side(self):
        self.store.save_role_vip(self.role_id, tody_prop_value=500)
        target = self.cfg.vip_level_for_gold(600)
        need = self.cfg.vip_need_gold(target)
        self.assertTrue(100 < need <= 600, 'real table shape changed')
        out = self.sess.vip_upgrade_level(self.role, 100)
        self.assertEqual(decode(out[0][4:]), ['62003', target])
        row = self.store.get_role_vip(self.role_id)
        self.assertEqual(row['prop_value'], need - 100)
        self.assertEqual(row['tody_prop_value'], 500 - (need - 100))
        self.assertEqual(row['vip_level'], target)

    def test_add_prop_value_pushes_62006_then_level(self):
        self.store.save_role_vip(self.role_id, tody_prop_value=0)
        before = int(time.time() * 1000)
        out = self.sess.vip_add_prop_value(self.role, 500, 0)
        after = int(time.time() * 1000)
        self.assertEqual([decode(f[4:]) for f in out],
                         [['62006', None], ['62003', 1]])
        row = self.store.get_role_vip(self.role_id)
        self.assertEqual((row['prop_value'], row['tody_prop_value']), (500, 0))
        self.assertEqual(row['vip_level'], 1)
        # Java stamps propUseTime = System.currentTimeMillis() on each add.
        self.assertTrue(before <= row['prop_use_time'] <= after)

    def test_store_adds_prop_use_time_to_legacy_role_vip(self):
        path = os.path.join(self.tmp.name, 'legacy.db')
        legacy = sqlite3.connect(path)
        legacy.execute(
            'CREATE TABLE role_vip (role_id INTEGER PRIMARY KEY,'
            ' vip_level INTEGER DEFAULT 0, state_day INTEGER DEFAULT 0,'
            ' state_week INTEGER DEFAULT 0, state_tejia TEXT,'
            ' prop_value INTEGER DEFAULT 0, tody_prop_value INTEGER DEFAULT 0,'
            ' day_time INTEGER DEFAULT 0, week_time INTEGER DEFAULT 0)')
        legacy.commit()
        legacy.close()
        store = Store(path)
        self.addCleanup(store.db.close)
        cols = {r['name'] for r in store.db.execute('PRAGMA table_info(role_vip)')}
        self.assertIn('prop_use_time', cols)
        store.save_role_vip(1, vip_level=1, prop_use_time=42)
        self.assertEqual(store.get_role_vip(1)['prop_use_time'], 42)

    def test_add_prop_value_without_row_pushes_nothing(self):
        self.assertEqual(self.sess.vip_add_prop_value(self.role, 50, 0), [])
        self.assertIsNone(self.store.get_role_vip(self.role_id))
        self.assertEqual(self.reg.pushed, [])


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class VipQqTest(VipPushTest):
    """88003 info, 88004 rewards and the 88005 bind push, golden against
    VipQqAction/VipQqServiceImpl bytecode (ModuleInit routes only the
    first two; 794000-794002 are error codes; the QQ platform callback
    behind vipQqOK has no local equivalent)."""

    def setUp(self):
        super().setUp()
        self.sess.get_role_qq_list = self.store.get_role_qq_list
        self.sess.save_role_qq_list = self.store.save_role_qq_list
        self.sess.get_vip_qq = self.store.get_vip_qq
        self.sess.save_vip_qq = self.store.save_vip_qq
        self.store.save_vip_qq(min_recharge=100, pic='p', qq='q')

    def info(self, charge=0):
        return self.frames(self.sess.vipqq_info([88003, []],
                                                charge_total=charge))

    def rewards(self):
        return self.frames(self.sess.vipqq_rewards([88004, []]))

    def test_wire_ids_match_java(self):
        from game.protocol import (BAG_ERR_SLOT_LESS, CMD_VIPQQ_BIND_PUSH,
                                   CMD_VIPQQ_INFO, CMD_VIPQQ_REWARDS,
                                   VIPQQ_ERR_CLAIMED, VIPQQ_ERR_NOBIND,
                                   VIPQQ_ERR_NOCONFIG)
        self.assertEqual((CMD_VIPQQ_INFO, CMD_VIPQQ_REWARDS,
                          CMD_VIPQQ_BIND_PUSH),
                         (88003, 88004, 88005))
        self.assertEqual((VIPQQ_ERR_NOBIND, VIPQQ_ERR_CLAIMED,
                          VIPQQ_ERR_NOCONFIG),
                         ('794000', '794001', '794002'))
        self.assertEqual(BAG_ERR_SLOT_LESS, 430212)

    def test_info_without_config_answers_794002(self):
        self.store.db.execute('DELETE FROM vip_qq')
        self.store.db.commit()
        self.assertEqual(self.info(), [['88003', [0, '794002']]])

    def test_info_flags_recharge_and_claim(self):
        self.assertEqual(self.info(),
                         [['88003', [1, 100, 0, 'p', 'q']]])
        self.assertEqual(self.info(charge=1000),
                         [['88003', [1, 100, 1, 'p', 'q']]])
        self.store.save_role_qq_list(self.role_id, qq='1', user_name='u',
                                     is_get_rewards=1)
        self.assertEqual(self.info(charge=1000),
                         [['88003', [1, 100, 2, 'p', 'q']]])

    def test_rewards_without_binding_answers_794000(self):
        self.assertEqual(self.rewards(), [['88004', [0, '794000']]])

    def test_rewards_claimed_answers_794001(self):
        self.store.save_role_qq_list(self.role_id, qq='1', user_name='u',
                                     is_get_rewards=1)
        self.assertEqual(self.rewards(), [['88004', [0, '794001']]])

    def test_rewards_success_grants_and_claims(self):
        self.store.save_role_qq_list(self.role_id, qq='1', user_name='u',
                                     is_get_rewards=0)
        self.assertEqual(self.rewards(), [['88004', [1]]])
        row = self.store.get_role_qq_list(self.role_id)
        self.assertEqual(row['is_get_rewards'], 1)
        goods = {s['goods_id']
                 for s in self.store.get_role_bag_slots(self.role_id, 1,
                                                         150)}
        for gid, _count, _bind in self.cfg.vipqq_rewards():
            self.assertIn(gid, goods)

    def test_bind_pushes_88005_with_null(self):
        out = self.sess.vipqq_bind(self.role, '1', 'u')
        self.assertEqual([decode(f[4:]) for f in out], [['88005', None]])
        self.assertEqual(self.reg.pushed, [(str(self.role_id), out)])
        row = self.store.get_role_qq_list(self.role_id)
        self.assertEqual((row['qq'], row['user_name'],
                          row['is_get_rewards']),
                         ('1', 'u', 0))

    def test_recharge_pushes_88003_refresh(self):
        self.store.save_role_qq_list(self.role_id, qq='1', user_name='u',
                                     is_get_rewards=0)
        self.assertEqual(self.sess.vipqq_recharge(self.role, 0), [])
        out = self.sess.vipqq_recharge(self.role, 1000)
        self.assertEqual([decode(f[4:]) for f in out],
                         [['88003', [1, 100, 1, 'p', 'q']]])
        self.store.save_role_qq_list(self.role_id, is_get_rewards=1)
        self.assertEqual(self.sess.vipqq_recharge(self.role, 1000), [])


if __name__ == '__main__':
    unittest.main()

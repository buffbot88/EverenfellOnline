"""Goldens for the equip enhance + dress slices (34000/34003/34009/31001).

Oracle: RoleEquipSlotServiceImpl.qiangHuaEquip/qianHuaClear/qianHuaMax/
dressEquip/peiDaiEquip/unLoadEquip/checkEquip plus EquipAction request
parsing, traced via tools/javap.py against dntg_start.jar. 31015/31035
ride the 11101 broadcast and 30106 is a session-directed push; none
has an inbound route (push-only). Worn slots are the (-105, 0) band
(slot = -eqpart); the dress reply is [1, info, xingxingLv] over a
formatMove [id, slot, count, bind] pair. Worn ids read as goods ids
and worn bind as 0, like the 31000 record; events need a bus.
"""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from auth import hash_password
from db import Store
from game.amf3 import decode
from game.config import GameConfig
from game.protocol import Session

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..', 'reference',
                           'TonNgoKhong', 'server', 'config', 'game')

HAVE_REAL = os.path.isfile(os.path.join(REAL_CONFIG, 'sys_config',
                                        'ZhuangBeiQiangHua.jat'))


def blob(qh, stars=(), fails=0):
    """Role_equip_slot.attributes blob with qhcount, stars, fail count."""
    return json.dumps({'fjattrstr': '{}', 'jjfailcount': fails, 'qhcount': qh,
                       'qhxingxing': json.dumps([list(s) for s in stars])},
                      separators=(',', ':'))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class EquipQianghuaTest(unittest.TestCase):
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
            get_role_equip=self.store.get_role_equip,
            save_role_equip=self.store.save_role_equip,
            save_role_state=self.store.update_character_state,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=30)

    def gear(self, goods='zj0011', qh=0, slot=1):
        self.store.save_role_equip(
            self.role_id, [{'slot_num': slot, 'goods_id': goods,
                            'rare_level': 1, 'item_level': 1,
                            'attributes': blob(qh)}])

    def bag(self, goods, count, slot):
        self.store.save_role_bag_slots(
            self.role_id, [{'slot_num': slot, 'goods_id': goods,
                            'count': count, 'bag_id': f'g{slot}', 'bind': 0,
                            'expire_time': 0, 'rare_level': 0, 'item_level': 1,
                            'attributes': None}])

    def frames(self, out):
        self.assertIsNotNone(out)
        if not isinstance(out, tuple):
            return [decode(out[4:])]
        return [decode(f[4:]) for f in out]

    def role(self):
        return self.store.list_roles('hero', 'fu1304')[0]

    def vo(self):
        rows = self.store.get_role_equip(self.role_id)
        self.assertEqual(len(rows), 1)
        return json.loads(rows[0]['attributes'])

    @staticmethod
    def assoc(m):
        """Unwrap the decoder's dynamic-object envelope around formart maps."""
        return m.get('__assoc__', m)

    def call(self, cmd, *args):
        if cmd == 34000:
            return self.frames(self.sess.equip_qianghua([cmd, list(args)]))
        if cmd == 34001:
            return self.frames(self.sess.equip_jinjie([cmd, list(args)]))
        if cmd == 34003:
            return self.frames(self.sess.equip_qianghua_clear([cmd, args[0]]))
        if cmd == 34009:
            return self.frames(self.sess.equip_qianghua_max([cmd, list(args)]))
        return self.frames(self.sess.equip_dress([cmd, list(args)]))

    def test_first_enhance_always_hits_at_odds_one(self):
        # zj0011 qhlv0 carries qhodds 1.00, so the roll is deterministic:
        # no notice row (qhnotice 0), hence [30106, 34000].
        self.gear()
        self.bag('qianghuashi', 3, 10)
        got = self.call(34000, '1', 0, 0)
        self.assertEqual([f[0] for f in got], ['30106', '34000'])
        self.assertEqual(got[1][1], [1, '1'])
        self.assertEqual(self.vo()['qhcount'], 1)
        self.assertEqual(json.loads(self.vo()['qhxingxing']), [[1, 1]])
        self.assertEqual(self.role()['tongqian'], 1000000 - 10000)
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 10))
        change = self.assoc(got[0][1][0])
        self.assertEqual(change['14'], [1])
        self.assertEqual(change['10'], 1)

    def test_failed_roll_still_bumps_qhcount(self):
        # Literal Java quirk: the fail branch also steps qhcount +1 and
        # persists; only the star bit (0) and the [-1, id] reply differ.
        # The RNG is forced white-box; the quirk itself is bytecode-traced.
        self.gear(qh=1)
        self.store.save_role_bag_slots(self.role_id, [
            {'slot_num': 10, 'goods_id': 'qianghuashi', 'count': 6,
             'bag_id': 'g10', 'bind': 0, 'expire_time': 0, 'rare_level': 0,
             'item_level': 1, 'attributes': None}])
        with mock.patch.object(Session, '_lottery_roll', return_value=False):
            got = self.call(34000, '1', 0, 0)
        self.assertEqual([f[0] for f in got], ['30106', '34000'])
        self.assertEqual(got[1][1], [-1, '1'])
        self.assertEqual(self.vo()['qhcount'], 2)
        self.assertEqual(json.loads(self.vo()['qhxingxing']), [[2, 0]])
        self.assertEqual(self.role()['tongqian'], 1000000 - 20000)

    def test_gold_slot_adds_odds_and_zero_extra(self):
        # glod1 is 0.1|5: the odds bonus applies, and the literal extra
        # (int)(1/5) is 0, so no BIND_YB/YB moves beyond qhJb.
        self.gear()
        self.bag('qianghuashi', 3, 10)
        before_yb = self.role()['lingshi']
        got = self.call(34000, '1', 0, 1)
        self.assertEqual(got[1][1], [1, '1'])
        self.assertEqual(self.role()['lingshi'], before_yb)
        self.assertEqual(self.role()['tongqian'], 1000000 - 10000)

    def test_gates_report_without_consume(self):
        self.gear(qh=10)
        self.bag('qianghuashi', 99, 10)
        got = self.call(34000, '1', 0, 0)
        self.assertEqual(got, [['34000', [0, 31009]]])
        # No real row reaches the permit gate (permitqh is 0 only on
        # maxed rows, which the max gate catches first), so it is pinned
        # white-box with a synthetic config, like the lihe cost golden.
        self.gear()
        cfg = self.cfg.qianghua_config('zj0011', 0)
        cfg = dict(cfg, isQianghua=False)
        with mock.patch.object(self.cfg, 'qianghua_config',
                               return_value=cfg):
            got = self.call(34000, '1', 0, 0)
        self.assertEqual(got, [['34000', [0, 31010]]])
        self.gear()
        self.store.update_character_state(self.role_id, tongqian=5)
        self.bag('qianghuashi', 99, 10)
        got = self.call(34000, '1', 0, 0)
        self.assertEqual(got, [['34000', [0, 31011]]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 10)['count'], 99)
        self.store.update_character_state(self.role_id, tongqian=1000000)
        self.store.save_role_bag_slots(self.role_id, [])
        got = self.call(34000, '1', 0, 0)
        self.assertEqual(got, [['34000', [0, 31012]]])
        self.assertEqual(self.role()['tongqian'], 1000000)

    def test_unknown_slot_stays_silent(self):
        self.gear()
        self.assertIsNone(self.sess.equip_qianghua([34000, ['9', 0, 0]]))

    def test_clear_resets_and_consumes_charm(self):
        self.gear(qh=2)
        self.store.save_role_bag_slots(self.role_id, [
            {'slot_num': 11, 'goods_id': 'qianghuaqingxifu', 'count': 1,
             'bag_id': 'g11', 'bind': 0, 'expire_time': 0, 'rare_level': 0,
             'item_level': 1, 'attributes': None}])
        before_yb = self.role()['lingshi']
        got = self.call(34003, '1')
        self.assertEqual([f[0] for f in got], ['30106', '34003'])
        self.assertEqual(got[1][1], [1, '1'])
        self.assertEqual(self.vo()['qhcount'], 0)
        self.assertEqual(json.loads(self.vo()['qhxingxing']), [])
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 11))
        self.assertEqual(self.role()['lingshi'], before_yb - 5)

    def test_clear_gates(self):
        self.gear()
        got = self.call(34003, '9')
        self.assertEqual(got, [['34003', [0, 31001]]])
        self.store.save_role_bag_slots(self.role_id, [])
        self.store.update_character_state(self.role_id, lingshi=0)
        got = self.call(34003, '1')
        self.assertEqual(got, [['34003', [0, 31012]]])
        self.assertEqual(self.vo()['qhcount'], 0)

    def test_max_steps_to_eleven_and_notifies(self):
        self.gear(qh=10)
        self.bag('jinglianshi', 1, 12)
        got = self.call(34009, '1')
        self.assertEqual([f[0] for f in got], ['11101', '30106', '34009'])
        notice = got[0][1]
        self.assertEqual(notice[0], '31035')
        self.assertEqual(notice[1][0], 'Wukong')
        self.assertEqual(notice[1][2], '+MAX')
        self.assertEqual(got[2][1], [1])
        self.assertEqual(self.vo()['qhcount'], 11)
        self.assertEqual(self.role()['tongqian'], 1000000 - 300000)
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 12))

    def test_max_gates(self):
        self.gear(qh=11)
        self.bag('jinglianshi', 1, 12)
        got = self.call(34009, '1')
        self.assertEqual(got, [['34009', [0, 31034]]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 12)['count'], 1)
        self.gear(qh=10)
        self.store.update_character_state(self.role_id, tongqian=5)
        got = self.call(34009, '1')
        self.assertEqual(got, [['34009', [0, 31011]]])
        self.store.update_character_state(self.role_id, tongqian=1000000)
        self.store.save_role_bag_slots(self.role_id, [])
        got = self.call(34009, '1')
        self.assertEqual(got, [['34009', [0, 1005]]])

    def test_command_ids_match_map(self):
        from game.protocol import (CMD_EQUIP_CHANGE, CMD_EQUIP_NOTICE,
                                   CMD_EQUIP_QIANGHUA, CMD_EQUIP_QIANGHUA_CLEAR,
                                   CMD_EQUIP_QIANGHUA_MAX, CMD_NOTICE_ALL)
        self.assertEqual(
            (CMD_EQUIP_QIANGHUA, CMD_EQUIP_QIANGHUA_CLEAR,
             CMD_EQUIP_QIANGHUA_MAX, CMD_EQUIP_NOTICE, CMD_EQUIP_CHANGE,
             CMD_NOTICE_ALL),
            (34000, 34003, 34009, 31015, 30106, 11101))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class EquipJinjieTest(EquipQianghuaTest):
    def gear10(self, goods='zj0011', fails=0):
        self.store.save_role_equip(
            self.role_id, [{'slot_num': 1, 'goods_id': goods,
                            'rare_level': 1, 'item_level': 1,
                            'attributes': blob(10, fails=fails)}])

    def costs(self, qianghuashi=5, jinjieshi=1):
        rows = []
        if qianghuashi:
            rows.append({'slot_num': 10, 'goods_id': 'qianghuashi',
                         'count': qianghuashi, 'bag_id': 'g10', 'bind': 0,
                         'expire_time': 0, 'rare_level': 0, 'item_level': 1,
                         'attributes': None})
        if jinjieshi:
            rows.append({'slot_num': 11, 'goods_id': 'jinjieshi',
                         'count': jinjieshi, 'bag_id': 'g11', 'bind': 0,
                         'expire_time': 0, 'rare_level': 0, 'item_level': 1,
                         'attributes': None})
        self.store.save_role_bag_slots(self.role_id, rows)

    def test_jinjie_swaps_gear_and_notifies(self):
        # zj0011 qhlv10: min=max=0, odds 1.00, so success is deterministic.
        self.gear10()
        self.costs()
        got = self.call(34001, '1', 0)
        self.assertEqual([f[0] for f in got], ['11101', '30106', '34001'])
        notice = got[0][1]
        self.assertEqual(notice[0], '31016')
        self.assertEqual(notice[1][0], 'Wukong')
        self.assertNotEqual(notice[1][1], notice[1][2])
        self.assertEqual(got[2][1], [1, '1'])
        rows = self.store.get_role_equip(self.role_id)
        self.assertEqual(rows[0]['goods_id'], 'zj0201')
        self.assertEqual(rows[0]['item_level'], 20)
        self.assertEqual(json.loads(rows[0]['attributes'])['qhcount'], 10)
        self.assertEqual(self.role()['tongqian'], 1000000 - 10000)
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 11))

    def test_pity_fail_bumps_fail_count(self):
        # zj0601: min 2, so fails 0 fails outright and burns the costs.
        # Its target needs level 70, hence the bump (the gate golden below
        # pins the un-bumped 56).
        self.store.update_character_state(self.role_id, level=70)
        self.gear10(goods='zj0601')
        self.store.save_role_bag_slots(self.role_id, [
            {'slot_num': 10, 'goods_id': 'qianghuashi', 'count': 20,
             'bag_id': 'g10', 'bind': 0, 'expire_time': 0, 'rare_level': 0,
             'item_level': 1, 'attributes': None},
            {'slot_num': 11, 'goods_id': 'jinjieshi', 'count': 5,
             'bag_id': 'g11', 'bind': 0, 'expire_time': 0, 'rare_level': 0,
             'item_level': 1, 'attributes': None}])
        got = self.call(34001, '1', 0)
        self.assertEqual([f[0] for f in got], ['30106', '34001'])
        self.assertEqual(got[1][1], [-1, '1'])
        rows = self.store.get_role_equip(self.role_id)
        self.assertEqual(rows[0]['goods_id'], 'zj0601')
        self.assertEqual(
            json.loads(rows[0]['attributes'])['jjfailcount'], 1)
        self.assertEqual(self.role()['tongqian'], 1000000 - 40000)

    def test_pity_success_skips_the_roll(self):
        # Fails 3 >= max 3 succeeds even with a rigged-against roll.
        self.store.update_character_state(self.role_id, level=70)
        self.gear10(goods='zj0601', fails=3)
        self.store.save_role_bag_slots(self.role_id, [
            {'slot_num': 10, 'goods_id': 'qianghuashi', 'count': 20,
             'bag_id': 'g10', 'bind': 0, 'expire_time': 0, 'rare_level': 0,
             'item_level': 1, 'attributes': None},
            {'slot_num': 11, 'goods_id': 'jinjieshi', 'count': 5,
             'bag_id': 'g11', 'bind': 0, 'expire_time': 0, 'rare_level': 0,
             'item_level': 1, 'attributes': None}])
        with mock.patch.object(Session, '_lottery_roll',
                               return_value=False):
            got = self.call(34001, '1', 0)
        self.assertEqual(got[2][1], [1, '1'])
        rows = self.store.get_role_equip(self.role_id)
        self.assertEqual(rows[0]['goods_id'], 'zj0701')

    def test_mid_pity_uses_the_roll(self):
        # Fails 2 sits in [min, max), so the forced roll decides.
        self.store.update_character_state(self.role_id, level=70)
        self.gear10(goods='zj0601', fails=2)
        self.costs(qianghuashi=20, jinjieshi=5)
        with mock.patch.object(Session, '_lottery_roll',
                               return_value=False):
            got = self.call(34001, '1', 0)
        self.assertEqual(got[1][1], [-1, '1'])
        rows = self.store.get_role_equip(self.role_id)
        self.assertEqual(
            json.loads(rows[0]['attributes'])['jjfailcount'], 3)

    def test_gates_report_without_consume(self):
        self.gear()
        got = self.call(34001, '1', 0)
        self.assertEqual(got, [['34001', [0, 31013]]])
        self.gear10(goods='zj0601')
        self.costs(qianghuashi=20, jinjieshi=5)
        got = self.call(34001, '1', 0)
        self.assertEqual(got, [['34001', [0, 1000]]])
        self.assertEqual(self.role()['tongqian'], 1000000)
        self.gear10()
        self.costs()
        self.store.update_character_state(self.role_id, tongqian=5)
        got = self.call(34001, '1', 0)
        self.assertEqual(got, [['34001', [0, 31011]]])
        self.assertEqual(
            self.store.get_role_bag_slot(self.role_id, 10)['count'], 5)
        self.store.update_character_state(self.role_id, tongqian=1000000)
        self.store.save_role_bag_slots(self.role_id, [])
        got = self.call(34001, '1', 0)
        self.assertEqual(got, [['34001', [0, 31012]]])
        self.assertEqual(self.role()['tongqian'], 1000000)

    def test_unknown_slot_stays_silent(self):
        self.gear10()
        self.assertIsNone(self.sess.equip_jinjie([34001, ['9', 0]]))

    def test_jinjie_ids_match_map(self):
        from game.protocol import (CMD_EQUIP_CHANGE, CMD_EQUIP_JINJIE,
                                   CMD_EQUIP_JINJIE_NOTICE, CMD_NOTICE_ALL)
        self.assertEqual(
            (CMD_EQUIP_JINJIE, CMD_EQUIP_JINJIE_NOTICE, CMD_EQUIP_CHANGE,
             CMD_NOTICE_ALL),
            (34001, 31016, 30106, 11101))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class EquipJiandingTest(unittest.TestCase):
    """Goldens for the jianding slice (34004/34005/34006).

    Oracle: RoleEquipSlotServiceImpl.jianDing/jianDingClear/getJianDingExp
    plus lotteryKey and the GoodsEquipVo fjattrstr helpers, traced via
    tools/javap.py against dntg_start.jar. 34004 gates fire before any
    consume; the RNG pins use the same white-box patch style as the
    enhance fail golden. zj0401 is both an appraisable gear and a
    cailiao-flagged equip material (category 20, itemLevel 40).
    """
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
            get_role_equip=self.store.get_role_equip,
            save_role_equip=self.store.save_role_equip,
            get_role_jianding=self.store.get_role_jianding,
            save_role_jianding=self.store.save_role_jianding,
            get_role_vip=self.store.get_role_vip,
            save_role_state=self.store.update_character_state,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=30)

    def gear(self, goods='zj0401', pairs=None, slot=1):
        fj = json.dumps({str(k): f'{fid}@{cnt}'
                         for k, (fid, cnt) in (pairs or {}).items()},
                        separators=(',', ':'))
        self.store.save_role_equip(
            self.role_id, [{'slot_num': slot, 'goods_id': goods,
                            'rare_level': 1, 'item_level': 40,
                            'attributes': json.dumps(
                                {'fjattrstr': fj, 'qhcount': 0},
                                separators=(',', ':'))}])

    def bag(self, goods, count, slot, bag_id=None):
        self.store.save_role_bag_slots(
            self.role_id, [{'slot_num': slot, 'goods_id': goods,
                            'count': count,
                            'bag_id': bag_id or f'g{slot}', 'bind': 0,
                            'expire_time': 0, 'rare_level': 0, 'item_level': 1,
                            'attributes': None}])

    def frames(self, out):
        self.assertIsNotNone(out)
        if not isinstance(out, tuple):
            return [decode(out[4:])]
        return [decode(f[4:]) for f in out]

    def role(self):
        return self.store.list_roles('hero', 'fu1304')[0]

    def call(self, cmd, *args):
        if cmd == 34004:
            return self.frames(self.sess.equip_jianding([cmd, list(args)]))
        if cmd == 34005:
            return self.frames(
                self.sess.equip_jianding_clear([cmd, list(args)]))
        return self.frames(self.sess.equip_jianding_exp([cmd, list(args)]))

    def test_unknown_gear_and_material(self):
        self.gear()
        self.bag('zj0401', 1, 10)
        got = self.call(34004, '9', 'g10', 1)
        self.assertEqual(got, [['34004', [0, 31001]]])
        got = self.call(34004, '1', 'g99', 1)
        self.assertEqual(got, [['34004', [0, 31001]]])
        self.assertEqual(self.role()['tongqian'], 1000000)

    def test_gear_must_be_appraisable(self):
        # zj0011 carries no jianding flag; the gate precedes the level
        # match even though its itemLevel differs too.
        self.gear(goods='zj0011')
        self.bag('zj0401', 1, 10)
        got = self.call(34004, '1', 'g10', 1)
        self.assertEqual(got, [['34004', [0, 31027]]])

    def test_material_must_be_cailiao_or_stone(self):
        # zj0011 is category-20 gear without the jdcailiao flag.
        self.gear()
        self.bag('zj0011', 1, 10)
        got = self.call(34004, '1', 'g10', 1)
        self.assertEqual(got, [['34004', [0, 31028]]])

    def test_material_level_must_match(self):
        # qianghuashi is no equip, so only the itemLevel gate can fire.
        self.gear()
        self.bag('qianghuashi', 1, 10)
        got = self.call(34004, '1', 'g10', 1)
        self.assertEqual(got, [['34004', [0, 31020]]])

    def test_capped_pair_has_no_slot(self):
        # Rare-1 max is 12; both pair halves full resolves to -1.
        self.gear(pairs={1: (3, 12), 2: (5, 12)})
        self.bag('zj0401', 1, 10)
        got = self.call(34004, '1', 'g10', 1)
        self.assertEqual(got, [['34004', [0, 31021]]])
        self.assertEqual(self.role()['tongqian'], 1000000)

    def test_vip_and_level_both_short(self):
        # Pair 2 needs vip 5 and role 70; the role is 56 with no vip.
        self.gear()
        self.bag('zj0401', 1, 10)
        got = self.call(34004, '1', 'g10', 2)
        self.assertEqual(got, [['34004', [0, 31016]]])
        self.assertEqual(self.role()['tongqian'], 1000000)

    def test_star_short_needs_vip_cover(self):
        # Vip 5 alone clears the combined gate, exposing the star gate:
        # fresh gear has xingxing 0 below needEquipLv 3.
        self.store.save_role_vip(self.role_id, vip_level=5)
        self.gear()
        self.bag('zj0401', 1, 10)
        got = self.call(34004, '1', 'g10', 2)
        self.assertEqual(got, [['34004', [0, 31017]]])

    def test_copper_short(self):
        self.gear()
        self.bag('zj0401', 1, 10)
        self.store.update_character_state(self.role_id, tongqian=5)
        got = self.call(34004, '1', 'g10', 1)
        self.assertEqual(got, [['34004', [0, 1003]]])
        self.assertIsNotNone(
            self.store.get_role_bag_slot_by_bag_id(self.role_id, 'g10'))

    def test_success_opens_empty_slot(self):
        # Pair 1 untouched opens slot 1; the rigged winner lands at the
        # rare minimum with rolled 0 in the reply.
        self.gear()
        self.bag('zj0401', 1, 10)
        with mock.patch.object(Session, '_lottery_map_key',
                               return_value=5), mock.patch.object(
                Session, '_lottery_success', return_value=True):
            got = self.call(34004, '1', 'g10', 1)
        self.assertEqual([f[0] for f in got], ['30106', '34004'])
        self.assertEqual(got[1][1], [1, '1', 1, 5, 1, 0, 0])
        rows = self.store.get_role_equip(self.role_id)
        self.assertEqual(json.loads(rows[0]['attributes'])['fjattrstr'],
                         '{"1":"5@1"}')
        self.assertEqual(self.role()['tongqian'], 1000000 - 20000)
        self.assertIsNone(
            self.store.get_role_bag_slot_by_bag_id(self.role_id, 'g10'))
        jd = self.store.get_role_jianding(str(self.role_id))
        self.assertEqual(jd['jianding_count'], 1)

    def test_half_filled_pair_opens_empty_half(self):
        # Slot 1 taken sends pair 1 at slot 2; the rigged winner opens
        # there at the rare minimum.
        self.gear(pairs={1: (3, 2)})
        self.bag('zj0401', 1, 10)
        with mock.patch.object(Session, '_lottery_map_key',
                               return_value=6), mock.patch.object(
                Session, '_lottery_success', return_value=True):
            got = self.call(34004, '1', 'g10', 1)
        self.assertEqual(got[1][1], [1, '1', 2, 6, 1, 0, 0])
        rows = self.store.get_role_equip(self.role_id)
        self.assertEqual(json.loads(rows[0]['attributes'])['fjattrstr'],
                         '{"1":"3@2","2":"6@1"}')

    def test_success_adds_capped_count(self):
        # Slot 2 maxed sends pair 1 back at slot 1, where the rolled 2
        # lands under the rare max of 12.
        self.gear(pairs={1: (3, 2), 2: (5, 12)})
        self.bag('zj0401', 1, 10)
        with mock.patch.object(Session, '_lottery_success',
                               return_value=True), mock.patch.object(
                Session, '_lottery_weighted_key', return_value=2):
            got = self.call(34004, '1', 'g10', 1)
        self.assertEqual(got[1][1], [1, '1', 1, 3, 4, 2, 0])
        rows = self.store.get_role_equip(self.role_id)
        self.assertEqual(json.loads(rows[0]['attributes'])['fjattrstr'],
                         '{"1":"3@4","2":"5@12"}')

    def test_failure_banks_exp(self):
        # addexp 2500 * role 56 lands under the 56 cap, so the full
        # amount reaches both the pool and the role with a 12001 push.
        self.gear()
        self.bag('zj0401', 1, 10)
        with mock.patch.object(Session, '_lottery_success',
                               return_value=False):
            got = self.call(34004, '1', 'g10', 1)
        self.assertEqual([f[0] for f in got], ['12001', '34004'])
        self.assertEqual(got[1][1], [1, '1', 1, 0, 0, 0, 140000])
        self.assertEqual(self.role()['exp'], 140000)
        jd = self.store.get_role_jianding(str(self.role_id))
        self.assertEqual(
            (jd['jianding_exp'], jd['jianding_count']), (140000, 1))

    def test_clear_consumes_charm(self):
        self.gear(pairs={1: (3, 2)})
        self.bag('jiandingqingxifu', 1, 11)
        got = self.call(34005, '1', 1)
        self.assertEqual([f[0] for f in got], ['30106', '34005'])
        self.assertEqual(got[1][1], [1, '1', 1])
        rows = self.store.get_role_equip(self.role_id)
        self.assertEqual(json.loads(rows[0]['attributes'])['fjattrstr'],
                         '{}')
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 11))

    def test_clear_gold_short(self):
        self.gear(pairs={1: (3, 2)})
        self.store.update_character_state(self.role_id, bind_lingshi=0,
                                          lingshi=0)
        got = self.call(34005, '1', 1)
        self.assertEqual(got, [['34005', [0, 31015]]])

    def test_get_exp_empty_and_stored(self):
        self.assertEqual(self.call(34006), [['34006', [0]]])
        self.store.save_role_jianding(
            str(self.role_id), jianding_exp=140000, jianding_count=2,
            jianding_time=int(time.time() * 1000), hecheng_count=3)
        self.assertEqual(self.call(34006), [['34006', [140000, 3]]])

    def test_jianding_ids_match_map(self):
        from game.protocol import (CMD_EQUIP_CHANGE, CMD_EQUIP_JIANDING,
                                   CMD_EQUIP_JIANDING_CLEAR,
                                   CMD_EQUIP_JIANDING_EXP)
        self.assertEqual(
            (CMD_EQUIP_JIANDING, CMD_EQUIP_JIANDING_CLEAR,
             CMD_EQUIP_JIANDING_EXP, CMD_EQUIP_CHANGE),
            (34004, 34005, 34006, 30106))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class EquipHechengTest(unittest.TestCase):
    """Goldens for the hecheng slice (34007/34008).

    Oracle: RoleEquipSlotServiceImpl.heCheng/gethehengCount, traced via
    tools/javap.py against dntg_start.jar. Synthesis is deterministic
    (no lottery): 4 same-level cailiao materials fuse into the
    next-tier scroll. jiandingjuan40 (category 90, itemLevel 40) chains
    into jiandingjuan50. The 31025 branch needs a non-juanzhou row
    and the stone-short branch needs stones; no such rows exist in
    data, so both are carried as dead-but-ported branches.
    """
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
            get_role_equip=self.store.get_role_equip,
            save_role_equip=self.store.save_role_equip,
            get_role_jianding=self.store.get_role_jianding,
            save_role_jianding=self.store.save_role_jianding,
            get_role_vip=self.store.get_role_vip,
            save_role_state=self.store.update_character_state,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=30)

    def bag(self, goods, count, slot, bind=0):
        self.store.save_role_bag_slots(
            self.role_id, [{'slot_num': slot, 'goods_id': goods,
                            'count': count, 'bag_id': f'g{slot}',
                            'bind': bind, 'expire_time': 0, 'rare_level': 0,
                            'item_level': 1, 'attributes': None}])

    def frames(self, out):
        self.assertIsNotNone(out)
        if not isinstance(out, tuple):
            return [decode(out[4:])]
        return [decode(f[4:]) for f in out]

    def call(self, cmd, *args):
        if cmd == 34007:
            return self.frames(self.sess.equip_hecheng([cmd, list(args)]))
        return self.frames(self.sess.equip_hecheng_count([cmd, list(args)]))

    def scrolls40(self):
        self.store.save_role_bag_slots(
            self.role_id, [{'slot_num': slot, 'goods_id': 'jiandingjuan40',
                            'count': 1, 'bag_id': f'g{slot}', 'bind': 0,
                            'expire_time': 0, 'rare_level': 0, 'item_level': 1,
                            'attributes': None}
                           for slot in (10, 11, 12, 13)])

    def counts(self, goods):
        return sum(s['count'] for s in
                   self.store.get_role_bag_slots(self.role_id, 1, 150)
                   if s['goods_id'] == goods)

    def test_arg_count(self):
        self.scrolls40()
        got = self.call(34007, 'g10', 'g11', 'g12')
        self.assertEqual(got, [['34007', [0, 31022]]])
        self.assertEqual(self.counts('jiandingjuan40'), 4)

    def test_unknown_material(self):
        self.scrolls40()
        got = self.call(34007, 'g10', 'g11', 'g12', 'g99')
        self.assertEqual(got, [['34007', [0, 31001]]])

    def test_equip_without_flag_names_itself(self):
        self.scrolls40()
        self.store.save_role_bag_slots(
            self.role_id, [self.store.get_role_bag_slot(self.role_id, 10),
                           self.store.get_role_bag_slot(self.role_id, 11),
                           self.store.get_role_bag_slot(self.role_id, 12),
                           {'slot_num': 14, 'goods_id': 'zj0011', 'count': 1,
                            'bag_id': 'g14', 'bind': 0, 'expire_time': 0,
                            'rare_level': 0, 'item_level': 1,
                            'attributes': None}])
        got = self.call(34007, 'g10', 'g11', 'g12', 'g14')
        self.assertEqual(got[0][0], '34007')
        self.assertEqual(got[0][1][0], 0)
        self.assertEqual(got[0][1][1], 31029)
        self.assertEqual(
            got[0][1][2],
            self.cfg._goods_table()['zj0011']['name'])

    def test_plain_goods_rejected(self):
        self.scrolls40()
        self.store.save_role_bag_slots(
            self.role_id, [self.store.get_role_bag_slot(self.role_id, 10),
                           self.store.get_role_bag_slot(self.role_id, 11),
                           self.store.get_role_bag_slot(self.role_id, 12),
                           {'slot_num': 14, 'goods_id': 'qianghuashi',
                            'count': 1, 'bag_id': 'g14', 'bind': 0,
                            'expire_time': 0, 'rare_level': 0, 'item_level': 1,
                            'attributes': None}])
        got = self.call(34007, 'g10', 'g11', 'g12', 'g14')
        self.assertEqual(got, [['34007', [0, 31024]]])

    def test_level_must_match(self):
        self.scrolls40()
        self.store.save_role_bag_slots(
            self.role_id, [self.store.get_role_bag_slot(self.role_id, 10),
                           self.store.get_role_bag_slot(self.role_id, 11),
                           self.store.get_role_bag_slot(self.role_id, 12),
                           {'slot_num': 14, 'goods_id': 'jiandingjuan50',
                            'count': 1, 'bag_id': 'g14', 'bind': 0,
                            'expire_time': 0, 'rare_level': 0, 'item_level': 1,
                            'attributes': None}])
        got = self.call(34007, 'g10', 'g11', 'g12', 'g14')
        self.assertEqual(got, [['34007', [0, 31023]]])

    def test_vip_cap(self):
        # hechengci is 999 at every vip level, so the pool must sit at
        # the cap to trip it.
        self.scrolls40()
        self.store.save_role_jianding(str(self.role_id), hecheng_count=999)
        got = self.call(34007, 'g10', 'g11', 'g12', 'g13')
        self.assertEqual(got, [['34007', [0, 31026]]])
        self.assertEqual(self.counts('jiandingjuan40'), 4)

    def test_fuse_four_scrolls(self):
        self.scrolls40()
        got = self.call(34007, 'g10', 'g11', 'g12', 'g13')
        self.assertEqual(got, [['34007', [1]]])
        self.assertEqual(self.counts('jiandingjuan40'), 0)
        self.assertEqual(self.counts('jiandingjuan50'), 1)
        jd = self.store.get_role_jianding(str(self.role_id))
        self.assertEqual(jd['hecheng_count'], 1)
        self.assertGreater(jd['hecheng_time'], 0)
        self.assertEqual(self.call(34008), [['34008', [1]]])

    def test_bind_flag_rides_reward(self):
        self.scrolls40()
        self.store.update_role_bag_slot(self.role_id, 10, bind=1)
        self.call(34007, 'g10', 'g11', 'g12', 'g13')
        rows = [s for s in
                self.store.get_role_bag_slots(self.role_id, 1, 150)
                if s['goods_id'] == 'jiandingjuan50']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['bind'], 1)

    def test_full_bag_blocks_reward(self):
        # Slots 1..4 fill capacity 4, so the check runs before the burn.
        self.store.save_role_bag_state(self.role_id, bag_capacity=4)
        self.store.save_role_bag_slots(
            self.role_id, [{'slot_num': slot, 'goods_id': 'jiandingjuan40',
                            'count': 1, 'bag_id': f'g{slot}', 'bind': 0,
                            'expire_time': 0, 'rare_level': 0, 'item_level': 1,
                            'attributes': None}
                           for slot in (1, 2, 3, 4)])
        got = self.call(34007, 'g1', 'g2', 'g3', 'g4')
        self.assertEqual(got, [['34007', [0, 1006]]])
        self.assertEqual(self.counts('jiandingjuan40'), 4)

    def test_count_empty_and_null(self):
        self.assertEqual(self.call(34008), [['34008', [0]]])
        self.scrolls40()
        self.call(34007, 'g10', 'g11', 'g12', 'g13')
        self.assertEqual(self.call(34008), [['34008', [1]]])

    def test_hecheng_ids_match_map(self):
        from game.protocol import (CMD_EQUIP_HECHENG, CMD_EQUIP_HECHENG_COUNT,
                                   EQUIP_ERROR_HC_ARGS, EQUIP_ERROR_HC_LEVEL,
                                   EQUIP_ERROR_HC_KIND, EQUIP_ERROR_HC_JUAN,
                                   EQUIP_ERROR_HC_LIMIT, EQUIP_ERROR_HC_MAT)
        self.assertEqual((CMD_EQUIP_HECHENG, CMD_EQUIP_HECHENG_COUNT),
                         (34007, 34008))
        self.assertEqual(
            (EQUIP_ERROR_HC_ARGS, EQUIP_ERROR_HC_LEVEL, EQUIP_ERROR_HC_KIND,
             EQUIP_ERROR_HC_JUAN, EQUIP_ERROR_HC_LIMIT, EQUIP_ERROR_HC_MAT),
            (31022, 31023, 31024, 31025, 31026, 31029))

@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class EquipDressTest(unittest.TestCase):
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
            get_role_equip=self.store.get_role_equip,
            save_role_equip=self.store.save_role_equip,
            get_role_zuoqi=self.store.get_role_zuoqi,
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

    def call(self, *args):
        return self.frames(self.sess.equip_dress([31001, list(args)]))

    def gear(self, goods='zj0011', slot=-70, attrs=None):
        self.store.save_role_equip(
            self.role_id, [{'slot_num': slot, 'goods_id': goods,
                            'rare_level': 1, 'item_level': 1,
                            'attributes': attrs}])

    def bag(self, goods, slot, count=1, bind=0):
        self.store.save_role_bag_slots(
            self.role_id, [{'slot_num': slot, 'goods_id': goods,
                            'count': count, 'bag_id': f'g{slot}', 'bind': bind,
                            'expire_time': 0, 'rare_level': 0, 'item_level': 1,
                            'attributes': None}])

    def worn(self, slot):
        rows = [r for r in self.store.get_role_equip(self.role_id)
                if r['slot_num'] == slot]
        return rows[0] if rows else None

    def test_wear_fresh(self):
        self.bag('zj0011', 10)
        self.assertEqual(
            self.call('g10', 10, -70),
            [['31001', [1, [None, ['zj0011', -70, 1, 0]], 0]]])
        self.assertEqual(self.worn(-70)['goods_id'], 'zj0011')
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 10))

    def test_wear_swap(self):
        self.gear()
        self.bag('zj0011', 11)
        got = self.call('g11', 11, -70)
        self.assertEqual(got[0][1][0], 1)
        self.assertEqual(got[0][1][1][0], ['zj0011', -70, 1, 0])
        self.assertEqual(got[0][1][1][1][0], 'zj0011')
        self.assertEqual(self.worn(-70)['goods_id'], 'zj0011')
        back = self.store.get_role_bag_slot(self.role_id, 11)
        self.assertEqual(back['goods_id'], 'zj0011')

    def test_wear_empty_slot(self):
        self.assertEqual(self.call('g9', 9, -70),
                         [['31001', [0, 31001]]])

    def test_wear_id_mismatch(self):
        self.bag('zj0011', 10)
        self.assertEqual(self.call('gX', 10, -70),
                         [['31001', [0, 31002]]])
        self.assertIsNone(self.worn(-70))

    def test_wear_unknown_goods(self):
        self.bag('nope', 10)
        self.assertEqual(self.call('g10', 10, -70),
                         [['31001', [0, 31004]]])

    def test_wear_not_equip(self):
        self.bag('qianghuashi', 10)
        self.assertEqual(self.call('g10', 10, -70),
                         [['31001', [0, 31005]]])

    def test_wear_wrong_job(self):
        self.bag('zj0013', 10)
        self.assertEqual(self.call('g10', 10, -70),
                         [['31001', [0, 31014]]])

    def test_wear_wrong_slot(self):
        self.bag('zj0011', 10)
        self.assertEqual(self.call('g10', 10, -71),
                         [['31001', [0, 31006]]])

    def test_wear_low_level(self):
        self.bag('zj0601', 10)
        self.assertEqual(self.call('g10', 10, -70),
                         [['31001', [0, 31007]]])

    def test_wear_zuoqi_rank(self):
        self.bag('zqzb0101', 10)
        self.assertEqual(self.call('g10', 10, -101),
                         [['31001', [0, 31036]]])
        self.store.save_role_zuoqi(str(self.role_id), zuoqi_rank=2)
        got = self.call('g10', 10, -101)
        self.assertEqual(got[0][1][0], 1)
        self.assertEqual(self.worn(-101)['goods_id'], 'zqzb0101')

    def test_unwear(self):
        self.gear()
        got = self.call('worn', -70, 20)
        self.assertEqual(got[0][1][0], 1)
        self.assertEqual(got[0][1][1],
                         [['zj0011', -70, 1, 0],
                          [got[0][1][1][1][0], 20, 1, 0]])
        self.assertIsNone(self.worn(-70))
        landed = self.store.get_role_bag_slot(self.role_id, 20)
        self.assertEqual(landed['goods_id'], 'zj0011')

    def test_unwear_empty(self):
        self.assertEqual(self.call('worn', -70, 20),
                         [['31001', [0, 31002]]])

    def test_unwear_target_taken(self):
        self.gear()
        self.bag('qianghuashi', 20, count=5)
        self.assertEqual(self.call('worn', -70, 20),
                         [['31001', [0, 31002]]])
        self.assertIsNotNone(self.worn(-70))

    def test_unwear_full_bag(self):
        self.gear()
        self.store.save_role_bag_state(self.role_id, bag_capacity=0)
        self.assertEqual(self.call('worn', -70, 20),
                         [['31001', [0, 31003]]])

    def test_band_mismatch_silent(self):
        self.bag('zj0011', 10)
        self.assertIsNone(self.sess.equip_dress([31001, ['g10', 10, 11]]))
        self.assertIsNone(self.sess.equip_dress([31001, ['g10', -70, -71]]))
        self.assertIsNone(self.sess.equip_dress([31001, ['g10', 0, -70]]))
        self.assertIsNone(self.sess.equip_dress([31001, ['g10', 10, 151]]))
        self.assertIsNone(self.sess.equip_dress([31001, [10, 10, -70]]))
        self.assertIsNone(self.sess.equip_dress([31001, ['g10', '10', -70]]))
        self.assertIsNone(self.worn(-70))

    def test_dress_ids_match_map(self):
        from game.protocol import (CMD_EQUIP_DRESS, EQUIP_ERROR_NOSLOT,
                                   EQUIP_ERROR_DRESS_MISMATCH,
                                   EQUIP_ERROR_DRESS_NOROOM,
                                   EQUIP_ERROR_DRESS_NOCONFIG,
                                   EQUIP_ERROR_DRESS_NOTEQUIP,
                                   EQUIP_ERROR_DRESS_BADSLOT,
                                   EQUIP_ERROR_DRESS_LEVEL,
                                   EQUIP_ERROR_DRESS_SEX,
                                   EQUIP_ERROR_DRESS_JOB,
                                   EQUIP_ERROR_DRESS_ZUOQIRANK,
                                   EQUIP_ERROR_DRESS_YUANSHEN)
        self.assertEqual(CMD_EQUIP_DRESS, 31001)
        self.assertEqual(
            (EQUIP_ERROR_NOSLOT, EQUIP_ERROR_DRESS_MISMATCH,
             EQUIP_ERROR_DRESS_NOROOM, EQUIP_ERROR_DRESS_NOCONFIG,
             EQUIP_ERROR_DRESS_NOTEQUIP, EQUIP_ERROR_DRESS_BADSLOT,
             EQUIP_ERROR_DRESS_LEVEL, EQUIP_ERROR_DRESS_SEX,
             EQUIP_ERROR_DRESS_JOB, EQUIP_ERROR_DRESS_ZUOQIRANK,
             EQUIP_ERROR_DRESS_YUANSHEN),
            (31001, 31002, 31003, 31004, 31005, 31006, 31007, 31008,
             31014, 31036, 31038))


if __name__ == '__main__':
    unittest.main()

"""Zonghe loader + first-recharge claim core (HuodongAction ct=21 family).

Evidence: docs/zonghe-finding.md (authentic fu0 snapshot at
MKO_Client/.../compositiveactivity/fu0, Java TC_LONGSTRING + JSON),
hdzh.txt (configureDataResolve null/empty silent keep-old, missing
activitys skips the category, convert failure drops unknown
clienttypes, HuodongInit after load), the CompositiveActivityClientType
int values (hdct.txt) and checkHuodongIsValid/timeIsExpiry semantics. The loader reads the shipped snapshot in place (like the reference/
 config tree) and preserves JSON types (con1 stays a string, thresholds
 are per-family). 70000/70001 are wired to HuodongAction's
getRechargeInfo/lingquRechargeReward with the exact firstrecharge
13-array and [1, configId]/[0, code] shapes recovered from
RoleHuodongOutputWrapper/HuodongServiceImpl bytecode; the tests pin
the full lifecycle through the wire: recharge latch + 71002 push
([activityId, yb, 1]), job-filtered grant, mount-rank side effect,
duplicate/bag-full/expiry gates.
 """
import copy
import json
import os
import struct
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode, encode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session, frame  # noqa: E402

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..',
                           'reference', 'TonNgoKhong', 'server', 'config',
                           'game')
HAVE_REAL = os.path.isdir(REAL_CONFIG)
SNAPSHOT = os.path.normpath(os.path.join(
    os.path.dirname(__file__), '..', '..', 'MKO_Client', 'Assets',
    'gameconfig', 'upload', 'gameanalyze', 'compositiveactivity', 'fu0'))
HAVE_SNAPSHOT = os.path.isfile(SNAPSHOT)

# ct=21 has 16 single-activity categories; 20140301-21-1 is explicit
# 1393603201000-1393689599000 and grants only firstrechargearwardarray
# items (its awards currencies are all zero in fu0).
LIVE_NOW = 1393603201000 + 3600000
LIVE_CAT = '20140301-21-1'
LIVE_ACT = '20140301-qbsc0002-1'
LIVE_PAIRS = [['qibinglixiang1', 1], ['qibing001', 2],
              ['expfold_002', 1], ['xunbaotu01', 2],
              ['xunbaotu02', 2], ['tongqian003', 1]]
# The grant filters like GoodsJobFilter: xunbaotu02 has no goods-table
# row, so the jar drops it from the grant (the 70000 display keeps it).
LIVE_GRANTED = [p for p in LIVE_PAIRS if p[0] != 'xunbaotu02']
# Kaifu-relative day-1 category (startday 0, kaifudays 1): live in
# [kaifu, kaifu + 1 day). Its award mixes job-C/A/D/B equips with
# universal goods; a job-C role keeps zj0401 plus the universals.
DAY1_ACT = '201400001-m003-1'
DAY1_KAIFU = 1400000000000
DAY1_NOW = DAY1_KAIFU + 43200000
DAY1_GRANTED = [['zj0401', 1], ['expfold_003', 1],
                ['jinjiedan002', 1], ['zhenqipill_003', 5],
                ['tongqian003', 3], ['10yb', 1]]
# Exact 70000 display array for the live row, uncharged (state 0): the
# 13-slot firstrecharge layout with the 6 config items (unfiltered)
# and zero currencies, per RoleHuodongOutputWrapper bytecode.
LIVE_INFO_UNCHARGED = [
    LIVE_ACT, '天天首充', 0, ['', ''],
    1393603201000, 1393689599000, 0, 0,
    [0, 0, 0, 0, 0, [
        ['qibinglixiang1', 1, 1, 24.0, [0, 0], 0, ''],
        ['qibing001', 2, 1, 0.0, [0, 0], 0, ''],
        ['expfold_002', 1, 1, 0.0, [0, 0], 0, ''],
        ['xunbaotu01', 2, 1, 0.0, [0, 0], 0, ''],
        ['xunbaotu02', 2, 1, 0.0, [0, 0], 0, ''],
        ['tongqian003', 1, 1, 0.0, [0, 0], 0, ''],
    ]],
    'huodong_bg11.png', '', '', 'wanshengjieshouchong.png',
]
# Exact 70000 item half for the day-1 row: job equips carry
# strengthenlv '10|10' -> [10, 10] and rare 3; 10yb rides 48h.
DAY1_ITEMS = [
    ['zj0401', 1, 1, 0.0, [10, 10], 3, ''],
    ['zj0403', 1, 1, 0.0, [10, 10], 3, ''],
    ['zj0405', 1, 1, 0.0, [10, 10], 3, ''],
    ['zj0407', 1, 1, 0.0, [10, 10], 3, ''],
    ['expfold_003', 1, 1, 0.0, [0, 0], 0, ''],
    ['jinjiedan002', 1, 1, 0.0, [0, 0], 0, ''],
    ['zhenqipill_003', 5, 1, 0.0, [0, 0], 0, ''],
    ['tongqian003', 3, 1, 0.0, [0, 0], 0, ''],
    ['10yb', 1, 1, 48.0, [0, 0], 0, ''],
]
PROD_KAIFU = 1394466091000

# Genuine fu0 census (docs/zonghe-finding.md section 5): categories and
# activities per clienttype, including the 5 ct=36 rows Java drops.
CATEGORIES_PER_CT = {1: 16, 5: 3, 9: 16, 10: 6, 21: 16, 22: 5, 30: 6,
                     31: 3, 32: 1, 34: 6, 36: 1}
ACTIVITIES_PER_CT = {1: 122, 5: 31, 9: 245, 10: 34, 21: 16, 22: 25,
                     30: 34, 31: 21, 32: 5, 34: 36, 36: 5}


def frames(out):
    return [decode(bytes(f)[4:]) for f in out]


class _SynthTable:
    """Wrap a GameConfig appending one synthetic zonghe category."""
    def __init__(self, real, clienttype, cat):
        self._real = real
        self._ct = clienttype
        self._cat = cat

    def __getattr__(self, name):
        return getattr(self._real, name)

    def zonghe(self, server_id='fu0', kaifu_ms=0):
        table = copy.deepcopy(self._real.zonghe(
            server_id=server_id, kaifu_ms=kaifu_ms))
        table.setdefault(self._ct, {'categories': [],
                                   'by_activity': {}})
        table[self._ct]['categories'].append(copy.deepcopy(self._cat))
        return table


@unittest.skipUnless(HAVE_REAL and HAVE_SNAPSHOT,
                     'legacy config tree or zonghe snapshot missing')
class ZongheLoaderTest(unittest.TestCase):
    def setUp(self):
        self.cfg = GameConfig(str(REAL_CONFIG))

    def table(self, kaifu_ms=0):
        return self.cfg.zonghe(server_id='fu0', kaifu_ms=kaifu_ms)

    # -- snapshot shape ------------------------------------------------
    def test_category_and_activity_counts(self):
        table = self.table()
        self.assertEqual(
            {ct: len(b['categories']) for ct, b in table.items()},
            {ct: n for ct, n in CATEGORIES_PER_CT.items() if ct != 36})
        self.assertEqual(
            {ct: sum(len(c['activities']) for c in b['categories'])
             for ct, b in table.items()},
            {ct: n for ct, n in ACTIVITIES_PER_CT.items() if ct != 36})

    def test_unknown_clienttype_dropped(self):
        table = self.table()
        self.assertNotIn(36, table)
        total = sum(len(c['activities'])
                    for b in table.values() for c in b['categories'])
        self.assertEqual(total, 569)

    def test_reload_is_deterministic(self):
        again = GameConfig(str(REAL_CONFIG))
        self.assertEqual(self.table(), again.zonghe())

    def test_missing_snapshot_is_empty(self):
        self.assertEqual(self.cfg.zonghe(server_id='no-such-server'), {})

    def test_activity_fields_preserve_types(self):
        bucket = self.table()[21]
        _cat, act = bucket['by_activity'][LIVE_ACT]
        self.assertEqual(act['con1'], '')
        self.assertIsInstance(act['con1'], str)
        self.assertEqual(act['functiontype'], 100)
        self.assertEqual(
            [list(p[:2]) for p in act['parcels']],
            [list(p) for p in LIVE_PAIRS])

    # -- timing ----------------------------------------------------------
    def test_explicit_window_passthrough(self):
        bucket = self.table()[21]
        cats = {c['id']: c for c in bucket['categories']}
        self.assertEqual(
            (cats[LIVE_CAT]['start_ms'], cats[LIVE_CAT]['end_ms']),
            (1393603201000, 1393689599000))

    def test_kaifu_relative_window(self):
        kaifu = 1394400000000
        cats = {c['id']: c
                for c in self.table(kaifu_ms=kaifu)[21]['categories']}
        cat = cats['201400001-21-1']
        self.assertEqual((cat['start_ms'], cat['end_ms']),
                         (kaifu, kaifu + 86400000))

    def test_no_kaifu_source_never_live(self):
        live = self.cfg.zonghe_live(21, kaifu_ms=0,
                                    now_ms=1393603201000 + 1000)
        ids = [c['id'] for c, _a in live]
        self.assertNotIn('201400001-21-1', ids)

    def test_expiry_edges(self):
        live = GameConfig._zonghe_live_ms
        self.assertTrue(live(10, 20, 10))
        self.assertTrue(live(10, 20, 20))
        self.assertFalse(live(10, 20, 21))
        self.assertFalse(live(20, 10, 15))

    def test_real_today_nothing_live(self):
        import time
        live = self.cfg.zonghe_live(
            21, kaifu_ms=PROD_KAIFU, now_ms=int(time.time() * 1000))
        self.assertEqual(live, [])


@unittest.skipUnless(HAVE_REAL and HAVE_SNAPSHOT,
                     'legacy config tree or zonghe snapshot missing')
class ZongheFirstRechargeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'z.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.rid = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56)
        self.store.save_role_bag_state(self.rid, bag_capacity=144,
                                       storage_capacity=144)
        self.sess = self.make_sess(PROD_KAIFU)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.role = dict(self.store.list_roles('hero', 'fu1304')[0])

    def make_sess(self, kaifu_ms):
        return Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=kaifu_ms,
            save_role_state=self.store.update_character_state,
            get_role_huodong=self.store.get_role_huodong,
            save_role_huodong=self.store.save_role_huodong,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            get_role_zuoqi=self.store.get_role_zuoqi,
            save_role_zuoqi=self.store.save_role_zuoqi,
            config=self.cfg)

    # -- helpers ---------------------------------------------------------
    def state(self):
        raw = (self.store.get_role_huodong(self.rid) or {}).get('max_count')
        return (json.loads(raw or '{}') or {}).get('zonghe_first')

    def bag(self):
        slots = self.store.get_role_bag_slots(self.rid, 1, 150)
        have = {}
        for s in slots:
            have[s['goods_id']] = have.get(s['goods_id'], 0) + s['count']
        return have

    # -- recharge hook ----------------------------------------------------
    def test_nonpositive_recharge_silent(self):
        self.assertEqual(self.sess.zonghe_recharge(self.role, 0), [])
        self.assertIsNone(self.state())

    def test_recharge_latches_and_pushes(self):
        out = self.sess.zonghe_recharge(
            self.role, 1000, now_ms=LIVE_NOW)
        self.assertEqual(frames(out), [['71002', [LIVE_ACT, 1000, 1]]])
        self.assertEqual(self.state(), {'charged': 1, 'claimed': []})

    def test_recharge_outside_window_latches_without_push(self):
        out = self.sess.zonghe_recharge(
            self.role, 1000, now_ms=1390000000000)
        self.assertEqual(out, [])
        self.assertEqual(self.state(), {'charged': 1, 'claimed': []})

    # -- 70000 info (HuodongAction.getRechargeInfo) -----------------------
    def info(self, now_ms):
        out = self.sess.huodong_first_info(None, now_ms=now_ms)
        return decode(bytes(out)[4:])

    def test_info_no_live_is_null(self):
        self.assertEqual(self.info(1390000000000), ['70000', None])

    def test_info_uncharged_state_zero(self):
        self.assertEqual(self.info(LIVE_NOW),
                         ['70000', LIVE_INFO_UNCHARGED])

    def test_info_level_gate(self):
        body = self.sess._zonghe_first_info(dict(self.role, level=0),
                                             now_ms=LIVE_NOW)
        self.assertEqual(body, [0, 792005])

    def test_info_charged_then_claimed(self):
        self.sess.zonghe_recharge(self.role, 1000, now_ms=LIVE_NOW)
        body = self.sess._zonghe_first_info(self.role, now_ms=LIVE_NOW)
        self.assertEqual((body[2], body[7]), (1, 0))
        self.sess.huodong_first_reward(None, now_ms=LIVE_NOW)
        body = self.sess._zonghe_first_info(self.role, now_ms=LIVE_NOW)
        self.assertEqual((body[2], body[7]), (2, 1))

    # -- 70001 reward (HuodongAction.lingquRechargeReward) ----------------
    def reward(self, now_ms):
        out = self.sess.huodong_first_reward(None, now_ms=now_ms)
        if isinstance(out, list):
            return frames(out)
        return [decode(bytes(out)[4:])]

    def test_reward_no_live(self):
        self.assertEqual(self.reward(1390000000000),
                         [['70001', [0, 792005]]])

    def test_reward_uncharged(self):
        self.assertEqual(self.reward(LIVE_NOW),
                         [['70001', [0, 792001]]])

    def test_reward_success_pushes_mount_then_reply(self):
        self.sess.zonghe_recharge(self.role, 1000, now_ms=LIVE_NOW)
        self.assertEqual(
            self.reward(LIVE_NOW),
            [['33004', [1, 3, 30]], ['70001', [1, LIVE_ACT]]])
        self.assertEqual(self.state(),
                         {'charged': 1, 'claimed': [LIVE_ACT]})
        self.assertEqual(
            self.bag(),
            {gid: count for gid, count in LIVE_GRANTED})

    def test_reward_duplicate(self):
        self.sess.zonghe_recharge(self.role, 1000, now_ms=LIVE_NOW)
        self.sess.huodong_first_reward(None, now_ms=LIVE_NOW)
        self.assertEqual(self.reward(LIVE_NOW),
                         [['70001', [0, 792002]]])

    def test_reward_bag_full(self):
        self.store.save_role_bag_state(self.rid, bag_capacity=0,
                                       storage_capacity=0)
        self.sess.zonghe_recharge(self.role, 1000, now_ms=LIVE_NOW)
        self.assertEqual(self.reward(LIVE_NOW),
                         [['70001', [0, 430212]]])
        self.assertEqual(self.state(), {'charged': 1, 'claimed': []})

    def test_reward_after_window(self):
        self.sess.zonghe_recharge(self.role, 1000, now_ms=LIVE_NOW)
        self.assertEqual(self.reward(1393689599000 + 1),
                         [['70001', [0, 792005]]])
        self.assertEqual(self.state(), {'charged': 1, 'claimed': []})

    # -- 70500 panel (HuodongAction.getHuodongInfo) -----------------------
    def panel(self, now_ms):
        out = self.sess.huodong_panel_info(None, now_ms=now_ms)
        return decode(bytes(out)[4:])

    def test_panel_empty_when_nothing_live(self):
        self.assertEqual(self.panel(1394000000000), ['70500', []])

    def test_panel_exact_rows_at_prod_plus_one_hour(self):
        now = PROD_KAIFU + 3600000
        self.assertEqual(self.panel(now), ['70500', [
            ['新服特惠', 'kaifu1.png,kaifu2.png', 'kaifu3.png'],
            [1, '1', '充值送大礼', '', 2, ''],
            [10, '3', '坐骑狂进阶', '', 3, ''],
            [5, '5', '新服折扣店', '', 5, ''],
            [9, '4', '免费大兑换', '', 4, ''],
        ]])

    def test_panel_skips_first_recharge_and_ended_rows(self):
        # LIVE_NOW has a live ct-21 row plus liveMall/rank rows; the
        # panel carries no ct-21 row and no row past its end instant
        # (end is exclusive: start <= now < end).
        rows = self.panel(LIVE_NOW)[1]
        self.assertGreater(len(rows), 1)
        self.assertEqual(rows[0],
                         ['骑兵特惠', 'qibing1.png,qibing2.png',
                          'qibinghuodong1.png'])
        self.assertFalse([r for r in rows[1:] if r[0] == 21])
        for r in rows[1:]:
            self.assertEqual(len(r), 6)

    def test_zonghe_wire_dispatch_routes_all_four(self):
        # Wall-clock dispatch through the encrypted wire: no 2014 row
        # is live in 2026, so each command gets its jar-verbatim empty
        # reply, proving the dispatcher routes all four handlers.
        self.sess.feed(bytes.fromhex('00000009060f494e49544b4559'))
        for cmd, want in ((70500, []), (70501, [2]), (70506, [2]),
                          (70507, [2])):
            req = self.sess.cipher.encode(encode([cmd, None]))
            out = self.sess.feed(struct.pack('>I', len(req)) + req)
            self.assertEqual([decode(bytes(f)[4:]) for f in out],
                             [[str(cmd), want]])

    # -- 70501 accumulate (HuodongAction.getAccumulateRecharge) ----------
    def acc(self, now_ms):
        out = self.sess.huodong_accumulate_recharge(None, now_ms=now_ms)
        return decode(bytes(out)[4:])

    def test_accumulate_no_config_is_792005(self):
        cfg, self.sess.config = self.sess.config, None
        try:
            body = self.sess._zonghe_accumulate(self.role, now_ms=LIVE_NOW)
        finally:
            self.sess.config = cfg
        self.assertEqual(body, [0, 792005])

    def test_accumulate_no_live_window_is_bare_two(self):
        self.assertEqual(self.acc(1394000000000), ['70501', [2]])

    def test_accumulate_exact_golden_at_prod_plus_one_hour(self):
        now = PROD_KAIFU + 3600000
        body = self.acc(now)
        self.assertEqual(body[0], '70501')
        outer, rows = body[1][:6], body[1][6]
        self.assertEqual(
            outer,
            [1, 1, PROD_KAIFU, PROD_KAIFU + 86400000, 0, ''])
        # [id, isAccumulate, con, maxVal, maxLimit, dayVal, dayLimit,
        # state, order, nItems]: ft-11 rows read state 1 with no total
        # gate (jar verbatim), the single ft-10 row gates on the total
        # and reads 0 for a fresh role.
        self.assertEqual(
            [[r[0], r[1], r[2], r[4], r[5], r[6], r[7], r[8], r[9],
              len(r[3][0][2])] for r in rows],
            [['201400001-zuixinleiji101-2', 1, 200, 0, 1, 0, 1, 1, 1, 5],
             ['201400001-zuixinleiji102-2', 1, 500, 0, 1, 0, 1, 1, 2, 4],
             ['201400001-zuixinleiji103-2', 1, 1000, 0, 1, 0, 1, 1, 3, 4],
             ['201400001-zuixinleiji104-2', 0, 2000, 0, 30, 0, 30, 0, 4, 5],
             ['201400001-zuixinleiji105-2', 1, 5000, 0, 1, 0, 1, 1, 5, 5],
             ['201400001-zuixinleiji106-2', 1, 10000, 0, 1, 0, 1, 1, 6, 6]])
        self.assertEqual(
            [r[3][0][1] for r in rows],
            ['超值套餐', '实惠套餐', '优惠套餐',
             '随心套餐', '贵宾套餐', '至尊套餐'])
        # Full first row: the single 5-array (no chooseAwards or zubao
        # in fu0) with 10-slot itemParamVo2Client items.
        self.assertEqual(rows[0][3], [[None, '超值套餐', [
            ['chip_nvwa', 2, 1, 0.0, [0, 0], 0, None, None, 1, None],
            ['jinjiedan001', 2, 1, 0.0, [0, 0], 0, None, None, 0, None],
            ['zhenqipill_003', 1, 1, 0.0, [0, 0], 0, None, None, 0, None],
            ['tongqian003', 1, 1, 0.0, [0, 0], 0, None, None, 0, None],
            ['expfold_002', 1, 1, 0.0, [0, 0], 0, None, None, 0, None],
        ], None, '']])
        # Full PER row: isAccumulate 0, state 0, wider day/max limits.
        self.assertEqual(rows[3][3], [[None, '随心套餐', [
            ['jinjiedan006', 3, 1, 0.0, [0, 0], 0, None, None, 1, None],
            ['duihuan2', 1, 1, 0.0, [0, 0], 0, None, None, 1, None],
            ['tongqian003', 2, 1, 0.0, [0, 0], 0, None, None, 0, None],
            ['zhenqipill_003', 2, 1, 0.0, [0, 0], 0, None, None, 0, None],
            ['jinjiedan002', 1, 1, 0.0, [0, 0], 0, None, None, 0, None],
        ], None, '']])
        # A 48h item keeps its hours (ceil path with nonzero lasttime).
        timed = [it for r in rows for it in r[3][0][2]
                 if it[0] == 'zuoqiyouhui']
        self.assertEqual(len(timed), 1)
        self.assertEqual(timed[0][3], 48.0)

    def test_accumulate_level_zero_sees_no_rows(self):
        body = self.sess._zonghe_accumulate(
            dict(self.role, level=0), now_ms=PROD_KAIFU + 3600000)
        self.assertEqual(body[:6],
                         [1, 1, PROD_KAIFU, PROD_KAIFU + 86400000, 0, ''])
        self.assertEqual(body[6], [])

    # -- 70506 mall (HuodongAction.getLimitedMall) ------------------------
    def mall(self, now_ms):
        out = self.sess.huodong_limited_mall(None, now_ms=now_ms)
        return decode(bytes(out)[4:])

    def rich_role(self, lingshi=100000):
        self.store.update_character_state(self.rid, lingshi=lingshi)
        return dict(self.store.list_roles('hero', 'fu1304')[0])

    def test_mall_no_config_is_792005(self):
        cfg, self.sess.config = self.sess.config, None
        try:
            body = self.sess._zonghe_mall(self.role, now_ms=LIVE_NOW)
        finally:
            self.sess.config = cfg
        self.assertEqual(body, [0, 792005])

    def test_mall_no_live_window_is_bare_two(self):
        self.assertEqual(self.mall(1394000000000), ['70506', [2]])

    def test_mall_exact_golden_at_prod_plus_one_hour(self):
        now = PROD_KAIFU + 3600000
        role = self.rich_role()
        body = self.mall(now)
        self.assertEqual(body[0], '70506')
        outer, rows = body[1][:5], body[1][5]
        self.assertEqual(outer, [1, 5, PROD_KAIFU, PROD_KAIFU + 86400000,
                                 ''])
        # [actId, itemId, tags, opayYb, npayYb, buyRemain, sellRemain,
        # dayVal, dayLimit, state, order, itemName]; a rich role reads
        # state 1 on every row (stock + limit + purse all allow it).
        self.assertEqual(
            [[r[0], r[1][0], r[2], r[3], r[4], r[6], r[7], r[8], r[9],
              r[10], r[11], r[13]] for r in rows],
            [['201400001-50zizhuang-2', '50zizhuang', ['5'], 1500, 800,
              1, 9999, 0, 1, 1, 5, '【牛魔】50级+10紫武箱'],
             ['201400001-50zizhuang2-2', '50zizhuang2', ['5'], 1500, 800,
              1, 9999, 0, 1, 1, 18, '【灵猴】50级+10紫武箱'],
             ['201400001-50zizhuang3-2', '50zizhuang3', ['5'], 1500, 800,
              1, 9999, 0, 1, 1, 19, '【罗刹】50级+10紫武箱'],
             ['201400001-50zizhuang4-2', '50zizhuang4', ['5'], 1500, 800,
              1, 9999, 0, 1, 1, 20, '【九尾】50级+10紫武箱'],
             ['201400001-50zizhuang5-2', '50zizhuang5', ['5'], 4500, 2400,
              1, 9999, 0, 1, 1, 21, '【通用】50级+10紫装箱'],
             ['201400001-xxsd001-2', 'shenmu', ['5'], 50, 20,
              9999, 9999, 0, 9999, 1, 1, '神木鼎'],
             ['201400001-xxsd002-2', 'dashi', ['5'], 1000, 300,
              1, 200, 0, 1, 1, 2, '大师冲级包'],
             ['201400001-xxsd003-2', 'gonghui', ['5'], 2000, 500,
              1, 200, 0, 1, 1, 3, '公会升级包'],
             ['201400001-zjth001-2', 'zuoqihuodong1', ['5'], 300, 270,
              9999, 9999, 0, 9999, 1, 22, '坐骑特惠小型礼包'],
             ['201400001-zjth002-2', 'zuoqihuodong2', ['5'], 600, 540,
              9999, 9999, 0, 9999, 1, 23, '坐骑特惠中型礼包'],
             ['201400001-zjth003-2', 'zuoqihuodong3', ['5'], 1500, 1350,
              9999, 9999, 0, 9999, 1, 24, '坐骑特惠大型礼包'],
             ['201400001-zjth004-2', 'zuoqihuodong4', ['5'], 3000, 2700,
              150, 150, 0, 150, 1, 25, '坐骑特惠豪华礼包']])
        # Full first row: 14 slots; the good rides count 1 with the
        # unclamped lasttime (-1.0, jar-exact on this path), no gifts
        # or zubao in fu0, desc ''.
        self.assertEqual(rows[0], [
            '201400001-50zizhuang-2',
            ['50zizhuang', 1, 0, -1.0, [0, 0], 0, None, None, 0, None],
            ['5'], 1500, 800, [], 1, 9999, 0, 1, 1, 5, '',
            '【牛魔】50级+10紫武箱'])

    def test_mall_broke_role_reads_state_zero(self):
        now = PROD_KAIFU + 3600000
        body = decode(bytes(self.sess.huodong_limited_mall(
            None, now_ms=now))[4:])
        rows = body[1][5]
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(r[10] == 0 for r in rows))

    def test_mall_level_zero_sees_no_rows(self):
        body = self.sess._zonghe_mall(
            dict(self.role, level=0), now_ms=PROD_KAIFU + 3600000)
        self.assertEqual(body[:5],
                         [1, 5, PROD_KAIFU, PROD_KAIFU + 86400000, ''])
        self.assertEqual(body[5], [])

    # -- 70507 exchange (HuodongAction.getLimitedExchange) -------------
    def exch(self, now_ms):
        out = self.sess.huodong_limited_exchange(None, now_ms=now_ms)
        return decode(bytes(out)[4:])

    def test_exchange_no_config_is_792005(self):
        cfg, self.sess.config = self.sess.config, None
        try:
            body = self.sess._zonghe_exchange(self.role,
                                              now_ms=LIVE_NOW)
        finally:
            self.sess.config = cfg
        self.assertEqual(body, [0, 792005])

    def test_exchange_no_live_window_is_bare_two(self):
        self.assertEqual(self.exch(1394000000000), ['70507', [2]])

    def test_exchange_exact_golden_at_prod_plus_one_hour(self):
        now = PROD_KAIFU + 3600000
        self.rich_role()
        table = self.cfg.zonghe(server_id='fu0', kaifu_ms=PROD_KAIFU)
        cat = [c for c in table[9]['categories']
               if c['id'] == '201400001-9-2'][0]
        need = {}
        for a in cat['activities']:
            for part in str(a['con1']).split(','):
                cells = part.split('|')
                key = (cells[0], int(cells[2]) if len(cells) > 2
                       else 0)
                need[key] = need.get(key, 0) + int(cells[1])
        for i, ((gid, bind), count) in enumerate(sorted(need.items())):
            self.store.insert_role_bag_slot(
                self.rid, {'slot_num': i + 1, 'goods_id': gid,
                           'count': count, 'bind': bind})
        body = self.exch(now)
        self.assertEqual(body[0], '70507')
        outer, rows = body[1][:5], body[1][5]
        self.assertEqual(outer, [1, 9, PROD_KAIFU, PROD_KAIFU + 86400000,
                                 ''])
        # [actId, costs, maxVal, maxLimit, dayVal, dayLimit, state,
        # order, nAwards]; a stocked rich role reads state 1 on all
        # 12 rows (purse + exact-bind bag cover every cost).
        self.assertEqual(
            [[r[0], r[1], r[3], r[4], r[5], r[6], r[7], r[9],
              len(r[2])] for r in rows],
            [['201400001-1chongzhiduihuan6-2', [['qixing1', 480, 1]],
              0, 200, 0, 200, 1, 13, 1],
             ['201400001-duihuan1101-2', [['duihuan2', 15, 1]],
              0, 1, 0, 1, 1, 1, 2],
             ['201400001-duihuan1102-2', [['duihuan2', 35, 1]],
              0, 1, 0, 1, 1, 2, 2],
             ['201400001-duihuantaozhuang-2',
              [['duihuantaozhuang', 5, 1]], 0, 1, 0, 1, 1, 3, 1],
             ['201400001-xxdh001-2',
              [['dntg001', 10, 1], ['dntg002', 10, 1]],
              0, 6, 0, 6, 1, 5, 2],
             ['201400001-xxdh002-2',
              [['dntg003', 10, 1], ['dntg004', 10, 1]],
              0, 6, 0, 6, 1, 6, 2],
             ['201400001-xxdh003-2',
              [['duihuan1', 1, 0], ['jinjiedan002', 1, 0]],
              0, 2, 0, 2, 1, 7, 2],
             ['201400001-xxdh004-2',
              [['duihuan1', 1, 0], ['sm_001', 1, 0]],
              0, 2, 0, 2, 1, 8, 2],
             ['201400001-xxdh005-2',
              [['duihuan1', 1, 0], ['sb_001', 1, 0]],
              0, 2, 0, 2, 1, 9, 2],
             ['201400001-xxdh006-2',
              [['duihuan1', 1, 0], ['gj_001', 1, 0]],
              0, 2, 0, 2, 1, 10, 2],
             ['201400001-xxdh007-2',
              [['duihuan1', 1, 0], ['fy_001', 1, 0]],
              0, 2, 0, 2, 1, 11, 2],
             ['201400001-xxdh008-2',
              [['duihuan1', 5, 0], ['chip_zixia', 1, 0]],
              0, 1, 0, 1, 1, 12, 2]])
        # Full first row: the single cost triple plus the
        # itemParamVo2Client award projection (unsale rides).
        self.assertEqual(rows[0], [
            '201400001-1chongzhiduihuan6-2', [['qixing1', 480, 1]],
            [['72shengming7', 1, 1, 0.0, [0, 0], 0, None, None, 1,
              None]],
            0, 200, 0, 200, 1, None, 13])
        # Multi-cost row pins the two-part default-bind-0 parse.
        self.assertEqual(rows[6][1],
                         [['duihuan1', 1, 0], ['jinjiedan002', 1, 0]])
        self.assertEqual(rows[1][2], [
            ['kangxing2', 1, 1, 0.0, [0, 0], 0, None, None, 2, None],
            ['duihuan2', 15, 1, 0.0, [0, 0], 0, None, None, 0, None]])

    def test_exchange_broke_role_reads_state_zero(self):
        now = PROD_KAIFU + 3600000
        body = decode(bytes(self.sess.huodong_limited_exchange(
            None, now_ms=now))[4:])
        rows = body[1][5]
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(r[7] == 0 for r in rows))

    def test_exchange_level_zero_sees_no_rows(self):
        body = self.sess._zonghe_exchange(
            dict(self.role, level=0), now_ms=PROD_KAIFU + 3600000)
        self.assertEqual(body[:5],
                         [1, 9, PROD_KAIFU, PROD_KAIFU + 86400000, ''])
        self.assertEqual(body[5], [])

    # -- kaifu-relative day-1 row: job filter ----------------------------
    def test_day1_claim_grants_job_filtered_items(self):
        sess = self.make_sess(DAY1_KAIFU)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        out = sess.zonghe_recharge(self.role, 100, now_ms=DAY1_NOW)
        self.assertEqual(frames(out), [['71002', [DAY1_ACT, 100, 1]]])
        body = decode(bytes(
            sess.huodong_first_info(None, now_ms=DAY1_NOW))[4:])
        self.assertEqual(body[0], '70000')
        info = body[1]
        self.assertEqual(info[0], DAY1_ACT)
        self.assertEqual(info[1], '首次充值')
        self.assertEqual(info[2], 1)
        self.assertEqual(info[4:6],
                         [DAY1_KAIFU, DAY1_KAIFU + 86400000])
        self.assertEqual(info[8][:5], [0, 0, 0, 0, 0])
        self.assertEqual(info[8][5], DAY1_ITEMS)
        self.assertEqual(info[12], 'shouchong002.png')
        got = frames(sess.huodong_first_reward(None, now_ms=DAY1_NOW))
        self.assertEqual(got[1], ['70001', [1, DAY1_ACT]])
        self.assertEqual(
            self.bag(),
            {gid: count for gid, count in DAY1_GRANTED})


@unittest.skipUnless(HAVE_REAL and HAVE_SNAPSHOT,
                     'legacy config tree or zonghe snapshot missing')
class ZongheTransactionTest(unittest.TestCase):
    """70550/70551 write lifecycle: debit, grant, persisted counters.

    Evidence: HuodongAction.buyHuodongMallGoods/getHuodongReward and
    HuodongServiceImpl buyDiscountMallGoods/getGoodsExchangeReward
    (+ the check*/huodongReward/counter helpers) in /tmp/hd705_svc.txt
    and /tmp/hd705_action.txt. fu0 supplies the normal cases (the
    201400001-9-2 exchange and 201400001-5-2 mall categories live at
    PROD_KAIFU+1h; the 201402252-9-3 category covers real
    yuanbao/money costs); currency grants ride a labeled synthetic
    ct-9 row since every fu0 award carries zero currencies.
    """
    EX_ID = '201400001-duihuan1101-2'
    EX_NOW = PROD_KAIFU + 3600000
    OLD_CAT = '201402252-9-3'
    OLD_NOW = 1393257601000 + 3600000
    MALL_ACT = '201400001-xxsd001-2'
    MALL_GOOD = 'shenmu'
    ONE_ACT = '201400001-50zizhuang-2'
    ONE_GOOD = '50zizhuang'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, 't.db')
        self.store = Store(self.db_path)
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.rid = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56)
        self.store.save_role_bag_state(self.rid, bag_capacity=144,
                                       storage_capacity=144)
        self.sess = self.make_sess(PROD_KAIFU)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.role = dict(self.store.list_roles('hero', 'fu1304')[0])

    def make_sess(self, kaifu_ms, config=None, charge=None,
                  lifetime=None, qibing=None):
        extra = {}
        if charge is not None:
            extra['charge_total_in_time'] = lambda r, s, e: charge
        if lifetime is not None:
            extra['charge_total'] = lambda r: lifetime
        if qibing is not None:
            extra['qibing_level'] = lambda r: qibing
        return Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=kaifu_ms,
            get_role_zuoqi=self.store.get_role_zuoqi,
            save_role_zuoqi=self.store.save_role_zuoqi,
            get_role_baoshi=self.store.get_role_baoshi,
            save_role_baoshi=self.store.save_role_baoshi,
            get_role_guangyi=self.store.get_role_guangyi,
            save_role_guangyi=self.store.save_role_guangyi,
            get_role_vip=self.store.get_role_vip,
            save_role_vip=self.store.save_role_vip,
            **extra,
            save_role_state=self.store.update_character_state,
            get_role_huodong=self.store.get_role_huodong,
            save_role_huodong=self.store.save_role_huodong,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            get_huodong_info=self.store.get_huodong_info,
            huodong_exchange_tx=self.store.huodong_exchange_tx,
            huodong_mall_buy_tx=self.store.huodong_mall_buy_tx,
            config=config if config is not None else self.cfg)

    # -- helpers ---------------------------------------------------------
    def claim(self, data, now_ms):
        out = self.sess.huodong_exchange_claim([70551, data],
                                               now_ms=now_ms)
        return decode(bytes(out)[4:]) if out is not None else None

    def buy(self, data, now_ms):
        out = self.sess.huodong_mall_buy([70550, data], now_ms=now_ms)
        if out is None:
            return None
        if isinstance(out, list):
            return [decode(bytes(f)[4:]) for f in out]
        return decode(bytes(out)[4:])

    def bag(self):
        have = {}
        for s in self.store.get_role_bag_slots(self.rid, 1, 150):
            have[s['goods_id']] = have.get(s['goods_id'], 0) + s['count']
        return have

    def claim_all(self, data, now_ms):
        out = self.sess.huodong_exchange_claim([70551, data],
                                               now_ms=now_ms)
        if out is None:
            return None
        if isinstance(out, list):
            return [decode(bytes(f)[4:]) for f in out]
        return decode(bytes(out)[4:])

    def counters(self):
        row = self.store.get_role_huodong(self.rid) or {}
        return {k: json.loads(row.get(k) or '{}')
                for k in ('day_count', 'max_count', 'mall_buy_count')}

    def rich(self, lingshi=100000, tongqian=0):
        self.store.update_character_state(
            self.rid, lingshi=lingshi, tongqian=tongqian)

    def stock(self, *pairs):
        for i, (gid, count, bind) in enumerate(pairs):
            self.store.insert_role_bag_slot(
                self.rid, {'slot_num': i + 1, 'goods_id': gid,
                           'count': count, 'bind': bind})

    # -- 70551 exchange claim --------------------------------------------
    def test_exchange_success_persists(self):
        self.rich()
        self.stock(('duihuan2', 15, 1))
        body = self.claim([9, self.EX_ID, ''], self.EX_NOW)
        # Limits are 1/1, so the post-claim display reads state 2.
        self.assertEqual(body, ['70551', [1, self.EX_ID, None, 2, 1, 1,
                                          1, 1]])
        # Debit plus grant net out: one kangxing2, duihuan2 restored.
        self.assertEqual(self.bag(), {'duihuan2': 15, 'kangxing2': 1})
        self.assertEqual(
            self.counters()['day_count'], {self.EX_ID: 1})
        self.assertEqual(
            self.counters()['max_count'], {self.EX_ID: 1})
        # Restart: a fresh store on the same file keeps the counters,
        # so the repeat claim is a duplicate, not a second grant.
        self.store.close()
        self.store = Store(self.db_path)
        self.addCleanup(self.store.close)
        self.sess = self.make_sess(PROD_KAIFU)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        again = self.claim([9, self.EX_ID, ''], self.EX_NOW)
        self.assertEqual(again, ['70551', [0, 792006]])
        self.assertEqual(self.bag(), {'duihuan2': 15, 'kangxing2': 1})

    def test_exchange_short_bag_is_792001_without_side_effects(self):
        self.rich()
        body = self.claim([9, self.EX_ID, ''], self.EX_NOW)
        self.assertEqual(body, ['70551', [0, 792001]])
        self.assertEqual(self.bag(), {})
        row = self.store.get_role_huodong(self.rid) or {}
        self.assertEqual(json.loads(row.get('day_count') or '{}'), {})
        self.assertEqual(
            dict(self.store.list_roles('hero', 'fu1304')[0])['lingshi'],
            100000)

    def test_exchange_yuanbao_cost_debits_and_state_one(self):
        act = '201402252-9chongzhiduihuan4-3'
        self.rich()
        self.stock(('expfold_002', 2, 1))
        body = self.claim([9, act, ''], self.OLD_NOW)
        # Post-debit the purse and bag still cover the cost and the
        # 10/10 limits stay open, so the jar reads state 1.
        self.assertEqual(body, ['70551', [1, act, None, 1, 1, 10, 1,
                                          10]])
        role = dict(self.store.list_roles('hero', 'fu1304')[0])
        self.assertEqual(role['lingshi'], 100000 - 20)
        self.assertEqual(self.bag(), {'expfold_002': 1,
                                       'expfold_003': 1})

    def test_exchange_money_cost_debits_tongqian(self):
        act = '201402252-9chongzhiduihuan10-3'
        self.rich(tongqian=9000000)
        body = self.claim([9, act, ''], self.OLD_NOW)
        self.assertEqual(body, ['70551', [1, act, None, 2, 1, 1, 1, 1]])
        role = dict(self.store.list_roles('hero', 'fu1304')[0])
        self.assertEqual(role['tongqian'], 9000000 - 5000000)
        self.assertEqual(self.bag(), {'silver100': 2})

    def test_exchange_money_short_is_792001(self):
        act = '201402252-9chongzhiduihuan10-3'
        self.rich(tongqian=4999999)
        body = self.claim([9, act, ''], self.OLD_NOW)
        self.assertEqual(body, ['70551', [0, 792001]])
        role = dict(self.store.list_roles('hero', 'fu1304')[0])
        self.assertEqual(role['tongqian'], 4999999)

    def test_exchange_day_and_max_floors(self):
        self.rich()
        self.stock(('duihuan2', 99, 1))
        self.store.save_role_huodong(
            self.rid, day_count=json.dumps({self.EX_ID: 1}))
        self.assertEqual(self.claim([9, self.EX_ID, ''], self.EX_NOW),
                         ['70551', [0, 792006]])
        self.store.save_role_huodong(self.rid, day_count=json.dumps({}),
                                     max_count=json.dumps({self.EX_ID: 1}))
        self.assertEqual(self.claim([9, self.EX_ID, ''], self.EX_NOW),
                         ['70551', [0, 792007]])
        self.assertEqual(self.bag(), {'duihuan2': 99})

    def test_exchange_expired_category_is_792003(self):
        self.assertEqual(self.claim([9, self.EX_ID, ''], 1390000000000),
                         ['70551', [0, 792003]])

    def test_exchange_bag_full_is_430212(self):
        self.rich()
        self.stock(('duihuan2', 15, 1))
        self.store.save_role_bag_state(self.rid, bag_capacity=1,
                                       storage_capacity=144)
        body = self.claim([9, self.EX_ID, ''], self.EX_NOW)
        self.assertEqual(body, ['70551', [0, 430212]])
        self.assertEqual(self.bag(), {'duihuan2': 15})
        row = self.store.get_role_huodong(self.rid) or {}
        self.assertEqual(json.loads(row.get('day_count') or '{}'), {})

    def test_exchange_unknown_activity_is_silent(self):
        self.assertIsNone(self.claim([9, 'no-such-act', ''],
                                     self.EX_NOW))

    def test_exchange_wrong_clienttype_is_silent(self):
        self.assertIsNone(self.claim([5, self.EX_ID, ''],
                                     self.EX_NOW))

    def test_exchange_currency_grants_and_level_frames(self):
        # Synthetic ct-9 row: no fu0 award carries currencies, so the
        # jb/lijin/zhenqi/exp grant arms ride a labeled fixture with
        # the shipped schema (con1 costs, item_views, currencies).
        need = int(self.cfg.role_need_exp(56))
        fixture = {
            'id': 'synth-9-1', 'start_ms': self.EX_NOW - 1000,
            'end_ms': self.EX_NOW + 3600000, 'pic': '',
            'activities': [{
                'id': 'synth-ex-1', 'order': 1, 'need_level': 1,
                'need_pay_yb': 0, 'day_count': 5, 'max_count': 5,
                'con1': 'yuanbao|50', 'functiontype': 93,
                'currencies': {'jb': 100, 'lijin': 200,
                               'zhenqi': 300, 'shengwang': 0,
                               'exp': need},
                'item_views': [{
                    'goods_id': 'kangxing2', 'count': 1, 'bind': 1,
                    'hours': 0.0, 'effect': None, 'unsale': 0,
                    'lost': None}],
            }],
        }

        class _Synth:
            def __init__(self, real, cat):
                self._real = real
                self._cat = cat

            def __getattr__(self, name):
                return getattr(self._real, name)

            def zonghe(self, server_id='fu0', kaifu_ms=0):
                table = copy.deepcopy(self._real.zonghe(
                    server_id=server_id, kaifu_ms=kaifu_ms))
                table.setdefault(9, {'categories': [],
                                     'by_activity': {}})
                table[9]['categories'].append(copy.deepcopy(self._cat))
                return table

        self.rich()
        sess = self.make_sess(PROD_KAIFU,
                              config=_Synth(self.cfg, fixture))
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        out = sess.huodong_exchange_claim(
            [70551, [9, 'synth-ex-1', '']], now_ms=self.EX_NOW)
        got = frames(out)
        # Post-debit the purse still covers 50 and the 5/5 limits
        # stay open: state 1, with level-up pushes behind the reply.
        self.assertEqual(got[0], ['70551', [1, 'synth-ex-1', None, 1,
                                            1, 5, 1, 5]])
        self.assertEqual(got[1][0], '12001')
        role = dict(self.store.list_roles('hero', 'fu1304')[0])
        self.assertEqual(role['lingshi'], 100000 - 50)
        self.assertEqual(role['tongqian'], 100)
        self.assertEqual(role['bind_lingshi'], 200)
        self.assertEqual(role['zhenqi'], 300)
        self.assertEqual(role['level'], 57)
        self.assertEqual(self.bag(), {'kangxing2': 1})

    def test_exchange_failed_apply_rolls_back(self):
        # Straight at the store: a two-grant apply whose second grant
        # overflows capacity writes the first slot, then aborts; the
        # rollback must leave no partial state behind.
        self.store.save_role_bag_state(self.rid, bag_capacity=1,
                                       storage_capacity=144)
        with self.assertRaises(Exception) as ctx:
            self.store.huodong_exchange_tx(
                self.rid, 0, 0, [],
                [{'goods_id': 'kangxing2', 'count': 1, 'bind': 1},
                 {'goods_id': 'duihuan2', 'count': 15, 'bind': 1}],
                {'kangxing2': 99, 'duihuan2': 999}, 1, {}, '{}', '{}')
        self.assertEqual(type(ctx.exception).__name__, 'HuodongAbort')
        self.assertEqual(self.bag(), {})
        row = self.store.get_role_huodong(self.rid) or {}
        self.assertEqual(json.loads(row.get('day_count') or '{}'), {})
        self.assertEqual(json.loads(row.get('max_count') or '{}'), {})

    def test_exchange_concurrent_claims_stay_consistent(self):
        act = '201402252-9chongzhiduihuan4-3'
        self.rich()
        self.stock(('expfold_002', 5, 1))
        results, lock = [], threading.Lock()

        def one():
            sess = self.make_sess(PROD_KAIFU)
            sess.authed_user, sess.server_id = 'hero', 'fu1304'
            try:
                out = sess.huodong_exchange_claim(
                    [70551, [9, act, '']], now_ms=self.OLD_NOW)
                body = decode(bytes(out)[4:])
            except Exception as e:  # pragma: no cover - deadlock tripwire
                body = e
            with lock:
                results.append(body)

        threads = [threading.Thread(target=one) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Stock and limits admit every claim; the lock serializes the
        # five transactions, so all five win with no lost update.
        self.assertEqual(len(results), 5)
        for body in results:
            self.assertEqual(body[0], '70551')
            self.assertEqual(body[1][0], 1)
            self.assertEqual(body[1][1:3], [act, None])
        row = self.store.get_role_huodong(self.rid) or {}
        self.assertEqual(json.loads(row.get('day_count') or '{}'),
                         {act: 5})
        self.assertEqual(json.loads(row.get('max_count') or '{}'),
                         {act: 5})
        self.assertEqual(self.bag(), {'expfold_003': 5})
        role = dict(self.store.list_roles('hero', 'fu1304')[0])
        self.assertEqual(role['lingshi'], 100000 - 5 * 20)

    # -- 70551 recharge claim (ct-1: getRechangeReward) ------------------
    PER_ACT = '201400001-zuixinleiji104-2'
    ACC_ACT = '201400001-zuixinleiji101-2'
    ZQ_ACT = '201400001-zxzuoqi105-2'
    XIAOFEI_ACT = '201402252-xxfph003-3'

    def test_recharge_per_short_total_is_792001(self):
        # ft-10 row, con 2000: a fresh role's windowed total reads 0.
        body = self.claim([1, self.PER_ACT, ''], self.EX_NOW)
        self.assertEqual(body, ['70551', [0, 792001]])
        self.assertEqual(self.bag(), {})
        row = self.store.get_role_huodong(self.rid) or {}
        self.assertEqual(json.loads(row.get('day_count') or '{}'), {})

    def test_recharge_acc_short_total_is_792001(self):
        # ft-11 row, con 200: same gate, no side effects.
        body = self.claim([1, self.ACC_ACT, ''], self.EX_NOW)
        self.assertEqual(body, ['70551', [0, 792001]])
        self.assertEqual(self.bag(), {})

    def test_recharge_success_persists_and_repeats(self):
        self.sess = self.make_sess(PROD_KAIFU, charge=5000)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        body = self.claim([1, self.ACC_ACT, ''], self.EX_NOW)
        # Limits are 1/1, so the post-claim display reads state 2;
        # the choujiang cell reads null (empty table, jar's null arm).
        self.assertEqual(
            body,
            ['70551', [1, self.ACC_ACT, '', 2, 1, 1, 1, 1, None]])
        self.assertEqual(self.bag(), {
            'chip_nvwa': 2, 'jinjiedan001': 2, 'zhenqipill_003': 1,
            'tongqian003': 1, 'expfold_002': 1})
        self.assertEqual(
            self.counters()['day_count'], {self.ACC_ACT: 1})
        self.assertEqual(
            self.counters()['max_count'], {self.ACC_ACT: 1})
        self.assertEqual(self.claim([1, self.ACC_ACT, ''], self.EX_NOW),
                         ['70551', [0, 792006]])

    def test_recharge_unknown_choose_is_792005(self):
        # fu0 rows carry no choose entries: any non-empty chooseId
        # misses the map, with no counters or grants written.
        self.sess = self.make_sess(PROD_KAIFU, charge=5000)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        body = self.claim([1, self.ACC_ACT, 'nope'], self.EX_NOW)
        self.assertEqual(body, ['70551', [0, 792005]])
        self.assertEqual(self.bag(), {})
        row = self.store.get_role_huodong(self.rid) or {}
        self.assertEqual(json.loads(row.get('day_count') or '{}'), {})

    def test_recharge_choose_grant_state_one_and_level_frames(self):
        # Synthetic ct-1 row with one choose entry: a covering total
        # grants the chosen award (not the flat one), the 5/5 limits
        # and con*(1+1) <= total keep state 1, and the exp arm pushes
        # the 12001 level-up frames behind the 9-array reply.
        need = int(self.cfg.role_need_exp(56))
        fixture = {
            'id': 'synth-1-1', 'start_ms': self.EX_NOW - 1000,
            'end_ms': self.EX_NOW + 3600000, 'pic': '',
            'activities': [{
                'id': 'synth-r-1', 'order': 1, 'need_level': 1,
                'need_pay_yb': 0, 'day_count': 5, 'max_count': 5,
                'con1': '100', 'functiontype': 11,
                'currencies': {'jb': 0, 'lijin': 0, 'zhenqi': 0,
                               'shengwang': 0, 'exp': 0},
                'item_views': [{
                    'goods_id': 'duihuan2', 'count': 1, 'bind': 1,
                    'hours': 0.0, 'effect': None, 'unsale': 0,
                    'lost': None}],
                'choose_awards': {'c9': {
                    'currencies': {'jb': 50, 'lijin': 0, 'zhenqi': 0,
                                   'shengwang': 0, 'exp': need},
                    'item_views': [{
                        'goods_id': 'kangxing2', 'count': 2, 'bind': 1,
                        'hours': 0.0, 'effect': None, 'unsale': 0,
                        'lost': None}]}},
            }],
        }

        class _Synth:
            def __init__(self, real, cat):
                self._real = real
                self._cat = cat

            def __getattr__(self, name):
                return getattr(self._real, name)

            def zonghe(self, server_id='fu0', kaifu_ms=0):
                table = copy.deepcopy(self._real.zonghe(
                    server_id=server_id, kaifu_ms=kaifu_ms))
                table.setdefault(1, {'categories': [],
                                     'by_activity': {}})
                table[1]['categories'].append(copy.deepcopy(self._cat))
                return table

        sess = self.make_sess(PROD_KAIFU,
                              config=_Synth(self.cfg, fixture),
                              charge=5000)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        out = sess.huodong_exchange_claim(
            [70551, [1, 'synth-r-1', 'c9']], now_ms=self.EX_NOW)
        got = [decode(bytes(f)[4:]) for f in out]
        self.assertEqual(got[0], ['70551', [1, 'synth-r-1', 'c9', 1,
                                            1, 5, 1, 5, None]])
        self.assertEqual(got[1][0], '12001')
        role = dict(self.store.list_roles('hero', 'fu1304')[0])
        self.assertEqual(role['tongqian'], 50)
        self.assertEqual(role['level'], 57)
        self.assertEqual(self.bag(), {'kangxing2': 2})

    # -- 70551 in-tx EXP / credit deltas ---------------------------------
    EXP_NEED_56 = 13531560
    EXP_CHAIN = [(57, 0), (57, 13531560), (58, 12417528),
                 (59, 10175232), (60, 6790440)]

    def exp_fixture(self, exp=None, jb=50, lijin=0, zhenqi=0,
                    act_id='synth-exp-5'):
        return {
            'id': 'synth-1x-1', 'start_ms': self.EX_NOW - 1000,
            'end_ms': self.EX_NOW + 3600000, 'pic': '',
            'activities': [{
                'id': act_id, 'order': 1, 'need_level': 1,
                'need_pay_yb': 0, 'day_count': 5, 'max_count': 5,
                'con1': '100', 'functiontype': 11,
                'currencies': {'jb': jb, 'lijin': lijin,
                               'zhenqi': zhenqi, 'shengwang': 0,
                               'exp': exp},
                'item_views': [{
                    'goods_id': 'kangxing2', 'count': 2, 'bind': 1,
                    'hours': 0.0, 'effect': None, 'unsale': 0,
                    'lost': None}],
                'choose_awards': {},
            }],
        }

    def exp_sess(self, fixture, charge=5000):
        sess = self.make_sess(
            PROD_KAIFU,
            config=_SynthTable(self.cfg, 1, fixture), charge=charge)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return sess

    def test_exchange_exp_concurrent_claims_serialize_on_value(self):
        # Five simultaneous exp-granting claims must serialize on
        # value: each tx computes from its fresh in-tx row, so the
        # five replies land on five distinct chain states, the
        # credits add up, and nothing is clobbered. Pre-fix code
        # computed all five from the same stale snapshot (identical
        # frames, last-writer-wins persistence).
        need = int(self.cfg.role_need_exp(56))
        self.assertEqual(need, self.EXP_NEED_56)
        fixture = self.exp_fixture(exp=need)
        results, lock = [], threading.Lock()

        def one():
            sess = self.exp_sess(fixture)
            try:
                out = sess.huodong_exchange_claim(
                    [70551, [1, 'synth-exp-5', '']], now_ms=self.EX_NOW)
                blobs = out if isinstance(out, list) else [out]
                body = [decode(bytes(f)[4:]) for f in blobs]
            except Exception as e:  # pragma: no cover - deadlock tripwire
                body = e
            with lock:
                results.append(body)

        threads = [threading.Thread(target=one) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), 5)
        noticed = []
        singles = 0
        for body in results:
            self.assertEqual(body[0][0], '70551')
            self.assertEqual(body[0][1][0], 1)
            self.assertEqual(body[0][1][3], 1)
            if len(body) == 1:
                singles += 1
            else:
                self.assertEqual(body[1][0], '12001')
                noticed.append((int(body[1][1][1]),
                                int(body[1][1][0])))
        # Exactly the non-leveling claim pushes no frames; the four
        # level-ups carry the exact chain states.
        self.assertEqual(singles, 1)
        self.assertEqual(
            sorted(noticed),
            sorted(self.EXP_CHAIN[i] for i in (0, 2, 3, 4)))
        role = dict(self.store.list_roles('hero', 'fu1304')[0])
        self.assertEqual((role['level'], role['exp']), (60, 6790440))
        self.assertEqual(role['tongqian'], 250)
        self.assertEqual(self.bag(), {'kangxing2': 10})

    def test_exchange_exp_sequential_claims_accumulate_exactly(self):
        need = int(self.cfg.role_need_exp(56))
        sess = self.exp_sess(self.exp_fixture(exp=need))
        first = [decode(bytes(f)[4:])
                 for f in sess.huodong_exchange_claim(
                     [70551, [1, 'synth-exp-5', '']], now_ms=self.EX_NOW)]
        self.assertEqual(first[0], ['70551', [1, 'synth-exp-5', '', 1,
                                              1, 5, 1, 5, None]])
        self.assertEqual(first[1], ['12001', [0.0, 57]])
        role = dict(self.store.list_roles('hero', 'fu1304')[0])
        attr57 = self.cfg.role_attribute_row(57)
        self.assertEqual(
            (role['level'], role['exp'], role['max_hp'], role['max_mp']),
            (57, 0, int(attr57['hitpoints']), int(attr57['mana'])))
        # No level-up on the second gain: a bare reply, no pushes,
        # and the bar banks the full amount.
        second = sess.huodong_exchange_claim(
            [70551, [1, 'synth-exp-5', '']], now_ms=self.EX_NOW)
        self.assertEqual(decode(bytes(second)[4:]),
                         ['70551', [1, 'synth-exp-5', '', 1,
                                   2, 5, 2, 5, None]])
        role = dict(self.store.list_roles('hero', 'fu1304')[0])
        self.assertEqual(
            (role['level'], role['exp'], role['max_hp']),
            (57, need, int(attr57['hitpoints'])))

    def test_exchange_exp_failure_rolls_back_values(self):
        # Straight at the store: an exp-granting tx whose bag grant
        # overflows must roll the persisted level/exp/credits back
        # with the counters and stock, not bank them and fail.
        need = int(self.cfg.role_need_exp(56))
        before = dict(self.store.list_roles('hero', 'fu1304')[0])
        self.store.save_role_bag_state(self.rid, bag_capacity=1,
                                       storage_capacity=144)
        apply = self.sess._zonghe_exp_apply(need)
        with self.assertRaises(Exception) as ctx:
            self.store.huodong_exchange_tx(
                self.rid, 0, 0, [],
                [{'goods_id': 'kangxing2', 'count': 1, 'bind': 1},
                 {'goods_id': 'duihuan2', 'count': 15, 'bind': 1}],
                {'kangxing2': 99, 'duihuan2': 999}, 1,
                {'tongqian': 50}, 'synth-x', 'synth-x',
                exp_apply=apply)
        self.assertEqual(type(ctx.exception).__name__, 'HuodongAbort')
        role = dict(self.store.list_roles('hero', 'fu1304')[0])
        for col in ('level', 'exp', 'tongqian', 'max_hp', 'max_mp'):
            self.assertEqual(role[col], before[col], col)
        row = self.store.get_role_huodong(self.rid) or {}
        self.assertEqual(json.loads(row.get('day_count') or '{}'), {})
        self.assertEqual(json.loads(row.get('max_count') or '{}'), {})
        self.assertEqual(self.bag(), {})

    def test_exchange_currency_grants_add_not_assign(self):
        # The jar's incr semantics: grants add to nonzero balances.
        self.store.update_character_state(
            self.rid, tongqian=1000, bind_lingshi=2000, zhenqi=3000)
        sess = self.exp_sess(self.exp_fixture(
            exp=0, jb=50, lijin=60, zhenqi=70, act_id='synth-cur-1'))
        body = decode(bytes(sess.huodong_exchange_claim(
            [70551, [1, 'synth-cur-1', '']],
            now_ms=self.EX_NOW))[4:])
        self.assertEqual(body[1][0], 1)
        role = dict(self.store.list_roles('hero', 'fu1304')[0])
        self.assertEqual(
            (role['tongqian'], role['bind_lingshi'], role['zhenqi']),
            (1050, 2060, 3070))

    # -- 70551 rank claims (ct-22/30/31/32) -------------------------------
    BS_ACT = '20140226-1bsa001-3'
    BS_NOW = 1393344001000 + 3600000
    QB_ACT = '20140226-6qc002-3'
    QB_NOW = 1393344001000 + 3600000
    GY_ACT = '20140227-gygy003-3'
    GY_NOW = 1393430401000 + 3600000
    VIP_KAIFU = 1394000000000
    VIP_NOW = 1394000000000 + 2 * 86400000 + 3600000
    VIP_ACT = '201400003-zxvip104-5'

    def test_baoshi_short_sum_is_792001(self):
        # Genuine row, con 30 against no socketed gems.
        body = self.claim([22, self.BS_ACT], self.BS_NOW)
        self.assertEqual(body, ['70551', [0, 792001]])
        self.assertEqual(self.bag(), {})

    def test_baoshi_success_persists(self):
        self.store.save_role_baoshi(self.rid, [
            {'id': 'g1', 'part': 1, 'grid': 1, 'level': 10},
            {'id': 'g2', 'part': 2, 'grid': 1, 'level': 10},
            {'id': 'g3', 'part': 3, 'grid': 1, 'level': 10}])
        body = self.claim([22, self.BS_ACT], self.BS_NOW)
        # Limits are 1/1: post-claim state 2, no choujiang cell.
        self.assertEqual(body, ['70551', [1, self.BS_ACT, None, 2,
                                          1, 1, 1, 1]])
        self.assertEqual(self.bag(),
                         {'bscl': 200, 'baoshilixiang1': 1})
        self.assertEqual(
            self.counters()['day_count'], {self.BS_ACT: 1})
        self.assertEqual(self.claim([22, self.BS_ACT], self.BS_NOW),
                         ['70551', [0, 792006]])

    def test_baoshi_bag_full_is_430212(self):
        self.store.save_role_baoshi(self.rid, [
            {'id': 'g1', 'part': 1, 'grid': 1, 'level': 30}])
        self.stock(('duihuan2', 15, 1))
        self.store.save_role_bag_state(self.rid, bag_capacity=1,
                                       storage_capacity=144)
        body = self.claim([22, self.BS_ACT], self.BS_NOW)
        self.assertEqual(body, ['70551', [0, 430212]])
        self.assertEqual(self.bag(), {'duihuan2': 15})

    def test_qibing_short_is_792001(self):
        # The qibing service is unported: the metric reads 0.
        body = self.claim([30, self.QB_ACT], self.QB_NOW)
        self.assertEqual(body, ['70551', [0, 792001]])
        self.assertEqual(self.bag(), {})

    def test_qibing_success_persists_and_restart(self):
        self.sess = self.make_sess(PROD_KAIFU, qibing=3)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        body = self.claim([30, self.QB_ACT], self.QB_NOW)
        self.assertEqual(body, ['70551', [1, self.QB_ACT, None, 2,
                                          1, 1, 1, 1]])
        self.assertEqual(self.bag(),
                         {'qibing001': 160, 'qibinglixiang1': 1})
        self.assertEqual(
            self.counters()['day_count'], {self.QB_ACT: 1})
        self.store.close()
        self.store = Store(self.db_path)
        self.addCleanup(self.store.close)
        self.sess = self.make_sess(PROD_KAIFU, qibing=3)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.assertEqual(self.claim([30, self.QB_ACT], self.QB_NOW),
                         ['70551', [0, 792006]])
        self.assertEqual(self.bag(),
                         {'qibing001': 160, 'qibinglixiang1': 1})

    def test_chibang_short_is_792001(self):
        # No wing row: the level reads 0 against con 3.
        body = self.claim([31, self.GY_ACT], self.GY_NOW)
        self.assertEqual(body, ['70551', [0, 792001]])
        self.assertEqual(self.bag(), {})

    def test_chibang_success_persists(self):
        self.store.save_role_guangyi(self.rid, level=3)
        body = self.claim([31, self.GY_ACT], self.GY_NOW)
        self.assertEqual(body, ['70551', [1, self.GY_ACT, None, 2,
                                          1, 1, 1, 1]])
        self.assertEqual(self.bag(),
                         {'guangyi001': 250, 'guangyilixiang1': 1})
        self.assertEqual(
            self.counters()['max_count'], {self.GY_ACT: 1})
        self.assertEqual(self.claim([31, self.GY_ACT], self.GY_NOW),
                         ['70551', [0, 792006]])

    def test_vip_short_is_792001(self):
        # No vip row: the level reads 0 against con 4.
        sess = self.make_sess(self.VIP_KAIFU)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        out = sess.huodong_exchange_claim(
            [70551, [32, self.VIP_ACT]], now_ms=self.VIP_NOW)
        self.assertEqual(decode(bytes(out)[4:]),
                         ['70551', [0, 792001]])

    def test_vip_success_persists(self):
        self.store.save_role_vip(self.rid, vip_level=4)
        sess = self.make_sess(self.VIP_KAIFU)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        out = sess.huodong_exchange_claim(
            [70551, [32, self.VIP_ACT]], now_ms=self.VIP_NOW)
        self.assertEqual(decode(bytes(out)[4:]),
                         ['70551', [1, self.VIP_ACT, None, 2,
                                   1, 1, 1, 1]])
        self.assertEqual(self.bag(),
                         {'qianghuashi': 30, 'jinjieshi': 15})
        self.assertEqual(
            self.counters()['day_count'], {self.VIP_ACT: 1})

    def test_wire_rank_gates(self):
        # Encrypted-wire: live-shaped ct-22/30/31/32 rows read
        # expired against the wall clock, proving dispatch reaches
        # all four new rank branches through the real cipher path.
        self.sess.feed(bytes.fromhex('00000009060f494e49544b4559'))
        payloads = [([22, self.BS_ACT], [0, 792003]),
                    ([30, self.QB_ACT], [0, 792003]),
                    ([31, self.GY_ACT], [0, 792003]),
                    ([32, self.VIP_ACT], [0, 792003])]
        for data, want in payloads:
            req = self.sess.cipher.encode(encode([70551, data]))
            out = self.sess.feed(struct.pack('>I', len(req)) + req)
            self.assertEqual([decode(bytes(f)[4:]) for f in out],
                             [['70551', want]])

    # -- 70551 consume/forever claims (ct-3/ct-7, synthetic) -------------
    # fu0 holds zero ct-3 and zero ct-7 rows, so both branches ride
    # labeled synthetic fixtures in the shipped schema; the
    # thresholds, replies and gates are bytecode-verbatim.
    def synth_family(self, ctype, act, con, functiontype,
                     day=1, maximum=1, currencies=None):
        return {
            'id': 'synth-%d-1' % ctype,
            'start_ms': self.EX_NOW - 1000,
            'end_ms': self.EX_NOW + 3600000, 'pic': '',
            'activities': [{
                'id': act, 'order': 1, 'need_level': 1,
                'need_pay_yb': 0, 'day_count': day,
                'max_count': maximum, 'con1': con,
                'functiontype': functiontype,
                'currencies': currencies or
                {'jb': 0, 'lijin': 0, 'zhenqi': 0,
                 'shengwang': 0, 'exp': 0},
                'item_views': [{
                    'goods_id': 'kangxing2', 'count': 1, 'bind': 1,
                    'hours': 0.0, 'effect': None, 'unsale': 0,
                    'lost': None}],
                'choose_awards': {},
            }],
        }

    def test_consume_short_pay_is_792001(self):
        sess = self.make_sess(
            PROD_KAIFU,
            config=_SynthTable(
                self.cfg, 3,
                self.synth_family(3, 'synth-c-1', '200', 92)))
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        out = sess.huodong_exchange_claim(
            [70551, [3, 'synth-c-1', '']], now_ms=self.EX_NOW)
        self.assertEqual(decode(bytes(out)[4:]),
                         ['70551', [0, 792001]])
        self.assertEqual(self.bag(), {})

    def test_consume_success_persists(self):
        self.store.save_role_huodong(
            self.rid, pay_yb=json.dumps({'synth-c-1': 200}))
        sess = self.make_sess(
            PROD_KAIFU,
            config=_SynthTable(
                self.cfg, 3,
                self.synth_family(3, 'synth-c-1', '200', 92)))
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        out = sess.huodong_exchange_claim(
            [70551, [3, 'synth-c-1', '']], now_ms=self.EX_NOW)
        # Limits are 1/1: post-claim state 2, choujiang null.
        self.assertEqual(decode(bytes(out)[4:]),
                         ['70551', [1, 'synth-c-1', '', 2, 1, 1,
                                   1, 1, None]])
        self.assertEqual(self.bag(), {'kangxing2': 1})
        self.assertEqual(
            self.counters()['day_count'], {'synth-c-1': 1})
        out = sess.huodong_exchange_claim(
            [70551, [3, 'synth-c-1', '']], now_ms=self.EX_NOW)
        self.assertEqual(decode(bytes(out)[4:]),
                         ['70551', [0, 792006]])

    def test_consume_unknown_choose_is_792005(self):
        self.store.save_role_huodong(
            self.rid, pay_yb=json.dumps({'synth-c-1': 200}))
        sess = self.make_sess(
            PROD_KAIFU,
            config=_SynthTable(
                self.cfg, 3,
                self.synth_family(3, 'synth-c-1', '200', 92)))
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        out = sess.huodong_exchange_claim(
            [70551, [3, 'synth-c-1', 'nope']], now_ms=self.EX_NOW)
        self.assertEqual(decode(bytes(out)[4:]),
                         ['70551', [0, 792005]])
        self.assertEqual(self.bag(), {})

    def test_forever_short_total_is_792001(self):
        sess = self.make_sess(
            PROD_KAIFU,
            config=_SynthTable(
                self.cfg, 7,
                self.synth_family(7, 'synth-f-1', '500', 14)))
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        out = sess.huodong_exchange_claim(
            [70551, [7, 'synth-f-1', '']], now_ms=self.EX_NOW)
        self.assertEqual(decode(bytes(out)[4:]),
                         ['70551', [0, 792001]])
        self.assertEqual(self.bag(), {})

    def test_forever_success_persists_state_one(self):
        sess = self.make_sess(
            PROD_KAIFU,
            config=_SynthTable(
                self.cfg, 7,
                self.synth_family(7, 'synth-f-1', '500', 14,
                                  day=5, maximum=5)),
            lifetime=1000)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        out = sess.huodong_exchange_claim(
            [70551, [7, 'synth-f-1', '']], now_ms=self.EX_NOW)
        # The 8-array carries no chooseId slot; the 5/5 limits and
        # 1000 >= 500 keep state 1, choujiang null.
        self.assertEqual(decode(bytes(out)[4:]),
                         ['70551', [1, 'synth-f-1', 1, 1, 5, 1,
                                   5, None]])
        self.assertEqual(self.bag(), {'kangxing2': 1})
        self.assertEqual(
            self.counters()['max_count'], {'synth-f-1': 1})

    # -- 70551 zuoqi claim (ct-10: getZuoqiReward) -----------------------
    def test_zuoqi_short_rank_is_792001(self):
        # con 5 against a fresh rank-0 mount.
        body = self.claim([10, self.ZQ_ACT], self.EX_NOW)
        self.assertEqual(body, ['70551', [0, 792001]])
        self.assertEqual(self.bag(), {})
        row = self.store.get_role_huodong(self.rid) or {}
        self.assertEqual(json.loads(row.get('day_count') or '{}'), {})

    def test_zuoqi_success_persists(self):
        self.store.save_role_zuoqi(self.rid, zuoqi_rank=5,
                                   zuoqi_cur_rank=5)
        body = self.claim([10, self.ZQ_ACT], self.EX_NOW)
        # Limits are 1/1: post-claim state 2, no choujiang cell.
        self.assertEqual(body, ['70551', [1, self.ZQ_ACT, None, 2,
                                          1, 1, 1, 1]])
        self.assertEqual(self.bag(), {'jinjiedan001': 300})
        self.assertEqual(
            self.counters()['day_count'], {self.ZQ_ACT: 1})
        self.assertEqual(
            self.counters()['max_count'], {self.ZQ_ACT: 1})
        self.assertEqual(self.claim([10, self.ZQ_ACT], self.EX_NOW),
                         ['70551', [0, 792006]])

    def test_zuoqi_bag_full_is_430212(self):
        self.store.save_role_zuoqi(self.rid, zuoqi_rank=8,
                                   zuoqi_cur_rank=8)
        self.stock(('duihuan2', 15, 1))
        self.store.save_role_bag_state(self.rid, bag_capacity=1,
                                       storage_capacity=144)
        body = self.claim([10, self.ZQ_ACT], self.EX_NOW)
        self.assertEqual(body, ['70551', [0, 430212]])
        self.assertEqual(self.bag(), {'duihuan2': 15})

    # -- 70551 silent arms ------------------------------------------------
    def test_xiaofei_claim_is_silent(self):
        # ct-34 has no claim arm: the jar falls through and returns
        # null, so nothing is framed even for a real activity id.
        self.assertIsNone(self.claim([34, self.XIAOFEI_ACT],
                                     self.EX_NOW))

    def test_unknown_clienttype_claim_is_silent(self):
        self.assertIsNone(self.claim([99, self.ACC_ACT, ''],
                                     self.EX_NOW))

    def test_recharge_unknown_activity_is_silent(self):
        self.assertIsNone(self.claim([1, 'no-such-act', ''],
                                     self.EX_NOW))

    def test_wire_recharge_and_zuoqi_gates(self):
        # Encrypted-wire: live ct-1/ct-10 rows at PROD_KAIFU+1h read
        # expired against the wall clock, proving dispatch reaches
        # both new branches through the real cipher path.
        self.sess.feed(bytes.fromhex('00000009060f494e49544b4559'))
        payloads = [([1, self.ACC_ACT, ''], [0, 792003]),
                    ([10, self.ZQ_ACT], [0, 792003])]
        for data, want in payloads:
            req = self.sess.cipher.encode(encode([70551, data]))
            out = self.sess.feed(struct.pack('>I', len(req)) + req)
            self.assertEqual([decode(bytes(f)[4:]) for f in out],
                             [['70551', want]])

    # -- 70550 mall buy -------------------------------------------------
    def test_mall_buy_success_persists_and_refreshes(self):
        self.rich()
        got = self.buy([5, self.MALL_ACT, self.MALL_GOOD, 1],
                        self.EX_NOW)
        self.assertIsInstance(got, list)
        self.assertEqual(
            got[0],
            ['70550', [1, self.MALL_ACT, self.MALL_GOOD, 1, 1, 9999,
                       1, 9999]])
        # Queued 70506 refresh already reflects the persisted buy.
        rows = {r[0]: r for r in got[1][1][5]}
        self.assertEqual(rows[self.MALL_ACT][6:8], [9998, 9998])
        role = dict(self.store.list_roles('hero', 'fu1304')[0])
        self.assertEqual(role['lingshi'], 100000 - 20)
        self.assertEqual(self.bag(), {self.MALL_GOOD: 1})
        self.assertEqual(
            self.counters()['mall_buy_count'],
            {self.MALL_ACT + self.MALL_GOOD: 1})
        info = self.store.get_huodong_info(self.MALL_ACT) or {}
        self.assertEqual(json.loads(info.get('mall_sell_info') or '{}'),
                         {self.MALL_GOOD: 1})
        # Restart keeps every counter: the panel stays consistent.
        self.store.close()
        self.store = Store(self.db_path)
        self.addCleanup(self.store.close)
        self.sess = self.make_sess(PROD_KAIFU)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        rows = {r[0]: r
                for r in self.sess._zonghe_mall(self.role,
                                                now_ms=self.EX_NOW)[5]}
        self.assertEqual(rows[self.MALL_ACT][6:8], [9998, 9998])

    def test_mall_buy_single_unit_rejects_repeat(self):
        self.rich()
        first = self.buy([5, self.ONE_ACT, self.ONE_GOOD, 1],
                         self.EX_NOW)
        self.assertEqual(first[0][1][3], 2)
        # The spent day counter trips the day floor first (Java gate
        # order: day 792008 before the per-good limit).
        self.assertEqual(self.buy([5, self.ONE_ACT, self.ONE_GOOD, 1],
                                  self.EX_NOW),
                         ['70550', [0, 792008]])
        self.assertEqual(
            self.counters()['mall_buy_count'],
            {self.ONE_ACT + self.ONE_GOOD: 1})
        self.assertEqual(self.bag(), {self.ONE_GOOD: 1})

    def test_mall_buy_short_purse_is_792001(self):
        self.rich(lingshi=19)
        body = self.buy([5, self.MALL_ACT, self.MALL_GOOD, 1],
                        self.EX_NOW)
        self.assertEqual(body, ['70550', [0, 792001]])
        self.assertEqual(self.bag(), {})

    def test_mall_buy_sellout_is_792004(self):
        self.rich()
        self.store.save_huodong_info(
            self.MALL_ACT, json.dumps({self.MALL_GOOD: 9999}))
        body = self.buy([5, self.MALL_ACT, self.MALL_GOOD, 1],
                        self.EX_NOW)
        self.assertEqual(body, ['70550', [0, 792004]])
        self.assertEqual(self.bag(), {})
        role = dict(self.store.list_roles('hero', 'fu1304')[0])
        self.assertEqual(role['lingshi'], 100000)

    def test_mall_buy_unknown_good_is_792001(self):
        self.assertEqual(self.buy([5, self.MALL_ACT, 'no-such-good', 1],
                                  self.EX_NOW),
                         ['70550', [0, 792001]])

    def test_mall_buy_unknown_activity_is_silent(self):
        self.assertIsNone(self.buy([5, 'no-such-act', self.MALL_GOOD, 1],
                                   self.EX_NOW))

    def test_mall_buy_count_floor_is_792001(self):
        self.assertEqual(self.buy([5, self.MALL_ACT, self.MALL_GOOD, 0],
                                  self.EX_NOW),
                         ['70550', [0, 792001]])

    def test_mall_buy_expired_is_792003(self):
        self.assertEqual(self.buy([5, self.MALL_ACT, self.MALL_GOOD, 1],
                                  1390000000000),
                         ['70550', [0, 792003]])

    # -- wire + regression -----------------------------------------------
    def test_wire_dispatch_wall_clock(self):
        # No 2014 category is live now: both gates read expired.
        self.sess.feed(bytes.fromhex('00000009060f494e49544b4559'))
        payloads = {70550: [5, self.MALL_ACT, self.MALL_GOOD, 1],
                    70551: [9, self.EX_ID, '']}
        for cmd, data in payloads.items():
            req = self.sess.cipher.encode(encode([cmd, data]))
            out = self.sess.feed(struct.pack('>I', len(req)) + req)
            self.assertEqual([decode(bytes(f)[4:]) for f in out],
                             [[str(cmd), [0, 792003]]])

    def test_missing_clienttype_is_792005(self):
        # Java's null category reads [0, 792005], not the bare [2].
        class _DropCt:
            def __init__(self, real, drop):
                self._real = real
                self._drop = drop

            def __getattr__(self, name):
                return getattr(self._real, name)

            def zonghe(self, server_id='fu0', kaifu_ms=0):
                table = copy.deepcopy(self._real.zonghe(
                    server_id=server_id, kaifu_ms=kaifu_ms))
                table.pop(self._drop, None)
                return table

        sess = self.make_sess(PROD_KAIFU,
                              config=_DropCt(self.cfg, 9))
        self.assertEqual(
            sess._zonghe_exchange(self.role, now_ms=self.EX_NOW),
            [0, 792005])
        sess = self.make_sess(PROD_KAIFU,
                              config=_DropCt(self.cfg, 5))
        self.assertEqual(
            sess._zonghe_mall(self.role, now_ms=self.EX_NOW),
            [0, 792005])


if __name__ == '__main__':
    unittest.main()

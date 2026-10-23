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
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode  # noqa: E402
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


if __name__ == '__main__':
    unittest.main()

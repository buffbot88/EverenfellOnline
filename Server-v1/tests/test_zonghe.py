"""Zonghe loader + first-recharge claim core (HuodongAction ct=21 family).

Evidence: docs/zonghe-finding.md (authentic fu0 snapshot at
MKO_Client/.../compositiveactivity/fu0, Java TC_LONGSTRING + JSON),
hdzh.txt (configureDataResolve null/empty silent keep-old, missing
activitys skips the category, convert failure drops unknown
clienttypes, HuodongInit after load), the CompositiveActivityClientType
int values (hdct.txt) and checkHuodongIsValid/timeIsExpiry semantics.

The loader reads the shipped snapshot in place (like the reference/
config tree) and preserves JSON types (con1 stays a string, thresholds
are per-family). The claim core covers the full lifecycle through the
real handlers + SQLite store: recharge latch + 71002 push (ledger shape),
live-window eligibility, snapshot-item grant, duplicate protection,
bag-full with no state change, and expiry. 70000/70001 have no inbound
wire yet: their reply shapes are unrecovered, so the core is exercised
through zonghe_recharge/zonghe_first_claim directly.
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
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=PROD_KAIFU,
            save_role_state=self.store.update_character_state,
            get_role_huodong=self.store.get_role_huodong,
            save_role_huodong=self.store.save_role_huodong,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.role = dict(self.store.list_roles('hero', 'fu1304')[0])

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
        self.assertEqual(frames(out), [['71002', [LIVE_CAT, 1000, 1]]])
        self.assertEqual(self.state(), {'charged': 1, 'claimed': []})

    def test_recharge_outside_window_latches_without_push(self):
        out = self.sess.zonghe_recharge(
            self.role, 1000, now_ms=1390000000000)
        self.assertEqual(out, [])
        self.assertEqual(self.state(), {'charged': 1, 'claimed': []})

    # -- claim ---------------------------------------------------------------
    def test_claim_before_recharge(self):
        self.assertIsNone(
            self.sess.zonghe_first_claim(self.role, now_ms=LIVE_NOW))
        self.assertEqual(self.bag(), {})

    def test_claim_grants_snapshot_items_and_persists(self):
        self.sess.zonghe_recharge(self.role, 1000, now_ms=LIVE_NOW)
        got = self.sess.zonghe_first_claim(self.role, now_ms=LIVE_NOW)
        self.assertEqual(got, LIVE_PAIRS)
        self.assertEqual(
            self.bag(),
            {gid: count for gid, count in LIVE_PAIRS})
        self.assertEqual(self.state(),
                         {'charged': 1, 'claimed': [LIVE_ACT]})

    def test_claim_duplicate(self):
        self.sess.zonghe_recharge(self.role, 1000, now_ms=LIVE_NOW)
        self.assertIsNotNone(
            self.sess.zonghe_first_claim(self.role, now_ms=LIVE_NOW))
        self.assertIsNone(
            self.sess.zonghe_first_claim(self.role, now_ms=LIVE_NOW))
        self.assertEqual(self.state(),
                         {'charged': 1, 'claimed': [LIVE_ACT]})

    def test_claim_after_window(self):
        self.sess.zonghe_recharge(self.role, 1000, now_ms=LIVE_NOW)
        self.assertIsNone(self.sess.zonghe_first_claim(
            self.role, now_ms=1393689599000 + 1))
        self.assertEqual(self.state(), {'charged': 1, 'claimed': []})

    def test_claim_full_bag_keeps_state(self):
        self.store.save_role_bag_state(self.rid, bag_capacity=0,
                                       storage_capacity=0)
        self.sess.zonghe_recharge(self.role, 1000, now_ms=LIVE_NOW)
        self.assertIsNone(
            self.sess.zonghe_first_claim(self.role, now_ms=LIVE_NOW))
        self.assertEqual(self.state(), {'charged': 1, 'claimed': []})


if __name__ == '__main__':
    unittest.main()

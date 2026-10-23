"""Online gifts (HuodongAction via OnlineGiftServiceImpl, 94000/94001).

Evidence: action javap (94000 info, 94001 reward with the null-reply
silence), OnlineGiftServiceImpl bytecode (getHuodongInfo/getReward/
online/logout, isNotEmptyAndNoEnd/isToday/initToday/getremainderTime/
getRewardArray/resetToNext/reSetLoginTime/resetRemainderTime), the
OnlineGiftConfig/OnlineGiftDayConfig loader mapping (kaifuzaixian.jat
rows {id, shijian=kaifu day, time=online seconds, jiangli}, file-order
nextId chains), RoleOnlineHuodongOutput ([[goodsId, count]] pairs),
RoleHuodongErrorCode 792010/792011 and the login/logout event wiring.

Every path runs through the real handlers and the real SQLite store,
with the wall clock replaced by backdated gift state: no sleeping.
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode, encode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session, frame  # noqa: E402
from game.protocol import (BAG_ERR_SLOT_LESS, CMD_HUODONG_ONLINE_INFO,  # noqa: E402
                            CMD_HUODONG_ONLINE_REWARD, HUODONG_ERR_NO_GIFT,
                            HUODONG_ERR_NOT_YET)

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..',
                           'reference', 'TonNgoKhong', 'server', 'config',
                           'game')
HAVE_REAL = os.path.isdir(REAL_CONFIG)


def frames(out):
    if isinstance(out, (bytes, bytearray)):
        return [decode(bytes(out)[4:])]
    return [decode(bytes(f)[4:]) for f in out]


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class HuodongOnlineGiftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'h.db'))
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
            server_start_ms=0,
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

    # -- helpers ----------------------------------------------------
    def row(self):
        return self.store.get_role_huodong(self.rid)

    def gift(self):
        raw = (self.row() or {}).get('max_count') or '{}'
        return (json.loads(raw) or {}).get('online_gift')

    def save_gift(self, state):
        self.store.save_role_huodong(self.rid, max_count=json.dumps(
            {'online_gift': state}))

    def backdate_created(self, days):
        with self.store.lock:
            self.store.db.execute(
                'UPDATE characters SET created=? WHERE id=?',
                (int(time.time()) - days * 86400, self.rid))
            self.store.db.commit()

    def reply(self, out):
        self.assertIsNotNone(out)
        got = frames(out)
        return got[0] if isinstance(got, list) else got

    # -- config -------------------------------------------------------
    def test_shipped_day_one_chain(self):
        days = self.cfg.online_gift_days()
        self.assertEqual(days[1]['start_id'], '1')
        ids = []
        cid = days[1]['start_id']
        while cid is not None:
            ids.append(cid)
            cid = days[1]['configs'][cid]['next_id']
        self.assertEqual(ids, ['1', '2', '3', '4', '5', '6', '7', '8'])
        self.assertEqual(days[1]['configs']['1']['minute'], 60)
        self.assertEqual(days[7]['configs']['56']['minute'], 3600)

    # -- login / silence ----------------------------------------------
    def test_info_silent_before_login(self):
        self.assertIsNone(self.sess.huodong_online_info())
        self.assertIsNone(self.gift())

    def test_enter_inits_day_one(self):
        self.sess._huodong_on_enter(str(self.rid))
        state = self.gift()
        self.assertEqual(state['day'], 1)
        self.assertEqual(state['id'], '1')
        self.assertEqual(state['minute'], 60 * 1000)

    def test_enter_same_day_refreshes_login_time(self):
        self.sess._huodong_on_enter(str(self.rid))
        self.save_gift({'day': 1, 'id': '1', 'logintime': 1,
                        'minute': 60000})
        self.sess._huodong_on_enter(str(self.rid))
        state = self.gift()
        self.assertEqual(state['id'], '1')
        self.assertGreater(state['logintime'], 1000)

    def test_enter_new_kaifu_day_reinits(self):
        self.backdate_created(1)
        self.sess._huodong_on_enter(str(self.rid))
        state = self.gift()
        self.assertEqual(state['day'], 2)
        self.assertEqual(state['id'], '9')

    def test_enter_past_last_day_ends(self):
        self.backdate_created(30)
        self.sess._huodong_on_enter(str(self.rid))
        state = self.gift()
        self.assertIn('end', state)
        self.assertIsNone(self.sess.huodong_online_info())
        self.assertEqual(self.reply(self.sess.huodong_online_reward()),
                         ['94001', [0, HUODONG_ERR_NO_GIFT]])

    # -- 94000 info ----------------------------------------------------
    def test_info_reports_countdown_and_pairs(self):
        self.sess._huodong_on_enter(str(self.rid))
        got = self.reply(self.sess.huodong_online_info())
        self.assertEqual(got[0], '94000')
        self.assertEqual(got[1][0], 1)
        self.assertGreater(got[1][1], 55000)
        self.assertLessEqual(got[1][1], 60000)
        self.assertEqual(got[1][2], [['xuechi', 3], ['lanchi', 3]])

    # -- 94001 claim ----------------------------------------------------
    def test_claim_too_early(self):
        self.sess._huodong_on_enter(str(self.rid))
        got = self.reply(self.sess.huodong_online_reward())
        self.assertEqual(got[0], '94001')
        self.assertEqual(got[1][0], 2)
        self.assertEqual(got[1][2], HUODONG_ERR_NOT_YET)

    def test_claim_matured_grants_and_advances(self):
        self.sess._huodong_on_enter(str(self.rid))
        self.save_gift({'day': 1, 'id': '1',
                        'logintime': int(time.time() * 1000) - 61000,
                        'minute': 60000})
        got = self.reply(self.sess.huodong_online_reward())
        self.assertEqual(got[0], '94001')
        self.assertEqual(got[1][0], 1)
        self.assertEqual(got[1][2], [['xuechi', 3], ['lanchi', 3]])
        slots = self.store.get_role_bag_slots(self.rid, 1, 150)
        have = {s['goods_id']: s['count'] for s in slots}
        self.assertEqual(have.get('xuechi'), 3)
        self.assertEqual(have.get('lanchi'), 3)
        state = self.gift()
        self.assertEqual(state['id'], '2')
        self.assertNotIn('end', state)

    def test_claim_last_gift_marks_end(self):
        self.sess._huodong_on_enter(str(self.rid))
        self.save_gift({'day': 1, 'id': '8',
                        'logintime': int(time.time() * 1000) - 3700000,
                        'minute': 3600000})
        got = self.reply(self.sess.huodong_online_reward())
        self.assertEqual(got, ['94001', [1, -1, got[1][2]]])
        self.assertIn('end', self.gift())

    def test_claim_full_bag(self):
        self.store.save_role_bag_state(self.rid, bag_capacity=0,
                                       storage_capacity=0)
        self.sess._huodong_on_enter(str(self.rid))
        self.save_gift({'day': 1, 'id': '1',
                        'logintime': int(time.time() * 1000) - 61000,
                        'minute': 60000})
        got = self.reply(self.sess.huodong_online_reward())
        self.assertEqual(got, ['94001', [0, BAG_ERR_SLOT_LESS]])
        self.assertEqual(self.gift()['id'], '1')

    def test_claim_without_state(self):
        got = self.reply(self.sess.huodong_online_reward())
        self.assertEqual(got, ['94001', [0, HUODONG_ERR_NO_GIFT]])

    # -- logout banking ---------------------------------------------------
    def test_disconnect_banks_remainder(self):
        self.sess._huodong_on_enter(str(self.rid))
        self.save_gift({'day': 1, 'id': '1',
                        'logintime': int(time.time() * 1000) - 10000,
                        'minute': 60000})
        self.sess._huodong_on_disconnect()
        state = self.gift()
        self.assertLess(state['minute'], 60000)
        self.assertGreaterEqual(state['minute'], 49000)
        self.sess._huodong_on_enter(str(self.rid))
        state = self.gift()
        self.assertEqual(state['id'], '1')
        self.assertLess(state['minute'], 60000)

    # -- wire dispatch ------------------------------------------------------
    def test_wire_dispatch(self):
        self.sess.feed(bytes.fromhex('00000009060f494e49544b4559'))
        self.sess._huodong_on_enter(str(self.rid))
        out = self.sess.feed(frame(self.sess.cipher.encode(
            encode([CMD_HUODONG_ONLINE_INFO]))))
        self.assertEqual(frames(out)[0][0], '94000')
        out = self.sess.feed(frame(self.sess.cipher.encode(
            encode([CMD_HUODONG_ONLINE_REWARD]))))
        self.assertEqual(frames(out)[0][0], '94001')


if __name__ == '__main__':
    unittest.main()

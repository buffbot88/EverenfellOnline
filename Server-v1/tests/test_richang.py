"""Richang daily quest: 50201 creates one task_richang row per role and reuses it.

Evidence: TaskRiChangAction.getTaskRichangeInfo and
TaskRiChangServiceImpl.initRiChang (queues its own 50201 before the reply).
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode, encode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import (CMD_RICHANG_NOTIFY_LOOP,  # noqa: E402
                           MALL_ERR_YB_NO_ENOUGHT,
                           RICHANG_COST_TISHENG, RICHANG_MAX_LOOP,
                           RICHANG_MIN_LEVEL,
                           RICHANG_THICK_MAX, TASK_ERR_NOT_RICHANG,
                           TASK_ERR_RICHANG_THICK_MAX, Session, frame)

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..',
                           'reference', 'TonNgoKhong', 'server', 'config',
                           'game')
HAVE_REAL = os.path.isdir(REAL_CONFIG)

# Live-captured first frame from the original client (see
# tests/test_protocol.py); the fufei path below goes through dispatch.
INITKEY_FRAME = bytes.fromhex('00000009060f494e49544b4559')


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class RichangInfoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'r.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.cfg = GameConfig(str(REAL_CONFIG))

    def make_session(self, level):
        rid = self.store.create_character(
            'hero', 'fu1304', f'Wukong{level}', job='C', level=level)
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_task_richang=self.store.get_task_richang,
            save_task_richang=self.store.save_task_richang,
            delete_task_richang=self.store.delete_task_richang,
            config=self.cfg)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return rid, sess

    @staticmethod
    def frames(out):
        if isinstance(out, (bytes, bytearray)):
            return [decode(bytes(out)[4:])]
        return [decode(bytes(f)[4:]) for f in out]

    @staticmethod
    def quest_id(frame):
        # Reply is [quest VO, cost data, loop VO]; the VO's first field is the id.
        return frame[1][0][0]

    def test_first_call_creates_row(self):
        rid, sess = self.make_session(RICHANG_MIN_LEVEL)
        out = sess.richang_info()
        self.assertIsNotNone(out)
        frames = self.frames(out)
        self.assertTrue(all(f[0] == '50201' for f in frames))
        row = self.store.get_task_richang(rid)
        self.assertIsNotNone(row)
        self.assertEqual(self.quest_id(frames[-1]), row['id'])
        self.assertEqual(row['current_loop'], 1)
        self.assertEqual(row['task_state'], 0)

    def test_second_call_reuses_row(self):
        rid, sess = self.make_session(RICHANG_MIN_LEVEL)
        first = self.quest_id(self.frames(sess.richang_info())[-1])
        second = self.quest_id(self.frames(sess.richang_info())[-1])
        self.assertEqual(first, second)
        self.assertEqual(self.store.get_task_richang(rid)['id'], first)

    def test_below_min_level_returns_none(self):
        rid, sess = self.make_session(RICHANG_MIN_LEVEL - 1)
        self.assertIsNone(sess.richang_info())
        self.assertIsNone(self.store.get_task_richang(rid))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class RichangActionTest(unittest.TestCase):
    """50202/50204/50205/50206/50209 money, VIP and state gates."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'ra.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.rid = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56,
            tongqian=60000, lingshi=100, bind_lingshi=0)
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_vip=self.store.get_role_vip,
            save_role_state=self.store.update_character_state,
            get_task_richang=self.store.get_task_richang,
            save_task_richang=self.store.save_task_richang,
            delete_task_richang=self.store.delete_task_richang,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.sess.richang_info()  # creates the quest row

    def role(self):
        return dict(self.store.list_roles('hero', 'fu1304')[0])

    def reply(self, out):
        self.assertIsNotNone(out)
        frames = RichangInfoTest.frames(out)
        return frames[-1]

    def set_vip(self, level):
        self.store.save_role_vip(self.rid, vip_level=level)

    def high_difficulty_condition(self):
        table = self.cfg._richang_condition_assembly()[0]
        return next(c for c in table.values() if c['difficulty'] > 1)

    def test_decrease_without_row_is_silent(self):
        self.store.delete_task_richang(self.rid)
        self.assertIsNone(self.sess.richang_decrease())

    def test_decrease_short_yxb_returns_error(self):
        cond = self.high_difficulty_condition()
        row = self.store.get_task_richang(self.rid)
        self.store.save_task_richang(
            self.rid, condition_config_id=cond['id'], current_loop=1,
            task_state=0)
        self.store.update_character_state(self.rid, tongqian=0)
        self.assertEqual(self.reply(self.sess.richang_decrease()),
                         ['50202', [0, MALL_ERR_YB_NO_ENOUGHT]])

    def test_zhijie_short_yb_returns_error(self):
        self.store.update_character_state(self.rid, lingshi=0)
        self.assertEqual(self.reply(self.sess.richang_zhijie()),
                         ['50204', [0, MALL_ERR_YB_NO_ENOUGHT]])

    def test_complete_all_requires_vip(self):
        self.assertEqual(self.reply(self.sess.richang_complete_all()),
                         ['50205', [0, TASK_ERR_NOT_RICHANG]])

    def test_complete_all_with_vip_charges_50_yb(self):
        self.set_vip(1)
        self.assertEqual(self.reply(self.sess.richang_complete_all()),
                         ['50205', [1, 1]])
        self.assertEqual(self.role()['lingshi'], 50)
        row = self.store.get_task_richang(self.rid)
        self.assertEqual(row['fufei_state'], 1)

    def test_complete_best_short_yb_returns_error(self):
        self.set_vip(1)
        self.store.update_character_state(self.rid, lingshi=99)
        self.assertEqual(self.reply(self.sess.richang_complete_best()),
                         ['50206', [0, MALL_ERR_YB_NO_ENOUGHT]])
        self.assertEqual(self.role()['lingshi'], 99)

    def test_notify_loop_without_fufei_is_silent(self):
        self.assertIsNone(self.sess.richang_notify_loop())

    def test_direct_finish_on_final_loop_emits_stop(self):
        # Loop 20 paid through 50204 settles the quest and pushes the
        # 50211 stop frame with the loop reward (no 50210 follows).
        self.set_reward(thick_is_max=False)
        self.store.save_task_richang(
            self.rid, current_loop=RICHANG_MAX_LOOP, task_state=1,
            fufei_state=0)
        frames = RichangInfoTest.frames(self.sess.richang_zhijie())
        self.assertEqual([f[0] for f in frames],
                         ['50207', '50211', '50204'])
        row = self.store.get_task_richang(self.rid)
        self.assertEqual(row['task_state'], 2)

    def test_notify_loop_fufei_pays_and_advances(self):
        table = self.cfg._richang_reward_assembly()[0]
        reward = next(r for r in table.values()
                      if r['jb'] > 0 and r['thick'] != RICHANG_THICK_MAX)
        self.store.save_task_richang(
            self.rid, reward_config_id=reward['id'], current_loop=1,
            task_state=1, fufei_state=1)
        before = self.role()['tongqian']
        self.sess.feed(INITKEY_FRAME)
        out = self.sess.feed(frame(self.sess.cipher.encode(
            encode([CMD_RICHANG_NOTIFY_LOOP, None]))))
        frames = [decode(bytes(f)[4:]) for f in out]
        self.assertEqual([f[0] for f in frames], ['50207', '50210'])
        row = self.store.get_task_richang(self.rid)
        self.assertEqual(row['current_loop'], 2)
        self.assertEqual(row['task_state'], 0)
        self.assertEqual(self.role()['tongqian'], before + reward['jb'])

    def set_reward(self, thick_is_max):
        table = self.cfg._richang_reward_assembly()[0]
        reward = next(r for r in table.values()
                      if (r['thick'] == RICHANG_THICK_MAX) == thick_is_max)
        self.store.save_task_richang(
            self.rid, reward_config_id=reward['id'], current_loop=1,
            task_state=0, fufei_state=0)

    def test_increase_short_yxb_returns_error(self):
        self.set_reward(thick_is_max=False)
        self.store.update_character_state(self.rid, tongqian=0)
        self.assertEqual(self.reply(self.sess.richang_increase()),
                         ['50203', [0, MALL_ERR_YB_NO_ENOUGHT]])

    def test_increase_rejects_max_thick_reward(self):
        self.set_reward(thick_is_max=True)
        self.assertEqual(self.reply(self.sess.richang_increase()),
                         ['50203', [0, TASK_ERR_RICHANG_THICK_MAX]])
        self.assertEqual(self.role()['tongqian'], 60000)

    def test_increase_charges_50000_yxb(self):
        self.set_reward(thick_is_max=False)
        reply = self.reply(self.sess.richang_increase())
        self.assertEqual(reply[0], '50203')
        self.assertEqual(reply[1][0], 1)
        self.assertEqual(reply[1][1], RICHANG_THICK_MAX)
        self.assertEqual(self.role()['tongqian'], 60000 - RICHANG_COST_TISHENG)

    def test_kill_progress_emits_50208_and_records_kill(self):
        table = self.cfg._richang_condition_assembly()[0]
        cond = next(c for c in table.values() if c['kill_monsters'])
        monster = next(iter(cond['kill_monsters']))
        self.store.save_task_richang(
            self.rid, condition_config_id=cond['id'], task_condition='',
            task_state=0, fufei_state=0, current_loop=1)
        role = self.role()
        first = RichangInfoTest.frames(
            self.sess.richang_kill_progress(role, monster))[0]
        self.assertEqual(first[0], '50208')
        self.assertEqual(first[1][1], monster)
        self.assertEqual(first[1][2], 1)
        row = self.store.get_task_richang(self.rid)
        self.assertNotEqual(row['task_condition'], '')

    def test_pay_settles_row_and_grants_reward_jb(self):
        table = self.cfg._richang_reward_assembly()[0]
        reward = next(r for r in table.values()
                      if r['jb'] > 0 and r['thick'] != RICHANG_THICK_MAX)
        self.store.save_task_richang(
            self.rid, reward_config_id=reward['id'], current_loop=1,
            task_state=1, fufei_state=0)
        before = self.role()['tongqian']
        result = self.sess._richang_pay(self.role(), self.rid, False)
        self.assertIsNotNone(result)
        self.assertEqual(self.store.get_task_richang(self.rid)['task_state'], 2)
        self.assertEqual(self.role()['tongqian'], before + reward['jb'])


if __name__ == '__main__':
    unittest.main()

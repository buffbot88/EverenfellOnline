"""Guild-task quests (GonghuitaskAction/GonghuitaskServiceImpl).

Evidence: action javap (7 inbound 81000-81005 + 81008; pushes
81006/81007/81009/81010), impl bytecode (guild gate, 81101-81103,
GeneralErrorCode 1003 YB-short, special-loop thick 11/12, banggong via
addRoleGongxian), GongHuiTaskConstants clinit, and the
GongHuiRenWu(.JiangLi/EWaiJiangLi).jat tables.

Every path runs through the real handlers and the real SQLite store,
mirroring the richang lifecycle with the guild-membership gate: no
member row answers silence on every command, exactly like Java's null
GuildWrapper branch.
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
from game.protocol import Session, frame  # noqa: E402
from game.protocol import (CMD_GONGHUI_NOTIFY_LOOP,  # noqa: E402
                            GONGHUI_MAX_LOOP, GONGHUI_MIN_LEVEL,
                            GONGHUI_THICK_MAX)

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..',
                           'reference', 'TonNgoKhong', 'server', 'config',
                           'game')
HAVE_REAL = os.path.isdir(REAL_CONFIG)


def frames(out):
    if isinstance(out, (bytes, bytearray)):
        return [decode(bytes(out)[4:])]
    return [decode(bytes(f)[4:]) for f in out]


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class GonghuiInfoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'g.db'))
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
            get_task_gonghui=self.store.get_task_gonghui,
            save_task_gonghui=self.store.save_task_gonghui,
            delete_task_gonghui=self.store.delete_task_gonghui,
            get_guild_id=self.store.get_guild_id,
            save_guild_member=self.store.save_guild_member,
            add_guild_gongxian=self.store.add_guild_gongxian,
            config=self.cfg)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return rid, sess

    def test_no_guild_is_silent(self):
        rid, sess = self.make_session(GONGHUI_MIN_LEVEL)
        self.assertIsNone(sess.gonghui_info())
        self.assertIsNone(self.store.get_task_gonghui(rid))

    def test_guild_member_creates_row(self):
        rid, sess = self.make_session(GONGHUI_MIN_LEVEL)
        self.store.save_guild_member(rid, 'guild001')
        out = sess.gonghui_info()
        self.assertIsNotNone(out)
        got = frames(out)
        # initRiChang queues its own 81000 before the reply is built.
        self.assertTrue(all(f[0] == '81000' for f in got))
        row = self.store.get_task_gonghui(rid)
        self.assertIsNotNone(row)
        self.assertEqual(got[-1][1][0][0], row['id'])
        self.assertEqual(row['current_loop'], 1)
        self.assertEqual(row['task_state'], 0)

    def test_second_call_reuses_row(self):
        rid, sess = self.make_session(GONGHUI_MIN_LEVEL)
        self.store.save_guild_member(rid, 'guild001')
        first = frames(sess.gonghui_info())[-1][1][0][0]
        second = frames(sess.gonghui_info())[-1][1][0][0]
        self.assertEqual(first, second)
        self.assertEqual(self.store.get_task_gonghui(rid)['id'], first)

    def test_below_min_level_returns_none(self):
        rid, sess = self.make_session(GONGHUI_MIN_LEVEL - 1)
        self.store.save_guild_member(rid, 'guild001')
        self.assertIsNone(sess.gonghui_info())
        self.assertIsNone(self.store.get_task_gonghui(rid))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class GonghuiActionTest(unittest.TestCase):
    """81001-81005/81008 money, VIP, guild and state gates."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'ga.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.rid = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56,
            tongqian=60000, lingshi=100, bind_lingshi=0)
        self.store.save_guild_member(self.rid, 'guild001')
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_vip=self.store.get_role_vip,
            save_role_state=self.store.update_character_state,
            get_task_gonghui=self.store.get_task_gonghui,
            save_task_gonghui=self.store.save_task_gonghui,
            delete_task_gonghui=self.store.delete_task_gonghui,
            get_guild_id=self.store.get_guild_id,
            save_guild_member=self.store.save_guild_member,
            add_guild_gongxian=self.store.add_guild_gongxian,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'
        self.sess.gonghui_info()  # creates the quest row

    def role(self):
        return dict(self.store.list_roles('hero', 'fu1304')[0])

    def reply(self, out):
        self.assertIsNotNone(out)
        return frames(out)[-1]

    def set_vip(self, level):
        self.store.save_role_vip(self.rid, vip_level=level)

    def test_no_guild_silences_every_command(self):
        self.store.db.execute('DELETE FROM guild_member WHERE role_id=?',
                              (str(self.rid),))
        self.store.db.commit()
        self.assertIsNone(self.sess.gonghui_decrease())
        self.assertIsNone(self.sess.gonghui_increase())
        self.assertIsNone(self.sess.gonghui_zhijie())
        self.assertIsNone(self.sess.gonghui_complete_all())
        self.assertIsNone(self.sess.gonghui_complete_best())
        self.assertIsNone(self.sess.gonghui_notify_loop())
        self.assertEqual(self.sess.gonghui_kill_progress(self.role(), 'x'),
                         [])

    def test_decrease_without_row_is_silent(self):
        self.store.delete_task_gonghui(self.rid)
        self.assertIsNone(self.sess.gonghui_decrease())

    def test_decrease_short_yxb_returns_1003(self):
        table = self.cfg._gonghui_condition_assembly()[0]
        cond = next(c for c in table.values() if c['difficulty'] > 1)
        self.store.save_task_gonghui(
            self.rid, condition_config_id=cond['id'], current_loop=1,
            task_state=0)
        self.store.update_character_state(self.rid, tongqian=0)
        self.assertEqual(self.reply(self.sess.gonghui_decrease()),
                         ['81001', [0, 1003]])

    def test_decrease_rejects_min_difficulty(self):
        table = self.cfg._gonghui_condition_assembly()[0]
        cond = next(c for c in table.values() if c['difficulty'] == 1)
        self.store.save_task_gonghui(
            self.rid, condition_config_id=cond['id'], current_loop=1,
            task_state=0)
        self.assertEqual(self.reply(self.sess.gonghui_decrease()),
                         ['81001', [0, 81102]])
        self.assertEqual(self.role()['tongqian'], 60000)

    def test_decrease_done_loop_returns_81101(self):
        self.store.save_task_gonghui(
            self.rid, current_loop=GONGHUI_MAX_LOOP, task_state=2)
        self.assertEqual(self.reply(self.sess.gonghui_decrease()),
                         ['81001', [0, 81101]])

    def test_zhijie_short_yb_returns_1003(self):
        self.store.update_character_state(self.rid, lingshi=0)
        self.assertEqual(self.reply(self.sess.gonghui_zhijie()),
                         ['81003', [0, 1003]])

    def test_complete_all_requires_vip(self):
        self.assertEqual(self.reply(self.sess.gonghui_complete_all()),
                         ['81004', [0, 480073]])

    def test_complete_all_with_vip_charges_50_yb(self):
        self.set_vip(1)
        self.assertEqual(self.reply(self.sess.gonghui_complete_all()),
                         ['81004', [1, 1]])
        self.assertEqual(self.role()['lingshi'], 50)
        row = self.store.get_task_gonghui(self.rid)
        self.assertEqual(row['fufei_state'], 1)

    def test_complete_best_short_yb_returns_1003(self):
        self.set_vip(1)
        self.store.update_character_state(self.rid, lingshi=99)
        self.assertEqual(self.reply(self.sess.gonghui_complete_best()),
                         ['81005', [0, 1003]])
        self.assertEqual(self.role()['lingshi'], 99)

    def test_notify_loop_without_fufei_is_silent(self):
        self.assertIsNone(self.sess.gonghui_notify_loop())

    def test_direct_finish_on_final_loop_emits_stop(self):
        # Loop 20 paid through 81003 settles the quest and pushes the
        # 81010 stop frame with the loop reward (no 81009 follows).
        self.store.save_task_gonghui(
            self.rid, current_loop=GONGHUI_MAX_LOOP, task_state=1,
            fufei_state=0)
        got = frames(self.sess.gonghui_zhijie())
        self.assertEqual([f[0] for f in got],
                         ['81006', '81010', '81003'])
        row = self.store.get_task_gonghui(self.rid)
        self.assertEqual(row['task_state'], 2)

    def test_notify_loop_fufei_pays_and_advances(self):
        table = self.cfg._gonghui_reward_assembly()[0]
        reward = next(r for r in table.values()
                      if r['jb'] > 0 and r['thick'] != GONGHUI_THICK_MAX
                      and not r['reward_items'])
        self.store.save_task_gonghui(
            self.rid, reward_config_id=reward['id'], current_loop=1,
            task_state=1, fufei_state=1)
        before = self.role()['tongqian']
        got = frames(self.sess.gonghui_notify_loop())
        self.assertEqual([f[0] for f in got], ['81006', '81009'])
        row = self.store.get_task_gonghui(self.rid)
        self.assertEqual(row['current_loop'], 2)
        self.assertEqual(row['task_state'], 0)
        self.assertEqual(self.role()['tongqian'], before + reward['jb'])

    def test_increase_short_yxb_returns_1003(self):
        table = self.cfg._gonghui_reward_assembly()[0]
        reward = next(r for r in table.values()
                      if r['thick'] != GONGHUI_THICK_MAX)
        self.store.save_task_gonghui(
            self.rid, reward_config_id=reward['id'], current_loop=1,
            task_state=0, fufei_state=0)
        self.store.update_character_state(self.rid, tongqian=0)
        self.assertEqual(self.reply(self.sess.gonghui_increase()),
                         ['81002', [0, 1003]])

    def test_increase_rejects_max_thick_reward(self):
        table = self.cfg._gonghui_reward_assembly()[0]
        reward = next(r for r in table.values()
                      if r['thick'] == GONGHUI_THICK_MAX)
        self.store.save_task_gonghui(
            self.rid, reward_config_id=reward['id'], current_loop=1,
            task_state=0, fufei_state=0)
        self.assertEqual(self.reply(self.sess.gonghui_increase()),
                         ['81002', [0, 81103]])
        self.assertEqual(self.role()['tongqian'], 60000)

    def test_increase_charges_50000_yxb(self):
        table = self.cfg._gonghui_reward_assembly()[0]
        reward = next(r for r in table.values()
                      if r['thick'] != GONGHUI_THICK_MAX)
        self.store.save_task_gonghui(
            self.rid, reward_config_id=reward['id'], current_loop=1,
            task_state=0, fufei_state=0)
        reply = self.reply(self.sess.gonghui_increase())
        self.assertEqual(reply[0], '81002')
        self.assertEqual(reply[1][0], 1)
        self.assertEqual(reply[1][1], GONGHUI_THICK_MAX)
        self.assertEqual(self.role()['tongqian'], 60000 - 50000)

    def test_kill_progress_emits_81007_and_records_kill(self):
        table = self.cfg._gonghui_condition_assembly()[0]
        cond = next(c for c in table.values() if c['kill_monsters'])
        monster = next(iter(cond['kill_monsters']))
        self.store.save_task_gonghui(
            self.rid, condition_config_id=cond['id'], task_condition='',
            task_state=0, fufei_state=0, current_loop=1)
        role = self.role()
        first = frames(self.sess.gonghui_kill_progress(role, monster))[0]
        self.assertEqual(first[0], '81007')
        self.assertEqual(first[1][1], monster)
        self.assertEqual(first[1][2], 1)
        row = self.store.get_task_gonghui(self.rid)
        self.assertNotEqual(row['task_condition'], '')

    def test_kill_completion_pays_81006_and_advances_81009(self):
        table = self.cfg._gonghui_condition_assembly()[0]
        cond = next(c for c in table.values() if c['kill_monsters'])
        monster = next(iter(cond['kill_monsters']))
        need = cond['kill_monsters'][monster]['count']
        rewards = self.cfg._gonghui_reward_assembly()[0]
        reward = next(r for r in rewards.values()
                      if r['banggong'] > 0 and not r['reward_items'])
        kills = {monster: need - 1}
        cond_str = ';'.join(f'{mid};{n}' for mid, n in kills.items())
        self.store.save_task_gonghui(
            self.rid, condition_config_id=cond['id'],
            reward_config_id=reward['id'], task_condition=cond_str,
            task_state=0, fufei_state=0, current_loop=1)
        before = self.store.db.execute(
            'SELECT gongxian FROM guild_member WHERE role_id=?',
            (str(self.rid),)).fetchone()['gongxian']
        got = frames(self.sess.gonghui_kill_progress(self.role(), monster))
        self.assertEqual([f[0] for f in got], ['81007', '81006', '81009'])
        after = self.store.db.execute(
            'SELECT gongxian FROM guild_member WHERE role_id=?',
            (str(self.rid),)).fetchone()['gongxian']
        self.assertEqual(after, before + reward['banggong'])
        row = self.store.get_task_gonghui(self.rid)
        self.assertEqual(row['current_loop'], 2)
        self.assertEqual(row['task_state'], 0)

    def test_settled_final_loop_pays_nothing(self):
        table = self.cfg._gonghui_reward_assembly()[0]
        reward = next(r for r in table.values() if r['jb'] > 0)
        self.store.save_task_gonghui(
            self.rid, reward_config_id=reward['id'],
            current_loop=GONGHUI_MAX_LOOP, task_state=2, fufei_state=0)
        self.assertIsNone(self.sess._gonghui_pay(self.role(), self.rid,
                                                 False))

    def test_loop_14_stalls_without_thick_12_rewards(self):
        # Loop 14 finished at state 2 draws thick 12, but the shipped
        # tables hold no thick-12 reward in any bucket, so Java's
        # receiveTask returns null and the quest stays put. Pinned as
        # observed jar behavior, not invented.
        self.store.save_task_gonghui(
            self.rid, current_loop=14, task_state=2, fufei_state=0)
        self.assertIsNone(
            self.sess._gonghui_receive(self.role(), self.rid, False))
        row = self.store.get_task_gonghui(self.rid)
        self.assertEqual((row['current_loop'], row['task_state']),
                         (14, 2))

    def test_notify_loop_dispatches_81008_through_the_wire(self):
        # The 81008 route itself: fufei quest paid through a real frame.
        table = self.cfg._gonghui_reward_assembly()[0]
        reward = next(r for r in table.values()
                      if r['jb'] > 0 and r['thick'] != GONGHUI_THICK_MAX
                      and not r['reward_items'])
        self.store.save_task_gonghui(
            self.rid, reward_config_id=reward['id'], current_loop=1,
            task_state=1, fufei_state=1)
        self.sess.feed(bytes.fromhex('00000009060f494e49544b4559'))
        out = self.sess.feed(frame(self.sess.cipher.encode(
            encode([CMD_GONGHUI_NOTIFY_LOOP, None]))))
        got = frames(out)
        self.assertEqual([f[0] for f in got], ['81006', '81009'])
        self.assertEqual(self.store.get_task_gonghui(self.rid)
                         ['current_loop'], 2)

    def test_loop_19_draws_difficulty_11(self):
        # The finished second-to-last loop re-rolls from the thick-11
        # pool; level 35 sits in buckets carrying thick-11 rewards.
        self.store.update_character_state(self.rid, level=35)
        self.store.save_task_gonghui(
            self.rid, current_loop=GONGHUI_MAX_LOOP - 1, task_state=2,
            fufei_state=0)
        nxt = self.sess._gonghui_receive(self.role(), self.rid, False)
        self.assertIsNotNone(nxt)
        row = self.store.get_task_gonghui(self.rid)
        cond = self.cfg.gonghui_condition(row['condition_config_id'])
        self.assertEqual(cond['difficulty'], 11)
        self.assertEqual(row['current_loop'], GONGHUI_MAX_LOOP)


if __name__ == '__main__':
    unittest.main()

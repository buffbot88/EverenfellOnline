"""Taofa quests: TaskTaoFaConfig/interval bytecode plus the 50101/50103 routes.

Evidence: TaskTaoFaServiceImpl (getRoleTaskTaofas/tunshiTaoFaTask/
recevieTaskTaofa/changeTaskTaofaMonster/payTaskTaofa/reward),
TaskTaoFaAction (50101/50103 only), TaskCommands, TaskTaoFaConstants,
TaskTaoFaConfigExportServiceImpl.createTaskTaofaConfig, TaoFaPropType
(skill 3, consumePrior false), GetTaskOutPut/CreateTaskOutputWrapper.
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode  # noqa: E402
from game.config import (TAOFA_MAX_TUNSHI, TAOFA_MAX_USE,  # noqa: E402
                         TAOFA_RECEIVE_MAX, GameConfig, config_float,
                         parse_taofa_items, parse_taofa_monster)
from game.protocol import Session  # noqa: E402

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..',
                           'reference', 'TonNgoKhong', 'server', 'config',
                           'game')
HAVE_REAL = os.path.isdir(REAL_CONFIG)


class TaofaParseTest(unittest.TestCase):
    def test_monster_vo_forms(self):
        self.assertIsNone(parse_taofa_monster(''))
        self.assertEqual(parse_taofa_monster('#D030001:20'),
                         {'monster_id': 'D030001', 'count': 20,
                          'auto_attack': True, 'show_name': None})
        self.assertEqual(parse_taofa_monster('name_D01:3'),
                         {'monster_id': 'D01', 'count': 3,
                          'auto_attack': False, 'show_name': 'name'})
        # Only the first ';' segment counts (getConfigMonsterVo).
        vo = parse_taofa_monster('D01:1;D02:2')
        self.assertEqual((vo['monster_id'], vo['count']), ('D01', 1))
        self.assertIsNone(parse_taofa_monster('D01;x'))

    def test_item_order_split(self):
        goods, zubao = parse_taofa_items('taofalan:1:1', 1)
        self.assertEqual(goods, [{'goods_id': 'taofalan', 'count': 1,
                                  'bind': 1, 'expire': 0}])
        self.assertEqual(zubao, [])
        goods, zubao = parse_taofa_items('@zb001;taofazi:2:1', 1)
        self.assertEqual(zubao, ['@zb001'])
        self.assertEqual(goods[0]['goods_id'], 'taofazi')
        self.assertEqual(parse_taofa_items('', 1), ([], []))

    def test_float_cells(self):
        self.assertEqual(config_float('0.5'), 0.5)
        self.assertEqual(config_float(''), 0.0)
        self.assertEqual(config_float(None), 0.0)

    def test_constants(self):
        self.assertEqual((TAOFA_MAX_TUNSHI, TAOFA_MAX_USE,
                          TAOFA_RECEIVE_MAX), (5, 10, 20))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class TaofaConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = GameConfig(str(REAL_CONFIG))

    def test_first_row_full_parse(self):
        cfg = self.cfg.taofa_config('TF02001')
        self.assertEqual((cfg['min'], cfg['max'], cfg['color'],
                          cfg['query_id']),
                         (21, 30, 0, '21_30_0'))
        self.assertTrue(cfg['swallow'])
        self.assertEqual(cfg['merge'], 0.5)
        self.assertEqual(cfg['kill_monster'],
                         {'monster_id': 'D030001', 'count': 20,
                          'auto_attack': True, 'show_name': None})
        self.assertEqual((cfg['exp'], cfg['jb'], cfg['bind_yb'],
                          cfg['prestige'], cfg['zhenqi']),
                         (120000, 20000, 0, 0, 0))
        self.assertEqual(cfg['goods'], [])
        self.assertIsNone(cfg['show_items'])
        self.assertIsNone(cfg['target'])
        self.assertFalse(cfg['call_permit'])
        self.assertIsNone(cfg['call_goods'])

    def test_goods_row_parse(self):
        cfg = self.cfg.taofa_config('TF07003')
        self.assertEqual(cfg['goods'], [{'goods_id': 'taofalan', 'count': 1,
                                         'bind': 1, 'expire': 0}])
        self.assertEqual(len(cfg['show_items']), 1)
        self.assertEqual(cfg['show_items'][0]['goods_id'], 'taofalan')

    def test_interval_key_is_level_color(self):
        self.assertEqual([c['id'] for c in self.cfg.taofa_interval(56, 2)],
                         ['TF07003'])
        self.assertEqual(self.cfg.taofa_interval(56, 4), [])
        self.assertIsNone(self.cfg.taofa_config('nope'))

    def test_vip_helpers(self):
        self.assertEqual(self.cfg.vip_tunshi_times(1), 7)
        self.assertEqual(self.cfg.vip_taofa_times(4), 2)
        self.assertFalse(self.cfg.vip_onekeytask(0))
        self.assertTrue(self.cfg.vip_onekeytask(1))

    def test_goods_rarelevel(self):
        self.assertEqual(self.cfg.goods_rarelevel('xtf003'), 2)
        self.assertEqual(self.cfg.goods_rarelevel('nope'), 0)


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class TaofaFrameTest(unittest.TestCase):
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
            get_role_vip=self.store.get_role_vip,
            save_role_state=self.store.update_character_state,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            save_role_bag_state=self.store.save_role_bag_state,
            get_role_bag_slot_by_bag_id=(
                self.store.get_role_bag_slot_by_bag_id),
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            get_task_taofa=self.store.get_task_taofa,
            get_task_taofas=self.store.get_task_taofas,
            insert_task_taofa=self.store.insert_task_taofa,
            update_task_taofa=self.store.update_task_taofa,
            delete_task_taofa=self.store.delete_task_taofa,
            get_task_taofa_state=self.store.get_task_taofa_state,
            save_task_taofa_state=self.store.save_task_taofa_state,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'

    def frames(self, out):
        self.assertIsNotNone(out)
        if isinstance(out, (bytes, bytearray)):
            return [decode(bytes(out)[4:])]
        return [decode(bytes(f)[4:]) for f in out]

    def role(self):
        return self.store.list_roles('hero', 'fu1304')[0]

    def give_scroll(self, goods_id='xtf003'):
        taken = [s.get('slot_num') for s in
                 self.store.get_role_bag_slots(self.role_id, 1, 150)]
        slot = max(taken or [0]) + 1
        return self.store.insert_role_bag_slot(
            self.role_id, {'slot_num': slot, 'goods_id': goods_id,
                           'count': 1, 'bind': 0, 'expire_time': None,
                           'rare_level': 0, 'item_level': 0,
                           'attributes': None})

    def test_list_empty(self):
        (out,) = self.frames(self.sess.taofa_list())
        self.assertEqual(out[0], '50101')
        infos, counts, maxed = out[1]
        self.assertIsNone(infos)
        self.assertEqual(counts, [0, 0, 0])
        self.assertEqual(maxed, [5, 10, 10])
        state = self.store.get_task_taofa_state(self.role_id)
        self.assertEqual(state['hebing_count'], 0)

    def test_receive_scroll(self):
        guid = self.give_scroll('xtf003')
        got = self.frames(self.sess.prop_use(guid))
        self.assertEqual([f[0] for f in got], ['50102', '30301'])
        _cmd, (ok, info) = got[0]
        self.assertEqual(ok, 1)
        # The 18-field quest VO for TF07003 (only 56_2 row: no roll).
        self.assertEqual(info[1], 'TF07003')
        self.assertEqual(info[3], 0)
        self.assertEqual(info[4], [None, ['D060010', 1, 0, True, None]])
        self.assertEqual(info[5], [165000, 660000, 0, 0, 0, None, 0,
                                   [['taofalan', 1]]])
        self.assertEqual(info[6], 2)
        self.assertIsNone(info[7])
        self.assertEqual(info[8:12], [1, '『เรื่องราว』พญามังกรเอ๋ากว่าง',
                                      60, 1.0])
        self.assertEqual(info[12:16], [2, True, 0.5, 'longgong'])
        self.assertIsNone(info[16])
        self.assertIsNone(info[17])
        self.assertEqual(got[1], ['30301', [1, guid]])
        # Scroll burned, use counted, quest stored.
        self.assertIsNone(
            self.store.get_role_bag_slot_by_bag_id(self.role_id, guid))
        state = self.store.get_task_taofa_state(self.role_id)
        self.assertEqual(state['hebing_count'], 1)
        rows = self.store.get_task_taofas(self.role_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['task_id'], 'TF07003')

    def test_list_after_receive(self):
        self.give_scroll('xtf003')
        self.sess.prop_use(self.give_scroll('xtf003'))
        (out,) = self.frames(self.sess.taofa_list())
        infos, counts, maxed = out[1]
        self.assertEqual(len(infos), 1)
        self.assertEqual(counts, [0, 0, 1])
        self.assertEqual(maxed, [5, 10, 10])

    def test_receive_unknown_guid_silent(self):
        # Unknown bag rows never reach the hook (Java's null path).
        self.assertIsNone(self.sess.prop_use('ghost-guid'))

    def test_receive_unknown_goods_errors(self):
        # An item whose goods row is gone hits GOODS_NO_EXIST directly.
        err, info = self.sess._taofa_receive(
            self.role(), self.role_id,
            {'goods_id': 'no-such-goods', 'bag_id': 'g1'})
        self.assertEqual((err, info), (480040, None))

    def test_receive_bad_interval_errors(self):
        # xtf005 (rare 4) has no color-4 taofa rows: CONFIG_ERROR.
        guid = self.give_scroll('xtf005')
        (out,) = self.frames(self.sess.prop_use(guid))
        self.assertEqual(out, ['30301', [0, 480048]])

    def test_receive_use_capped(self):
        self.store.save_task_taofa_state(
            self.role_id, tunshi_count=0, hebing_count=10, finish_count=0,
            total_count=0, create_time=int(time.time() * 1000))
        guid = self.give_scroll('xtf003')
        (out,) = self.frames(self.sess.prop_use(guid))
        self.assertEqual(out, ['30301', [0, 480041]])

    def test_receive_board_capped(self):
        now = int(time.time() * 1000)
        for num in range(20):
            self.store.insert_task_taofa(
                self.role_id, {'id': f'q{num:02d}', 'task_id': 'TF07003',
                               'master_count': 0, 'task_state': 0,
                               'ts_state': 0, 'ts_reward_jb': 0,
                               'ts_reward_exp': 0, 'ts_reward_zhenqi': 0,
                               'ts_reward_bing_yb': 0,
                               'ts_reward_prestige': 0, 'update_time': now,
                               'create_time': now})
        guid = self.give_scroll('xtf003')
        (out,) = self.frames(self.sess.prop_use(guid))
        self.assertEqual(out, ['30301', [0, 480042]])

    def _insert_quest(self, uid, task_id):
        now = int(time.time() * 1000)
        self.store.insert_task_taofa(
            self.role_id, {'id': uid, 'task_id': task_id, 'master_count': 0,
                           'task_state': 0, 'ts_state': 0, 'ts_reward_jb': 0,
                           'ts_reward_exp': 0, 'ts_reward_zhenqi': 0,
                           'ts_reward_bing_yb': 0, 'ts_reward_prestige': 0,
                           'update_time': now, 'create_time': now})

    def test_tunshi_merges(self):
        self._insert_quest('keeper', 'TF07003')
        self._insert_quest('eaten', 'TF02001')
        (out,) = self.frames(self.sess.taofa_tunshi(['keeper', 'eaten']))
        self.assertEqual(out[0], '50103')
        ok, (info, gone) = out[1]
        self.assertEqual((ok, gone), (1, 'eaten'))
        self.assertEqual(info[1], 'TF07003')
        # int((0 + base) * 0.5) lands in the keeper's ts rewards.
        self.assertEqual(info[5][:5], [165000 + 82500, 660000 + 330000,
                                       0, 0, 0])
        self.assertEqual(info[11], 1.5)
        keeper = self.store.get_task_taofa(self.role_id, 'keeper')
        self.assertEqual(keeper['ts_state'], 1)
        self.assertEqual(keeper['ts_reward_exp'], 330000)
        self.assertEqual(keeper['ts_reward_jb'], 82500)
        self.assertIsNone(self.store.get_task_taofa(self.role_id, 'eaten'))
        state = self.store.get_task_taofa_state(self.role_id)
        self.assertEqual(state['tunshi_count'], 1)

    def test_tunshi_missing(self):
        self._insert_quest('keeper', 'TF07003')
        (out,) = self.frames(self.sess.taofa_tunshi(['keeper', 'ghost']))
        self.assertEqual(out, ['50103', [0, 480044]])

    def test_tunshi_capped(self):
        self._insert_quest('keeper', 'TF07003')
        self._insert_quest('eaten', 'TF02001')
        self.store.save_task_taofa_state(
            self.role_id, tunshi_count=5, hebing_count=0, finish_count=0,
            total_count=0, create_time=int(time.time() * 1000))
        (out,) = self.frames(self.sess.taofa_tunshi(['keeper', 'eaten']))
        self.assertEqual(out, ['50103', [0, 480045]])

    def test_tunshi_bad_args_silent(self):
        self.assertIsNone(self.sess.taofa_tunshi([]))
        self.assertIsNone(self.sess.taofa_tunshi(None))

    def test_kill_progress_reports(self):
        self._insert_quest('q1', 'TF02001')
        (out,) = self.frames(
            self.sess.taofa_kill_progress(self.role(), 'D030001'))
        self.assertEqual(out, ['50104', ['q1', 'D030001', 1]])
        row = self.store.get_task_taofa(self.role_id, 'q1')
        self.assertEqual(row['master_count'], 1)
        self.assertEqual(row['task_state'], 0)

    def test_kill_completion_pays(self):
        self._insert_quest('q1', 'TF07003')
        before_exp = self.role()['exp'] or 0
        before_yxb = self.role()['tongqian'] or 0
        got = self.frames(
            self.sess.taofa_kill_progress(self.role(), 'D060010'))
        self.assertEqual([f[0] for f in got], ['50104', '50105'])
        self.assertEqual(got[0][1], ['q1', 'D060010', 1])
        # 50105 carries base config values, not ts-augmented ones.
        self.assertEqual(got[1][1], ['TF07003', [['taofalan', 1]],
                                     660000, 165000, 0, 0, 0])
        self.assertIsNone(self.store.get_task_taofa(self.role_id, 'q1'))
        self.assertEqual(self.role()['exp'], before_exp + 660000)
        self.assertEqual(self.role()['tongqian'], before_yxb + 165000)
        state = self.store.get_task_taofa_state(self.role_id)
        self.assertEqual(state['finish_count'], 1)
        slots = self.store.get_role_bag_slots(self.role_id, 1, 150)
        granted = [s for s in slots if s['goods_id'] == 'taofalan']
        self.assertEqual(sum(s['count'] for s in granted), 1)

    def test_kill_wrong_monster_silent(self):
        self._insert_quest('q1', 'TF07003')
        self.assertEqual(
            self.sess.taofa_kill_progress(self.role(), 'D060011'), [])

    def test_kill_highest_task_id_wins(self):
        # TF03004 and TF04004 share monster B200002; the comparator sorts
        # task ids descending, so the TF04004 quest takes the kill.
        self._insert_quest('qa', 'TF03004')
        self._insert_quest('qb', 'TF04004')
        got = self.frames(
            self.sess.taofa_kill_progress(self.role(), 'B200002'))
        # Both quests need one B200002 kill; qb wins and completes, so a
        # 50105 pay push follows its 50104 progress frame.
        self.assertEqual([f[0] for f in got], ['50104', '50105'])
        self.assertEqual(got[0][1], ['qb', 'B200002', 1])
        self.assertEqual(got[1][1][0], 'TF04004')
        self.assertIsNone(self.store.get_task_taofa(self.role_id, 'qb'))
        self.assertEqual(
            self.store.get_task_taofa(self.role_id, 'qa')['master_count'], 0)


if __name__ == '__main__':
    unittest.main()

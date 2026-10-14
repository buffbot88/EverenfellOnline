"""Command 50000 getRunMainTask: TaskMainServiceImpl.getRunTaskMainInfo.

Evidence: jar bytecode (TaskMainAction.getRunMainTask, getRunTaskMainInfo,
initFirstTaskMain/createTaskMain, getTaskMainWrapper/getConditionOutputData/
convertMonsterVo2Array, getTaskRecevieState/taskMainIsFinished/isPayTask,
TaskDataUtil kill strings, TaskMainConfigExportServiceImpl incl.
getConfigMonsterMap, goods cells) plus ZhuXianRenWu.jat (444 rows, first
c001001). No 50000 capture exists, so expectations are the bytecode shape
filled with real config, never invented numbers.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode  # noqa: E402
from game.config import (GameConfig, parse_task_goods,  # noqa: E402
                         parse_task_monsters)
from game.protocol import Session  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2]
               / 'reference' / 'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config' / 'ZhuXianRenWu.jat').is_file()


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class TaskMainConfigTest(unittest.TestCase):
    def setUp(self):
        self.cfg = GameConfig(str(REAL_CONFIG))

    def test_first_task_and_head_chain(self):
        self.assertEqual(self.cfg.task_main_first_id(), 'c001001')
        head = self.cfg.task_main('c001001')
        self.assertEqual(head['next_task_id'], 'c001002')
        self.assertEqual(head['recevie_level'], 1)
        self.assertEqual(head['complete_npc'], 'N020001')
        self.assertIsNone(head['complete_items'])
        self.assertIsNone(head['complete_monsters'])

    def test_kill_cell_parses(self):
        monsters = self.cfg.task_main('c001004')['complete_monsters']
        self.assertEqual(monsters, {
            'D010006': {'monster_id': 'D010006', 'count': 1,
                        'auto_attack': True, 'show_name': None}})

    def test_unknown_task_is_none(self):
        self.assertIsNone(self.cfg.task_main('nope'))

    def test_goods_cells(self):
        self.assertIsNone(parse_task_goods(''))
        self.assertEqual(parse_task_goods('g1_5;g2_1'), {'g1': 5, 'g2': 1})

    def test_monster_cell_forms(self):
        # showName_id, #auto ids, and repeat-id accumulation, per bytecode.
        self.assertIsNone(parse_task_monsters(''))
        self.assertEqual(
            parse_task_monsters('name_D01:3;#D02:2'), {
                'D01': {'monster_id': 'D01', 'count': 3,
                        'auto_attack': False, 'show_name': 'name'},
                'D02': {'monster_id': 'D02', 'count': 2,
                        'auto_attack': True, 'show_name': None}})
        self.assertEqual(
            parse_task_monsters('D01:1;D01:2')['D01']['count'], 3)


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class MainTaskFrameTest(unittest.TestCase):
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
            get_task_main=self.store.get_task_main,
            save_task_main=self.store.save_task_main,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'

    def frames(self, out):
        self.assertIsNotNone(out)
        if not isinstance(out, tuple):
            return [decode(out[4:])]
        return [decode(f[4:]) for f in out]

    def test_fresh_role_inits_first_task(self):
        before = int(time.time() * 1000)
        got = self.frames(self.sess.main_task())
        # Action order: 50000 reply first, then the queued 50004 push.
        self.assertEqual([f[0] for f in got], ['50000', '50004'])
        cmd, obj = got[0][0], got[0][1]
        self.assertEqual(cmd, '50000')
        self.assertEqual(obj[0], 'c001001')
        self.assertTrue(before <= obj[1] <= before + 60000)
        self.assertEqual(obj[2], [None, None])   # no conditions on c001001
        # c001001 has no kill/item reqs, so taskMainIsFinished is vacuously
        # true (bytecode: null maps skip to iconst_1) and recevie stores 1.
        self.assertEqual(obj[3], 1)
        self.assertEqual(got[1][1], obj)
        row = self.store.get_task_main(self.role_id)
        self.assertEqual(row['task_id'], 'c001001')
        self.assertEqual(row['state'], 1)

    def test_kill_progress_reports(self):
        self.store.save_task_main(
            self.role_id, task_uid='t1', task_id='c001004', state=0,
            condition='D010006;1', recevie_time=1, create_time=1)
        (out,) = self.frames(self.sess.main_task())
        self.assertEqual(out[0], '50000')
        task_id, _recevie, (items, monsters), state = out[1]
        self.assertEqual(task_id, 'c001004')
        self.assertIsNone(items)
        self.assertEqual(monsters, ['D010006', 1, 1, True, None])
        self.assertEqual(state, 0)

    def test_done_state_reports_full_count(self):
        self.store.save_task_main(
            self.role_id, task_uid='t1', task_id='c001004', state=1,
            condition=None, recevie_time=1, create_time=1)
        (out,) = self.frames(self.sess.main_task())
        self.assertEqual(out[1][2][1], ['D010006', 1, 1, True, None])

    def test_paid_state_previews_next(self):
        # State 2 on c001001 previews c001002 (limit 2 opens at level 56).
        self.store.save_task_main(
            self.role_id, task_uid='t1', task_id='c001001', state=2,
            condition=None, recevie_time=1, create_time=1)
        (out,) = self.frames(self.sess.main_task())
        self.assertEqual(out, ['50000', ['c001002', None, None, 3]])

    def test_unknown_task_is_silent(self):
        self.store.save_task_main(
            self.role_id, task_uid='t1', task_id='nope', state=0,
            condition=None, recevie_time=1, create_time=1)
        self.assertIsNone(self.sess.main_task())

    def test_malformed_condition_is_silent(self):
        self.store.save_task_main(
            self.role_id, task_uid='t1', task_id='c001004', state=0,
            condition='D010006;x', recevie_time=1, create_time=1)
        self.assertIsNone(self.sess.main_task())


if __name__ == '__main__':
    unittest.main()

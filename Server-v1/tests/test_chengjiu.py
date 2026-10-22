"""Commands 89000/89005: achievement panel and reward claim.

Evidence: ChengjiuAction.getChengJiu/getLingQu plus
RoleChengjiuServiceImpl.getChengJiu/getLingQu/isTaskKaiqi/isTaskTiaoJian,
ChengJiuConfigExportServiceImpl.createEntity (one kaiqi pair, jiangli via
convertGoodsesStrs2List3, five tiaojian pairs), ChengJiuConstant
(STATUS_1/KAIQITYPE/TIAOJIANTYPE), GeneralErrorCode.BAG_SLOT_NOT_ENOUGH,
and StoreGoodsOutput.formart2, all from dntg_start.jar via tools/javap.py.
Real chengjiuzhuizong.jat rows (cjzz01-cjzz07) drive the goldens below.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db import Store  # noqa: E402
from game.amf3 import decode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2]
               / 'reference' / 'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config'
             / 'chengjiuzhuizong.jat').is_file()


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class ChengjiuTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.store = Store(os.path.join(tmp, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', 'pw')
        self.role_id = str(self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='A', level=56,
            tongqian=50000, zhenqi=5000))
        self.store.save_role_bag_state(self.role_id, bag_capacity=144)
        self.cfg = GameConfig(str(REAL_CONFIG))

    def sess_as(self, **override):
        role = dict(self.store.list_roles('hero', 'fu1304')[0], **override)
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [role],
            server_start_ms=0,
            save_role_state=self.store.update_character_state,
            get_role_chengjiu=self.store.get_role_chengjiu,
            save_role_chengjiu=self.store.save_role_chengjiu,
            get_task_main=self.store.get_task_main,
            save_task_main=self.store.save_task_main,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            config=self.cfg)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return sess

    def one(self, out):
        self.assertIsNotNone(out)
        if isinstance(out, tuple):
            self.assertEqual(len(out), 1)
            out = out[0]
        return decode(out[4:])

    @staticmethod
    def assoc(m):
        """Unwrap the decoder's dynamic-object envelope (test_bag.py)."""
        return m.get('__assoc__', m)

    def seed_task(self, task_id, state=1):
        self.store.save_task_main(
            self.role_id, task_uid='u1', task_id=task_id, state=state,
            condition='', recevie_time=0, create_time=0)

    # Panel (89000).

    def test_panel_empty(self):
        body = self.one(self.sess_as().chengjiu_panel())
        self.assertEqual(body, ['89000', []])

    def test_panel_lists_claimed(self):
        self.store.save_role_chengjiu(self.role_id, 'cjzz02')
        self.store.save_role_chengjiu(self.role_id, 'cjzz01')
        body = self.one(self.sess_as().chengjiu_panel())
        self.assertEqual(body, ['89000', [['cjzz01', 1], ['cjzz02', 1]]])

    def test_panel_no_role_silent(self):
        sess = self.sess_as()
        sess.get_roles = lambda u, s: []
        self.assertIsNone(sess.chengjiu_panel())

    # Config parse.

    def test_config_rows(self):
        cjzz01 = self.cfg.chengjiu_config('cjzz01')
        self.assertEqual(cjzz01['kaiqi'], [(1, 'c001016')])
        self.assertEqual(cjzz01['rewards'],
                         [{'goods_id': 'zj0023', 'count': 1,
                           'bind': 1, 'expire': 0}])
        self.assertEqual(cjzz01['tiaojian'],
                         [(1, 'c002002'), (1, 'c002006'),
                          (1, 'c002007'), (1, 'c002008')])
        cjzz05 = self.cfg.chengjiu_config('cjzz05')
        self.assertEqual(cjzz05['tiaojian'],
                         [(2, 42), (2, 44), (2, 46), (2, 47),
                          (1, 'c005032')])
        self.assertIsNone(self.cfg.chengjiu_config('nope'))

    # Claim gates (89005).

    def test_claim_unknown_id_null(self):
        body = self.one(self.sess_as().chengjiu_claim(['89005', 'nope']))
        self.assertEqual(body, ['89005', None])

    def test_claim_bad_arg_silent(self):
        self.assertIsNone(self.sess_as().chengjiu_claim(['89005', 42]))
        self.assertIsNone(self.sess_as().chengjiu_claim(['89005', None]))
        self.assertIsNone(self.sess_as().chengjiu_claim(['89005']))

    def test_claim_already_claimed(self):
        self.store.save_role_chengjiu(self.role_id, 'cjzz01')
        body = self.one(self.sess_as().chengjiu_claim(['89005', 'cjzz01']))
        self.assertEqual(body, ['89005', [0, 'cjzz01']])

    def test_claim_kaiqi_unstarted(self):
        # No running quest: c007001 is neither current nor passed.
        body = self.one(self.sess_as().chengjiu_claim(['89005', 'cjzz07']))
        self.assertEqual(body, ['89005', [False, [0, 'cjzz07']]])

    def test_claim_kaiqi_current_unfinished(self):
        # On c001016 but state 0: isTaskfinsh needs state 1.
        self.seed_task('c001016', state=0)
        body = self.one(self.sess_as().chengjiu_claim(['89005', 'cjzz01']))
        self.assertEqual(body, ['89005', [False, [0, 'cjzz01']]])

    def test_claim_tiaojian_task_fail(self):
        # Past the c001016 unlock but short of c002006.
        self.seed_task('c002005')
        body = self.one(self.sess_as().chengjiu_claim(['89005', 'cjzz01']))
        self.assertEqual(body, ['89005', [False, [0, 'cjzz01']]])

    def test_claim_tiaojian_level_fail(self):
        # Past the c005001 unlock, but level 1 < 42.
        self.seed_task('c005002')
        body = self.one(
            self.sess_as(level=1).chengjiu_claim(['89005', 'cjzz05']))
        self.assertEqual(body, ['89005', [False, [0, 'cjzz05']]])

    def test_claim_bag_full(self):
        self.seed_task('c002009')
        self.store.save_role_bag_state(self.role_id, bag_capacity=0)
        body = self.one(self.sess_as().chengjiu_claim(['89005', 'cjzz01']))
        self.assertEqual(body, ['89005', [0, 1006]])

    # Claim success.

    def test_claim_success_quest_gates(self):
        self.seed_task('c002009')
        body = self.one(self.sess_as().chengjiu_claim(['89005', 'cjzz01']))
        self.assertEqual(body[0], '89005')
        self.assertEqual(body[1][0], 1)
        self.assertEqual(body[1][1], 'cjzz01')
        records = body[1][2]
        self.assertEqual(records[0], 0)
        self.assertEqual(records[1], 0)
        self.assertEqual(len(records[2]), 1)
        rec = records[2][0]
        self.assertEqual(rec[0], 'zj0023')
        self.assertEqual(rec[3], 1)
        self.assertEqual(rec[4], self.role_id)
        self.assertEqual(rec[7], 1)
        rows = self.store.get_role_chengjiu(self.role_id)
        self.assertEqual(rows, [{'task_id': 'cjzz01', 'task_status': 1}])
        slots = self.store.get_role_bag_slots(self.role_id, 1, 150)
        self.assertEqual(
            [(s['goods_id'], s['count'], s['bind']) for s in slots],
            [('zj0023', 1, 1)])

    def test_claim_success_level_gates(self):
        # cjzz05 mixes level gates (42/44/46/47, role is 56) with a quest
        # gate; the sj0103 reward is a category-40 kept good.
        self.seed_task('c005033')
        body = self.one(self.sess_as().chengjiu_claim(['89005', 'cjzz05']))
        self.assertEqual(body[1][0], 1)
        self.assertEqual(body[1][1], 'cjzz05')
        self.assertEqual([r[0] for r in body[1][2][2]], ['sj0103'])
        self.assertEqual(
            self.store.get_role_chengjiu(self.role_id),
            [{'task_id': 'cjzz05', 'task_status': 1}])

    def test_claim_success_drops_job_mismatch(self):
        # cjzz02 rewards one equip per job (C/A/D/B); a job-A role keeps
        # only zj0203, like GoodsJobFilter.
        self.seed_task('c002016')
        body = self.one(self.sess_as().chengjiu_claim(['89005', 'cjzz02']))
        self.assertEqual(body[1][0], 1)
        self.assertEqual([r[0] for r in body[1][2][2]], ['zj0203'])

    def test_claim_empty_grant_null(self):
        self.seed_task('c002009')
        fake = mock.Mock()
        fake.chengjiu_config.return_value = {
            'id': 'cjzz01', 'kaiqi': [], 'tiaojian': [],
            'rewards': [{'goods_id': 'nope', 'count': 1, 'bind': 0}],
        }
        fake.goods_category.return_value = None
        sess = self.sess_as()
        sess.config = fake
        body = self.one(sess.chengjiu_claim(['89005', 'cjzz01']))
        self.assertEqual(body, ['89005', None])


if __name__ == '__main__':
    unittest.main()

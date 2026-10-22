"""Commands 41001/41002/41003/41004/41021: shenjiang fragment synthesis,
skill upgrade, star-chart arm/light, and breakthrough.

Evidence: ShenjiangAction.suiPianHeCheng/skillUpgrade/canJihuoJiangxingtu/
jihuoJiangxingtu/jiangxingtuJinjie plus ShenjiangServiceImpl.checkSkillUpgrade/
checkCanJihuoJiangxingtu/computeIsSuccess/jinjieFail, ShenjiangErrorCode ints
and JiangliErrorCodeOutput 423000-series strings, from dntg_start.jar via
tools/javap.py. Real ShenJiangBiao/JiangXingTu/JiNengBiao rows (sj0101 five
tiers, dj0101 chart, niumowang1 ladder) drive the goldens below.
"""
import json
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
HAVE_REAL = (REAL_CONFIG / 'sys_config' / 'ShenJiangBiao.jat').is_file()

SJ = 'sj0101'
CHART = 'dj0101'
SKILL = 'niumowang1'


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class ShenjiangTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.store = Store(os.path.join(tmp, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', 'pw')
        self.role_id = str(self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56,
            tongqian=50000, zhenqi=5000))
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = self.sess_as()

    def sess_as(self, **override):
        role = dict(self.store.list_roles('hero', 'fu1304')[0], **override)
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [role],
            server_start_ms=0,
            save_role_state=self.store.update_character_state,
            get_role_shenjiang=self.store.get_role_shenjiang,
            save_role_shenjiang=self.store.save_role_shenjiang,
            save_role_skill=self.store.save_role_skill,
            get_role_bag_slots=self.store.get_role_bag_slots,
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

    def skills(self):
        return {r['category']: r['level']
                for r in self.store.get_role_skills(self.role_id)}

    def own(self, skills, rank=0, **extra):
        fields = {'jiangxing_id': '', 'jiangxing_rank': rank,
                  'skills': json.dumps(skills)}
        fields.update(extra)
        self.store.save_role_shenjiang(self.role_id, SJ, **fields)

    def owned(self):
        rows = self.store.get_role_shenjiang(self.role_id)
        self.assertEqual(len(rows), 1)
        return rows[0]

    def role(self):
        return self.store.list_roles('hero', 'fu1304')[0]

    # 41001 suiPianHeCheng
    def test_activate_unknown_id_is_silent(self):
        self.assertIsNone(self.sess.shenjiang_activate(['41001', 'zzz']))

    def test_activate_owned_id_is_silent(self):
        self.own({})
        self.assertIsNone(self.sess.shenjiang_activate(['41001', SJ]))

    def test_activate_fragment_short_answers_420011(self):
        out = self.sess.shenjiang_activate(['41001', 'sj0105'])
        self.assertEqual(self.one(out), ['41001', [0, 420011]])
        self.assertEqual(self.store.get_role_shenjiang(self.role_id), [])

    def test_activate_zhenqi_short_answers_1001(self):
        # sj0101 tier0 wants 10000 zhenqi; the role carries 5000.
        out = self.sess.shenjiang_activate(['41001', SJ])
        self.assertEqual(self.one(out), ['41001', [0, 1001]])
        self.assertEqual(self.store.get_role_shenjiang(self.role_id), [])

    def test_activate_burns_zhenqi_and_inserts_row_41001(self):
        sess = self.sess_as(zhenqi=20000)
        out = sess.shenjiang_activate(['41001', SJ])
        self.assertEqual(self.one(out), ['41001', [1, SJ]])
        row = self.owned()
        self.assertEqual((row['jiangxing_rank'], row['skills']), (0, '{}'))
        self.assertEqual(self.role()['zhenqi'], 10000)

    # 41002 skillUpgrade
    def test_skillup_unknown_shenjiang_is_silent(self):
        self.assertIsNone(
            self.sess.shenjiang_skill_up(['41002', ['zzz', SKILL]]))

    def test_skillup_unowned_skill_is_silent(self):
        self.own({SKILL: 1})
        self.assertIsNone(
            self.sess.shenjiang_skill_up(['41002', [SJ, 'other']]))

    def test_skillup_missing_config_answers_420001(self):
        self.own({'nosuchskill': 1})
        out = self.sess.shenjiang_skill_up(
            ['41002', [SJ, 'nosuchskill']])
        self.assertEqual(self.one(out), ['41002', [0, 420001]])

    def test_skillup_maxed_skill_answers_420010(self):
        # rank 0 arms the tier0 (maxlv 20) row.
        self.own({SKILL: 20})
        out = self.sess.shenjiang_skill_up(['41002', [SJ, SKILL]])
        self.assertEqual(self.one(out), ['41002', [0, 420010]])

    def test_skillup_learns_and_burns_costs_41002(self):
        # niumowang1 L1: levelneed 1, zhenqineed 100, goldneed 1000,
        # learnodds 1; role L56 / 5000 zhenqi / 50000 coin.
        self.own({SKILL: 1})
        out = self.sess.shenjiang_skill_up(['41002', [SJ, SKILL]])
        self.assertEqual(self.one(out), ['41002', [1, SJ, SKILL, 2]])
        self.assertEqual(json.loads(self.owned()['skills']), {SKILL: 2})
        self.assertEqual(self.skills()[SKILL], 2)
        role = self.role()
        self.assertEqual((role['zhenqi'], role['tongqian']),
                         (4900, 49000))

    def test_skillup_zhenqi_short_answers_1001(self):
        self.own({SKILL: 1})
        sess = self.sess_as(zhenqi=50)
        out = sess.shenjiang_skill_up(['41002', [SJ, SKILL]])
        self.assertEqual(self.one(out), ['41002', [0, 1001]])
        self.assertEqual(json.loads(self.owned()['skills']), {SKILL: 1})

    # 41003 canJihuoJiangxingtu
    def test_canjihuo_unknown_chart_is_silent(self):
        self.own({SKILL: 1}, rank=1)
        self.assertIsNone(
            self.sess.shenjiang_can_jihuo(['41003', [SJ, 'zzz']]))

    def test_canjihuo_unowned_shenjiang_is_silent(self):
        self.assertIsNone(
            self.sess.shenjiang_can_jihuo(['41003', [SJ, CHART]]))

    def test_canjihuo_short_rank_answers_423006(self):
        # dj0101 needs dwlv 1; a rank-0 row falls short.
        self.own({SKILL: 1}, rank=0)
        out = self.sess.shenjiang_can_jihuo(['41003', [SJ, CHART]])
        self.assertEqual(self.one(out), ['41003', [0, '423006']])

    def test_canjihuo_arms_chart_and_burns_costs_41003(self):
        # dj0101: needlv 30, costzhenqi 2000, costtype 1 x 1000,
        # needmaxtime 1; role L56 / 5000 zhenqi / 50000 coin.
        self.own({SKILL: 1}, rank=1)
        out = self.sess.shenjiang_can_jihuo(['41003', [SJ, CHART]])
        self.assertEqual(self.one(out),
                         ['41003', [1, 1, 1, 1000, CHART]])
        row = self.owned()
        self.assertEqual(
            (row['cur_jiangxing_id'], row['jiangxing_state']),
            (CHART, 1))
        role = self.role()
        self.assertEqual((role['zhenqi'], role['tongqian']),
                         (3000, 49000))

    def test_canjihuo_lit_chart_answers_423000(self):
        self.own({SKILL: 1}, rank=1, jiangxing_id=CHART)
        out = self.sess.shenjiang_can_jihuo(['41003', [SJ, CHART]])
        self.assertEqual(self.one(out), ['41003', [0, '423000']])

    # 41004 jihuoJiangxingtu
    def test_jihuo_unarmed_is_silent(self):
        self.own({SKILL: 1}, rank=1)
        self.assertIsNone(self.sess.shenjiang_jihuo(['41004', SJ]))

    def test_jihuo_success_lights_chart_41004(self):
        # dj0101 successodds 1 always lights: successaddexp 24000,
        # successskillid df_sf, hitpoints 64 -> attr index 1.
        self.own({SKILL: 1}, rank=1, cur_jiangxing_id=CHART)
        out = self.sess.shenjiang_jihuo(['41004', SJ])
        frame = self.one(out)
        self.assertEqual(frame[0], '41004')
        self.assertEqual(frame[1][0], 1)
        self.assertEqual(frame[1][1], CHART)
        # The attribute-index table is empty, so the map passes through.
        self.assertEqual(self.assoc(frame[1][2]), {'hitpoints': 64})
        self.assertEqual(frame[1][3], ['df_sf'])
        self.assertEqual(frame[1][4], 24000)
        row = self.owned()
        self.assertEqual(
            (row['jiangxing_id'], row['cur_jiangxing_id'],
             row['fail_count']),
            (CHART, '', 0))
        self.assertEqual(self.skills()['df_sf'], 1)

    def test_jihuo_fail_banks_count_and_exp_41004(self):
        self.own({SKILL: 1}, rank=1, cur_jiangxing_id=CHART)
        with mock.patch.object(Session, '_lottery_success',
                               return_value=False):
            out = self.sess.shenjiang_jihuo(['41004', SJ])
        # dj0101 failaddexp 8000.
        self.assertEqual(self.one(out), ['41004', [0, 8000]])
        row = self.owned()
        self.assertEqual(
            (row['jiangxing_id'], row['cur_jiangxing_id'],
             row['fail_count']),
            ('', '', 1))

    # 41021 jiangxingtuJinjie
    def test_jinjie_unowned_is_silent(self):
        self.assertIsNone(
            self.sess.shenjiang_jinjie(['41021', [SJ, 0]]))

    def test_jinjie_unlit_chart_answers_423004(self):
        self.own({SKILL: 1}, rank=1)
        out = self.sess.shenjiang_jinjie(['41021', [SJ, 0]])
        self.assertEqual(self.one(out), ['41021', [0, '423004']])

    def test_jinjie_top_tier_answers_423005(self):
        self.own({SKILL: 1}, rank=4, jiangxing_id=CHART)
        out = self.sess.shenjiang_jinjie(['41021', [SJ, 0]])
        self.assertEqual(self.one(out), ['41021', [0, '423005']])

    def test_jinjie_short_coin_answers_1003(self):
        # rank 1 arms the tier1 (jinjieneedcoin 20000) row.
        self.own({SKILL: 1}, rank=1, jiangxing_id=CHART)
        sess = self.sess_as(tongqian=10)
        out = sess.shenjiang_jinjie(['41021', [SJ, 0]])
        self.assertEqual(self.one(out), ['41021', [0, 1003]])

    def test_jinjie_short_goods_answers_1005(self):
        self.own({SKILL: 1}, rank=1, jiangxing_id=CHART)
        out = self.sess.shenjiang_jinjie(['41021', [SJ, 0]])
        self.assertEqual(self.one(out), ['41021', [0, 1005]])

    def test_jinjie_success_ranks_up_41021(self):
        self.own({SKILL: 1}, rank=1, jiangxing_id=CHART)
        self.store.insert_role_bag_slot(
            self.role_id, {'slot_num': 1, 'goods_id': 'jinjiedan002',
                           'count': 1})
        with mock.patch.object(Session, '_lottery_success',
                               return_value=True):
            out = self.sess.shenjiang_jinjie(['41021', [SJ, 0]])
        self.assertEqual(self.one(out), ['41021', [1, SJ, 2]])
        row = self.owned()
        self.assertEqual(
            (row['jiangxing_rank'], row['rank_fail_count'],
             row['rank_lucky']),
            (2, 0, 0))
        self.assertEqual(self.role()['tongqian'], 30000)

    def test_jinjie_fail_grows_blessing_41021(self):
        self.own({SKILL: 1}, rank=1, jiangxing_id=CHART)
        self.store.insert_role_bag_slot(
            self.role_id, {'slot_num': 1, 'goods_id': 'jinjiedan002',
                           'count': 1})
        with mock.patch.object(Session, '_lottery_success',
                               return_value=False), \
            mock.patch('random.randint', return_value=3):
            out = self.sess.shenjiang_jinjie(['41021', [SJ, 0]])
        self.assertEqual(self.one(out), ['41021', [-1, SJ, 3]])
        row = self.owned()
        self.assertEqual(
            (row['jiangxing_rank'], row['rank_fail_count'],
             row['rank_lucky']),
            (1, 1, 3))


if __name__ == '__main__':
    unittest.main()

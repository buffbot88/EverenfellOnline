"""Commands 58012/58013/58014/58015: sign-in, retro-sign, reward and meiren claim.

Evidence: JiangliAction.qiandao/buqian/lingquQiandaoReward/lingquMeiren
plus JiangliServiceImpl.qiandao/buQian/checkBuqian/lingquQiandaoReward/
checkLingquQiandaoReward/lingquQiandaoMeiren/checkLingquQiandaoMeiren/
createRoleQiandao/getVipQiandaoConfig, QiandaoConfigExportServiceImpl
(stye categories from jianglipeizhi.jat), QiandaoOutput.qiandao [1],
MeirenServiceImpl.addMeiRen, and the JiangliErrorCodeOutput 592000-592010
payloads, all from dntg_start.jar via tools/javap.py. Real
jianglipeizhi.jat rows (z100-z106, z111+) drive the goldens below.
"""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db import Store  # noqa: E402
from game.amf3 import decode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2]
               / 'reference' / 'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config'
             / 'jianglipeizhi.jat').is_file()

TODAY = time.localtime().tm_mday
WEEKDAY = (time.localtime().tm_wday + 1) % 7


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class QiandaoTest(unittest.TestCase):
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
            get_role_qiandao=self.store.get_role_qiandao,
            save_role_qiandao=self.store.save_role_qiandao,
            get_role_vip=self.store.get_role_vip,
            get_role_meiren=self.store.get_role_meiren,
            save_role_meiren=self.store.save_role_meiren,
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

    def seed_row(self, **fields):
        base = {'total_qiandao_count': 0, 'month': time.localtime().tm_mon,
                'month_qiandao': '', 'total_qiandao_reward': '',
                'month_qiandao_reward': '', 'week': TODAY, 'qiandao_time': 0}
        base.update(fields)
        self.store.save_role_qiandao(self.role_id, **base)

    # Config parse.

    def test_config_categories(self):
        tables = self.cfg.qiandao_tables()
        self.assertEqual(sorted(tables), [1, 2, 3])
        self.assertEqual(tables[1]['z100']['rewards'],
                         [('fuhuo', 2, 1), ('zhenqipill_001', 2, 1),
                          ('silver10', 5, 1)])
        self.assertEqual(tables[2]['z105']['meiren_id'], 'zixia')
        self.assertEqual(tables[2]['z105']['count'], 30)
        self.assertEqual(tables[3]['z111']['vip_level'], 1)
        self.assertIsNone(self.cfg.qiandao_config(1, 'nope'))
        self.assertIsNone(self.cfg.qiandao_config(9, 'z100'))

    # Sign-in (58012).

    def test_sign_first_creates_row(self):
        body = self.one(self.sess_as().qiandao_sign())
        self.assertEqual(body, ['58012', [1]])
        row = self.store.get_role_qiandao(self.role_id)
        self.assertEqual(row['total_qiandao_count'], 1)
        self.assertEqual(row['month_qiandao'], str(TODAY))

    def test_sign_repeat_same_day(self):
        self.seed_row(month_qiandao=str(TODAY),
                      qiandao_time=int(time.time() * 1000),
                      total_qiandao_count=3)
        body = self.one(self.sess_as().qiandao_sign())
        self.assertEqual(body, ['58012', [0, '592000']])
        self.assertEqual(
            self.store.get_role_qiandao(self.role_id)['total_qiandao_count'],
            3)

    def test_sign_next_day_marks(self):
        self.seed_row(month_qiandao='1', qiandao_time=1,
                      total_qiandao_count=3)
        body = self.one(self.sess_as().qiandao_sign())
        self.assertEqual(body, ['58012', [1]])
        row = self.store.get_role_qiandao(self.role_id)
        self.assertEqual(row['total_qiandao_count'], 4)
        self.assertEqual(row['month_qiandao'], '1,%d' % TODAY)

    def test_sign_vip_weekend_grants(self):
        # A crafted category-3 config hitting today's weekday grants.
        sess = self.sess_as()
        vip_cfg = {'id': 'zvip', 'count': 1, 'vip_level': 1,
                   'rewards': [('silver10', 7, 1)], 'meiren_id': '',
                   'week1': WEEKDAY, 'week2': -1}
        sess.config = _ConfigWithQiandao(self.cfg, {3: {'zvip': vip_cfg}})
        self.store.save_role_vip(self.role_id, vip_level=1)
        body = self.one(sess.qiandao_sign())
        self.assertEqual(body, ['58012', [1]])
        slots = self.store.get_role_bag_slots(self.role_id, 1, 150)
        self.assertIn(('silver10', 7, 1),
                      [(s['goods_id'], s['count'], s['bind'])
                       for s in slots])

    def test_sign_vip_weekday_mismatch_skips_grant(self):
        sess = self.sess_as()
        vip_cfg = {'id': 'zvip', 'count': 1, 'vip_level': 1,
                   'rewards': [('silver10', 7, 1)], 'meiren_id': '',
                   'week1': -1, 'week2': -2}
        sess.config = _ConfigWithQiandao(self.cfg, {3: {'zvip': vip_cfg}})
        self.store.save_role_vip(self.role_id, vip_level=1)
        body = self.one(sess.qiandao_sign())
        self.assertEqual(body, ['58012', [1]])
        slots = self.store.get_role_bag_slots(self.role_id, 1, 150)
        self.assertEqual(slots, [])

    # Retro-sign (58013).

    def test_buqian_bad_arg_silent(self):
        self.assertIsNone(self.sess_as().qiandao_buqian(['58013', 'x']))
        self.assertIsNone(self.sess_as().qiandao_buqian(['58013', True]))
        self.assertIsNone(self.sess_as().qiandao_buqian(['58013']))

    def test_buqian_future_day_silent(self):
        self.assertIsNone(
            self.sess_as().qiandao_buqian(['58013', TODAY + 1]))

    def test_buqian_non_vip(self):
        self.seed_row()
        body = self.one(self.sess_as().qiandao_buqian(['58013', TODAY]))
        self.assertEqual(body, ['58013', [0, 1010]])

    def test_buqian_vip_config_missing(self):
        self.seed_row()
        self.store.save_role_vip(self.role_id, vip_level=99)
        body = self.one(self.sess_as().qiandao_buqian(['58013', TODAY]))
        self.assertEqual(body, ['58013', [0, '592007']])

    def test_buqian_already_signed(self):
        self.seed_row(month_qiandao=str(TODAY))
        self.store.save_role_vip(self.role_id, vip_level=1)
        body = self.one(self.sess_as().qiandao_buqian(['58013', TODAY]))
        self.assertEqual(body, ['58013', [0, '592010']])

    def test_buqian_success_marks_and_bumps(self):
        self.seed_row(month_qiandao='1', total_qiandao_count=2)
        self.store.save_role_vip(self.role_id, vip_level=1)
        body = self.one(self.sess_as().qiandao_buqian(['58013', TODAY]))
        self.assertEqual(body, ['58013', [1, TODAY]])
        row = self.store.get_role_qiandao(self.role_id)
        self.assertEqual(row['total_qiandao_count'], 3)
        self.assertIn(str(TODAY), row['month_qiandao'].split(','))

    # Reward claim (58014).

    def test_reward_bad_arg_silent(self):
        self.assertIsNone(
            self.sess_as().qiandao_reward(['58014', 42]))

    def test_reward_no_row_null(self):
        body = self.one(self.sess_as().qiandao_reward(['58014', 'z100']))
        self.assertEqual(body, ['58014', None])

    def test_reward_unknown_id(self):
        self.seed_row(total_qiandao_count=30)
        body = self.one(self.sess_as().qiandao_reward(['58014', 'nope']))
        self.assertEqual(body, ['58014', [0, '592002']])

    def test_reward_repeat(self):
        self.seed_row(total_qiandao_count=30,
                      month_qiandao_reward='z100')
        body = self.one(self.sess_as().qiandao_reward(['58014', 'z100']))
        self.assertEqual(body, ['58014', [0, '592001']])

    def test_reward_bag_full(self):
        self.seed_row(total_qiandao_count=30)
        self.store.save_role_bag_state(self.role_id, bag_capacity=0)
        body = self.one(self.sess_as().qiandao_reward(['58014', 'z100']))
        self.assertEqual(body, ['58014', [0, 1006]])

    def test_reward_success_grants_and_marks(self):
        self.seed_row(total_qiandao_count=30)
        body = self.one(self.sess_as().qiandao_reward(['58014', 'z100']))
        self.assertEqual(body, ['58014', [1, 'z100']])
        row = self.store.get_role_qiandao(self.role_id)
        self.assertEqual(row['month_qiandao_reward'], 'z100')
        slots = self.store.get_role_bag_slots(self.role_id, 1, 150)
        got = sorted((s['goods_id'], s['count'], s['bind']) for s in slots)
        self.assertEqual(got, [('fuhuo', 2, 1), ('silver10', 5, 1),
                               ('zhenqipill_001', 2, 1)])

    # Meiren claim (58015).

    def test_meiren_bad_arg_row_and_config_silent(self):
        self.assertIsNone(
            self.sess_as().qiandao_meiren(['58015', 42]))
        self.assertIsNone(
            self.sess_as().qiandao_meiren(['58015', 'z105']))
        self.seed_row(total_qiandao_count=30)
        self.assertIsNone(
            self.sess_as().qiandao_meiren(['58015', 'nope']))

    def test_meiren_count_short(self):
        self.seed_row(total_qiandao_count=5)
        body = self.one(self.sess_as().qiandao_meiren(['58015', 'z105']))
        self.assertEqual(body, ['58015', [0, '592002']])

    def test_meiren_repeat(self):
        self.seed_row(total_qiandao_count=30, total_qiandao_reward='z105')
        body = self.one(self.sess_as().qiandao_meiren(['58015', 'z105']))
        self.assertEqual(body, ['58015', [0, '592001']])

    def test_meiren_success_pushes_82001(self):
        self.seed_row(total_qiandao_count=30)
        out = self.sess_as().qiandao_meiren(['58015', 'z105'])
        self.assertIsInstance(out, tuple)
        self.assertEqual(len(out), 2)
        push, reply = decode(out[0][4:]), decode(out[1][4:])
        self.assertEqual(push, ['82001', [1, 'zixia', 1]])
        self.assertEqual(reply, ['58015', [1, 'z105']])
        owned = self.store.get_role_meiren(self.role_id)
        self.assertTrue(
            any(self.cfg.meiren_type_for(m.get('meiren_id')) == 'zixia'
                for m in owned))

    def test_meiren_owned_still_answers_success(self):
        self.seed_row(total_qiandao_count=30)
        sess = self.sess_as()
        first = sess.qiandao_meiren(['58015', 'z105'])
        self.assertIsInstance(first, tuple)
        again = self.one(sess.qiandao_meiren(['58015', 'z105']))
        self.assertEqual(again, ['58015', [1, 'z105']])


class _ConfigWithQiandao:
    """GameConfig proxy overriding only the category-3 qiandao table."""

    def __init__(self, base, tables):
        self._base = base
        self._tables = tables

    def __getattr__(self, name):
        return getattr(self._base, name)

    def qiandao_tables(self):
        return self._tables


if __name__ == '__main__':
    unittest.main()

"""Commands 58017/58018/58019: voice-download reward, state, and daily reward.

Evidence: JiangliAction.yingyinXiaZaiReward/getYingYinState/yingyinreward
plus JiangliServiceImpl.yingyinXiaZaiReward/getYingYinState/yingyinreward/
xiazaiReward/dayReward/loginYingYin, BaiDuYingYinConfigExportServiceImpl
(number-1 loadByYingyin from baiduyingyin.jat), and the 592013/592014
payloads, all from dntg_start.jar via tools/javap.py. The real
baiduyingyin.jat number-1 row drives the goldens below.
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
             / 'baiduyingyin.jat').is_file()

FIRST_GOODS = [('qianghuashi', 3, 1), ('jinjieshi', 1, 1),
               ('bscl', 5, 1), ('zhenqipill_003', 1, 1)]


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class YingyinTest(unittest.TestCase):
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

    def sess_as(self, start_ms=None, **override):
        role = dict(self.store.list_roles('hero', 'fu1304')[0], **override)
        if start_ms is None:
            start_ms = int(time.time() * 1000)
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [role],
            server_start_ms=start_ms,
            save_role_state=self.store.update_character_state,
            get_role_jiangli_list=self.store.get_role_jiangli_list,
            save_role_jiangli_list=self.store.save_role_jiangli_list,
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
        base = {'baidu_yingyin': 0, 'baidu_yingyin_xiazai': 0,
                'baidu_yingyin_time': int(time.time() * 1000)}
        base.update(fields)
        self.store.save_role_jiangli_list(self.role_id, **base)

    # Config parse.

    def test_config_row(self):
        cfg = self.cfg.yingyin_config()
        self.assertEqual(cfg['time'], 30)
        self.assertEqual([tuple(g) for g in cfg['first_goods']],
                         FIRST_GOODS)
        self.assertEqual([tuple(g) for g in cfg['day_goods']],
                         FIRST_GOODS)

    # State (58018).

    def test_state_creates_row(self):
        body = self.one(self.sess_as().yingyin_state())
        self.assertEqual(body, ['58018', [0, 0]])
        row = self.store.get_role_jiangli_list(self.role_id)
        self.assertEqual((row['baidu_yingyin_xiazai'],
                          row['baidu_yingyin']), (0, 0))

    def test_state_reads_flags(self):
        self.seed_row(baidu_yingyin=1, baidu_yingyin_xiazai=1)
        body = self.one(self.sess_as().yingyin_state())
        self.assertEqual(body, ['58018', [1, 1]])

    def test_state_resets_stale_day_flag(self):
        self.seed_row(baidu_yingyin=1, baidu_yingyin_xiazai=1,
                      baidu_yingyin_time=1)
        body = self.one(self.sess_as().yingyin_state())
        self.assertEqual(body, ['58018', [1, 0]])
        row = self.store.get_role_jiangli_list(self.role_id)
        self.assertEqual((row['baidu_yingyin_xiazai'],
                          row['baidu_yingyin']), (1, 0))

    # Download claim (58017).

    def test_xiazai_repeat(self):
        self.seed_row(baidu_yingyin_xiazai=1)
        body = self.one(self.sess_as().yingyin_xiazai())
        self.assertEqual(body, ['58017', [0, '592013']])

    def test_xiazai_past_window(self):
        old = int(time.time() * 1000) - 31 * 86400 * 1000
        sess = self.sess_as(start_ms=old)
        body = self.one(sess.yingyin_xiazai())
        self.assertEqual(body, ['58017', [0, '592014']])

    def test_xiazai_bag_full(self):
        self.seed_row()
        self.store.save_role_bag_state(self.role_id, bag_capacity=0)
        body = self.one(self.sess_as().yingyin_xiazai())
        self.assertEqual(body, ['58017', [0, 1006]])

    def test_xiazai_success_grants_and_stamps(self):
        body = self.one(self.sess_as().yingyin_xiazai())
        self.assertEqual(body, ['58017', [1]])
        row = self.store.get_role_jiangli_list(self.role_id)
        self.assertEqual(row['baidu_yingyin_xiazai'], 1)
        slots = self.store.get_role_bag_slots(self.role_id, 1, 150)
        got = sorted((s['goods_id'], s['count'], s['bind']) for s in slots)
        self.assertEqual(got, sorted(FIRST_GOODS))

    # Daily claim (58019).

    def test_reward_repeat(self):
        self.seed_row(baidu_yingyin=1)
        body = self.one(self.sess_as().yingyin_reward())
        self.assertEqual(body, ['58019', [0, '592013']])

    def test_reward_past_window(self):
        old = int(time.time() * 1000) - 31 * 86400 * 1000
        sess = self.sess_as(start_ms=old)
        body = self.one(sess.yingyin_reward())
        self.assertEqual(body, ['58019', [0, '592014']])

    def test_reward_bag_full(self):
        self.seed_row()
        self.store.save_role_bag_state(self.role_id, bag_capacity=0)
        body = self.one(self.sess_as().yingyin_reward())
        self.assertEqual(body, ['58019', [0, 1006]])

    def test_reward_success_lists_pairs(self):
        body = self.one(self.sess_as().yingyin_reward())
        self.assertEqual(body, ['58019', [1, [[gid, count]
                                             for gid, count, _
                                             in FIRST_GOODS]]])
        row = self.store.get_role_jiangli_list(self.role_id)
        self.assertEqual(row['baidu_yingyin'], 1)

    def test_no_role_silent(self):
        sess = self.sess_as()
        sess.get_roles = lambda u, s: []
        self.assertIsNone(sess.yingyin_state())
        self.assertIsNone(sess.yingyin_xiazai())
        self.assertIsNone(sess.yingyin_reward())


if __name__ == '__main__':
    unittest.main()

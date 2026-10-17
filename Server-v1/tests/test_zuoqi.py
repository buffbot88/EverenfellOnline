"""Mount panel/ride/claim: 33001 reads the rank row, 33000 rides, 33004 claims.

Evidence: ZuoQiAction.ZuoqiMianban/rideZuoQi/lingquZuoqi and
RoleZuoQiServiceImpl.getZuoQiPannel/rideZuoqi/changeZuoqiRank (33000 clamps
the ridden rank and stage-pushes [roleId, rank]; 33001 answers
[1, [rank, level, lucky, fight], [], kaifu, cost] or [0, [520005]] with no
mount; 33004 sets rank 1 once and stays silent past the rank gate).
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..',
                           'reference', 'TonNgoKhong', 'server', 'config',
                           'game')
HAVE_REAL = os.path.isdir(REAL_CONFIG)


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class ZuoqiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'z.db'))
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
            get_role_zuoqi=self.store.get_role_zuoqi,
            save_role_zuoqi=self.store.save_role_zuoqi,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'

    @staticmethod
    def frames(out):
        if isinstance(out, (bytes, bytearray)):
            return [decode(bytes(out)[4:])]
        return [decode(bytes(f)[4:]) for f in out]

    def test_panel_without_mount_is_empty_33001(self):
        out = self.sess.zuoqi_panel(['33001', ['hero', 1]])
        (frame,) = self.frames(out)
        self.assertEqual(frame[0], '33001')
        self.assertEqual(frame[1], [0, [520005]])
        row = self.store.get_role_zuoqi(self.role_id)
        self.assertEqual((row['zuoqi_rank'], row['zuoqi_cur_rank'],
                          row['lucky_value']), (0, 0, 0))

    def test_claim_grants_rank1_33004_then_silent(self):
        (frame,) = self.frames(self.sess.zuoqi_claim())
        self.assertEqual(frame[0], '33004')
        self.assertEqual(frame[1][0], 1)
        self.assertEqual(frame[1][1], 1)
        row = self.store.get_role_zuoqi(self.role_id)
        self.assertEqual((row['zuoqi_rank'], row['zuoqi_cur_rank']), (1, 1))
        self.assertIsNone(self.sess.zuoqi_claim())

    def test_ride_clamps_and_stage_pushes_33000(self):
        self.sess.zuoqi_claim()
        (frame,) = self.frames(self.sess.zuoqi_ride(['33000', ['x', 1]]))
        self.assertEqual(frame[0], '33000')
        self.assertEqual(frame[1], [str(self.role_id), 1])
        self.assertEqual(
            self.store.get_role_zuoqi(self.role_id)['zuoqi_cur_rank'], 1)
        # Past the owned rank falls back to the owned rank.
        (frame,) = self.frames(self.sess.zuoqi_ride(['33000', ['x', 5]]))
        self.assertEqual(frame[1][1], 1)
        # Dismounting to 0 is allowed.
        (frame,) = self.frames(self.sess.zuoqi_ride(['33000', ['x', 0]]))
        self.assertEqual(frame[1][1], 0)

    def test_panel_with_mount_33001(self):
        self.sess.zuoqi_claim()
        (frame,) = self.frames(self.sess.zuoqi_panel(['33001', ['x', 1]]))
        self.assertEqual(frame[0], '33001')
        head, inner, items, kaifu, cost = frame[1]
        self.assertEqual(head, 1)
        self.assertEqual(inner[0], 1)
        self.assertEqual(inner[1], self.cfg.zuoqi_rank_config(1)['max_level']
                         if 56 > self.cfg.zuoqi_rank_config(1)['max_level']
                         else 56)
        self.assertEqual(inner[2], 0)
        self.assertEqual(inner[3], self.cfg.zuoqi_fight(1, 56))
        self.assertGreater(inner[3], 0)
        # server_start_ms 0 reads as kaifu day 0, inside the 3-day window.
        self.assertEqual((items, kaifu, cost), ([], True, 0))
        self.sess.server_start_ms = (
            __import__('time').time() * 1000 - 10 * 86400 * 1000)
        (frame,) = self.frames(self.sess.zuoqi_panel(['33001', ['x', 1]]))
        self.assertEqual(frame[1][3:], [[], False, 0])

    def test_stale_day_restamps_update_time(self):
        self.sess.zuoqi_claim()
        self.store.save_role_zuoqi(self.role_id, 1, 1, 7, 1)
        before = self.store.get_role_zuoqi(self.role_id)['update_time']
        self.sess.zuoqi_panel(['33001', ['x', 1]])
        after = self.store.get_role_zuoqi(self.role_id)['update_time']
        self.assertNotEqual(before, after)
        self.assertTrue(self.sess._same_day_ms(
            __import__('time').time() * 1000, after))

    def test_rank_config_and_kaifu_rows(self):
        cfg = self.cfg.zuoqi_rank_config(1)
        self.assertEqual(cfg['rank'], 1)
        self.assertTrue(cfg['name'])
        self.assertGreaterEqual(cfg['need_level'], 0)
        self.assertIsNone(self.cfg.zuoqi_rank_config(999))
        self.assertEqual(self.cfg.zuoqi_max_rank(), 10)
        kai = self.cfg.kaifu_zuoqi_config(1)
        self.assertEqual(kai['last_days'], 3)
        self.assertIsNone(self.cfg.kaifu_zuoqi_config(9))
        self.assertEqual(self.cfg.kaifu_zuoqi_fanhuan()['rank'], 4)


if __name__ == '__main__':
    unittest.main()

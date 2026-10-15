"""Chat goldens: 11000 level-gated normal chat, 10050 area broadcast, 10051 whisper.

Oracle: RoleBehaviourServiceImpl.normalChat (XianlingConfigUtil chat_level gate,
surround addMsg '11000' with the client data), StageInfoServiceImpl.arroundBroadcast
(surround '10050' [roleId, data]) and point2point (send2One '10051' [sender, content]),
from dntg_start.jar via tools/javap.py. chat_level comes from config/localization.properties.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import amf3  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402


def make_config(chat_level):
    root = tempfile.mkdtemp()
    cfg_dir = os.path.join(root, 'game')
    os.makedirs(cfg_dir)
    with open(os.path.join(root, 'localization.properties'), 'w', encoding='utf-8') as f:
        f.write(f'chat_level = {chat_level}\n')
    return GameConfig(cfg_dir), root


def decode(frames):
    return [amf3.decode(f[4:]) for f in frames]


class ChatTest(unittest.TestCase):
    def setUp(self):
        self.cfg, root = make_config(1)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.reg = StageRegistry()

    def session(self, conn_id, role_id, level=1, x=1, y=3, map_id='7'):
        role = {'id': role_id, 'map_id': map_id, 'map_x': x, 'map_y': y,
                'level': level, 'exp': 0, 'zhenqi': 0}
        sess = Session(conn_id=conn_id, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [role], server_start_ms=0,
                       config=self.cfg, stage_registry=self.reg)
        self.reg.register(str(role_id), map_id, sess, x=x, y=y)
        return sess

    def test_normal_chat_broadcasts_to_surround_including_self(self):
        a = self.session(1, 1)
        out = a.normal_chat([11000, [1, 'x', 'hello']])
        self.assertEqual(decode([out[0]]), [['11000', [1, 'x', 'hello']]])

    def test_normal_chat_below_level_is_silent(self):
        cfg, root = make_config(5)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.cfg = cfg
        a = self.session(1, 1, level=2)
        self.assertIsNone(a.normal_chat([11000, [1, 'x', 'hi']]))

    def test_normal_chat_skips_roles_outside_surround(self):
        a = self.session(1, 1, x=1, y=3)
        b = self.session(2, 2, x=50, y=3)  # far cell
        a.normal_chat([11000, [1, 'x', 'hi']])
        self.assertEqual(b.tick(now_ms=0), None)
        self.assertEqual(decode(a.tick(now_ms=0) or []), [])

    def test_area_chat_reaches_neighbour_on_other_session(self):
        a = self.session(1, 1)
        b = self.session(2, 2, x=2, y=3)
        out = a.area_chat([10050, ['hi']])
        self.assertEqual(decode([out[0]]), [['10050', ['1', ['hi']]]])
        self.assertEqual(decode(b.tick(now_ms=0)), [['10050', ['1', ['hi']]]])

    def test_whisper_delivers_to_target_on_its_tick(self):
        a = self.session(1, 1)
        b = self.session(2, 2, x=50)
        self.assertIsNone(a.whisper([10051, ['2', 'secret']]))
        self.assertEqual(decode(b.tick(now_ms=0)), [['10051', ['1', 'secret']]])

    def test_whisper_to_offline_role_is_silent(self):
        a = self.session(1, 1)
        self.assertIsNone(a.whisper([10051, ['ghost', 'hi']]))

    def test_chat_without_placed_role_is_silent(self):
        sess = Session(conn_id=9, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [], server_start_ms=0,
                       config=self.cfg, stage_registry=self.reg)
        self.assertIsNone(sess.normal_chat([11000, [1, 'x', 'hi']]))
        self.assertIsNone(sess.area_chat([10050, ['hi']]))


if __name__ == '__main__':
    unittest.main()

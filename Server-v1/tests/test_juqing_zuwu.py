"""Golden tests for the story-copy (64001/64010) and clan-copy (108001) info routes.

Evidence: JuQingFuBenAction.getInfo/getAwards and ZuwufubenServiceImpl.getInfo
via tools/javap.py against dntg_start.jar (see docs/server-roadmap.md Phase 1
evidence log). No progress tables are migrated, so every role reads back the
fresh-role defaults; the tests pin those wire shapes through dispatch.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import amf3  # noqa: E402
from game.protocol import (CMD_JUQING_AWARD, CMD_JUQING_INFO,  # noqa: E402
                           CMD_ZUWUFUBEN, Session, frame)
from db import Store  # noqa: E402

# Live-captured first frame from the original client (see test_protocol.py).
INITKEY_FRAME = bytes.fromhex('00000009060f494e49544b4559')


def dispatch(cmd):
    """Feed one client frame through dispatch, return decoded reply frames."""
    sess = Session(conn_id=1, check_sign=lambda *a: False,
                   get_roles=lambda u, s: [], server_start_ms=0, config=None)
    sess.feed(INITKEY_FRAME)
    out = sess.feed(frame(sess.cipher.encode(amf3.encode([cmd, None]))))
    return [amf3.decode(bytes(f)[4:]) for f in out]


class JuqingTest(unittest.TestCase):
    """Fresh-role 64001/64010 shapes with a seeded (role-less-safe) store.

    The handlers need an authenticated role, so these pin the shapes
    through a real Store row; the full lifecycle lives in
    test_juqing_fuben.py.
    """
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', 'pw')
        self.store.create_character('hero', 'fu1304', 'Wukong', level=30)

    def session(self):
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_juqing=self.store.get_role_juqing,
            save_role_juqing=self.store.save_role_juqing,
            save_role_state=self.store.update_character_state,
            config=None)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return sess

    def call(self, sess, method, *args):
        out = getattr(sess, method)(*args) if args else getattr(sess, method)()
        if out is None:
            return None
        frames = out if isinstance(out, tuple) else (out,)
        return [amf3.decode(bytes(f)[4:]) for f in frames]

    def test_info_fresh_role_shape(self):
        self.assertEqual(self.call(self.session(), 'juqing_info'),
                         [['64001', [1, [0, None, None, None]]]])

    def test_award_without_progress_is_null(self):
        self.assertEqual(self.call(self.session(), 'juqing_award'),
                         [['64010', None]])


class ZuwufubenTest(unittest.TestCase):
    def test_info_fresh_role_shape(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(os.path.join(tmp.name, 't.db'))
        self.addCleanup(store.close)
        store.create_account('hero', 'pw')
        store.create_character('hero', 'fu1304', 'Wukong', level=30)
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    store.list_roles(u, s)],
            server_start_ms=0,
            get_role_zuwufuben=store.get_role_zuwufuben,
            save_role_zuwufuben=store.save_role_zuwufuben,
            config=None)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        out = sess.zuwufuben_info()
        frames = out if isinstance(out, tuple) else (out,)
        self.assertEqual([amf3.decode(bytes(f)[4:]) for f in frames],
                         [['108001', [1, [0, [['1', 0, 1]], None]]]])


if __name__ == '__main__':
    unittest.main()

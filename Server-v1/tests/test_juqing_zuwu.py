"""Golden tests for the story-copy (64001/64010) and clan-copy (108001) info routes.

Evidence: JuQingFuBenAction.getInfo/getAwards and ZuwufubenServiceImpl.getInfo
via tools/javap.py against dntg_start.jar (see docs/server-roadmap.md Phase 1
evidence log). No progress tables are migrated, so every role reads back the
fresh-role defaults; the tests pin those wire shapes through dispatch.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import amf3  # noqa: E402
from game.protocol import (CMD_JUQING_AWARD, CMD_JUQING_INFO,  # noqa: E402
                           CMD_ZUWUFUBEN, Session, frame)

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
    def test_info_fresh_role_shape(self):
        self.assertEqual(dispatch(CMD_JUQING_INFO),
                         [['64001', [1, [0, None, None, None]]]])

    def test_award_without_progress_is_null(self):
        self.assertEqual(dispatch(CMD_JUQING_AWARD), [['64010', None]])


class ZuwufubenTest(unittest.TestCase):
    def test_info_fresh_role_shape(self):
        self.assertEqual(dispatch(CMD_ZUWUFUBEN),
                         [['108001', [1, [0, [['1', 0, 1]], None]]]])


if __name__ == '__main__':
    unittest.main()

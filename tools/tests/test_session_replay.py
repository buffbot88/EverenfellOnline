"""Generalized replay harness: filtering, grouping and per-command diff."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'Server-v1'))

import session_replay as sr  # noqa: E402


def msg(direction, cmd, args):
    return {'dir': direction, 'cmd': cmd, 'args': args, 'line': 1,
            'truncated': False}


class ClientSequenceTest(unittest.TestCase):
    def test_tap_order_and_cmd_filter(self):
        tap = [msg('C', 42002, [[1]]), msg('S', 42002, [[2]]),
               msg('C', 42001, [[3]]), msg('C', 42002, [[4]])]
        self.assertEqual(sr.client_sequence(tap),
                         [[42002, [1]], [42001, [3]], [42002, [4]]])
        self.assertEqual(sr.client_sequence(tap, cmds=[42002]),
                         [[42002, [1]], [42002, [4]]])

    def test_limit_and_truncated_skip(self):
        tap = [msg('C', 1, [[1]]), msg('C', 2, None), msg('C', 3, [[3]])]
        tap[1]['truncated'] = True
        self.assertEqual(sr.client_sequence(tap), [[1, [1]], [3, [3]]])
        self.assertEqual(sr.client_sequence(tap, limit=1), [[1, [1]]])


class CompareTest(unittest.TestCase):
    def test_match_diff_missing_extra(self):
        java = [msg('S', 42002, [[1]]), msg('S', 42002, [[2]]),
                msg('S', 999, [[9]])]
        py = [[42002, [1]], [42002, [3]], [42001, [7]]]
        got = sr.compare_sequences(java, py)
        self.assertEqual(got[42002]['match'], 1)
        self.assertEqual(got[42002]['diff'], 1)
        self.assertEqual(got[999]['missing'], 1)
        self.assertEqual(got[42001]['extra'], 1)

    def test_volatile_paths_are_ignored(self):
        java = [msg('S', 19001, [[111]])]
        py = [[19001, [222]]]
        got = sr.compare_sequences(java, py, volatile={19001: ('[0]',)})
        self.assertEqual(got[19001]['match'], 1)
        self.assertEqual(got[19001]['diff'], 0)

    def test_replay_window_scopes_the_java_side(self):
        tap = [msg('C', 1, [[1]]), msg('S', 9, [[9]]),
               msg('C', 2, [[2]]), msg('S', 9, [[8]])]
        tap[0]['line'], tap[1]['line'], tap[2]['line'], tap[3]['line'] = 1, 2, 3, 4
        msgs, last = sr.replay_window(tap, limit=1)
        self.assertEqual(msgs, [[1, [1]]])
        self.assertEqual(last, 1)
        run = {'sent': msgs, 'replies': [], 'last_line': last}
        java = [m for m in tap if m['dir'] == 'S' and m['line'] <= run['last_line']]
        self.assertEqual(len(java), 0)

    def test_truncated_java_excluded(self):
        bad = msg('S', 5, None)
        bad['truncated'] = True
        got = sr.compare_sequences([bad], [])
        self.assertEqual(got, {})


if __name__ == '__main__':
    unittest.main()

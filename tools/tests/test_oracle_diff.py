"""Tests for tools/oracle-diff.py: signs, comparison, and the socket loop.

The socket tests run two in-process fake game servers, so no live Java or
Python server (and no web login) is needed.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import socketserver
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(os.path.dirname(TOOLS), 'Server-v1'))

_spec = importlib.util.spec_from_file_location(
    'oracle_diff', os.path.join(TOOLS, 'oracle-diff.py'))
od = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(od)

from game import amf3                      # noqa: E402
from game.cipher import SimpleEncrypt      # noqa: E402
import auth                                # noqa: E402

KEY = '0123456789abcdef0123456789abcdef'


class SignTest(unittest.TestCase):
    def test_legacy_sign_is_the_java_md5(self):
        expected = hashlib.md5(b'stressxianlingkey1700000000').hexdigest()
        self.assertEqual(od.legacy_sign('stress', 1700000000), expected)

    def test_hmac_sign_matches_the_python_web_sign(self):
        saved = auth._sign_secret
        self.addCleanup(lambda: setattr(auth, '_sign_secret', saved))
        old = os.environ.get('MKO_SIGN_SECRET')
        self.addCleanup(lambda: os.environ.pop('MKO_SIGN_SECRET', None)
                        if old is None
                        else os.environ.__setitem__('MKO_SIGN_SECRET', old))
        os.environ['MKO_SIGN_SECRET'] = 'diff-secret'
        auth._sign_secret = None
        ts = '1700000000'
        self.assertEqual(od.hmac_sign('diff-secret', 'stress', ts),
                         auth.generate_sign('stress', ts))


class ParseCmdTest(unittest.TestCase):
    def test_bare_id_has_no_arguments(self):
        self.assertEqual(od.parse_cmd('58011'), (58011, []))

    def test_json_arguments_are_decoded(self):
        self.assertEqual(od.parse_cmd('41023:["sj0101"]'), (41023, ['sj0101']))

    def test_bad_id_is_a_setup_error(self):
        with self.assertRaises(od.SetupError):
            od.parse_cmd('abc')

    def test_non_list_arguments_are_rejected(self):
        with self.assertRaises(od.SetupError):
            od.parse_cmd('41023:{"id":"sj0101"}')


class NormalizeTest(unittest.TestCase):
    def test_int_and_double_compare_equal(self):
        self.assertIsNone(od.compare(['58011', [1, 0]],
                                     ['58011', [1.0, 0.0]]))

    def test_nested_numbers_are_normalized(self):
        self.assertIsNone(od.compare({'a': [1, {'b': 2}]},
                                     {'a': [1.0, {'b': 2.0}]}))

    def test_strings_and_numbers_stay_distinct(self):
        self.assertIsNotNone(od.compare(['58011', [1]], ['58011', ['1']]))


class FirstDiffTest(unittest.TestCase):
    def test_reports_the_first_differing_index(self):
        diff = od.first_diff([1, [2, 3]], [1, [2, 4]])
        self.assertEqual(diff, '$[1][1]: java=3 python=4')

    def test_reports_length_differences(self):
        self.assertEqual(od.first_diff([1], [1, 2]),
                         '$: length java=1 python=2')

    def test_reports_a_missing_object_key(self):
        self.assertEqual(od.first_diff({'a': 1}, {}),
                         '$.a: python missing, java=1')


class FakeGameServer(socketserver.ThreadingTCPServer):
    """Answers INITKEY/login/10003 and one configured reply per command."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, replies, pushes=None, late_pushes=None,
                 late_delay=0.15, notifications=None,
                 late_notifications=None):
        self.replies = replies
        self.pushes = pushes or []
        self.late_pushes = late_pushes or []
        self.late_delay = late_delay
        self.notifications = notifications or {}
        self.late_notifications = late_notifications or {}
        self.seen = []
        super().__init__(('127.0.0.1', 0), _FakeHandler)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self.server_address[1]

    def stop(self):
        self.shutdown()
        self.server_close()


class _FakeHandler(socketserver.BaseRequestHandler):
    def _read_frame(self):
        head = self._recv(4)
        if head is None:
            return None
        length = struct.unpack('>I', head)[0]
        body = self._recv(length)
        return None if body is None else head + body

    def _recv(self, size):
        buf = b''
        while len(buf) < size:
            chunk = self.request.recv(size - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def handle(self):
        first = self._read_frame()
        if first is None or amf3.decode(first[4:]) != 'INITKEY':
            return
        self.request.sendall(struct.pack('>I', len(KEY)) + KEY.encode())
        cipher = SimpleEncrypt(KEY)
        while True:
            raw = self._read_frame()
            if raw is None:
                return
            try:
                msg = amf3.decode(cipher.decode(raw[4:]))
                cmd_id = int(msg[0])
            except Exception:
                return
            self.server.seen.append(msg)
            reply = self.server.replies.get(cmd_id)
            for notify in self.server.notifications.get(cmd_id, []):
                self._send(notify)
            if reply is not None:
                self._send(reply)
            if cmd_id in self.server.late_notifications:
                threading.Thread(target=self._late_notify,
                                 args=(cmd_id,), daemon=True).start()
            if cmd_id == 21000:
                for push in self.server.pushes:
                    self._send(push)
                if self.server.late_pushes:
                    threading.Thread(target=self._late, daemon=True).start()

    def _send(self, msg):
        payload = amf3.encode(msg)
        try:
            self.request.sendall(struct.pack('>I', len(payload)) + payload)
        except OSError:
            pass

    def _late(self):
        time.sleep(self.server.late_delay)
        for push in self.server.late_pushes:
            self._send(push)

    def _late_notify(self, cmd_id):
        time.sleep(self.server.late_delay)
        for notify in self.server.late_notifications.get(cmd_id, []):
            self._send(notify)


LOGIN_OK = ['10001', [1, [0.0, 0.0], [0, 0], []]]
ROLE_OK = ['10003', [1]]


def fake_args(java_port, python_port, cmds, push_window=0.3, **overrides):
    """Namespace as argparse would build it, pointed at two fake servers."""
    args = argparse.Namespace(
        java=f'127.0.0.1:{java_port}', python=f'127.0.0.1:{python_port}',
        python_web='', python_secret='diff-secret', user='stress',
        password='', uid='stress', server='fu1304',
        role='fu0UR1-10-0-1', java_role='', python_role='',
        cmd=cmds, timeout=1.0, settle=0.1, width=200, report='',
        push_window=push_window, notify_window=0.2, baseline='',
        push_ignore=[], reply_ignore=[], write_baseline='')
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


class ClientTest(unittest.TestCase):
    def test_handshake_world_entry_and_command(self):
        server = FakeGameServer({10001: LOGIN_OK, 10003: ROLE_OK,
                                 58011: ['58011', [1, None, 0, None, None]]})
        port = server.start()
        self.addCleanup(server.stop)
        client = od.Client('fake', '127.0.0.1', port, 'stress', 'fu1304',
                           od.legacy_sign('stress', 1), 1,
                           timeout=1.0, settle=0.1)
        try:
            client.login()
            client.world_entry('fu0UR1-10-0-1')
            reply, _ = client.request(58011, [None])
        finally:
            client.close()
        self.assertEqual(reply, ['58011', [1, None, 0, None, None]])
        # The login frame carries one nested array, as the captured client does.
        self.assertIsInstance(server.seen[0][1], list)
        self.assertEqual(server.seen[0][1][0], 'stress')
        # A bare command pads the missing argument with null, like the client.
        self.assertEqual(server.seen[-1], [58011, None])

    def test_login_rejected_raises_setup_error(self):
        server = FakeGameServer({10001: ['10001', [0, '16002']]})
        port = server.start()
        self.addCleanup(server.stop)
        client = od.Client('fake', '127.0.0.1', port, 'stress', 'fu1304',
                           'bad', 1, timeout=1.0, settle=0.1)
        try:
            with self.assertRaises(od.SetupError):
                client.login()
        finally:
            client.close()


def run_fakes(case, java_reply, python_reply, cmds=('58011',),
              java_pushes=None, python_pushes=None, java_late=None,
              java_notifications=None, python_notifications=None,
              java_late_notifications=None, push_window=0.3, **overrides):
    """Run both sides against fake servers registered for cleanup on `case`."""
    java = FakeGameServer({10001: LOGIN_OK, 10003: ROLE_OK, 58011: java_reply},
                          pushes=java_pushes, late_pushes=java_late,
                          notifications=java_notifications,
                          late_notifications=java_late_notifications)
    python = FakeGameServer({10001: LOGIN_OK, 10003: ROLE_OK,
                             58011: python_reply}, pushes=python_pushes,
                            notifications=python_notifications)
    case.addCleanup(java.stop)
    case.addCleanup(python.stop)
    return od.run(fake_args(java.start(), python.start(), list(cmds),
                            push_window=push_window, **overrides))


class RunTest(unittest.TestCase):
    def _run(self, java_reply, python_reply, cmds=('58011',),
             java_pushes=None, python_pushes=None, java_late=None,
             push_window=0.3, **overrides):
        return run_fakes(self, java_reply, python_reply, cmds,
                         java_pushes=java_pushes,
                         python_pushes=python_pushes,
                         java_late=java_late, push_window=push_window,
                         **overrides)

    def test_matching_replies_report_no_mismatch(self):
        lines, mismatches, push_issues, _ = self._run(
            ['58011', [1, None, 0, None, None]],
            ['58011', [1, None, 0, None, None]])
        self.assertEqual(mismatches, 0)
        self.assertEqual(push_issues, 0)
        self.assertIn('   MATCH', lines)

    def test_differing_replies_report_the_first_field(self):
        lines, mismatches, _, _ = self._run(
            ['58011', [1, None, 0, None, None]],
            ['58011', [1, [], 1, [], []]])
        self.assertEqual(mismatches, 1)
        joined = '\n'.join(lines)
        self.assertIn('MISMATCH: $[1][1]', joined)

    def test_silent_server_counts_as_a_mismatch(self):
        lines, mismatches, _, _ = self._run(
            ['58011', [1, None, 0, None, None]], None)
        self.assertEqual(mismatches, 1)
        self.assertIn('no reply from python', '\n'.join(lines))


class PushTest(unittest.TestCase):
    REPLY = ['58011', [1]]

    def test_only_on_one_side_is_reported(self):
        lines, _, push_issues, _ = run_fakes(
            self, self.REPLY, self.REPLY,
            java_pushes=[['23003', [['N020001', 6, 152]]],
                         ['40000', [1, 2]]],
            python_pushes=[['23003', [['N020001', 6, 152]]]])
        joined = '\n'.join(lines)
        self.assertEqual(push_issues, 1)
        self.assertIn('PUSH-MATCH 23003', joined)
        self.assertIn('PUSH-ONLY java 40000 (x1)', joined)

    def test_single_push_values_are_compared(self):
        lines, _, push_issues, _ = run_fakes(
            self, self.REPLY, self.REPLY,
            java_pushes=[['12004', [1, 348.0]]],
            python_pushes=[['12004', [1, 348.5]]])
        joined = '\n'.join(lines)
        self.assertEqual(push_issues, 1)
        self.assertIn('PUSH-DIFF 12004: $[1][1]', joined)

    def test_repeated_pushes_compare_presence_only(self):
        lines, _, push_issues, _ = run_fakes(
            self, self.REPLY, self.REPLY,
            java_pushes=[['40000', [1]], ['40000', [9]]],
            python_pushes=[['40000', [2]], ['40000', [3]]])
        joined = '\n'.join(lines)
        self.assertEqual(push_issues, 0)
        self.assertIn('PUSH-BOTH 40000 (x2/x2, values not compared)', joined)

    def test_zero_window_disables_the_comparison(self):
        lines, _, push_issues, _ = run_fakes(
            self, self.REPLY, self.REPLY,
            java_pushes=[['40000', [1]]], python_pushes=[],
            push_window=0)
        joined = '\n'.join(lines)
        self.assertEqual(push_issues, 0)
        self.assertNotIn('push stream', joined)
        self.assertIn('0 push issues', joined)

    def test_a_late_push_arrives_inside_the_window(self):
        lines, _, push_issues, _ = run_fakes(
            self, self.REPLY, self.REPLY,
            java_late=[['23003', [['N020001', 6, 152]]]],
            push_window=0.6)
        joined = '\n'.join(lines)
        self.assertEqual(push_issues, 1)
        self.assertIn('PUSH-ONLY java 23003', joined)


class BaselineTest(unittest.TestCase):
    REPLY = ['58011', [1]]
    JAVA_PUSH = [['12004', [1, 348.0]]]
    PYTHON_PUSH = [['12004', [1, 253.0]]]
    DIFF = "$[1][1]: java=348.0 python=253.0"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, 'baseline.json')

    def _write(self, data):
        with open(self.path, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)

    def _run(self, **overrides):
        return run_fakes(self, self.REPLY, self.REPLY,
                         java_pushes=self.JAVA_PUSH,
                         python_pushes=self.PYTHON_PUSH, **overrides)

    def test_ignored_id_is_skipped_entirely(self):
        lines, _, push_issues, _ = run_fakes(
            self, self.REPLY, self.REPLY,
            java_pushes=[['40000', [1]]], python_pushes=[],
            push_ignore=['40000'])
        joined = '\n'.join(lines)
        self.assertEqual(push_issues, 0)
        self.assertIn('ignored ids: 40000', joined)
        self.assertNotIn('PUSH-ONLY', joined)

    def test_matching_baseline_does_not_fail_the_run(self):
        self._write({'baseline': {'12004': self.DIFF}})
        lines, _, push_issues, _ = self._run(baseline=self.path)
        joined = '\n'.join(lines)
        self.assertEqual(push_issues, 0)
        self.assertIn('PUSH-BASELINED 12004', joined)

    def test_changed_diff_is_still_an_issue(self):
        self._write({'baseline': {'12004': 'some old value'}})
        lines, _, push_issues, _ = self._run(baseline=self.path)
        joined = '\n'.join(lines)
        self.assertEqual(push_issues, 1)
        self.assertIn('PUSH-DIFF 12004', joined)

    def test_stale_baseline_is_reported_without_failing(self):
        self._write({'baseline': {'12004': self.DIFF}})
        lines, _, push_issues, _ = run_fakes(
            self, self.REPLY, self.REPLY,
            java_pushes=[['12004', [1, 348.0]]],
            python_pushes=[['12004', [1, 348.0]]],
            baseline=self.path)
        joined = '\n'.join(lines)
        self.assertEqual(push_issues, 0)
        self.assertIn('PUSH-BASELINE-STALE 12004', joined)

    def test_written_baseline_makes_the_next_run_pass(self):
        lines, _, push_issues, _ = self._run(write_baseline=self.path)
        self.assertEqual(push_issues, 1)
        self.assertIn('baseline written', '\n'.join(lines))
        ignore, known = od.load_push_baseline(self.path)
        self.assertEqual(ignore, set())
        self.assertEqual(known, {'12004': self.DIFF})
        lines, _, push_issues, _ = self._run(baseline=self.path)
        self.assertEqual(push_issues, 0)
        self.assertIn('PUSH-BASELINED 12004', '\n'.join(lines))

    def test_written_baseline_keeps_the_ignore_list(self):
        self._run(push_ignore=['40000'], write_baseline=self.path)
        ignore, known = od.load_push_baseline(self.path)
        self.assertEqual(ignore, {'40000'})
        self.assertEqual(known, {'12004': self.DIFF})

    def test_writing_without_a_push_window_keeps_the_push_section(self):
        self._write({'push': {'ignore': ['42100'],
                              'baseline': {'12004': 'kept'}}})
        self._run(push_window=0, write_baseline=self.path)
        base = od.load_baseline(self.path)
        self.assertEqual(base['push'], ({'42100'}, {'12004': 'kept'}))

    def test_bad_baseline_file_is_a_setup_error(self):
        self._write({'baseline': {'12004': 5}})
        with self.assertRaises(od.SetupError):
            od.load_push_baseline(self.path)


class ReplyBaselineTest(unittest.TestCase):
    JAVA = ['58011', [1]]
    PYTHON = ['58011', [2]]
    DIFF = '$[1][0]: java=1.0 python=2.0'
    UNSET = object()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, 'baseline.json')

    def _write(self, data):
        with open(self.path, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)

    def _run(self, java_reply=UNSET, python_reply=UNSET, **overrides):
        return run_fakes(
            self,
            self.JAVA if java_reply is self.UNSET else java_reply,
            self.PYTHON if python_reply is self.UNSET else python_reply,
            push_window=0.2, **overrides)

    def test_baselined_reply_does_not_fail(self):
        self._write({'reply': {'baseline': {'58011': self.DIFF}}})
        lines, mismatches, _, _ = self._run(baseline=self.path)
        joined = '\n'.join(lines)
        self.assertEqual(mismatches, 0)
        self.assertIn('BASELINED', joined)

    def test_changed_reply_diff_still_fails(self):
        self._write({'reply': {'baseline': {'58011': 'an old diff'}}})
        lines, mismatches, _, _ = self._run(baseline=self.path)
        self.assertEqual(mismatches, 1)
        self.assertIn('MISMATCH', '\n'.join(lines))

    def test_reply_ignore_skips_the_comparison(self):
        lines, mismatches, _, _ = self._run(reply_ignore=['58011'])
        self.assertEqual(mismatches, 0)
        self.assertIn('IGNORED', '\n'.join(lines))

    def test_a_missing_reply_can_be_baselined(self):
        self._write({'reply': {'baseline': {
            '58011': 'no reply from python'}}})
        lines, mismatches, _, _ = self._run(python_reply=None, baseline=self.path)
        self.assertEqual(mismatches, 0)
        self.assertIn('BASELINED: no reply from python', '\n'.join(lines))

    def test_stale_reply_baseline_is_reported_without_failing(self):
        self._write({'reply': {'baseline': {'58011': self.DIFF}}})
        lines, mismatches, _, _ = self._run(
            python_reply=self.JAVA, baseline=self.path)
        self.assertEqual(mismatches, 0)
        self.assertIn('REPLY-BASELINE-STALE 58011', '\n'.join(lines))

    def test_write_records_both_channels(self):
        lines, mismatches, _, _ = self._run(
            java_pushes=[['12004', [1, 348.0]]],
            python_pushes=[['12004', [1, 253.0]]],
            write_baseline=self.path)
        self.assertEqual(mismatches, 1)
        self.assertIn('baseline written', '\n'.join(lines))
        base = od.load_baseline(self.path)
        self.assertEqual(base['push'][1], {
            '12004': '$[1][1]: java=348.0 python=253.0'})
        self.assertEqual(base['reply'][1], {'58011': self.DIFF})


class NotificationTest(unittest.TestCase):
    REPLY = ['58011', [1]]
    NOTIFY = ['30304', [1]]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, 'baseline.json')

    def _run(self, java_notifications=None, python_notifications=None,
             java_late_notifications=None, **overrides):
        return run_fakes(
            self, self.REPLY, self.REPLY,
            java_notifications=java_notifications,
            python_notifications=python_notifications,
            java_late_notifications=java_late_notifications, **overrides)

    def test_identical_notifications_match(self):
        lines, _, _, notify_issues = self._run(
            java_notifications={58011: [self.NOTIFY]},
            python_notifications={58011: [self.NOTIFY]})
        self.assertEqual(notify_issues, 0)
        self.assertIn('NOTIFY-MATCH 30304', '\n'.join(lines))

    def test_notification_seen_on_one_side_only(self):
        lines, _, _, notify_issues = self._run(
            java_notifications={58011: [self.NOTIFY]},
            python_notifications={})
        self.assertEqual(notify_issues, 1)
        self.assertIn('NOTIFY-ONLY java 30304', '\n'.join(lines))

    def test_notification_payload_is_compared(self):
        lines, _, _, notify_issues = self._run(
            java_notifications={58011: [['30304', [1]]]},
            python_notifications={58011: [['30304', [2]]]})
        self.assertEqual(notify_issues, 1)
        self.assertIn('NOTIFY-DIFF 30304: $[1][0]', '\n'.join(lines))

    def test_pre_reply_notification_is_seen_without_a_window(self):
        lines, _, _, notify_issues = self._run(
            java_notifications={58011: [self.NOTIFY]},
            python_notifications={58011: [self.NOTIFY]},
            notify_window=0)
        self.assertEqual(notify_issues, 0)
        self.assertIn('NOTIFY-MATCH 30304', '\n'.join(lines))

    def test_late_notification_needs_the_window(self):
        lines, _, _, notify_issues = self._run(
            java_late_notifications={58011: [self.NOTIFY]},
            notify_window=0.4)
        self.assertEqual(notify_issues, 1)
        self.assertIn('NOTIFY-ONLY java 30304', '\n'.join(lines))

    def test_late_notification_is_dropped_without_the_window(self):
        lines, _, _, notify_issues = self._run(
            java_late_notifications={58011: [self.NOTIFY]},
            notify_window=0)
        self.assertEqual(notify_issues, 0)
        joined = '\n'.join(lines)
        self.assertNotIn('NOTIFY-', joined)
        self.assertIn('pushes: none', joined)

    def test_baseline_suppresses_a_known_notification_diff(self):
        with open(self.path, 'w', encoding='utf-8') as handle:
            json.dump({'push': {'baseline': {
                '58011:30304': '$[1][0]: java=1.0 python=2.0'}}}, handle)
        lines, _, _, notify_issues = self._run(
            java_notifications={58011: [['30304', [1]]]},
            python_notifications={58011: [['30304', [2]]]},
            baseline=self.path)
        self.assertEqual(notify_issues, 0)
        self.assertIn('NOTIFY-BASELINED 30304', '\n'.join(lines))

    def test_ignore_skips_a_triggered_id(self):
        lines, _, _, notify_issues = self._run(
            java_notifications={58011: [['30304', [1]]]},
            python_notifications={58011: [['30304', [2]]]},
            push_ignore=['58011:30304'])
        self.assertEqual(notify_issues, 0)
        self.assertNotIn('NOTIFY-', '\n'.join(lines))

    def test_bare_ignore_also_covers_a_triggered_frame(self):
        lines, _, _, notify_issues = self._run(
            java_notifications={58011: [['30304', [1]]]},
            python_notifications={58011: [['30304', [2]]]},
            push_ignore=['30304'])
        self.assertEqual(notify_issues, 0)
        self.assertNotIn('NOTIFY-', '\n'.join(lines))

    def test_write_records_the_triggered_key(self):
        lines, _, _, _ = self._run(
            java_notifications={58011: [['30304', [1]]]},
            python_notifications={58011: [['30304', [2]]]},
            write_baseline=self.path)
        self.assertIn('baseline written', '\n'.join(lines))
        base = od.load_baseline(self.path)
        self.assertEqual(base['push'][1],
                         {'58011:30304': '$[1][0]: java=1.0 python=2.0'})


class MainExitTest(unittest.TestCase):
    """The exit contract the CI gate relies on: any issue class fails the run."""

    def _status(self, mismatches, push_issues, notify_issues):
        argv = ['oracle-diff', '--cmd', '58011', '--python-web', 'none']
        result = (['-- 58011'], mismatches, push_issues, notify_issues)
        with mock.patch.object(sys, 'argv', argv), \
                mock.patch.object(od, 'run', return_value=result):
            return od.main()

    def test_clean_run_exits_zero(self):
        self.assertEqual(self._status(0, 0, 0), 0)

    def test_reply_mismatch_exits_one(self):
        self.assertEqual(self._status(1, 0, 0), 1)

    def test_push_issue_alone_exits_one(self):
        self.assertEqual(self._status(0, 1, 0), 1)

    def test_notification_issue_alone_exits_one(self):
        self.assertEqual(self._status(0, 0, 1), 1)


if __name__ == '__main__':
    unittest.main()

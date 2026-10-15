"""Event bus goldens: EventCenter/EventType ordering, isolation, session wiring.

Oracle: EventCenter.subscribe/publish and EventType.subscribe/publish from
dntg_start.jar (javap): handlers sorted ascending by handleOrder, handler
exceptions logged (role_logout -> offlineError, others -> frameError) and
skipped, publish is a no-op with no subscribers. Inner tokens follow
StageMsgSender.send2StageInnerToken -> StageMsgDispatcher.in (routed command
run, not a bus publish). The state lock is this port's own addition.
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import eventbus as E  # noqa: E402
from game.protocol import Session  # noqa: E402


class Recorder:
    def __init__(self, name, log, fail=False):
        self.name = name
        self.log = log
        self.fail = fail

    def handle(self, source, data):
        self.log.append((self.name, source, data))
        if self.fail:
            raise RuntimeError(f'{self.name} broke')


class EventCenterTest(unittest.TestCase):
    def test_handlers_run_in_ascending_order(self):
        seen = []
        center = E.EventCenter()
        center.subscribe('ping', 30, Recorder('c', seen))
        center.subscribe('ping', 10, Recorder('a', seen))
        center.subscribe('ping', 20, Recorder('b', seen))
        center.publish(E.Event('ping', 'src', 'payload'))
        self.assertEqual([s[0] for s in seen], ['a', 'b', 'c'])
        self.assertEqual(seen[0], ('a', 'src', 'payload'))

    def test_equal_order_keeps_subscription_order(self):
        seen = []
        center = E.EventCenter()
        center.subscribe('t', 5, Recorder('first', seen))
        center.subscribe('t', 5, Recorder('second', seen))
        center.publish(E.Event('t'))
        self.assertEqual([s[0] for s in seen], ['first', 'second'])

    def test_publish_without_subscribers_is_silent(self):
        center = E.EventCenter()
        center.publish(E.Event('nobody'))  # must not raise
        self.assertEqual(center.subscriber_count('nobody'), 0)

    def test_failing_handler_is_isolated_and_logged(self):
        seen = []
        center = E.EventCenter()
        center.subscribe('t', 1, Recorder('bad', seen, fail=True))
        center.subscribe('t', 2, Recorder('good', seen))
        with self.assertLogs(E.log, level='WARNING') as logs:
            center.publish(E.Event('t', 'src'))
        self.assertEqual([s[0] for s in seen], ['bad', 'good'])
        self.assertTrue(any('handle error' in m for m in logs.output))

    def test_role_logout_failure_uses_offline_message(self):
        center = E.EventCenter()
        center.subscribe(E.ROLE_LOGOUT, 1, Recorder('bad', [], fail=True))
        with self.assertLogs(E.log, level='WARNING') as logs:
            center.publish(E.Event(E.ROLE_LOGOUT, 'role7'))
        self.assertTrue(any('offline error on role7' in m for m in logs.output))

    def test_types_are_independent(self):
        seen = []
        center = E.EventCenter()
        center.subscribe('a', 1, Recorder('a', seen))
        center.publish(E.Event('b'))
        self.assertEqual(seen, [])
        self.assertEqual(center.subscriber_count('a'), 1)


class SessionBusTest(unittest.TestCase):
    def build(self):
        return Session(conn_id=9, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [], server_start_ms=0)

    def test_session_publish_reaches_subscriber(self):
        sess = self.build()
        seen = []
        sess.subscribe('UseMoneyPropEvent', 1, Recorder('h', seen))
        sess.publish('UseMoneyPropEvent', source='role1', data={'n': 2})
        self.assertEqual(seen, [('h', 'role1', {'n': 2})])


class InnerTokenTest(unittest.TestCase):
    def build(self):
        return Session(conn_id=10, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [], server_start_ms=0)

    def test_routed_inner_token_frames_join_tick(self):
        sess = self.build()
        calls = []

        def handler(role_id, stage_id, data, token):
            calls.append((role_id, stage_id, data, token))
            return (b'PUSH',)

        sess.register_inner('AI:RETRIEVE', handler)
        sess.schedule_inner('k', 'stage', 'AI:RETRIEVE', 'r1', 's9',
                            {'n': 1}, 2, 'SECONDS', now_ms=1000)
        self.assertIsNone(sess.tick(now_ms=2999))
        self.assertEqual(sess.tick(now_ms=3000), (b'PUSH',))
        self.assertEqual(calls, [('r1', 's9', {'n': 1}, None)])
        self.assertEqual(sess.stage_scheduler.pending(), [])

    def test_inner_token_without_handler_is_silent(self):
        sess = self.build()
        sess.schedule_inner('k', 'stage', 'NOPE', 'r1', 's9', None, 0,
                            'SECONDS', now_ms=0)
        self.assertIsNone(sess.tick(now_ms=0))

    def test_inner_handler_returning_none_is_silent(self):
        sess = self.build()
        sess.register_inner('cmd', lambda r, s, d, t: None)
        sess.schedule_inner('k', 'stage', 'cmd', 'r1', 's9', None, 0,
                            'SECONDS', now_ms=0)
        self.assertIsNone(sess.tick(now_ms=0))

    def test_failing_inner_handler_contained(self):
        sess = self.build()

        def boom(r, s, d, t):
            raise RuntimeError('command blew up')

        sess.register_inner('cmd', boom)
        sess.schedule_inner('k', 'stage', 'cmd', 'r1', 's9', None, 0,
                            'SECONDS', now_ms=0)
        self.assertIsNone(sess.tick(now_ms=0))


class StateLockTest(unittest.TestCase):
    def build(self):
        return Session(conn_id=11, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [], server_start_ms=0)

    def test_tick_holds_state_lock_against_other_threads(self):
        sess = self.build()
        probe = {}

        def timer():
            def other():
                probe['got'] = sess.state_lock.acquire(blocking=False)
                if probe['got']:
                    sess.state_lock.release()
            t = threading.Thread(target=other)
            t.start()
            t.join()
            return None

        sess.schedule_stage('k', 'probe', timer, now_ms=0)
        sess.tick(now_ms=0)
        self.assertFalse(probe['got'])

    def test_lock_free_after_tick_and_feed(self):
        sess = self.build()
        sess.tick(now_ms=0)
        self.assertTrue(sess.state_lock.acquire(blocking=False))
        sess.state_lock.release()
        sess.feed(b'')
        self.assertTrue(sess.state_lock.acquire(blocking=False))
        sess.state_lock.release()

    def test_tick_is_reentrant_for_nested_ai_calls(self):
        # ai_tick runs inside tick under the same RLock; must not deadlock.
        sess = self.build()
        self.assertIsNone(sess.tick(now_ms=0))


if __name__ == '__main__':
    unittest.main()

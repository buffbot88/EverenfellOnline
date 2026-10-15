"""Scheduler mirror goldens: heartbeat, schedule map, quartz, tokens, tick.

Oracle: HeartBeatRateUtil.getHeartBeat, AiFightServiceImpl.calNextOptDelay,
IAi.XUNLUO_PERIOD/CRITICAL_RESPONSE_TIME, StageScheduleManager.scheduleMap,
QuartzScheduleExportServiceImpl ids, KuangZhanQuartz.init cron
('0 */1 * * * ?'), StageTokenRunable/BusTokenRunable.run, all from
dntg_start.jar via tools/javap.py.
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import scheduler as S  # noqa: E402
from game.protocol import Session  # noqa: E402


def minute_wall(second=0):
    return time.mktime((2026, 1, 1, 0, 5, second, 0, 0, -1))


class HeartBeatTest(unittest.TestCase):
    def test_idle_velocity_answers_400(self):
        self.assertEqual(S.heart_beat(0), 400)
        self.assertEqual(S.heart_beat(None), 400)

    def test_captured_monster_velocity(self):
        self.assertEqual(S.heart_beat(450), 370)  # D040011: 166682//450
        self.assertEqual(S.heart_beat(200), 833)
        self.assertEqual(S.heart_beat('450'), 370)

    def test_integer_division_truncates(self):
        self.assertEqual(S.heart_beat(-5), int(166682 / -5))


class NextOptDelayTest(unittest.TestCase):
    def test_dead_never_reschedules(self):
        self.assertEqual(S.next_opt_delay('DEAD', 450), -1)

    def test_xunluo_period_plus_roll(self):
        self.assertEqual(S.next_opt_delay('XUNLUO', 0, roll=0), 10000)
        self.assertEqual(S.next_opt_delay('XUNLUO', 0, roll=4999), 14999)

    def test_fight_uses_heartbeat(self):
        self.assertEqual(S.next_opt_delay('FIGHT', 450), 370)
        self.assertEqual(S.next_opt_delay(None, 0), 400)


class StageScheduleTest(unittest.TestCase):
    def test_due_order_and_firing(self):
        mgr = S.StageScheduleManager()
        mgr.schedule('b', 'cb', {'v': 2}, 6, 'SECONDS', now_ms=1000)
        mgr.schedule('a', 'ca', {'v': 1}, 5, 'SECONDS', now_ms=1000)
        self.assertEqual(mgr.pending(), ['a', 'b'])
        self.assertEqual(mgr.due(now_ms=5999), [])
        got = mgr.due(now_ms=7000)
        self.assertEqual([e['key'] for e in got], ['a', 'b'])
        self.assertEqual(mgr.pending(), [])

    def test_same_key_replaces(self):
        mgr = S.StageScheduleManager()
        mgr.schedule('k', 'old', None, 5, 'SECONDS', now_ms=0)
        mgr.schedule('k', 'new', None, 50, 'SECONDS', now_ms=0)
        self.assertEqual(mgr.pending(), ['k'])
        self.assertEqual(mgr.due(now_ms=6000), [])

    def test_cancel_and_clear(self):
        mgr = S.StageScheduleManager()
        mgr.schedule('k', 'c', None, 1, 'SECONDS', now_ms=0)
        self.assertTrue(mgr.cancel('k'))
        self.assertFalse(mgr.cancel('k'))
        mgr.schedule('k', 'c', None, 1, 'SECONDS', now_ms=0)
        mgr.clear()
        self.assertEqual(mgr.due(now_ms=99999), [])

    def test_minute_unit(self):
        mgr = S.StageScheduleManager()
        mgr.schedule('k', 'c', None, 1, 'MINUTES', now_ms=0)
        self.assertEqual(mgr.due(now_ms=59999), [])
        self.assertEqual(len(mgr.due(now_ms=60000)), 1)

    def test_unknown_unit_rejected(self):
        mgr = S.StageScheduleManager()
        with self.assertRaises(ValueError):
            mgr.schedule('k', 'c', None, 1, 'FORTNIGHTS', now_ms=0)

    def test_scoped_keeps_task_name_key(self):
        mgr = S.StageScheduleManager()
        mgr.schedule_scoped('stage9', 'retrieve', 'AI:RETRIEVE', None,
                            3, 'SECONDS', now_ms=0)
        self.assertEqual(mgr.pending(), ['retrieve'])
        got = mgr.due(now_ms=3000)
        self.assertEqual(got[0]['scope'], 'stage9')


class QuartzTest(unittest.TestCase):
    def test_job_ids_unique(self):
        sched = S.QuartzScheduler()
        a = sched.schedule_call(None, 'm', [], 1, 'SECONDS', now_ms=0)
        b = sched.schedule_call(None, 'm', [], 1, 'SECONDS', now_ms=0)
        self.assertNotEqual(a, b)

    def test_one_shot_calls_service(self):
        calls = []

        class Svc:
            def ping(self, *args):
                calls.append(('ping', list(args)))

        sched = S.QuartzScheduler()
        sched.schedule_call(Svc(), 'ping', ['a'], 5, 'SECONDS', now_ms=1000)
        self.assertEqual(sched.due(now_ms=5999, moment=minute_wall(30)), [])
        got = sched.due(now_ms=6000, moment=minute_wall(30))
        self.assertEqual(len(got), 1)
        self.assertEqual(calls, [('ping', ['a'])])
        self.assertEqual(sched.due(now_ms=6000, moment=minute_wall(30)), [])

    def test_missing_service_skipped(self):
        sched = S.QuartzScheduler()
        sched.schedule_call(None, 'checkKuangZhanStart', [], 0, 'SECONDS',
                            now_ms=0)
        self.assertEqual(len(sched.due(now_ms=0, moment=minute_wall(30))), 1)

    def test_kuangzhan_cron_fires_each_minute(self):
        self.assertTrue(S.cron_matches('0 */1 * * * ?', minute_wall(0)))
        self.assertFalse(S.cron_matches('0 */1 * * * ?', minute_wall(30)))

    def test_cron_fires_once_per_slot(self):
        calls = []

        class Svc:
            def checkKuangZhanStart(self):
                calls.append(1)

        sched = S.QuartzScheduler()
        sched.schedule_cron(Svc(), 'checkKuangZhanStart', [],
                            S.KUANGZHAN_CRON)
        wall = minute_wall(0)
        self.assertEqual(len(sched.due(now_ms=0, moment=wall)), 1)
        self.assertEqual(len(sched.due(now_ms=0, moment=wall)), 0)
        self.assertEqual(calls, [1])

    def test_nonwildcard_day_rejected(self):
        sched = S.QuartzScheduler()
        with self.assertRaises(ValueError):
            sched.schedule_cron(None, 'm', [], '0 0 12 5 * ?')

    def test_register_stage_quartz(self):
        sched = S.QuartzScheduler()
        ids = S.register_stage_quartz(sched, None, ['0 0 3 * * ?'])
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])


class TokenTest(unittest.TestCase):
    def test_bus_null_role_throws(self):
        with self.assertRaises(ValueError) as ctx:
            S.BusTokenRunable.scoped('m', None, 'cmd', None)
        self.assertEqual(str(ctx.exception),
                         'BusTokenRunable<contructor>:roleId is null')

    def test_bus_role_routes_inner(self):
        got = []
        job = S.BusTokenRunable.scoped(
            'm', 'r1', 'cmd', {'n': 1}, token=['t'],
            on_role=lambda r, c, d, t: got.append((r, c, d, t)))
        self.assertTrue(job.run())
        self.assertEqual(got, [('r1', 'cmd', {'n': 1}, ['t'])])

    def test_bus_system_routes_module(self):
        got = []
        job = S.BusTokenRunable('m', 'cmd', 7,
                                on_system=lambda m, c, d, t: got.append(m))
        self.assertTrue(job.run())
        self.assertEqual(got, ['m'])

    def test_bus_without_sender_skips(self):
        self.assertFalse(S.BusTokenRunable('m', 'cmd', None).run())

    def test_stage_null_ids_throw(self):
        with self.assertRaises(ValueError) as ctx:
            S.StageTokenRunable.scoped('m', None, 's', 'cmd', None)
        self.assertIn('roleId', str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            S.StageTokenRunable.scoped('m', 'r', None, 'cmd', None)
        self.assertIn('stageId', str(ctx.exception))

    def test_stage_inner_routes_ids(self):
        got = []
        job = S.StageTokenRunable.scoped(
            'm', 'r1', 's9', 'AI:RETRIEVE', None,
            on_stage=lambda r, s, c, d, t: got.append((r, s, c)))
        self.assertTrue(job.run())
        self.assertEqual(got, [('r1', 's9', 'AI:RETRIEVE')])

    def test_stage_without_sender_skips(self):
        job = S.StageTokenRunable.scoped('m', 'r', 's', 'cmd', None)
        self.assertFalse(job.run())


class SessionTickTest(unittest.TestCase):
    def build(self):
        sess = Session(conn_id=3, check_sign=lambda *a: False,
                       get_roles=lambda u, s: [], server_start_ms=0)
        return sess

    def test_quiet_session_ticks_silent(self):
        self.assertIsNone(self.build().tick(now_ms=0))

    def test_due_timer_frames_returned(self):
        sess = self.build()
        sess.schedule_stage('k', 'wake', lambda: (b'F1',), delay=2,
                            unit='SECONDS', now_ms=1000)
        self.assertIsNone(sess.tick(now_ms=2999))
        self.assertEqual(sess.tick(now_ms=3000), (b'F1',))
        self.assertIsNone(sess.tick(now_ms=3000))

    def test_failing_timer_does_not_break_tick(self):
        sess = self.build()

        def boom():
            raise RuntimeError('timer blew up')

        sess.schedule_stage('k', 'bad', boom, now_ms=0)
        self.assertIsNone(sess.tick(now_ms=0))

    def test_handlerless_timer_skipped(self):
        sess = self.build()
        sess.stage_scheduler.schedule('k', 'AI:RETRIEVE', None, 0,
                                      'SECONDS', now_ms=0)
        self.assertIsNone(sess.tick(now_ms=0))


class TickSessionsTest(unittest.TestCase):
    def test_frames_pushed_and_counted(self):
        sent = []

        class Fake:
            send_lock = None

            def tick(self):
                return (b'a', b'b')

        ticked, count = S.tick_sessions([(Fake(), sent.append)])
        self.assertEqual((ticked, count), (1, 2))
        self.assertEqual(sent, [[b'a', b'b']])

    def test_quiet_and_broken_sessions(self):
        class Quiet:
            send_lock = None

            def tick(self):
                return None

        class Broken:
            send_lock = None

            def tick(self):
                raise RuntimeError('nope')

        ticked, count = S.tick_sessions([(Quiet(), lambda f: None),
                                         (Broken(), lambda f: None)])
        self.assertEqual((ticked, count), (1, 0))

    def test_send_lock_held_only_while_sending(self):
        # The tick takes the session state lock itself; send_lock orders sendall.
        tick_held, send_held = [], []
        lock = threading.Lock()

        class Fake:
            send_lock = lock

            def tick(self):
                tick_held.append(lock.locked())
                return (b'x',)

        S.tick_sessions([(Fake(), lambda f: send_held.append(lock.locked()))])
        self.assertEqual(tick_held, [False])
        self.assertEqual(send_held, [True])


if __name__ == '__main__':
    unittest.main()

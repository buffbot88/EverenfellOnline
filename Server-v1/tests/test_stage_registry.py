"""Stage registry goldens: map index, cross-session push, outbox flush on tick.

Covers the registry (game/stage_registry.py), the Session outbox drained by
tick() (game/protocol.py), and the registry hooks in change_stage/apply_stage.
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game.protocol import Session  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402


def make_session(conn_id, registry=None, roles=()):
    return Session(conn_id=conn_id, check_sign=lambda *a: False,
                   get_roles=lambda u, s: list(roles), server_start_ms=0,
                   stage_registry=registry)


class RegistryIndexTest(unittest.TestCase):
    def test_peers_exclude_self_and_other_maps(self):
        reg = StageRegistry()
        a, b, c = object(), object(), object()
        reg.register('r1', 'm1', a)
        reg.register('r2', 'm1', b)
        reg.register('r3', 'm2', c)
        peers = reg.peers('m1', exclude_role='r1')
        self.assertEqual(peers, [('r2', b)])
        self.assertEqual(sorted(r for r, _ in reg.peers('m1')), ['r1', 'r2'])

    def test_register_moves_role_between_maps(self):
        reg = StageRegistry()
        s = object()
        reg.register('r1', 'm1', s)
        reg.register('r1', 'm2', s)
        self.assertEqual(reg.peers('m1'), [])
        self.assertEqual([r for r, _ in reg.peers('m2')], ['r1'])

    def test_ids_are_stringified(self):
        reg = StageRegistry()
        reg.register(7, 3, 'S')
        self.assertEqual(reg.peers('3'), [('7', 'S')])
        self.assertTrue(reg.unregister(7))

    def test_unregister_reports_presence(self):
        reg = StageRegistry()
        reg.register('r1', 'm1', object())
        self.assertTrue(reg.unregister('r1'))
        self.assertFalse(reg.unregister('r1'))
        self.assertEqual(reg.peers('m1'), [])

    def test_unregister_session_drops_all_its_roles(self):
        reg = StageRegistry()
        owner, other = object(), object()
        reg.register('r1', 'm1', owner)
        reg.register('r2', 'm2', owner)
        reg.register('r3', 'm1', other)
        self.assertEqual(reg.unregister_session(owner), 2)
        self.assertEqual(reg.peers('m1'), [('r3', other)])
        self.assertEqual(reg.peers('m2'), [])


class CrossSessionPushTest(unittest.TestCase):
    def test_push_lands_in_target_outbox_and_flushes_on_tick(self):
        reg = StageRegistry()
        sender = make_session(1, reg)
        target = make_session(2, reg)
        reg.register('r2', 'm1', target)
        self.assertTrue(reg.push('r2', [b'A', b'B']))
        self.assertEqual(target.outbox, [b'A', b'B'])
        out = target.tick(now_ms=0)
        self.assertEqual(out, (b'A', b'B'))
        self.assertEqual(target.outbox, [])
        self.assertIsNone(target.tick(now_ms=0))
        self.assertIsNone(sender.tick(now_ms=0))

    def test_push_to_unknown_or_gone_role_is_false(self):
        reg = StageRegistry()
        self.assertFalse(reg.push('nobody', [b'x']))
        target = make_session(2, reg)
        reg.register('r2', 'm1', target)
        reg.unregister_session(target)
        self.assertFalse(reg.push('r2', [b'x']))

    def test_push_frames_accepts_single_frame(self):
        sess = make_session(4)
        sess.push_frames(b'one')
        self.assertEqual(sess.tick(now_ms=0), (b'one',))

    def test_timer_frames_precede_pushed_frames(self):
        sess = make_session(5)
        sess.schedule_stage('k', 'wake', lambda: (b'T',), delay=0,
                            unit='SECONDS', now_ms=0)
        sess.push_frames([b'P'])
        self.assertEqual(sess.tick(now_ms=0), (b'T', b'P'))

    def test_push_does_not_need_target_state_lock(self):
        reg = StageRegistry()
        target = make_session(6, reg)
        reg.register('r6', 'm1', target)
        held = threading.Event()
        release = threading.Event()

        def hold_target_state():
            with target.state_lock:
                held.set()
                release.wait(5)

        holder = threading.Thread(target=hold_target_state)
        holder.start()
        self.assertTrue(held.wait(5))
        done = []
        pusher = threading.Thread(target=lambda: done.append(reg.push('r6', [b'Z'])))
        pusher.start()
        pusher.join(5)
        release.set()
        holder.join(5)
        self.assertEqual(done, [True])
        self.assertEqual(target.tick(now_ms=0), (b'Z',))


class StageHookTest(unittest.TestCase):
    def test_change_stage_registers_role_on_its_map(self):
        reg = StageRegistry()
        role = {'id': 11, 'map_id': '64'}
        sess = make_session(7, reg, roles=[role])
        sess.authed_user, sess.server_id = 'u', 's'
        sess.change_stage(['21000', ['11']])
        self.assertEqual([r for r, _ in reg.peers('64')], ['11'])

    def test_apply_stage_moves_role_on_target_map(self):
        reg = StageRegistry()
        role = {'id': 12, 'map_id': '64', 'map_x': 1, 'map_y': 2}
        sess = make_session(8, reg, roles=[role])
        sess.authed_user, sess.server_id = 'u', 's'
        sess.apply_stage([20000, ['12', '70']])
        self.assertEqual(reg.peers('64'), [])
        self.assertEqual([r for r, _ in reg.peers('70')], ['12'])

    def test_no_registry_keeps_hooks_inert(self):
        role = {'id': 13, 'map_id': '64'}
        sess = make_session(9, None, roles=[role])
        sess.authed_user, sess.server_id = 'u', 's'
        self.assertIsNotNone(sess.change_stage(['21000', ['13']]))


if __name__ == '__main__':
    unittest.main()

"""Party/team lifecycle (TeamAction 52000-52006/52030/52035 + 11002 chat).

Evidence: TeamAction javap (param shapes, reply-vs-void routes, the
P:STAGE_CHANGE event mapping), TeamServiceImpl bytecode (gate order,
error codes, PublicMsgQueue fan-out, earliest-join succession),
TeamVoOutput/TeamMemberVoOutput/ChangeLeaderOutput/GetTeamByMapOutput
shapes, TeamErrorCode clinit, TeamConstants (cap 4) and the
DuiWuJiaCheng exp/life-by-size table.

Every path runs through the real handlers, a shared in-memory
TeamState and a shared StageRegistry: pushes to other sessions land in
their tick outboxes, like the PublicMsgQueue flush. Team state never
touches SQLite (Java's DataContainer regions are process memory).
"""
import os
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode, encode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402
from game.team import TeamState  # noqa: E402

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..',
                           'reference', 'TonNgoKhong', 'server', 'config',
                           'game')
HAVE_REAL = os.path.isdir(REAL_CONFIG)
INITKEY = bytes.fromhex('00000009060f494e49544b4559')
MAP = '7'


def frames(out):
    if out is None:
        return []
    if isinstance(out, (bytes, bytearray)):
        return [decode(bytes(out)[4:])]
    return [decode(bytes(f)[4:]) for f in out]


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class TeamTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, 't.db')
        self.store = Store(self.db_path)
        self.addCleanup(self.store.close)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.reg = StageRegistry()
        self.team = TeamState()
        self.seq = 0

    # -- helpers ---------------------------------------------------------
    def session(self, name, level=56, map_id=MAP, bag=False):
        self.seq += 1
        acct = f'teamhero{self.seq}'
        self.store.create_account(acct, hash_password('pw'))
        rid = self.store.create_character(
            acct, 'fu1304', name, job='C', level=level, map_id=map_id,
            map_x=10, map_y=10)
        extra = {}
        if bag:
            extra.update(dict(
                get_role_bag_slots=self.store.get_role_bag_slots,
                get_role_bag_state=self.store.get_role_bag_state,
                get_role_bag_slot=self.store.get_role_bag_slot,
                get_role_bag_slot_by_bag_id=
                self.store.get_role_bag_slot_by_bag_id,
                update_role_bag_slot=self.store.update_role_bag_slot,
                delete_role_bag_slot=self.store.delete_role_bag_slot,
                move_role_bag_slot=self.store.move_role_bag_slot,
                insert_role_bag_slot=self.store.insert_role_bag_slot,
                rewrite_role_bag_slots=
                self.store.rewrite_role_bag_slots,
                save_role_bag_state=self.store.save_role_bag_state,
                get_role_equip=self.store.get_role_equip))
            self.store.save_role_bag_state(rid, bag_capacity=34,
                                           storage_capacity=30)
        sess = Session(
            conn_id=self.seq, check_sign=lambda *a: False,
            get_roles=lambda u, s, _a=acct: [dict(r) for r in
                                             self.store.list_roles(_a, s)],
            server_start_ms=0,
            save_role_state=self.store.update_character_state,
            get_role_brief=self.store.get_role_brief,
            config=self.cfg, stage_registry=self.reg,
            team_state=self.team, **extra)
        sess.authed_user, sess.server_id = acct, 'fu1304'
        self.reg.mark_online(str(rid), sess)
        return str(rid), sess

    def drain(self, sess):
        return [decode(f[4:]) for f in (sess.tick() or [])]

    def role(self, rid):
        for i in range(1, self.seq + 1):
            for r in self.store.list_roles(f'teamhero{i}', 'fu1304'):
                if str(r['id']) == str(rid):
                    return dict(r)
        return None

    def create(self, sess):
        return frames(sess.team_create(['52000', None]))

    def master(self, name='WukongA'):
        rid, sess = self.session(name)
        out = self.create(sess)
        self.assertEqual(out[0][0], '52000')
        self.assertEqual(out[0][1][0], 1)
        return rid, sess, out[0][1][1]

    def invite_card(self, sess):
        """Newest 52030/52035 push waiting in a session's outbox."""
        for cmd in self.drain(sess):
            if cmd[0] in ('52030', '52035'):
                return cmd
        return None

    def join(self, leader_sess, member_sess, member_rid):
        """Invite/accept round trip; returns the shared team id."""
        frames(leader_sess.team_create(['52000', None]))
        out = frames(leader_sess.team_invite(['52002', member_rid]))
        self.assertEqual(out[-1], ['52002', [1, True]])
        card = self.invite_card(member_sess)
        self.assertIsNotNone(card)
        self.assertEqual(card[0], '52030')
        team_id = card[1][5]
        back = frames(member_sess.team_invite_answer(
            ['52030', [True, team_id]]))
        # Java flushes the joiner's 52000 VO to the joiner's own session
        # (plus a 52006 self-notice when it disbanded their solo team).
        joins = [c for c in back if c[0] == '52000']
        self.assertEqual(len(joins), 1)
        self.assertEqual(joins[0][1][1][0], team_id)
        self.assertIn(member_rid,
                      [m[0] for m in joins[0][1][1][2]])
        return team_id

    # -- creation ----------------------------------------------------------
    def test_create_replies_team_vo_and_second_create_silent(self):
        rid, sess = self.session('WukongA')
        out = self.create(sess)
        self.assertEqual(out[0][0], '52000')
        self.assertEqual(out[0][1][0], 1)
        vo = out[0][1][1]
        self.assertEqual(vo[1], rid)
        self.assertTrue(str(vo[0]).startswith('T'))
        self.assertEqual(vo[3], [0, 0])
        (card,) = vo[2]
        self.assertEqual(len(card), 10)
        self.assertEqual(card[0], rid)
        self.assertEqual(card[1], 'WukongA')
        self.assertEqual(card[4], 56)
        self.assertEqual(card[5], vo[0])
        self.assertIsInstance(card[6], float)
        self.assertEqual(card[7], 'C')
        # Already teamed: Java sends nothing (the queue stays empty).
        self.assertIsNone(sess.team_create(['52000', None]))

    def test_wire_create_dispatches_52000(self):
        _rid, sess = self.session('WukongWire')
        sess.feed(INITKEY)
        req = sess.cipher.encode(encode(['52000', None]))
        out = frames(sess.feed(struct.pack('>I', len(req)) + req))
        self.assertEqual(out[0][0], '52000')
        self.assertEqual(out[0][1][0], 1)

    def test_invite_self_and_offline_gates(self):
        rid, sess = self.session('WukongB')
        self.master('WukongB2')
        # Inviting yourself hits the operation gate and returns early.
        out = frames(sess.team_invite(['52002', rid]))
        self.assertEqual(out, [['52002', [0, 460013]]])
        # A teamless role inviting itself hits the operation gate.
        a_rid, a_sess = self.session('WukongB3')
        out = frames(a_sess.team_invite(['52002', a_rid]))
        self.assertIn(['52002', [0, 460013]], out)
        # Unknown (never online) target reports offline.
        out = frames(a_sess.team_invite(['52002', 'no-such-role']))
        self.assertEqual(out, [['52002', [0, 460003]]])

    # -- invite / apply round trips -----------------------------------------
    def test_invite_accept_lifecycle_with_fanout(self):
        a_rid, a_sess, vo = self.master('WukongC')
        b_rid, b_sess = self.session('WukongD')
        team_id = self.join(a_sess, b_sess, b_rid)
        self.assertEqual(team_id, vo[0])
        # The joiner's 52000 VO (with the jiacheng pair) rides back
        # inline from the answer; the leader sees 52003 + 52011.
        got_a = self.drain(a_sess)
        members = [c for c in got_a if c[0] == '52003']
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0][1][0], b_rid)
        self.assertEqual(members[0][1][5], team_id)
        bonus = [c for c in got_a if c[0] == '52011']
        self.assertEqual(bonus, [['52011', [0.1, 0.01]]])
        # 52001 lists the team for a map mate.
        info = frames(a_sess.team_info())
        self.assertEqual(info[0][0], '52001')
        self.assertEqual(info[0][1][0], 1)
        (listed,) = info[0][1][1]
        self.assertEqual(listed[0], team_id)
        self.assertEqual(listed[1], a_rid)
        self.assertEqual({m[0] for m in listed[2]}, {a_rid, b_rid})
        self.assertEqual(listed[3], [0.1, 0.01])

    def test_apply_accept_lifecycle(self):
        a_rid, a_sess, _vo = self.master('WukongE')
        b_rid, b_sess = self.session('WukongF')
        out = frames(b_sess.team_invite(['52002', a_rid]))
        self.assertEqual(out[-1], ['52002', [1, True]])
        # Teamless applicant -> the leader gets the 52035 card.
        card = self.invite_card(a_sess)
        self.assertIsNotNone(card)
        self.assertEqual(card[0], '52035')
        self.assertEqual(card[1][0], b_rid)
        back = frames(a_sess.team_apply_answer(
            ['52035', [True, b_rid]]))
        # The leader's own session gets the 52003 notice inline; the
        # applicant's 52000 VO rides the applicant's outbox.
        self.assertTrue(any(c[0] == '52003' and c[1][0] == b_rid
                            for c in back))
        got_b = self.drain(b_sess)
        self.assertTrue(any(c[0] == '52000' for c in got_b))
        team = self.team.get_team(self.team.get_role_team(a_rid)['team_id'])
        self.assertEqual(set(team['member_map']), {a_rid, b_rid})

    def test_both_solo_invite_merges_teams(self):
        a_rid, a_sess, _vo = self.master('WukongG')
        b_rid, b_sess = self.session('WukongH')
        frames(b_sess.team_create(['52000', None]))
        out = frames(a_sess.team_invite(['52002', b_rid]))
        self.assertEqual(out[-1], ['52002', [1, True]])
        # Both sides solo: the target gets a 52030 invite card.
        card = self.invite_card(b_sess)
        self.assertIsNotNone(card)
        self.assertEqual(card[0], '52030')
        back = frames(b_sess.team_invite_answer(
            ['52030', [True, card[1][5]]]))
        # removeTeam disbands the answerer's solo team (52006 to self)
        # before the 52000 join VO.
        self.assertIn(['52006', [1, b_rid, True]], back)
        joins = [c for c in back if c[0] == '52000']
        self.assertEqual(len(joins), 1)
        team = self.team.get_team(self.team.get_role_team(a_rid)['team_id'])
        self.assertEqual(len(team['member_map']), 2)

    def test_refusals_notify_the_other_side(self):
        _a_rid, a_sess, _vo = self.master('WukongI')
        b_rid, b_sess = self.session('WukongJ')
        frames(a_sess.team_invite(['52002', b_rid]))
        card = self.invite_card(b_sess)
        back = frames(b_sess.team_invite_answer(
            ['52030', [False, card[1][5]]]))
        self.assertEqual(back, [])
        got_a = self.drain(a_sess)
        refused = [c for c in got_a if c[0] == '52002']
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0][1][0], 0)
        self.assertEqual(refused[0][1][1], 460012)
        # Application refused by the leader.
        c_rid, c_sess = self.session('WukongK')
        frames(c_sess.team_invite(['52002', _a_rid]))
        apply_card = self.invite_card(a_sess)
        self.assertEqual(apply_card[0], '52035')
        frames(a_sess.team_apply_answer(['52035', [False, c_rid]]))
        got_c = self.drain(c_sess)
        refused_c = [c for c in got_c if c[0] == '52002']
        self.assertEqual(len(refused_c), 1)
        self.assertEqual(refused_c[0][1][1], 460011)

    # -- permissions and limits --------------------------------------------------
    def test_nonleader_invite_and_kick_gates(self):
        a_rid, a_sess, _vo = self.master('WukongL')
        b_rid, b_sess = self.session('WukongM')
        self.join(a_sess, b_sess, b_rid)
        self.drain(a_sess)
        self.drain(b_sess)
        c_rid, _c_sess = self.session('WukongN')
        # A member cannot invite: 460007 to the member (plus the ack).
        out = frames(b_sess.team_invite(['52002', c_rid]))
        self.assertIn(['52002', [0, 460007]], out)
        self.assertEqual(out[-1], ['52002', [1, True]])
        # A member cannot kick: 460007; kicking the leader: 460008.
        out = frames(b_sess.team_exit(['52006', a_rid]))
        self.assertEqual(out, [['52006', [0, 460007]]])
        out = frames(a_sess.team_exit(['52006', a_rid]))
        self.assertEqual(out, [['52006', [0, 460008]]])
        # Kicking a non-member is a silent no-op (no corrupt removal).
        out = frames(a_sess.team_exit(['52006', c_rid]))
        self.assertEqual(out, [])
        team = self.team.get_team(self.team.get_role_team(a_rid)['team_id'])
        self.assertEqual(set(team['member_map']), {a_rid, b_rid})

    def test_full_team_gates(self):
        a_rid, a_sess, _vo = self.master('WukongO')
        members = [(a_rid, a_sess)]
        for name in ('WukongP', 'WukongQ', 'WukongR'):
            r_rid, r_sess = self.session(name)
            self.join(a_sess, r_sess, r_rid)
            members.append((r_rid, r_sess))
        for _r, s in members:
            self.drain(s)
        team = self.team.get_team(self.team.get_role_team(a_rid)['team_id'])
        self.assertEqual(len(team['member_map']), 4)
        e_rid, _e_sess = self.session('WukongS')
        # Application to a full team: 460002 to the applicant.
        t_rid, t_sess = self.session('WukongT')
        out = frames(t_sess.team_invite(['52002', a_rid]))
        self.assertEqual(out[-1], ['52002', [1, True]])
        card = self.invite_card(a_sess)
        back = frames(a_sess.team_apply_answer(['52035', [True, t_rid]]))
        self.assertEqual(back, [])
        # The full-team refusal goes to the applicant's session.
        got_t = self.drain(t_sess)
        self.assertIn(['52002', [0, 460002]], got_t)
        self.assertIsNone(self.team.get_role_team(t_rid))
        # Invite into a full team: 460001 to the leader, no card sent.
        out = frames(a_sess.team_invite(['52002', e_rid]))
        self.assertIn(['52002', [0, 460001]], out)
        self.assertEqual(out[-1], ['52002', [1, True]])
        e_got = self.drain(_e_sess)
        self.assertFalse(any(c[0] == '52030' for c in e_got))

    def test_double_answer_is_rejected(self):
        a_rid, a_sess, _vo = self.master('WukongV')
        b_rid, b_sess = self.session('WukongW')
        frames(a_sess.team_invite(['52002', b_rid]))
        card = self.invite_card(b_sess)
        frames(b_sess.team_invite_answer(['52030', [True, card[1][5]]]))
        self.drain(a_sess)
        self.drain(b_sess)
        # Answering again: already teamed, so 460004 to the answerer.
        back = frames(b_sess.team_invite_answer(
            ['52030', [True, card[1][5]]]))
        self.assertEqual(back, [['52002', [0, 460004]]])
        team = self.team.get_team(self.team.get_role_team(a_rid)['team_id'])
        self.assertEqual(set(team['member_map']), {a_rid, b_rid})

    # -- leadership ------------------------------------------------------------------
    def test_leadership_transfer_accept(self):
        a_rid, a_sess, _vo = self.master('WukongX')
        b_rid, b_sess = self.session('WukongY')
        self.join(a_sess, b_sess, b_rid)
        self.drain(a_sess)
        self.drain(b_sess)
        out = frames(a_sess.team_apply_leader(['52004', b_rid]))
        self.assertEqual(out[0], ['52004', [1]])
        ask = [c for c in self.drain(b_sess) if c[0] == '52005']
        self.assertEqual(ask, [['52005', [1]]])
        back = frames(b_sess.team_change_leader(['52005', True]))
        self.assertTrue(any(c == ['52004', [1, b_rid]] for c in back))
        got_a = self.drain(a_sess)
        self.assertTrue(any(c == ['52004', [1, b_rid]] for c in got_a))
        team = self.team.get_team(self.team.get_role_team(a_rid)['team_id'])
        self.assertEqual(team['leader_id'], b_rid)
        self.assertEqual(team['next_leader_id'], '')

    def test_leadership_refuse_only_tells_the_leader(self):
        a_rid, a_sess, _vo = self.master('WukongZ1')
        b_rid, b_sess = self.session('WukongZ2')
        self.join(a_sess, b_sess, b_rid)
        self.drain(a_sess)
        self.drain(b_sess)
        frames(a_sess.team_apply_leader(['52004', b_rid]))
        self.drain(b_sess)
        back = frames(b_sess.team_change_leader(['52005', False]))
        self.assertEqual(back, [])
        got_a = self.drain(a_sess)
        refused = [c for c in got_a if c[0] == '52004']
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0][1][0], 0)
        self.assertEqual(refused[0][1][1], 460009)
        team = self.team.get_team(self.team.get_role_team(a_rid)['team_id'])
        self.assertEqual(team['leader_id'], a_rid)

    def test_leadership_gates(self):
        a_rid, a_sess, _vo = self.master('WukongZ3')
        b_rid, b_sess = self.session('WukongZ4')
        self.join(a_sess, b_sess, b_rid)
        c_rid, _c_sess = self.session('WukongZ5')
        # Member nominating: 460007.
        out = frames(b_sess.team_apply_leader(['52004', b_rid]))
        self.assertEqual(out, [['52004', [0, 460007]]])
        # Nominating an outsider: 460005.
        out = frames(a_sess.team_apply_leader(['52004', c_rid]))
        self.assertEqual(out, [['52004', [0, 460005]]])
        # Nominating an offline role: 460003.
        self.reg.mark_offline(c_rid)
        try:
            out = frames(a_sess.team_apply_leader(['52004', c_rid]))
        finally:
            self.reg.mark_online(c_rid, _c_sess)
        self.assertEqual(out, [['52004', [0, 460003]]])
        # Answering with no pending nomination: 460004.
        out = frames(b_sess.team_change_leader(['52005', True]))
        self.assertEqual(out, [['52004', [0, 460004]]])

    # -- exit / kick / teardown -----------------------------------------------------------
    def test_member_exit_notifies_and_refreshes_bonus(self):
        a_rid, a_sess, _vo = self.master('WukongAA')
        b_rid, b_sess = self.session('WukongAB')
        c_rid, c_sess = self.session('WukongAC')
        self.join(a_sess, b_sess, b_rid)
        self.join(a_sess, c_sess, c_rid)
        for s in (a_sess, b_sess, c_sess):
            self.drain(s)
        back = frames(b_sess.team_exit(['52006', None]))
        self.assertTrue(any(c == ['52006', [1, b_rid, True]]
                            for c in back))
        for sess, rid in ((a_sess, a_rid), (c_sess, c_rid)):
            got = self.drain(sess)
            self.assertIn(['52006', [1, b_rid, True]], got)
            self.assertIn(['52011', [0.1, 0.01]], got)
        self.assertIsNone(self.team.get_role_team(b_rid))
        team = self.team.get_team(self.team.get_role_team(a_rid)['team_id'])
        self.assertEqual(set(team['member_map']), {a_rid, c_rid})

    def test_kick_notifies_everyone(self):
        a_rid, a_sess, _vo = self.master('WukongAD')
        b_rid, b_sess = self.session('WukongAE')
        self.join(a_sess, b_sess, b_rid)
        self.drain(a_sess)
        self.drain(b_sess)
        back = frames(a_sess.team_exit(['52006', b_rid]))
        # The leader's own 52006 notice returns inline.
        self.assertIn(['52006', [1, b_rid, True]], back)
        self.assertIn(['52006', [1, b_rid, True]], self.drain(b_sess))
        self.assertIsNone(self.team.get_role_team(b_rid))

    def test_last_member_exit_disbands(self):
        a_rid, a_sess, vo = self.master('WukongAF')
        team_id = vo[0]
        back = frames(a_sess.team_exit(['52006', None]))
        self.assertIn(['52006', [1, a_rid, True]], back)
        self.assertIsNone(self.team.get_team(team_id))
        self.assertIsNone(self.team.get_role_team(a_rid))
        self.assertEqual(frames(a_sess.team_info()),
                         [['52001', [1, []]]])

    def test_leader_exit_succession_goes_to_earliest_joiner(self):
        a_rid, a_sess, _vo = self.master('WukongAG')
        b_rid, b_sess = self.session('WukongAH')
        c_rid, c_sess = self.session('WukongAI')
        self.join(a_sess, b_sess, b_rid)
        self.join(a_sess, c_sess, c_rid)
        for s in (a_sess, b_sess, c_sess):
            self.drain(s)
        back = frames(a_sess.team_exit(['52006', None]))
        self.assertIn(['52006', [1, a_rid, True]], back)
        for sess in (b_sess, c_sess):
            got = self.drain(sess)
            self.assertIn(['52004', [1, b_rid]], got)
            self.assertIn(['52006', [1, a_rid, True]], got)
        team = self.team.get_team(self.team.get_role_team(b_rid)['team_id'])
        self.assertEqual(team['leader_id'], b_rid)
        self.assertEqual(set(team['member_map']), {b_rid, c_rid})

    def test_disconnect_exits_and_succession_runs(self):
        a_rid, a_sess, _vo = self.master('WukongAJ')
        b_rid, b_sess = self.session('WukongAK')
        self.join(a_sess, b_sess, b_rid)
        self.drain(a_sess)
        self.drain(b_sess)
        # Solo disconnect disbands the team.
        solo_rid, solo_sess, _solo_vo = self.master('WukongAL')
        solo_team = self.team.get_role_team(solo_rid)['team_id']
        self.reg.mark_offline(solo_rid)
        solo_sess._team_on_disconnect()
        self.assertIsNone(self.team.get_team(solo_team))
        # Leader disconnect hands the team to the earliest joiner.
        self.reg.mark_offline(a_rid)
        a_sess._team_on_disconnect()
        team = self.team.get_team(self.team.get_role_team(b_rid)['team_id'])
        self.assertEqual(team['leader_id'], b_rid)
        got_b = self.drain(b_sess)
        self.assertIn(['52004', [1, b_rid]], got_b)
        self.assertIn(['52006', [1, a_rid, True]], got_b)

    def test_teams_do_not_survive_a_fresh_state(self):
        a_rid, a_sess, vo = self.master('WukongAM')
        team_id = vo[0]
        self.assertIsNotNone(self.team.get_team(team_id))
        # Restart semantics: a new TeamState knows nothing (no SQLite rows).
        fresh = TeamState()
        self.assertIsNone(fresh.get_team(team_id))
        self.assertIsNone(fresh.get_role_team(a_rid))
        # The live state is process memory: a DB reopen keeps the team.
        self.store.close()
        reopened = Store(self.db_path)
        self.addCleanup(reopened.close)
        self.assertIsNotNone(self.team.get_team(team_id))

    # -- map moves / visibility ------------------------------------------------------
    def test_cross_map_move_pushes_52012(self):
        a_rid, a_sess, _vo = self.master('WukongAN')
        b_rid, b_sess = self.session('WukongAO')
        self.join(a_sess, b_sess, b_rid)
        self.reg.register(a_rid, MAP, a_sess, x=10, y=10)
        self.reg.register(b_rid, MAP, b_sess, x=12, y=10)
        for s in (a_sess, b_sess):
            self.drain(s)
        out = a_sess.change_map(a_rid, '8', 5, 5)
        moves = [c for c in (frames(out) if isinstance(out, list) else [])
                 if c[0] == '52012']
        self.assertTrue(moves)
        self.assertEqual(moves[0][1], [a_rid, '8'])
        got_b = self.drain(b_sess)
        self.assertIn(['52012', [a_rid, '8']], got_b)

    def test_leader_move_rebuckets_team_info(self):
        a_rid, a_sess, _vo = self.master('WukongAP')
        b_rid, b_sess = self.session('WukongAQ')
        self.join(a_sess, b_sess, b_rid)
        self.reg.register(a_rid, MAP, a_sess, x=10, y=10)
        self.reg.register(b_rid, MAP, b_sess, x=12, y=10)
        a_sess.change_map(a_rid, '8', 5, 5)
        self.drain(a_sess)
        self.drain(b_sess)
        # The leader's team now lists under map 8, no longer map 7.
        info = frames(b_sess.team_info())
        self.assertEqual(info, [['52001', [1, []]]])
        self.reg.register(b_rid, '8', b_sess, x=6, y=5)
        info = frames(b_sess.team_info())
        self.assertEqual(len(info[0][1][1]), 1)
        self.assertEqual(info[0][1][1][0][0],
                         self.team.get_role_team(a_rid)['team_id'])

    def test_team_info_prunes_offline_members(self):
        a_rid, a_sess, _vo = self.master('WukongAR')
        b_rid, b_sess = self.session('WukongAS')
        self.join(a_sess, b_sess, b_rid)
        self.reg.mark_offline(b_rid)
        try:
            info = frames(a_sess.team_info())
        finally:
            self.reg.mark_online(b_rid, b_sess)
        (listed,) = info[0][1][1]
        self.assertEqual({m[0] for m in listed[2]}, {a_rid})
        team = self.team.get_team(self.team.get_role_team(a_rid)['team_id'])
        self.assertEqual(set(team['member_map']), {a_rid})

    # -- chat ---------------------------------------------------------------------------
    def test_team_chat_fans_out_to_members(self):
        a_rid, a_sess, _vo = self.master('WukongAT')
        b_rid, b_sess = self.session('WukongAU')
        self.join(a_sess, b_sess, b_rid)
        self.drain(a_sess)
        self.drain(b_sess)
        payload = [a_rid, 'hello team', 'hello team']
        back = frames(a_sess.team_chat(['11002', payload]))
        self.assertEqual(back, [['11002', payload]])
        self.assertIn(['11002', payload], self.drain(b_sess))
        # Outsiders hear nothing and send nothing.
        _c_rid, c_sess = self.session('WukongAV')
        self.assertIsNone(c_sess.team_chat(['11002', payload]))
        self.assertEqual(self.drain(c_sess), [])

    # -- combat and loot integration -------------------------------------------------------
    def test_team_kill_uses_team_exp_column_and_size(self):
        from game import combat as combat_lib  # noqa: E402
        tpl = self.cfg.monster_template('D000006')
        self.assertEqual(int(tpl['hitpoints']), 200)
        a_rid, a_sess = self.session('WukongAW', level=5)
        b_rid, b_sess = self.session('WukongAX', level=5)
        self.join(a_sess, b_sess, b_rid)
        self.drain(a_sess)
        self.drain(b_sess)
        for sess, rid in ((a_sess, a_rid), (b_sess, b_rid)):
            sess._monster_reg['m_7_0'] = {'template': tpl, 'map': MAP,
                                          'born': [12, 12], 'pos': [12, 12]}
            sess._monster_hp['m_7_0'] = 50.0
        role = self.role(a_rid)
        me = {'kind': 'role', 'id': a_rid, 'role': role}
        with mock.patch('random.random', return_value=0.5):
            got_frames = a_sess._resolve_fire(me, 'normal003', 0,
                                               ['m_7_0'], None, 1)
        decoded = [decode(f[4:]) for f in got_frames]
        # Hand-derived: basicexp 50 * (1 + (2-1) * 0.05) * rankrevise 1.00 *
        # decay 1.0 = 52.5 -> 52 (solo would pay exactly 50).
        self.assertEqual(combat_lib.base_kill_exp(50, team_size=2,
                                                  xiuZheng=1.0,
                                                  levelXishu=1.0), 52)
        exp_frame = next(d for d in decoded if d[0] == '12001')
        self.assertEqual(exp_frame[1], [52.0, 5])
        drop = next(d for d in decoded if d[0] == '12030')
        self.assertEqual(drop[1], ['m_7_0', 'D000006', 52.0])
        self.assertEqual(self.role(a_rid)['exp'], 52)

    def test_team_loot_shared_pickup_stranger_blocked(self):
        tpl = self.cfg.monster_template('D040001')
        a_rid, a_sess = self.session(
            'WukongAY', level=31, bag=True)
        b_rid, b_sess = self.session(
            'WukongAZ', level=31, bag=True)
        c_rid, c_sess = self.session('WukongBA', level=31, bag=True)
        self.join(a_sess, b_sess, b_rid)
        self.drain(a_sess)
        self.drain(b_sess)
        team_id = self.team.get_role_team(a_rid)['team_id']
        a_sess._monster_reg['m_7_0'] = {'template': tpl, 'map': MAP,
                                        'born': [27, 28], 'pos': [27, 28]}
        a_sess._monster_hp['m_7_0'] = 50.0
        me = {'kind': 'role', 'id': a_rid, 'role': self.role(a_rid)}
        with mock.patch('game.protocol.random.randrange', return_value=100):
            with mock.patch.object(Session, '_world_now_ms',
                                   return_value=1000):
                with mock.patch('random.random', return_value=0.5):
                    a_sess._resolve_fire(me, 'normal003', 0,
                                         ['m_7_0'], None, 1)
        (item,) = [i for i in a_sess._world.ground_items.on_map(MAP)
                   if i.goods_id == 'hpadd002']
        self.assertEqual(item.owner_id, a_rid)
        self.assertEqual(item.owner_team_id, team_id)
        # A teammate picks up inside the owner window.
        ok, pick_frames = b_sess.pickup_item(self.role(b_rid), item.id,
                                             now_ms=2000)
        self.assertTrue(ok)
        got = [decode(f[4:]) for f in pick_frames]
        self.assertEqual(got[0], ['30103', [1, 'hpadd002', 1, item.id]])
        rows = self.store.get_role_bag_slots(b_rid, 1, 150)
        self.assertEqual([(r['goods_id'], r['count']) for r in rows],
                         [('hpadd002', 1)])
        # A stranger is blocked inside the window, open after it. The
        # second kill uses a fresh monster id (the first corpse stays in
        # _dead, so a repeat hit on it adds nothing).
        a_sess._monster_reg['m_7_1'] = {'template': tpl, 'map': MAP,
                                        'born': [27, 28], 'pos': [27, 28]}
        a_sess._monster_hp['m_7_1'] = 50.0
        me = {'kind': 'role', 'id': a_rid, 'role': self.role(a_rid)}
        with mock.patch('game.protocol.random.randrange', return_value=100):
            with mock.patch.object(Session, '_world_now_ms',
                                   return_value=9000):
                with mock.patch('random.random', return_value=0.5):
                    a_sess._resolve_fire(me, 'normal003', 0,
                                         ['m_7_1'], None, 1)
        (item2,) = [i for i in a_sess._world.ground_items.on_map(MAP)
                    if i.goods_id == 'hpadd002' and i.drop_time_ms == 9000]
        ok, stranger_frames = c_sess.pickup_item(self.role(c_rid), item2.id,
                                                 now_ms=10000)
        self.assertFalse(ok)
        self.assertEqual([decode(f[4:]) for f in stranger_frames],
                         [['30103', [0]]])
        ok, _late = c_sess.pickup_item(self.role(c_rid), item2.id,
                                       now_ms=30000)
        self.assertTrue(ok)

    def test_concurrent_accepts_keep_consistent_membership(self):
        a_rid, a_sess, _vo = self.master('WukongBB')
        b_rid, b_sess = self.session('WukongBC')
        c_rid, c_sess = self.session('WukongBD')
        frames(a_sess.team_invite(['52002', b_rid]))
        frames(a_sess.team_invite(['52002', c_rid]))
        card_b = self.invite_card(b_sess)
        card_c = self.invite_card(c_sess)
        self.drain(a_sess)
        errors = []

        def answer(sess, card):
            try:
                frames(sess.team_invite_answer(
                    ['52030', [True, card[1][5]]]))
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=answer, args=(b_sess, card_b)),
                   threading.Thread(target=answer, args=(c_sess, card_c))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        team = self.team.get_team(self.team.get_role_team(a_rid)['team_id'])
        self.assertEqual(set(team['member_map']), {a_rid, b_rid, c_rid})


if __name__ == '__main__':
    unittest.main()

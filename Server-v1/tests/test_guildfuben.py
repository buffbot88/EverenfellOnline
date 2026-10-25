"""Guild-dungeon lifecycle (GuildFuBenAction 118001-118004/118007).

Evidence: GuildFuBenServiceImpl + GuildFuBenUtil + BangPaiFuBen(Config)
+ GuildFuBenStageCopy javap (gate order, error codes, fan-out shapes,
weekly-reset math), the genuine bangpaifuben/bangpaifubenboss tables,
and Server-v1/docs/guildfuben-ledger.md.

Every path runs through the real handlers, the shared StageRegistry
and SQLite: two members enter, fight seeded bosses with real swings,
share the kill roster, claim chests, and exercise quit/disconnect/
leave/disband plus the weekly reset. Guild state reuses the canonical
guild store; presence/attempts are session-local like the port's other
dungeon attempts.
"""
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode, encode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session, _wire_id  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2]
               / 'reference' / 'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config' / 'bangpaifuben.jat').is_file()

INITKEY = bytes.fromhex('00000009060f494e49544b4559')
MID = 'm_92_0'
HOME_MAP = '7'


def frames(out):
    if out is None:
        return []
    if isinstance(out, (bytes, bytearray)):
        return [decode(bytes(out)[4:])]
    return [decode(bytes(f)[4:]) for f in out]


def cmds(out):
    return [c[0] for c in frames(out)]


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class GuildFubenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = GameConfig(str(REAL_CONFIG))
        cls.tpl = cls.cfg.monster_template('G200001')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'g.db'))
        self.addCleanup(self.store.close)
        self.reg = StageRegistry()
        self.seq = 0

    # -- helpers ---------------------------------------------------------
    def session(self, name, level=56, bag=False, map_id=HOME_MAP):
        self.seq += 1
        acct = f'gfbhero{self.seq}'
        self.store.create_account(acct, hash_password('pw'))
        rid = self.store.create_character(
            acct, 'fu1304', name, job='C', level=level, tongqian=2000000,
            map_id=map_id, map_x=10, map_y=10)
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
            get_guild_id=self.store.get_guild_id,
            save_guild_member=self.store.save_guild_member,
            get_guild=self.store.get_guild,
            save_guild=self.store.save_guild,
            delete_guild=self.store.delete_guild,
            get_guild_member=self.store.get_guild_member,
            get_guild_members=self.store.get_guild_members,
            delete_guild_member=self.store.delete_guild_member,
            delete_guild_gongxian=self.store.delete_guild_gongxian,
            get_guild_fuben=self.store.get_guild_fuben,
            list_guild_fubens=self.store.list_guild_fubens,
            save_guild_fuben=self.store.save_guild_fuben,
            delete_guild_fubens=self.store.delete_guild_fubens,
            get_guild_fuben_reward=self.store.get_guild_fuben_reward,
            save_guild_fuben_reward=self.store.save_guild_fuben_reward,
            config=self.cfg, stage_registry=self.reg, **extra)
        sess.authed_user, sess.server_id = acct, 'fu1304'
        self.reg.mark_online(str(rid), sess)
        try:
            self.reg.register(str(rid), map_id, sess, x=10, y=10)
        except Exception:
            pass
        return str(rid), sess

    def drain(self, sess, **kw):
        return [decode(f[4:]) for f in (sess.tick(**kw) or [])]

    def role(self, rid, acct_seq=None):
        for i in range(1, self.seq + 1):
            for r in self.store.list_roles(f'gfbhero{i}', 'fu1304'):
                if str(r['id']) == str(rid):
                    return dict(r)
        return None

    def guild(self, name='浩气会', banner='浩气旗'):
        rid, sess = self.session(f'Wukong{self.seq + 100}', bag=True)
        out = frames(sess.guild_create(
            [53000, [name, banner, 1, 0, 1]]))
        self.assertEqual(out[0], ['53000', [1, out[0][1][1]]])
        return rid, sess, str(out[0][1][1][0])

    def member(self, gid, name=None):
        rid, sess = self.session(name or f'Wukong{self.seq + 100}',
                                 bag=True)
        self.store.save_guild_member(rid, gid, 3)
        return rid, sess

    def fund(self, gid, amount=10):
        guild = dict(self.store.get_guild(gid))
        guild['money'] = amount
        self.store.save_guild(guild)

    def unseal(self, sess, mainid=1):
        return frames(sess.guildfuben_seal([118007, mainid]))

    def enter(self, sess, mainid=1):
        return frames(sess.guildfuben_enter([118003, mainid]))

    def swing(self, sess, role, tpl, mid):
        sess._monster_reg[mid] = {'template': tpl, 'map': '92',
                                  'born': [15, 170], 'pos': [15, 170]}
        sess._monster_hp[mid] = 50.0
        me = {'kind': 'role', 'id': str(role['id']), 'role': role}
        out = []
        # Level-70 bosses blunt a level-56 swing (~42 dmg); keep
        # swinging until the seeded HP is gone, like a real fight.
        with mock.patch('random.random', return_value=0.5):
            with mock.patch('game.protocol.random.randrange',
                            return_value=100):
                for _ in range(6):
                    if mid in sess._dead:
                        break
                    out.extend(sess._resolve_fire(
                        me, 'normal003', 0, [mid], None, 1))
                    role = self.role(role['id']) or role
                    me = {'kind': 'role', 'id': str(role['id']),
                          'role': role}
        self.assertIn(mid, sess._dead)
        return out

    # -- access gates ------------------------------------------------------
    def test_guildless_panel_enter_reward_seal(self):
        _rid, sess = self.session('WukongLone')
        self.assertEqual(frames(sess.guildfuben_info()),
                         [['118001', []]])
        # Guildless entry answers the empty shape, like the Java action.
        self.assertEqual(self.enter(sess), [['118003', []]])
        self.assertIsNone(sess.guildfuben_reward([118002, [1, 'G200001']]))
        self.assertIsNone(sess.guildfuben_seal([118007, 1]))

    def test_create_seeds_sealed_row(self):
        _rid, _sess, gid = self.guild()
        row = self.store.get_guild_fuben(gid, 1)
        self.assertIsNotNone(row)
        self.assertEqual(row['open'], 0)
        self.assertEqual(row['killboss'], '{}')
        self.assertEqual(row['reward_list'], '{}')
        self.assertEqual(row['stageid'], f'GUILDFUBEN-{gid}-1-92')

    def test_info_panel_shape(self):
        rid, sess, _gid = self.guild()
        out = frames(sess.guildfuben_info())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], '118001')
        (panel,) = out[0][1]
        self.assertEqual(panel[0], 1)
        self.assertEqual(panel[1], [])
        self.assertEqual(panel[2], [])
        self.assertEqual(panel[3], 0)
        self.assertTrue(0 < panel[4] <= 7 * 24 * 3600 * 1000)
        _ = rid

    def test_wire_info_dispatches_118001(self):
        _rid, sess, _gid = self.guild()
        sess.feed(INITKEY)
        req = sess.cipher.encode(encode(['118001', None]))
        out = frames(sess.feed(struct.pack('>I', len(req)) + req))
        self.assertEqual(out[0][0], '118001')
        self.assertEqual(out[0][1][0][0], 1)

    # -- unseal --------------------------------------------------------------
    def test_seal_gates(self):
        _rid, sess, gid = self.guild()
        brid, _bsess = self.member(gid)
        # Non-master cannot unseal.
        self.assertEqual(
            frames(_bsess.guildfuben_seal([118007, 1])),
            [['118007', [0, 118000]]])
        # Master without funds.
        self.assertEqual(self.unseal(sess), [['118007', [0, 118002]]])
        self.fund(gid)
        out = self.unseal(sess)
        self.assertEqual(out[0], ['118007', [1, 1]])
        # The 118008 world notice rides the reply.
        notices = [c for c in out if c[0] == '11101']
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0][1][0], 118008)
        self.assertEqual(self.store.get_guild(gid)['money'], 9)
        self.assertEqual(self.store.get_guild_fuben(gid, 1)['open'], 1)
        # Already open.
        self.assertEqual(self.unseal(sess), [['118007', [0, 118001]]])
        _ = brid

    def test_unknown_dungeon_is_silent(self):
        _rid, sess, gid = self.guild()
        self.fund(gid)
        self.assertIsNone(sess.guildfuben_seal([118007, 999]))
        self.assertIsNone(sess.guildfuben_enter([118003, 999]))
        self.assertEqual(self.store.list_guild_fubens(gid) == [], False)

    # -- entry ---------------------------------------------------------------
    def test_enter_gates_and_lifecycle(self):
        arid, asess, gid = self.guild()
        brid, bsess = self.member(gid)
        # Sealed dungeon.
        self.assertEqual(self.enter(asess), [['118003', [0, 118006]]])
        self.fund(gid)
        self.unseal(asess)
        out = self.enter(asess)
        by_cmd = {c[0]: c[1] for c in out}
        # Per-guild SC:APPLY_COPY: the wire map is 92 while the row
        # keeps the offline-save position and the live stage is the copy.
        self.assertEqual(by_cmd['20000'], [1, '92', [15, 170]])
        self.assertEqual(asess._live_map(arid), '92')
        self.assertEqual(self.role(arid)['map_id'], HOME_MAP)
        self.assertTrue(str(asess._guildfuben_attempt[arid]['stage']).startswith(
            'GUILDFUBEN-'))
        # Stage-enter payload carries the (empty) kill log.
        self.assertEqual(by_cmd['118006'], [1, [], 0])
        self.assertEqual(by_cmd['118003'], [1])
        # Already inside answers nothing.
        self.assertEqual(self.enter(asess), [])
        # The 118011 guild notice reaches the other member.
        got = self.drain(bsess)
        notices = [c for c in got if c[0] == '11130']
        self.assertTrue(any(c[1][0] == '11003' and
                            c[1][1][0] == 118011 for c in notices))
        # Re-entry cooldown after a weekly reset stamp.
        asess._guildfuben_ref['1'] = int(
            asess._world_now_ms()) + 10 * 60 * 1000
        self.assertEqual(frames(asess.guildfuben_quit([118004, '1']))[-1],
                         ['118004', [1]])
        self.assertEqual(self.enter(asess),
                         [['118003', [0, 118013]]])
        _ = brid

    def test_quit_releases_and_notifies(self):
        arid, asess, gid = self.guild()
        brid, bsess = self.member(gid)
        self.fund(gid)
        self.unseal(asess)
        self.enter(asess)
        self.enter(bsess)
        out = frames(asess.guildfuben_quit([118004, '1']))
        self.assertEqual(out[-1], ['118004', [1]])
        got = self.drain(bsess)
        notices = [c for c in got if c[0] == '11130']
        self.assertTrue(any(c[1][1][0] == 118012 for c in notices))
        # The quitter can re-enter; quitting again is still [1].
        self.assertEqual(self.enter(asess)[-1], ['118003', [1]])
        self.assertEqual(frames(asess.guildfuben_quit([118004, '1']))[-1],
                         ['118004', [1]])
        self.assertNotIn(arid, asess._guildfuben_attempt)
        _ = brid

    # -- boss kills with real combat ------------------------------------------
    def test_boss_kill_credits_guild_with_real_swing(self):
        arid, asess, gid = self.guild()
        brid, bsess = self.member(gid)
        self.fund(gid)
        self.unseal(asess)
        self.enter(asess)
        self.enter(bsess)
        kill_out = self.swing(asess, self.role(arid), self.tpl, MID)
        got = [decode(bytes(f)[4:]) for f in kill_out]
        row = self.store.get_guild_fuben(gid, 1)
        killboss = json.loads(row['killboss'])
        self.assertEqual(killboss['G200001'][0], arid)
        self.assertEqual(killboss['G200001'][1],
                         self.role(arid)['name'])
        # The whole guild is on the claim roster.
        roster = json.loads(row['reward_list'])['G200001']
        self.assertEqual(set(roster), {arid, brid})
        # Killer sees the 118009 world notice.
        notices = [c for c in got if c[0] == '11101']
        self.assertTrue(any(c[1][0] == 118009 for c in notices))
        # Teammate kills nothing extra but shares the roster.
        self.assertEqual(set(json.loads(
            self.store.get_guild_fuben(gid, 1)['reward_list']
        )['G200001']), {arid, brid})
        _ = bsess

    def test_non_wanted_and_offmap_kills_ignored(self):
        arid, asess, gid = self.guild()
        self.fund(gid)
        self.unseal(asess)
        self.enter(asess)
        other = dict(self.tpl)
        other['id'] = 'D040001'
        self.swing(asess, self.role(arid), other, 'm_92_9')
        self.assertEqual(json.loads(
            self.store.get_guild_fuben(gid, 1)['killboss']), {})
        # A wanted boss outside the dungeon copy does not count.
        self.store.update_character_state(arid, map_id=HOME_MAP)
        self.reg.unregister(arid)
        self.reg.register(arid, HOME_MAP, asess, x=10, y=10)
        self.swing(asess, self.role(arid), self.tpl, 'm_92_8')
        self.assertEqual(json.loads(
            self.store.get_guild_fuben(gid, 1)['killboss']), {})

    def test_stranger_kill_credits_nothing(self):
        _arid, _asess, gid = self.guild()
        brid, bsess = self.member(gid)
        crid, csess = self.session('WukongOutsider', bag=True)
        self.fund(gid)
        self.unseal(_asess)
        self.enter(bsess)
        self.store.update_character_state(crid, map_id='92')
        self.swing(csess, self.role(crid), self.tpl, 'm_92_x')
        self.assertEqual(json.loads(
            self.store.get_guild_fuben(gid, 1)['killboss']), {})

    def test_two_guilds_are_isolated(self):
        arid, asess, agid = self.guild('恶人会', '恶人旗')
        _brid, _bsess, bgid = self.guild('君山会', '君山旗')
        for gid, sess in ((agid, asess), (bgid, _bsess)):
            self.fund(gid)
        self.unseal(asess)
        self.unseal(_bsess)
        self.enter(asess)
        self.enter(_bsess)
        self.swing(asess, self.role(arid), self.tpl, MID)
        self.assertIn('G200001', json.loads(
            self.store.get_guild_fuben(agid, 1)['killboss']))
        self.assertEqual(json.loads(
            self.store.get_guild_fuben(bgid, 1)['killboss']), {})

    def test_finish_notice_on_last_boss(self):
        arid, asess, gid = self.guild()
        _brid, _bsess = self.member(gid)
        self.fund(gid)
        self.unseal(asess)
        self.enter(asess)
        notices = []
        for idx, boss in enumerate(['G200001', 'G200002', 'G200003',
                                    'G200004', 'G200005']):
            tpl = dict(self.tpl)
            tpl['id'] = boss
            kill_out = self.swing(asess, self.role(arid), tpl,
                                  f'm_92_{idx}')
            notices.extend(decode(bytes(f)[4:]) for f in kill_out)
        codes = [c[1][0] for c in notices if c[0] == '11101']
        self.assertEqual(codes.count(118009), 5)
        self.assertIn(118010, codes)
        self.assertEqual(
            set(json.loads(
                self.store.get_guild_fuben(gid, 1)['killboss'])),
            {'G200001', 'G200002', 'G200003', 'G200004', 'G200005'})

    # -- claims -----------------------------------------------------------------
    def claim(self, sess, boss='G200001', mainid=1):
        return frames(sess.guildfuben_reward([118002, [mainid, boss]]))

    def test_claim_flow_and_dup_guard(self):
        arid, asess, gid = self.guild()
        brid, bsess = self.member(gid)
        self.fund(gid)
        self.unseal(asess)
        self.enter(asess)
        self.enter(bsess)
        self.swing(asess, self.role(arid), self.tpl, MID)
        # Unslain boss.
        self.assertEqual(self.claim(asess, 'G200002'),
                         [['118002', [0, 118003]]])
        out = self.claim(asess)
        self.assertEqual(out, [['118002', [1, 1, 'G200001']]])
        slots = self.store.get_role_bag_slots(arid, 1, 150)
        self.assertEqual([(r['goods_id'], r['count']) for r in slots],
                         [('jinjiedan003', 1)])
        # Duplicate claim.
        self.assertEqual(self.claim(asess),
                         [['118002', [0, 118005]]])
        # Teammate claims the same shared chest.
        self.assertEqual(self.claim(bsess),
                         [['118002', [1, 1, 'G200001']]])
        history = json.loads(
            self.store.get_guild_fuben_reward(brid)['reward_history'])
        self.assertEqual(history['1'], ['G200001'])

    def test_late_joiner_not_on_roster(self):
        arid, asess, gid = self.guild()
        self.fund(gid)
        self.unseal(asess)
        self.enter(asess)
        self.swing(asess, self.role(arid), self.tpl, MID)
        _crid, csess = self.member(gid)
        self.assertEqual(self.claim(csess),
                         [['118002', [0, 118004]]])

    def test_full_bag_blocks_claim(self):
        arid, asess, gid = self.guild()
        self.fund(gid)
        self.unseal(asess)
        self.enter(asess)
        self.swing(asess, self.role(arid), self.tpl, MID)
        self.store.save_role_bag_state(arid, bag_capacity=0,
                                       storage_capacity=0)
        self.assertEqual(self.claim(asess),
                         [['118002', [0, 1006]]])
        self.assertEqual(json.loads(
            self.store.get_guild_fuben_reward(arid)['reward_history']),
            {})

    # -- leave / disconnect / disband --------------------------------------------
    def test_disconnect_drops_attempt(self):
        arid, asess, gid = self.guild()
        self.fund(gid)
        self.unseal(asess)
        self.enter(asess)
        self.assertIn(arid, asess._guildfuben_attempt)
        asess._guildfuben_on_disconnect()
        self.assertNotIn(arid, asess._guildfuben_attempt)
        self.assertNotIn(arid, asess._guildfuben_inside)
        # Re-entry works after the drop.
        self.assertEqual(self.enter(asess)[-1], ['118003', [1]])
        _ = gid

    def test_self_exit_evicts_with_118004(self):
        arid, asess, gid = self.guild()
        brid, bsess = self.member(gid)
        self.fund(gid)
        self.unseal(asess)
        self.enter(asess)
        self.enter(bsess)
        # Master exits with a member present: leadership passes, the
        # leaver is evicted from the copy, the member stays inside.
        out = frames(asess.guild_exit([53005, None]))
        self.assertNotIn(arid, asess._guildfuben_attempt)
        self.assertIn(['118004', [1]], out)
        self.assertIn(brid, bsess._guildfuben_attempt)
        got = self.drain(bsess)
        self.assertFalse(any(c[0] == '118004' for c in got))
        _ = gid

    def test_kick_evicts_cross_session(self):
        arid, asess, gid = self.guild()
        brid, bsess = self.member(gid)
        self.fund(gid)
        self.unseal(asess)
        self.enter(asess)
        self.enter(bsess)
        out = frames(asess.guild_exit([53005, str(brid)]))
        self.assertEqual(out[0], ['53005', [1, 1]])
        got = self.drain(bsess)
        self.assertNotIn(brid, bsess._guildfuben_attempt)
        self.assertTrue(any(c == ['118004', [1]] for c in got))
        _ = arid

    def test_disband_clears_rows_and_evicts(self):
        arid, asess, gid = self.guild()
        brid, bsess = self.member(gid)
        self.fund(gid)
        self.unseal(asess)
        self.enter(asess)
        self.enter(bsess)
        out = frames(asess.guild_disband())
        self.assertEqual(out[0][0], '20000')
        self.assertIn(['118004', [1]], out)
        self.assertIn(['53009', [1]], out)
        self.assertEqual(self.store.list_guild_fubens(gid), [])
        got_a = self.drain(asess)
        got_b = self.drain(bsess)
        self.assertNotIn(arid, asess._guildfuben_attempt)
        self.assertNotIn(brid, bsess._guildfuben_attempt)
        # A's evict frame arrived in the direct disband reply above;
        # B's was queued cross-session and arrives on drain.
        self.assertFalse(any(c == ['118004', [1]] for c in got_a))
        self.assertTrue(any(c == ['118004', [1]] for c in got_b))

    # -- weekly reset ---------------------------------------------------------------
    def test_weekly_reset_seals_and_cools_down(self):
        arid, asess, gid = self.guild()
        brid, bsess = self.member(gid)
        self.fund(gid)
        self.unseal(asess)
        self.enter(asess)
        self.enter(bsess)
        self.swing(asess, self.role(arid), self.tpl, MID)
        self.assertEqual(self.claim(bsess),
                         [['118002', [1, 1, 'G200001']]])
        # Age the dungeon row past a reset boundary.
        self.assertEqual(frames(asess.guildfuben_quit([118004, '1']))[-1],
                         ['118004', [1]])
        row = dict(self.store.get_guild_fuben(gid, 1))
        row['log_update_time'] = 1000
        self.store.save_guild_fuben(row)
        out = frames(asess.guildfuben_info())
        panel = out[0][1][0]
        self.assertEqual(panel[1], [])
        self.assertEqual(panel[2], [])
        self.assertEqual(panel[3], 0)
        # The reset arms the 10-minute cooldown on the resetting
        # session; a different session has no cooldown stamp, so its
        # fresh entry reaches the sealed row and fails there.
        self.assertEqual(self.enter(asess),
                         [['118003', [0, 118013]]])
        self.assertEqual(self.enter(bsess),
                         [['118003', [0, 118006]]])
        # The first post-reset entry stamped this session too, so the
        # next attempt meets the 10-minute re-entry cooldown instead.
        self.assertEqual(frames(bsess.guildfuben_quit([118004, '1']))[-1],
                         ['118004', [1]])
        self.assertEqual(self.enter(bsess),
                         [['118003', [0, 118013]]])

    def test_login_prunes_expired_claims(self):
        arid, asess, gid = self.guild()
        self.fund(gid)
        self.unseal(asess)
        self.enter(asess)
        self.swing(asess, self.role(arid), self.tpl, MID)
        self.assertEqual(self.claim(asess),
                         [['118002', [1, 1, 'G200001']]])
        reward = dict(self.store.get_guild_fuben_reward(arid))
        reward['update_time'] = json.dumps({'1': 1000})
        self.store.save_guild_fuben_reward(reward)
        asess._guildfuben_on_enter(arid)
        self.assertEqual(json.loads(
            self.store.get_guild_fuben_reward(arid)['reward_history']),
            {})
        # The chest is claimable again after the prune.
        self.assertEqual(self.claim(asess),
                         [['118002', [1, 1, 'G200001']]])
        _ = gid


if __name__ == '__main__':
    unittest.main()

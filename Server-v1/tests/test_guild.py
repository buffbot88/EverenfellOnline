"""Guild management (GuildAction 53000-53009/53013-53017/53024/53028-53030/53051).

Evidence: GuildAction javap (param shapes, reply-vs-void routes, silent
guards), GuildServiceImpl bytecode (gate order, error codes,
PublicMsgQueue fan-out), GuildVoOutput/GuildMemberVoOutput/
GuildBannerOutput/GuildGongxianOutput/GuildInfoOutput/SimpleClanVoOutput
shapes, GuildErrorCode clinit, and the GongHuiChuangJian (create cost 1M
YXB + bangpai:1, level 20), GongHuiZhiWei (permission flags) and
GongHuiQiZhiBiao (banner caps) tables.

Every path runs through the real handlers, the real SQLite store and a
shared StageRegistry: pushes to other sessions land in their tick
outbox, like the PublicMsgQueue flush.
"""
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode, encode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session, frame  # noqa: E402
from game.protocol import CMD_GUILD_BY_ROLE  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..',
                           'reference', 'TonNgoKhong', 'server', 'config',
                           'game')
HAVE_REAL = os.path.isdir(REAL_CONFIG)
INITKEY = bytes.fromhex('00000009060f494e49544b4559')


def frames(out):
    if out is None:
        return []
    if isinstance(out, (bytes, bytearray)):
        return [decode(bytes(out)[4:])]
    return [decode(bytes(f)[4:]) for f in out]


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class GuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, 'g.db')
        self.store = Store(self.db_path)
        self.addCleanup(self.store.close)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.reg = StageRegistry()
        self.seq = 0

    # -- helpers ---------------------------------------------------------
    def session(self, name, level=56, tongqian=2000000):
        self.seq += 1
        acct = f'hero{self.seq}'
        self.store.create_account(acct, hash_password('pw'))
        rid = self.store.create_character(
            acct, 'fu1304', name, job='C', level=level, tongqian=tongqian)
        sess = Session(
            conn_id=self.seq, check_sign=lambda *a: False,
            get_roles=lambda u, s, _a=acct: [dict(r) for r in
                                             self.store.list_roles(_a, s)],
            server_start_ms=0,
            get_role_brief=self.store.get_role_brief,
            save_role_state=self.store.update_character_state,
            get_role_bag_slots=self.store.get_role_bag_slots,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            get_guild_id=self.store.get_guild_id,
            save_guild_member=self.store.save_guild_member,
            add_guild_gongxian=self.store.add_guild_gongxian,
            get_guild=self.store.get_guild,
            list_guilds=self.store.list_guilds,
            save_guild=self.store.save_guild,
            delete_guild=self.store.delete_guild,
            find_guild_by_name=self.store.find_guild_by_name,
            find_guild_by_banner_name=self.store.find_guild_by_banner_name,
            search_guilds=self.store.search_guilds,
            get_guild_member=self.store.get_guild_member,
            get_guild_members=self.store.get_guild_members,
            count_guild_position=self.store.count_guild_position,
            delete_guild_member=self.store.delete_guild_member,
            add_guild_apply=self.store.add_guild_apply,
            has_guild_apply=self.store.has_guild_apply,
            list_guild_applies=self.store.list_guild_applies,
            delete_guild_apply=self.store.delete_guild_apply,
            save_guild_gongxian=self.store.save_guild_gongxian,
            list_guild_gongxian=self.store.list_guild_gongxian,
            delete_guild_gongxian=self.store.delete_guild_gongxian,
            add_guild_info=self.store.add_guild_info,
            list_guild_info=self.store.list_guild_info,
            config=self.cfg, stage_registry=self.reg)
        sess.authed_user, sess.server_id = acct, 'fu1304'
        self.reg.mark_online(rid, sess)
        return rid, sess

    def create(self, sess, name='天地会', banner='龙旗', banner_id=1,
               setting=0, decr=1):
        return sess.guild_create([53000, [name, banner, banner_id,
                                          setting, decr]])

    def master(self, name='天地会', banner='龙旗'):
        rid, sess = self.session(f'Wukong{self.seq + 100}')
        out = self.create(sess, name, banner)
        got = frames(out)
        self.assertEqual(got[0][0], '53000')
        self.assertEqual(got[0][1][0], 1)
        return rid, sess, got[0][1][1][0]

    def role(self, rid, acct_seq=None):
        for i in range(1, self.seq + 1):
            for r in self.store.list_roles(f'hero{i}', 'fu1304'):
                if str(r['id']) == str(rid):
                    return dict(r)
        return None

    def wire(self, sess, cmd, data):
        req = sess.cipher.encode(encode([cmd, data]))
        return frames(sess.feed(struct.pack('>I', len(req)) + req))

    # -- creation ----------------------------------------------------------
    def test_create_success_deducts_and_masters(self):
        rid, sess = self.session('WukongA')
        before = self.role(rid)['tongqian']
        out = frames(self.create(sess))
        self.assertEqual(out[0], ['53000', [1, out[0][1][1]]])
        vo = out[0][1][1]
        self.assertEqual(vo[1], '天地会')
        self.assertEqual(vo[9], str(rid))
        member = self.store.get_guild_member(rid)
        self.assertEqual(member['position'], 0)
        self.assertEqual(self.role(rid)['tongqian'], before - 1000000)

    def test_create_gates(self):
        rid, sess = self.session('WukongB')
        self.assertEqual(frames(self.create(sess, 'x'))[0],
                         ['53000', [0, 470003]])
        self.assertEqual(frames(self.create(sess, 'ABCDEF'))[0],
                         ['53000', [0, 470004]])
        self.assertEqual(frames(self.create(sess))[0][1][0], 1)
        self.assertEqual(frames(self.create(sess, '风云会'))[0],
                         ['53000', [0, 470002]])
        _r2, s2 = self.session('WukongC')
        self.assertEqual(frames(self.create(s2, '天地会', '月旗'))[0],
                         ['53000', [0, 470005]])
        self.assertEqual(frames(self.create(s2, '风云会', '龙旗'))[0],
                         ['53000', [0, 470008]])
        _r3, s3 = self.session('WukongD', level=10)
        self.assertEqual(frames(self.create(s3, '风云会', '月旗'))[0],
                         ['53000', [0, 470010]])
        _r4, s4 = self.session('WukongE', tongqian=10)
        self.assertEqual(frames(self.create(s4, '风云会', '月旗'))[0],
                         ['53000', [0, 470009]])
        self.assertEqual(frames(s2.guild_create(
            [53000, ['风云会', '月旗', 99, 0, 1]]))[0],
            ['53000', [0, 470046]])
        self.assertEqual(frames(s4.guild_create(
            [53000, ['', '月旗', 1, 0, 1]]))[0],
            ['53000', [0, 470000]])

    def test_create_enables_guild_task_gate(self):
        rid, sess = self.session('WukongF')
        gid = frames(self.create(sess, '云会友', '云旗友'))[0][1][1][0]
        self.assertEqual(self.store.get_guild_id(rid), gid)

    # -- apply / invite ----------------------------------------------------
    def test_apply_approve_membership(self):
        _a, master, gid = self.master()
        brid, b = self.session('WukongG')
        self.assertEqual(frames(b.guild_apply([53001, gid]))[0],
                         ['53001', [1, 1]])
        admin_frames = frames(master.tick(now_ms=0))
        self.assertTrue(any(f[0] == '53002' for f in admin_frames))
        master.guild_apply_reply([53002, [True, str(brid)]])
        got = frames(b.tick(now_ms=0))
        self.assertTrue(any(f[0] == '53001' and f[1][0] == 1
                            for f in got))
        member = self.store.get_guild_member(brid)
        self.assertEqual(member['position'], 3)
        self.assertFalse(self.store.has_guild_apply(gid, brid))

    def test_apply_duplicate_member_rejected(self):
        _a, master, gid = self.master('风云甲', '风旗甲')
        brid, b = self.session('WukongH')
        b.guild_apply([53001, gid])
        master.guild_apply_reply([53002, [True, str(brid)]])
        b.tick(now_ms=0)
        self.assertEqual(frames(b.guild_apply([53001, gid]))[0],
                         ['53001', [0, 470011]])

    def test_apply_refuse_notifies_target(self):
        _a, master, gid = self.master('风云乙', '风旗乙')
        brid, b = self.session('WukongI')
        b.guild_apply([53001, gid])
        master.tick(now_ms=0)
        master.guild_apply_reply([53002, [False, str(brid)]])
        got = frames(b.tick(now_ms=0))
        self.assertIn(['53001', [0, 470125]], got)
        self.assertIsNone(self.store.get_guild_member(brid))

    def test_invite_accept_and_refuse(self):
        _a, master, gid = self.master('风云丙', '风旗丙')
        crid, c = self.session('WukongJ')
        self.assertEqual(frames(master.guild_invite(
            [53003, str(crid)]))[0], ['53003', [1, 1]])
        got = frames(c.tick(now_ms=0))
        self.assertIn(['53004', [gid, '风云丙']], got)
        c.guild_invite_reply([53004, [True, gid]])
        self.assertEqual(self.store.get_guild_member(crid)['position'], 3)
        brid, b = self.session('WukongK')
        master.guild_invite([53003, str(brid)])
        b.tick(now_ms=0)
        b.guild_invite_reply([53004, [False, gid]])
        admin_frames = frames(master.tick(now_ms=0))
        self.assertTrue(any(f[0] == '53003' and f[1][0] == 0
                            for f in admin_frames))
        self.assertIsNone(self.store.get_guild_member(brid))

    # -- positions / kick --------------------------------------------------
    def test_position_caps_and_transfer(self):
        arid, master, gid = self.master('风云丁', '风旗丁')
        b, c, d, e = (self.session(n)[0] for n in
                      ('WukongL', 'WukongM', 'WukongN', 'WukongO'))
        for r in (b, c, d, e):
            self.store.save_guild_member(r, gid, 3)
        master.guild_position([53015, [str(b), 1]])
        self.assertEqual(self.store.get_guild_member(b)['position'], 1)
        self.assertEqual(self.store.get_guild(gid)['vice_user_role_id'],
                         str(b))
        got = frames(master.guild_position([53015, [str(c), 1]]))
        self.assertIn(['53015', [0, 470054]], got)
        self.assertEqual(self.store.get_guild_member(c)['position'], 3)
        for r in (c, d, e):
            master.guild_position([53015, [str(r), 2]])
        f = self.session('WukongP')[0]
        self.store.save_guild_member(f, gid, 3)
        got = frames(master.guild_position([53015, [str(f), 2]]))
        self.assertIn(['53015', [0, 470053]], got)
        _bsess = None
        master.guild_position([53015, [str(b), 0]])
        self.assertEqual(self.store.get_guild_member(b)['position'], 0)
        self.assertEqual(self.store.get_guild_member(arid)['position'], 1)

    def test_kick_seniority(self):
        arid, master, gid = self.master('风云戊', '风旗戊')
        brid, b = self.session('WukongQ')
        self.store.save_guild_member(brid, gid, 3)
        self.assertEqual(frames(b.guild_exit([53005, str(arid)]))[0],
                         ['53005', [0, 470024]])
        out = frames(master.guild_exit([53005, str(brid)]))
        self.assertEqual(out[0], ['53005', [1, 1]])
        self.assertIsNone(self.store.get_guild_member(brid))
        got = frames(b.tick(now_ms=0))
        self.assertIn(['53005', [str(brid)]], got)

    # -- exit / disband ----------------------------------------------------
    def test_master_exit_transfers(self):
        arid, master, gid = self.master('风云己', '风旗己')
        brid, b = self.session('WukongR')
        crid, _c = self.session('WukongS')
        self.store.save_guild_member(brid, gid, 1)
        self.store.save_guild_member(crid, gid, 3)
        master.guild_exit([53005, None])
        self.assertIsNone(self.store.get_guild_member(arid))
        self.assertEqual(self.store.get_guild(gid)['user_role_id'],
                         str(brid))
        self.assertEqual(self.store.get_guild_member(brid)['position'], 0)
        got = frames(b.tick(now_ms=0))
        self.assertTrue(any(f[0] == '53005' for f in got))

    def test_last_member_exit_disbands(self):
        rid, sess, gid = self.master('风云庚', '风旗庚')
        out = frames(sess.guild_exit([53005, None]))
        self.assertEqual(out[0], ['53005', [1, 1]])
        self.assertIsNone(self.store.get_guild(gid))
        self.assertIsNone(self.store.get_guild_member(rid))

    def test_disband_and_perm(self):
        _a, master, gid = self.master('风云辛', '风旗辛')
        brid, b = self.session('WukongT')
        self.store.save_guild_member(brid, gid, 3)
        got = frames(b.guild_disband())
        self.assertIn(['53009', [0, 470022]], got)
        self.assertIsNotNone(self.store.get_guild(gid))
        master.guild_disband()
        self.assertIsNone(self.store.get_guild(gid))
        got = frames(b.tick(now_ms=0))
        self.assertIn(['53009', [1]], got)

    # -- setting / message -------------------------------------------------
    def test_setting_and_message(self):
        _a, master, gid = self.master('风云壬', '风旗壬')
        _brid, b = self.session('WukongU')
        self.store.save_guild_member(_brid, gid, 3)
        master.guild_setting([53013, 1])
        self.assertEqual(self.store.get_guild(gid)['guild_setting'], 1)
        got = frames(b.tick(now_ms=0))
        self.assertIn(['53013', [1, 1]], got)
        got = frames(b.guild_setting([53013, 0]))
        self.assertIn(['53013', [0, 470033]], got)
        out = frames(master.guild_message([53014, '欢迎光临']))
        self.assertEqual(out[0], ['53014', [1, 1]])
        self.assertEqual(self.store.get_guild(gid)['guild_message'],
                         '欢迎光临')
        self.assertEqual(frames(b.guild_message([53014, '你好']))[0],
                         ['53014', [0, 470034]])
        self.assertEqual(frames(master.guild_message(
            [53014, 'x' * 101]))[0], ['53014', [0, 470055]])

    # -- contributions -----------------------------------------------------
    def test_contrib_money(self):
        rid, sess, gid = self.master('风云癸', '风旗癸')
        before = self.role(rid)['tongqian']
        sess.guild_contrib_money([53016, 5000])
        self.assertEqual(self.role(rid)['tongqian'], before - 5000)
        self.assertEqual(self.store.get_guild(gid)['money'], 5000)
        member = self.store.get_guild_member(rid)
        self.assertEqual(member['gongxian'], 5000)
        entries = self.store.list_guild_gongxian(gid)
        self.assertEqual(entries[-1]['money'], 5000)
        got = frames(sess.guild_contrib_money([53016, 10 ** 12]))
        self.assertIn(['53016', [0, 1003]], got)

    def test_contrib_goods_and_cap(self):
        rid, sess, gid = self.master('云甲会', '云甲旗')
        self.store.insert_role_bag_slot(
            rid, {'slot_num': 10, 'goods_id': 'lingql', 'count': 5,
                  'bind': 0})
        sess.guild_contrib_goods([53017, ['lingql', 1]])
        self.assertEqual(self.store.get_guild(gid)['qinglong_count'], 1)
        got = frames(sess.guild_contrib_goods([53017, ['lingql', 1]]))
        self.assertIn(['53017', [0, 470059]], got)
        self.assertEqual(self.store.get_guild(gid)['qinglong_count'], 1)

    # -- queries -----------------------------------------------------------
    def test_queries(self):
        _a, master, gid = self.master('云乙会', '云乙旗')
        out = frames(master.guild_by_role())
        self.assertEqual(out[0][0], '53006')
        self.assertEqual(out[0][1][1], '云乙会')
        out = frames(master.guild_by_guild([53024, gid]))
        self.assertEqual(out[0][1][1], '云乙会')
        out = frames(master.guild_by_guild([53024, 'nope']))
        self.assertEqual(out, [['53024', None]])
        out = frames(master.guild_by_id([53051, gid]))
        self.assertEqual(out[0][1][1], '云乙会')
        self.assertIsNone(master.guild_by_id([53051, 'nope']))
        out = frames(master.guild_list())
        self.assertTrue(any(g[1] == '云乙会' for g in out[0][1]))
        out = frames(master.guild_search([53030, '云乙']))
        self.assertTrue(any(g[1] == '云乙会' for g in out[0][1]))
        self.assertEqual(frames(master.guild_search([53030, '']))[0],
                         ['53030', []])
        out = frames(master.guild_banners())
        self.assertEqual(len(out[0][1][0]), 5)
        self.assertEqual(len(out[0][1][1]), 5)
        out = frames(master.guild_gongxian())
        self.assertEqual(out[0][0], '53029')
        out = frames(master.guild_info_detail())
        self.assertEqual(out[0][0], '53007')

    def test_guildless_behavior(self):
        _rid, sess = self.session('WukongV')
        self.assertIsNone(sess.guild_exit([53005, None]))
        self.assertIsNone(sess.guild_setting([53013, 1]))
        self.assertIsNone(sess.guild_position([53015, ['1', 1]]))
        self.assertIsNone(sess.guild_contrib_money([53016, 10]))
        out = frames(sess.guild_by_role())
        self.assertEqual(out, [['53006', None]])
        self.assertEqual(frames(sess.guild_banners())[0],
                         ['53028', [0, 470018]])

    # -- persistence + wire ------------------------------------------------
    def test_persistence_across_reopen(self):
        _a, _master, gid = self.master('云丙会', '云丙旗')
        brid, _b = self.session('WukongW')
        self.store.save_guild_member(brid, gid, 3)
        self.store.close()
        reopened = Store(self.db_path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.get_guild(gid)['name'], '云丙会')
        members = reopened.get_guild_members(gid)
        self.assertEqual(len(members), 2)
        self.assertEqual(
            sorted(m['position'] for m in members), [0, 3])

    def test_wire_dispatch_by_role(self):
        _a, sess, gid = self.master('云丁会', '云丁旗')
        sess.feed(INITKEY)
        got = self.wire(sess, CMD_GUILD_BY_ROLE, None)
        self.assertEqual(got[0][0], '53006')
        self.assertEqual(got[0][1][1], '云丁会')


if __name__ == '__main__':
    unittest.main()

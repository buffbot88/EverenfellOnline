"""Commands 42000/42003 + 99000/99001/99002: skill info/upgrade, skillbooks.

Evidence: jar bytecode (SkillAction.getSkill/upgradeSkill,
SkillServiceImpl.getSkill/upgradeSkill/autoStudySkill,
SkillbookAction.getSkillBookInfo/moveSkillBook/yjTunshi,
SkillbookServiceImpl.getSkillBookInfo/moveSkillBook/peidai/xieZai/move/
tunshi/yjTunshi/checkUpgradeLevel/checkPeiDai, SkillErrorCode(Output),
StudySkillOutput, SkillBookConfig row mapping, GoodsExpVo, isNewSkillBook)
plus real JiNengBiao/jinengshubiao/ZuoJiBiao/goods rows. 42004 is
push-only (no inbound route exists in SkillModuleInit) and is already
covered by the prop-use goldens in test_bag.py, like 30104/30105.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db import Store  # noqa: E402
from game.amf3 import Obj, decode, encode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2]
               / 'reference' / 'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config' / 'jinengshubiao.jat').is_file()

# niumowang1 L1: levelneed 1, zhenqineed 100, goldneed 1000, learnodds 1,
# no bianshenneed. zuoqijineng1: zuoqi book (gongnengtype 1, zuoqilv 5,
# jcexp 40, maxexp 160, L1 of the chongfeng1 ladder).
BOOK = 'zuoqijineng1'
BOOK2 = 'zuoqijineng1_1'
ALT_BOOK = 'lvsegongji1'


def write_bytes(directory, rel, data):
    path = os.path.join(directory, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    return path


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class SkillSliceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.store = Store(os.path.join(tmp, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', 'pw')
        self.role_id = str(self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56, tongqian=5000,
            zhenqi=5000))
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = self.sess_as()

    def sess_as(self, **override):
        role = dict(self.store.list_roles('hero', 'fu1304')[0], **override)
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [role],
            server_start_ms=0,
            get_role_skills=self.store.get_role_skills,
            save_role_skill=self.store.save_role_skill,
            get_role_shenjiang=self.store.get_role_shenjiang,
            get_role_zuoqi=self.store.get_role_zuoqi,
            save_role_state=self.store.update_character_state,
            get_role_bag_slot=self.store.get_role_bag_slot,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            get_role_skillbook_slots=self.store.get_role_skillbook_slots,
            get_role_skillbook_slot=self.store.get_role_skillbook_slot,
            insert_role_skillbook_slot=
            self.store.insert_role_skillbook_slot,
            update_role_skillbook_slot=
            self.store.update_role_skillbook_slot,
            delete_role_skillbook_slot=
            self.store.delete_role_skillbook_slot,
            config=self.cfg)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return sess

    def one(self, out):
        self.assertIsNotNone(out)
        if isinstance(out, tuple):
            self.assertEqual(len(out), 1)
            out = out[0]
        return decode(out[4:])

    @staticmethod
    def assoc(m):
        """Unwrap the decoder's dynamic-object envelope (test_bag.py)."""
        return m.get('__assoc__', m)

    def bag_row(self, slot, goods, count=1, attributes=None):
        return {'slot_num': slot, 'goods_id': goods, 'count': count,
                'bag_id': f'p{slot}', 'bind': 0, 'expire_time': 0,
                'rare_level': 0, 'item_level': 1, 'attributes': attributes}

    def role(self):
        return self.store.list_roles('hero', 'fu1304')[0]

    def mount(self, rank):
        self.store.save_role_zuoqi(self.role_id, rank, rank)

    # 42000 getSkill
    def test_info_lists_category_level_pairs(self):
        self.store.save_role_skill(self.role_id, 'niumowang1', 3)
        self.store.save_role_skill(self.role_id, 'kangxing1', 1)
        self.assertEqual(self.one(self.sess.skill_info()),
                         ['42000', [['kangxing1', 1], ['niumowang1', 3]]])

    def test_info_empty_is_empty_list(self):
        self.assertEqual(self.one(self.sess.skill_info()), ['42000', []])

    def test_info_without_role_is_silent(self):
        sess = self.sess_as()
        sess.get_roles = lambda u, s: []
        self.assertIsNone(sess.skill_info())

    # 42003 upgradeSkill
    def test_upgrade_learns_and_burns_costs(self):
        self.store.save_role_skill(self.role_id, 'niumowang1', 1)
        got = self.one(self.sess.skill_upgrade([42003, 'niumowang1']))
        self.assertEqual(got, ['42003', [1, 'niumowang1', 2]])
        skills = self.store.get_role_skills(self.role_id)
        self.assertEqual([s['level'] for s in skills
                          if s['category'] == 'niumowang1'], [2])
        self.assertEqual(self.role()['tongqian'], 4000)
        self.assertEqual(self.role()['zhenqi'], 4900)

    def test_upgrade_unknown_skill_reports_study_not(self):
        got = self.one(self.sess.skill_upgrade([42003, 'nope']))
        self.assertEqual(got, ['42003', [0, 420005]])
        self.assertEqual(self.role()['tongqian'], 5000)

    def test_upgrade_capped_at_100_without_consume(self):
        self.store.save_role_skill(self.role_id, 'niumowang1', 100)
        got = self.one(self.sess.skill_upgrade([42003, 'niumowang1']))
        self.assertEqual(got, ['42003', [0, 420010]])
        self.assertEqual(self.role()['tongqian'], 5000)

    def test_upgrade_at_role_level_reports_study_level(self):
        self.store.save_role_skill(self.role_id, 'niumowang1', 1)
        got = self.one(self.sess_as(level=1).skill_upgrade(
            [42003, 'niumowang1']))
        self.assertEqual(got, ['42003', [0, 420006]])
        self.assertEqual(self.role()['tongqian'], 5000)

    def test_upgrade_levelneed_reports_general_level(self):
        # No live row has levelneed above its level, so the branch is
        # proved with a synthetic table (test_ai precedent).
        cfg_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cfg_dir, ignore_errors=True)
        write_bytes(cfg_dir, 'sys_config/JiNengBiao.jat', encode([
            Obj(skilltype='synskill', level=1, levelneed=99, zhenqineed=0,
                goldneed=0, learnodds=1)]))
        sess = self.sess_as()
        sess.config = GameConfig(cfg_dir)
        self.store.save_role_skill(self.role_id, 'synskill', 1)
        got = decode(sess.skill_upgrade([42003, 'synskill'])[4:])
        self.assertEqual(got, ['42003', [0, 1000]])
        self.assertEqual(self.role()['tongqian'], 5000)

    def test_upgrade_zhenqi_short_reports_1001(self):
        self.store.save_role_skill(self.role_id, 'niumowang1', 1)
        got = self.one(self.sess_as(zhenqi=50).skill_upgrade(
            [42003, 'niumowang1']))
        self.assertEqual(got, ['42003', [0, 1001]])
        self.assertEqual(self.role()['tongqian'], 5000)

    def test_upgrade_money_short_reports_jb(self):
        self.store.save_role_skill(self.role_id, 'niumowang1', 1)
        got = self.one(self.sess_as(tongqian=500).skill_upgrade(
            [42003, 'niumowang1']))
        self.assertEqual(got, ['42003', [0, 1003]])
        self.assertEqual(self.role()['zhenqi'], 5000)

    def test_upgrade_odds_fail_burns_costs(self):
        # Every live learnodds is 1, so the fail branch is proved with
        # the white-box roll patch (vip-lottery precedent).
        self.store.save_role_skill(self.role_id, 'niumowang1', 1)
        with mock.patch.object(Session, '_lottery_roll', return_value=False):
            got = self.one(self.sess.skill_upgrade([42003, 'niumowang1']))
        self.assertEqual(got, ['42003', [-1]])
        skills = self.store.get_role_skills(self.role_id)
        self.assertEqual([s['level'] for s in skills
                          if s['category'] == 'niumowang1'], [1])
        self.assertEqual(self.role()['tongqian'], 4000)
        self.assertEqual(self.role()['zhenqi'], 4900)

    def test_upgrade_shenjiang_gate(self):
        # kangxing1 L1 needs bianshenneed sj0101|1.
        self.store.save_role_skill(self.role_id, 'kangxing1', 1)
        sess = self.sess_as(tongqian=5000, zhenqi=5000)
        self.assertEqual(self.one(sess.skill_upgrade([42003, 'kangxing1'])),
                         ['42003', [0, 420012]])
        self.store.db.execute(
            'INSERT INTO role_shenjiang(role_id, shenjiang_key, shenjiang_id,'
            ' jiangxing_rank) VALUES(?,?,?,?)',
            (self.role_id, 'k1', 'sj0101', 1))
        self.store.db.commit()
        # Rank 1 passes the gate; zhenqi 0 then trips the next gate.
        got = self.one(self.sess_as(tongqian=5000, zhenqi=0).skill_upgrade(
            [42003, 'kangxing1']))
        self.assertEqual(got, ['42003', [0, 1001]])

    def test_upgrade_missing_config_is_silent(self):
        self.store.save_role_skill(self.role_id, 'ghost-skill', 1)
        self.assertIsNone(self.sess.skill_upgrade([42003, 'ghost-skill']))
        skills = self.store.get_role_skills(self.role_id)
        self.assertEqual([s['level'] for s in skills
                          if s['category'] == 'ghost-skill'], [1])

    # 99000 getSkillBookInfo
    def test_book_info_empty_is_empty_list(self):
        self.assertEqual(self.one(self.sess.skillbook_info()), ['99000', []])

    def test_book_info_maps_worn_rows(self):
        self.mount(5)
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":7}')])
        self.sess.skillbook_move([99001, [5, 10001]])
        got = self.one(self.sess.skillbook_info())
        self.assertEqual(got[0], '99000')
        self.assertEqual(len(got[1]), 1)
        cell = self.assoc(got[1][0])
        self.assertEqual(cell['0'], BOOK)
        self.assertEqual(cell['2'], 10001)
        self.assertEqual(cell['15'], 7)

    # 99001 moveSkillBook: wear
    def test_wear_moves_bag_book_to_mount_slot(self):
        self.mount(5)
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}')])
        got = self.one(self.sess.skillbook_move([99001, [5, 10001]]))
        self.assertEqual(got[0], '99001')
        self.assertEqual(got[1][0], 1)
        self.assertEqual(got[1][1][0], 10001)
        self.assertEqual(self.assoc(got[1][1][1])['0'], BOOK)
        self.assertIsNone(got[1][2])
        self.assertIsNone(
            self.store.get_role_bag_slot(self.role_id, 5))
        worn = self.store.get_role_skillbook_slot(self.role_id, 10001)
        self.assertEqual(worn['goods_id'], BOOK)
        self.assertEqual(worn['bag_id'], 'p5')

    def test_wear_wrong_band_reports_type(self):
        self.mount(5)
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}')])
        got = self.one(self.sess.skillbook_move([99001, [5, 10031]]))
        self.assertEqual(got, ['99001', [0, 99003]])
        self.assertIsNotNone(
            self.store.get_role_bag_slot(self.role_id, 5))

    def test_wear_locked_slot_reports_unopen(self):
        self.mount(1)
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}')])
        got = self.one(self.sess.skillbook_move([99001, [5, 10001]]))
        self.assertEqual(got, ['99001', [0, 99004]])
        self.assertIsNotNone(
            self.store.get_role_bag_slot(self.role_id, 5))

    def test_wear_short_mount_rank_reports_zuoqi(self):
        self.mount(4)
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}')])
        got = self.one(self.sess.skillbook_move([99001, [5, 10001]]))
        self.assertEqual(got, ['99001', [0, 99005]])
        self.assertIsNotNone(
            self.store.get_role_bag_slot(self.role_id, 5))

    def test_wear_only_dupe_reports_only(self):
        self.mount(6)
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}'),
                           self.bag_row(6, BOOK2, 1, '{"exp":0}')])
        self.one(self.sess.skillbook_move([99001, [5, 10001]]))
        got = self.one(self.sess.skillbook_move([99001, [6, 10002]]))
        self.assertEqual(got, ['99001', [0, 99007]])
        self.assertIsNotNone(
            self.store.get_role_bag_slot(self.role_id, 6))

    def test_wear_swap_with_taken_slot(self):
        self.mount(6)
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}'),
                           self.bag_row(6, ALT_BOOK, 1, '{"exp":0}')])
        self.one(self.sess.skillbook_move([99001, [5, 10001]]))
        got = self.one(self.sess.skillbook_move([99001, [6, 10001]]))
        self.assertEqual(got[0], '99001')
        self.assertEqual(got[1][0], 1)
        self.assertEqual(self.assoc(got[1][1][1])['0'], ALT_BOOK)
        back = self.store.get_role_bag_slot(self.role_id, 6)
        self.assertEqual(back['goods_id'], BOOK)
        worn = self.store.get_role_skillbook_slot(self.role_id, 10001)
        self.assertEqual(worn['goods_id'], ALT_BOOK)

    def test_wear_unknown_book_is_silent_null(self):
        self.mount(5)
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, 'ghost-book', 1)])
        got = self.one(self.sess.skillbook_move([99001, [5, 10001]]))
        self.assertEqual(got, ['99001', None])
        self.assertIsNotNone(
            self.store.get_role_bag_slot(self.role_id, 5))

    # 99001: strip
    def test_strip_returns_book_to_bag(self):
        self.mount(5)
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}')])
        self.one(self.sess.skillbook_move([99001, [5, 10001]]))
        got = self.one(self.sess.skillbook_move([99001, [10001, 7]]))
        self.assertEqual(got, ['99001', [1, [10001, None], None]])
        self.assertIsNone(
            self.store.get_role_skillbook_slot(self.role_id, 10001))
        back = self.store.get_role_bag_slot(self.role_id, 7)
        self.assertEqual(back['goods_id'], BOOK)

    def test_strip_errors_leave_state(self):
        got = self.one(self.sess.skillbook_move([99001, [10001, 7]]))
        self.assertEqual(got, ['99001', [0, 99000]])
        self.mount(5)
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}'),
                           self.bag_row(7, BOOK, 1, '{"exp":0}')])
        self.one(self.sess.skillbook_move([99001, [5, 10001]]))
        got = self.one(self.sess.skillbook_move([99001, [10001, 7]]))
        self.assertEqual(got, ['99001', [0, 99000]])
        self.assertIsNotNone(
            self.store.get_role_skillbook_slot(self.role_id, 10001))

    # 99001: shift
    def test_shift_slides_within_band(self):
        self.mount(6)
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}')])
        self.one(self.sess.skillbook_move([99001, [5, 10001]]))
        got = self.one(self.sess.skillbook_move([99001, [10001, 10002]]))
        self.assertEqual(got[0], '99001')
        self.assertEqual(got[1][0], 1)
        self.assertEqual(got[1][1][0], 10002)
        self.assertEqual(self.assoc(got[1][1][1])['0'], BOOK)
        self.assertEqual(got[1][2], [10001, None])
        self.assertIsNone(
            self.store.get_role_skillbook_slot(self.role_id, 10001))
        self.assertEqual(
            self.store.get_role_skillbook_slot(
                self.role_id, 10002)['goods_id'], BOOK)

    def test_shift_across_bands_reports_error(self):
        self.mount(6)
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}')])
        self.one(self.sess.skillbook_move([99001, [5, 10001]]))
        # 10031 sits in the unmigrated qizhan band, so Java's own
        # isOpenSlot check fires (99004) before the isMove check; the
        # isMove [0, 99000] branch needs an open cross-band slot, which
        # no live data provides.
        got = self.one(self.sess.skillbook_move([99001, [10001, 10031]]))
        self.assertEqual(got, ['99001', [0, 99004]])

    def test_shift_into_locked_slot_reports_unopen(self):
        self.mount(5)
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}')])
        self.one(self.sess.skillbook_move([99001, [5, 10001]]))
        got = self.one(self.sess.skillbook_move([99001, [10001, 10002]]))
        self.assertEqual(got, ['99001', [0, 99004]])

    def test_routing_fallback_reports_error(self):
        got = self.one(self.sess.skillbook_move([99001, [5, 200]]))
        self.assertEqual(got, ['99001', [0, 99000]])

    # 99001: tunshi feed
    def test_feed_merges_exp_and_clears_eater(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}'),
                           self.bag_row(6, BOOK, 1, '{"exp":0}')])
        out = self.sess.skillbook_move([99001, [5, 6]])
        got = [decode(f[4:]) for f in out]
        self.assertEqual([f[0] for f in got], ['30106', '99001'])
        self.assertEqual(got[1][1][0], 1)
        self.assertEqual(got[1][1][1][0], 6)
        self.assertEqual(self.assoc(got[1][1][1][1])['0'], BOOK)
        self.assertEqual(got[1][1][2], [5, None])
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 5))
        food = self.store.get_role_bag_slot(self.role_id, 6)
        self.assertEqual(food['goods_id'], BOOK)
        self.assertEqual(json.loads(food['attributes'])['exp'], 40)
        self.assertEqual(self.assoc(got[0][1][0])['15'], 40)

    def test_feed_promotes_past_maxexp(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}'),
                           self.bag_row(6, BOOK, 1, '{"exp":150}')])
        out = self.sess.skillbook_move([99001, [5, 6]])
        got = [decode(f[4:]) for f in out]
        self.assertEqual(self.assoc(got[1][1][1][1])['0'], BOOK2)
        food = self.store.get_role_bag_slot(self.role_id, 6)
        self.assertEqual(food['goods_id'], BOOK2)
        self.assertEqual(json.loads(food['attributes'])['exp'], 190)

    def test_feed_same_slot_reports_same(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}')])
        got = self.one(self.sess.skillbook_move([99001, [5, 5]]))
        self.assertEqual(got, ['99001', [0, 99013]])
        self.assertIsNotNone(
            self.store.get_role_bag_slot(self.role_id, 5))

    def test_feed_non_book_reports_error(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}'),
                           self.bag_row(6, 'silver50', 1)])
        got = self.one(self.sess.skillbook_move([99001, [5, 6]]))
        self.assertEqual(got, ['99001', [0, 99000]])

    # 99002 yjTunshi
    def test_bulk_devour_feeds_in_order(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}'),
                           self.bag_row(6, BOOK, 1, '{"exp":0}'),
                           self.bag_row(7, BOOK, 1, '{"exp":0}')])
        out = self.sess.skillbook_tunshi([99002, [5, [6, 7]]])
        got = [decode(f[4:]) for f in out]
        self.assertEqual([f[0] for f in got], ['30106', '99002'])
        self.assertEqual(got[1][1][0], 1)
        self.assertEqual(got[1][1][1][0], 5)
        self.assertEqual(self.assoc(got[1][1][1][1])['0'], BOOK)
        eater = self.store.get_role_bag_slot(self.role_id, 5)
        self.assertEqual(json.loads(eater['attributes'])['exp'], 80)
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 6))
        self.assertIsNone(self.store.get_role_bag_slot(self.role_id, 7))

    def test_bulk_devour_empty_foods_is_silent(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, BOOK, 1, '{"exp":0}')])
        self.assertIsNone(self.sess.skillbook_tunshi([99002, [5, []]]))

    def test_bulk_devour_missing_eater_reports_error(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(6, BOOK, 1, '{"exp":0}')])
        got = self.one(self.sess.skillbook_tunshi([99002, [9, [6]]]))
        self.assertEqual(got, ['99002', [0, 99000]])

    def test_bulk_devour_capped_eater_reports_max(self):
        self.store.save_role_bag_slots(
            self.role_id, [self.bag_row(5, 'zuoqijineng1_9', 1,
                                        '{"exp":0}'),
                           self.bag_row(6, BOOK, 1, '{"exp":0}')])
        got = self.one(self.sess.skillbook_tunshi([99002, [5, [6]]]))
        self.assertEqual(got, ['99002', [0, 99002]])


class SkillAutoLearnTest(unittest.TestCase):
    """P:ROLE_CREATE / P:ROLE_LEVEL_UPGRADE -> SkillServiceImpl auto-learn.

    Evidence: SkillRoleCreateEventHandler -> createRoleStudySkill (level-1
    learnSkill tokens, needJob gate only, silent inserts) and
    SkillRoleStudyEventHandler -> roleLevelUpgradeSkill (per new level,
    autoStudySkill with needAutoLearn=false, so levelneed/job/config-level
    gates apply and each learn pushes 42004). The reference JiNengBiao's
    level-1 tokens (mb/yx/bh/lx) carry an empty needjob, which Java's
    "needjob is neither '0' nor the job" check rejects, so this suite
    writes a small fixture table to exercise the gates (test_marry.py
    pattern for legacy-absent data).
    """

    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.cfgdir = os.path.join(tmp, 'cfg')
        write_bytes(self.cfgdir, 'sys_config/ZhuJueShuXingBiao.jat', encode([
            Obj(level=1,
                learnskill='sk_job;sk_any;sk_other;sk_late;sk_missing'),
            Obj(level=5, learnskill='sk_job5;sk_other5;sk_late5'),
        ]))
        rows = [
            Obj(skilltype='sk_job', level=1, needjob='C', levelneed=1),
            Obj(skilltype='sk_any', level=1, needjob='0', levelneed=1),
            Obj(skilltype='sk_other', level=1, needjob='A', levelneed=1),
            Obj(skilltype='sk_late', level=1, needjob='0', levelneed=50),
            Obj(skilltype='sk_job5', level=1, needjob='C', levelneed=5),
            Obj(skilltype='sk_other5', level=1, needjob='B', levelneed=5),
            Obj(skilltype='sk_late5', level=1, needjob='0', levelneed=50),
        ]
        write_bytes(self.cfgdir, 'sys_config/JiNengBiao.jat', encode(rows))
        self.store = Store(os.path.join(tmp, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', 'pw')
        self.rid = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=1)
        self.cfg = GameConfig(self.cfgdir)
        self.sess = self.session()

    def session(self, **override):
        roles = [dict(r) for r in self.store.list_roles('hero', 'fu1304')]
        roles = [dict(roles[0], **override)] if roles else []
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: roles,
            server_start_ms=0,
            get_role_skills=self.store.get_role_skills,
            save_role_skill=self.store.save_role_skill,
            create_role=lambda acct, sid, name, job, sex, face:
                self.store.create_character(
                    acct, sid, name, job=job, sex=sex, face=face, level=1),
            config=self.cfg)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return sess

    def owned(self):
        return {s['category'] for s in self.store.get_role_skills(self.rid)}

    def test_create_learn_gates_job_only(self):
        # createRoleStudySkill checks needjob and nothing else: a matched
        # job learns, '0' is open to all, and levelneed/config level are
        # NOT consulted at creation (Java's insert2DB loop).
        self.sess._skill_create_learn(self.rid, 'C')
        self.assertEqual(self.owned(), {'sk_job', 'sk_any', 'sk_late'})

    def test_create_learn_skips_other_jobs(self):
        self.sess._skill_create_learn(self.rid, 'A')
        self.assertEqual(self.owned(), {'sk_any', 'sk_other', 'sk_late'})

    def test_create_role_wire_seeds_skills(self):
        out = self.sess.create_role(
            [10002, ['hero', '八戒', 'C', 0, '1', 0, 'fu1304', 'p']])
        got = decode(out[4:])
        self.assertEqual(got[0], '10002')
        self.assertEqual(got[1][0], 1)
        role_id = got[1][1][0]
        self.assertEqual(
            {s['category'] for s in self.store.get_role_skills(role_id)},
            {'sk_job', 'sk_any', 'sk_late'})

    def test_level_learn_applies_all_gates(self):
        frames = self.sess._skill_level_learn(self.rid, 5, 'C')
        # sk_job5 passes (job C, levelneed 5, config level 1); sk_other5 is
        # another job; sk_late5 needs level 50.
        self.assertEqual(self.owned(), {'sk_job5'})
        self.assertEqual([decode(f[4:]) for f in frames],
                         [['42004', ['sk_job5', 1]]])

    def test_level_learn_skips_owned(self):
        self.store.save_role_skill(self.rid, 'sk_job5', 1)
        self.assertEqual(
            self.sess._skill_level_learn(self.rid, 5, 'C'), [])
        self.assertEqual(self.owned(), {'sk_job5'})

    def test_level_learn_without_config_is_empty(self):
        sess = self.session()
        sess.config = None
        self.assertEqual(sess._skill_level_learn(self.rid, 5, 'C'), [])


if __name__ == '__main__':
    unittest.main()

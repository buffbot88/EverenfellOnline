"""Character level progression: UserRoleServiceImpl.calUpgradeAndExp,
RoleExportServiceImpl.incrExp fan-out, and derived-stat recomputation.

Evidence: jar bytecode (calUpgradeAndExp banks at loadMaxLevel,
otherwise spends needexp per rung with a zeroed bar and recurses;
incrExp publishes one RoleLevelUpgradeEvent per gained level, then the
12001 [exp, level] push; roleUpgrade swaps the level row and emits
outputAttributeChange [12004/12005/12000] plus 12002; SkillServiceImpl
roleLevelUpgradeSkill learns each event level's tokens with a 42004
study notice; ShengJiEventHandler routes the upgrade event to
shengJiRecevieMainTask) plus ZhuJueShuXingBiao.jat (95 shipped levels,
needexp/learnskill cells) and the ported 50004 receive chain.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode  # noqa: E402
from game import combat as combat_lib  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2]
               / 'reference' / 'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config' / 'ZhuJueShuXingBiao.jat').is_file()


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class CalUpgradeExpTest(unittest.TestCase):
    """apply_exp_gain mirrors the calUpgradeAndExp rung loop."""

    def setUp(self):
        self.cfg = GameConfig(str(REAL_CONFIG))

    def gain(self, level, exp, amount):
        return combat_lib.apply_exp_gain(
            level, exp, amount, self.cfg.role_need_exp,
            self.cfg.role_max_level())

    def test_below_threshold_banks(self):
        self.assertEqual(self.gain(1, 0, 50), (1, 50, 0))

    def test_exact_threshold_spends_to_zero(self):
        # needexp(1) is 100: the rung spends it all for +1 level.
        self.assertEqual(self.gain(1, 0, 100), (2, 0, 1))

    def test_remainder_carries_and_chains_levels(self):
        # 600 covers needexp(1)=100 then needexp(2)=400, leaving 100.
        self.assertEqual(self.gain(1, 0, 600), (3, 100, 2))

    def test_cap_banks_with_no_level_up(self):
        level, total, gained = self.gain(95, 7, 5000)
        self.assertEqual((level, gained), (95, 0))
        self.assertEqual(total, 5007)

    def test_unknown_table_banks_without_leveling(self):
        level, total, gained = combat_lib.apply_exp_gain(
            1, 10, 20, lambda lv: None, 95)
        self.assertEqual((level, total, gained), (1, 30, 0))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class RoleGainExpTest(unittest.TestCase):
    """_role_gain_exp persists, pushes 12001 first, and fans out per level."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=1, exp=0,
            hp=144, max_hp=144, mp=96, max_mp=96)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            save_role_state=self.store.update_character_state,
            get_role_skills=self.store.get_role_skills,
            save_role_skill=self.store.save_role_skill,
            get_task_main=self.store.get_task_main,
            save_task_main=self.store.save_task_main,
            get_role_equip=self.store.get_role_equip,
            get_role_attr_buffs=self.store.get_role_attr_buffs,
            get_role_vip=self.store.get_role_vip,
            get_role_xianjiechenhao=self.store.get_role_xianjiechenhao,
            get_role_meiren=self.store.get_role_meiren,
            get_role_baoshi=self.store.get_role_baoshi,
            get_role_zuoqi=self.store.get_role_zuoqi,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'

    def role(self):
        return self.store.list_roles('hero', 'fu1304')[0]

    def frames(self, out):
        self.assertIsNotNone(out)
        if not isinstance(out, tuple):
            return [decode(out[4:])]
        return [decode(f[4:]) for f in out]

    def gain(self, amount):
        role = self.role()
        total, level, gained, frames = self.sess._role_gain_exp(
            role, str(self.role_id), amount)
        return total, level, gained, [decode(f[4:]) for f in frames]

    def test_no_gain_is_just_the_notice(self):
        total, level, gained, got = self.gain(50)
        self.assertEqual((total, level, gained), (50, 1, 0))
        self.assertEqual(got, [['12001', [50.0, 1]]])
        self.assertEqual(self.role()['exp'], 50)

    def test_level_up_pushes_refreshes_and_persists_max(self):
        total, level, gained, got = self.gain(100)
        self.assertEqual((total, level, gained), (0, 2, 1))
        self.assertEqual(got[0], ['12001', [0.0, 2]])
        cmds = [f[0] for f in got]
        self.assertEqual(cmds[:4], ['12001', '12000', '12004', '12002'])
        wire = str(self.role_id)
        self.assertEqual(got[3], ['12002', [wire, 'Wukong', 2]])
        # No refill: current hp stays, max follows the level-2 row.
        row = self.role()
        self.assertEqual(
            (row['level'], row['exp'], row['hp'], row['max_hp'],
             row['max_mp']),
            (2, 0, 144, 168, 112))
        # pushed 12000 carries the new level-2 base attack.
        from game.attributes import entry_attribute_map  # noqa: E402
        bare2 = entry_attribute_map(self.cfg.role_attribute_row(2))
        self.assertEqual(got[1][1]['2'], bare2['2'])
        self.assertEqual(self.sess.role_attribute_map(row)['2'],
                         bare2['2'])
        # Reconnect sees the persisted level and max values.
        fresh = self.store.list_roles('hero', 'fu1304')[0]
        self.assertEqual(
            (fresh['level'], fresh['exp'], fresh['max_hp'],
             fresh['max_mp']),
            (2, 0, 168, 112))

    def test_multi_level_learns_each_level_skills(self):
        # 3000 covers 100 + 400 + 900 + 1600: level 5 with a zeroed bar.
        total, level, gained, got = self.gain(3000)
        self.assertEqual((total, level, gained), (0, 5, 4))
        notices = [f for f in got if f[0] == str(42004)]
        kinds = sorted(f[1][0] for f in notices)
        self.assertEqual(
            kinds,
            ['jiuweihu1', 'niumowang1', 'sunwukong1',
             'tieshangongzhu1'])
        owned = {s['category']
                 for s in self.store.get_role_skills(str(self.role_id))}
        self.assertTrue(set(kinds) <= owned)
        # A repeat gain learns nothing twice.
        _t, _l, _g, again = self.gain(0)
        self.assertEqual([f for f in again if f[0] == str(42004)], [])

    def test_cap_gain_banks_and_stays_silent(self):
        self.store.update_character_state(
            str(self.role_id), level=95, exp=7)
        total, level, gained, got = self.gain(5000)
        self.assertEqual((total, level, gained), (5007, 95, 0))
        self.assertEqual(got, [['12001', [5007.0, 95]]])

    def test_level_up_unlocks_gated_main_quest(self):
        # Paid c001001 with c001002 gated at recevie_level 2: the gain
        # to level 2 receives the next quest like shengJi does.
        self.store.save_task_main(
            self.role_id, task_uid='t1', task_id='c001001', state=2,
            condition=None, recevie_time=1, create_time=1)
        _t, level, gained, got = self.gain(100)
        self.assertEqual((level, gained), (2, 1))
        cmds = [f[0] for f in got]
        self.assertIn('50004', cmds)
        row = self.store.get_task_main(self.role_id)
        self.assertEqual(row['task_id'], 'c001002')

    def test_derived_stats_feed_combat(self):
        self.gain(100)
        role = self.role()
        live = self.sess._fighter_attrs({'kind': 'role', 'role': role})
        expect = self.sess.role_attribute_map(role)
        self.assertEqual(live['wuli'], expect['2'])
        self.assertEqual(live['fangyu'], expect['3'])
        # Level-2 base attack (56) beats the level-1 value (48).
        self.assertGreater(live['wuli'], 48.0)

    def test_equip_recomputes_and_removal_reverses(self):
        bare = self.sess.role_attribute_map(self.role())['2']
        self.store.save_role_equip(str(self.role_id), [{
            'slot_num': 1, 'goods_id': 'zj0011', 'rare_level': 0,
            'item_level': 0, 'attributes': None}])
        geared = self.sess.role_attribute_map(self.role())['2']
        self.assertGreater(geared, bare)
        live = self.sess._fighter_attrs(
            {'kind': 'role', 'role': self.role()})
        self.assertEqual(live['wuli'], geared)
        self.store.save_role_equip(str(self.role_id), [])
        self.assertEqual(
            self.sess.role_attribute_map(self.role())['2'], bare)


if __name__ == '__main__':
    unittest.main()

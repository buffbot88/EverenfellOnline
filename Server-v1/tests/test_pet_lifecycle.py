"""Commands 136001/136002/136003/136004/136008/136009: pet lifecycle.

Evidence: PetAction @EasyMapping (136001 activatePet, 136002 upgradePet,
136003 petJinJie, 136004 upgradeZhenFa, 136008 chuanChen, 136009
jinJieZhenFa) and PetServiceImpl bytecode (level/goods gates, exp add and
single level-up, pity isSucc/isZhanfaJinJieSucc with the strict zhenfa
ceiling, blessing fail() promoting past maxblessing, the chuanChen
merge/reset, zhenfa level/jinjie, online()/clearCount daily resets, and
replacePetAttribute's PETBAOBAO bag).

The reference config tree does not ship the four ChongWu .jat tables, so
this suite writes small fixture tables (clearly labeled values exercising
the branches, not production numbers) via game.amf3, mirroring
test_marry.py's fixture approach. Item use is covered through the
progression costs (bag goods are consumed); the pet-egg PropType is dead
in this jar build (no userProp switch case news it up, and its useDaoJu
passes a constant empty petId), so acquisition runs through 136001.
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import Obj, decode, encode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402

DAY_MS = 24 * 60 * 60 * 1000


def _biao(pid, jieshu, **over):
    row = {'id': pid, 'jieshu': jieshu, 'maxlv': 5, 'jinjie': 'true',
           'skillid': '', 'fuskillid': '', 'name': 'Pet %s' % pid,
           'nengliangtiem': 0, 'fushentime': 0, 'fushenshuxing': 0,
           'needthingsid': 'g_j1|2', 'shengjieshuxing': 0, 'mintims': 2,
           'maxtimes': 3, 'odds': 0.0, 'addminblessing': 10,
           'addmaxblessing': 10, 'notice': 'true', 'luckyclear': 'true',
           'maxblessing': 25, 'value1': 50, 'value2': 'g_act|1'}
    row.update(over)
    return row


def _shengji(pid, level, **over):
    row = {'id': pid, 'level': level, 'expmin': 0, 'expmax': 0,
           'needexp': 100, 'thingid': 'g_up|1', 'exp': 60,
           'physicdamage': 10, 'shanghai': 1.0}
    row.update(over)
    return row


def make_config(root):
    sys_dir = os.path.join(root, 'sys_config')
    os.makedirs(sys_dir, exist_ok=True)
    tables = {
        'chongwubiao.jat': [
            _biao('petA', 1),
            _biao('petA', 2, maxlv=9, jinjie='false', needthingsid='',
                  mintims=0, maxtimes=0, addminblessing=0,
                  addmaxblessing=0, notice='false', luckyclear='false',
                  maxblessing=0, value1=0, value2=''),
            _biao('petB', 1, jinjie='false', value1=1),
            _biao('petC', 1, jinjie='false', value1=99, value2=''),
        ],
        'chongwushengjibiao.jat': [
            _shengji('petA', 1),
            _shengji('petA', 2, needexp=200, physicdamage=20),
            _shengji('petB', 1, needexp=50, exp=50, physicdamage=7),
            _shengji('petC', 5, needexp=9999, thingid='',
                     physicdamage=99),
        ],
        'chongwutujianbiao.jat': [
            {'id': 'tj1', 'chongwuid': 'petA;petB', 'physicdamage': 5},
        ],
        'chongwuzshouhubiao.jat': [
            {'level': 1, 'thingid': 'g_z|1', 'jinjie': 'false', 'odds': 0.0,
             'exp': 40, 'maxlevel': 10, 'maxtimes': 3, 'needthingsid': 'g_zj|1',
             'notice': 'false', 'needexp': 100, 'mintims': 0,
             'zhenfaxiaoguo': 2.0},
            {'level': 2, 'thingid': 'g_z|1', 'jinjie': 'true', 'odds': 0.0,
             'exp': 10, 'maxlevel': 10, 'maxtimes': 3, 'needthingsid': 'g_zj|1',
             'notice': 'false', 'needexp': 50, 'mintims': 0,
             'zhenfaxiaoguo': 2.0},
        ],
        'ZhuJueShuXingBiao.jat': [
            {'level': 56, 'mana': 96, 'physicdamage': 100,
             'physicdefence': 50, 'critical': 10, 'volt': 7, 'attackrate': 3,
             'velocity': 520, 'dunshudian': 12.7, 'jiangu': 0.25,
             'zhenqi': 100000},
        ],
    }
    for name, rows in tables.items():
        with open(os.path.join(sys_dir, name), 'wb') as f:
            f.write(encode([Obj(**row) for row in rows]))
    return GameConfig(root)


class PetLifecycleBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfgdir = os.path.join(self.tmp.name, 'cfg')
        self.cfg = make_config(self.cfgdir)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56)
        self.sess = self.make_session(self.cfg)

    def make_session(self, cfg):
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_pet=self.store.get_role_pet,
            get_role_pets=self.store.get_role_pets,
            save_role_pet=self.store.save_role_pet,
            get_role_pet_zhenfa=self.store.get_role_pet_zhenfa,
            save_role_pet_zhenfa=self.store.save_role_pet_zhenfa,
            get_role_bag_slots=self.store.get_role_bag_slots,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            config=cfg)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return sess

    def call(self, fn, *args):
        out = fn(*args)
        if out is None:
            return None
        if isinstance(out, (bytes, bytearray)):
            return decode(bytes(out)[4:])
        return [decode(bytes(f)[4:]) for f in out]

    def goods(self, gid):
        return self.sess._task_goods_count(str(self.role_id), gid)

    def seed_goods(self, **counts):
        for i, (gid, count) in enumerate(counts.items()):
            self.store.insert_role_bag_slot(
                self.role_id,
                {'slot_num': i + 1, 'goods_id': gid, 'count': count})

    def seed_pet(self, pid, lv=1, exp=0, rank=1, rank_exp=0, fail=0,
                 update_time=None):
        self.store.save_role_pet(
            self.role_id, pid, pet_lv=lv, pet_lv_exp=exp, pet_rank=rank,
            pet_rank_exp=rank_exp, pet_rank_fail=fail,
            pet_rank_update_time=update_time, create_time=update_time)

    def seed_zhenfa(self, zid='1', exp=0, fail=0, upgrade_count=0,
                    upgrade_time=None, zhenfa_pet='{}', chuzhan=None):
        self.store.save_role_pet_zhenfa(
            self.role_id, zhenfa_id=zid, pet_chuzhan_id=chuzhan,
            upgrade_exp=exp, jinjie_fail_count=fail,
            jinjie_time=upgrade_time, jinjie_data='{}',
            zhenfa_pet=zhenfa_pet, pet_upgrade_count=upgrade_count,
            pet_upgrade_time=upgrade_time)

    def row(self, pid):
        return self.store.get_role_pet(str(self.role_id), pid)

    def zhenfa(self):
        return self.store.get_role_pet_zhenfa(str(self.role_id))


class PetActivateTest(PetLifecycleBase):
    """136001 over fixture chongwubiao rows."""

    def test_activate_success_consumes_cost(self):
        self.seed_goods(g_act=1)
        self.assertEqual(self.call(self.sess.pet_activate,
                                   [136001, 'petA']),
                         ['136001', [1, 'petA']])
        self.assertEqual(self.goods('g_act'), 0)
        row = self.row('petA')
        self.assertEqual((row['pet_lv'], row['pet_rank'],
                          row['pet_lv_exp'], row['pet_rank_exp'],
                          row['pet_rank_fail']), (1, 1, 0, 0, 0))

    def test_activate_duplicate_is_136000(self):
        self.seed_goods(g_act=2)
        self.call(self.sess.pet_activate, [136001, 'petA'])
        self.assertEqual(self.call(self.sess.pet_activate,
                                   [136001, 'petA']),
                         ['136001', [0, 136000]])
        # The duplicate attempt spends nothing.
        self.assertEqual(self.goods('g_act'), 1)

    def test_activate_level_gate_is_1000(self):
        self.assertEqual(self.call(self.sess.pet_activate,
                                   [136001, 'petC']),
                         ['136001', [0, 1000]])

    def test_activate_goods_short_is_1005(self):
        self.assertEqual(self.call(self.sess.pet_activate,
                                   [136001, 'petB']),
                         ['136001', [0, 1005]])

    def test_activate_unknown_pet_is_silent(self):
        self.assertIsNone(self.call(self.sess.pet_activate,
                                    [136001, 'ghost']))

    def test_activate_without_config_is_silent(self):
        bare = self.make_session(None)
        self.assertIsNone(bare.pet_activate([136001, 'petA']))


class PetUpgradeTest(PetLifecycleBase):
    """136002 over fixture shengji rows."""

    def test_upgrade_accumulates_exp(self):
        self.seed_pet('petA')
        self.seed_zhenfa()
        self.seed_goods(g_up=2)
        self.assertEqual(self.call(self.sess.pet_upgrade,
                                   [136002, 'petA']),
                         ['136002', [1, 'petA', 1, 60]])
        self.assertEqual(self.goods('g_up'), 1)

    def test_upgrade_levels_on_overflow_and_marks_zhenfa(self):
        self.seed_pet('petA', exp=60)
        self.seed_zhenfa()
        self.seed_goods(g_up=1)
        self.assertEqual(self.call(self.sess.pet_upgrade,
                                   [136002, 'petA']),
                         ['136002', [1, 'petA', 2, 0]])
        # Java stores petUpgradeCount + 1 into upgradeExp (live: 1).
        self.assertEqual(self.zhenfa()['upgrade_exp'], 1)
        self.assertGreater(self.zhenfa()['pet_upgrade_time'], 0)

    def test_upgrade_capped_is_136001(self):
        self.seed_pet('petA', lv=5)
        self.seed_zhenfa()
        self.seed_goods(g_up=1)
        self.assertEqual(self.call(self.sess.pet_upgrade,
                                   [136002, 'petA']),
                         ['136002', [0, 136001]])
        self.assertEqual(self.goods('g_up'), 1)

    def test_upgrade_goods_short_is_1005(self):
        self.seed_pet('petA')
        self.seed_zhenfa()
        self.assertEqual(self.call(self.sess.pet_upgrade,
                                   [136002, 'petA']),
                         ['136002', [0, 1005]])

    def test_upgrade_unknown_pet_is_silent(self):
        self.assertIsNone(self.call(self.sess.pet_upgrade,
                                    [136002, 'ghost']))

    def test_upgrade_missing_shengji_is_silent(self):
        self.seed_pet('petC')
        self.seed_zhenfa()
        self.seed_goods(g_up=1)
        self.assertIsNone(self.call(self.sess.pet_upgrade,
                                    [136002, 'petC']))


class PetJinjieTest(PetLifecycleBase):
    """136003 pity bands over fixture biao rows."""

    def test_fail_below_pity_accrues_blessing(self):
        self.seed_pet('petA')
        self.seed_goods(g_j1=2)
        self.assertEqual(self.call(self.sess.pet_jinjie,
                                   [136003, 'petA']),
                         ['136003', [-1, 'petA', 1, 10]])
        row = self.row('petA')
        self.assertEqual((row['pet_rank_exp'], row['pet_rank_fail']),
                         (10, 1))

    def test_blessing_overflow_promotes_with_notice(self):
        self.seed_pet('petA', rank_exp=20, fail=2)
        self.seed_goods(g_j1=2)
        self.assertEqual(
            self.call(self.sess.pet_jinjie, [136003, 'petA']),
            [['11101', [136009, ['Wukong', 'Pet petA', 2]]],
             ['136003', [1, 'petA', 2, 0]]])
        row = self.row('petA')
        self.assertEqual((row['pet_rank'], row['pet_rank_exp'],
                          row['pet_rank_fail']), (2, 0, 0))

    def test_max_times_forces_success_despite_zero_odds(self):
        self.seed_pet('petA', fail=3)
        self.seed_goods(g_j1=2)
        got = self.call(self.sess.pet_jinjie, [136003, 'petA'])
        self.assertEqual(got[1], ['136003', [1, 'petA', 2, 0]])

    def test_no_jinjie_rank_is_136002(self):
        self.seed_pet('petB')
        self.seed_goods(g_j1=2)
        self.assertEqual(self.call(self.sess.pet_jinjie,
                                   [136003, 'petB']),
                         ['136003', [0, 136002]])

    def test_goods_short_is_1005(self):
        self.seed_pet('petA')
        self.assertEqual(self.call(self.sess.pet_jinjie,
                                   [136003, 'petA']),
                         ['136003', [0, 1005]])


class PetZhenfaTest(PetLifecycleBase):
    """136004/136009 over fixture shouhu rows."""

    def test_upgrade_accumulates_then_levels(self):
        self.seed_zhenfa()
        self.seed_goods(g_z=3)
        self.assertEqual(self.call(self.sess.pet_zhenfa_upgrade,
                                   [136004, None]),
                         ['136004', [1, '1', 40]])
        self.assertEqual(self.call(self.sess.pet_zhenfa_upgrade,
                                   [136004, None]),
                         ['136004', [1, '1', 80]])
        self.assertEqual(self.call(self.sess.pet_zhenfa_upgrade,
                                   [136004, None]),
                         ['136004', [1, '2', 0]])

    def test_upgrade_jinjie_node_gate_is_136003(self):
        self.seed_zhenfa(zid='2', exp=50)
        self.seed_goods(g_z=1)
        self.assertEqual(self.call(self.sess.pet_zhenfa_upgrade,
                                   [136004, None]),
                         ['136004', [0, 136003]])

    def test_upgrade_maxlevel_is_136011(self):
        root = os.path.join(self.tmp.name, 'cfg2')
        os.makedirs(os.path.join(root, 'sys_config'))
        with open(os.path.join(root, 'sys_config',
                               'chongwuzshouhubiao.jat'), 'wb') as f:
            f.write(encode([Obj(level=1, thingid='g_z|1',
                                 jinjie='false', odds=0.0, exp=40,
                                 maxlevel=1, maxtimes=3, needthingsid='',
                                 notice='false', needexp=100, mintims=0,
                                 zhenfaxiaoguo=2.0)]))
        sess = self.make_session(GameConfig(root))
        self.seed_zhenfa()
        self.seed_goods(g_z=1)
        self.assertEqual(self.call(sess.pet_zhenfa_upgrade,
                                   [136004, None]),
                         ['136004', [0, 136011]])

    def test_upgrade_goods_short_is_1005(self):
        self.seed_zhenfa()
        self.assertEqual(self.call(self.sess.pet_zhenfa_upgrade,
                                   [136004, None]),
                         ['136004', [0, 1005]])

    def test_jinjie_below_gate_is_136004(self):
        self.seed_zhenfa(exp=40)
        self.seed_goods(g_zj=1)
        self.assertEqual(self.call(self.sess.pet_zhenfa_jinjie,
                                   [136009, None]),
                         ['136009', [0, 136004]])

    def test_jinjie_success_past_maxtimes(self):
        self.seed_zhenfa(zid='2', exp=50, fail=6)
        self.seed_goods(g_zj=1)
        self.assertEqual(self.call(self.sess.pet_zhenfa_jinjie,
                                   [136009, None]),
                         ['136009', [1, '3']])
        row = self.zhenfa()
        self.assertEqual((row['zhenfa_id'], row['jinjie_fail_count'],
                          row['jinjie_data']), ('3', 0, '{"3": 1}'))

    def test_jinjie_fail_bumps_count(self):
        self.seed_zhenfa(zid='2', exp=50, fail=0)
        self.seed_goods(g_zj=1)
        self.assertEqual(self.call(self.sess.pet_zhenfa_jinjie,
                                   [136009, None]),
                         ['136009', [-1, '2']])
        self.assertEqual(self.zhenfa()['jinjie_fail_count'], 1)

    def test_jinjie_goods_short_is_1005(self):
        self.seed_zhenfa(zid='2', exp=50)
        self.assertEqual(self.call(self.sess.pet_zhenfa_jinjie,
                                   [136009, None]),
                         ['136009', [0, 1005]])


class PetChuanchenTest(PetLifecycleBase):
    """136008 merge/reset."""

    def test_merge_takes_feed_stats_then_resets_feed(self):
        self.seed_pet('petA', lv=3, exp=10, rank_exp=5)
        self.seed_pet('petB', lv=1, exp=90)
        self.assertEqual(self.call(self.sess.pet_chuanchen,
                                   [136008, ['petA', 'petB']]),
                         ['136008', [1]])
        gain = self.row('petA')
        # 10 + 90 hits needexp 100: lv normalizes to the row level.
        self.assertEqual((gain['pet_lv'], gain['pet_lv_exp'],
                          gain['pet_rank'], gain['pet_rank_exp']),
                         (1, 0, 1, 5))
        feed = self.row('petB')
        self.assertEqual((feed['pet_lv'], feed['pet_lv_exp'],
                          feed['pet_rank'], feed['pet_rank_exp'],
                          feed['pet_rank_fail']), (1, 0, 1, 0, 0))

    def test_gate_when_feed_dominates_is_136007(self):
        self.seed_pet('petA', lv=1)
        self.seed_pet('petB', lv=3)
        self.assertEqual(self.call(self.sess.pet_chuanchen,
                                   [136008, ['petA', 'petB']]),
                         ['136008', [0, 136007]])

    def test_missing_pet_is_136005(self):
        self.seed_pet('petA')
        self.assertEqual(self.call(self.sess.pet_chuanchen,
                                   [136008, ['petA', 'ghost']]),
                         ['136008', [0, 136005]])


class PetEnterTest(PetLifecycleBase):
    """online()/clearCount: seeding, daily resets, restart persistence."""

    def test_first_login_seeds_formation(self):
        self.sess._pet_on_enter(str(self.role_id))
        row = self.zhenfa()
        self.assertEqual((row['zhenfa_id'], row['upgrade_exp'],
                          row['zhenfa_pet'], row['pet_upgrade_count']),
                         ('1', 0, '{}', 0))

    def test_stale_count_resets_but_fresh_keeps(self):
        self.seed_zhenfa(upgrade_count=5,
                         upgrade_time=int(time.time() * 1000) - DAY_MS)
        self.sess._pet_on_enter(str(self.role_id))
        self.assertEqual(self.zhenfa()['pet_upgrade_count'], 0)
        self.seed_zhenfa(upgrade_count=5,
                         upgrade_time=int(time.time() * 1000))
        self.sess._pet_on_enter(str(self.role_id))
        self.assertEqual(self.zhenfa()['pet_upgrade_count'], 5)

    def test_lucky_clear_resets_stale_pity(self):
        stale = int(time.time() * 1000) - DAY_MS
        self.seed_zhenfa()
        self.seed_pet('petA', rank_exp=40, fail=2, update_time=stale)
        self.sess._pet_on_enter(str(self.role_id))
        row = self.row('petA')
        self.assertEqual((row['pet_rank_exp'], row['pet_rank_fail']),
                         (0, 0))

    def test_lucky_clear_keeps_fresh_pity(self):
        self.seed_zhenfa()
        self.seed_pet('petA', rank_exp=40, fail=2,
                      update_time=int(time.time() * 1000))
        self.sess._pet_on_enter(str(self.role_id))
        row = self.row('petA')
        self.assertEqual((row['pet_rank_exp'], row['pet_rank_fail']),
                         (40, 2))

    def test_panel_open_applies_clear_count(self):
        self.seed_zhenfa(upgrade_count=5,
                         upgrade_time=int(time.time() * 1000) - DAY_MS)
        got = self.call(self.sess.pet_info)
        self.assertEqual(got[1][3], 0)
        self.assertEqual(self.zhenfa()['pet_upgrade_count'], 0)

    def test_restart_keeps_state(self):
        self.sess._pet_on_enter(str(self.role_id))
        self.seed_goods(g_act=1, g_up=2)
        self.call(self.sess.pet_activate, [136001, 'petA'])
        self.call(self.sess.pet_upgrade, [136002, 'petA'])
        self.call(self.sess.pet_upgrade, [136002, 'petA'])
        fresh = self.make_session(self.cfg)
        got = self.call(fresh.pet_info)
        self.assertEqual(got[1][0], [['petA', 2, 1, 0, 0]])
        fresh._pet_on_enter(str(self.role_id))
        again = self.call(fresh.pet_info)
        self.assertEqual(again[1][0], [['petA', 2, 1, 0, 0]])


class PetAttributeTest(PetLifecycleBase):
    """replacePetAttribute PETBAOBAO bag into the 12000 map."""

    def role(self):
        return dict(self.store.list_roles('hero', 'fu1304')[0])

    def test_deployed_plus_tujian_bag(self):
        self.seed_pet('petA', lv=2)
        self.seed_pet('petB')
        self.seed_zhenfa(zhenfa_pet='{\"1\": \"petA\"}')
        bag = self.sess._pet_attribute_bag(self.role())
        # 20 (lv2 shengji) * 2.0 (zhenfa factor) + 5 (tj1) = 45.
        self.assertEqual(bag, {'physicdamage': 45.0})
        self.assertEqual(self.sess.role_attribute_map(self.role())['2'],
                         145.0)

    def test_ownership_without_deployment_gives_tujian_only(self):
        self.seed_pet('petA', lv=2)
        self.seed_pet('petB')
        self.seed_zhenfa()
        self.assertEqual(self.sess._pet_attribute_bag(self.role()),
                         {'physicdamage': 5.0})
        self.assertEqual(self.sess.role_attribute_map(self.role())['2'],
                         105.0)

    def test_no_formation_no_bag(self):
        self.seed_pet('petA', lv=2)
        self.seed_pet('petB')
        self.assertEqual(self.sess._pet_attribute_bag(self.role()), {})
        self.assertEqual(self.sess.role_attribute_map(self.role())['2'],
                         100.0)


if __name__ == '__main__':
    unittest.main()

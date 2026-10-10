"""Phase 3 combat loop: bytecode formulas, capture goldens, session wiring.

Oracle: FightServiceImpl.skillFire / SkillProcessHelper.fight+changeOutput /
FightOutputWrapper.skillFire+hpMpChangedOutput+getHarmOutput+getDeadOutput /
ShanghaiResultCalculator+T21/T7/T8/T9 / AiServiceImpl.monsterExpDrop /
RoleExportServiceImpl.incrExp / RoleCalExpExportService.calFightExp, all from
dntg_start.jar via tools/javap.py. Live numbers from
output/orig-stack/tap-decoded.txt (role normal003 -> 1649 / crit 2474 / miss,
monster06 -> 30, zuoqi11 -> 100, +51 exp per D040011 kill at the captured
role's exp-fold bonuses).
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import amf3  # noqa: E402
from game import combat as C  # noqa: E402
from game.amf3 import Obj  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2]
               / 'reference' / 'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config' / 'MapLine.jat').is_file()

# Captured live 12000 map for the tap role (level 56, S> 12000).
ROLE_ATTRS = {'wuli': 2049.800048828125, 'fangyu': 996.7999877929688,
              'baoji': 191.64999389648438, 'shanbi': 196.64999389648438,
              'level': 56, 'max_hp': 5466.0, 'is_role': True,
              'is_monster': False}
# GuaiWuBiao D040011 (map 5 mob): the fields the pipeline reads.
MON_ATTRS = {'wuli': 390.0, 'fangyu': 0.0, 'baoji': 165.0, 'shanbi': 165.0,
             'level': 40, 'max_hp': 3895.0, 'is_role': False,
             'is_monster': True}
NORMAL003 = {'damageformule': 'T21', 'formulea': 0.8, 'formuleb': 10,
             'formulec': '', 'formuleg': 0.75, 'criticalcalculate': 1,
             'voltcalculate': 1}
MONSTER06 = {'damageformule': 'T21', 'formulea': 1, 'formuleb': 10,
             'formulec': '', 'formuleg': 0.75, 'criticalcalculate': 1,
             'voltcalculate': 1}
ZUOQI11 = {'damageformule': 'T21', 'formulea': 0, 'formuleb': 100,
           'formulec': '', 'formuleg': 0.75, 'criticalcalculate': 0,
           'voltcalculate': 0}


class FormulaTest(unittest.TestCase):
    def test_t21_base(self):
        self.assertAlmostEqual(C.t21_base(0.8, 2049.800048828125, 10),
                               1649.8400390625)

    def test_effective_attack_full_defence_kills_it(self):
        self.assertEqual(C.effective_attack(390.0, 996.8, 0, 0, 40, 56), 0.0)

    def test_effective_attack_no_defence_passes_through(self):
        self.assertAlmostEqual(
            C.effective_attack(2049.800048828125, 0, 0, 0, 56, 40),
            2049.800048828125)

    def test_level_floor_applies_when_base_is_lower(self):
        # max(Q, lv*formuleg): the monster's Q=10 floors to 40*0.75=30.
        self.assertEqual(max(10.0, 40 * 0.75), 30.0)
        self.assertEqual(max(1649.8400390625, 56 * 0.75), 1649.8400390625)

    def test_putong_scale_identity_without_formulec(self):
        self.assertEqual(C.putong_scale(1649.84, 0.0, 56), 1649.84)
        self.assertEqual(C.putong_scale(1649.84, '', 56), 1649.84)

    def test_baoji_is_1_5x_with_empty_crit_terms(self):
        self.assertAlmostEqual(C.baoji_value(1649.8400390625), 2474.76005859375)

    def test_harm_type_values_match_clinit(self):
        self.assertEqual((C.HARM_PUTONG, C.HARM_SHANBI, C.HARM_BAOJI), (0, 1, 2))


class CaptureGoldenTest(unittest.TestCase):
    """tap-decoded.txt damage numbers through resolve_hit with forced rolls."""

    def test_role_normal_hit_1649(self):
        val, typ = C.resolve_hit(dict(ROLE_ATTRS), dict(MON_ATTRS),
                                 dict(NORMAL003), force='hit')
        self.assertEqual((val, typ), (1649, C.HARM_PUTONG))

    def test_role_normal_crit_2474(self):
        val, typ = C.resolve_hit(dict(ROLE_ATTRS), dict(MON_ATTRS),
                                 dict(NORMAL003), force='crit')
        self.assertEqual((val, typ), (2474, C.HARM_BAOJI))

    def test_role_miss_is_shanbi_zero(self):
        val, typ = C.resolve_hit(dict(ROLE_ATTRS), dict(MON_ATTRS),
                                 dict(NORMAL003), force='miss')
        self.assertEqual((val, typ), (0, C.HARM_SHANBI))

    def test_monster_hit_floors_to_30(self):
        val, typ = C.resolve_hit(dict(MON_ATTRS), dict(ROLE_ATTRS),
                                 dict(MONSTER06), force='hit')
        self.assertEqual((val, typ), (30, C.HARM_PUTONG))

    def test_pet_hit_is_flat_100(self):
        pet = {'wuli': 0.0, 'fangyu': 0.0, 'baoji': 0.0, 'shanbi': 0.0,
               'level': 30, 'max_hp': 500.0,
               'is_role': False, 'is_monster': False}
        val, typ = C.resolve_hit(pet, dict(MON_ATTRS), dict(ZUOQI11),
                                 force='hit')
        self.assertEqual((val, typ), (100, C.HARM_PUTONG))

    def test_hit_record_and_frames_match_capture_shapes(self):
        self.assertEqual(C.hit_record('m_64_96', 0, 1649, False),
                         ['m_64_96', 0, 1649, 0])
        self.assertEqual(C.hit_record('m_64_96', 0, 1649, True),
                         ['m_64_96', 0, 1649, 1])
        self.assertEqual(
            C.skill_fire_frame('fu0UR1-0-1-1', 'normal003', 0,
                               [['m_64_96', 0, 1649, 0]], None, 1),
            ['42002', ['fu0UR1-0-1-1', 'normal003', 0,
                       [['m_64_96', 0, 1649, 0]], None, 1]])
        self.assertEqual(
            C.dead_notice('m_64_96', 'fu0UR1-0-1-1', 's0.XXX', 'normal003'),
            ['43000', [1, ['m_64_96', 'fu0UR1-0-1-1', 's0.XXX', 0,
                           'normal003']]])
        self.assertEqual(
            C.hp_changed_frame('m_64_96', 2246.0, 3895.0, 3895.0, 3895.0),
            ['12004', ['m_64_96', 2246.0, 3895.0, 3895.0, 3895.0]])
        self.assertEqual(C.buff_flush_frame('m_64_96'),
                         ['42100', ['m_64_96', None, None]])
        self.assertEqual(C.exp_drop_frame('m_64_96', 'D040011', 51),
                         ['12030', ['m_64_96', 'D040011', 51.0]])
        self.assertEqual(C.exp_notice(10692943, 56),
                         ['12001', [10692943.0, 56]])
        self.assertEqual(C.aoi_leave_frame('m_64_96'),
                         ['24002', [['m_64_96']]])

    def test_base_kill_exp_without_bonuses_is_4(self):
        # 400 * 1.0 (harm 100) * 0.01 (gap 16): the capture's 51 needs the
        # role's unmigrated exp-fold buffs, which default to 0 here.
        self.assertEqual(C.base_kill_exp(400, xiuZheng=1.0, levelXishu=0.01), 4)
        self.assertEqual(C.fight_exp_with_bonuses(4), 4)


def write_bytes(directory, rel, data):
    path = os.path.join(directory, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    return path


def synthetic_config(root):
    write_bytes(root, 'sys_config/JiNengBiao.jat', amf3.encode([
        Obj(skilltype='normal003', level=1, damageformule='T21', formulea=0.8,
            formuleb=10, formulec='', formuleg=0.75, criticalcalculate=1,
            voltcalculate=1, cd1='t070'),
        Obj(skilltype='monster06', level=1, damageformule='T21', formulea=1,
            formuleb=10, formulec='', formuleg=0.75, criticalcalculate=1,
            voltcalculate=1, cd1='guaiwucd1')]))
    write_bytes(root, 'sys_config/GuaiWuBiao.jat', amf3.encode([
        Obj(id='T1', name='mob', level=3, hitpoints=100, mana=50, velocity=200,
            physicdamage=20, physicdefence=0, critical=5, volt=5,
            basicexp=400)]))
    write_bytes(root, 'map_config/7/monster.mm', amf3.encode([
        Obj(id='T1', team=0, createPoints=[[1, 2, 0]], createTime=1,
            bossCreateTime=None, maxCount=9, name='mob', monsterType=1)]))
    write_bytes(root, 'sys_config/ZhuJueShuXingBiao.jat', amf3.encode([
        Obj(level=1, mana=60, physicdamage=120, physicdefence=0, critical=9,
            volt=9, attackrate=0, velocity=0, dunshudian=1)]))
    write_bytes(root, 'sys_config/JingYanShuaiJianBiao.jat', amf3.encode([
        Obj(lvdifference=0, subtractfactor=1),
        Obj(lvdifference=3, subtractfactor=0.01)]))
    write_bytes(root, 'sys_config/ShaGuaiXiuZhengBiao.jat', amf3.encode([
        Obj(hurtpercentage=100, solorevise='1.00', rankrevise='1.00')]))
    return GameConfig(root)


class SessionCombatTest(unittest.TestCase):
    """skill_fire wiring: burst order, HP/exp persist, kills, guards."""

    LEVEL = 1

    def build(self):
        from db import Store
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        store = Store(os.path.join(d, 't.db'))
        self.addCleanup(store.close)
        role_id = store.create_character(
            'hero', 'fu1304', 'Wukong', job='A', sex=0, face=1,
            level=self.LEVEL, exp=100, hp=120, mp=60, max_hp=120, max_mp=60)
        cfg_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cfg_dir, ignore_errors=True)
        cfg = synthetic_config(cfg_dir)
        sess = Session(conn_id=7, check_sign=lambda *a: False,
                       get_roles=lambda u, s: store.list_roles(u, s),
                       server_start_ms=0,
                       save_role_state=store.update_character_state,
                       config=cfg)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return sess, store, str(role_id)

    def fire(self, sess, actor, action='normal003', targets=('m_7_0',),
             resolve=(20, 0)):
        with mock.patch.object(C, 'resolve_hit', return_value=resolve):
            return sess.skill_fire(
                [42002, [actor, action, 0, list(targets), None, 1]])

    def test_hit_burst_order_and_role_hp_persist(self):
        sess, store, role_id = self.build()
        out = self.fire(sess, role_id)
        decoded = [amf3.decode(o[4:]) for o in out]
        self.assertEqual([d[0] for d in decoded],
                         ['12004', '42100', '42100', '42002'])
        self.assertEqual(decoded[0],
                         ['12004', ['m_7_0', 80.0, 100.0, 50.0, 50.0]])
        self.assertEqual(decoded[1], ['42100', ['m_7_0', None, None]])
        self.assertEqual(decoded[2], ['42100', [role_id, None, None]])
        self.assertEqual(decoded[3],
                         ['42002', [role_id, 'normal003', 0,
                                    [['m_7_0', 0, 20, 0]], None, 1]])
        role = store.list_roles('hero', 'fu1304')[0]
        self.assertEqual(role['hp'], 120)  # attacker HP untouched

    def test_monster_hit_persists_role_hp(self):
        sess, store, role_id = self.build()
        out = self.fire(sess, 'm_7_0', action='monster06', targets=(role_id,),
                        resolve=(30, 0))
        decoded = [amf3.decode(o[4:]) for o in out]
        self.assertEqual(decoded[0],
                         ['12004', [role_id, 90.0, 120.0, 60.0, 60.0]])
        self.assertEqual(decoded[-1][0], '42002')
        role = store.list_roles('hero', 'fu1304')[0]
        self.assertEqual(role['hp'], 90)

    def test_kill_emits_43000_12001_12030_and_persists_exp(self):
        sess, store, role_id = self.build()
        out = self.fire(sess, role_id, resolve=(100, 0))
        decoded = [amf3.decode(o[4:]) for o in out]
        self.assertEqual([d[0] for d in decoded],
                         ['12004', '42100', '42100', '43000', '42002',
                          '12001', '12030'])
        self.assertEqual(decoded[0], ['12004', ['m_7_0', 0.0, 100.0, 50.0, 50.0]])
        self.assertEqual(decoded[3][1][0], 1)
        self.assertEqual(decoded[3][1][1][:3], ['m_7_0', role_id, 'Wukong'])
        self.assertEqual(decoded[4][1][3], [['m_7_0', 0, 100, 1]])
        # Gap 1-3 = 0 -> decay 1; revise 1.0; 400 base, no bonuses.
        self.assertEqual(decoded[5], ['12001', [500.0, 1]])
        self.assertEqual(decoded[6], ['12030', ['m_7_0', 'T1', 400.0]])
        role = store.list_roles('hero', 'fu1304')[0]
        self.assertEqual(role['exp'], 500)

    def test_miss_sends_no_12004(self):
        sess, _, role_id = self.build()
        out = self.fire(sess, role_id, resolve=(0, 1))
        decoded = [amf3.decode(o[4:]) for o in out]
        self.assertEqual([d[0] for d in decoded], ['42100', '42100', '42002'])
        self.assertEqual(decoded[2][1][3], [['m_7_0', 1, 0, 0]])

    def test_unknown_actor_skill_and_dead_targets_are_ignored(self):
        sess, _, role_id = self.build()
        self.assertIsNone(sess.skill_fire([42002, ['nobody', 'normal003', 0,
                                                   ['m_7_0'], None, 1]]))
        self.assertIsNone(sess.skill_fire([42002, [role_id, 'nope', 0,
                                                   ['m_7_0'], None, 1]]))
        self.assertIsNone(sess.skill_fire([42002, [role_id, 'normal003', 0,
                                                   ['m_9_9'], None, 1]]))
        self.assertIsNone(sess.skill_fire([42002, [[role_id]]]))
        # A corpse takes no further hits.
        self.fire(sess, role_id, resolve=(100, 0))
        with mock.patch.object(C, 'resolve_hit', return_value=(20, 0)) as rh:
            self.assertIsNone(sess.skill_fire(
                [42002, [role_id, 'normal003', 0, ['m_7_0'], None, 1]]))
            rh.assert_not_called()

    def test_aoi_leave_builder(self):
        sess, _, _ = self.build()
        self.assertEqual(amf3.decode(sess.aoi_leave_frame('m_7_0')[4:]),
                         ['24002', [['m_7_0']]])


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class RealConfigCombatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = GameConfig(str(REAL_CONFIG))

    def test_normal003_row_is_t21(self):
        row = self.cfg.skill_row('normal003')
        self.assertEqual(row['damageformule'], 'T21')
        self.assertEqual((row['formulea'], row['formuleb']), (0.8, 10))
        self.assertEqual(row['cd1'], 't070')

    def test_d040011_template_values(self):
        tpl = self.cfg.monster_template('D040011')
        self.assertEqual(tpl['hitpoints'], 3895)
        self.assertEqual(tpl['basicexp'], 400)
        self.assertEqual(tpl['level'], 40)

    def test_exp_tables_hit_captured_values(self):
        self.assertEqual(self.cfg.exp_decay(16), 0.01)
        self.assertEqual(self.cfg.exp_revise(100), 1.0)

    def test_captured_role_vs_d040011_is_1649(self):
        att = dict(ROLE_ATTRS)
        tpl = self.cfg.monster_template('D040011')
        tgt = {'wuli': float(tpl['physicdamage']), 'fangyu': 0.0,
               'baoji': float(tpl['critical']), 'shanbi': float(tpl['volt']),
               'level': 40, 'max_hp': 3895.0,
               'is_role': False, 'is_monster': True}
        val, typ = C.resolve_hit(att, tgt, self.cfg.skill_row('normal003'),
                                 force='hit')
        self.assertEqual((val, typ), (1649, C.HARM_PUTONG))
        val, typ = C.resolve_hit(att, tgt, self.cfg.skill_row('normal003'),
                                 force='crit')
        self.assertEqual((val, typ), (2474, C.HARM_BAOJI))


if __name__ == '__main__':
    unittest.main()

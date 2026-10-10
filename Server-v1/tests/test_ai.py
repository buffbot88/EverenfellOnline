"""Phase 4 monster/pet AI: oracle shapes, capture goldens, session ticks.

Oracle: AiFightServiceImpl.defaultHandle/move/skillExecute/calNextOptDelay,
AiFightOutput.move, FightOutputWrapper.skillReady, Monster.deadHandle +
scheduleDisappearHandle ('AI:RETRIEVE' after disappearDuration seconds),
AiServiceImpl.retrieve/produce, PetFightServiceImpl.skillExecute, all from
dntg_start.jar via tools/javap.py. Live numbers from
output/orig-stack/tap-decoded.txt (monster 42001 readies [1,id,'monster06',
[2640,990],None,1,roleId], 40000 steps [x,y,flag,6,id], pet readies with a
path and null target, pet 40000 kind 2, 24002 ~58 msgs after the 43000 and
23002 re-enters with flag True: m_64_110+).
"""
import math
import os
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import ai as A  # noqa: E402
from game import amf3  # noqa: E402
from game import combat as C  # noqa: E402
from game.amf3 import Obj  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402


class AiShapesTest(unittest.TestCase):
    def test_tile_to_pixel_matches_captured_ready(self):
        self.assertEqual(A.tile_to_pixel([44, 33]), [2640, 990])

    def test_monster_ready_shape(self):
        self.assertEqual(
            A.skill_ready_frame('m_64_96', 'monster06', [2640, 990], None,
                                'fu0UR1-0-1-1'),
            ['42001', [1, 'm_64_96', 'monster06', [2640, 990], None, 1,
                       'fu0UR1-0-1-1']])

    def test_move_flag_zero_at_born_else_one(self):
        self.assertEqual(A.tile_move_frame('m_64_93', [40, 29], True),
                         ['40000', [40, 29, 0, 6, 'm_64_93']])
        self.assertEqual(A.tile_move_frame('m_64_93', [41, 30], False),
                         ['40000', [41, 30, 1, 6, 'm_64_93']])
        self.assertEqual(A.tile_move_frame('zuoqi_64_109', [45, 33], False,
                                           A.MOVE_KIND_PET),
                         ['40000', [45, 33, 1, 2, 'zuoqi_64_109']])

    def test_step_toward_is_a_king_move(self):
        walk = lambda x, y: True  # noqa: E731
        # (2,2) and (2,3) tie at distance 3; the first cell wins.
        self.assertEqual(A.step_toward([1, 2], [5, 5], walk), [2, 2])
        self.assertIsNone(A.step_toward([5, 5], [5, 5], walk))
        self.assertIsNone(A.step_toward([1, 2], [5, 5], lambda x, y: False))

    def test_aggro_uses_eyeshot(self):
        self.assertTrue(A.in_aggro([1, 2], [5, 5], 5))
        self.assertFalse(A.in_aggro([1, 2], [7, 7], 5))

    def test_respawn_record_flags_true(self):
        tpl = {'id': 'T1', 'name': 'mob', 'level': 3, 'hitpoints': 100,
               'mana': 50, 'velocity': 200}
        rec = A.respawn_record('m_7_1', tpl, [1, 2])
        self.assertEqual(rec[:4], ['m_7_1', 'T1', 'mob', 3])
        self.assertEqual(rec[4:10], [100, 100, 50, 50, 200, 200])
        self.assertEqual((rec[11], rec[12], rec[15]), (1, 2, True))


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
            voltcalculate=1, cd1='guaiwucd1'),
        Obj(skilltype='zuoqi11', level=1, damageformule='T21', formulea=0,
            formuleb=100, formulec='', formuleg=0.75, criticalcalculate=0,
            voltcalculate=0, cd1='zuoqicd1')]))
    write_bytes(root, 'sys_config/GuaiWuBiao.jat', amf3.encode([
        Obj(id='T1', name='mob', level=3, hitpoints=100, mana=50, velocity=200,
            physicdamage=20, physicdefence=0, critical=5, volt=5,
            basicexp=400, eyeshot=5, maxrange=9, ifactive=1, asheslast=2,
            creattime=3)]))
    write_bytes(root, 'map_config/7/monster.mm', amf3.encode([
        Obj(id='T1', team=0, createPoints=[[1, 2, 0]], createTime=1,
            bossCreateTime=None, maxCount=9, name='mob', monsterType=1)]))
    write_bytes(root, 'map_config/7/path.mm',
                struct.pack('>ii', 8, 8) + bytes([0x1F] * 64))
    write_bytes(root, 'sys_config/ZhuJueShuXingBiao.jat', amf3.encode([
        Obj(level=1, mana=60, physicdamage=120, physicdefence=0, critical=9,
            volt=9, attackrate=0, velocity=0, dunshudian=1)]))
    write_bytes(root, 'sys_config/JingYanShuaiJianBiao.jat', amf3.encode([
        Obj(lvdifference=0, subtractfactor=1)]))
    write_bytes(root, 'sys_config/ShaGuaiXiuZhengBiao.jat', amf3.encode([
        Obj(hurtpercentage=100, solorevise='1.00', rankrevise='1.00')]))
    return GameConfig(root)


class SessionAiTest(unittest.TestCase):
    def build(self, role_xy=(1, 3)):
        from db import Store
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        store = Store(os.path.join(d, 't.db'))
        self.addCleanup(store.close)
        role_id = store.create_character(
            'hero', 'fu1304', 'Wukong', job='A', sex=0, face=1,
            level=1, exp=100, hp=120, mp=60, max_hp=120, max_mp=60,
            map_id='7', map_x=role_xy[0], map_y=role_xy[1])
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

    def fire(self, sess, actor, targets, resolve):
        with mock.patch.object(C, 'resolve_hit', return_value=resolve):
            return sess.skill_fire(
                [42002, [actor, 'normal003', 0, list(targets), None, 1]])

    def test_hit_plants_hatred_and_tick_retaliates(self):
        sess, _, role_id = self.build()
        self.fire(sess, role_id, ['m_7_0'], (20, 0))
        self.assertEqual(sess._hatred, {'m_7_0': role_id})
        with mock.patch.object(C, 'resolve_hit', return_value=(30, 0)):
            out = sess.ai_tick()
        decoded = [amf3.decode(o[4:]) for o in out]
        self.assertEqual([d[0] for d in decoded],
                         ['42001', '12004', '42100', '42100', '42002'])
        ready = decoded[0][1]
        self.assertEqual(ready[:3], [1, 'm_7_0', 'monster06'])
        self.assertEqual(ready[3], [60, 90])  # role tile (1,3) -> pixel
        self.assertIsNone(ready[4])
        self.assertEqual(ready[6], role_id)
        self.assertEqual(decoded[1], ['12004', [role_id, 90.0, 120.0, 60.0, 60.0]])
        self.assertEqual(decoded[4][1][3], [[role_id, 0, 30, 0]])
        self.assertEqual(decoded[4][1][:3], ['m_7_0', 'monster06', 0])

    def test_distant_monster_chases_one_tile(self):
        sess, _, role_id = self.build(role_xy=(5, 5))
        sess._hatred['m_7_0'] = role_id
        sess._stage_fighter('m_7_0')  # seed the registry
        out = sess.ai_tick()
        decoded = [amf3.decode(o[4:]) for o in out]
        self.assertEqual(decoded, [['40000', [2, 2, 1, 6, 'm_7_0']]])
        self.assertEqual(sess._monster_reg['m_7_0']['pos'], [2, 2])

    def test_presence_aggro_is_silent(self):
        sess, _, role_id = self.build()
        self.assertEqual(sess._hatred, {})
        self.assertIsNone(sess.tile_step([40000, [2, 3, 0, 0, role_id]]))
        self.assertEqual(sess._hatred, {'m_7_0': role_id})

    def test_kill_leave_respawn_cycle(self):
        sess, store, role_id = self.build()
        self.fire(sess, role_id, ['m_7_0'], (100, 0))
        self.assertIn('m_7_0', sess._dead)
        self.assertEqual(sess._leaving, {'m_7_0': 2})
        got = []
        with mock.patch.object(C, 'resolve_hit', return_value=(30, 0)):
            for _ in range(5):
                out = sess.ai_tick()
                if out is not None:
                    got.extend(amf3.decode(o[4:]) for o in out)
        kinds = [g[0] for g in got]
        self.assertEqual(kinds, ['24002', '23002'])
        self.assertEqual(got[0], ['24002', [['m_7_0']]])
        rec = got[1][1][0]
        self.assertEqual(rec[0], 'm_7_1')
        self.assertEqual(rec[1], 'T1')
        self.assertEqual((rec[11], rec[12], rec[15]), (1, 2, True))
        # The re-produced monster fights again.
        self.assertNotIn('m_7_1', sess._dead)
        self.assertIsNotNone(sess._stage_fighter('m_7_1'))
        with mock.patch.object(C, 'resolve_hit', return_value=(20, 0)):
            out = sess.skill_fire(
                [42002, [role_id, 'normal003', 0, ['m_7_1'], None, 1]])
        self.assertTrue(any(amf3.decode(o[4:])[0] == '42002' for o in out))

    def test_pet_auto_fires_with_owner(self):
        sess, _, role_id = self.build()
        sess._pet_state['zuoqi_7_1'] = {
            'max_hp': 500.0, 'hp': 500.0, 'level': 1, 'owner': role_id,
            'owner_name': 'Wukong', 'name': 'mount', 'template_id': 'zuoqi1',
            'pos': [2, 2]}
        with mock.patch.object(C, 'resolve_hit',
                               side_effect=[(20, 0), (10, 0)]):
            out = sess.skill_fire(
                [42002, [role_id, 'normal003', 0, ['m_7_0'], None, 1]])
        decoded = [amf3.decode(o[4:]) for o in out]
        kinds = [d[0] for d in decoded]
        self.assertEqual(kinds[:4], ['12004', '42100', '42100', '42002'])
        self.assertEqual(kinds[4:], ['42001', '12004', '42100', '42100',
                                     '42002'])
        ready = decoded[4][1]
        self.assertEqual(ready[:3], [1, 'zuoqi_7_1', 'zuoqi11'])
        self.assertEqual(ready[3], [120, 60])  # pet tile (2,2) -> pixel
        self.assertEqual(len(ready[4]), 1)  # single straight-line waypoint
        self.assertIsNone(ready[6])
        self.assertEqual(decoded[8][1][:3], ['zuoqi_7_1', 'zuoqi11', 0])

    def test_pet_kill_uses_owner_variant_notice(self):
        sess, _, role_id = self.build()
        sess._pet_state['zuoqi_7_1'] = {
            'max_hp': 500.0, 'hp': 500.0, 'level': 1, 'owner': role_id,
            'owner_name': 'Wukong', 'name': 'mount', 'template_id': 'zuoqi1',
            'pos': [2, 2]}
        with mock.patch.object(C, 'resolve_hit',
                               side_effect=[(20, 0), (90, 0)]):
            out = sess.skill_fire(
                [42002, [role_id, 'normal003', 0, ['m_7_0'], None, 1]])
        decoded = [amf3.decode(o[4:]) for o in out]
        notices = [d for d in decoded if d[0] == '43000']
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0],
                         ['43000', [1, ['m_7_0', role_id, 'Wukong', 0,
                                       'zuoqi11', 'mount']]])

    def test_pet_steps_to_distant_owner(self):
        sess, _, role_id = self.build(role_xy=(6, 6))
        sess._pet_state['zuoqi_7_1'] = {
            'max_hp': 500.0, 'hp': 500.0, 'level': 1, 'owner': role_id,
            'owner_name': 'Wukong', 'name': 'mount', 'template_id': 'zuoqi1',
            'pos': [1, 1]}
        out = sess.ai_tick()
        decoded = [amf3.decode(o[4:]) for o in out]
        self.assertEqual(len(decoded), 1)
        self.assertEqual(decoded[0][0], '40000')
        self.assertEqual(decoded[0][1][3:], [2, 'zuoqi_7_1'])
        self.assertEqual(sess._pet_state['zuoqi_7_1']['pos'], [2, 2])

    def test_quiet_stage_ticks_none(self):
        sess, _, _ = self.build()
        self.assertIsNone(sess.ai_tick())

    def test_handle_appends_retaliation_after_role_fire(self):
        import struct
        from game.protocol import frame as wire_frame
        sess, _, role_id = self.build()
        hello = amf3.encode('INITKEY')
        sess.feed(struct.pack('>I', len(hello)) + hello)
        req = [42002, [role_id, 'normal003', 0, ['m_7_0'], None, 1]]
        with mock.patch.object(C, 'resolve_hit',
                               side_effect=[(20, 0), (30, 0)]):
            out = sess.feed(wire_frame(sess.cipher.encode(amf3.encode(req))))
        kinds = [amf3.decode(o[4:])[0] for o in out]
        self.assertEqual(kinds,
                         ['12004', '42100', '42100', '42002',
                          '42001', '12004', '42100', '42100', '42002'])
        role = sess.get_roles('hero', 'fu1304')[0]
        self.assertEqual(role['hp'], 90)  # monster retaliated live


if __name__ == '__main__':
    unittest.main()

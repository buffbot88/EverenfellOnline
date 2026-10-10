"""Phase 2 goldens: 42100/42102 buff shapes, the 42005 cooldown, 40501.

Bytecode sources (dntg_start.jar): FightOutputWrapper.buffChange /
buffValueChange / stateChangeOutput, Buff/PropBuff.getClientMsg,
BuffStatistics (null-when-empty), FightServiceImpl.skillReadyFire via
StageOutputWrapper.readyAttackSkill, PublicCdManager.toDynamicCd.
Captured values: probe-111111 / tap-decoded entry bursts and combat ticks.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import amf3  # noqa: E402
from game.buffs import (buff_change, buff_value, dynamic_cd, prop_buff,  # noqa: E402
                        timed_buff)


class DynamicCdTest(unittest.TestCase):
    """int(cdTime / (1 + gongJiSuDu/2000)): the captured 42005 value 651."""

    def test_captured_role_cooldown_is_651(self):
        # CdBiao t070 -> 700; the captured role's live attack speed 147.4.
        self.assertEqual(dynamic_cd(700, 147.40000915527344), 651)

    def test_base_only_attack_speed_gives_699(self):
        self.assertEqual(dynamic_cd(700, 1.0), 699)

    def test_truncates_like_java_f2i(self):
        self.assertEqual(dynamic_cd(700, 150.0), 651)
        self.assertEqual(dynamic_cd(700, 0.0), 700)


class TimedBuffTest(unittest.TestCase):
    """Buff.getClientMsg: [id, buffId, remaining, layer, attacker]."""

    def test_permanent_buff_reports_minus_one_double(self):
        entry = timed_buff('buff_64_107', 'vip010', None, 1, 'fu0UR1-0-1-1')
        self.assertEqual(entry,
                         ['buff_64_107', 'vip010', -1.0, 1, 'fu0UR1-0-1-1'])
        self.assertIsInstance(entry[2], float)  # Java Long -> AMF3 double
        self.assertIsInstance(entry[3], int)    # Java Integer -> AMF3 int

    def test_fresh_birthprotect_reports_full_lasttime(self):
        entry = timed_buff('buff_1_2', 'birthprotect', 10000, 1, 'r1')
        self.assertEqual(entry[2], 10000.0)
        self.assertIsInstance(entry[2], float)


class PropBuffTest(unittest.TestCase):
    """PropBuff.getClientMsg: timed shows remaining + flag 0, else value + 1."""

    def test_expfold_shows_remaining_with_timed_flag(self):
        entry = prop_buff('propbuff_64_106', 'expfold_002', 12804944.0, 0,
                          1, 'fu0UR1-0-1-1')
        self.assertEqual(entry, ['propbuff_64_106', 'expfold_002', 12804944.0,
                                 1, 'fu0UR1-0-1-1', 0])

    def test_pool_shows_value_with_value_flag(self):
        entry = prop_buff('propbuff_64_101', 'lanchi_ef', 0, 288103.0,
                          1, 'fu0UR1-0-1-1')
        self.assertEqual(entry, ['propbuff_64_101', 'lanchi_ef', 288103.0,
                                 1, 'fu0UR1-0-1-1', 1])
        self.assertIsInstance(entry[2], float)
        self.assertIsInstance(entry[5], int)


class BuffChangeTest(unittest.TestCase):
    """42100: [fighterId, adds-or-null, removes-or-null]."""

    def test_entry_flush_carries_adds_with_null_removes(self):
        adds = [timed_buff('buff_1_1', 'vip010', None, 1, 'r1')]
        self.assertEqual(buff_change('r1', adds),
                         ['42100', ['r1', adds, None]])

    def test_empty_lists_stay_null_like_java(self):
        self.assertEqual(buff_change('r1'), ['42100', ['r1', None, None]])
        self.assertEqual(buff_change('r1', [], []),
                         ['42100', ['r1', None, None]])

    def test_removal_lists_carry_buff_ids(self):
        env = buff_change('r1', None, ['buff_1_8'])
        self.assertEqual(env, ['42100', ['r1', None, ['buff_1_8']]])


class BuffValueTest(unittest.TestCase):
    """42102: [ownerId, propBuffId, poolValue] (xuechi regen ticks)."""

    def test_pool_tick_shape(self):
        env = buff_value('fu0UR1-0-1-1', 'propbuff_64_102', 328576.0)
        self.assertEqual(env, ['42102', ['fu0UR1-0-1-1', 'propbuff_64_102',
                                         328576.0]])
        self.assertIsInstance(env[1][2], float)


class WireMarkerTest(unittest.TestCase):
    """Durations encode as AMF3 doubles (0x05), layer/flag as ints (0x04)."""

    def test_double_and_int_markers(self):
        self.assertEqual(amf3.encode(-1.0)[:1], b'\x05')
        self.assertEqual(amf3.encode(1)[:1], b'\x04')


if __name__ == '__main__':
    unittest.main()

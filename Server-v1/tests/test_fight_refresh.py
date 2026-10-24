"""Shared ZhanDouLi refresh: change events -> one coalesced 12010 push.

Evidence: `ZhanDouLiModuleInit` registers each producer event against a
`ZDL:*` change command, `ZhanDouLiServiceImpl.changeFight` maps the
command to a bucket and `changeFightValue` ends with
`BusMsgSender.send2BusInner(roleId, "12010")`, which `getRoleFight`
turns into a client push (`BusMsgQueue$ClientMsg.flush` ->
`send2One`). The port therefore marks a per-request flag in the shared
producer helpers and `_fight_refresh_frames` emits the wrapper once,
after the command's own frames and the queued 70520s.

The suite drives real config tables and SQLite through the real
handlers: skill learns/upgrades, level-ups, enhancement, gems, mounts
and direct helper calls, plus the negative paths (failed operations
never refresh) and self-only delivery.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode, encode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session, frame  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2]
               / 'reference' / 'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config' / 'JiNengBiao.jat').is_file()

# Captured client hello (same bytes as the other suites).
INITKEY = bytes.fromhex('00000009060f494e49544b4559')


def decoded(out):
    if out is None:
        return []
    if isinstance(out, (bytes, bytearray)):
        return [decode(bytes(out)[4:])]
    return [decode(bytes(f)[4:]) for f in out]


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class FightRefreshTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.store = Store(os.path.join(tmp, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = str(self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=5, exp=0,
            tongqian=1000000, zhenqi=100000, lingshi=1000000))
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=30)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = self.make_sess()

    def make_sess(self, **over):
        kw = dict(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            save_role_state=self.store.update_character_state,
            get_role_skills=self.store.get_role_skills,
            save_role_skill=self.store.save_role_skill,
            get_role_equip=self.store.get_role_equip,
            save_role_equip=self.store.save_role_equip,
            get_role_zuoqi=self.store.get_role_zuoqi,
            save_role_zuoqi=self.store.save_role_zuoqi,
            get_role_baoshi=self.store.get_role_baoshi,
            save_role_baoshi=self.store.save_role_baoshi,
            get_role_vip=self.store.get_role_vip,
            save_role_vip=self.store.save_role_vip,
            get_role_xianjiechenhao=self.store.get_role_xianjiechenhao,
            get_role_shenjiang=self.store.get_role_shenjiang,
            get_role_attr_buffs=self.store.get_role_attr_buffs,
            get_role_qibing=self.store.get_role_qibing,
            save_role_qibing=self.store.save_role_qibing,
            get_role_pozhen=self.store.get_role_pozhen,
            save_role_pozhen=self.store.save_role_pozhen,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            get_role_bag_slot=self.store.get_role_bag_slot,
            get_role_bag_slot_by_bag_id=self.store.get_role_bag_slot_by_bag_id,
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            config=self.cfg)
        kw.update(over)
        sess = Session(**kw)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return sess

    # -- helpers ---------------------------------------------------------
    def role(self):
        return self.store.list_roles('hero', 'fu1304')[0]

    def wire(self, cmd, data):
        """Send one encrypted command through the real feed path."""
        s = self.sess
        if s.cipher is None:
            s.feed(INITKEY)
        return decoded(s.feed(frame(s.cipher.encode(encode([cmd, data])))))

    def drain(self):
        """Consume the coalesced refresh (direct handler calls skip feed)."""
        return decoded(self.sess._fight_refresh_frames())

    def gear(self, goods='zj0011', qh=0, slot='1'):
        self.store.save_role_equip(
            self.role_id, [{'slot_num': slot, 'goods_id': goods,
                            'rare_level': 1, 'item_level': 1,
                            'attributes': json.dumps(
                                {'fjattrstr': '{}', 'jjfailcount': 0,
                                 'qhcount': qh, 'qhxingxing': '[]'},
                                separators=(',', ':'))}])

    def bag(self, goods, count, slot):
        self.store.save_role_bag_slots(
            self.role_id, [{'slot_num': slot, 'goods_id': goods,
                            'count': count, 'bag_id': f'g{slot}', 'bind': 0,
                            'expire_time': 0, 'rare_level': 0,
                            'item_level': 1, 'attributes': None}])

    # -- mechanism -------------------------------------------------------
    def test_flag_coalesces_to_one_frame(self):
        self.sess._fight_changed()
        self.sess._fight_changed()
        got = self.drain()
        self.assertEqual([f[0] for f in got], ['12010'])
        self.assertEqual(len(got[0][1]), 25)
        # Cleared: a second drain answers nothing.
        self.assertEqual(self.drain(), [])

    def test_no_role_answers_nothing(self):
        sess = self.make_sess(get_roles=lambda u, s: [])
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        sess._fight_changed()
        self.assertEqual(sess._fight_refresh_frames(), [])

    def test_missing_config_answers_nothing(self):
        sess = self.make_sess(config=None)
        sess._fight_changed()
        self.assertEqual(sess._fight_refresh_frames(), [])

    # -- skills ----------------------------------------------------------
    def test_skill_learn_refreshes_skill_bucket_only(self):
        frames = self.sess._skill_level_learn(self.role_id, 5, 'C')
        self.assertEqual([decode(f[4:])[0] for f in frames], ['42004'])
        got = self.drain()
        self.assertEqual([f[0] for f in got], ['12010'])
        body = got[0][1]
        self.assertEqual(
            body[2], self.cfg.skill_fight([{'category': 'niumowang1',
                                            'level': 1}]))
        # A learned skill is not a level-up: no 12000/12002/12004/12005.
        self.assertEqual(
            [f for f in frames if f[4:] and decode(f[4:])[0] != '42004'], [])

    def test_skill_upgrade_wire_pushes_after_reply(self):
        self.store.save_role_skill(self.role_id, 'niumowang1', 1)
        self.assertEqual(len(self.drain()), 0)  # setup writes no flag
        # learnodds 1 for niumowang1 L1, so the first upgrade succeeds.
        got = self.wire(42003, 'niumowang1')
        self.assertEqual([f[0] for f in got], ['42003', '12010'])
        self.assertEqual(got[0][1], [1, 'niumowang1', 2])
        self.assertEqual(
            got[1][1][2],
            self.cfg.skill_fight([{'category': 'niumowang1', 'level': 2}]))
        # Persistence is unchanged by the push.
        rows = self.store.get_role_skills(self.role_id)
        self.assertEqual([(r['category'], r['level']) for r in rows],
                         [('niumowang1', 2)])

    def test_failed_skill_upgrade_does_not_refresh(self):
        got = self.wire(42003, 'nosuchskill')
        self.assertEqual(got, [['42003', [0, 420005]]])
        self.assertEqual(self.drain(), [])

    def test_skill_gate_failure_does_not_refresh(self):
        self.store.save_role_skill(self.role_id, 'niumowang1', 1)
        self.store.update_character_state(self.role_id, zhenqi=0)
        got = self.wire(42003, 'niumowang1')
        self.assertEqual(got, [['42003', [0, 1001]]])
        self.assertEqual(self.drain(), [])

    # -- level -----------------------------------------------------------
    def test_level_up_refreshes_level_bucket(self):
        role = self.role()
        need = self.cfg.role_need_exp(5)
        total, level, gained, frames = self.sess._role_gain_exp(
            role, self.role_id, need)
        self.assertEqual((level, gained), (6, 1))
        codes = [decode(f[4:])[0] for f in frames]
        self.assertIn('12001', codes)
        self.assertIn('12000', codes)
        self.assertIn('12004', codes)
        got = self.drain()
        self.assertEqual([f[0] for f in got], ['12010'])
        self.assertEqual(
            got[0][1][1],
            self.cfg.level_fight(self.cfg.role_attribute_row(6)))
        # The level row swap already persisted: nothing else moved.
        self.assertEqual(self.role()['level'], 6)

    def test_exp_without_level_does_not_refresh(self):
        role = self.role()
        _t, level, gained, _f = self.sess._role_gain_exp(
            role, self.role_id, 10)
        self.assertEqual((level, gained), (5, 0))
        self.assertEqual(self.drain(), [])

    # -- equipment -------------------------------------------------------
    def test_enhance_success_refreshes_equip_bucket(self):
        self.gear()
        self.bag('qianghuashi', 3, 10)
        got = self.sess.equip_qianghua([34000, ['1', 0, 0]])
        self.assertIsNotNone(got)
        refresh = self.drain()
        self.assertEqual([f[0] for f in refresh], ['12010'])
        # The wrapper carries the post-enhance parts (qh moved to 1).
        parts = self.cfg.equip_fight_parts(self.store.get_role_equip(
            self.role_id))
        self.assertEqual(refresh[0][1][0][:3], list(parts))
        self.assertGreater(refresh[0][1][0][1], 0)

    def test_enhance_failure_does_not_refresh(self):
        self.gear()
        got = self.sess.equip_qianghua([34000, ['1', 0, 0]])
        self.assertIsNotNone(got)
        self.assertEqual(self.drain(), [])

    def test_equip_persist_failure_does_not_refresh(self):
        sess = self.make_sess(
            save_role_equip=lambda *a, **k: (_ for _ in ()).throw(ValueError()))
        self.assertEqual(sess._equip_persist_worn(self.role_id, []), None)
        self.assertEqual(sess._fight_refresh_frames(), [])

    # -- gems ------------------------------------------------------------
    def test_baoshi_save_marks_only_on_success(self):
        sess = self.make_sess(save_role_baoshi=lambda *a, **k: False)
        self.assertFalse(sess._baoshi_save(self.role_id, []))
        self.assertEqual(sess._fight_refresh_frames(), [])

    # -- mounts ----------------------------------------------------------
    def test_mount_claim_refreshes_mount_bucket(self):
        self.store.save_role_zuoqi(self.role_id, 0, 0)
        got = self.sess.zuoqi_claim()
        self.assertIsNotNone(got)
        refresh = self.drain()
        self.assertEqual([f[0] for f in refresh], ['12010'])
        self.assertGreater(refresh[0][1][3][0], 0)
        self.assertEqual(self.store.get_role_zuoqi(self.role_id)['zuoqi_rank'],
                         1)

    # -- delivery ---------------------------------------------------------
    def test_refresh_is_self_only(self):
        class Registry:
            def __init__(self):
                self.pushed = []

            def push(self, role_id, frames):
                self.pushed.append((role_id, frames))

            def peers(self, map_id):
                return []

        registry = Registry()
        self.sess.stage_registry = registry
        self.store.save_role_skill(self.role_id, 'niumowang1', 1)
        self.wire(42003, 'niumowang1')
        self.assertEqual(registry.pushed, [])

    def test_one_refresh_per_request(self):
        self.store.save_role_skill(self.role_id, 'niumowang1', 1)
        self.bag('qianghuashi', 3, 10)
        self.gear()
        got = self.wire(42003, 'niumowang1')
        self.assertEqual([f[0] for f in got].count('12010'), 1)
        self.assertEqual(got[-1][0], '12010')


if __name__ == '__main__':
    unittest.main()

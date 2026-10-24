"""Marriage lifecycle (MarryAction 135000/135001/135002/135004/135005/135006).

Evidence: MarryServiceImpl + MarryOnlineHandler/MarryLoginOutHandler +
Hunjie(Config) + Hunjieqianghua(ConfigDetail) + MarryErrorCode javap
(gate order, error codes, push shapes, quartz/intimacy math), and
docs/marry-ledger.md.

Every path runs through the real handlers, the shared StageRegistry
and SQLite: proposals with ring/broadcast gates, two-sided acceptance
with ring consumption and wedding fan-out, divorce cost rules,
spouse teleport, ring strengthening, daily intimacy, login/logout
presence, and encrypted-wire dispatch.

Config note: the legacy tree does not ship hunjiebiao.jat or
hunjieqianghua.jat, so the suite writes small fixture tables (clearly
test values, not Java rows) exercising the genuine loader contract.
"""
import os
import struct
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import Obj, decode, encode  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session, frame  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402

INITKEY = bytes.fromhex('00000009060f494e49544b4559')

HUNJIE = Obj(needlevel=10, time=5, missing_linit=7, maqinmi=60,
              qinmi=10, yuanbao_divorce=99, yuanbao_broadcast=50)
RING_TIERS = [
    Obj(hunjieid='RING1', rideweapon=1, needthingsid='STONE1',
        needthingsvalue=2, cohesion=10, skillcd=60, attribute={}),
    Obj(hunjieid='RING1', rideweapon=2, needthingsid='STONE1',
        needthingsvalue=3, cohesion=20, skillcd=30, attribute={}),
    Obj(hunjieid='RING1', rideweapon=3, needthingsid='STONE1',
        needthingsvalue=4, cohesion=30, skillcd=10, attribute={}),
]


def frames(out):
    if out is None:
        return []
    if isinstance(out, (bytes, bytearray)):
        return [decode(bytes(out)[4:])]
    return [decode(bytes(f)[4:]) for f in out]


def last_cmd(out):
    got = frames(out)
    assert got, 'handler answered nothing'
    return got[-1]


def outbox_frames(sess):
    with sess.outbox_lock:
        pending, sess.outbox = sess.outbox, []
    return [decode(bytes(f)[4:]) for f in pending]


class MarryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cfgdir = os.path.join(tmp.name, 'cfg')
        os.makedirs(os.path.join(cfgdir, 'sys_config'))
        with open(os.path.join(cfgdir, 'sys_config',
                               'hunjiebiao.jat'), 'wb') as f:
            f.write(encode([HUNJIE]))
        with open(os.path.join(cfgdir, 'sys_config',
                               'hunjieqianghua.jat'), 'wb') as f:
            f.write(encode(list(RING_TIERS)))
        cls.cfgdir = cfgdir

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'm.db'))
        self.addCleanup(self.store.close)
        self.cfg = GameConfig(self.cfgdir)
        self.reg = StageRegistry()
        self.seq = 0

    # -- helpers ---------------------------------------------------------
    def session(self, name, level=30, lingshi=500, ring=True):
        self.seq += 1
        acct = f'marryhero{self.seq}'
        self.store.create_account(acct, hash_password('pw'))
        rid = self.store.create_character(
            acct, 'fu1304', name, job='C', level=level, lingshi=lingshi,
            map_id='7', map_x=10, map_y=10)
        self.store.save_role_bag_state(rid, bag_capacity=34,
                                       storage_capacity=30)
        if ring:
            self.store.insert_role_bag_slot(
                rid, {'slot_num': 1, 'bag_id': f'ring-{rid}',
                      'goods_id': 'RING1', 'count': 1, 'bind': 1})
        self.store.insert_role_bag_slot(
            rid, {'slot_num': 2, 'bag_id': f'stone-{rid}',
                  'goods_id': 'STONE1', 'count': 10, 'bind': 0})
        sess = Session(
            conn_id=self.seq, check_sign=lambda *a: False,
            get_roles=lambda u, s, _a=acct: [dict(r) for r in
                                             self.store.list_roles(_a, s)],
            server_start_ms=0,
            save_role_state=self.store.update_character_state,
            get_role_brief=self.store.get_role_brief,
            find_roles_by_name=self.store.find_roles_by_name,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_slot_by_bag_id=(
                self.store.get_role_bag_slot_by_bag_id),
            update_role_bag_slot=self.store.update_role_bag_slot,
            delete_role_bag_slot=self.store.delete_role_bag_slot,
            get_role_online_reward=self.store.get_role_online_reward,
            save_role_online_reward=self.store.save_role_online_reward,
            get_guild_id=self.store.get_guild_id,
            get_guild=self.store.get_guild,
            get_role_marry=self.store.get_role_marry,
            save_role_marry=self.store.save_role_marry,
            marry_tx=self.store.marry_tx,
            marry_spend_yb=self.store.marry_spend_yb,
            count_role_marry=self.store.count_role_marry,
            config=self.cfg, stage_registry=self.reg)
        sess.authed_user, sess.server_id = acct, 'fu1304'
        self.reg.mark_online(str(rid), sess)
        self.reg.register(str(rid), '7', sess, x=10, y=10)
        return str(rid), sess

    def propose(self, sess, name, guid, text='', bc=0):
        return sess.marry_qiuhun(['135001', [name, guid, text, bc]])

    def marry_pair(self, aname='RomeoHero', bname='JulietHero'):
        arid, asess = self.session(aname)
        brid, bsess = self.session(bname)
        outbox_frames(asess)
        outbox_frames(bsess)
        got = last_cmd(self.propose(asess, bname, f'ring-{arid}'))
        self.assertEqual(got, ['135001', [1]])
        got = last_cmd(bsess.marry_accept(
            ['135002', [arid, f'ring-{arid}', 1]]))
        self.assertEqual(got[0], '135003')
        return arid, asess, brid, bsess

    # -- panel -----------------------------------------------------------
    def test_info_silent_when_never_married(self):
        _rid, sess = self.session('SoloHero')
        self.assertIsNone(sess.marry_info())

    def test_info_panel_shape_after_wedding(self):
        arid, asess, brid, bsess = self.marry_pair()
        got = last_cmd(asess.marry_info())
        self.assertEqual(got[0], '135000')
        body = got[1]
        self.assertEqual(len(body), 9)
        self.assertEqual(body[2], brid)
        self.assertEqual(body[3], 'JulietHero')
        self.assertEqual(body[7], 0)
        mine_ring = body[4].get('__assoc__', body[4])
        hers_ring = body[6].get('__assoc__', body[6])
        self.assertEqual(mine_ring['0'], 'RING1')
        self.assertEqual(hers_ring['0'], 'RING1')
        self.assertEqual(mine_ring['4'], brid)
        self.assertEqual(hers_ring['4'], arid)
        self.assertEqual(body[5], 2)
        _ = bsess

    # -- proposals -------------------------------------------------------
    def test_propose_level_gate(self):
        _low, low = self.session('TinyHero', level=5)
        _rid, _sess = self.session('BigHero')
        got = last_cmd(self.propose(low, 'BigHero', 'ring-x'))
        self.assertEqual(got, ['135001', [0, 1000]])

    def test_propose_unknown_target(self):
        _rid, sess = self.session('LonelyHero')
        got = last_cmd(self.propose(sess, 'NobodyHero', 'ring-x'))
        self.assertEqual(got, ['135001', [0, 135003]])

    def test_propose_without_ring(self):
        _rid, sess = self.session('PoorHero', ring=False)
        _t, _ts = self.session('TargetHero')
        got = last_cmd(self.propose(sess, 'TargetHero', 'ring-missing'))
        self.assertEqual(got, ['135001', [0, 135002]])

    def test_propose_offline_target(self):
        arid, asess = self.session('WaitHero')
        brid, bsess = self.session('GoneHero')
        self.reg.mark_offline(brid)
        self.reg.unregister(brid)
        got = last_cmd(self.propose(asess, 'GoneHero', f'ring-{arid}'))
        self.assertEqual(got, ['135001', [0, 135003]])
        _ = bsess

    def test_propose_card_and_pending(self):
        arid, asess = self.session('CardHero')
        brid, bsess = self.session('CardTina')
        got = last_cmd(self.propose(asess, 'CardTina', f'ring-{arid}',
                                    'be mine', 0))
        self.assertEqual(got, ['135001', [1]])
        self.assertEqual(self.store.get_character_lingshi(arid), 500)
        push = outbox_frames(bsess)
        self.assertEqual(push[-1],
                         ['135002', [arid, 'CardHero', None, 30, 'RING1',
                                     'be mine', f'ring-{arid}']])
        self.assertIn(arid, bsess._marry_pending.get(brid, []))

    def test_propose_broadcast_costs_yb(self):
        arid, asess = self.session('CastHero')
        _brid, _bs = self.session('CastTina')
        out = frames(self.propose(asess, 'CastTina', f'ring-{arid}',
                                  'hear ye', 1))
        self.assertIn(['11101', ['hear ye']], out)
        self.assertEqual(out[-1], ['135001', [1]])
        self.assertEqual(self.store.get_character_lingshi(arid), 450)

    def test_propose_broadcast_short_yb(self):
        arid, asess = self.session('BrokeHero', lingshi=10)
        _brid, _bs = self.session('BrokeTina')
        got = last_cmd(self.propose(asess, 'BrokeTina', f'ring-{arid}',
                                    'hear ye', 1))
        self.assertEqual(got, ['135001', [0, 1002]])
        self.assertEqual(self.store.get_character_lingshi(arid), 10)

    def test_propose_into_married_target(self):
        _c, _cs, _d, _ds = self.marry_pair('WedHero', 'WedTina')
        arid, asess = self.session('LateHero')
        got = last_cmd(self.propose(asess, 'WedTina', f'ring-{arid}'))
        self.assertEqual(got, ['135001', [0, 135001]])

    def test_proposer_married_cannot_repropose(self):
        arid, asess, _b, _bs = self.marry_pair()
        _c, _cs = self.session('OtherTina')
        got = last_cmd(self.propose(asess, 'OtherTina', 'ring-x'))
        self.assertEqual(got, ['135001', [0, 135001]])

    # -- answers ---------------------------------------------------------
    def test_decline_notifies_both_sides(self):
        arid, asess = self.session('BlueHero')
        brid, bsess = self.session('BlueTina')
        last_cmd(self.propose(asess, 'BlueTina', f'ring-{arid}'))
        outbox_frames(bsess)
        out = frames(bsess.marry_accept(['135002', [arid, f'ring-{arid}',
                                                    0]]))
        self.assertEqual(out[0], ['135003', [1, arid, 0]])
        push = outbox_frames(asess)
        self.assertEqual(push[-1], ['135003', [1, arid, 0]])
        self.assertIsNone(self.store.get_role_marry(arid))
        self.assertIsNone(self.store.get_role_marry(brid))

    def test_accept_weds_both_and_consumes_ring(self):
        arid, asess, brid, bsess = self.marry_pair()
        mine = self.store.get_role_marry(arid)
        hers = self.store.get_role_marry(brid)
        self.assertEqual(mine['marry_user_role_id'], brid)
        self.assertEqual(hers['marry_user_role_id'], arid)
        self.assertEqual(mine['goods_id'], 'RING1')
        self.assertEqual(mine['item_level'], 1)
        self.assertIsNone(
            self.store.get_role_bag_slot_by_bag_id(arid, f'ring-{arid}'))
        self.assertEqual(
            self.store.get_role_marry(arid)['lihun'], 0)

    def test_accept_fanout_and_wedding_notice(self):
        arid, asess, brid, bsess = self.marry_pair()
        push = outbox_frames(asess)
        kinds = [p[0] for p in push]
        self.assertIn('135000', kinds)
        self.assertIn('135003', kinds)
        self.assertEqual(push[-2], ['135003', [1, arid, 1]])
        info = [p for p in push if p[0] == '135000'][0]
        self.assertEqual(info[1][2], brid)
        own = outbox_frames(bsess)
        self.assertEqual(own[-1], ['11131', ['JulietHero', 'RomeoHero']])

    def test_accept_rejects_other_proposers(self):
        arid, asess = self.session('PickHero')
        brid, bsess = self.session('PickTina')
        crid, csess = self.session('PickCody')
        last_cmd(self.propose(asess, 'PickTina', f'ring-{arid}'))
        last_cmd(self.propose(csess, 'PickTina', f'ring-{crid}'))
        outbox_frames(csess)
        last_cmd(bsess.marry_accept(['135002', [arid, f'ring-{arid}', 1]]))
        push = outbox_frames(csess)
        self.assertEqual(push[-1], ['135003', [1, brid, 0]])

    def test_married_acceptor_rejects(self):
        arid, asess, brid, bsess = self.marry_pair()
        crid, _cs = self.session('ThirdHero')
        last_cmd(self.propose(_cs, 'JulietHero', f'ring-{crid}'))
        got = last_cmd(bsess.marry_accept(
            ['135002', [crid, f'ring-{crid}', 1]]))
        self.assertEqual(got, ['135003', [0, 135001]])
        _ = arid, asess

    # -- divorce ---------------------------------------------------------
    def test_divorce_online_costs_yb_and_frees_both(self):
        arid, asess, brid, bsess = self.marry_pair()
        outbox_frames(bsess)
        out = frames(asess.marry_lihun())
        self.assertEqual(out[-1], ['135004', [1]])
        push = outbox_frames(bsess)
        self.assertEqual(push[-1], ['135004', [1]])
        self.assertEqual(self.store.get_role_marry(arid)['lihun'], 1)
        self.assertEqual(self.store.get_role_marry(brid)['lihun'], 1)
        self.assertEqual(self.store.get_role_marry(arid)['qingmidu'], 0)
        self.assertEqual(self.store.get_character_lingshi(arid), 401)

    def test_divorce_short_yb(self):
        arid, asess, brid, _bs = self.marry_pair()
        self.store.update_character_state(arid, lingshi=10)
        got = last_cmd(asess.marry_lihun())
        self.assertEqual(got, ['135004', [0, 1002]])
        self.assertEqual(self.store.get_role_marry(arid)['lihun'], 0)

    def test_divorce_offline_spouse_is_free(self):
        arid, asess, brid, bsess = self.marry_pair()
        self.reg.mark_offline(brid)
        self.reg.unregister(brid)
        bsess._marry_on_disconnect()
        outbox_frames(bsess)
        got = last_cmd(asess.marry_lihun())
        self.assertEqual(got, ['135004', [1]])
        self.assertEqual(self.store.get_character_lingshi(arid), 500)
        self.assertEqual(self.store.get_role_marry(brid)['lihun'], 1)
        _ = bsess

    def test_divorce_unmarried_errors(self):
        _rid, sess = self.session('FreeHero')
        got = last_cmd(sess.marry_lihun())
        self.assertEqual(got, ['135004', [0, 135004]])

    def test_remarry_after_divorce(self):
        arid, asess, brid, bsess = self.marry_pair()
        last_cmd(asess.marry_lihun())
        self.store.insert_role_bag_slot(
            arid, {'slot_num': 3, 'bag_id': f'ring2-{arid}',
                   'goods_id': 'RING1', 'count': 1, 'bind': 1})
        got = last_cmd(self.propose(asess, 'JulietHero', f'ring2-{arid}'))
        self.assertEqual(got, ['135001', [1]])
        _ = brid, bsess

    # -- teleport --------------------------------------------------------
    def test_chuansong_moves_to_spouse(self):
        arid, asess, brid, bsess = self.marry_pair()
        self.reg.unregister(brid)
        self.reg.register(brid, '8', bsess, x=5, y=6)
        out = frames(asess.marry_chuansong())
        self.assertEqual(out[0], ['20000', [1, '8', [5, 6]]])
        self.assertEqual(self.reg.map_of(arid), '8')
        self.assertGreater(
            self.store.get_role_marry(arid)['chuansong_time'], 0)

    def test_chuansong_cooldown(self):
        arid, asess, brid, bsess = self.marry_pair()
        self.reg.unregister(brid)
        self.reg.register(brid, '8', bsess, x=5, y=6)
        frames(asess.marry_chuansong())
        got = last_cmd(asess.marry_chuansong())
        self.assertEqual(got, ['135005', [0, 135011]])

    def test_chuansong_offline_or_unmarried(self):
        arid, asess, brid, bsess = self.marry_pair()
        self.reg.mark_offline(brid)
        self.reg.unregister(brid)
        got = last_cmd(asess.marry_chuansong())
        self.assertEqual(got, ['135005', [0, 135003]])
        _rid, sess = self.session('SoloFlyHero')
        got = last_cmd(sess.marry_chuansong())
        self.assertEqual(got, ['135005', [0, 135004]])

    # -- strengthening ---------------------------------------------------
    def test_qianghua_climbs_tiers_then_caps(self):
        arid, asess, _b, _bs = self.marry_pair()
        row = self.store.get_role_marry(arid)
        row['qingmidu'] = 25
        self.store.save_role_marry(row)
        got = last_cmd(asess.marry_qianghua())
        self.assertEqual(got, ['135006', [1]])
        self.assertEqual(self.store.get_role_marry(arid)['item_level'], 2)
        row = self.store.get_role_marry(arid)
        row['qingmidu'] = 25
        self.store.save_role_marry(row)
        got = last_cmd(asess.marry_qianghua())
        self.assertEqual(got, ['135006', [1]])
        self.assertEqual(self.store.get_role_marry(arid)['item_level'], 3)
        got = last_cmd(asess.marry_qianghua())
        self.assertEqual(got, ['135006', [0, 135009]])
        stones = self.store.get_role_bag_slot_by_bag_id(arid,
                                                        f'stone-{arid}')
        self.assertEqual(stones['count'], 5)

    def test_qianghua_gates(self):
        arid, asess, _b, _bs = self.marry_pair()
        got = last_cmd(asess.marry_qianghua())
        self.assertEqual(got, ['135006', [0, 135010]])
        row = self.store.get_role_marry(arid)
        row['qingmidu'] = 50
        self.store.save_role_marry(row)
        self.store.delete_role_bag_slot(arid, 2)
        got = last_cmd(asess.marry_qianghua())
        self.assertEqual(got, ['135006', [0, 1005]])
        _rid, sess = self.session('BareHero', ring=False)
        self.store.delete_role_bag_slot(_rid, 2)
        got = last_cmd(sess.marry_qianghua())
        self.assertEqual(got, ['135006', [0, 135004]])

    # -- intimacy schedule -----------------------------------------------
    def test_schedule_accrues_once_logged_pairs(self):
        arid, asess, brid, bsess = self.marry_pair()
        asess._marry_on_enter(arid)
        bsess._marry_on_enter(brid)
        asess._marry_schedule_qingmidu()
        self.assertEqual(self.store.get_role_marry(arid)['qingmidu'], 10)
        self.assertEqual(self.store.get_role_marry(brid)['qingmidu'], 10)
        self.assertEqual(
            self.store.get_role_marry(arid)['day_qingmidu'], 10)

    def test_schedule_respects_daily_cap(self):
        arid, asess, brid, bsess = self.marry_pair()
        row = self.store.get_role_marry(arid)
        row['day_qingmidu'] = 60
        self.store.save_role_marry(row)
        asess._marry_on_enter(arid)
        bsess._marry_on_enter(brid)
        asess._marry_schedule_qingmidu()
        self.assertEqual(self.store.get_role_marry(arid)['qingmidu'], 0)

    def test_login_resets_stale_daily_intimacy(self):
        arid, asess, _b, _bs = self.marry_pair()
        row = self.store.get_role_marry(arid)
        row['day_qingmidu'] = 40
        self.store.save_role_marry(row)
        self.store.save_role_online_reward(
            arid, role_online_time=int(time.time() * 1000) - 90000 * 1000)
        asess._marry_on_enter(arid)
        self.assertEqual(self.store.get_role_marry(arid)['day_qingmidu'],
                         0)

    # -- presence --------------------------------------------------------
    def test_disconnect_drops_pairs_and_pending(self):
        arid, asess, brid, bsess = self.marry_pair()
        asess._marry_on_enter(arid)
        bsess._marry_on_enter(brid)
        self.assertEqual(asess._marry_pairs.get(arid), brid)
        crid, csess = self.session('KnockHero')
        drid, dsess = self.session('KnockTina')
        last_cmd(self.propose(csess, 'KnockTina', f'ring-{crid}'))
        self.assertIn(crid, dsess._marry_pending.get(drid, []))
        self.reg.mark_offline(drid)
        self.reg.unregister(drid)
        dsess._marry_on_disconnect()
        self.assertNotIn(drid, dsess._marry_pending)
        self.reg.mark_offline(brid)
        self.reg.unregister(brid)
        bsess._marry_on_disconnect()
        self.assertNotIn(brid, bsess._marry_pending)
        self.assertNotIn(brid, asess._marry_pairs.values())
        _ = arid

    def test_reconnect_restores_panel(self):
        arid, asess, brid, _bs = self.marry_pair()
        fresh = Session(
            conn_id=999, check_sign=lambda *a: False,
            get_roles=asess.get_roles, server_start_ms=0,
            save_role_state=self.store.update_character_state,
            get_role_brief=self.store.get_role_brief,
            find_roles_by_name=self.store.find_roles_by_name,
            get_role_online_reward=self.store.get_role_online_reward,
            save_role_online_reward=self.store.save_role_online_reward,
            get_role_marry=self.store.get_role_marry,
            save_role_marry=self.store.save_role_marry,
            marry_tx=self.store.marry_tx,
            marry_spend_yb=self.store.marry_spend_yb,
            count_role_marry=self.store.count_role_marry,
            config=self.cfg, stage_registry=self.reg)
        fresh.authed_user, fresh.server_id = asess.authed_user, 'fu1304'
        got = last_cmd(fresh.marry_info())
        self.assertEqual(got[1][2], brid)
        _ = arid

    def test_concurrent_spend_single_winner(self):
        arid, asess = self.session('RaceHero')
        self.store.update_character_state(arid, lingshi=500)
        results = []

        def run():
            results.append(self.store.marry_spend_yb(arid, 400))

        threads = [threading.Thread(target=run) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(self.store.get_character_lingshi(arid), 100)
        _ = asess

    # -- wire ------------------------------------------------------------
    def test_encrypted_dispatch(self):
        arid, asess = self.session('WireHero')
        _brid, _bs = self.session('WireTina')
        asess.feed(INITKEY)
        self.assertIsNotNone(asess.cipher)
        req = asess.cipher.encode(
            encode(['135001', ['WireTina', f'ring-{arid}', '', 0]]))
        out = asess.feed(struct.pack('>I', len(req)) + req)
        self.assertEqual(frames(out)[-1], ['135001', [1]])


if __name__ == '__main__':
    unittest.main()

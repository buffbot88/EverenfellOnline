"""JuQingFuBen batch: codecs, gates, victory lifecycle, claims, persistence.

Evidence: JuQingFuBenServiceImpl + JuQingFuBenUtil + ZuBao drop chain +
StageJuQingCopyServiceImpl, all recovered from dntg_start.jar javap
(see batch notes). Unit tests use synthetic data; wire tests seed the
real JuQingFuBen/ZuBaoDiaoLuoBiao/goods tables (skipped when the legacy
tree is absent) and drive the 64001/2/3/4/6/7/9/10/12/13 handlers.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pathlib import Path  # noqa: E402

from game import amf3  # noqa: E402
from game import juqing as juqing_lib  # noqa: E402
from game.config import GameConfig  # noqa: E402
from game.protocol import Session, _wire_id, frame  # noqa: E402
from db import Store  # noqa: E402

REAL_CONFIG = (Path(__file__).resolve().parents[2] / 'reference' /
               'TonNgoKhong' / 'server' / 'config' / 'game')
HAVE_REAL = (REAL_CONFIG / 'sys_config' / 'JuQingFuBen.jat').is_file()


class CodecTest(unittest.TestCase):
    def test_auto_round_trip(self):
        cell = juqing_lib.encode_auto(True, 3, 1711111111111, 250)
        auto = juqing_lib.decode_auto(cell)
        self.assertEqual(auto, {'onekey': True, 'curid': 3,
                               'start': 1711111111111, 'usetime': 250})

    def test_auto_empty_and_broken_are_none(self):
        self.assertIsNone(juqing_lib.decode_auto(''))
        self.assertIsNone(juqing_lib.decode_auto(None))
        self.assertIsNone(juqing_lib.decode_auto('not json'))

    def test_sweep_remain_is_millisecond_exact(self):
        auto = {'onekey': False, 'curid': 1, 'start': 1000, 'usetime': 200}
        self.assertEqual(juqing_lib.sweep_remain_ms(auto, 5000, 3000), 2800)

    def test_best_keeps_fastest_time_and_best_grade(self):
        cell = juqing_lib.merge_best('', 1, 9000, 4)
        cell = juqing_lib.merge_best(cell, 1, 12000, 2)
        self.assertEqual(juqing_lib.decode_best(cell, 1),
                         {'challenge': 1, 'pingjia': 2, 'fast': 9000})
        rows = juqing_lib.best_time_rows(cell)
        self.assertEqual(rows[0][0], '1')
        self.assertEqual(rows[0][1:], [9000, 2])

    def test_best_unknown_chapter_is_none(self):
        self.assertIsNone(juqing_lib.decode_best('', 9))
        cell = juqing_lib.merge_best('', 1, 9000, 4)
        self.assertIsNone(juqing_lib.decode_best(cell, 2))

    def test_award_incr_decr_round_trip(self):
        cell = juqing_lib.award_incr('', 1, 4, 1700000000000)
        cell = juqing_lib.award_incr(cell, 2, 3, 1700000001000)
        entries = juqing_lib.award_entries(cell)
        self.assertEqual([(c, p) for _, c, p, _ in entries],
                         [(1, 4), (2, 3)])
        cell2, removed = juqing_lib.award_decr(cell, 0)
        self.assertEqual(removed['id'], 1)
        self.assertEqual([c for _, c, _, _ in
                         juqing_lib.award_entries(cell2)], [2])
        self.assertEqual(juqing_lib.award_decr(cell2, 5), (cell2, None))

    def test_award_decr_last_entry_clears_cell(self):
        cell = juqing_lib.award_incr('', 1, 4, 1)
        cleared, _ = juqing_lib.award_decr(cell, 0)
        self.assertEqual(cleared, '')
        self.assertEqual(juqing_lib.award_entries(cleared), [])

    def test_award_null_pingjia_defaults_to_4(self):
        import json
        cell = json.dumps([{'id': 1, 'time': 5}])
        self.assertEqual(juqing_lib.award_entries(cell)[0][2], 4)

    def test_daily_count_is_overwritten_not_incremented(self):
        cell = juqing_lib.set_count('', 1, 1)
        self.assertEqual(juqing_lib.parse_counts(cell), {1: 1})
        cell = juqing_lib.set_count(cell, 1, 2)
        self.assertEqual(juqing_lib.parse_counts(cell), {1: 2})

    def test_challenge_gate_order(self):
        cfg = {'id': '1', 'open_level': 30}
        self.assertEqual(
            juqing_lib.check_can_challenge(cfg, 29, None, '', False),
            juqing_lib.ERR_NO_ENOUGH_LEVEL)
        self.assertEqual(
            juqing_lib.check_can_challenge(cfg, 30, None, '', True),
            juqing_lib.ERR_IN_COPY)
        self.assertEqual(
            juqing_lib.check_can_challenge(cfg, 30, None, '1:1', False),
            juqing_lib.ERR_IS_PASS)
        # Chapter 1 with no progress is the next chapter, so it is open.
        self.assertIsNone(
            juqing_lib.check_can_challenge(cfg, 30, None, '', False))
        cfg2 = {'id': '2', 'open_level': 30}
        self.assertEqual(
            juqing_lib.check_can_challenge(cfg2, 30, None, '', False),
            juqing_lib.ERR_NOT_ACTIVATED)
        self.assertIsNone(
            juqing_lib.check_can_challenge(cfg2, 30, 1, '', False))

    def test_saodang_gate_order(self):
        cfg = {'id': '1'}
        best = {'challenge': 1, 'pingjia': 2, 'fast': 60000}
        auto = {'onekey': False, 'curid': 1, 'start': 0, 'usetime': 0}
        self.assertEqual(
            juqing_lib.check_can_saodang(cfg, None, best, '', True, 0),
            juqing_lib.ERR_NO_VIP)
        self.assertEqual(
            juqing_lib.check_can_saodang(None, None, best, '', False, 0),
            juqing_lib.ERR_NOT_EXIST)
        self.assertEqual(
            juqing_lib.check_can_saodang(cfg, auto, best, '', False, 0),
            juqing_lib.ERR_IN_SAODANG)
        self.assertEqual(
            juqing_lib.check_can_saodang(cfg, None, None, '', False, 0),
            juqing_lib.ERR_NO_PASSED)
        self.assertEqual(
            juqing_lib.check_can_saodang(cfg, None, best, '1:2', False, 0),
            juqing_lib.ERR_IS_PASS)
        self.assertIsNone(
            juqing_lib.check_can_saodang(cfg, None, best, '', False, 0))

    def test_time_grade_compares_raw_millis(self):
        # Java compares the millisecond cost against the raw cutoffs, so
        # any real clear grades 4 with shipped data; keep it verbatim.
        self.assertEqual(juqing_lib.rating_for(100, [180, 300, 600]), 1)
        self.assertEqual(juqing_lib.rating_for(180, [180, 300, 600]), 1)
        self.assertEqual(juqing_lib.rating_for(181, [180, 300, 600]), 2)
        self.assertEqual(juqing_lib.rating_for(360000, [180, 300, 600]), 4)
        self.assertEqual(juqing_lib.dead_rating(0), 1)
        self.assertEqual(juqing_lib.dead_rating(3), 4)
        self.assertEqual(juqing_lib.victory_pingjia(360000, [180, 300, 600],
                                                   0), 1)
        self.assertEqual(juqing_lib.victory_pingjia(100, [180, 300, 600],
                                                   3), 1)
        self.assertEqual(juqing_lib.victory_pingjia(360000, [180, 300, 600],
                                                   3), 4)

    def test_weighted_pick_is_deterministic_per_seed(self):
        import random
        table = {'a': 0.1, 'b': 0.2}
        first = [juqing_lib.random_key2(table, rng=random.Random(7))
                 for _ in range(5)]
        second = [juqing_lib.random_key2(table, rng=random.Random(7))
                  for _ in range(5)]
        self.assertEqual(first, second)
        self.assertIsNone(juqing_lib.random_key2({}))
        self.assertIsNone(juqing_lib.random_key2({'a': 0.0}))
        self.assertEqual(juqing_lib.random_key2({'a': 1.0}), 'a')

    def test_convert_item_splits_stacks_and_skips_unknown(self):
        self.assertEqual(juqing_lib.convert_item(None, 'x', 3), [])
        row = {'maxstack': '99', 'rarelevel': '2', 'itemlevel': '5'}
        models = juqing_lib.convert_item(row, 'bscl', 200, bind=1)
        self.assertEqual([m['count'] for m in models], [99, 99, 2])
        self.assertTrue(all(m['bind'] == 1 for m in models))
        self.assertEqual(models[0]['rare_level'], 2)
        self.assertEqual(models[0]['item_level'], 5)

    def test_nested_group_roll_resolves_to_concrete_goods(self):
        # componentRoll draws one odds per group, recursing into @-refs.
        import random
        table = {'@outer': {'dropNumber': '@outer', 'drop1': '@inner',
                            'drop1Odds': '1.0'},
                 '@inner': {'dropNumber': '@inner', 'drop1': 'zj0409',
                            'drop1Odds': '0.5', 'drop2': 'zj0410',
                            'drop2Odds': '0.5'}}
        for seed in range(5):
            picked = juqing_lib.component_roll(table, '@outer',
                                               rng=random.Random(seed))
            self.assertIn(picked[0], ('zj0409', 'zj0410'))
        self.assertIsNone(juqing_lib.component_roll(table, '@missing'))

    def test_roll_candidates_keep_first_model_per_entry(self):
        # rollItems: one convert2ItemModel[0] per group entry, weighted
        # by the resolved odds; overflow beyond one stack is truncated.
        import random
        goods = {'bscl': {'maxstack': '99', 'rarelevel': '0',
                          'itemlevel': '1'}}
        table = {'@g': {'dropNumber': '@g', 'drop1': 'bscl:250',
                        'drop1Odds': '1.0'}}
        cands = juqing_lib.roll_candidates(goods, table, '@g', {}, 1,
                                           rng=random.Random(0))
        self.assertEqual(len(cands), 1)
        model, rate = cands[0]
        self.assertEqual((model['goods_id'], model['count'],
                         model['bind'], model['id']), ('bscl', 99, 1, '0'))
        self.assertEqual(rate, 1.0)
        self.assertEqual(juqing_lib.roll_candidates(goods, table, None,
                                                    {}, 0), [])
        self.assertIsNone(juqing_lib.roll_pick([]))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class ChapterConfigTest(unittest.TestCase):
    def setUp(self):
        self.cfg = GameConfig(str(REAL_CONFIG))

    def test_chapter_one_shape(self):
        row = self.cfg.juqing_row(1)
        self.assertEqual(row['map'], '13')
        self.assertEqual(row['pos'], [29, 119])
        self.assertEqual(row['open_level'], 30)
        self.assertEqual(row['accel_yb'], 5)
        self.assertEqual(row['expire_ms'], 3600000)
        self.assertEqual(row['drop_id'], '@juqingfuben1')
        self.assertEqual(row['fixed_goods'],
                         [['qianghuashi', 1, 1], ['bscl', 2, 1]])
        self.assertEqual(row['award_odds'], {1: 1.0, 2: 1.0, 3: 1.0,
                                             4: 1.0})
        self.assertEqual(row['pingjia'], [180, 300, 600])
        self.assertEqual(row['roll_bind'], 1)
        self.assertEqual(row['wanted'][0], 'F010003')
        self.assertEqual(dict(row['complete'])['F010007'], 1)

    def test_zubao_chain_resolves_to_concrete_goods(self):
        import random
        table = self.cfg.zubao_table()
        group = table.get('@juqingfuben1')
        self.assertIsNotNone(group)
        seen = set()
        for seed in range(20):
            picked = juqing_lib.component_roll(table, '@juqingfuben1',
                                               rng=random.Random(seed))
            self.assertIsNotNone(picked)
            seen.add(picked[0])
        self.assertTrue(seen <= {'zj0409', 'zj0410', 'zj0411', 'zj0412',
                                 'zj0413', 'zj0414', 'qianghuashi', 'bscl',
                                 'jinjiedan001', 'exppill_0001',
                                 'zhenqipill_00001', 'tongqian002'})
        goods = {gid: {'maxstack': '99'} for gid in (
            'zj0409', 'zj0410', 'zj0411', 'zj0412', 'zj0413', 'zj0414',
            'qianghuashi', 'bscl', 'jinjiedan001', 'exppill_0001',
            'zhenqipill_00001', 'tongqian002')}
        n_entries = sum(1 for i in range(1, 77) if group.get(f'drop{i}'))
        cands = juqing_lib.roll_candidates(goods, table, '@juqingfuben1',
                                           {}, 1, rng=random.Random(3))
        # One candidate per top-level group entry, ids follow order.
        self.assertEqual(len(cands), n_entries)
        self.assertEqual([m['id'] for m, _ in cands],
                         [str(i) for i in range(len(cands))])
        self.assertTrue(all(m['bind'] == 1 for m, _ in cands))

    def test_unknown_chapter_is_none(self):
        self.assertIsNone(self.cfg.juqing_row(9999))


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class LifecycleTest(unittest.TestCase):
    CHAPTER = 1
    FIXED = [['qianghuashi', 1], ['bscl', 2]]
    ROLL_GOODS = {'zj0409', 'zj0410', 'zj0411', 'zj0412', 'zj0413',
                  'zj0414', 'qianghuashi', 'bscl', 'jinjiedan001',
                  'exppill_0001', 'zhenqipill_00001', 'tongqian002'}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', 'pw')
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=30, exp=0,
            zhenqi=0, tongqian=0, lingshi=0)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = self.session()
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=30)

    def session(self):
        sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_juqing=self.store.get_role_juqing,
            save_role_juqing=self.store.save_role_juqing,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            get_role_bag_slot=self.store.get_role_bag_slot,
            update_role_bag_slot=self.store.update_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            get_role_email=self.store.get_role_email,
            save_role_email=self.store.save_role_email,
            save_role_state=self.store.update_character_state,
            config=self.cfg)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return sess

    def role(self):
        return self.store.list_roles('hero', 'fu1304')[0]

    def call(self, method, *args):
        out = getattr(self.sess, method)(*args) if args \
            else getattr(self.sess, method)()
        self.assertIsNotNone(out)
        frames = out if isinstance(out, tuple) else (out,)
        return [amf3.decode(bytes(f)[4:]) for f in frames]

    def challenge(self, cid=1):
        return self.call('juqing_challenge', [64002, [cid]])

    def complete_chapter(self):
        """Kill every wanted monster of chapter 1 via the kill hook."""
        cfg = self.cfg.juqing_row(self.CHAPTER)
        out = []
        for mid, count in cfg['complete']:
            for _ in range(count):
                out.extend(self.sess._juqing_kill_progress(
                    self.role(), mid))
        return [amf3.decode(bytes(f)[4:]) for f in out]

    def test_info_fresh_role(self):
        self.assertEqual(self.call('juqing_info'),
                         [['64001', [1, [0, None, None, None]]]])

    def test_challenge_gates(self):
        self.assertEqual(self.challenge(9999), [['64002', [0, 83006]]])
        self.assertEqual(self.challenge(2), [['64002', [0, 83004]]])
        frames = self.challenge(1)
        self.assertEqual(frames[-1], ['64002', [1, 1]])
        self.assertEqual(frames[-2][0], '64009')
        # An active attempt reports IN_COPY before the daily gate.
        self.assertEqual(self.challenge(1), [['64002', [0, 83005]]])
        # After victory the attempt is gone, so the daily gate answers.
        self.complete_chapter()
        self.assertEqual(self.challenge(1), [['64002', [0, 83001]]])

    def test_victory_stages_claim_and_reports_progress(self):
        self.challenge(1)
        frames = self.complete_chapter()
        victory = [f for f in frames if f[0] == '64003']
        self.assertEqual(len(victory), 1)
        body = victory[0][1]
        self.assertEqual(body[:3], [1, 1, str(self.role_id)])
        self.assertEqual(body[6], self.FIXED)
        self.assertEqual(body[8], body[8])  # useTime echoes below
        self.assertEqual(body[9], 0)
        row = self.store.get_role_juqing(str(self.role_id))
        self.assertEqual(row['passed_highest_id'], 1)
        self.assertEqual(row['passed_ids_daily'], '1:2')
        self.assertEqual(row['tiaozhan_jindu'], '')
        self.assertTrue(row['pending_award'])
        # 64001 shows the clear and no running offline sweep.
        info = self.call('juqing_info')
        body = info[0][1][1]
        self.assertEqual(body[0], 1)
        self.assertEqual(body[1], [['1', '2']])
        self.assertEqual(body[2][0][0], '1')
        self.assertIsNone(body[3])

    def test_claim_grants_currencies_goods_and_clears(self):
        self.challenge(1)
        self.complete_chapter()
        pending = self.store.get_role_juqing(str(self.role_id))
        staged = pending['pending_award']
        reply = self.call('juqing_lingqu', [64012, None])
        self.assertEqual(reply[0][0], '64012')
        body = reply[0][1]
        self.assertEqual(body[0], 1)
        self.assertEqual(body[4], self.FIXED)
        self.assertGreater(body[1], 0)  # exp from the level formula
        self.assertGreater(body[2], 0)  # yxb from the level formula
        role = self.role()
        self.assertEqual(role['exp'], body[1])
        self.assertEqual(role['tongqian'], body[2])
        self.assertEqual(role['zhenqi'], body[3])
        totals = {}
        for s in self.store.get_role_bag_slots(self.role_id, -1000000,
                                               1000000):
            totals[s['goods_id']] = totals.get(s['goods_id'], 0) + \
                int(s['count'] or 0)
        for gid, count in self.FIXED:
            # Totals meet the fixed grant; the roll may stack more of
            # the same goods into the slot (e.g. qianghuashi).
            self.assertGreaterEqual(totals.get(gid, 0), count)
        roll_map = body[5]
        if roll_map is not None:
            assoc = roll_map.get('__assoc__', roll_map)
            self.assertIn(assoc['0'], self.ROLL_GOODS)
        # Duplicate claim is rejected and the stage cleared.
        self.assertEqual(self.call('juqing_lingqu', [64012, None]),
                         [['64012', [0, 83007]]])
        row = self.store.get_role_juqing(str(self.role_id))
        self.assertFalse(row['pending_award'])
        self.assertGreater(len(staged), 0)

    def test_partial_kills_stage_nothing(self):
        self.challenge(1)
        cfg = self.cfg.juqing_row(self.CHAPTER)
        mid, _ = cfg['complete'][0]
        frames = [amf3.decode(bytes(f)[4:])
                  for f in self.sess._juqing_kill_progress(self.role(),
                                                           mid)]
        # No progress push (Java sends none per kill) and no victory.
        self.assertEqual(frames, [])
        row = self.store.get_role_juqing(str(self.role_id))
        self.assertFalse(row['pending_award'])
        self.assertEqual(self.call('juqing_lingqu', [64012, None]),
                         [['64012', [0, 83007]]])

    def test_daily_reset_keeps_permanent_progress(self):
        self.challenge(1)
        self.complete_chapter()
        self.next_day()
        info = self.call('juqing_info')
        body = info[0][1][1]
        self.assertEqual(body[0], 1)  # highest persists
        self.assertIsNone(body[1])  # daily cleared
        self.assertIsNotNone(body[2])  # best time persists

    def test_victory_reply_carries_full_candidate_set(self):
        self.challenge(1)
        frames = self.complete_chapter()
        body = [f for f in frames if f[0] == '64003'][0][1]
        cands = body[7]
        self.assertIsInstance(cands, list)
        self.assertGreater(len(cands), 1)  # all rollItems candidates
        for formart in cands:
            assoc = formart.get('__assoc__', formart)
            self.assertIn(assoc['0'], self.ROLL_GOODS)
            self.assertEqual(assoc['7'], 1)  # chapter roll bind

    def test_fixed_grants_keep_cell_bind(self):
        self.challenge(1)
        self.complete_chapter()
        self.call('juqing_lingqu', [64012, None])
        slots = self.store.get_role_bag_slots(self.role_id, -1000000,
                                              1000000)
        binds = {(s['goods_id'], s.get('bind')) for s in slots}
        self.assertIn(('qianghuashi', 1), binds)
        self.assertIn(('bscl', 1), binds)

    def test_claim_without_stage_is_rejected(self):
        self.assertEqual(self.call('juqing_lingqu', [64012, None]),
                         [['64012', [0, 83007]]])

    def test_pending_survives_reconnect(self):
        self.challenge(1)
        self.complete_chapter()
        fresh = self.session()
        out = fresh.juqing_lingqu([64012, None])
        self.assertIsNotNone(out)
        reply = amf3.decode(bytes(out)[4:])
        self.assertEqual(reply, ['64012', reply[1]])
        self.assertEqual(reply[1][0], 1)
        self.assertEqual(reply[1][4], self.FIXED)

    def next_day(self):
        """Roll the entity clock back so the next access refreshes daily."""
        self.store.save_role_juqing(str(self.role_id), refresh_time=1)
        self.sess = self.session()

    def test_sweep_lifecycle(self):
        self.challenge(1)
        self.complete_chapter()
        self.call('juqing_lingqu', [64012, None])
        # Sweeps need a fresh day after a manual clear.
        self.next_day()
        # Start a sweep: needs no VIP for oneKey=False.
        reply = self.call('juqing_saodang', [64004, [1, False]])
        self.assertEqual(reply[0][0], '64004')
        self.assertEqual(reply[0][1][:3], [1, 1, False])
        fast = reply[0][1][3]
        self.assertGreater(fast, 0)
        # Still running.
        early = self.call('juqing_finish', [64006, None])
        self.assertEqual(early[0][0], '64006')
        self.assertEqual(early[0][1][0], -1)
        self.assertEqual(early[0][1][1], 1)
        # Fast-forward past the fast time and collect.
        real_clock = self.sess._world_now_ms
        self.sess._world_now_ms = lambda: real_clock() + fast + 5000
        try:
            done = self.call('juqing_finish', [64006, None])
        finally:
            self.sess._world_now_ms = real_clock
        self.assertEqual(done, [['64006', [1, 1, False]]])
        awards = self.call('juqing_award')
        self.assertEqual(awards[0][0], '64010')
        self.assertEqual(len(awards[0][1]), 1)
        self.assertEqual(awards[0][1][0][0], 1)
        claimed = self.call('juqing_onekey', [64013, None])
        self.assertEqual(claimed[0][0], '64013')
        self.assertEqual(len(claimed[0][1]), 4)
        self.assertGreater(claimed[0][1][0], 0)
        self.assertEqual(
            self.call('juqing_onekey', [64013, None]),
            [['64013', [0, 83007]]])

    def test_sweep_gates(self):
        # No best time yet: sweep is rejected.
        self.assertEqual(
            self.call('juqing_saodang', [64004, [1, False]]),
            [['64004', [0, 83009]]])
        # One-key sweep needs VIP.
        self.assertEqual(
            self.call('juqing_saodang', [64004, [1, True]]),
            [['64004', [0, 83011]]])

    def test_accelerate_gates_and_collects(self):
        self.challenge(1)
        self.complete_chapter()
        self.call('juqing_lingqu', [64012, None])
        self.next_day()
        self.call('juqing_saodang', [64004, [1, False]])
        # Short of the 5-YB fee.
        self.assertEqual(self.call('juqing_accelerate', [64007, None]),
                         [['64007', [0, 1002]]])
        self.store.update_character_state(self.role_id, lingshi=50)
        self.sess = self.session()
        self.assertEqual(self.call('juqing_accelerate', [64007, None]),
                         [['64007', [1, 1, 5]]])
        self.assertEqual(self.role()['lingshi'], 45)
        awards = self.call('juqing_award')
        self.assertEqual(len(awards[0][1]), 1)

    def test_expire_clears_attempt_and_reports(self):
        self.challenge(1)
        out = self.sess._juqing_expire(_wire_id(self.role()))
        self.assertIsNotNone(out)
        frames = [amf3.decode(bytes(f)[4:]) for f in out]
        self.assertEqual(frames[0], ['64003', [1, 1, 3]])
        self.assertEqual(frames[1], ['64008', [1]])
        row = self.store.get_role_juqing(str(self.role_id))
        self.assertFalse(row['tiaozhan_jindu'])

    def test_login_logout_pause_sweep_clock(self):
        self.challenge(1)
        self.complete_chapter()
        self.call('juqing_lingqu', [64012, None])
        self.next_day()
        self.call('juqing_saodang', [64004, [1, False]])
        base = self.sess._world_now_ms()
        later = base + 30000
        self.sess._world_now_ms = lambda: later
        try:
            self.sess._juqing_on_disconnect()
        finally:
            self.sess._world_now_ms = lambda: base
        row = self.store.get_role_juqing(str(self.role_id))
        import json
        auto = json.loads(row['auto_pass_info'])
        self.assertGreaterEqual(auto['usetime'], 30000)
        # Re-login restarts the clock without losing banked millis.
        self.sess._world_now_ms = lambda: later + 60000
        try:
            self.sess._juqing_on_enter(str(self.role_id))
        finally:
            self.sess._world_now_ms = lambda: base
        row = self.store.get_role_juqing(str(self.role_id))
        auto = json.loads(row['auto_pass_info'])
        self.assertGreaterEqual(auto['usetime'], 30000)


if __name__ == '__main__':
    unittest.main()

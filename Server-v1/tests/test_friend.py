"""Friend / social relationships (FriendAction/FriendServiceImpl bytecode).

Every path runs through the real protocol handlers and the real SQLite
store: one-sided adds with been-add notifies, mutual friendship,
directed deletes, foe kill counters, blacklist guards, mood validation
and login/logout/map presence notifies. Cross-session pushes land in the
peer's outbox, exactly like Java's PublicMsgQueue flush.

Inbound IDs are 51000-51008 plus 51011/51015; 51010/51012-51014 and
51016/51017 are push-only notifies asserted in the peer outboxes.
"""
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode  # noqa: E402
from game.protocol import Session  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402


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


def make_sess(store, registry, user, conn):
    sess = Session(
        conn_id=conn, check_sign=lambda *a: False,
        get_roles=lambda u, s: [dict(r) for r in store.list_roles(u, s)],
        server_start_ms=0,
        save_role_state=store.update_character_state,
        find_roles_by_name=store.find_roles_by_name,
        get_role_brief=store.get_role_brief,
        list_friend_links=store.list_friend_links,
        has_friend_link=store.has_friend_link,
        count_friend_links=store.count_friend_links,
        follower_ids=store.follower_ids,
        friend_add_tx=store.friend_add_tx,
        friend_del_tx=store.friend_del_tx,
        friend_touch_foe_tx=store.friend_touch_foe_tx,
        get_friend_info=store.get_friend_info,
        save_friend_info=store.save_friend_info,
        friend_add_count_tx=store.friend_add_count_tx,
        stage_registry=registry)
    sess.authed_user, sess.server_id = user, 'fu1304'
    return sess


class FriendHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'f.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('a_acct', hash_password('pw'))
        self.store.create_account('b_acct', hash_password('pw'))
        self.alice_id = self.store.create_character(
            'a_acct', 'fu1304', 'AliceHero', job='C', level=10)
        self.bob_id = self.store.create_character(
            'b_acct', 'fu1304', 'BobHero', job='C', level=12)
        self.registry = StageRegistry()
        self.alice = make_sess(self.store, self.registry, 'a_acct', 1)
        self.bob = make_sess(self.store, self.registry, 'b_acct', 2)
        self.registry.mark_online(self.alice_id, self.alice)
        self.registry.mark_online(self.bob_id, self.bob)
        self.registry.register(self.alice_id, 'fu1304', self.alice,
                               x=10, y=10)
        self.registry.register(self.bob_id, 'fu1304', self.bob,
                               x=12, y=12)

    def alice_add_friend(self, target):
        return last_cmd(self.alice.friend_add(['51001', [str(target)]]))

    def bob_add_friend(self, target):
        return last_cmd(self.bob.friend_add(['51001', [str(target)]]))

    def make_named(self, acct, name):
        self.store.create_account(acct, hash_password('pw'))
        return self.store.create_character(
            acct, 'fu1304', name, job='C', level=5)


class FriendInfoTest(FriendHarness):
    def test_empty_info_lists_all_four_categories(self):
        got = last_cmd(self.alice.friend_info())
        self.assertEqual(got[0], '51000')
        self.assertEqual(got[1], [0, None, [], [], [], []])

    def test_info_lists_each_category_after_adds(self):
        self.alice_add_friend(self.bob_id)
        last_cmd(self.alice.foe_add(['51003', [str(self.bob_id)]]))
        last_cmd(self.alice.contacts_add(['51007', [str(self.bob_id)]]))
        got = last_cmd(self.alice.friend_info())
        friends, foes, blacklist, contacts = got[1][2:6]
        self.assertEqual(len(friends), 1)
        self.assertEqual(len(foes), 1)
        self.assertEqual(len(blacklist), 0)
        self.assertEqual(len(contacts), 1)
        # incoming-request counter lands on the target headline.
        self.assertEqual(got[1][0], 0)
        bobs = last_cmd(self.bob.friend_info())
        self.assertEqual(bobs[1][0], 1)
        self.assertEqual(len(bobs[1][2]), 0)  # one-sided until bob adds back

    def test_card_shape_is_thirteen_slots(self):
        self.alice_add_friend(self.bob_id)
        got = last_cmd(self.alice.friend_info())
        card = got[1][2][0]
        self.assertEqual(len(card), 13)
        self.assertEqual(card[0], str(self.bob_id))
        self.assertEqual(card[1], 'BobHero')
        self.assertEqual(card[6], 0)  # FRIEND_TYPE_FRIEND


class FriendAddTest(FriendHarness):
    def test_request_replies_card_and_pushes_count_plus_been_add(self):
        got = self.alice_add_friend(self.bob_id)
        self.assertEqual(got[0], '51001')
        self.assertEqual(got[1][0], 1)
        self.assertEqual(got[1][1][0], str(self.bob_id))
        self.assertTrue(self.store.has_friend_link(
            'friend', self.alice_id, self.bob_id))
        self.assertFalse(self.store.has_friend_link(
            'friend', self.bob_id, self.alice_id))
        pushes = outbox_frames(self.bob)
        self.assertEqual(pushes[0], ['51012', 1])
        self.assertEqual(pushes[1][0], '51016')
        self.assertEqual(pushes[1][1][0], str(self.alice_id))

    def test_accept_back_makes_it_mutual_and_pushes_requester(self):
        self.alice_add_friend(self.bob_id)
        outbox_frames(self.bob)
        got = self.bob_add_friend(self.alice_id)
        self.assertEqual(got[1][0], 1)
        self.assertTrue(self.store.has_friend_link(
            'friend', self.bob_id, self.alice_id))
        pushes = outbox_frames(self.alice)
        self.assertEqual(pushes[0], ['51012', 1])
        self.assertEqual(pushes[1][0], '51016')
        self.assertEqual(pushes[1][1][0], str(self.bob_id))

    def test_duplicate_add_errors(self):
        self.alice_add_friend(self.bob_id)
        got = last_cmd(self.alice.friend_add(['51001',
                                               [str(self.bob_id)]]))
        self.assertEqual(got[1][:2], [0, 450022])
        self.assertEqual(got[1][2], 'BobHero')

    def test_add_self_errors(self):
        got = last_cmd(self.alice.friend_add(['51001',
                                               [str(self.alice_id)]]))
        self.assertEqual(got[1], [0, 450020])

    def test_add_missing_role_errors(self):
        got = last_cmd(self.alice.friend_add(['51001', ['999999']]))
        self.assertEqual(got[1], [0, 450001])

    def test_add_blacklisted_target_errors(self):
        last_cmd(self.alice.blacklist_add(['51005', [str(self.bob_id)]]))
        got = last_cmd(self.alice.friend_add(['51001',
                                               [str(self.bob_id)]]))
        self.assertEqual(got[1][:2], [0, 450023])

    def test_thirty_first_friend_hits_cap(self):
        for i in range(30):
            tid = self.make_named(f'cap{i}', f'CapHero{i:02d}')
            got = self.alice_add_friend(tid)
            self.assertEqual(got[1][0], 1)
        got = self.alice_add_friend(self.bob_id)
        self.assertEqual(got[1][:2], [0, 450021])
        self.assertEqual(got[1][2], 30)

    def test_concurrent_add_only_one_wins(self):
        results = []

        def run():
            try:
                results.append(self.store.friend_add_tx(
                    'friend', self.alice_id, self.bob_id, 30))
            except Exception as exc:  # pragma: no cover - lock owner wins
                results.append(exc)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wins = [r for r in results if r == (True, None)]
        self.assertEqual(len(wins), 1)


class FriendDeleteTest(FriendHarness):
    def test_delete_is_directed_and_replies_target(self):
        self.alice_add_friend(self.bob_id)
        self.bob_add_friend(self.alice_id)
        got = last_cmd(self.alice.friend_del(['51002',
                                               [str(self.bob_id)]]))
        self.assertEqual(got, ['51002', [1, str(self.bob_id)]])
        self.assertFalse(self.store.has_friend_link(
            'friend', self.alice_id, self.bob_id))
        # directed rows: the reverse side survives its own delete.
        self.assertTrue(self.store.has_friend_link(
            'friend', self.bob_id, self.alice_id))

    def test_delete_missing_link_is_silent(self):
        self.assertIsNone(self.alice.friend_del(['51002',
                                                  [str(self.bob_id)]]))

    def test_reconnect_keeps_accepted_links(self):
        self.alice_add_friend(self.bob_id)
        self.bob_add_friend(self.alice_id)
        fresh = make_sess(self.store, StageRegistry(), 'a_acct', 9)
        got = last_cmd(fresh.friend_info())
        self.assertEqual(len(got[1][2]), 1)


class FoeTest(FriendHarness):
    def test_foe_add_replies_card_and_pushes_been_add(self):
        got = last_cmd(self.alice.foe_add(['51003', [str(self.bob_id)]]))
        self.assertEqual(got[0], '51003')
        self.assertEqual(got[1][0], 1)
        self.assertEqual(got[1][1][0], str(self.bob_id))
        pushes = outbox_frames(self.bob)
        self.assertEqual(pushes[-1][0], '51017')
        self.assertEqual(pushes[-1][1][0], str(self.alice_id))

    def test_foe_add_self_missing_dup(self):
        self.assertEqual(last_cmd(
            self.alice.foe_add(['51003', [str(self.alice_id)]]))[1],
            [0, 450040])
        self.assertEqual(last_cmd(
            self.alice.foe_add(['51003', ['999999']]))[1],
            [0, 450001])
        last_cmd(self.alice.foe_add(['51003', [str(self.bob_id)]]))
        got = last_cmd(self.alice.foe_add(['51003', [str(self.bob_id)]]))
        self.assertEqual(got[1][:2], [0, 450042])

    def test_foe_fight_counts_winner_and_loser(self):
        last_cmd(self.alice.foe_add(['51003', [str(self.bob_id)]]))
        last_cmd(self.bob.foe_add(['51003', [str(self.alice_id)]]))
        outbox_frames(self.alice)
        outbox_frames(self.bob)
        out = self.alice.friend_fight(
            ['51015', [str(self.bob_id), str(self.alice_id), 'fu1304']])
        got = frames(out)
        self.assertEqual(got[0][0], '51013')
        self.assertEqual(got[0][1], [str(self.bob_id), 1, 1])
        info = last_cmd(self.alice.friend_info())
        self.assertEqual(info[1][3][0][10], 1)  # winner foe_count
        binfo = last_cmd(self.bob.friend_info())
        self.assertEqual(binfo[1][3][0][10], -1)  # loser decremented
        loser_pushes = outbox_frames(self.bob)
        self.assertEqual(loser_pushes[0],
                         ['51013', [str(self.alice_id), -1, -1]])

    def test_foe_fight_auto_adds_loser_side(self):
        last_cmd(self.alice.foe_add(['51003', [str(self.bob_id)]]))
        self.alice.friend_fight(
            ['51015', [str(self.bob_id), str(self.alice_id), 'fu1304']])
        self.assertTrue(self.store.has_friend_link(
            'foe', self.bob_id, self.alice_id))
        pushes = outbox_frames(self.bob)
        kinds = [p[0] for p in pushes]
        self.assertIn('51003', kinds)  # auto-add card on the loser side

    def test_foe_del_roundtrip(self):
        last_cmd(self.alice.foe_add(['51003', [str(self.bob_id)]]))
        got = last_cmd(self.alice.foe_del(['51004', [str(self.bob_id)]]))
        self.assertEqual(got, ['51004', [1, str(self.bob_id)]])
        self.assertFalse(self.store.has_friend_link(
            'foe', self.alice_id, self.bob_id))


class BlacklistContactsTest(FriendHarness):
    def test_blacklist_add_del_roundtrip(self):
        got = last_cmd(self.alice.blacklist_add(['51005',
                                                  [str(self.bob_id)]]))
        self.assertEqual(got[0], '51005')
        self.assertEqual(got[1][0], 1)
        self.assertEqual(got[1][1][0], str(self.bob_id))
        out = last_cmd(self.alice.blacklist_del(['51006',
                                                  [str(self.bob_id)]]))
        self.assertEqual(out, ['51006', [1, str(self.bob_id)]])
        self.assertFalse(self.store.has_friend_link(
            'blacklist', self.alice_id, self.bob_id))

    def test_blacklist_self_dup_and_friend_conflict(self):
        self.assertEqual(last_cmd(
            self.alice.blacklist_add(['51005',
                                      [str(self.alice_id)]]))[1],
            [0, 450060])
        last_cmd(self.alice.blacklist_add(['51005', [str(self.bob_id)]]))
        got = last_cmd(self.alice.blacklist_add(['51005',
                                                  [str(self.bob_id)]]))
        self.assertEqual(got[1][:2], [0, 450062])
        last_cmd(self.alice.blacklist_del(['51006', [str(self.bob_id)]]))
        self.alice_add_friend(self.bob_id)
        got = last_cmd(self.alice.blacklist_add(['51005',
                                                  [str(self.bob_id)]]))
        self.assertEqual(got[1][:2], [0, 450063])

    def test_contacts_add_del_roundtrip(self):
        got = last_cmd(self.alice.contacts_add(['51007',
                                                 [str(self.bob_id)]]))
        self.assertEqual(got[0], '51007')
        self.assertEqual(got[1][0], str(self.bob_id))  # bare card
        out = last_cmd(self.alice.contacts_del(['51008',
                                                 [str(self.bob_id)]]))
        self.assertEqual(out, ['51008', [1, str(self.bob_id)]])
        self.assertFalse(self.store.has_friend_link(
            'contacts', self.alice_id, self.bob_id))

    def test_contacts_dup_self_missing_are_silent(self):
        last_cmd(self.alice.contacts_add(['51007', [str(self.bob_id)]]))
        self.assertIsNone(self.alice.contacts_add(['51007',
                                                    [str(self.bob_id)]]))
        self.assertIsNone(self.alice.contacts_add(['51007',
                                                    [str(self.alice_id)]]))
        self.assertIsNone(self.alice.contacts_add(['51007', ['999999']]))

    def test_contacts_evict_oldest_past_cap(self):
        first = self.make_named('ev0', 'EvHero00')
        last_cmd(self.alice.contacts_add(['51007', [str(first)]]))
        for i in range(1, 30):
            last_cmd(self.alice.contacts_add(
                ['51007', [str(self.make_named(f'ev{i}',
                                                f'EvHero{i:02d}'))]]))
        extra = self.make_named('evX', 'EvHeroXX')
        out = self.alice.contacts_add(['51007', [str(extra)]])
        got = frames(out)
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0][0], '51007')
        self.assertEqual(got[1], ['51008', [1, str(first)]])
        self.assertFalse(self.store.has_friend_link(
            'contacts', self.alice_id, first))


class MoodPresenceTest(FriendHarness):
    def test_mood_update_persists_and_replies(self):
        got = last_cmd(self.alice.friend_xinqing(['51011', '努力修炼']))
        self.assertEqual(got, ['51011', [1, '努力修炼']])
        self.assertEqual(self.store.get_friend_info(
            self.alice_id)['xinqing'], '努力修炼')
        got = last_cmd(self.alice.friend_info())
        self.assertEqual(got[1][1], '努力修炼')

    def test_mood_same_text_is_idempotent(self):
        last_cmd(self.alice.friend_xinqing(['51011', '努力修炼']))
        got = last_cmd(self.alice.friend_xinqing(['51011', '努力修炼']))
        self.assertEqual(got, ['51011', [1, '努力修炼']])

    def test_mood_too_long_errors_with_old_text(self):
        last_cmd(self.alice.friend_xinqing(['51011', '努力修炼']))
        got = last_cmd(self.alice.friend_xinqing(['51011', 'x' * 65]))
        self.assertEqual(got[1], [0, 450030, '努力修炼'])

    def test_mood_illegal_chars_error(self):
        got = last_cmd(self.alice.friend_xinqing(['51011',
                                                   'hello world']))
        self.assertEqual(got[1][:2], [0, 450031])

    def test_login_logout_notify_followers(self):
        self.alice_add_friend(self.bob_id)
        self.bob_add_friend(self.alice_id)
        outbox_frames(self.bob)
        self.alice._friend_on_enter(str(self.alice_id))
        self.assertEqual(outbox_frames(self.bob)[-1],
                         ['51010', [str(self.alice_id), 1]])
        self.alice._friend_on_disconnect()
        self.assertEqual(outbox_frames(self.bob)[-1],
                         ['51010', [str(self.alice_id), 0]])

    def test_map_change_notifies_followers(self):
        self.alice_add_friend(self.bob_id)
        self.bob_add_friend(self.alice_id)
        outbox_frames(self.bob)
        self.alice._friend_on_map(str(self.alice_id), 'fu1304')
        pushes = outbox_frames(self.bob)
        self.assertEqual(pushes[-1][0], '51014')
        self.assertEqual(pushes[-1][1], [str(self.alice_id), -1,
                                         'fu1304', None])


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
"""Replay any captured client sequence through the Python game Session.

Generalizes tools/world_entry_replay.py beyond world entry: feeds every C>
message in tap order (optionally filtered) and diffs each S> reply per
command, pairwise in order. Usage from the repo root:
  python3 tools/session_replay.py [--tap PATH] [--cmds 42002,42001] [--limit 50]
"""
import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Server-v1'))

from auth import check_sign  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode, encode  # noqa: E402
from game.cipher import SimpleEncrypt  # noqa: E402
from game.config import DEFAULT_CONFIG_DIR, GameConfig  # noqa: E402
from game.protocol import Session, frame  # noqa: E402
from world_entry_replay import (VOLATILE, diff, first, read_raw_frames,  # noqa: E402
                                read_tap, seed_store, substitute)

MAX_DIFFS_SHOWN = 6


def make_full_session(store):
    """Session wired like server.py GameTCPHandler, with all store callbacks."""
    return Session(
        conn_id=1,
        check_sign=check_sign,
        get_roles=lambda u, s: [dict(r) for r in store.list_roles(u, s)],
        server_start_ms=int(time.time() * 1000),
        get_role_settings=store.get_role_settings,
        create_role=lambda acct, sid, name, job, sex, face: store.create_character(
            acct, sid, name, job=job, sex=sex, face=face),
        save_role_state=store.update_character_state,
        get_role_equip=store.get_role_equip,
        get_role_attr_buffs=store.get_role_attr_buffs,
        get_role_vip=store.get_role_vip,
        get_role_xianjiechenhao=store.get_role_xianjiechenhao,
        get_role_meiren=store.get_role_meiren,
        get_role_zuoqi=store.get_role_zuoqi,
        get_role_skills=store.get_role_skills,
        get_role_shenjiang=store.get_role_shenjiang,
        save_role_stage=store.save_role_stage,
        get_role_bag_slots=store.get_role_bag_slots,
        get_role_bag_state=store.get_role_bag_state,
        get_role_bag_slot=store.get_role_bag_slot,
        get_role_bag_slot_by_bag_id=store.get_role_bag_slot_by_bag_id,
        update_role_bag_slot=store.update_role_bag_slot,
        delete_role_bag_slot=store.delete_role_bag_slot,
        move_role_bag_slot=store.move_role_bag_slot,
        insert_role_bag_slot=store.insert_role_bag_slot,
        rewrite_role_bag_slots=store.rewrite_role_bag_slots,
        save_role_bag_state=store.save_role_bag_state,
        get_task_main=store.get_task_main,
        save_task_main=store.save_task_main,
        config=GameConfig(os.path.normpath(str(ROOT / 'Server-v1' / DEFAULT_CONFIG_DIR))))


def seed_best_effort(store, tap):
    """Seed from the capture when it has world-entry replies, else an empty store."""
    try:
        return seed_store(store, tap)
    except SystemExit:
        return None, None, None


def client_sequence(tap, cmds=None, skip_truncated=True, limit=None):
    """Every C> message in tap order, each as [cmd, *args]."""
    picked = [m for m in tap if m['dir'] == 'C'
              and (cmds is None or m['cmd'] in cmds)
              and (not skip_truncated or m['args'] is not None)]
    if limit is not None:
        picked = picked[:limit]
    return [[m['cmd'], *m['args']] for m in picked]


def replay_window(tap, cmds=None, limit=None):
    """Client messages plus the tap line they end at, for scoping the Java side."""
    picked = [m for m in tap if m['dir'] == 'C'
              and (cmds is None or m['cmd'] in cmds)
              and m['args'] is not None]
    if limit is not None:
        picked = picked[:limit]
    last_line = picked[-1]['line'] if picked else 0
    return [[m['cmd'], *m['args']] for m in picked], last_line


def group_by_cmd(replies):
    """Command id -> list of arg-lists, in arrival order."""
    grouped = {}
    for r in replies:
        grouped.setdefault(int(r[0]), []).append(r[1:])
    return grouped


def compare_sequences(java_msgs, py_replies, volatile=None, max_diffs=MAX_DIFFS_SHOWN):
    """Pairwise per-command diff of java S> payloads vs python replies."""
    volatile = volatile or {}
    java_by_cmd = {}
    for m in java_msgs:
        if m['dir'] == 'S' and not m.get('truncated'):
            java_by_cmd.setdefault(m['cmd'], []).append(m['args'])
    py_by_cmd = group_by_cmd(py_replies)
    result = {}
    for cmd in sorted(set(java_by_cmd) | set(py_by_cmd)):
        vols = volatile.get(cmd, ())
        pairs = min(len(java_by_cmd.get(cmd, [])), len(py_by_cmd.get(cmd, [])))
        diffs = []
        for i in range(pairs):
            for d in diff(java_by_cmd[cmd][i], py_by_cmd[cmd][i]):
                if not d.startswith(vols):
                    diffs.append(f'[{i}]{d}')
        result[cmd] = {'match': sum(1 for i in range(pairs)
                                    if not [d for d in diffs if d.startswith(f'[{i}]')]),
                       'diff': len({d.split(']')[0] for d in diffs}),
                       'missing': max(len(java_by_cmd.get(cmd, [])) - len(py_by_cmd.get(cmd, [])), 0),
                       'extra': max(len(py_by_cmd.get(cmd, [])) - len(java_by_cmd.get(cmd, [])), 0),
                       'details': diffs[:max_diffs]}
    return result


def replay_all(tap, fix_role_id=True, cmds=None, limit=None):
    """Feed the tap's client messages through a fresh session; return the run."""
    tmp = tempfile.mkdtemp()
    store = Store(os.path.join(tmp, 'replay.db'))
    try:
        seed_best_effort(store, tap)
        try:
            legacy_id = first(tap, 'S', 10001)['args'][0][3][0][0]
        except SystemExit:
            legacy_id = None
        sess = make_full_session(store)
        key = sess.feed(frame(encode('INITKEY')))[0][4:].decode()
        cipher = SimpleEncrypt(key)
        replies, sent = [], []
        py_role_id = None
        msgs, last_line = replay_window(tap, cmds=cmds, limit=limit)
        for msg in msgs:
            if fix_role_id and legacy_id and replies and py_role_id is None:
                try:
                    py_role_id = replies[0][1][3][0][0]
                except (IndexError, TypeError, KeyError):
                    py_role_id = False
            if fix_role_id and legacy_id and py_role_id:
                msg = substitute(msg, legacy_id, py_role_id)
            sent.append(msg)
            for out in sess.feed(frame(cipher.encode(encode(msg)))):
                replies.append(decode(out[4:]))
        return {'sent': sent, 'replies': replies, 'legacy_id': legacy_id,
                'last_line': last_line}
    finally:
        store.close()
        shutil.rmtree(tmp, ignore_errors=True)


def report(run, tap, max_diffs=MAX_DIFFS_SHOWN):
    """Print the per-command comparison; return the result dict."""
    last_line = run.get('last_line', 0) or 0
    java_msgs = [m for m in tap if m['dir'] == 'S'
                 and (not last_line or m['line'] <= last_line)]
    result = compare_sequences(java_msgs, run['replies'], VOLATILE, max_diffs)
    print('client sent: ' + ', '.join(str(m[0]) for m in run['sent']))
    print('python replies (order): ' + ', '.join(str(r[0]) for r in run['replies']))
    counts = {'match': 0, 'diff': 0, 'missing': 0, 'extra': 0}
    for cmd in sorted(result):
        r = result[cmd]
        counts['match'] += r['match']
        counts['diff'] += r['diff']
        counts['missing'] += r['missing']
        counts['extra'] += r['extra']
        print(f"  {cmd}  match={r['match']} diff={r['diff']} "
              f"missing={r['missing']} extra={r['extra']}")
        for d in r['details']:
            print(f'      {d[:220]}')
    print(f"  summary: match={counts['match']} diff={counts['diff']} "
          f"missing={counts['missing']} extra={counts['extra']}")
    print('  note: java pushes async frames (42001 readies, 42100 flushes, '
          '40000 moves) with no 1:1 client trigger, so missing is an '
          'upper bound, not a failure count.')
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tap', default=str(ROOT / 'output' / 'orig-stack' / 'tap-decoded.txt'))
    ap.add_argument('--raw-log', default=str(ROOT / 'output' / 'orig-stack' / 'tap.log'))
    ap.add_argument('--cmds', default=None,
                    help='comma-separated client command IDs to replay (default: all)')
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--no-fix-role-id', action='store_true')
    a = ap.parse_args()
    tap = read_tap(a.tap, read_raw_frames(a.raw_log))
    cmds = [int(c) for c in a.cmds.split(',')] if a.cmds else None
    run = replay_all(tap, fix_role_id=not a.no_fix_role_id, cmds=cmds, limit=a.limit)
    report(run, tap)


if __name__ == '__main__':
    main()

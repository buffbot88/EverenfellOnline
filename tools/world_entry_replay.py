#!/usr/bin/env python3
"""Replay the captured Java world-entry client messages through the Python game Session.

Seeds a throwaway SQLite DB from the captured role and diffs each Python reply
against the Java S> reply for the same command. Two runs: the captured bytes
verbatim, and the same messages with the role id the Python server issued.

  python3 tools/world_entry_replay.py [--tap output/orig-stack/tap-decoded.txt]
                                   [--raw-log output/orig-stack/tap.log]
"""
import argparse
import ast
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Server-v1'))

from auth import check_sign, hash_password
from db import Store
from game.amf3 import decode, encode
from game.cipher import SimpleEncrypt
from game.config import DEFAULT_CONFIG_DIR, GameConfig
from game.protocol import Session, frame

WORLD_ENTRY_CLIENT_CMDS = [10001, 10003, 20000, 21000, 53021, 19001]
WORLD_ENTRY_REPLY_CMDS = [10001, 13000, 32010, 10003, 20000, 21000, 23002,
                          23009, 12004, 12005, 12050, 12000, 19001]
# Server timestamps differ on every run; they are not comparable. The pet id
# is IdUtil.nextString('zuoqi') = thread-local counter in Java, so its value
# is runtime data, not protocol state (the frame is still compared on fields
# 1..13).
VOLATILE = {10001: ('[0][1][0]', '[0][1][1]'), 19001: ('[0]',),
            23009: ('[0][0][0]',)}
TAP_LINE = re.compile(r'([CS])> (\d+) (.*)$')
RAW_FRAME = re.compile(r'S>C len=(\d+) hex=\[([0-9a-f ]*)\]')
MAX_DIFFS_SHOWN = 6


def read_raw_frames(path):
    """Complete server frames from the hex log, as args lists keyed by command."""
    frames = {}
    for line in Path(path).read_text(encoding='utf-8', errors='replace').split('\n'):
        m = RAW_FRAME.search(line)
        if not m:
            continue
        raw = bytes.fromhex(m.group(2).replace(' ', ''))
        if len(raw) != int(m.group(1)):
            continue  # the hex log itself was cut short
        try:
            msg = decode(raw[4:])
        except Exception:
            continue
        if isinstance(msg, list) and msg and str(msg[0]).isdigit():
            frames.setdefault(int(msg[0]), []).append(msg[1:])
    return frames


def read_tap(path, raw_frames):
    """Parse the decoded tap into message dicts; the payload is the args list after the command."""
    msgs = []
    # Split on \n only: payload reprs can contain a raw carriage return.
    for lineno, line in enumerate(Path(path).read_text(encoding='utf-8').split('\n'), 1):
        m = TAP_LINE.search(line)
        if not m:
            continue
        direction, cmd, text = m.group(1), int(m.group(2)), m.group(3)
        try:
            args, truncated = ast.literal_eval(text), False
        except (ValueError, SyntaxError):
            # The tap cuts long payloads mid-repr. Recover the full frame from the
            # hex log only if the cut text is an exact prefix of its repr.
            args, truncated = None, True
            if direction == 'S':
                for full in raw_frames.get(cmd, []):
                    if repr(full).startswith(text):
                        args, truncated = full, False
                        break
        msgs.append({'dir': direction, 'cmd': cmd, 'args': args,
                     'line': lineno, 'truncated': truncated})
    return msgs


def first(msgs, direction, cmd):
    for m in msgs:
        if m['dir'] == direction and m['cmd'] == cmd:
            return m
    raise SystemExit(f'tap has no {direction}> {cmd}')


def client_messages(tap):
    """First client message per world-entry command, in tap order; each is [cmd, *args]."""
    picked = []
    for cmd in WORLD_ENTRY_CLIENT_CMDS:
        m = next((m for m in tap if m['dir'] == 'C' and m['cmd'] == cmd), None)
        if m is None:
            raise SystemExit(f'tap has no C> {cmd}')
        picked.append(m)
    picked.sort(key=lambda m: m['line'])
    return [[m['cmd'], *m['args']] for m in picked]


def seed_store(store, tap):
    """Insert the captured account, role, money, stage and settings; returns (account, server_id, role_id)."""
    login = first(tap, 'C', 10001)['args'][0]
    account, server_id = login[0], login[2]
    java_login = first(tap, 'S', 10001)['args'][0]
    legacy_id, name, job, sex, level, _, face, created_ms = java_login[3][0]
    state = first(tap, 'S', 10003)['args'][0][1]
    stage = first(tap, 'S', 10003)['args'][0][2]
    money = first(tap, 'S', 32010)['args'][0]
    hp = first(tap, 'S', 12004)['args'][0]
    zhenqi = int(first(tap, 'S', 12050)['args'][0][0])
    shanbi_val = int(first(tap, 'S', 12005)['args'][0][0])
    settings_msg = first(tap, 'S', 13000)
    settings = [None] * 4 if settings_msg['truncated'] else settings_msg['args'][0]

    store.create_account(account, hash_password('captured-replay'))
    role_id = store.create_character(
        account, server_id, name, job=job, sex=sex, face=face,
        legacy_id=legacy_id, level=level, exp=int(state[2]),
        map_id=stage[0], map_x=stage[1], map_y=stage[2],
        hp=int(hp[1]), max_hp=int(hp[2]), mp=int(hp[3]), max_mp=int(hp[4]),
        zhenqi=zhenqi,
        tongqian=int(money[0]), lingshi=int(money[1]),
        bind_lingshi=int(money[2]), recive_yb=int(money[3]))
    # shanbi_val lives on role_stage (the migrated stage row's column).
    # zuoqi_info seeds the captured mount: the tap's 23009 says rank 1 with
    # curHp 500 and pet alive, i.e. rideOrNo false (Java only spawns the pet
    # when not riding). No migrated role_stage row has this column yet.
    store.save_role_stage(role_id, shanbi_val=shanbi_val,
                          zuoqi_info='{"id":1,"hp":500,"deadTime":0,'
                                     '"useTime":0,"rideOrNo":false}')
    # create_character stamps "now"; restore the captured role creation time.
    with store.lock:
        store.db.execute('UPDATE characters SET created=? WHERE id=?',
                         (created_ms // 1000, role_id))
        store.db.commit()
    values = {n: v for n, v in zip(
        ['quickbar_info', 'panel_config', 'ui_info', 'guaji_info'], settings)
        if v is not None}
    if values:
        store.save_role_settings(role_id, account, server_id, **values)
    return account, server_id, role_id


def make_session(store):
    """Same wiring as server.py GameTCPHandler, with the defaults server.py uses."""
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
        # DEFAULT_CONFIG_DIR is relative to Server-v1/, as server.py expects.
        config=GameConfig(os.path.normpath(str(ROOT / 'Server-v1' / DEFAULT_CONFIG_DIR))))


def substitute(value, old, new):
    """Replace whole-string occurrences of old with new, recursively."""
    if isinstance(value, str):
        return new if value == old else value
    if isinstance(value, list):
        return [substitute(v, old, new) for v in value]
    return value


def diff(java, python, path='', out=None):
    """Structural diff; numbers compare by value, so 5466 == 5466.0."""
    out = [] if out is None else out
    if isinstance(java, dict) and isinstance(python, dict):
        for k in sorted(set(java) | set(python), key=str):
            if k not in python:
                out.append(f'{path}{{{k!r}}}: only in java')
            elif k not in java:
                out.append(f'{path}{{{k!r}}}: only in python')
            else:
                diff(java[k], python[k], f'{path}{{{k!r}}}', out)
    elif isinstance(java, (list, tuple)) and isinstance(python, (list, tuple)):
        if len(java) != len(python):
            out.append(f'{path}: length java={len(java)} python={len(python)}')
        for i, (a, b) in enumerate(zip(java, python)):
            diff(a, b, f'{path}[{i}]', out)
    elif isinstance(java, (bytes, bytearray)) and isinstance(python, (bytes, bytearray)):
        if bytes(java) != bytes(python):
            out.append(f'{path}: bytes differ (java {len(java)}B, python {len(python)}B)')
    elif isinstance(java, (int, float)) and isinstance(python, (int, float)):
        if float(java) != float(python):
            out.append(f'{path}: java={java!r} python={python!r}')
    elif java != python:
        out.append(f'{path}: java={java!r} python={python!r}')
    return out


def clip(text, limit=110):
    text = text if len(text) <= limit else text[:limit] + '...'
    return text


def replay(tap, use_python_role_id):
    tmp = tempfile.mkdtemp()
    store = Store(os.path.join(tmp, 'replay.db'))
    try:
        account, server_id, role_id = seed_store(store, tap)
        legacy_id = first(tap, 'S', 10001)['args'][0][3][0][0]
        sess = make_session(store)
        key = sess.feed(frame(encode('INITKEY')))[0][4:].decode()
        cipher = SimpleEncrypt(key)
        replies = []
        sent = []
        for msg in client_messages(tap):
            if use_python_role_id and replies:
                # The 10001 reply carries Python's role id; a client would use it.
                py_id = replies[0][1][3][0][0]
                msg = substitute(msg, legacy_id, py_id)
            sent.append(msg)
            for out in sess.feed(frame(cipher.encode(encode(msg)))):
                replies.append(decode(out[4:]))
        return {'sent': sent, 'replies': replies, 'legacy_id': legacy_id,
                'role_id': role_id, 'account': account, 'server_id': server_id}
    finally:
        store.close()
        shutil.rmtree(tmp, ignore_errors=True)


def report(title, tap, run, max_diffs=MAX_DIFFS_SHOWN):
    print(f'== {title}')
    print('client sent: ' + ', '.join(str(m[0]) for m in run['sent']))
    print('python replies (order): ' + ', '.join(str(r[0]) for r in run['replies']))
    java_order = []
    for m in tap:
        if m['dir'] == 'S' and m['cmd'] in WORLD_ENTRY_REPLY_CMDS and m['cmd'] not in java_order:
            java_order.append(m['cmd'])
    print('java replies (first of each): ' + ', '.join(str(c) for c in java_order))
    py_by_cmd = {}
    for r in run['replies']:
        py_by_cmd.setdefault(int(r[0]), r)
    java_cmds = set()
    counts = {'match': 0, 'diff': 0, 'missing': 0}
    for cmd in WORLD_ENTRY_REPLY_CMDS:
        java = next((m for m in tap if m['dir'] == 'S' and m['cmd'] == cmd), None)
        if java is None:
            continue
        java_cmds.add(cmd)
        if java['truncated']:
            print(f'  {cmd}  NOT COMPARED (java payload truncated in tap line {java["line"]})')
            continue
        if cmd not in py_by_cmd:
            counts['missing'] += 1
            print(f'  {cmd}  MISSING in python (java sent it, python sent nothing)')
            continue
        py_args = py_by_cmd[cmd][1:]
        volatile = VOLATILE.get(cmd, ())
        diffs = [d for d in diff(java['args'], py_args) if not d.startswith(volatile)]
        if not diffs:
            counts['match'] += 1
            print(f'  {cmd}  match')
            continue
        counts['diff'] += 1
        print(f'  {cmd}  DIFF ({len(diffs)})')
        for d in diffs[:max_diffs]:
            print(f'      {clip(d, 220)}')
        if len(diffs) > max_diffs:
            print(f'      ... {len(diffs) - max_diffs} more')
    extras = sorted({int(r[0]) for r in run['replies']} - java_cmds)
    if extras:
        print('  python-only replies: ' + ', '.join(str(c) for c in extras))
    print(f'  summary: match={counts["match"]} diff={counts["diff"]} missing={counts["missing"]}')
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tap', default=str(ROOT / 'output' / 'orig-stack' / 'tap-decoded.txt'))
    ap.add_argument('--raw-log', default=str(ROOT / 'output' / 'orig-stack' / 'tap.log'),
                    help='hex frame log used to recover payloads the decoded tap cut short')
    a = ap.parse_args()
    tap = read_tap(a.tap, read_raw_frames(a.raw_log))
    verbatim = replay(tap, use_python_role_id=False)
    report('run 1: captured client bytes verbatim '
           f'(role id {verbatim["legacy_id"]!r} sent back)', tap, verbatim)
    fixed = replay(tap, use_python_role_id=True)
    report('run 2: role id replaced by the id python issued '
           f'({fixed["role_id"]})', tap, fixed)


if __name__ == '__main__':
    main()

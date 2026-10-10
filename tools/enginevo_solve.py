#!/usr/bin/env python3
"""Solver for EngineVO.readExternal (exploratory; not part of the suite)."""
import copy
import glob
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Server-v1'))
from game.amf3 import Reader, Amf3Error  # noqa: E402

MAPINFO_AFTER = 9
SETTINGS_TOTAL = 22


def ext_begin(d, r):
    p = r.p
    ln = struct.unpack('>H', d[p:p + 2])[0]
    tag = d[p + 2:p + 2 + ln].decode('utf-8', errors='replace')
    q = p + 2 + ln
    ints = [struct.unpack('>i', d[q + 4 * k:q + 4 * k + 4])[0] for k in range(7)]
    flag = d[q + 28]
    return tag, ints, flag, q + 29


def snapshot(r):
    return (r.p, list(r.strings), copy.deepcopy(r.objects), list(r.traits))


def restore(r, snap):
    r.p, r.strings, r.objects, r.traits = snap[0], snap[1], snap[2], snap[3]


def try_resume_outer(d, r, n_settings_remain):
    """14 sealed settings members, then dynamic pairs, then 9 mapinfo members."""
    snap = snapshot(r)
    try:
        vals = [r.read() for _ in range(n_settings_remain)]
        dyn = {}
        for _ in range(100):
            k = r.string()
            if k == '':
                break
            dyn[k] = r.read()
        vals.append(dyn)
        vals.extend(r.read() for _ in range(MAPINFO_AFTER))
        if r.p == len(d):
            return vals
        return None
    except (Amf3Error, IndexError, struct.error, UnicodeDecodeError):
        return None
    finally:
        restore(r, snap)


def member_index(r, cls, member):
    for cname, members, ext, dyn in r.traits:
        if cname == cls:
            return members.index(member)
    raise AssertionError(f'no traits for {cls}')


def solve(path):
    mid = os.path.basename(os.path.dirname(path))
    d = zlib.decompress(open(path, 'rb').read())
    r = Reader(d)
    try:
        r.read()
        return {'mid': mid, 'status': 'no-externalizable'}
    except Amf3Error as e:
        if 'externalizable' not in str(e):
            return {'mid': mid, 'status': 'other-error: %s' % e}
    if r.traits[-1][0] != 'com.youbt.game.tbg.vo.EngineVO':
        return {'mid': mid, 'status': 'raiser-is-%s' % r.traits[-1][0]}
    n_set = SETTINGS_TOTAL - (member_index(r, 'com.youbt.game.tbg.vo.MapSettings', 'enginevo') + 1)
    tag, ints, flag, q = ext_begin(d, r)
    if tag != 'EngineVO2' or flag != 1:
        return {'mid': mid, 'status': 'header-mismatch tag=%r flag=%r' % (tag, flag)}
    r.p = q
    items = []
    for _ in range(600):
        got = try_resume_outer(d, r, n_set)
        if got is not None:
            return {'mid': mid, 'status': 'solved', 'n_items': len(items),
                    'items': [type(v).__name__ + ':' + repr(v)[:100] for v in items],
                    'tail': [type(v).__name__ + ':' + repr(v)[:70] for v in got]}
        if r.p >= len(d):
            return {'mid': mid, 'status': 'truncated@EOF items=%d' % len(items),
                    'items': [repr(v)[:70] for v in items]}
        if d[r.p] == 0x13 and d[r.p + 1:r.p + 10] == b'layerinfo':
            s = r.string()
            items.append(('section', s))
            continue
        try:
            items.append(r.read())
        except (Amf3Error, IndexError, UnicodeDecodeError, struct.error) as e:
            return {'mid': mid, 'status': 'fail@%d/%d: %s items=%d' % (r.p, len(d), e, len(items)),
                    'items': [repr(v)[:70] for v in items],
                    'context': repr(d[r.p:r.p + 32])}
    return {'mid': mid, 'status': 'too-many-items'}


def main():
    files = sorted(glob.glob('reference/TonNgoKhong/server/config/game/map_config/*/map.dat'))
    only = sys.argv[1:] or None
    solved = truncated = failed = 0
    for f in files:
        mid = os.path.basename(os.path.dirname(f))
        if only and mid not in only:
            continue
        res = solve(f)
        st = res['status']
        if st == 'solved':
            solved += 1
        elif st.startswith('truncated'):
            truncated += 1
        else:
            failed += 1
        print(mid, st, 'n_items', res.get('n_items'))
        if only:
            for it in (res.get('items') or [])[:60]:
                print('   ', it[:160])
            if st == 'solved':
                print('    tail:', res['tail'][:4], '...', res['tail'][-3:])
            if res.get('context'):
                print('    context:', res['context'])
    if not only:
        print('solved=%d truncated=%d failed=%d' % (solved, truncated, failed))


if __name__ == '__main__':
    main()

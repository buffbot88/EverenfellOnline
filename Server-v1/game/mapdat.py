"""Reader for client-side map.dat (zlib-wrapped AMF3 with an externalizable EngineVO).

Layout, recovered from the bytes (the client SWFs that define readExternal
are still encrypted, see docs/swf-encryption-notes.md):
  zlib stream, then one AMF3 object com.youbt.game.tbg.vo.MapInfo. Inside
  MapSettings.enginevo sits externalizable com.youbt.game.tbg.vo.EngineVO
  whose payload is readUTF('EngineVO2') + 7 big-endian int32 + 1 flag byte,
  then a body of AMF3 values (readObject, shared tables) plus U29-prefixed
  section strings (0x13 + 'layerinfo', registered like any AMF3 string).
  The body holds the walk grid (ByteArray, len == path_mm w*h), the layer
  name/dims, and a dynamic object of indexed tbg.EffectDef entries.
"""
import copy
import struct
import zlib

from .amf3 import Amf3Error, ByteArray, Obj, Reader

ENGINEVO_CLASS = 'com.youbt.game.tbg.vo.EngineVO'
ENGINEVO_TAG = 'EngineVO2'
ENGINEVO_INTS = [3, 60, 30, 0, 0, 1000, 600]
SETTINGS_MEMBERS = 22
ENGINEVO_INDEX = 7  # enginevo inside MapSettings sealed members
MAPINFO_TAIL = 9  # name..guid after settings
SECTION_MAGIC = b'layerinfo'


def _snapshot(r):
    return (r.p, list(r.strings), copy.deepcopy(r.objects), list(r.traits))


def _restore(r, snap):
    r.p, r.strings, r.objects, r.traits = snap[0], snap[1], snap[2], snap[3]


def _ext_head(d, r):
    """Parse tag + 7 ints + flag at readExternal start; return (tag, ints, flag, body_pos)."""
    p = r.p
    ln = struct.unpack('>H', d[p:p + 2])[0]
    tag = d[p + 2:p + 2 + ln].decode('utf-8', errors='replace')
    q = p + 2 + ln
    ints = [struct.unpack('>i', d[q + 4 * k:q + 4 * k + 4])[0] for k in range(7)]
    return tag, ints, d[q + 28], q + 29


def _try_outer(d, r, n_set):
    """Shape-validated outer resume: sealed + dynamics + 9 tail to exact EOF."""
    snap = _snapshot(r)
    try:
        sealed = [r.read() for _ in range(n_set)]
        dyn = {}
        for _ in range(200):
            k = r.string()
            if k == '':
                break
            dyn[k] = r.read()
        else:
            return None
        tail = [r.read() for _ in range(MAPINFO_TAIL)]
        if r.p != len(d):
            return None
        if not isinstance(tail[0], str) or not isinstance(tail[7], str):
            return None
        data = tail[6]
        if data is not None and not (
                isinstance(data, Obj) and set(data.keys()) == {'ba', 'h', 'w'}
                and isinstance(data['ba'], (bytes, ByteArray))):
            return None
        return {'settings_tail': sealed, 'dynamics': dyn, 'tail': tail}
    except (Amf3Error, IndexError, struct.error, UnicodeDecodeError):
        return None
    finally:
        _restore(r, snap)


def load_map_dat(path):
    """Parse a map.dat file; outer is None when no complete outer tail exists."""
    with open(path, 'rb') as f:
        d = zlib.decompress(f.read())
    r = Reader(d)
    try:
        v = r.read()
        return {'map_info': v, 'enginevo': None, 'outer': v,
                'complete': r.p == len(d), 'ext_end': r.p, 'size': len(d)}
    except Amf3Error as e:
        if 'externalizable' not in str(e):
            raise
    if not r.traits or r.traits[-1][0] != ENGINEVO_CLASS:
        raise Amf3Error('first externalizable is not EngineVO')
    members = r.traits[[t[0] for t in r.traits].index(
        'com.youbt.game.tbg.vo.MapSettings')][1]
    n_set = len(members) - (members.index('enginevo') + 1)
    tag, ints, flag, q = _ext_head(d, r)
    if tag != ENGINEVO_TAG or flag != 1:
        raise Amf3Error(f'EngineVO header: tag={tag!r} flag={flag!r}')
    r.p = q
    items = []
    outer = None
    stop = {'reason': 'eof', 'pos': len(d)}
    for _ in range(2000):
        outer = _try_outer(d, r, n_set)
        if outer is not None:
            stop = {'reason': 'outer', 'pos': r.p}
            break
        if r.p >= len(d):
            break
        if d[r.p:r.p + 1] == b'\x13' and d[r.p + 1:r.p + 10] == SECTION_MAGIC:
            items.append(('section', r.string()))
            continue
        try:
            items.append(r.read())
        except (Amf3Error, IndexError, struct.error, UnicodeDecodeError) as e:
            stop = {'reason': f'{e}', 'pos': r.p}
            break
    return {'map_info': None, 'enginevo': {'tag': tag, 'ints': ints, 'flag': flag,
                                           'items': items},
            'outer': outer, 'complete': outer is not None,
            'ext_end': stop['pos'], 'size': len(d), 'stop': stop}

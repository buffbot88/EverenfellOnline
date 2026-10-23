"""Clan-dungeon (ZuwuFuBen) service helpers: sweep codec, gates, settle math.

Ports ZuwufubenServiceImpl + SaoDangVo + ZuWuFuBenConfig Intelligence
against dntg_start.jar javap evidence (see docs/zuwufuben-ledger.md for
the method-by-method recovery notes).

Stored cells mirror the Java entity (RoleZuwufuben):
- everyday_pass_data: '{"1": remaining, ...}' (remaining attempts)
- buy_count_data: '{"1": bought, ...}' (bought attempts)
- saodang_data: SaoDangVo JSON
  {"sdStartTime": ms, "sdChiXuTime": ms, "sdId": id|null,
   "autoPass": bool, "center": bool, "saoDang": derived}
- everyday_time: epoch millis of the last daily touch.

Derived reply triple per dungeon: [idStr, used, total] where
total = bought + 1 and used = total - remaining.
"""
import json as _json
import time as _time

# ZuwufubenErrorCode <clinit> values (dntg_start.jar).
ERR_NOT_OPEN = 114001
ERR_NO_COUNT = 114002
ERR_SAODANGING = 114003
ERR_BUY_LOCKED = 114004
ERR_NO_SAODANG_ID = 114005
ERR_BUY_MAX = 114006
ERR_NOT_SAODANG = 114007
ERR_IN_FUBEN = 114008
ERR_SWEEP_LOCKED = 114009
ERR_AUTO_PASS = 114010
ERR_SAODANG_DONE = 114011
# GeneralErrorCode values shared with the story-dungeon port.
ERR_LEVEL_NOT_ENOUGH = 1000
ERR_YB_NOT_ENOUGH = 1002

# offline() floor: an already-elapsed sweep keeps 50s when the role logs out.
OFFLINE_SWEEP_FLOOR_MS = 50000

# SaoDangVo field order of JSON.toJSONString (getter order).
_SAO_KEYS = ('sdStartTime', 'sdChiXuTime', 'sdId', 'autoPass', 'center',
             'saoDang')


def _loads_obj(cell):
    """Parse a JSON object cell, or None when empty/broken."""
    text = str(cell or '').strip()
    if not text:
        return None
    try:
        obj = _json.loads(text)
    except (TypeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _dump(obj):
    """Compact JSON like fastjson JSONObject.toString (no spaces)."""
    return _json.dumps(obj, separators=(',', ':'))


def decode_sao(cell):
    """SaoDangVo fields, or None when the cell is empty/broken.

    Java createSaoDangVo returns null for unparseable input; a fresh
    ``new SaoDangVo()`` renders '{}', which parses with sdId None.
    """
    obj = _loads_obj(cell)
    if obj is None:
        return None
    try:
        sdid = obj.get('sdId')
        sdid = int(sdid) if sdid is not None else None
        return {'sdid': sdid,
                'start': int(obj.get('sdStartTime') or 0),
                'chixu': int(obj.get('sdChiXuTime') or 0),
                'autopass': bool(obj.get('autoPass')),
                'center': bool(obj.get('center'))}
    except (TypeError, ValueError):
        return None


def encode_sao(sdid, start_ms, chixu_ms, autopass=False, center=False):
    """SaoDangVo back to its info string (fastjson getter key order)."""
    sweeping = sdid is not None and int(sdid) != 0
    return _dump({'sdStartTime': int(start_ms),
                  'sdChiXuTime': int(chixu_ms),
                  'sdId': int(sdid) if sdid is not None else None,
                  'autoPass': bool(autopass),
                  'center': bool(center),
                  'saoDang': bool(sweeping)})


def is_sweeping(vo):
    """SaoDangVo.isSaoDang: sdId present and nonzero (the stored field
    is vestigial; the getter derives from sdId)."""
    return vo is not None and vo.get('sdid') not in (None, 0)


def sweep_end_ms(vo):
    """Sweep deadline: sdStartTime + sdChiXuTime."""
    return int(vo.get('start') or 0) + int(vo.get('chixu') or 0)


def parse_counts(cell):
    """'{id: remaining;...}' daily/buy map, tolerant of order and blanks."""
    out = {}
    try:
        obj = _loads_obj(cell)
    except Exception:
        return out
    if obj is None:
        return out
    for key, val in obj.items():
        try:
            out[int(str(key).strip())] = int(val)
        except (TypeError, ValueError):
            continue
    return out


def format_counts(mapping):
    """Daily/buy map back to a JSON string (sorted; Java order is random)."""
    return _dump({str(k): int(mapping[k]) for k in sorted(mapping)})


def used_total(everyday, buy, dungeon_id):
    """(used, total) reply pair: total = bought + 1, used = total - left."""
    total = int(buy.get(int(dungeon_id), 0)) + 1
    used = total - int(everyday.get(int(dungeon_id), 0))
    return used, total


def info_rows(everyday, buy):
    """getInfo per-dungeon rows [[idStr, used, total]] in stored order."""
    rows = []
    for key in everyday:
        try:
            did = int(key)
        except (TypeError, ValueError):
            continue
        used, total = used_total(everyday, buy, did)
        rows.append([str(did), used, total])
    return rows


def check_enter(center, sweeping, role_level, need_level, dungeon_id,
                pass_max, everyday):
    """enterFuBen checked() gate order; None when entry is allowed."""
    if center:
        return ERR_IN_FUBEN
    if sweeping:
        return ERR_SAODANGING
    if int(role_level or 0) < int(need_level or 0):
        return ERR_LEVEL_NOT_ENOUGH
    if int(dungeon_id) > int(pass_max or 0) + 1:
        return ERR_NOT_OPEN
    if int(everyday.get(int(dungeon_id), 0)) <= 0:
        return ERR_NO_COUNT
    return None


def first_sweep_id(everyday, pass_max):
    """getSaoDangId: lowest id <= passMax with remaining attempts, or None."""
    for did in range(1, int(pass_max or 0) + 1):
        if int(everyday.get(did, 0)) > 0:
            return did
    return None


def check_sweep_param(dungeon_id, pass_max, everyday):
    """Explicit-id saoDangFuben gates; None when the sweep may start."""
    if int(dungeon_id) > int(pass_max or 0):
        return ERR_SWEEP_LOCKED
    if int(everyday.get(int(dungeon_id), 0)) <= 0:
        return ERR_NO_COUNT
    return None


def offline_chixu(vo, now_ms):
    """offline(): remaining millis, or the 50s floor when already elapsed."""
    remain = int(vo.get('chixu') or 0) - \
        (int(now_ms) - int(vo.get('start') or 0))
    if remain > 0:
        return remain
    return OFFLINE_SWEEP_FLOOR_MS


def lottery_open(rate_text):
    """Lottery.isSuccess gate for the zubao1 roll (empty rate never hits)."""
    try:
        return float(str(rate_text or '').strip() or 0) > 0
    except (TypeError, ValueError):
        return False


def now_ms():
    """Wall clock in millis (matches System.currentTimeMillis use)."""
    return int(_time.time() * 1000)

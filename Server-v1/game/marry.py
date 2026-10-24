"""Marriage (MarryServiceImpl) helpers: error codes, gates, ring display.

Ports MarryErrorCode (<clinit> values from dntg_start.jar), the
hasMarry/addRoleMarray/lihun row shapes, and the getInfo/accept
payload layouts. Stored cells mirror the RoleMarry entity (see
db.py role_marry); timestamps are epoch millis like the rest of
the port.
"""
import datetime as _datetime
import time as _time

# MarryErrorCode <clinit> values (dntg_start.jar).
ERR_HAS_MARRY = 135001
ERR_HUNJIE_NOT_EXIST = 135002
ERR_NOT_ON_LINE = 135003
ERR_NOT_MARRY = 135004
ERR_MANOR_ING = 135006
ERR_HAS_DEAD = 135007
ERR_IN_COPY = 135008
ERR_LEVEL_MAX = 135009
ERR_QINGMIDU_NOT_ENOUGH = 135010
ERR_CHUANGSONG_CD = 135011
# GeneralErrorCode values shared with the other ports.
ERR_LEVEL_NOT_ENOUGH = 1000
ERR_YB_NOT_ENOUGH = 1002
ERR_GOODS_NOT_ENOUGH = 1005

# Fresh RoleMarry defaults (setLihun false, qingmidu/day 0, ring tier 1,
# bind locked, chuansong/expire 0, create now) from addRoleMarray.
RING_START_TIER = 1
RING_START_RARE = 0
RING_START_BIND = 1


def is_married(row):
    """hasMarry: a row exists and its lihun flag is not set."""
    if not row:
        return False
    try:
        return not bool(int(row.get('lihun') or 0))
    except (TypeError, ValueError):
        return False


def fresh_row(rid, spouse_rid, goods_id, now_ms=None):
    """addRoleMarray insert shape for a newlywed side."""
    now = int(now_ms) if now_ms is not None else int(_time.time() * 1000)
    return {'user_role_id': str(rid),
            'marry_user_role_id': str(spouse_rid),
            'qingmidu': 0,
            'chuansong_time': 0,
            'create_time': now,
            'goods_id': str(goods_id or ''),
            'bind': RING_START_BIND,
            'expire_time': 0,
            'rare_level': RING_START_RARE,
            'item_level': RING_START_TIER,
            'attributes': None,
            'lihun': 0,
            'day_qingmidu': 0,
            'log_update_time': now}


def divorce_row(row, now_ms=None):
    """lihun(RoleMarry): flag set, intimacy zeroed, spouse kept."""
    now = int(now_ms) if now_ms is not None else int(_time.time() * 1000)
    out = dict(row or {})
    out['lihun'] = 1
    out['qingmidu'] = 0
    out['day_qingmidu'] = 0
    out['log_update_time'] = now
    return out


def ring_formart(role_id, row):
    """StoreGoodsOutput.formart map for the wedding ring on a marry row.

    Same 18-slot shape the zuwu port uses for granted models: id is the
    ring goods id, slot 0, owner the role; bind/expire/rare/tier and the
    attribute blob ride from the row.
    """
    row = row or {}
    try:
        tier = int(row.get('item_level') or 0)
    except (TypeError, ValueError):
        tier = 0
    try:
        rare = int(row.get('rare_level') or 0)
    except (TypeError, ValueError):
        rare = 0
    try:
        bind = int(row.get('bind') or 0)
    except (TypeError, ValueError):
        bind = 0
    try:
        expire = int(row.get('expire_time') or 0)
    except (TypeError, ValueError):
        expire = 0
    attrs = row.get('attributes')
    return {
        '0': str(row.get('goods_id') or ''), '1': str(row.get('goods_id') or ''),
        '2': 0, '3': 1, '4': str(role_id), '5': tier,
        '6': rare, '7': bind, '8': expire, '9': None,
        '10': 0, '11': None, '12': 0, '13': attrs, '14': None,
        '15': 0, '16': 0, '17': 0}


def is_today(moment_ms, now_ms=None):
    """ObjectUtil.dayIsToday over epoch millis."""
    try:
        moment = int(moment_ms or 0)
    except (TypeError, ValueError):
        return False
    if moment <= 0:
        return False
    now = int(now_ms) if now_ms is not None else int(_time.time() * 1000)
    try:
        return _datetime.datetime.fromtimestamp(
            moment / 1000.0).date() == _datetime.datetime.fromtimestamp(
                now / 1000.0).date()
    except (OSError, OverflowError, ValueError):
        return False


def days_since(moment_ms, now_ms=None):
    """Whole days between a past stamp and now (twoDaysDiffence shape)."""
    try:
        moment = int(moment_ms or 0)
    except (TypeError, ValueError):
        return 0
    now = int(now_ms) if now_ms is not None else int(_time.time() * 1000)
    if moment <= 0 or now <= moment:
        return 0
    return int((now - moment) // 86400000)


def seconds_until_time_of_day(hour, minute=0, now_ms=None):
    """Seconds until the next wall-clock HH:MM (quartz daily tick)."""
    now = int(now_ms) if now_ms is not None else int(_time.time() * 1000)
    try:
        base = _datetime.datetime.fromtimestamp(now / 1000.0)
        slot = base.replace(hour=int(hour), minute=int(minute), second=0,
                            microsecond=0)
    except (TypeError, ValueError, OSError, OverflowError):
        return 86400
    if slot.timestamp() * 1000 <= now:
        slot = slot + _datetime.timedelta(days=1)
    return max(int(slot.timestamp() - now / 1000.0), 1)

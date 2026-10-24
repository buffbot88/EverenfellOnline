"""Xianjiehuoyuedu activity points and Xianjie/Chenghao progression.

Ports ``XianjiehuoyueduServiceImpl`` (daily activity accumulation, the
90000/90001/91001 surface, ``getDayHuoYuedu``), ``XianjiechenhaoServiceImpl``
(rank upgrade/switch plus the 27-type ``limit1`` title engine) and their
config tables. Everything here is pure: rows are dicts and the caller
persists them (``Server-v1/db.py`` role_xianjiehuoyuedu /
role_xianjiechenhao).

Java quirks preserved on purpose:

- ``MeiRiHuoYueConfig.value`` is ``huoyuezhi / jindu`` integer division,
  so per-unit rows whose threshold exceeds their reward (EXP 10/50000000,
  LINGQI 10/50000, PK_SHEGUAI 10/1000) award 0 per unit. That is the
  original data's behaviour, not a port bug.
- ``islingqu`` treats a null/empty claim cell as already claimed; only the
  ``'[]'`` initialized by ``online`` unlocks claims.
- a finished type keeps accumulating its counter but awards nothing more
  that day, and the 91000 push fires only on the call that finishes it.
- ``miaoSha`` never checks the finish list: the only guard is the
  counter against ``jindu``, so the buy writes the counter to the
  threshold and appends the finish id (a duplicate when the row was
  already finished).
- titles with condition 25 are unreachable and condition 5 uses a strict
  ``>`` on the monster counter.
"""
import datetime as _datetime
import json
import time as _time

# XianjiehuoyueduErrorCode <clinit>.
ERR_NOT_FINISH = 90001        # 90001: already at the activity threshold
ERR_NOT_MIAOSHA = 90002       # 90002: row has no instant-complete option
ERR_HAS_CLAIMED = 90003       # 90003: reward already claimed today
ERR_HUOYUE_NOT_ENOUGH = 90004  # 90004: daily activity below the reward row

# XianjiechenhaoErrorCode <clinit>.
CH_ERR_PREV = 91001        # previous rank not owned
CH_ERR_HAS = 91002         # rank already owned
CH_ERR_HUOYUE = 91003      # rank activity requirement not met
CH_ERR_SHOW = 91004        # rank switch push
CH_ERR_LOG = 91005         # kill-log page
CH_ERR_ACTIVATE = 91006    # title activation push
CH_ERR_LOG_APPEND = 91007  # kill-log append push
CH_ERR_ROUTE = 91008       # server-only route
CH_ERR_TITLE = 91009       # title activation broadcast
CH_ERR_NOTICE = 91010      # rank upgrade world notice

# GeneralErrorCode values used by the family.
ERR_YB_NOT_ENOUGH = 1002
ERR_BAG_SLOT_NOT_ENOUGH = 1004

# HuoYueDuType: intType -> enum name (getType's tableswitch 1..21).
HUOYUE_TYPES = {
    1: 'VIP',
    2: 'STORE',
    3: 'STORE_YB',
    4: 'JINDIANZHANYI',
    5: 'SHENJIANGJINDI',
    6: 'RICHANGRENWU',
    7: 'PK_SHEGUAI',
    8: 'GUIJIANGJINYING',
    9: 'SHENJIANGBOSS',
    10: 'LINGQI',
    11: 'EXP',
    12: 'MEIRICHANMIAN',
    13: 'QIQIN',
    14: 'GUANGHANGONG',
    15: 'MEJIERUQING',
    16: 'EQUIP_JIANDING',
    17: 'FENGSHENGZENGBA',
    18: 'TEAMFUBEN',
    19: 'BAIXIAN',
    20: 'WEIDUAN',
    21: 'BAIXIAN_YXB',
}
# Types whose config sets dandusuan (``jisuan``): the counter is a running
# total and every increment awards value points, not just the completion.
PER_UNIT_TYPES = frozenset({1, 4, 7, 10, 11, 12, 13, 14, 17, 18, 19, 20})
# Types whose producer passes a live count and Java passes bAdd=false, so
# the cell is replaced instead of accumulated.
STATE_TYPES = frozenset({1, 6, 16})


def row_for(role_id, row=None, now_ms=None):
    """A usable activity row: the stored one or a fresh ``online`` row."""
    now = _now_ms(now_ms)
    if row is None:
        return {'role_id': str(role_id), 'huoyuedu': 0,
                'huoyuedu_list': '{}', 'meiri_jiangli': '[]',
                'meiri_finish_id': '[]', 'meiri_jiangli_time': now,
                'log_update_time': now}, True
    out = dict(row)
    out['role_id'] = str(out.get('role_id') or role_id)
    out.setdefault('huoyuedu', 0)
    out.setdefault('huoyuedu_list', '{}')
    out.setdefault('meiri_jiangli', '[]')
    out.setdefault('meiri_finish_id', '[]')
    out.setdefault('meiri_jiangli_time', 0)
    out.setdefault('log_update_time', 0)
    return out, False


def _now_ms(now_ms=None):
    return int(now_ms) if now_ms is not None else int(_time.time() * 1000)


def day_is_today(stamp_ms, now_ms=None):
    """DatatimeUtil.dayIsToday: a null/zero stamp is never today."""
    try:
        stamp = int(stamp_ms or 0)
    except (TypeError, ValueError):
        return False
    if stamp <= 0:
        return False
    try:
        moment = _datetime.datetime.fromtimestamp(stamp / 1000.0).date()
        today = _datetime.datetime.fromtimestamp(
            _now_ms(now_ms) / 1000.0).date()
    except (OSError, OverflowError, ValueError):
        return False
    return moment == today


def clear_day(row, now_ms=None):
    """XianjiehuoyueduServiceImpl.clear: reset the daily cells, keep total."""
    out = dict(row)
    if day_is_today(out.get('meiri_jiangli_time'), now_ms):
        return out, False
    out['huoyuedu_list'] = '{}'
    out['meiri_jiangli'] = '[]'
    out['meiri_finish_id'] = '[]'
    out['meiri_jiangli_time'] = _now_ms(now_ms)
    return out, True


def _json_object(text):
    if text is None or text == '':
        return {}
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _json_array(text):
    if text is None or text == '':
        return []
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def counters(row):
    """The huoyueduList object with int values (getHuoyueduDataValue)."""
    out = {}
    for key, value in _json_object(row.get('huoyuedu_list')).items():
        try:
            out[str(key)] = int(value)
        except (TypeError, ValueError):
            out[str(key)] = 0
    return out


def counter(row, type_id):
    """getHuoyueduDataValue(type): one counter, 0 when absent."""
    return counters(row).get(str(type_id), 0)


def _set_counter(row, type_id, value):
    table = counters(row)
    table[str(type_id)] = int(value)
    row['huoyuedu_list'] = json.dumps(table, sort_keys=True)
    return row


def finish_ids(row):
    """The meiriFinishId array as strings."""
    return [str(v) for v in _json_array(row.get('meiri_finish_id'))]


def claims(row):
    """The meiriJiangli array as strings."""
    return [str(v) for v in _json_array(row.get('meiri_jiangli'))]


def _add_finish(row, type_id):
    ids = finish_ids(row)
    if str(type_id) not in ids:
        ids.append(str(type_id))
    row['meiri_finish_id'] = json.dumps(ids)
    return row


def finished(row, type_id):
    return str(type_id) in finish_ids(row)


def can_claim(row):
    """islingqu's inversion: null/empty claim cell means already claimed."""
    text = row.get('meiri_jiangli')
    if text is None or text == '':
        return False
    return True


def day_total(cfg, row):
    """getDayHuoYuedu: finished types pay huoyuezhi, open per-unit types
    pay counter * value."""
    table = counters(row)
    done = set(finish_ids(row))
    total = 0
    for key, value in table.items():
        try:
            type_id = int(key)
        except (TypeError, ValueError):
            continue
        cfg_row = cfg.get(str(type_id))
        if cfg_row is None:
            continue
        if key in done:
            total += _int(cfg_row.get('huoyuezhi'))
        elif cfg_row.get('jisuan'):
            total += int(value) * _int(cfg_row.get('value'))
    return total


def is_finish(cfg_row, current, data):
    """isfinish: counter >= jindu, with VIP reading the passed level."""
    threshold = _int(cfg_row.get('jindu'))
    if cfg_row.get('type') == 'VIP':
        try:
            return int(data) >= threshold
        except (TypeError, ValueError):
            return False
    return int(current) >= threshold


def record(cfg, row, type_id, data, add=True, now_ms=None):
    """One changeHuoYuedu/huoyuedu call.

    Returns ``{'row', 'changed', 'award', 'push'}`` where ``push`` is the
    91000 payload ``[type_id, data_string, day_total]`` or None. The
    caller persists ``row`` when ``changed``.
    """
    cfg_row = cfg.get(str(type_id))
    if cfg_row is None:
        return {'row': row, 'changed': False, 'award': 0, 'push': None}
    row, reset = clear_day(row, now_ms)
    changed = reset
    try:
        amount = int(data)
    except (TypeError, ValueError):
        amount = 0
    old = counter(row, type_id)
    new = old + amount if add else amount
    row = _set_counter(row, type_id, new)
    if finished(row, type_id):
        # Java returns after the addType write but before cacheUpdate, so
        # the day cells keep their stored value and no 91000 push follows.
        row = _set_counter(row, type_id, old)
        return {'row': row, 'changed': changed, 'award': 0, 'push': None}
    award = 0
    push = None
    if is_finish(cfg_row, new, data):
        row = _add_finish(row, type_id)
        if cfg_row.get('jisuan'):
            award = (new - old) * _int(cfg_row.get('value'))
        else:
            award = _int(cfg_row.get('huoyuezhi'))
        push = [str(type_id), str(data), day_total(cfg, row)]
    elif cfg_row.get('jisuan'):
        award = (new - old) * _int(cfg_row.get('value'))
    if award:
        row['huoyuedu'] = _int(row.get('huoyuedu')) + award
    row['log_update_time'] = _now_ms(now_ms)
    return {'row': row, 'changed': True, 'award': award, 'push': push}


def miaosha(cfg, row, type_id, now_ms=None):
    """miaoSha: pay to jump a daily type to its threshold.

    Returns ``(row, None, award, finished_type)`` on success or
    ``(row, error_code, 0, None)``. The caller does the YB debit and the
    90001 reply; this only mutates the activity cells.
    """
    cfg_row = cfg.get(str(type_id))
    if cfg_row is None or not cfg_row.get('miaosha'):
        return row, ERR_NOT_MIAOSHA, 0, None
    row, _reset = clear_day(row, now_ms)
    current = counter(row, type_id)
    threshold = _int(cfg_row.get('jindu'))
    if current >= threshold:
        return row, ERR_NOT_FINISH, 0, None
    row = _set_counter(row, type_id, threshold)
    row = _add_finish(row, type_id)
    award = _int(cfg_row.get('huoyuezhi'))
    row['huoyuedu'] = _int(row.get('huoyuedu')) + award
    row['log_update_time'] = _now_ms(now_ms)
    return row, None, award, str(type_id)


def claim_error(cfg_table, row, reward_id, total=None):
    """jiangLi's gate sequence (bag capacity is checked by the caller)."""
    if not can_claim(row):
        return ERR_HAS_CLAIMED
    if str(reward_id) in claims(row):
        return ERR_HAS_CLAIMED
    cfg_row = cfg_table.get(str(reward_id))
    if cfg_row is None:
        return None
    if total is None:
        total = 0
    if int(total) < _int(cfg_row.get('huoyue')):
        return ERR_HUOYUE_NOT_ENOUGH
    return None


def add_claim(row, reward_id):
    """Append a claimed reward id (meiriJiangli)."""
    ids = claims(row)
    ids.append(str(reward_id))
    row['meiri_jiangli'] = json.dumps(ids)
    return row


# -- ranks -------------------------------------------------------------

def rank_ids(table):
    """Configured xianjie ids in numeric order."""
    return sorted((str(key) for key in (table or {})), key=_id_key)


def rank_owned(row):
    """The owned rank ids from xianjie_id (JSON array)."""
    ids = []
    for value in _json_array((row or {}).get('xianjie_id')):
        ids.append(str(value))
    return ids


def active_rank(row):
    """xianjie_qiyong: the selected rank, or Java's string-maximum."""
    if row is None:
        return None
    stored = row.get('xianjie_qiyong')
    if stored not in (None, ''):
        return str(stored)
    return max(rank_owned(row)) if rank_owned(row) else '1'


def rank_upgrade_error(table, row, rank_id, activity):
    """upgradeChengHao gates: previous owned, not owned, config, activity."""
    rank_id = str(rank_id)
    cfg_row = (table or {}).get(rank_id)
    if rank_id != '1' and str(int(rank_id) - 1) not in rank_owned(row):
        return CH_ERR_PREV
    if rank_id in rank_owned(row):
        return CH_ERR_HAS
    if cfg_row is None:
        return None
    if int(activity or 0) < _int(cfg_row.get('huoyue')):
        return CH_ERR_HUOYUE
    return None


def add_rank(row, rank_id):
    """Append an owned rank id."""
    ids = rank_owned(row)
    ids.append(str(rank_id))
    row['xianjie_id'] = json.dumps(ids)
    return row


def max_rank(row):
    """The highest owned rank id, or 0 when none (91002's max cell)."""
    ids = rank_owned(row)
    return max((int(i) for i in ids if str(i).isdigit()), default=0)


# -- titles ------------------------------------------------------------

def title_rows(table):
    """chenghao rows in config (numeric) order."""
    return [table[key] for key in sorted(table or {}, key=_id_key)]


def title_types(table):
    """limit1 -> rows, skipping rows without a usable type."""
    out = {}
    for row in title_rows(table):
        try:
            kind = int(row.get('limit1'))
        except (TypeError, ValueError):
            continue
        out.setdefault(kind, []).append(row)
    return out


def cells(row):
    """value1 as a list of ints ('30|0' or 5 or null)."""
    raw = (row or {}).get('value1')
    if raw is None or raw == '':
        return []
    if isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        parts = str(raw).split('|')
    out = []
    for part in parts:
        try:
            out.append(int(str(part).strip() or 0))
        except (TypeError, ValueError):
            out.append(0)
    return out


def _cell(values, index):
    return values[index] if index < len(values) else 0


def title_condition(kind, values, ctx, row=None):
    """ischeck over one title: Java's exact comparisons and quirks.

    ``ctx`` carries the live cells; a missing key is 0, which is the
    Java null-source default for systems that are not ported yet. The
    type-27 branch needs the title's own ``value2`` task ids, passed as
    ``row``.
    """
    v = values
    if kind == 1:
        return int(ctx.get('sign_in_total') or 0) >= _cell(v, 0)
    if kind == 2:
        return (int(ctx.get('bag_used') or 0) >= _cell(v, 0)
                and int(ctx.get('storage_used') or 0) >= _cell(v, 1))
    if kind == 3:
        return (int(ctx.get('store_buy') or 0) >= _cell(v, 0)
                and int(ctx.get('store_sell') or 0) >= _cell(v, 1)
                and int(ctx.get('store_back') or 0) >= _cell(v, 2))
    if kind == 4:
        return int(ctx.get('onhook_minutes') or 0) >= _cell(v, 0)
    if kind == 5:
        # Strict '>' on the monster counter, '>=' on the other two.
        return (int(ctx.get('kill_monster') or 0) > _cell(v, 0)
                and int(ctx.get('kill_ghost') or 0) >= _cell(v, 1)
                and int(ctx.get('kill_god') or 0) >= _cell(v, 2))
    if kind == 6:
        return (int(ctx.get('friend_count') or 0) >= _cell(v, 0)
                and int(ctx.get('foe_count') or 0) >= _cell(v, 1))
    if kind == 7:
        return (int(ctx.get('zuoqi_rank') or 0) >= _cell(v, 0)
                and int(ctx.get('zuoqi_books') or 0) >= _cell(v, 1))
    if kind == 8:
        return (int(ctx.get('wing_level') or 0) >= _cell(v, 0)
                and int(ctx.get('wing_books') or 0) >= _cell(v, 1))
    if kind == 9:
        return (bool(ctx.get('shenjiang_done'))
                and int(ctx.get('shenjiang_count') or 0) >= _cell(v, 1))
    if kind == 10:
        return (int(ctx.get('skill_count') or 0) >= _cell(v, 0)
                and int(ctx.get('skill_max') or 0) >= _cell(v, 1))
    if kind == 11:
        return (bool(ctx.get('has_guild'))
                and int(ctx.get('banggong') or 0) >= _cell(v, 1))
    if kind == 12:
        return bool(ctx.get('has_team'))
    if kind == 13:
        return (int(ctx.get('store_yb') or 0) >= _cell(v, 0)
                and int(ctx.get('store_bind') or 0) >= _cell(v, 1))
    if kind == 14:
        return (int(ctx.get('fuben_finish') or 0) >= _cell(v, 0)
                and int(ctx.get('fuben_saodang') or 0) >= _cell(v, 1))
    if kind == 15:
        return (int(ctx.get('task_finish') or 0) >= _cell(v, 0)
                and int(ctx.get('task_tunshi') or 0) >= _cell(v, 1)
                and int(ctx.get('task_miaosha') or 0) >= _cell(v, 2))
    if kind == 16:
        return (int(ctx.get('meiren_count') or 0) >= _cell(v, 0)
                and int(ctx.get('meiren_chanmian') or 0) >= _cell(v, 1))
    if kind == 17:
        return (int(ctx.get('qibing_level') or 0) >= _cell(v, 0)
                and int(ctx.get('qibing_books') or 0) >= _cell(v, 1))
    if kind == 18:
        return (int(ctx.get('gear_worn') or 0) >= _cell(v, 0)
                and int(ctx.get('gear_quality') or 0) >= _cell(v, 1))
    if kind == 19:
        # Strict '>' like condition 5's monster cell.
        return int(ctx.get('fight') or 0) > _cell(v, 0)
    if kind == 20:
        return (int(ctx.get('equip_qianghua') or 0) >= _cell(v, 0)
                and int(ctx.get('gear_seven_star') or 0) >= _cell(v, 1))
    if kind == 21:
        return (int(ctx.get('tanwei_sell') or 0) >= _cell(v, 0)
                and int(ctx.get('tanwei_buy') or 0) >= _cell(v, 1))
    if kind == 22:
        return int(ctx.get('dazuo_minutes') or 0) >= _cell(v, 0)
    if kind == 23:
        # Java compares the cells in swapped order ([1] then [0]).
        return (int(ctx.get('baoshi_count_1') or 0) >= _cell(v, 0)
                and int(ctx.get('baoshi_count_0') or 0) >= _cell(v, 1))
    if kind == 24:
        return (int(ctx.get('popularity_0') or 0) >= _cell(v, 0)
                and int(ctx.get('popularity_1') or 0) >= _cell(v, 1))
    if kind == 25:
        return False
    if kind == 26:
        return (int(ctx.get('sjjd_putong') or 0) >= _cell(v, 0)
                and int(ctx.get('sjjd_vip') or 0) >= _cell(v, 1))
    if kind == 27:
        done = {str(i) for i in ctx.get('finished_task_ids') or []}
        ids = [i for i in str((row or {}).get('value2') or '').split('|')
               if i]
        if not ids:
            return False
        return all(i in done for i in ids)
    return False


def title_owned(row):
    return [str(value) for value in _json_array((row or {}).get('chenhao_id'))]


def title_activate(table, row, kind, ctx):
    """jihuoChengHao for one type: newly eligible title rows, in order.

    ``ctx`` is the same condition context as ``title_condition`` plus
    ``level`` and ``rank_owned``. Returns ``(row, [(cfg_row, award), ...])``;
    the caller saves, pays bind YB, pushes 91006 and broadcasts 91009.
    """
    out = list(title_owned(row))
    granted = []
    if int(ctx.get('level') or 0) < 20:
        return row, granted
    owned_ranks = {str(i) for i in ctx.get('rank_owned') or []}
    for cfg_row in (table or {}).get(kind) or []:
        title_id = str(cfg_row.get('chenghaoid'))
        if title_id in out:
            continue
        values = cells(cfg_row)
        if not values:
            continue
        if str(cfg_row.get('xianjieid')) not in owned_ranks:
            continue
        if not title_condition(kind, values, ctx, cfg_row):
            continue
        out.append(title_id)
        granted.append(cfg_row)
    if granted:
        row = dict(row)
        row['chenhao_id'] = json.dumps(out)
    return row, granted


def data_cells(row):
    """XianJieData (xianjie_data JSON object) with int values."""
    return counters({'huoyuedu_list': (row or {}).get('xianjie_data')})


def change_data(row, field, delta=1):
    """changeData: add delta to one XianJieData counter."""
    table = data_cells(row)
    table[str(field)] = int(table.get(str(field), 0)) + int(delta)
    row = dict(row)
    row['xianjie_data'] = json.dumps(table, sort_keys=True)
    return row


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _id_key(value):
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))

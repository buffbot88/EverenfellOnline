"""Story-dungeon (JuQingFuBen) service helpers: codecs, gates and awards.

Ports JuQingFuBenServiceImpl + JuQingFuBenUtil + the ZuBao drop chain
against dntg_start.jar javap evidence (see docs or commit history for
the method-by-method recovery notes).

Stored cells are JSON, not delimiter strings:
- auto_pass_info: {"onekey":bool,"curid":int,"starttime":ms,"usetime":ms}
- best_passed_info: {chapterId: {"time":ms,"estimate":grade}}
- award_info: [{id:chapter,"pingjia":grade,"time":ms}] (JSON array)
- passed_ids_daily stays 'id:count;...' (MapUtil.map2String); HashMap
  order is nondeterministic in Java, so Python writes sorted entries
  while reading any order.
"""
import json as _json
import random as _random
import time as _time

# JuQingFuBenErrorCode <clinit> values (dntg_start.jar).
ERR_IS_PASS = 83001
ERR_NOT_ACTIVATED = 83002
ERR_NO_ENOUGH_YB = 83003
ERR_NO_ENOUGH_LEVEL = 83004
ERR_IN_COPY = 83005
ERR_NOT_EXIST = 83006
ERR_NO_AWARD = 83007
ERR_IN_SAODANG = 83008
ERR_NO_PASSED = 83009
ERR_NO_AUTOPASS = 83010
ERR_NO_VIP = 83011
ERR_DROP_GOODS = 70007
ERR_YB_LESS = 1002

# Challenge-result types (JuQingFuBenChallengeResultType).
ROLE_WIN = 1
MONSTER_WIN = 2
COPY_EXPIRE3 = 3

# Mail subject for bag-overflow reward mail (BusMsgCodeUtil international
# key juqing_subject in Language.jat).
JUQING_SUBJECT = 'ด่านเรื่องราว'


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


def _loads_array(cell):
    """Parse a JSON array cell, or None when empty/broken."""
    text = str(cell or '').strip()
    if not text:
        return None
    try:
        arr = _json.loads(text)
    except (TypeError, ValueError):
        return None
    return arr if isinstance(arr, list) else None


def _dump(obj):
    """Compact JSON like fastjson JSONObject.toString (no spaces)."""
    return _json.dumps(obj, separators=(',', ':'))


def parse_counts(cell):
    """'id:count;...' daily map, tolerant of order and blanks."""
    out = {}
    for part in str(cell or '').split(';'):
        part = part.strip()
        if not part or ':' not in part:
            continue
        key, _, val = part.partition(':')
        try:
            out[int(key.strip())] = int(val.strip())
        except (TypeError, ValueError):
            continue
    return out


def format_counts(mapping):
    """Daily map back to a string (sorted; Java HashMap order is random)."""
    return ';'.join(f'{k}:{mapping[k]}' for k in sorted(mapping))


def set_count(cell, chapter_id, count):
    """Overwrite one chapter's daily count (addOrUpdatePassedIdDaily)."""
    mapping = parse_counts(cell)
    mapping[int(chapter_id)] = int(count)
    return format_counts(mapping)


def decode_auto(cell):
    """AutoPassVo fields, or None when no sweep is running.

    Java decodeAutoSaodang returns null only for empty/broken cells; a
    sweep counts as running only when curid is present (checkCanSaodang
    tests autoVo != null && getCurId() != null).
    """
    obj = _loads_obj(cell)
    if obj is None:
        return None
    try:
        return {'onekey': bool(obj.get('onekey')),
                'curid': int(obj['curid']) if obj.get('curid') is not None
                else None,
                'start': int(obj.get('starttime') or 0),
                'usetime': int(obj.get('usetime') or 0)}
    except (TypeError, ValueError):
        return None


def encode_auto(onekey, chapter_id, start_ms, usetime_ms=0):
    """AutoPassVo back to its info string (fastjson key order)."""
    return _dump({'onekey': bool(onekey), 'curid': int(chapter_id),
                  'starttime': int(start_ms), 'usetime': int(usetime_ms)})


def sweep_remain_ms(auto, fast_ms, now_ms):
    """Millis left on a sweep (offlineAutoFightHandle/finishAutoPass)."""
    return int(fast_ms) - int(auto.get('usetime') or 0) - \
        (int(now_ms) - int(auto.get('start') or 0))


def decode_best(cell, chapter_id):
    """BestPassVo for one chapter, or None when never cleared fast."""
    obj = _loads_obj(cell)
    if obj is None:
        return None
    inner = obj.get(str(chapter_id))
    if isinstance(inner, str):
        try:
            inner = _json.loads(inner)
        except (TypeError, ValueError):
            return None
    if not isinstance(inner, dict):
        return None
    try:
        return {'challenge': int(chapter_id),
                'pingjia': int(inner.get('estimate')),
                'fast': int(inner.get('time'))}
    except (TypeError, ValueError):
        return None


def best_time_rows(cell):
    """decodeBestPassTime: [[chapterKey, time, estimate]] in stored order.

    fastjson keySet preserves insertion order and the key stays a String.
    """
    obj = _loads_obj(cell)
    if obj is None:
        return None
    rows = []
    for key, inner in obj.items():
        if isinstance(inner, str):
            try:
                inner = _json.loads(inner)
            except (TypeError, ValueError):
                continue
        if not isinstance(inner, dict):
            continue
        rows.append([key, inner.get('time'), inner.get('estimate')])
    return rows


def merge_best(cell, chapter_id, clear_ms, pingjia):
    """handleBestPassInfo: independent fastest-time / best-grade minimums."""
    obj = _loads_obj(cell) or {}
    inner = obj.get(str(chapter_id))
    if isinstance(inner, str):
        try:
            inner = _json.loads(inner)
        except (TypeError, ValueError):
            inner = None
    if not isinstance(inner, dict):
        inner = {}
    try:
        old_time = inner.get('time')
        old_time = int(old_time) if old_time is not None else None
    except (TypeError, ValueError):
        old_time = None
    try:
        old_est = inner.get('estimate')
        old_est = int(old_est) if old_est is not None else None
    except (TypeError, ValueError):
        old_est = None
    if old_time is None or int(clear_ms) < old_time:
        inner['time'] = int(clear_ms)
    if old_est is None or int(pingjia) < old_est:
        inner['estimate'] = int(pingjia)
    obj[str(chapter_id)] = inner
    return _dump(obj)


def is_passed_today(daily_cell, chapter_id):
    """True when the chapter cleared since the last daily refresh."""
    return int(chapter_id) in parse_counts(daily_cell)


def is_activated(highest, chapter_id):
    """Passed-highest covers the chapter (null highest never does)."""
    return highest is not None and int(highest) >= int(chapter_id)


def is_next_activate(highest, chapter_id):
    """Next unpassed chapter: (highest or 0) + 1 == id."""
    return (int(highest) if highest is not None else 0) + 1 == \
        int(chapter_id)


def check_can_challenge(cfg_row, level, highest, daily_cell, in_copy):
    """checkCanChallenge gate order; None when the entry is allowed."""
    if cfg_row is None:
        return ERR_NOT_EXIST
    if int(level or 0) < int(cfg_row.get('open_level') or 0):
        return ERR_NO_ENOUGH_LEVEL
    if in_copy:
        return ERR_IN_COPY
    if is_passed_today(daily_cell, cfg_row['id']):
        return ERR_IS_PASS
    if not is_activated(highest, cfg_row['id']) and not is_next_activate(
            highest, cfg_row['id']):
        return ERR_NOT_ACTIVATED
    return None


def check_can_saodang(cfg_row, auto, best, daily_cell, onekey, vip_level):
    """checkCanSaodang gate order; None when the sweep may start."""
    if onekey and int(vip_level or 0) <= 0:
        return ERR_NO_VIP
    if cfg_row is None:
        return ERR_NOT_EXIST
    if auto is not None and auto.get('curid') is not None:
        return ERR_IN_SAODANG
    if best is None or best.get('fast') is None:
        return ERR_NO_PASSED
    if is_passed_today(daily_cell, cfg_row['id']):
        return ERR_IS_PASS
    return None


def rating_for(clear_ms, cutoffs):
    """getTimePingjia: raw millis vs the pingjia1/2/3 cutoffs.

    Java compares the millisecond cost directly against the cutoffs, so
    with the shipped 180/300/600 data every real clear grades 4; the
    comparison is kept verbatim rather than "fixed" to seconds.
    """
    try:
        ms = int(clear_ms)
        c1, c2, c3 = (int(c) for c in list(cutoffs)[:3])
    except (TypeError, ValueError):
        return 4
    if ms <= c1:
        return 1
    if ms <= c2:
        return 2
    if ms <= c3:
        return 3
    return 4


def dead_rating(deaths):
    """getDeadPingjia: 0 deaths grade 1, 1 death grade 2, 2 deaths 3."""
    try:
        deaths = int(deaths)
    except (TypeError, ValueError):
        return 4
    if deaths <= 0:
        return 1
    if deaths == 1:
        return 2
    if deaths == 2:
        return 3
    return 4


def victory_pingjia(clear_ms, cutoffs, deaths):
    """challengeResult grade: min(time grade, dead grade)."""
    return min(rating_for(clear_ms, cutoffs), dead_rating(deaths))


def pass_awards(cfg_row, level, factor):
    """passAwards exp/yxb/zhenqi: (level*factor + factor1) * odds."""
    lvl = float(level or 0)
    exp = int((lvl * float(cfg_row.get('exp_factor') or 0.0)
               + float(cfg_row.get('exp_base') or 0.0)) * float(factor))
    yxb = int((lvl * float(cfg_row.get('yxb_factor') or 0.0)
               + float(cfg_row.get('yxb_base') or 0.0)) * float(factor))
    zhenqi = int((lvl * float(cfg_row.get('zhenqi_factor') or 0.0)
                  + float(cfg_row.get('zhenqi_base') or 0.0))
                 * float(factor))
    return {'exp': max(exp, 0), 'yxb': max(yxb, 0),
            'zhenqi': max(zhenqi, 0)}


def award_entries(cell):
    """awardInfoAll: [(index, chapter, pingjia, ms)] in stored order."""
    arr = _loads_array(cell)
    if not arr:
        return []
    out = []
    for idx, entry in enumerate(arr):
        if not isinstance(entry, dict):
            continue
        try:
            pingjia = entry.get('pingjia')
            out.append([idx, int(entry.get('id')),
                        int(pingjia) if pingjia is not None else 4,
                        int(entry.get('time'))])
        except (TypeError, ValueError):
            continue
    return out


def award_info_shapes(cell):
    """getAwardInfo rows: [[chapterId, pingjia]] in stored order."""
    return [[cid, pingjia] for _, cid, pingjia, _ in award_entries(cell)]


def award_incr(cell, chapter_id, pingjia, now_ms=None):
    """Append one pending award entry (awardInfoIncr)."""
    arr = _loads_array(cell) or []
    arr.append({'id': int(chapter_id), 'pingjia': int(pingjia),
                'time': int(now_ms if now_ms is not None
                            else _time.time() * 1000)})
    return _dump(arr)


def award_decr(cell, index):
    """Remove one claimed award by position; (cell, entry|None)."""
    arr = _loads_array(cell)
    if arr is None:
        return cell, None
    try:
        idx = int(index)
    except (TypeError, ValueError):
        return cell, None
    if idx < 0 or idx >= len(arr):
        return cell, None
    entry = arr.pop(idx)
    if not arr:
        return '', entry
    return _dump(arr), entry


def daily_info_rows(daily_cell):
    """convertDailyPassInfo2Array: sorted [[id, count]] pairs."""
    return [[k, v] for k, v in sorted(parse_counts(daily_cell).items())]


def random_key2(weighted, rng=None):
    """Lottery.getRandomKey2: weighted pick over an insertion-ordered map.

    roll = rand(total * 10000); first entry with lo*10000 <= roll <
    hi*10000 wins; None when empty or the total is 0.
    """
    items = [(k, float(v)) for k, v in dict(weighted).items()]
    total = sum(v for _, v in items)
    if not items or total <= 0:
        return None
    source = rng if rng is not None else _random
    roll = source.randrange(int(total * 10000))
    low = 0.0
    for key, weight in items:
        high = low + weight
        if low * 10000 <= roll < high * 10000:
            return key
        low = high
    return None


def zubao_active(row):
    """ZuBaoConfig.isDropNow with the shipped data: no time columns are
    ever parsed into the config, so every group is always droppable."""
    return True


def zubao_group_entries(row):
    """Parse one ZuBaoDiaoLuoBiao row: [(goodsId, count, rate)]."""
    entries = []
    for idx in range(1, 77):
        gid = row.get(f'drop{idx}')
        if gid is None or not str(gid).strip():
            continue
        text = str(gid).strip()
        parts = text.split(':')
        goods_id = parts[0].strip()
        try:
            count = int(parts[1]) if len(parts) > 1 else 1
        except (TypeError, ValueError):
            count = 1
        try:
            rate = float(row.get(f'drop{idx}Odds') or 0)
        except (TypeError, ValueError):
            rate = 0.0
        if goods_id:
            entries.append([goods_id, count, rate])
    return entries


def zubao_roll(zubao_table, drop_id, rng=None):
    """componentRoll: resolve one (possibly nested @group) drop id.

    Returns (goodsId, count, rate) or None when the group is inactive
    or unconfigured. Nested @groups recurse like Java.
    """
    row = (zubao_table or {}).get(str(drop_id))
    if row is None or not zubao_active(row):
        return None
    entries = zubao_group_entries(row)
    if not entries:
        return None
    pick = random_key2({i: e[2] for i, e in enumerate(entries)}, rng=rng)
    if pick is None:
        entry = entries[0]
    else:
        entry = entries[pick]
    if entry[0].startswith('@'):
        return zubao_roll(zubao_table, entry[0], rng=rng)
    return entry


def convert_item(goods_row, goods_id, count, bind=0, expire_ms=0,
                 rare_level=None, item_level=None):
    """ItemCreatorServiceImpl.convert2ItemModel for one stackable good.

    Returns a list of ItemModel-ish dicts after controlGoodsStack
    splitting, or [] when the goods id is unconfigured (Java: null).
    Equip/zuoqi generation is out of scope: no shipped JuQing drop
    chain yields equipment, so those categories raise through the
    caller's normal equip path instead of being invented here.
    """
    if goods_row is None:
        return []
    try:
        max_stack = int(goods_row.get('maxstack') or 0)
    except (TypeError, ValueError):
        max_stack = 0
    try:
        count = int(count)
    except (TypeError, ValueError):
        return []
    if count <= 0:
        return []
    if goods_row.get('obtainlocked'):
        try:
            locked = int(str(goods_row.get('obtainlocked')).strip() or 0)
        except (TypeError, ValueError):
            locked = 0
        if locked:
            bind = 1
    elif int(bind or 0) != 1:
        bind = 0
    try:
        rare = int(rare_level) if rare_level is not None \
            else int(goods_row.get('rarelevel') or 0)
    except (TypeError, ValueError):
        rare = 0
    try:
        ilevel = int(item_level) if item_level is not None \
            else int(goods_row.get('itemlevel') or 0)
    except (TypeError, ValueError):
        ilevel = 0
    if max_stack > 0 and count > max_stack:
        full, rest = divmod(count, max_stack)
        counts = [max_stack] * full + ([rest] if rest else [])
    else:
        counts = [count]
    return [{'goods_id': str(goods_id), 'count': n, 'bind': int(bind),
             'expire_time': int(expire_ms), 'rare_level': rare,
             'item_level': ilevel} for n in counts]


def roll_models(goods_table, zubao_table, drop_id, fujia, roll_bind,
                rng=None):
    """passAwards roll: rollItems(dropId, equipFujiaMap) model list.

    Each rolled ZuBao entry becomes ItemParamVo(goodsId, count) with the
    chapter fujia params applied, converted with stack splitting and
    stamped with the chapter roll bind (ItemModel.setId(i) ordering is
    the table order, matching Java's per-model id assignment).
    """
    if not drop_id:
        return []
    picked = zubao_roll(zubao_table, drop_id, rng=rng)
    if picked is None:
        return []
    goods_id, count, _rate = picked
    models = convert_item((goods_table or {}).get(str(goods_id)),
                          goods_id, count, bind=roll_bind)
    for idx, model in enumerate(models):
        model['id'] = str(idx)
    return models

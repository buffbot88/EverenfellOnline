"""Story-dungeon (JuQingFuBen) service helpers: codecs, gates and awards.

Ports JuQingFuBenServiceImpl + JuQingFuBenUtil against dntg_start.jar
javap evidence. Stored strings use the Java separators (';' entries,
':' key/values, keys onekey/curid/starttime/usetime, id/pingjia/time
for best rows); HashMap iteration order is internal-only, so Python
writes sorted entries while reading any order.
"""
import json as _json
import time as _time

# JuQingFuBenErrorCode clinit values.
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
    """Daily map back to a string (sorted for determinism)."""
    return ';'.join(f'{k}:{mapping[k]}' for k in sorted(mapping))


def add_or_update_counts(cell, chapter_id, delta):
    """Add delta to one chapter's daily count (never negative)."""
    mapping = parse_counts(cell)
    mapping[int(chapter_id)] = max(mapping.get(int(chapter_id), 0) + delta, 0)
    return format_counts(mapping)


def parse_codemap(cell):
    """'k=v;...' helper for auto/best/award info strings."""
    out = {}
    for part in str(cell or '').split(';'):
        part = part.strip()
        if not part or '=' not in part:
            continue
        key, _, val = part.partition('=')
        out[key.strip()] = val.strip()
    return out


def format_codemap(mapping):
    """Helper map back to a string (sorted for determinism)."""
    return ';'.join(f'{k}={mapping[k]}' for k in sorted(mapping))


def decode_auto(cell):
    """AutoPassVo fields, or None when no sweep is running.

    Java stores `usetime` as a plain seconds string, not a codemap key.
    """
    text = str(cell or '').strip()
    if not text:
        return None
    parts = text.split(';')
    head = parts[0]
    info = parse_codemap(head) if '=' in head else {}
    chapters = [p for p in parts[1:] if p]
    if not info.get('curid') and not chapters:
        return None
    try:
        out = {'onekey': info.get('onekey') == '1',
               'curid': int(info['curid']) if info.get('curid') else 0,
               'start': int(info.get('starttime') or 0),
               'chapters': [int(c) for c in chapters],
               'usetime': parts[-1] if len(parts) > 1 else None}
    except (TypeError, ValueError):
        return None
    try:
        out['usetime'] = int(out['usetime']) if out['usetime'] else 0
    except (TypeError, ValueError):
        return None
    return out


def encode_auto(onekey, chapter_id, start_ms, usetime=0):
    """AutoPassVo back to its info string (Java: head + `;curid` + `;usetime`)."""
    head = format_codemap({'onekey': '1' if onekey else '0',
                           'curid': str(int(chapter_id)),
                           'starttime': str(int(start_ms))})
    return f'{head};{int(chapter_id)};{int(usetime)}'


def decode_best(cell, chapter_id):
    """BestPassVo for one chapter, or None when never cleared fast."""
    for part in str(cell or '').split(';'):
        cells = part.split(':')
        if len(cells) >= 3:
            try:
                cid = int(cells[0])
            except (TypeError, ValueError):
                continue
            if cid == int(chapter_id):
                try:
                    return {'challenge': cid, 'pingjia': int(cells[1]),
                            'fast': int(cells[2])}
                except (TypeError, ValueError):
                    return None
    return None


def encode_best(rows):
    """Best rows [(chapter, pingjia, ms)] back to the info string."""
    parts = []
    for cid, pingjia, ms in sorted(rows):
        parts.append(f'{int(cid)}:{int(pingjia)}:{int(ms)}')
    return ';'.join(parts)


def merge_best(cell, chapter_id, pingjia, clear_ms):
    """Keep the fastest clear per chapter (handleBestPassInfo)."""
    rows = []
    seen = False
    for part in str(cell or '').split(';'):
        cells = part.split(':')
        if len(cells) < 3:
            continue
        try:
            cid, old_p, old_ms = int(cells[0]), int(cells[1]), int(cells[2])
        except (TypeError, ValueError):
            continue
        if cid == int(chapter_id):
            seen = True
            if int(clear_ms) < old_ms:
                rows.append((cid, int(pingjia), int(clear_ms)))
            else:
                rows.append((cid, old_p, old_ms))
        else:
            rows.append((cid, old_p, old_ms))
    if not seen:
        rows.append((int(chapter_id), int(pingjia), int(clear_ms)))
    return encode_best(rows)


def is_passed_today(daily_cell, chapter_id):
    """True when the chapter already cleared today."""
    return int(chapter_id) in parse_counts(daily_cell)


def is_activated(highest, chapter_id):
    """Passed-highest covers the chapter (null highest never does)."""
    return highest is not None and int(highest) >= int(chapter_id)


def is_next_activate(highest, chapter_id):
    """Next unpassed chapter: (highest or 0) + 1 == id."""
    return (int(highest) if highest is not None else 0) + 1 == int(chapter_id)


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
    if auto is not None:
        return ERR_IN_SAODANG
    if best is None or best.get('fast') is None:
        return ERR_NO_PASSED
    if is_passed_today(daily_cell, cfg_row['id']):
        return ERR_IS_PASS
    return None


def rating_for(clear_ms, cutoffs):
    """getTimePingjia: faster clears earn the lower (better) grade 1-4."""
    secs = float(clear_ms) / 1000.0
    try:
        c1, c2, c3 = [float(c) for c in list(cutoffs)[:3]]
    except (TypeError, ValueError):
        return 4
    if secs <= c1:
        return 1
    if secs <= c2:
        return 2
    if secs <= c3:
        return 3
    return 4


def dead_rating(deaths):
    """getDeadPingjia: 0 deaths grade 1, 1 death grade 2, else worse."""
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


def pass_awards(cfg_row, level, factor):
    """passAwards exp/yxb/zhenqi from the factor cells and level."""
    lvl = float(level or 0)
    exp = int((lvl * float(cfg_row.get('exp_factor') or 0.0)
               + float(cfg_row.get('exp_base') or 0.0)) * float(factor))
    yxb = int((lvl * float(cfg_row.get('yxb_factor') or 0.0)
               + float(cfg_row.get('yxb_base') or 0.0)) * float(factor))
    zf = (lvl * float(cfg_row.get('zhenqi_factor') or 0.0)
          + float(cfg_row.get('zhenqi_base') or 0.0))
    zhenqi = int(zf * float(factor))
    return {'exp': max(exp, 0), 'yxb': max(yxb, 0),
            'zhenqi': max(zhenqi, 0)}


def award_entries(cell):
    """awardInfoAll rows as [(index, chapter, pingjia, ms)] lists."""
    out = []
    for part in str(cell or '').split(';'):
        cells = part.split(':')
        if len(cells) >= 4:
            try:
                out.append([int(cells[0]), int(cells[1]), int(cells[2]),
                            int(cells[3])])
            except (TypeError, ValueError):
                continue
    return out


def award_incr(cell, chapter_id, pingjia, now_ms=None):
    """Append one pending award entry (awardInfoIncr)."""
    rows = award_entries(cell)
    nxt = max([r[0] for r in rows] + [0]) + 1
    rows.append([nxt, int(chapter_id), int(pingjia),
                 int(now_ms if now_ms is not None else _time.time() * 1000)])
    return ';'.join(':'.join(str(v) for v in r) for r in rows)


def award_decr(cell, index):
    """Remove one claimed award entry; None when the index is absent."""
    rows = [r for r in award_entries(cell) if r[0] != int(index)]
    if len(rows) == len(award_entries(cell)):
        return None
    return ';'.join(':'.join(str(v) for v in r) for r in rows)


def daily_info_rows(daily_cell):
    """convertDailyPassInfo2Array: sorted [[id, count]] pairs."""
    return [[k, v] for k, v in sorted(parse_counts(daily_cell).items())]


def best_time_rows(best_cell):
    """decodeBestPassTime: sorted [[id, pingjia, ms]] rows."""
    rows = []
    for part in str(best_cell or '').split(';'):
        cells = part.split(':')
        if len(cells) >= 3:
            try:
                rows.append([int(cells[0]), int(cells[1]), int(cells[2])])
            except (TypeError, ValueError):
                continue
    return sorted(rows)


def challenge_entry_frames(cfg_row):
    """SC:APPLY_COPY equivalent: dungeon map + role position + chapter."""
    pos = cfg_row.get('pos') or []
    return [str(cfg_row.get('map') or ''), pos[0] if len(pos) > 0 else 0,
            pos[1] if len(pos) > 1 else 0, [cfg_row.get('id')]]

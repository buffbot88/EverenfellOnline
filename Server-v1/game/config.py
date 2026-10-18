"""Loaders for the legacy binary config tables the Java server reads.

  sys_config/MapLine.jat     -> per-map MapLineConfig rows (maptype, maxlinevalue, ...)
  map_config/<id>/monster.mm -> per-map monster spawn groups

Both are AMF3 serialized (see amf3.py). The loader is read-only and never
edits the tables; it only reports what the legacy server would load.
"""
import json
import logging
import os
import random
import re
import struct

from .amf3 import decode as amf3_decode

log = logging.getLogger('config')

# Default location of the legacy config tree, relative to Server-v1/ (where the
# server is normally started). The tree is gitignored, so it is passed explicitly
# via --config-dir when it lives elsewhere.
DEFAULT_CONFIG_DIR = os.path.join('..', 'reference', 'TonNgoKhong', 'server',
                                  'config', 'game')


def _load(path):
    with open(path, 'rb') as f:
        return amf3_decode(f.read())


def load_map_lines(path):
    """Return {str(mapid): row} from MapLine.jat; row keys are the Java field names."""
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of MapLine rows')
    table = {}
    for row in rows:
        if isinstance(row, dict) and row.get('mapid') is not None:
            table[str(row['mapid'])] = row
    return table


def load_task_main_table(path):
    """Main-quest row list from sys_config/ZhuXianRenWu.jat."""
    rows = _load(path)
    if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], list):
        rows = rows[0]
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of quest rows')
    return rows


def load_taofa_table(path):
    """Return {taofaid: row} from sys_config/taskTaoFaRenWu.jat (the taofa quest list)."""
    rows = _load(path)
    if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], list):
        rows = rows[0]
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of taofa rows')
    table = {}
    for row in rows:
        if isinstance(row, dict) and row.get('taofaid'):
            table[str(row['taofaid'])] = row
    return table


def config_int(value):
    """ConvertObjectUtil.object2int: null/''/garbage -> 0, true -> 1.

    Doubles truncate and NumberFormatException yields 0 (the quest table has
    '#N/A' cells, so this matters).
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    text = str(value).strip()
    if not text:
        return 0
    if text == 'true':
        return 1
    if text == 'false':
        return 0
    if '.' in text:
        text = text[:text.index('.')]
    try:
        return int(text)
    except (TypeError, ValueError):
        return 0


def parse_task_goods(cell):
    """{goods id: count} from a 'gid_count;...' cell; None when empty."""
    if not cell:
        return None
    goods = {}
    for segment in cell.split(';'):
        parts = segment.split('_')
        try:
            goods[parts[0]] = int(parts[1])
        except (IndexError, TypeError, ValueError):
            continue
    return goods or None


def parse_task_monsters(cell):
    """{monster id: vo} from a 'mid:count;...' cell; None when empty.

    A leading 'name_' on the id sets the display name; a '#' marks an
    auto-attack entry; repeat ids accumulate counts (getConfigMonsterMap).
    """
    if not cell:
        return None
    monsters = {}
    for segment in cell.split(';'):
        parts = segment.split(':')
        try:
            raw_id, count = parts[0], int(parts[1])
        except (IndexError, TypeError, ValueError):
            continue
        show_name = None
        if '_' in raw_id:
            show_name, _, raw_id = raw_id.partition('_')
        auto = '#' in raw_id
        monster_id = raw_id.replace('#', '')
        vo = monsters.get(monster_id)
        if vo is None:
            vo = {'monster_id': monster_id, 'count': 0,
                  'auto_attack': False, 'show_name': None}
            monsters[monster_id] = vo
        if vo['show_name'] is None:
            vo['show_name'] = show_name
        vo['count'] += count
        if auto:
            # getConfigMonsterMap only ever sets autoAttack true; a repeat
            # segment without '#' never clears a latched true.
            vo['auto_attack'] = True
    return monsters or None


def parse_task_item_order(cell):
    """[(goods id, count, bind, expire)] from an itemOrder cell.

    Port of convertGoodsesStrs2List2: 'goodsId:count[:bind][:expire]' segments, count <= 0 nulls the list, empty cell gives None.
    """
    if not cell:
        return None
    items = []
    for segment in cell.split(';'):
        parts = segment.split(':')
        try:
            goods_id, count = parts[0], int(parts[1])
        except (IndexError, TypeError, ValueError):
            continue
        if count <= 0:
            return None
        try:
            bind = int(parts[2]) if len(parts) > 2 else 0
        except (TypeError, ValueError):
            bind = 0
        try:
            expire = int(parts[3]) if len(parts) > 3 else 0
        except (TypeError, ValueError):
            expire = 0
        items.append({'goods_id': goods_id, 'count': count,
                      'bind': bind, 'expire': expire if expire > 0 else 0})
    return items


def parse_taofa_monster(cell):
    """Single kill VO from a taofa monster cell, or None when empty.

    Port of getConfigMonsterVo: only the first ';' segment counts, split
    on ':' into (id, count); a 'name_' prefix sets the display name and a
    '#' marks auto-attack (isShowName/isAutoType in TaskConfigUtil).
    """
    if not cell:
        return None
    segment = str(cell).split(';')[0]
    parts = segment.split(':')
    try:
        raw_id, count = parts[0], int(parts[1])
    except (IndexError, TypeError, ValueError):
        return None
    show_name = None
    if '_' in raw_id:
        show_name, _, raw_id = raw_id.partition('_')
    auto = '#' in raw_id
    return {'monster_id': raw_id.replace('#', ''), 'count': count,
            'auto_attack': auto, 'show_name': show_name}


def parse_taofa_items(cell, bind):
    """(goods list, zubao list) from a taofa itemOrder cell.

    Port of the createTaskTaofaConfig itemOrder loop: ';' segments
    starting with '@' land in the zubao ids; the rest become
    (goods id, count, bind) with bind forced from the row's bound cell.
    """
    goods, zubao = [], []
    if not cell:
        return goods, zubao
    for segment in str(cell).split(';'):
        if segment.startswith('@'):
            zubao.append(segment)
            continue
        parts = segment.split(':')
        try:
            goods_id, count = parts[0], int(parts[1])
        except (IndexError, TypeError, ValueError):
            continue
        if not goods_id:
            continue
        goods.append({'goods_id': goods_id, 'count': count,
                      'bind': config_int(bind), 'expire': 0})
    return goods, zubao


def config_float(value):
    """ConvertObjectUtil.object2Float: null/''/garbage -> 0.0."""
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def lottery_roll(count):
    """Lottery.roll: uniform int in [0, count), like Random.nextInt."""
    return random.randrange(count)


# TaskTaoFaConstants / TaskConfigConstants (jar clinit).
TAOFA_MAX_TUNSHI = 5
TAOFA_MAX_USE = 10
TAOFA_MAX_FINISH = 10
TAOFA_RECEIVE_MAX = 20
# TaskRiChangConstants + TaskRCConditionConfigExportServiceImpl costs.
RICHANG_MIN_LEVEL = 40
RICHANG_MAX_LOOP = 20
RICHANG_DIFFICULTY_MAX = 10
RICHANG_THICK_MAX = 10
RICHANG_COST_ONEKEY = 50
RICHANG_COST_ONEKEY_BEST = 100
RICHANG_COST_JIANGDI = 50000
RICHANG_COST_TISHENG = 50000
RICHANG_COST_DIRECT = 10


def richang_condition_interval(buckets, level):
    """TaskConfigUtil.getRichangeConditionLevelInterval: 'min_max' or None.

    The bucket holding the level wins; a miss recurses with level - 10
    (levels at or below 0 give None).
    """
    if level <= 0:
        return None
    for low, high in sorted(buckets.items()):
        if low <= level <= high:
            return f'{low}_{high}'
    return richang_condition_interval(buckets, level - 10)


def richang_reward_interval(buckets, cond_buckets, level):
    """TaskConfigUtil.getRichangeLevelInterval (misses fall into the condition map)."""
    if level <= 0:
        return None
    for low, high in sorted(buckets.items()):
        if low <= level <= high:
            return f'{low}_{high}'
    return richang_condition_interval(cond_buckets, level - 10)


def richang_loop_interval(buckets, cond_buckets, level):
    """TaskConfigUtil.getRichangeLoopLevelInterval (same condition-map fallback)."""
    if level <= 0:
        return None
    for low, high in sorted(buckets.items()):
        if low <= level <= high:
            return f'{low}_{high}'
    return richang_condition_interval(cond_buckets, level - 10)


def parse_task_attr_map(cell):
    """{attribute name: float} from a subchapter reward cell.

    Port of getAttributeConfigMap: 'name:value;...' accumulates floats; empty cell gives None like Java's isEmpty branch.
    """
    if not cell or not str(cell).strip():
        return None
    totals = {}
    for segment in str(cell).split(';'):
        parts = segment.split(':')
        if len(parts) < 2:
            continue
        try:
            value = float(parts[1])
        except (TypeError, ValueError):
            continue
        totals[parts[0]] = totals.get(parts[0], 0.0) + value
    return totals or None


def convert_index_attribute(mapping, index):
    """{attribute id: value} by looking each name up in the index table.

    Port of AttributeConvertIndexUtil.convertIndexAttribute: names resolve to ids via the index. The Java table is a static field nothing ever assigns, so an empty index passes the mapping through instead of Java's NPE.
    """
    if not mapping or not index:
        return mapping
    return {index.get(name): value for name, value in mapping.items()}


# Attribute-index table (names -> wire ids); content unrecoverable, so empty.
TASK_ATTRIBUTE_INDEX = {}


def load_goods_table(path):
    """{goods id: row} from sys_config/goods.jat (outer list holds one list)."""
    rows = _load(path)
    if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], list):
        rows = rows[0]
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of goods rows')
    return {str(r['id']): r for r in rows
            if isinstance(r, dict) and r.get('id') is not None}


def load_kaige_table(path):
    """{(slottype, num): row} from sys_config/KaiGeFeiYongBiao.jat."""
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of kaige rows')
    table = {}
    for row in rows:
        if isinstance(row, dict) and row.get('slottype') is not None \
                and row.get('id') is not None:
            table[(str(row['slottype']), int(row['id']))] = row
    return table


def load_monsters(path):
    """Return the monster spawn records from one monster.mm file (a list of dicts)."""
    records = _load(path)
    if not isinstance(records, list):
        raise ValueError(f'{path}: expected a list of monster records')
    return [r for r in records if isinstance(r, dict)]


# The eight flat attribute columns an equipment row can carry; ZuoQiConfig and
# the attribute pills use the same names (EquipFuJiaAttributeConfig fields).
EQUIP_ATTRIBUTE_NAMES = ('physicdamage', 'physicdefence', 'critical', 'volt',
                         'velocity', 'attackrate', 'hitpoints', 'mana')

_QH_STARS = re.compile(r'"qhxingxing"\s*:\s*"\[(.*?)\]"')
_QH_PAIR = re.compile(r'\[(\d+)\s*,')
_FUJIA_PAIR = re.compile(r'(\d+)@(\d+)')


def _number(value):
    """Config cells hold '' for 'no value'; that is zero, not an error."""
    return 0.0 if value in ('', None) else float(value)


def parse_item_attributes(text):
    """(qh stars, fujia pairs) from a role_equip_slot.attributes blob.

    GoodsEquipVo.getGoodsAttributes reads this JSON; qhxingxing pairs are
    [star, count] and fjattrstr maps a slot to '<fujiaId>@<count>' (Java
    consumes them as Integer[2] pairs). Stored rows sometimes carry a
    backslash-escaped copy of fjattrstr, so this scans the text instead
    of requiring strict JSON.
    """
    text = text or ''
    match = _QH_STARS.search(text)
    stars = [int(s) for s in _QH_PAIR.findall(match.group(1))] if match else []
    pairs = [(int(fid), int(cnt)) for fid, cnt in _FUJIA_PAIR.findall(text)]
    return stars, pairs


def _int(value):
    """Java getIntValue: a missing or non-numeric cell is 0."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _at(entry, index):
    """Element `index` of a JSON pair, 0 when the entry is short or not a list."""
    if isinstance(entry, list) and len(entry) > index:
        return entry[index]
    return 0


def equip_vo(text):
    """GoodsEquipVo(String): qhcount, jjfailcount, qhxingxing, fjattrstr.

    Java reads each key with getIntValue/getString, so a missing key is 0
    or null. A blob that is not JSON is logged and read as blank instead of
    failing the whole frame.
    """
    empty = {'qhcount': 0, 'jjfailcount': 0, 'qhxingxing': None, 'fjattrstr': None}
    if not text:
        return empty
    try:
        data = json.loads(text)
    except ValueError:
        log.warning('equipment attributes are not JSON; read as blank')
        return empty
    if not isinstance(data, dict):
        return empty

    def as_text(value):
        if value is None or isinstance(value, str):
            return value
        return json.dumps(value, separators=(',', ':'))

    return {'qhcount': _int(data.get('qhcount')),
            'jjfailcount': _int(data.get('jjfailcount')),
            'qhxingxing': as_text(data.get('qhxingxing')),
            'fjattrstr': as_text(data.get('fjattrstr'))}


def _goods_map(text):
    """'goods|count[;...]' cell into {goods_id: count}, skips bad pairs."""
    out = {}
    for cell in str(text or '').split(';'):
        gid, _, count = cell.partition('|')
        if not gid:
            continue
        try:
            need = int(count)
        except (TypeError, ValueError):
            continue
        out[gid] = need
    return out


def _qh_pairs(vo):
    """The parsed qhxingxing JSON array, or None when blank or not an array."""
    text = vo.get('qhxingxing')
    if text in (None, ''):
        return None
    try:
        data = json.loads(text)
    except ValueError:
        log.warning('qhxingxing is not JSON; treated as absent')
        return None
    return data if isinstance(data, list) else None


def xingxing_lv(vo):
    """GoodsEquipVo.getxingxingLv: how many star pairs carry the value 1."""
    return sum(1 for entry in (_qh_pairs(vo) or []) if _int(_at(entry, 1)) == 1)


def qh_xingxings_client(vo):
    """GoodsEquipVo.getQhXingXingsClient: qhcount star values, zero-padded.

    qhcount 0 gives ten zeros. Java returns null for a blank qhxingxing
    or when the array has MORE entries than qhcount.
    """
    if vo.get('qhxingxing') in (None, ''):
        return None
    count = vo.get('qhcount') or 0
    if count == 0:
        return [0] * 10
    pairs = _qh_pairs(vo)
    if pairs is None or len(pairs) > count:
        return None
    values = [_at(entry, 1) for entry in pairs]
    return values + [0] * (count - len(values))


def fujia_client_map(vo):
    """GoodsEquipVo.qhFuJiaAttrClient: {fujiaKey: [id, count]} or None.

    Each fjattrstr value is 'id@count'; Java splits it and boxes both halves
    as Integers.
    """
    text = vo.get('fjattrstr')
    if text in (None, ''):
        return None
    try:
        data = json.loads(text)
    except ValueError:
        log.warning('fjattrstr is not JSON; treated as absent')
        return None
    if not isinstance(data, dict):
        return None
    out = {}
    for key, value in data.items():
        parts = str(value).split('@')
        if len(parts) < 2:
            log.warning('fjattrstr entry %r is not id@count; skipped', key)
            continue
        out[str(key)] = [_int(parts[0]), _int(parts[1])]
    return out


def load_equip_attribute_table(path):
    """Rows of sys_config/ZhuangBeiFuJiaShuXingBiao.jat keyed by goods id.

    This is EquipFuJiaAttributeConfig: the flat base columns, the Njichubili
    rank rates and the starN<attr> enhancement (qianghua) columns EquipAttributeService reads.
    """
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of equipment rows')
    return {str(r['id']): r for r in rows if isinstance(r, dict) and r.get('id')}


def load_fujia_random_table(path):
    """Rows of ZhuangBeiFuJiaShuXingsuijiBiao.jat keyed by 'fujiaid-level'.

    Java keys EquipRandomConfig as str(fujiaid) + '-' + str(level)
    (EquipFuJiaRandomConfigExportServiceImpl.getKey); each row carries the
    shuxing bag key and its per-count value.
    """
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of fujia random rows')
    table = {}
    for row in rows:
        if not isinstance(row, dict) or row.get('fujiaid') is None \
                or row.get('level') is None:
            continue
        table['%s-%s' % (row['fujiaid'], row['level'])] = row
    return table


# WuPinChuShouBiao price column per MoneyType intType (the cost-map
# builder reads exactly one column per row: YXB=1 coin, YB=2 gold,
# BIND_YB=3 bindgole, BANGGONG=5 banggong).
MALL_PRICE_COLUMNS = {1: 'coin', 2: 'gold', 3: 'bindgole',
                      5: 'banggong'}


def load_mall_table(path):
    """Rows of sys_config/WuPinChuShouBiao.jat grouped by modelid, pages sorted.

    Java groups rows into WuPinChuShouCategoryConfig per modelId with items
    bucketed by page (WuPinChuShouConfigExportServiceImpl.configureDataResolve
    + addWupinChuShou); getAllData flattens the page buckets. Pages sort
    ascending, matching HashMap<Integer,List> bucket order for small ints.
    """
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of mall rows')
    cats = {}
    for row in rows:
        if not isinstance(row, dict) or row.get('modelid') is None:
            continue
        cats.setdefault(str(row['modelid']), {}).setdefault(
            int(row.get('page') or 0), []).append(row)
    return {model: [row for page in sorted(pages) for row in pages[page]]
            for model, pages in cats.items()}


def parse_att_string(text):
    """'k:v;k:v' attribute string into {key: float}.

    Port of XianJieExportServiceImpl/ChengHaoExportServiceImpl.getattMap:
    split on ';', then on ':', Float values. Unparseable pairs are skipped
    instead of faked (the shipped tables are clean; garbage must not
    become attributes).
    """
    table = {}
    for part in str(text or '').split(';'):
        part = part.strip()
        if not part or ':' not in part:
            continue
        key, _, value = part.partition(':')
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if key.strip():
            table[key.strip()] = number
    return table


# ConfigAttributeParser.attribute2Map(Map)'s key universe (jar bytecode):
# the flat cells a meiren.jat row can contribute to its attribute map.
MEIREN_ATTRIBUTE_NAMES = ('hitpoints', 'mana', 'physicdamage', 'physicdefence',
                          'critical', 'volt', 'attackrate', 'velocity', 'dodge',
                          'dodgedefence', 'mb', 'mbdk', 'yx', 'yxdk', 'bh',
                          'bhdk', 'xx', 'xxdk', 'dunshudian', 'criticalb',
                          'criticalc', 'pojia', 'qiege', 'jiangu', 'shishen',
                          'shenyou', 'damage', 'defence', 'perdamage',
                          'redamage', 'reph', 'leidamage', 'leidefence',
                          'mudamage', 'mudefence', 'shuidamage', 'shuidefence',
                          'huodamage', 'huodefence', 'tudamage', 'tudefence')


def load_xianjie_table(path):
    """Rows of sys_config/xianjie.jat keyed by id."""
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of xianjie rows')
    return {str(r['id']): r for r in rows
            if isinstance(r, dict) and r.get('id') is not None}


def load_chenghao_table(path):
    """Rows of sys_config/chenghao.jat keyed by chenghaoid."""
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of chenghao rows')
    return {str(r['chenghaoid']): r for r in rows
            if isinstance(r, dict) and r.get('chenghaoid') is not None}


def load_meiren_table(path):
    """Rows of sys_config/meiren.jat as ({meinvid: (type, level)},
    {type: {level: attribute map}}).

    Mirrors MeiRenConfigExportServiceImpl: each row becomes a MeiRenConfig
    whose attribtueMap is ConfigAttributeParser.attribute2Map(row), keyed
    into its type's meirenLevelMap by meinvlv; the type key is meinvtype
    (MeiRenTypeConfig's primary key, the id replaceMeirenAttribute looks
    up with the business object's type id).
    """
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of meiren rows')
    by_id, types = {}, {}
    for row in rows:
        if not isinstance(row, dict) or row.get('meinvid') is None:
            continue
        try:
            level = int(row.get('meinvlv') or 0)
        except (TypeError, ValueError):
            continue
        bag = {name: _number(row.get(name)) for name in MEIREN_ATTRIBUTE_NAMES
               if _number(row.get(name))}
        by_id[str(row['meinvid'])] = (str(row.get('meinvtype') or ''), level)
        types.setdefault(str(row.get('meinvtype') or ''), {})[level] = bag
    return by_id, types


def load_zuwu_table(path):
    """Rows of sys_config/ZuWuShuxing.jat as {type: first jieshu==1 id}.

    Java's typeIdMaps keeps the first row per type whose jieshu cell is 1
    (ZuwuShuxingConfigExportServiceImpl.configureDataResolve); 111000
    mocks one [id,0,0,0,type] entry per map member for unowned types.
    """
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of zuwu rows')
    table = {}
    for row in rows:
        if not isinstance(row, dict) or row.get('type') is None \
                or row.get('id') is None:
            continue
        try:
            kind, jieshu = int(row['type']), int(row.get('jieshu') or 0)
        except (TypeError, ValueError):
            continue
        if jieshu == 1 and kind not in table:
            table[kind] = str(row['id'])
    return table


def load_xishu_table(path):
    """Rows of sys_config/ZhanLiXiShu.jat as {attrName: factor}."""
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of zhanli xishu rows')
    return {str(r['name']): float(r['factor']) for r in rows
            if isinstance(r, dict) and r.get('name') is not None
            and r.get('factor') is not None}


def load_dazuo_table(path):
    """Rows of sys_config/DaZuoPeiZhiBiao.jat as {level: {'exp': {k: n}, 'zhenqi': {k: n}}}."""
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of dazuo rows')
    table = {}
    for r in rows:
        if not isinstance(r, dict) or r.get('level') is None:
            continue
        table[int(r['level'])] = {
            'exp': {k: int(r.get(f'exp{k}') or 0) for k in range(1, 5)},
            'zhenqi': {k: int(r.get(f'zhenqi{k}') or 0) for k in range(1, 5)}}
    return table


def load_vip_table(path):
    """Rows of sys_config/vipbiao.jat keyed by vip level."""
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of vip rows')
    return {int(r['lv']): r for r in rows
            if isinstance(r, dict) and r.get('lv') is not None}


def load_vipqq_rewards(path):
    """Parcels of sys_config/chaojihuiyuan.jat row 1 (jiangpin1 cell)."""
    rows = _load(path)
    if not isinstance(rows, list) or not rows:
        raise ValueError(f'{path}: expected a non-empty rewards list')
    first = rows[0]
    if not isinstance(first, dict) or not first.get('jiangpin1'):
        raise ValueError(f'{path}: expected a jiangpin1 cell')
    return first['jiangpin1']


def load_shuxingdan_table(path):
    """Rows of sys_config/shuxingdan.jat (permanent attribute pills) by id."""
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of shuxingdan rows')
    return {str(r['id']): r for r in rows if isinstance(r, dict) and r.get('id')}


def load_cd_table(path):
    """Rows of sys_config/CdBiao.jat as {cdid: cdtimeMs}."""
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of CdBiao rows')
    return {str(r['cdid']): int(r['cdtime']) for r in rows
            if isinstance(r, dict) and r.get('cdid') is not None
            and r.get('cdtime') is not None}


def load_xiaoguo_table(path):
    """Rows of sys_config/XiaoGuoBiao.jat (buff/effect configs) by effectid."""
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of XiaoGuoBiao rows')
    return {str(r['effectid']): r for r in rows
            if isinstance(r, dict) and r.get('effectid')}


def load_jineng_table(path):
    """Rows of sys_config/JiNengBiao.jat (skill configs) as a plain list."""
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of JiNengBiao rows')
    return [r for r in rows if isinstance(r, dict)]


def load_skillbook_table(path):
    """Rows of sys_config/jinengshubiao.jat keyed by skillbook id."""
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of jinengshubiao rows')
    return {str(r['id']): r for r in rows
            if isinstance(r, dict) and r.get('id')}


def load_zuoji_table(path):
    """Rows of sys_config/ZuoJiBiao.jat keyed by (int(stratum), int(ridelv)).

    Java keys ZuoQiConfig by String.valueOf(int(stratum)) and its level
    configs by int(ridelv) (ZuoQiConfigExportServiceImpl bytecode); every
    row carries both plus maxlv/meinvhp/meinvatt.
    """
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of ZuoJiBiao rows')
    table = {}
    for row in rows:
        if not isinstance(row, dict) or row.get('stratum') is None \
                or row.get('ridelv') is None:
            continue
        table[(int(row['stratum']), int(row['ridelv']))] = row
    return table


# MapExportServiceImpl.configureDataResolve reads path.mm as a big-endian int32 width,
# int32 height, then one unsigned byte per cell in row-major order (x wraps at width)
# until EOF. PathInfoConfig.addPathNode treats a cell as walkable when (value & 31) != 0.
WALKABLE_MASK = 31

# Surround order for getSurroundValidPoint: MapExportServiceImpl always loads
# maps with PathFinderType.AExtend, so PathInfoConfig.preprocess builds each
# node's surrounds from OffConfigUtils.AExtendOffs (bytecode order).
A_EXTEND_OFFS = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0),
                 (-1, 1), (0, 1), (1, 1))


class PathGrid:
    """Walkability grid from path.mm; cells past height*width (trailing bytes) are kept, as Java keeps them."""

    def __init__(self, width, height, values):
        self.width = width
        self.height = height
        self.values = values

    def value(self, x, y):
        index = y * self.width + x
        if x < 0 or x >= self.width or index < 0 or index >= len(self.values):
            return None
        return self.values[index]

    def walkable(self, x, y):
        v = self.value(x, y)
        return v is not None and (v & WALKABLE_MASK) != 0


def load_path_grid(path):
    """Parse one path.mm file into a PathGrid; raises ValueError on a truncated header or non-positive width."""
    with open(path, 'rb') as f:
        data = f.read()
    if len(data) < 8:
        raise ValueError(f'{path}: shorter than the 8-byte path.mm header')
    width, height = struct.unpack('>ii', data[:8])
    if width <= 0:
        raise ValueError(f'{path}: width must be positive, got {width}')
    return PathGrid(width, height, data[8:])


class GameConfig:
    """Lazily loads the legacy tables from a config directory; missing files are reported, not faked."""

    def __init__(self, config_dir=DEFAULT_CONFIG_DIR):
        self.config_dir = config_dir
        self._map_lines = None
        self._monsters = {}
        self._path_grids = {}
        self._templates = None
        self._zhujue = None
        self._zuoji = None
        self._equip = None
        self._shuxingdan = None
        self._fujia_random = None
        self._mall = None
        self._zuwu = None
        self._xishu = None
        self._dazuo = None
        self._vip = None
        self._vipqq = None
        self._xianjie = None
        self._chenghao = None
        self._meiren = None
        self._cd = None
        self._xiaoguo = None
        self._jineng = None
        self._skillbook = None
        self._jingyan = None
        self._shaguai = None
        self._goods = None
        self._dan = None
        self._lihe = None
        self._duoxuan = None
        self._youhui = None
        self._qianghua = None
        self._fujia = None
        self._fujia_random = None
        self._zhujue_shuxing = None
        self._jianding = None
        self._vip_choujiang = None
        self._vip_lingjiang = None
        self._vip_huodong = None
        self._kaige = None
        self._task_main = None
        self._task_sub = None
        self._task_main_first = None
        self._taofa = None
        self._taofa_cfg = None
        self._taofa_interval = None
        self._rc_cond = None
        self._rc_rew = None
        self._rc_loop = None
        self._kaifu_zuoqi = None
        self._zhujue_zqmax = None
        self._birth = None

    @property
    def map_lines_path(self):
        return os.path.join(self.config_dir, 'sys_config', 'MapLine.jat')

    def map_lines(self):
        if self._map_lines is None:
            path = self.map_lines_path
            self._map_lines = load_map_lines(path) if os.path.isfile(path) else {}
            if not self._map_lines:
                log.warning('no MapLine table at %s; map types unknown', path)
        return self._map_lines

    def map_type(self, map_id):
        """MapLineConfig.maptype for a map, or None if the map is not in the table."""
        row = self.map_lines().get(str(map_id))
        if row is None or row.get('maptype') is None:
            return None
        return int(row['maptype'])

    def path_grid(self, map_id):
        """Walkability grid for a map from map_config/<id>/path.mm, or None if the file is absent."""
        key = str(map_id)
        if key not in self._path_grids:
            path = os.path.join(self.config_dir, 'map_config', key, 'path.mm')
            self._path_grids[key] = load_path_grid(path) if os.path.isfile(path) else None
        return self._path_grids[key]

    @property
    def zhujue_attributes_path(self):
        return os.path.join(self.config_dir, 'sys_config', 'ZhuJueShuXingBiao.jat')

    def role_attribute_row(self, level):
        """ZhuJueShuXingBiao row for a level, or None when table/level is absent.

        Drives the 12000 attribute map and the 12050 zhenqi cap (Java:
        ZhujueAttributeExportServiceImpl.loadByLevel, config ZhuJueShuXingBiao.jat).
        """
        if self._zhujue is None:
            path = self.zhujue_attributes_path
            rows = _load(path) if os.path.isfile(path) else []
            self._zhujue = {int(r['level']): r for r in rows
                            if isinstance(r, dict) and r.get('level') is not None}
            if not self._zhujue:
                log.warning('no ZhuJueShuXingBiao table at %s; 12000/12050 unknown',
                            path)
        if level is None:
            return None
        return self._zhujue.get(int(level))

    def cd_time(self, cd_id):
        """PublicCdConfig.cdTime for a cooldown id, or None when unknown.

        Java: PublicCdExportServiceImpl over CdBiao.jat (t070 -> 700). Feeds
        the 42005 dynamic cooldown with the role's live gongjisudu."""
        if self._cd is None:
            path = os.path.join(self.config_dir, 'sys_config', 'CdBiao.jat')
            self._cd = load_cd_table(path) if os.path.isfile(path) else {}
            if not self._cd:
                log.warning('no CdBiao table at %s; skill cooldowns unknown',
                            path)
        return self._cd.get(str(cd_id)) if cd_id else None

    def buff_effect(self, effect_id):
        """XiaoGuoBiao row for a buff id (vip010, birthprotect, ...), or None."""
        if self._xiaoguo is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'XiaoGuoBiao.jat')
            self._xiaoguo = (load_xiaoguo_table(path)
                             if os.path.isfile(path) else {})
            if not self._xiaoguo:
                log.warning('no XiaoGuoBiao table at %s; buff configs unknown',
                            path)
        return self._xiaoguo.get(str(effect_id)) if effect_id else None

    def buff_lasttime(self, effect_id):
        """BuffConfig lasttime (ms) for a buff id, or None when not a timed buff."""
        row = self.buff_effect(effect_id)
        if row is None or row.get('lasttime') in (None, ''):
            return None
        return int(row['lasttime'])

    def skill_cd_id(self, category):
        """JiNengBiao cd1 for a skill category ('normal003' -> 't070'), or None."""
        if self._jineng is None:
            path = os.path.join(self.config_dir, 'sys_config', 'JiNengBiao.jat')
            self._jineng = (load_jineng_table(path)
                            if os.path.isfile(path) else [])
            if not self._jineng:
                log.warning('no JiNengBiao table at %s; skill cooldowns unknown',
                            path)
        for row in self._jineng:
            if row.get('skilltype') == category and row.get('cd1'):
                return str(row['cd1'])
        return None

    def dan_buff(self, goods_id):
        """ShuXinDan row for a dan goods id, or None when absent."""
        if self._dan is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'shuxingdan.jat')
            try:
                rows = _load(path) if os.path.isfile(path) else []
            except ValueError as e:
                log.error('bad dan table: %s', e)
                rows = []
            self._dan = {str(r['id']): r for r in rows
                         if isinstance(r, dict) and r.get('id') is not None}
        return self._dan.get(str(goods_id))

    def lihe_box(self, goods_id):
        """Parsed LiHe.jat row: fixed reward, lottery ids, needs, bind."""
        if self._lihe is None:
            path = os.path.join(self.config_dir, 'sys_config', 'LiHe.jat')
            try:
                rows = _load(path) if os.path.isfile(path) else []
            except ValueError as e:
                log.error('bad lihe table: %s', e)
                rows = []
            self._lihe = {str(r['id']): r for r in rows
                          if isinstance(r, dict) and r.get('id') is not None}
        row = self._lihe.get(str(goods_id))
        if row is None:
            return None
        fixed, zubao = None, []
        for num in range(1, 9):
            cell = str(row.get(f'things{num}') or '')
            if not cell:
                continue
            if cell.startswith('@'):
                zubao.append(cell)
                continue
            parts = cell.split('|')
            try:
                fixed = {'goods': parts[0], 'count': int(parts[1])}
            except (IndexError, TypeError, ValueError):
                fixed = None
        needs = {}
        for cell in str(row.get('itemneed') or '').split(';'):
            gid, _, count = cell.partition('|')
            try:
                needs[gid] = int(count)
            except (TypeError, ValueError):
                continue
        def num(key):
            try:
                return int(row.get(key) or 0)
            except (TypeError, ValueError):
                return 0
        return {'id': str(goods_id), 'fixed': fixed, 'zubao': zubao,
                'itemneed': needs, 'levelneed': num('levelneed'),
                'zuoqi': num('zuoqi'), 'jb': num('moneyneed'),
                'yb': num('goldneed'), 'bindyb': num('silverneed'),
                'bind': num('thingbangding')}

    @staticmethod
    def _libao_goods(cell):
        """'gid:count:bind[;...]' cell into [(gid, count, bind)]."""
        items = []
        for part in str(cell or '').split(';'):
            fields = part.split(':')
            if len(fields) < 2 or not fields[0]:
                continue
            try:
                count = int(fields[1])
            except (TypeError, ValueError):
                continue
            try:
                bind = int(fields[2]) if len(fields) > 2 else 0
            except (TypeError, ValueError):
                bind = 0
            if count <= 0:
                continue
            items.append((fields[0], count, bind))
        return items

    def duoxuan_box(self, goods_id):
        """DuoXuanLiBaoConfig for a box id: libao1..4 choices with goods+gold."""
        if self._duoxuan is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'duoxuanlibao.jat')
            try:
                rows = _load(path) if os.path.isfile(path) else []
            except ValueError as e:
                log.error('bad duoxuan table: %s', e)
                rows = []
            table = {}
            for r in rows:
                if not isinstance(r, dict) or r.get('id') is None:
                    continue
                options = {}
                for num in range(1, 5):
                    goods = self._libao_goods(r.get(f'libao{num}'))
                    if not goods:
                        continue
                    try:
                        gold = int(r.get(f'libao{num}cost') or 0)
                    except (TypeError, ValueError):
                        gold = 0
                    options[f'libao{num}'] = {'goods': goods,
                                             'gold': gold}
                table[str(r['id'])] = {'id': str(r['id']),
                                       'options': options}
            self._duoxuan = table
        return self._duoxuan.get(str(goods_id))

    def youhui_box(self, goods_id):
        """YouHuiQuanConfig for a coupon id: YB cost plus the goods list."""
        if self._youhui is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'youhuiquan.jat')
            try:
                rows = _load(path) if os.path.isfile(path) else []
            except ValueError as e:
                log.error('bad youhui table: %s', e)
                rows = []
            table = {}
            for r in rows:
                if not isinstance(r, dict) or r.get('id') is None:
                    continue
                try:
                    cost = int(r.get('libaocost') or 0)
                except (TypeError, ValueError):
                    cost = 0
                table[str(r['id'])] = {
                    'id': str(r['id']), 'cost': cost,
                    'goods': self._libao_goods(r.get('libao'))}
            self._youhui = table
        return self._youhui.get(str(goods_id))

    def qianghua_config(self, goods_id, qhlv):
        """ZhuangBeiQiangHua row for a gear id at one enhance level."""
        if self._qianghua is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'ZhuangBeiQiangHua.jat')
            try:
                rows = _load(path) if os.path.isfile(path) else []
            except ValueError as e:
                log.error('bad qianghua table: %s', e)
                rows = []
            self._qianghua = {}
            for r in rows:
                if not isinstance(r, dict) or r.get('id') is None:
                    continue
                try:
                    lv = int(r.get('qhlv') or 0)
                except (TypeError, ValueError):
                    continue
                self._qianghua[(str(r['id']), lv)] = r
        row = self._qianghua.get((str(goods_id), int(qhlv)))
        if row is None:
            return None
        def num(key):
            try:
                return int(row.get(key) or 0)
            except (TypeError, ValueError):
                return 0
        try:
            odds = float(row.get('qhodds') or 0)
        except (TypeError, ValueError):
            odds = 0.0
        try:
            jjodds = float(row.get('jjodds') or 0)
        except (TypeError, ValueError):
            jjodds = 0.0
        gold = {}
        for slot in range(1, 10):
            parts = str(row.get(f'glod{slot}') or '').split('|')
            try:
                gold[slot] = [float(parts[0]), float(parts[1])]
            except (IndexError, TypeError, ValueError):
                continue
        return {'maxQhLevel': num('qhmaxlv'),
                'isQianghua': num('permitqh') != 0,
                'costGoods': _goods_map(row.get('qhcostgoods')),
                'qhJb': num('qhneedcoin'), 'qhodds': odds,
                'qhNotice': num('qhnotice') != 0,
                'goldOrGaiLv': gold,
                'qingxiGoods': _goods_map(row.get('qingxi')),
                'qingxiyb': num('qingxiyb'),
                'isPermitjj': num('permitjj') != 0,
                'jjEquipId': str(row.get('jjequipid') or ''),
                'jjEquipQhLevel': num('jjequipqhlv'),
                'jjCostGoods': _goods_map(row.get('jjcostgoods')),
                'jjCostCoin': num('jjcostcoin'),
                'jjMinTimes': num('jjmintimes'),
                'jjMaxTimes': num('jjmaxtimes'), 'jjodds': jjodds}

    def fujia_config(self, goods_id):
        """ZhuangBeiFuJiaShuXingBiao row for a gear id, slots keyed by int."""
        if self._fujia is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'ZhuangBeiFuJiaShuXingBiao.jat')
            try:
                rows = _load(path) if os.path.isfile(path) else []
            except ValueError as e:
                log.error('bad fujia table: %s', e)
                rows = []
            self._fujia = {str(r['id']): r for r in rows
                           if isinstance(r, dict) and r.get('id') is not None}
        row = self._fujia.get(str(goods_id))
        if row is None:
            return None
        slots = {}
        for slot in range(0, 7):
            cell = str(row.get(f'{slot}fujiaid') or '')
            if not cell:
                continue
            try:
                ids = [int(p) for p in cell.split(',') if p != '']
            except (TypeError, ValueError):
                continue
            def cell_num(key, _slot=slot):
                try:
                    return int(row.get(f'{_slot}{key}') or 0)
                except (TypeError, ValueError):
                    return 0
            slots[slot] = {
                'ids': ids, 'needVip': cell_num('fujiaidkaiqi'),
                'needLv': cell_num('fujiaidkaiqilv'),
                'needEquipLv': cell_num('fujiaidqianghua'),
                'money': cell_num('money'),
                'clearGoods': _goods_map(row.get(f'{slot}fujiaidqingchu')),
                'clearYb': cell_num('fujiaidqingchuyb')}
        try:
            addexp = [int(row.get('jiandingexp1') or 0),
                      int(row.get('jiandingexp2') or 0)]
        except (TypeError, ValueError):
            addexp = [0, 0]
        try:
            fu_level = int(row.get('level') or 0)
        except (TypeError, ValueError):
            fu_level = 0
        rare_min, rare_max = {}, {}
        for slot in range(0, 7):
            for key, out in (('fujiamin', rare_min), ('fujiamax', rare_max)):
                try:
                    out[slot] = int(row.get(f'{slot}{key}') or 0)
                except (TypeError, ValueError):
                    continue
        return {'slots': slots, 'fuJiaLevel': fu_level, 'addexp': addexp,
                'rareMin': rare_min, 'rareMax': rare_max}

    def fujia_random(self, fujia_id, level):
        """ZhuangBeiFuJiaShuXingsuijiBiao row for (fujiaId, level)."""
        if self._fujia_random is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'ZhuangBeiFuJiaShuXingsuijiBiao.jat')
            try:
                rows = _load(path) if os.path.isfile(path) else []
            except ValueError as e:
                log.error('bad fujia random table: %s', e)
                rows = []
            self._fujia_random = {}
            for r in rows:
                if not isinstance(r, dict):
                    continue
                try:
                    key = (int(r.get('fujiaid')), int(r.get('level')))
                except (TypeError, ValueError):
                    continue
                self._fujia_random[key] = r
        try:
            row = self._fujia_random.get((int(fujia_id), int(level)))
        except (TypeError, ValueError):
            return None
        if row is None:
            return None
        rates, counts = {}, {}
        for num in range(0, 5):
            try:
                rates[num] = float(row.get(f'{num}jilv') or 0)
            except (TypeError, ValueError):
                continue
            weights = {}
            for cell in str(row.get(f'{num}jiading') or '').split(';'):
                count, _, weight = cell.partition('|')
                try:
                    weights[int(count)] = float(weight)
                except (TypeError, ValueError):
                    continue
            if weights:
                counts[num] = weights
        return {'rates': rates, 'counts': counts}

    def zhujue_jdexp(self, level):
        """ZhuJueShuXingBiao.jdexp for a role level (jianding fail cap)."""
        if self._zhujue_shuxing is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'ZhuJueShuXingBiao.jat')
            try:
                rows = _load(path) if os.path.isfile(path) else []
            except ValueError as e:
                log.error('bad zhujue shuxing table: %s', e)
                rows = []
            self._zhujue_shuxing = {}
            for r in rows:
                if not isinstance(r, dict):
                    continue
                try:
                    self._zhujue_shuxing[int(r.get('level'))] = int(
                        r.get('jdexp') or 0)
                except (TypeError, ValueError):
                    continue
        try:
            return self._zhujue_shuxing.get(int(level), 0)
        except (TypeError, ValueError):
            return 0

    def jianding_config(self, item_level):
        """gaojijiandingbiao.jat row for an itemLevel (hecheng synthesis)."""
        if self._jianding is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'gaojijiandingbiao.jat')
            try:
                rows = _load(path) if os.path.isfile(path) else []
            except ValueError as e:
                log.error('bad jianding table: %s', e)
                rows = []
            self._jianding = {}
            for r in rows:
                if not isinstance(r, dict):
                    continue
                try:
                    level = int(r.get('zhangbeiLV'))
                except (TypeError, ValueError):
                    continue
                rewards = []
                for cell in str(r.get('hechengwupin') or '').split(';'):
                    gid, _, count = cell.partition(':')
                    if not gid:
                        continue
                    try:
                        rewards.append((gid, int(count)))
                    except (TypeError, ValueError):
                        continue
                try:
                    juanzhou = int(r.get('juanzhou') or 0) != 0
                except (TypeError, ValueError):
                    juanzhou = False
                self._jianding[level] = {
                    'juanzhou': juanzhou,
                    'stones': _goods_map(r.get('hechengshi')),
                    'rewards': rewards}
        try:
            return self._jianding.get(int(item_level))
        except (TypeError, ValueError):
            return None

    def dead_birth(self, map_id):
        """{'map': dest map id, 'points': [(x, y)]} for a dead map, or None.

        Port of BornZuoBiaoConfigExportServiceImpl's DEAD_TYPE (borntype 2) rows: keyed by map1,
        the map2 cell is the revive map and map2target holds 'x|y' birth points.
        """
        if self._birth is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'ChuShengZuoBiaoPeiZhibBiao.jat')
            try:
                rows = _load(path) if os.path.isfile(path) else []
            except ValueError as e:
                log.error('bad born table: %s', e)
                rows = []
            self._birth = {}
            for r in rows:
                if not isinstance(r, dict) or str(r.get('borntype')) != '2' \
                        or r.get('map1') is None:
                    continue
                points = []
                for cell in str(r.get('map2target') or '').split(';'):
                    x, _, y = cell.partition('|')
                    try:
                        points.append((int(x), int(y)))
                    except ValueError:
                        continue
                if points:
                    self._birth[str(r['map1'])] = {
                        'map': str(r.get('map2')), 'points': points}
        return self._birth.get(str(map_id))

    def skill_info(self, category, level):
        """JiNengBiao row for a category at one level (learn checks)."""
        if not category:
            return None
        for row in self._jineng_rows():
            try:
                match = row.get('skilltype') == category and \
                    int(row.get('level') or 0) == int(level)
            except (TypeError, ValueError):
                match = False
            if match:
                return row
        return None

    def skill_row(self, category):
        """JiNengBiao row for a skill category, or None.

        Java keys SkillConfig by category (normal003 -> T21, a 0.8, b 10);
        rows carry per-level tiers, so the highest level tier wins."""
        if self._jineng is None:
            path = os.path.join(self.config_dir, 'sys_config', 'JiNengBiao.jat')
            self._jineng = (load_jineng_table(path)
                            if os.path.isfile(path) else [])
            if not self._jineng:
                log.warning('no JiNengBiao table at %s; skill cooldowns unknown',
                            path)
        best = None
        for row in self._jineng:
            if row.get('skilltype') != category:
                continue
            if best is None or int(row.get('level') or 0) > int(best.get('level') or 0):
                best = row
        return best

    def skillbook_table(self):
        """jinengshubiao rows keyed by skillbook id; empty if absent."""
        if self._skillbook is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'jinengshubiao.jat')
            try:
                self._skillbook = load_skillbook_table(path) \
                    if os.path.isfile(path) else {}
            except ValueError as e:
                log.error('bad skillbook table: %s', e)
                self._skillbook = {}
        return self._skillbook

    def skillbook_book(self, goods_id):
        """SkillBookConfig row for a skillbook goods id, or None.

        Port of loadBySkillBookId: the configure map is keyed by the
        row's id cell, which is the goods id.
        """
        if goods_id is None:
            return None
        return self.skillbook_table().get(str(goods_id))

    def skillbook_type(self, ridetype, rare_level, level):
        """SkillBookConfig row for a (ridetype, rare, level) tier, or None.

        Port of loadBySkillBookType: configureDataResolve indexes every
        row under 'ridetype-rarelevel-skillbooklevel' and resolves through
        that key, so the lookup scans for the matching triple.
        """
        for row in self.skillbook_table().values():
            try:
                match = str(row.get('ridetype')) == str(ridetype) and \
                    int(row.get('rarelevel') or 0) == int(rare_level) and \
                    int(row.get('skillbooklevel') or 0) == int(level)
            except (TypeError, ValueError):
                match = False
            if match:
                return row
        return None

    def zuoqi_skill_open(self, rank, role_level, index):
        """Whether a mount's skill slot `index` (1..6) is unlocked.

        Port of RoleZuoQiServiceImpl.isOpen over loadByRankLevel: the
        level row's mutex1..mutex6 cell above 0 opens its slot.
        """
        try:
            index = int(index)
        except (TypeError, ValueError):
            return False
        if index < 1 or index > 6:
            return False
        pet = self.zuoqi_pet(rank, role_level)
        if pet is None:
            return False
        try:
            return float(pet[1].get(f'mutex{index}') or 0) > 0
        except (TypeError, ValueError):
            return False

    def exp_decay(self, lv_diff):
        """JingYanShuaiJianBiao subtractfactor for a role-minus-monster gap.

        Feeds DropExpShuaiJianConfig.levelXishu (diff 16 -> 0.01); gaps past
        the table use the last row, exactly Java's keyed-config miss default
        of the nearest entry is NOT assumed -- absent table means None."""
        if self._jingyan is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'JingYanShuaiJianBiao.jat')
            rows = _load(path) if os.path.isfile(path) else []
            self._jingyan = {int(r['lvdifference']): float(r['subtractfactor'])
                             for r in rows
                             if isinstance(r, dict)
                             and r.get('lvdifference') is not None
                             and r.get('subtractfactor') is not None}
            if not self._jingyan:
                log.warning('no JingYanShuaiJianBiao table at %s; kill exp unknown',
                            path)
        if not self._jingyan:
            return None
        return self._jingyan.get(max(int(lv_diff), 0),
                                 self._jingyan[max(self._jingyan)])

    def exp_revise(self, harm_percent, solo=True):
        """ShaGuaiXiuZhengBiao correction for a killer's harm share.

        Solo kills read solorevise, team kills rankrevise (both stored as
        strings: '1.00' at harm 100); unknown tables/percentages give None."""
        if self._shaguai is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'ShaGuaiXiuZhengBiao.jat')
            rows = _load(path) if os.path.isfile(path) else []
            self._shaguai = {int(r['hurtpercentage']): r for r in rows
                             if isinstance(r, dict)
                             and r.get('hurtpercentage') is not None}
            if not self._shaguai:
                log.warning('no ShaGuaiXiuZhengBiao table at %s; kill exp unknown',
                            path)
        row = self._shaguai.get(min(max(int(harm_percent), 0), 100))
        if row is None:
            return None
        try:
            return float(row.get('solorevise' if solo else 'rankrevise'))
        except (TypeError, ValueError):
            return None

    def monster_template(self, template_id):
        """GuaiWuBiao row for a template id (D040011 -> hp 3895, basicexp 400)."""
        return self.monster_templates().get(str(template_id))

    def monsters(self, map_id):
        """Monster spawn records for a map (empty list if the map has no monster.mm)."""
        key = str(map_id)
        if key not in self._monsters:
            path = os.path.join(self.config_dir, 'map_config', key, 'monster.mm')
            self._monsters[key] = load_monsters(path) if os.path.isfile(path) else []
        return self._monsters[key]

    def zuoqi_table(self):
        """ZuoJiBiao rows keyed by (rank, level); empty when the file is absent."""
        if self._zuoji is None:
            path = os.path.join(self.config_dir, 'sys_config', 'ZuoJiBiao.jat')
            try:
                self._zuoji = load_zuoji_table(path) if os.path.isfile(path) else {}
            except ValueError as e:
                log.error('bad ZuoJiBiao table: %s', e)
                self._zuoji = {}
        return self._zuoji

    def zuoqi_pet(self, rank, role_level):
        """(pet_level, level_row) for a mount of `rank` owned by a level
        `role_level` role, or None when the rank/level row is missing.

        Port of RoleFactoryHelper.getZuoqiLevel + loadByRankLevel: the pet
        level is the role level clamped to the rank's maxlv (ZuoQiConfig-
        minLevel is never set in the jar, so the floor is 0) and the level
        row supplies maxHp via meinvhp.
        """
        table = self.zuoqi_table()
        if not table or rank is None or int(rank) <= 0:
            return None
        rank = int(rank)
        # The config object is created once, from the rank's first row in
        # file order, so maxlv is that row's (ZuoQiConfigExportServiceImpl).
        maxlv = next((int(r.get('maxlv') or 0)
                      for (rk, _lv), r in table.items() if rk == rank), None)
        if maxlv is None:
            return None
        level = max(0, min(int(role_level or 0), maxlv))
        row = table.get((rank, level))
        if row is None:
            return None
        return level, row

    def equip_table(self):
        """ZhuangBeiFuJiaShuXingBiao rows keyed by goods id; empty when absent."""
        if self._equip is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'ZhuangBeiFuJiaShuXingBiao.jat')
            try:
                self._equip = load_equip_attribute_table(path) \
                    if os.path.isfile(path) else {}
            except ValueError as e:
                log.error('bad ZhuangBeiFuJiaShuXingBiao table: %s', e)
                self._equip = {}
            if not self._equip:
                log.warning('no equipment attribute table at %s; 12000 has no gear',
                            path)
        return self._equip

    def shuxingdan_table(self):
        """shuxingdan.jat rows keyed by attribute id; empty when absent."""
        if self._shuxingdan is None:
            path = os.path.join(self.config_dir, 'sys_config', 'shuxingdan.jat')
            try:
                self._shuxingdan = load_shuxingdan_table(path) \
                    if os.path.isfile(path) else {}
            except ValueError as e:
                log.error('bad shuxingdan table: %s', e)
                self._shuxingdan = {}
        return self._shuxingdan

    def fujia_random_table(self):
        """ZhuangBeiFuJiaShuXingsuijiBiao rows keyed 'fujiaid-level'."""
        if self._fujia_random is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'ZhuangBeiFuJiaShuXingsuijiBiao.jat')
            try:
                self._fujia_random = load_fujia_random_table(path) \
                    if os.path.isfile(path) else {}
            except ValueError as e:
                log.error('bad fujia random table: %s', e)
                self._fujia_random = {}
        return self._fujia_random

    def fujia_attribute_map(self, pairs, level):
        """Random extra (fujia) affix bonuses for one item's fujia pairs at its fujia level.

        Port of EquipAttributeService.getEquipFuJiaAttribute: key each
        pair as '<fujiaid>-<level>' (the item's ZhuangBeiFuJiaShuXingBiao
        `level` cell) and add shuxinValue * count under the row's shuxing
        bag key. Keys like mb/mbdk feed resist formulas, not the 12000
        map; flat keys (physicdamage, ...) merge with the gear bag.
        """
        table = self.fujia_random_table()
        totals = {}
        for fid, count in pairs or []:
            row = table.get('%s-%s' % (fid, level))
            if row is None:
                log.warning('fujia %s-%s has no random row; skipped', fid, level)
                continue
            name = row.get('shuxing')
            value = _number(row.get('value')) * (count or 0)
            if name and value:
                totals[name] = totals.get(name, 0.0) + value
        return totals

    def equip_attribute_map(self, items):
        """Summed gear attribute map for equipped items.

        Port of EquipAttributeService.getEquipAttributeAll over a role's
        role_equip_slot rows: per item the flat base columns plus every 强化
        star's starN<attr>, all scaled by the rare level's Njichubili rate
        (getEquipBaseAttribute/getEquipQianghuaAttribute), plus the random
        附加 affixes keyed '<fujiaid>-<level>' (getEquipFuJiaAttribute).
        """
        table = self.equip_table()
        totals = {}
        for item in items:
            row = table.get(str(item.get('goods_id')))
            if row is None:
                log.warning('equipment %r has no attribute row; skipped',
                            item.get('goods_id'))
                continue
            rate = _number(row.get('%sjichubili' % int(item.get('rare_level') or 0))) or 1.0
            stars, pairs = parse_item_attributes(item.get('attributes'))
            for name in EQUIP_ATTRIBUTE_NAMES:
                value = _number(row.get(name))
                for star in stars:
                    value += _number(row.get('star%d%s' % (star, name)))
                if value:
                    totals[name] = totals.get(name, 0.0) + value * rate
            for name, value in self.fujia_attribute_map(pairs, row.get('level')).items():
                totals[name] = totals.get(name, 0.0) + value
        return totals

    def _goods_table(self):
        """Goods rows by id; empty when goods.jat is absent."""
        if self._goods is None:
            path = os.path.join(self.config_dir, 'sys_config', 'goods.jat')
            try:
                self._goods = load_goods_table(path) if os.path.isfile(path) else {}
            except ValueError as e:
                log.error('bad goods table: %s', e)
                self._goods = {}
        return self._goods

    def goods_category(self, goods_id):
        """Category code of a goods id (GoodsCategoryUtil compares as strings)."""
        row = self._goods_table().get(str(goods_id))
        if row is None or row.get('category') in ('', None):
            return None
        return str(row['category'])

    def _kaige_table(self):
        """Kaige rows by (slottype, num); empty when the file is absent."""
        if self._kaige is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'KaiGeFeiYongBiao.jat')
            try:
                self._kaige = load_kaige_table(path) if os.path.isfile(path) else {}
            except ValueError as e:
                log.error('bad kaige table: %s', e)
                self._kaige = {}
        return self._kaige

    def kaige_max_slot_num(self, slottype):
        """Max slot num for slottype ('B' bag, 'C' storage); 0 when unknown."""
        nums = [num for (stype, num) in self._kaige_table() if stype == slottype]
        return max(nums) if nums else 0

    def kaige_init_slot_num(self, slottype):
        """Slots unlocked before the first kaige row (min id - 1).

        Inferred, not traced: live role_bag_state rows carry exactly these
        values (bag 34, storage 30) for roles that never unlocked a slot.
        """
        nums = [num for (stype, num) in self._kaige_table() if stype == slottype]
        return min(nums) - 1 if nums else 0

    def kaige_row(self, slottype, num):
        """Kaige row for one unlockable slot number, or None."""
        return self._kaige_table().get((str(slottype), int(num)))

    def kaige_slot(self, slottype, num):
        """Parsed OpenSlotConfig for one kaige slot, or None when missing.

        cost 'a:b' pays abs(b) in YXB (copper) when a is 1, else YB
        (lingshi); needtime seconds, expadd and propertyvalue default to 0.
        """
        row = self.kaige_row(slottype, num)
        if row is None:
            return None
        try:
            first, _, second = str(row.get('cost') or '').partition(':')
            money = 'YXB' if int(first) == 1 else 'YB'
            cost_num = abs(int(second))
        except (TypeError, ValueError):
            return None
        try:
            open_time = int(row.get('needtime') or 0)
        except (TypeError, ValueError):
            open_time = 0
        try:
            add_exp = abs(int(row.get('expadd') or 0))
        except (TypeError, ValueError):
            add_exp = 0
        try:
            add_attr = abs(float(row.get('propertyvalue') or 0))
        except (TypeError, ValueError):
            add_attr = 0.0
        return {'money': money, 'cost_num': cost_num,
                'open_time': open_time, 'add_exp': add_exp,
                'add_attr_name': str(row.get('property') or ''),
                'add_attr_value': add_attr}

    def goods_max_stack(self, goods_id):
        """Max stack (maxstack cell) for a goods id, or None when unknown."""
        row = self._goods_table().get(str(goods_id))
        if row is None:
            return None
        try:
            return int(row.get('maxstack') or 0)
        except (TypeError, ValueError):
            return None

    def goods_recycle(self, goods_id):
        """Sell price (recycle cell) for a goods id, or None when unknown."""
        row = self._goods_table().get(str(goods_id))
        if row is None or row.get('recycle') in ('', None):
            return None
        try:
            return int(row.get('recycle'))
        except (TypeError, ValueError):
            return None

    def _task_assembly(self):
        """(quests by id2, subchapters by id, first id) from ZhuXianRenWu."""
        if self._task_main is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'ZhuXianRenWu.jat')
            try:
                rows = load_task_main_table(path) if os.path.isfile(path) \
                    else []
            except ValueError as e:
                log.error('bad task table: %s', e)
                rows = []
            table, subs = {}, {}
            first, prev_id, prev_sub = None, None, None
            accum, seq, sub_seq = {}, 1, 1
            for row in rows:
                if not isinstance(row, dict):
                    continue
                task_id = row.get('id2')
                sub_id = row.get('id')
                if task_id is None or sub_id is None:
                    break
                task_id, sub_id = str(task_id), str(sub_id)
                if first is None:
                    first = task_id
                cfg = self._parse_task_main(task_id, row)
                cfg['last_task_id'] = prev_id
                cfg['sequence'] = seq
                table[task_id] = cfg
                sub = subs.get(sub_id)
                if sub is None:
                    sub = {'id': sub_id,
                           'name': str(row.get('name1') or ''),
                           'disc': str(row.get('disc1') or ''),
                           'ico': str(row.get('ico1') or ''),
                           'shuoming': str(row.get('dijizizhang') or ''),
                           'reward': parse_task_attr_map(row.get('reward')),
                           'last_sub_id': prev_sub,
                           'sequence': sub_seq,
                           'task_ids': [],
                           'last_task_id': None,
                           'last_task_seq': 0}
                    if accum:
                        merged = dict(accum)
                        for name, value in (sub['reward'] or {}).items():
                            merged[name] = merged.get(name, 0.0) + value
                        sub['reward'] = merged or None
                    subs[sub_id] = sub
                    prev_sub = sub_id
                    sub_seq += 1
                    accum = dict(sub['reward'] or {})
                sub['task_ids'].append(task_id)
                if seq > sub['last_task_seq']:
                    sub['last_task_seq'] = seq
                    sub['last_task_id'] = task_id
                prev_id, seq = task_id, seq + 1
            self._task_main = table
            self._task_sub = subs
            self._task_main_first = first
        return self._task_main

    def _parse_task_main(self, task_id, row):
        """Parsed TaskMainConfig dict for one ZhuXianRenWu row."""
        items = parse_task_item_order(row.get('itemOrder') or '')
        full, shenjiang = [], []
        for item in items or []:
            # Awards parse splits shenjiang-category goods (category 40)
            # into the shenjiang id list; the rest grant through the bag.
            if self.goods_category(item['goods_id']) == '40':
                shenjiang.append(item['goods_id'])
            else:
                full.append(item)
        return {'id': task_id,
                'chapter_sub_id': str(row.get('id') or ''),
                'name': str(row.get('name2') or ''),
                'complete_npc': str(row.get('completeNpc') or ''),
                'describe': str(row.get('describe') or ''),
                'duologue': str(row.get('duologue') or ''),
                'pay_type': '' if row.get('pay') is None
                else str(row.get('pay')),
                'next_task_id': str(row.get('autoTask') or ''),
                'trace': str(row.get('trace')).split('_')
                if row.get('trace') else None,
                'recevie_level': config_int(row.get('limit')),
                'jb': config_int(row.get('gold')),
                'bound_ob': config_int(row.get('boundOb')),
                'exp': config_int(row.get('exp')),
                'prestige': config_int(row.get('prestige')),
                'zhiqi': config_int(row.get('zhenqi')),
                'reward_items': items,
                'reward_grant': full,
                'shenjiang': shenjiang,
                'reward_bind': config_int(row.get('bound')),
                'is_xinshou': config_int(row.get('xinshou')),
                'caiji_id': str(row.get('caiji') or ''),
                'complete_items': parse_task_goods(str(row.get('completeItem')
                                                      or '')),
                'complete_monsters': parse_task_monsters(
                    str(row.get('completeMonster') or '')),
                'recover_items': parse_task_goods(str(row.get('recoverItem')
                                                       or '')),
                'rewards_success': str(row.get('rewardsSuccess') or ''),
                'last_task_id': None,
                'sequence': 0}

    def _task_main_table(self):
        """Main-quest configs by id2; empty when the table is absent."""
        return self._task_assembly()

    def taofa_table(self):
        """{taofaid: row} from taskTaoFaRenWu.jat, loaded once; a bad or missing file gives {}."""
        if self._taofa is None:
            path = os.path.join(self.config_dir, 'sys_config', 'taskTaoFaRenWu.jat')
            try:
                self._taofa = load_taofa_table(path) if os.path.isfile(path) else {}
            except ValueError as e:
                log.error('bad taofa table: %s', e)
                self._taofa = {}
        return self._taofa

    def _taofa_assembly(self):
        """(parsed taofa configs by task id, level_color interval lists)."""
        if self._taofa_cfg is None:
            table, intervals = {}, {}
            for task_id, row in self.taofa_table().items():
                cfg = self._parse_taofa(task_id, row)
                table[task_id] = cfg
                for level in range(cfg['min'], cfg['max'] + 1):
                    key = f"{level}_{cfg['color']}"
                    intervals.setdefault(key, []).append(cfg)
            self._taofa_cfg = table
            self._taofa_interval = intervals
        return self._taofa_cfg

    @staticmethod
    def _parse_taofa(task_id, row):
        """Parsed TaskTaoFaConfig dict for one taskTaoFaRenWu row."""
        row = row or {}
        target = str(row.get('target') or '')
        show = str(row.get('showitem') or '')
        desc = row.get('desc')
        goods, zubao = parse_taofa_items(row.get('itemOrder') or '',
                                         row.get('bound'))
        low, high = config_int(row.get('min')), config_int(row.get('max'))
        color = config_int(row.get('color'))
        return {'id': task_id,
                'min': low, 'max': high, 'color': color,
                'query_id': f'{low}_{high}_{color}',
                'res': str(row.get('res') or ''),
                'map_name': str(row.get('mapName') or ''),
                'monster_level': config_int(row.get('monsterLv')),
                'monster_name': str(row.get('monsterName') or ''),
                'monster_type': config_int(row.get('monsterType')),
                'bind': config_int(row.get('bound')),
                'target': target.split('_') if target else None,
                'duologue': str(row.get('duologue') or ''),
                'swallow': config_int(row.get('swallow')) != 0,
                'merge': config_float(row.get('merge')),
                'kill_monster': parse_taofa_monster(row.get('monster') or ''),
                'exp': config_int(row.get('exp')),
                'jb': config_int(row.get('gold')),
                'bind_yb': config_int(row.get('boundOb')),
                'prestige': config_int(row.get('prestige')),
                'zhenqi': config_int(row.get('zhenqi')),
                'goods': goods,
                'zubao': zubao,
                'show_items': parse_task_item_order(show),
                'desc': config_int(desc) if desc not in ('', None) else None,
                'qianghua': str(row.get('intensify') or ''),
                'xilian': str(row.get('addition') or ''),
                'call_permit': config_int(row.get('callingallow')) != 0,
                'call_goods': str(row.get('callinggold') or '') or None,
                'call_lifetime': config_int(row.get('losttime'))}

    def taofa_config(self, task_id):
        """Parsed TaskTaoFaConfig for a taofaid, or None when unknown."""
        return self._taofa_assembly().get(str(task_id))

    def taofa_interval(self, level, color):
        """Taofa configs for a role level and goods rare level (level_color key)."""
        self._taofa_assembly()
        return list(self._taofa_interval.get(f'{level}_{color}', []))

    def _richang_rows(self, name):
        """Raw row list from a taskRiChangRenWu* table; [] when absent."""
        path = os.path.join(self.config_dir, 'sys_config', f'{name}.jat')
        try:
            rows = _load(path) if os.path.isfile(path) else []
        except ValueError as e:
            log.error('bad %s table: %s', name, e)
            return []
        if isinstance(rows, list) and len(rows) == 1 \
                and isinstance(rows[0], list):
            rows = rows[0]
        return [r for r in rows] if isinstance(rows, list) else []

    def _richang_condition_assembly(self):
        """(conditions by id, full min_max_diff lists, sub min_max lists, buckets)."""
        if self._rc_cond is None:
            table, full, sub, buckets = {}, {}, {}, {}
            for row in self._richang_rows('taskRiChangRenWu'):
                if not isinstance(row, dict) or not row.get('id'):
                    continue
                cfg = self._parse_richang_condition(row)
                table[cfg['id']] = cfg
                full.setdefault(cfg['query_id'], []).append(cfg)
                sub.setdefault(cfg['query_sub'], []).append(cfg)
                buckets[cfg['min']] = cfg['max']
            self._rc_cond = (table, full, sub, buckets)
        return self._rc_cond

    @staticmethod
    def _parse_richang_condition(row):
        """Parsed TaskRCConditionConfig: completeMonster/Item via the monster map."""
        low, high = config_int(row.get('min')), config_int(row.get('max'))
        diff = config_int(row.get('difficultyLv'))
        return {'id': str(row.get('id')),
                'difficulty': diff, 'min': low, 'max': high,
                'query_sub': f'{low}_{high}',
                'query_id': f'{low}_{high}_{diff}',
                'kill_monsters': parse_task_monsters(
                    str(row.get('completeMonster') or '')),
                'complete_items': parse_task_monsters(
                    str(row.get('completeItem') or ''))}

    def richang_condition(self, cond_id):
        """Parsed TaskRCConditionConfig for an id, or None when unknown."""
        return self._richang_condition_assembly()[0].get(str(cond_id))

    def richang_condition_interval(self, sub_key, difficulty):
        """Condition configs for 'min_max' + difficulty (full key lookup)."""
        return list(self._richang_condition_assembly()[1].get(
            f'{sub_key}_{difficulty}', []))

    def richang_condition_subinterval(self, sub_key):
        """Condition configs for one 'min_max' bucket."""
        return list(self._richang_condition_assembly()[2].get(sub_key, []))

    def richang_condition_buckets(self):
        """{min: max} level buckets for the condition interval lookup."""
        return dict(self._richang_condition_assembly()[3])

    def _richang_reward_assembly(self):
        """(rewards by id, full min_max_thick lists, sub min_max lists, buckets)."""
        if self._rc_rew is None:
            table, full, sub, buckets = {}, {}, {}, {}
            for row in self._richang_rows('taskRiChangRenWuJiangLi'):
                if not isinstance(row, dict) or not row.get('id'):
                    continue
                cfg = self._parse_richang_reward(row)
                table[cfg['id']] = cfg
                full.setdefault(cfg['query_id'], []).append(cfg)
                sub.setdefault(cfg['query_sub'], []).append(cfg)
                buckets[cfg['min']] = cfg['max']
            self._rc_rew = (table, full, sub, buckets)
        return self._rc_rew

    @staticmethod
    def _parse_richang_reward(row):
        """Parsed TaskRCRewardConfig for one JiangLi row."""
        low, high = config_int(row.get('min')), config_int(row.get('max'))
        thick = config_int(row.get('thickLv'))
        items = parse_task_item_order(str(row.get('itemOrder') or ''))
        return {'id': str(row.get('id')),
                'min': low, 'max': high, 'thick': thick,
                'query_sub': f'{low}_{high}',
                'query_id': f'{low}_{high}_{thick}',
                'exp': config_int(row.get('exp')),
                'jb': config_int(row.get('gold')),
                'bind_yb': config_int(row.get('boundOb')),
                'zhenqi': config_int(row.get('zhenqi')),
                'prestige': config_int(row.get('prestige')),
                'reward_items': items,
                'reward_bind': config_int(row.get('bound'))}

    def richang_reward(self, reward_id):
        """Parsed TaskRCRewardConfig for an id, or None when unknown."""
        return self._richang_reward_assembly()[0].get(str(reward_id))

    def richang_reward_interval(self, sub_key, thick):
        """Reward configs for 'min_max' + thick level."""
        return list(self._richang_reward_assembly()[1].get(
            f'{sub_key}_{thick}', []))

    def richang_reward_subinterval(self, sub_key):
        """Reward configs for one 'min_max' bucket."""
        return list(self._richang_reward_assembly()[2].get(sub_key, []))

    def richang_reward_buckets(self):
        """{min: max} level buckets for the reward interval lookup."""
        return dict(self._richang_reward_assembly()[3])

    def _richang_loop_assembly(self):
        """(loop rewards by id, min_max lists, buckets) from EWaiJiangLi."""
        if self._rc_loop is None:
            table, full, buckets = {}, {}, {}
            for row in self._richang_rows('taskRiChangRenWuEWaiJiangLi'):
                if not isinstance(row, dict) or not row.get('id'):
                    continue
                cfg = self._parse_richang_loop(row)
                table[cfg['id']] = cfg
                full.setdefault(cfg['query_id'], []).append(cfg)
                buckets[cfg['min']] = cfg['max']
            self._rc_loop = (table, full, buckets)
        return self._rc_loop

    @staticmethod
    def _parse_richang_loop(row):
        """Parsed TaskRCLoopRewardConfig; jb reads the thickLv cell.

        The loop table has no thickLv column, so object2int gives 0 and
        every loop reward pays no YXB, exactly like the jar.
        """
        low, high = config_int(row.get('min')), config_int(row.get('max'))
        items = parse_task_item_order(str(row.get('itemOrder') or ''))
        return {'id': str(row.get('id')),
                'min': low, 'max': high,
                'query_id': f'{low}_{high}',
                'exp': config_int(row.get('exp')),
                'jb': config_int(row.get('thickLv')),
                'bind_yb': config_int(row.get('boundOb')),
                'zhenqi': config_int(row.get('zhenqi')),
                'prestige': config_int(row.get('prestige')),
                'reward_items': items,
                'reward_bind': config_int(row.get('bound'))}

    def richang_loop_reward(self, reward_id):
        """Parsed TaskRCLoopRewardConfig for an id, or None when unknown."""
        return self._richang_loop_assembly()[0].get(str(reward_id))

    def richang_loop_interval(self, sub_key):
        """Loop reward configs for one 'min_max' bucket."""
        return list(self._richang_loop_assembly()[1].get(sub_key, []))

    def richang_loop_buckets(self):
        """{min: max} level buckets for the loop interval lookup."""
        return dict(self._richang_loop_assembly()[2])

    def vip_tunshi_times(self, vip_level):
        """VipConfig.getTunshitimes bonus for a level; 0 when absent."""
        return self._vip_cell(vip_level, 'tunshitimes')

    def vip_taofa_times(self, vip_level):
        """VipConfig.getTaofatimes bonus for a level; 0 when absent."""
        return self._vip_cell(vip_level, 'taofatimes')

    def vip_onekeytask(self, vip_level):
        """VipConfig.isOnekeytask for a level; False when absent."""
        return self._vip_cell(vip_level, 'onekeytask') != 0

    def _vip_cell(self, vip_level, cell):
        try:
            row = self.vip_table().get(int(vip_level or 0))
        except (TypeError, ValueError):
            return 0
        return config_int((row or {}).get(cell))

    def goods_rarelevel(self, goods_id):
        """Rare level (rarelevel cell) for a goods id; 0 when unknown."""
        row = self._goods_table().get(str(goods_id))
        if row is None:
            return 0
        return config_int(row.get('rarelevel'))

    def task_subchapter(self, sub_id):
        """Assembled subchapter (tasks, rewards, last task), or None."""
        self._task_assembly()
        return (self._task_sub or {}).get(str(sub_id))

    def task_attr_index_convert(self, mapping):
        """Subchapter/tips reward map with names resolved via the index table."""
        return convert_index_attribute(mapping, TASK_ATTRIBUTE_INDEX)

    def task_main_first_id(self):
        """First task id in file order (configureDataResolve keeps it)."""
        self._task_assembly()
        return self._task_main_first

    def task_main(self, task_id):
        """Parsed TaskMainConfig for a quest id, or None when unknown.

        Column mapping follows createTaskMainConfig; numerics tolerate '#N/A', category-40 awards land in shenjiang.
        """
        return self._task_assembly().get(str(task_id))

    def goods_job(self, goods_id):
        """Job gate of a goods id ('0' means any job); None when unknown."""
        row = self._goods_table().get(str(goods_id))
        if row is None or row.get('job') in ('', None):
            return None
        return str(row['job'])

    def goods_sort_num(self, goods_id):
        """Sort group (sortNum) for a goods id, or None when unknown.

        The jar never calls GoodsConfig.setSortNum, so this is 0 for every
        known goods; the tidy-up grouping still reads it per slot exactly
        as BagClearUpUtil.pickup does.
        """
        row = self._goods_table().get(str(goods_id))
        if row is None:
            return None
        try:
            return int(row.get('sortNum') or 0)
        except (TypeError, ValueError):
            return 0

    def _jineng_rows(self):
        """JiNengBiao rows (every skill level); empty when the file is absent."""
        if self._jineng is None:
            path = os.path.join(self.config_dir, 'sys_config', 'JiNengBiao.jat')
            try:
                self._jineng = load_jineng_table(path) if os.path.isfile(path) else []
            except ValueError as e:
                log.error('bad JiNengBiao table: %s', e)
                self._jineng = []
        return self._jineng

    def skill_fight(self, skills):
        """[skill, kangxin] fight ints from a role's owned skills.

        Port of ZhanDouLiServiceImpl.getSkillFighting: each owned skill adds
        the JiNengBiao combat of its (category, level) row to the bucket
        named by tabshow (2 -> skill, 1 -> kangxin). Non-numeric combat
        formulas such as 'x*4' (level-0 rows) count as 0.
        """
        totals = [0, 0]
        for skill in skills or []:
            category = str(skill.get('category') or '')
            level = _int(skill.get('level'))
            row = next((r for r in self._jineng_rows()
                        if r.get('skilltype') == category
                        and _int(r.get('level')) == level), None)
            if row is None:
                continue
            bucket = {2: 0, 1: 1}.get(_int(row.get('tabshow')))
            if bucket is not None:
                totals[bucket] += _int(row.get('combat'))
        return totals

    def shenjiang_skill_upgrade_fight(self, shenjiang_rows):
        """Slot [6][2]: ZhanDouLiServiceImpl.getShenJiangSkill over owned shenjiang.

        Each row's skills map {skillCategory: level} adds the JiNengBiao combat
        of the matching (category, level) row.
        """
        total = 0
        for shenjiang in shenjiang_rows or []:
            try:
                skills = json.loads(shenjiang.get('skills') or '{}')
            except (TypeError, ValueError):
                continue
            if not isinstance(skills, dict):
                continue
            for category, level in skills.items():
                row = next((r for r in self._jineng_rows()
                            if r.get('skilltype') == str(category)
                            and _int(r.get('level')) == _int(level)), None)
                if row is not None:
                    total += _int(row.get('combat'))
        return total

    def equip_item_fight(self, item):
        """ZhanDouLiServiceImpl.getRoleEquipFight: getFight over one item's map.

        Every role_equip row is equipped gear, so the equip-category test
        always passes for migrated rows.
        """
        return self.fight_value(self.equip_attribute_map([item]))

    def shuxingdan_attribute_map(self, attribute_ids):
        """Permanent attribute-pill bonuses for AttributeBuff rows.

        Java resolves each role_attribute_buff.attribute_id through the dan
        config and folds the row into the SHUXINGDAN bag
        (RoleFactoryHelper.replaceShuxingdanAttribute).
        """
        table = self.shuxingdan_table()
        totals = {}
        for attribute_id in attribute_ids:
            row = table.get(str(attribute_id))
            if row is None:
                log.warning('attribute id %r has no shuxingdan row', attribute_id)
                continue
            for name in EQUIP_ATTRIBUTE_NAMES + ('perdamage', 'jiangu'):
                value = _number(row.get(name))
                if value:
                    totals[name] = totals.get(name, 0.0) + value
        return totals

    def mall_table(self):
        """WuPinChuShouBiao rows by modelid; empty when the file is absent."""
        if self._mall is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'WuPinChuShouBiao.jat')
            try:
                self._mall = load_mall_table(path) \
                    if os.path.isfile(path) else {}
            except ValueError as e:
                log.error('bad mall table: %s', e)
                self._mall = {}
        return self._mall

    def mall_sign(self):
        """The 32000 sign: None, exactly like Java.

        ClasspathConfigureLoader.loadSign returns [null, path] and
        AbsConfigureParser.init stores element 0, so the sign is null and
        MallServiceImpl always takes the full-list branch (the [-1, echo]
        path is unreachable: a null request takes the list branch first,
        and any string .equals(null) is false).
        """
        return None

    def mall_shop_list(self, category):
        """Raw mall rows for a modelid (the source map IS the row).

        WuPinChuShouConfig.setMap stores the raw .jat row and getAllData
        returns those maps, so the client entries are the rows themselves.
        """
        return list(self.mall_table().get(str(category), []))

    def mall_offer(self, sellid, npc_id):
        """Merged offer for a sellid at one npc, or None when not sold there.

        Mirrors loadById(sellid) + containsNpcId plus the resolve merge:
        rows sharing a sellid fold into one entity, each contributing its
        modelid to the npc map and its {moneytype: price} to the cost map
        (cheapest wins per type). Later non-empty losttime and positive
        duration overwrite, like the merge block. Unparseable prices are
        skipped instead of faked (shipped rows are clean).
        """
        offer = None
        for rows in self.mall_table().values():
            for row in rows:
                if str(row.get('sellid')) != str(sellid) or \
                        str(row.get('modelid')) != str(npc_id):
                    continue
                if offer is None:
                    offer = {'costs': {}, 'losttime': '', 'duration': 0}
                try:
                    price = int(row.get(
                        MALL_PRICE_COLUMNS.get(int(row.get('moneytype') or 0),
                                             '') or 0))
                    money = int(row.get('moneytype') or 0)
                except (TypeError, ValueError):
                    continue
                if money not in offer['costs'] or \
                        price < offer['costs'][money]:
                    offer['costs'][money] = price
                if str(row.get('losttime') or '').strip():
                    offer['losttime'] = row.get('losttime')
                try:
                    duration = int(row.get('duration') or 0)
                except (TypeError, ValueError):
                    duration = 0
                if duration > 0:
                    offer['duration'] = duration
        return offer

    def zuwu_table(self):
        """ZuWuShuxing.jat as {type: first jieshu==1 id}; empty if absent."""
        if self._zuwu is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'ZuWuShuxing.jat')
            try:
                self._zuwu = load_zuwu_table(path) \
                    if os.path.isfile(path) else {}
            except ValueError as e:
                log.error('bad zuwu table: %s', e)
                self._zuwu = {}
        return self._zuwu

    def zuwu_info(self):
        """111000 payload for a role with no owned zuwu: mock entries + 0 fragments.

        Port of ZuwuServiceImpl.getInfo over an empty RoleZuwu list: one
        mockZuwuInfo [id,0,0,0,type] per typeIdMaps member, then the
        wuhunsuipian bag count (0: no bag data is migrated).
        """
        return [[[zid, 0, 0, 0, kind]
                 for kind, zid in sorted(self.zuwu_table().items())], 0]

    def chat_level(self):
        """chat_level from config/localization.properties; 0 (no gate) when unreadable."""
        path = os.path.join(self.config_dir, '..', 'localization.properties')
        try:
            with open(path, encoding='utf-8') as f:
                for line in f:
                    key, _, value = line.partition('=')
                    if key.strip() == 'chat_level':
                        return int(value.strip())
        except (OSError, ValueError):
            log.warning('chat_level unreadable at %s; chat level gate off', path)
            return 0
        log.warning('chat_level missing from %s; chat level gate off', path)
        return 0

    def dazuo_table(self):
        """DaZuoPeiZhiBiao keyed by level; empty if absent."""
        if self._dazuo is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'DaZuoPeiZhiBiao.jat')
            try:
                self._dazuo = load_dazuo_table(path) \
                    if os.path.isfile(path) else {}
            except ValueError as e:
                log.error('bad dazuo table: %s', e)
                self._dazuo = {}
        return self._dazuo

    def dazuo_gain(self, level, flag_sum):
        """(exp, zhenqi) of a level row at a flag sum (1..4), or None when unlisted."""
        row = self.dazuo_table().get(int(level or 0))
        key = int(flag_sum)
        if row is None or key not in (1, 2, 3, 4):
            return None
        return row['exp'][key], row['zhenqi'][key]

    def xishu_table(self):
        """ZhanLiXiShu factors keyed by attribute name; empty if absent."""
        if self._xishu is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'ZhanLiXiShu.jat')
            try:
                self._xishu = load_xishu_table(path) \
                    if os.path.isfile(path) else {}
            except ValueError as e:
                log.error('bad zhanli xishu table: %s', e)
                self._xishu = {}
        return self._xishu

    def vip_table(self):
        """vipbiao.jat rows keyed by level (zhanli, vipbuff); empty if absent."""
        if self._vip is None:
            path = os.path.join(self.config_dir, 'sys_config', 'vipbiao.jat')
            try:
                self._vip = load_vip_table(path) \
                    if os.path.isfile(path) else {}
            except ValueError as e:
                log.error('bad vip table: %s', e)
                self._vip = {}
        return self._vip

    def vip_need_gold(self, vip_level):
        """VipInfoConfig.getVipConfigByLevel needGold for a level; 0 when absent."""
        try:
            row = self.vip_table().get(int(vip_level or 0))
            return int(row.get('needgold') or 0) if row else 0
        except (TypeError, ValueError):
            return 0

    def vip_level_for_gold(self, total):
        """Highest vip level whose needGold is at most total; 0 below the first row."""
        try:
            gold = int(total or 0)
        except (TypeError, ValueError):
            return 0
        best_level, best_need = 0, -1
        for level in self.vip_table():
            need = self.vip_need_gold(level)
            if best_need < need <= gold:
                best_level, best_need = level, need
        return best_level

    def vipqq_rewards(self):
        """Super-member reward parcels (chaojihuiyuan cell); empty if absent."""
        if self._vipqq is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'chaojihuiyuan.jat')
            try:
                cell = load_vipqq_rewards(path) \
                    if os.path.isfile(path) else ''
                self._vipqq = self._vip_parcels(cell)
            except ValueError as e:
                log.error('bad vipqq rewards: %s', e)
                self._vipqq = []
        return self._vipqq

    def vip_hecheng(self, vip_level):
        """VipConfig.getHecheng for a level (vipbiao's hechengci cell)."""
        try:
            row = self.vip_table().get(int(vip_level or 0))
        except (TypeError, ValueError):
            return 0
        if not row:
            return 0
        try:
            return int(row.get('hechengci') or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _vip_parcels(cell):
        """vipbiao gift cell 'gid:count:bind[:expire][;...]' to tuples.

        The 4th expire-hours field has no _task_grant counterpart, so it
        is parsed and dropped (documented with the grant call).
        """
        out = []
        for part in str(cell or '').split(';'):
            fields = part.split(':')
            if len(fields) < 3 or not fields[0]:
                continue
            try:
                out.append((fields[0], int(fields[1]), int(fields[2])))
            except (TypeError, ValueError):
                continue
        return out

    def vip_gifts(self, vip_level):
        """VipConfig day/week/tejia gifts for a level (vipbiao cells)."""
        try:
            row = self.vip_table().get(int(vip_level or 0))
        except (TypeError, ValueError):
            return None
        if not row:
            return None
        try:
            price = int(row.get('specialprice') or 0)
        except (TypeError, ValueError):
            price = 0
        return {'daybag': self._vip_parcels(row.get('daybag')),
                'weekbag': self._vip_parcels(row.get('weekbag')),
                'libaoid': self._vip_parcels(row.get('libaoid')),
                'specialprice': price}

    def vip_choujiang(self):
        """vipchoujiang.jat: prize rows by id plus day window and vip floor.

        kaifuday/needvipLv are row-statics (last row wins, as Java
        overwrites them per parsed row); the lottery map covers every
        row unfiltered.
        """
        if self._vip_choujiang is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'vipchoujiang.jat')
            try:
                rows = _load(path) if os.path.isfile(path) else []
            except ValueError as e:
                log.error('bad vip choujiang table: %s', e)
                rows = []
            prizes, day, floor = {}, [0, 0], 0
            for r in rows:
                if not isinstance(r, dict):
                    continue
                try:
                    pid = int(r.get('id'))
                except (TypeError, ValueError):
                    continue
                try:
                    rate = float(r.get('rate') or 0)
                except (TypeError, ValueError):
                    continue
                prizes[pid] = {
                    'rate': rate,
                    'item': self._vip_parcels(r.get('item'))[:1] or [(None, 0,
                                                                     0)]}
                try:
                    floor = int(r.get('vip') or 0)
                except (TypeError, ValueError):
                    pass
                try:
                    lo, _, hi = str(r.get('time') or '').partition('-')
                    day = [int(lo), int(hi)]
                except (TypeError, ValueError):
                    pass
            self._vip_choujiang = {'prizes': prizes, 'kaifuday': day,
                                   'needvip': floor}
        return self._vip_choujiang

    def vip_lingjiang(self, reward_id):
        """viplingjiang.jat row for an id: kaifu day plus one parcel."""
        if self._vip_lingjiang is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'viplingjiang.jat')
            try:
                rows = _load(path) if os.path.isfile(path) else []
            except ValueError as e:
                log.error('bad vip lingjiang table: %s', e)
                rows = []
            self._vip_lingjiang = {}
            for r in rows:
                if not isinstance(r, dict):
                    continue
                try:
                    rid = int(r.get('id'))
                    day = int(r.get('date'))
                except (TypeError, ValueError):
                    continue
                parcels = self._vip_parcels(r.get('item'))
                if parcels:
                    self._vip_lingjiang[rid] = {'date': day,
                                               'item': parcels[0]}
        try:
            return self._vip_lingjiang.get(int(reward_id))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _huodong_parcels(cell):
        """kaifuchoujiang goods cell 'gid:count[:bind][...]' to tuples.

        Port of convertGoodsesStrs2List2/3's head fields: only goods,
        count and bind feed putInBag; later segments (expire hours,
        qianghua pairs) have no grant counterpart and are dropped,
        like _vip_parcels. A non-positive count nulls like Java.
        """
        if not cell:
            return None
        out = []
        for part in str(cell).split(';'):
            fields = part.split(':')
            if len(fields) < 2 or not fields[0]:
                continue
            try:
                count = int(fields[1])
            except (TypeError, ValueError):
                continue
            if count <= 0:
                return None
            try:
                bind = int(fields[2]) if len(fields) > 2 else 0
            except (TypeError, ValueError):
                bind = 0
            out.append((fields[0], count, bind))
        return out or None

    def vip_huodong(self, vip_level):
        """kaifuchoujiang.jat row for a vip: window, bisong, odds, prizes.

        'time' is 'lo;hi' kaifu days; jilvN/jiangpinN (N 1..8) build the
        uniform-pick odds map and the prize map.
        """
        if self._vip_huodong is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'kaifuchoujiang.jat')
            try:
                rows = _load(path) if os.path.isfile(path) else []
            except ValueError as e:
                log.error('bad vip huodong table: %s', e)
                rows = []
            self._vip_huodong = {}
            for r in rows:
                if not isinstance(r, dict):
                    continue
                try:
                    vip = int(r.get('vip'))
                except (TypeError, ValueError):
                    continue
                try:
                    lo, _, hi = str(r.get('time') or '').partition(';')
                    window = [int(lo), int(hi)]
                except (TypeError, ValueError):
                    window = [0, 0]
                odds, prizes = {}, {}
                for index in range(1, 9):
                    try:
                        rate = float(r.get(f'jilv{index}'))
                    except (TypeError, ValueError):
                        continue
                    goods = self._huodong_parcels(r.get(f'jiangpin{index}'))
                    if goods is None:
                        continue
                    odds[index] = rate
                    prizes[index] = goods
                self._vip_huodong[vip] = {
                    'window': window,
                    'bisong': self._huodong_parcels(r.get('bisong')),
                    'odds': odds, 'prizes': prizes}
        try:
            return self._vip_huodong.get(int(vip_level))
        except (TypeError, ValueError):
            return None

    def vip_fight(self, vip_level):
        """VipConfig.getZhanli for a level (vipZHanLi); 0 when unlisted."""
        row = self.vip_table().get(int(vip_level or 0))
        return int(row.get('zhanli') or 0) if row else 0

    def vip_buff_id(self, vip_level):
        """Buff id for a VIP level (vipbiao's vipbuff cell), or None.

        Port of RoleFactoryHelper.replaceVipAttribute's lookup: the
        VipConfig row's getVipBuff cell, applied as a BuffManager buff.
        Level 0 carries vipbuff 0 and unlisted levels carry nothing, so
        both send no buff, exactly Java's empty-source behavior.
        """
        try:
            level = int(vip_level or 0)
        except (TypeError, ValueError):
            return None
        if level <= 0:
            return None
        row = self.vip_table().get(level)
        buff_id = str(row.get('vipbuff') or '') if row else ''
        if not buff_id or buff_id == '0':
            return None
        return buff_id if self.buff_effect(buff_id) is not None else None

    def vip_effect_slots(self, vip_level):
        """Effect-slot map a VIP level's buff writes ({slot: value}).

        Port of BuffConfigExportServiceImpl.createBuffAttributes over the
        vipbuff's XiaoGuoBiao row: keys are the effectpro1..5 cells
        (the numbered slots the formulas read: 5 flat attack, 7 flat
        defence, 1 flat maxHp, 14 attack-speed %, 16 move-speed %), values
        are the effectproNvalue1 cells. Empty cells contribute nothing.
        """
        buff_id = self.vip_buff_id(vip_level)
        if buff_id is None:
            return {}
        row = self.buff_effect(buff_id)
        slots = {}
        for i in range(1, 6):
            slot = row.get('effectpro%d' % i)
            if slot in ('', None):
                continue
            try:
                value = float(row.get('effectpro%dvalue1' % i) or 0)
            except (TypeError, ValueError):
                continue
            slots[str(slot)] = value
        return slots

    def xianjie_table(self):
        """xianjie.jat rows by id; empty when the file is absent."""
        if self._xianjie is None:
            path = os.path.join(self.config_dir, 'sys_config', 'xianjie.jat')
            try:
                self._xianjie = load_xianjie_table(path) \
                    if os.path.isfile(path) else {}
            except ValueError as e:
                log.error('bad xianjie table: %s', e)
                self._xianjie = {}
        return self._xianjie

    def xianjie_attribute_map(self, xianjie_id):
        """XianJieConfig.getShuxing bag for one xianjie id.

        Port of replaceXianJieAttribute's incrBaseAttribute(XIANJIE, map):
        the row's shuxing 'k:v;k:v' string parsed to floats. Unknown ids
        yield no bag, exactly Java's missing-config behavior.
        """
        row = self.xianjie_table().get(str(xianjie_id or ''))
        if row is None:
            log.warning('xianjie %r has no config row; skipped', xianjie_id)
            return {}
        return parse_att_string(row.get('shuxing'))

    def chenghao_table(self):
        """chenghao.jat rows by chenghaoid; empty when the file is absent."""
        if self._chenghao is None:
            path = os.path.join(self.config_dir, 'sys_config', 'chenghao.jat')
            try:
                self._chenghao = load_chenghao_table(path) \
                    if os.path.isfile(path) else {}
            except ValueError as e:
                log.error('bad chenghao table: %s', e)
                self._chenghao = {}
        return self._chenghao

    def chenghao_attribute_map(self, chenghao_ids):
        """Summed ChengHaoConfig.getAttribute bags for chenghao ids.

        Port of replaceChengHaoAttribute's MapUtil.addMapValue loop over
        chenHaoIds: each row's shuxingjiacheng string parsed and added.
        Unknown ids are skipped, not faked.
        """
        totals = {}
        for chenghao_id in chenghao_ids or []:
            row = self.chenghao_table().get(str(chenghao_id))
            if row is None:
                log.warning('chenghao %r has no config row; skipped',
                            chenghao_id)
                continue
            for key, value in parse_att_string(
                    row.get('shuxingjiacheng')).items():
                totals[key] = totals.get(key, 0.0) + value
        return totals

    def meiren_table(self):
        """meiren.jat as ({meinvid: (type, level)}, {type: {level: bag}})."""
        if self._meiren is None:
            path = os.path.join(self.config_dir, 'sys_config', 'meiren.jat')
            try:
                self._meiren = load_meiren_table(path) \
                    if os.path.isfile(path) else ({}, {})
            except ValueError as e:
                log.error('bad meiren table: %s', e)
                self._meiren = ({}, {})
        return self._meiren

    def meiren_attribute_map(self, pairs):
        """Summed MeiRenConfig.getAttribtueMap bags for [(type, chanmian)].

        Port of replaceMeirenAttribute: each owned meiren resolves its
        type's level row by chanmianCount (meirenLevelMap.get) and adds
        the row's bag. Missing types or levels are logged and skipped,
        exactly Java's '{} meiren config is null' path.
        """
        _, types = self.meiren_table()
        totals = {}
        for meiren_type, chanmian in pairs or []:
            try:
                level = int(chanmian)
            except (TypeError, ValueError):
                continue
            bag = types.get(str(meiren_type), {}).get(level)
            if not bag:
                log.warning('meiren %r level %r has no config row; skipped',
                            meiren_type, chanmian)
                continue
            for key, value in bag.items():
                totals[key] = totals.get(key, 0.0) + value
        return totals

    def zuoqi_attribute_map(self, max_rank, role_level):
        """ZuoQiLevelConfig bag for a mount rank at a role level.

        Port of RoleFactoryHelper.replaceZuoqiAttribute: the gate is
        business maxRank (RoleZuoqi.rank via ZuoQiWrapper, set only when
        > 0 in RoleFactory.create), the level row is loadByRank(rank) at
        getZuoqiLevel (role level clamped to [0, maxlv]; minLevel is never
        set in the jar so the floor is 0), and the bag is the row's
        attribute2Map minus velocity (ConfigAnalyzeUtil-
        .refineAttributeMapWithOutMoveGongjiSp drops only that key). The
        attribute-goods multiplier path is unwired: no migrated role
        carries attribute_goods_id, so its map is always empty here.
        """
        try:
            rank = int(max_rank or 0)
        except (TypeError, ValueError):
            return {}
        if rank <= 0:
            return {}
        table = self.zuoqi_table()
        maxlv = next((int(r.get('maxlv') or 0)
                      for (rk, _lv), r in table.items() if rk == rank), None)
        if maxlv is None:
            log.warning('zuoqi rank %r has no config row; skipped', max_rank)
            return {}
        try:
            level = max(0, min(int(role_level or 0), maxlv))
        except (TypeError, ValueError):
            return {}
        row = table.get((rank, level))
        if row is None:
            log.warning('zuoqi rank %r level %r has no config row; skipped',
                        rank, level)
            return {}
        bag = {name: _number(row.get(name)) for name in MEIREN_ATTRIBUTE_NAMES
               if _number(row.get(name))}
        bag.pop('velocity', None)
        return bag

    def zuoqi_rank_config(self, rank):
        """ZuoQiConfig fields for a mount rank, or None when unconfigured.

        Port of createZuoQiConfig over the rank's first ZuoJiBiao row in
        file order (configureDataResolve creates the rank object from the
        first row seen for a stratum): id/rideid, type/ridetype, name,
        rank/int(stratum), cailiao from needthingsid/value, needLevel from
        needleaderlv, upgradeJb from jinjieneedcoin, luckyYb from
        qxlzneedgold, luckyClear, maxLevel from maxlv (minLevel is never
        set, so the floor is 0 as in getZuoqiLevel).
        """
        try:
            rank = int(rank)
        except (TypeError, ValueError):
            return None
        row = next((r for (rk, _lv), r in self.zuoqi_table().items()
                    if rk == rank), None)
        if row is None:
            return None
        return {'id': str(row.get('rideid') or ''),
                'type': str(row.get('ridetype') or ''),
                'name': str(row.get('name') or ''),
                'rank': rank,
                'cailiao_id': str(row.get('needthingsid') or ''),
                'cailiao_count': config_int(row.get('needthingsvalue')),
                'need_level': config_int(row.get('needleaderlv')),
                'upgrade_jb': config_int(row.get('jinjieneedcoin')),
                'lucky_yb': config_int(row.get('qxlzneedgold')),
                'lucky_clear': bool(row.get('luckyclear')),
                'max_level': config_int(row.get('maxlv'))}

    def zuoqi_max_rank(self):
        """Highest configured mount rank (setMaxMinRank over the table)."""
        ranks = [rk for (rk, _lv) in self.zuoqi_table()]
        return max(ranks) if ranks else 0

    def zuoqi_level_config(self, rank, level):
        """ZuoQiLevelConfig fields for a (rank, level) row, or None.

        Port of createLevelConfig: min/maxTimes from mintims/maxtimes,
        odds, upgradeZhufu from maxblessing, notice, min/maxZhufu from
        addmin/addmaxblessing.
        """
        try:
            row = self.zuoqi_table().get((int(rank), int(level)))
        except (TypeError, ValueError):
            return None
        if row is None:
            return None
        return {'level': config_int(row.get('ridelv')),
                'min_times': config_int(row.get('mintims')),
                'max_times': config_int(row.get('maxtimes')),
                'odds': _number(row.get('odds')),
                'upgrade_zhufu': config_int(row.get('maxblessing')),
                'notice': bool(row.get('notice')),
                'min_zhufu': config_int(row.get('addminblessing')),
                'max_zhufu': config_int(row.get('addmaxblessing'))}

    def kaifu_zuoqi_table(self):
        """kaifuzuoqi.jat rows (KaifuZuoqiConfig list); empty when absent."""
        if self._kaifu_zuoqi is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'kaifuzuoqi.jat')
            try:
                if os.path.isfile(path):
                    with open(path, 'rb') as f:
                        rows = amf3_decode(f.read())
                else:
                    rows = []
            except ValueError as e:
                log.error('bad kaifuzuoqi table: %s', e)
                rows = []
            self._kaifu_zuoqi = [r for r in rows or []
                                 if isinstance(r, dict)]
        return self._kaifu_zuoqi

    def kaifu_zuoqi_config(self, rank):
        """KaifuZuoqiConfig row for a mount rank (keyed by jieshu), or None.

        Port of loadConfig: the primary key is zuoqiRank, so a rank with
        no row (5+ in the shipped table) is outside kaifu like a null.
        """
        try:
            rank = int(rank)
        except (TypeError, ValueError):
            return None
        for row in self.kaifu_zuoqi_table():
            try:
                if int(row.get('jieshu')) == rank:
                    return {'rank': rank,
                            'last_days': config_int(row.get('time')),
                            'return_goods': bool(row.get('fanhuan')),
                            'meiren': str(row.get('meiren') or ''),
                            'expire_hours': config_int(row.get('guoqi'))}
            except (TypeError, ValueError):
                continue
        return None

    def kaifu_zuoqi_fanhuan(self):
        """First kaifu row with fanhuan set (loadFanhuanConfig), or None."""
        for row in self.kaifu_zuoqi_table():
            if row.get('fanhuan'):
                return self.kaifu_zuoqi_config(row.get('jieshu'))
        return None

    def kaifu_zuoqi_meiren(self):
        """First kaifu row with a meiren id (loadMeirenConfig), or None.

        The resolve maps empty cells to null (obj2StrOrNull), so only a
        non-empty cell counts, like the fanhuan accessor above.
        """
        for row in self.kaifu_zuoqi_table():
            if row.get('meiren'):
                return self.kaifu_zuoqi_config(row.get('jieshu'))
        return None

    def zuoqi_fail_rates(self, rank, level):
        """Fail-exp lottery entries for a (rank, level) row as (type, rate, exp).

        Port of the RateScope build in createLevelConfig: zcfailaddexp is
        type 0, xbjfailaddexp type 1, dbjfailaddexp type 2, each a
        'rate|exp' string; empty cells contribute nothing. The caller rolls
        randomZuoqiRate over these weights.
        """
        try:
            row = self.zuoqi_table().get((int(rank), int(level)))
        except (TypeError, ValueError):
            return []
        if row is None:
            return []
        entries = []
        for kind, key in ((0, 'zcfailaddexp'), (1, 'xbjfailaddexp'),
                          (2, 'dbjfailaddexp')):
            cell = str(row.get(key) or '')
            if '|' not in cell:
                continue
            rate_s, _, exp_s = cell.partition('|')
            try:
                entries.append((kind, float(rate_s), int(exp_s)))
            except (TypeError, ValueError):
                continue
        return entries

    def zhujue_zq_fail_max_exp(self, level):
        """ZhuJueShuXingBiao.zqjjsbaddmaxexp for a role level (jinjie cap)."""
        if self._zhujue_zqmax is None:
            path = os.path.join(self.config_dir, 'sys_config',
                                'ZhuJueShuXingBiao.jat')
            try:
                rows = _load(path) if os.path.isfile(path) else []
            except ValueError as e:
                log.error('bad zhujue shuxing table: %s', e)
                rows = []
            self._zhujue_zqmax = {}
            for r in rows:
                if not isinstance(r, dict):
                    continue
                try:
                    self._zhujue_zqmax[int(r.get('level'))] = int(
                        r.get('zqjjsbaddmaxexp') or 0)
                except (TypeError, ValueError):
                    continue
        try:
            return self._zhujue_zqmax.get(int(level), 0)
        except (TypeError, ValueError):
            return 0

    def goods_specialtype_substitutes(self, goods_id, rank):
        """Substitute pill ids for a jinjie material at a mount rank.

        Port of getGoodsSpecialtypeConfig: a goods with null/0 specialtype
        substitutes only itself; otherwise every goods sharing the
        specialtype whose specialVal fits the rank qualifies. specialVal is
        zuoqiLv for type 1 (bytecode) and qibinglv for type 2; higher types
        have no verified column mapping, so they substitute only
        themselves. Order follows the goods table (config load order).
        Returns None when the goods id is unknown.
        """
        table = self._goods_table()
        row = table.get(str(goods_id))
        if row is None:
            return None
        try:
            special = int(row.get('specialtype') or 0)
        except (TypeError, ValueError):
            special = 0
        if not special:
            return [str(goods_id)]
        key = {1: 'zuoqilv', 2: 'qibinglv'}.get(special)
        if key is None:
            return [str(goods_id)]
        try:
            rank = int(rank)
        except (TypeError, ValueError):
            return []
        subs = []
        for gid, grow in table.items():
            try:
                if int(grow.get('specialtype') or 0) != special:
                    continue
                if int(grow.get(key) or 0) > rank:
                    continue
            except (TypeError, ValueError):
                continue
            subs.append(str(gid))
        return subs

    def zuoqi_fight(self, max_rank, role_level):
        """ZhanDouLiServiceImpl.getZuoQiJiChuFight for a mount rank/level.

        getFight over loadByRankLevel(getZuoQiRank, roleLevel)-
        .getAttributeMap: rank 0 (or a missing row) yields null, hence 0.
        The attributeMap field IS ConfigAttributeParser.attribute2Map
        (createLevelConfig), so this reuses zuoqi_attribute_map; velocity
        needs no special-casing here because its ZhanLiXiShu factor is
        0.0, making the refined bag and the raw map agree exactly.
        """
        return self.fight_value(self.zuoqi_attribute_map(max_rank, role_level))

    def zuoqi_equip_fight(self, items):
        """ZhanDouLiServiceImpl.getZuoEquipFight over a role's equip rows.

        getFight over getEquipAttributeAll (one merged map, one
        truncation) of the rows in the zuoqi slot range
        (EquipConstants.ZUOQI_SLOT_MIN/MAX = -105/-100, inclusive
        EquipSlotBetweenFilter). No legacy role_equip_slot row falls in
        that range, so this is 0 for every migrated role.
        """
        zuoqi_items = [item for item in items or []
                       if -105 <= int(item.get('slot_num') or 0) <= -100]
        return self.fight_value(self.equip_attribute_map(zuoqi_items))

    def meiren_type_for(self, meiren_id):
        """meinvtype for a meiren.jat meinvid, or None when unlisted.

        Port of getMeiRenConfigByMeiRenId(String).getMeirenTypeId: the
        business object's id is the config type, and rows whose meinvid
        has no config are dropped (getMeiRenAllObj skips them).
        """
        by_id, _ = self.meiren_table()
        entry = by_id.get(str(meiren_id or ''))
        return entry[0] if entry else None

    def fight_value(self, attr_map):
        """ZhanDouLiServiceImpl.getFight: int-accumulated value*factor.

        Skips attributes with no xishu row. Caveat: Java iterates a
        HashMap, so multi-fractional maps can differ by truncation order
        (bounded, +-cycles); all-int maps like the level row are exact.
        """
        xishu = self.xishu_table()
        total = 0
        for name, value in (attr_map or {}).items():
            factor = xishu.get(str(name))
            if factor is None:
                continue
            total = int(total + float(value or 0) * factor)
        return total

    def level_fight(self, row):
        """getRoleLevelFight: getFight over the level row's combat keys."""
        return self.fight_value({k: v for k, v in (row or {}).items()})

    def equip_fight_parts(self, items):
        """(base, qianghua, fujia) fight ints over equipped items.

        Port of getRoleEquipBaseFighting/getRoleEquipQianghuaFighting/
        getRoleEquipFuJiaFight: per item getFight(base*rate),
        getFight(stars*rate), getFight(fujia), each truncated per item.
        """
        table = self.equip_table()
        base, qianghua, fujia = 0, 0, 0
        for item in items or []:
            row = table.get(str(item.get('goods_id')))
            if row is None:
                continue
            rate = _number(row.get('%sjichubili' % int(item.get('rare_level') or 0))) or 1.0
            stars, pairs = parse_item_attributes(item.get('attributes'))
            base_map, qh_map = {}, {}
            for name in EQUIP_ATTRIBUTE_NAMES:
                plain = _number(row.get(name))
                if plain:
                    base_map[name] = plain * rate
                extra = sum(_number(row.get('star%d%s' % (star, name)))
                            for star in stars)
                if extra:
                    qh_map[name] = extra * rate
            base += self.fight_value(base_map)
            qianghua += self.fight_value(qh_map)
            fujia += self.fight_value(
                self.fujia_attribute_map(pairs, row.get('level')))
        return base, qianghua, fujia

    def dan_fight(self, buffs):
        """getAttributeDanFight: row values times count, accumulated."""
        table = self.shuxingdan_table()
        merged = {}
        for buff in buffs or []:
            row = table.get(str(buff.get('attribute_id')))
            if row is None:
                continue
            count = buff.get('count') or 0
            for name in EQUIP_ATTRIBUTE_NAMES + ('perdamage', 'jiangu'):
                value = _number(row.get(name)) * count
                if value:
                    merged[name] = merged.get(name, 0.0) + value
        return self.fight_value(merged)

    def monster_templates(self):
        """Monster template rows from sys_config/GuaiWuBiao.jat, keyed by template id."""
        if self._templates is None:
            path = os.path.join(self.config_dir, 'sys_config', 'GuaiWuBiao.jat')
            rows = _load(path) if os.path.isfile(path) else []
            self._templates = {str(r['id']): r for r in rows
                               if isinstance(r, dict) and r.get('id')}
        return self._templates

    def monster_spawn_cells(self, map_id):
        """Spawn cells whose monsters Java can create (template row required).

        These cells are BEING-taken on stage entry, which is what
        getSurroundValidPoint skips when placing a mount pet.
        """
        templates = self.monster_templates()
        cells = set()
        for group in self.monsters(map_id):
            if templates.get(str(group.get('id'))) is None:
                continue
            for x, y, _dir in group.get('createPoints') or []:
                cells.add((int(x), int(y)))
        return cells

    def surround_valid_point(self, map_id, x, y, occupied=()):
        """Java's AoiStage.getSurroundValidPoint(point, false, BEING).

        Returns the first walkable, untaken surround in A_EXTEND_OFFS order,
        or None when the start cell has no PathNode (unwalkable/missing map).
        Java random-walks when every surround is taken; without a scene
        simulation this returns the original point, the same fallback Java's
        wrapper uses when the search fails.
        """
        grid = self.path_grid(map_id)
        if grid is None or not grid.walkable(x, y):
            return None
        taken = {(int(a), int(b)) for a, b in occupied}
        for dx, dy in A_EXTEND_OFFS:
            nx, ny = x + dx, y + dy
            if grid.walkable(nx, ny) and (nx, ny) not in taken:
                return nx, ny
        return x, y

    def monster_snapshot(self, map_id):
        """23002 monster records for a map: one per spawn point, template stats from GuaiWuBiao.

        Positions are the spawn points, not live positions; monsters that move
        later are not tracked. Spawn groups with no template row are skipped and logged.
        """
        templates = self.monster_templates()
        records = []
        for group in self.monsters(map_id):
            tpl = templates.get(str(group.get('id')))
            if tpl is None:
                log.warning('map %s: spawn group %r has no template; skipped',
                            map_id, group.get('id'))
                continue
            hp = tpl.get('hitpoints')
            mp = tpl.get('mana')
            speed = tpl.get('velocity')
            for x, y, _dir in group.get('createPoints') or []:
                n = len(records)
                # Layout copied from a captured 23002 record (output/orig-stack/tap-decoded.txt).
                # Verified: 0-4 (id, template, name, level, hp), 11-12 (x, y against spawn points).
                # Assumed: 5-9 (maxhp, mp, maxmp, speed = template velocity). Constants at
                # 10, 13-17 are copied from the capture; their meaning is unverified.
                records.append([f'm_{map_id}_{n}', tpl['id'], tpl.get('name'),
                                tpl.get('level'), hp, hp, mp, mp, speed, speed,
                                0, x, y, 0, None, False, None, 0])
        return records

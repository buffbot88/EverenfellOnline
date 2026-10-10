"""Loaders for the legacy binary config tables the Java server reads.

  sys_config/MapLine.jat     -> per-map MapLineConfig rows (maptype, maxlinevalue, ...)
  map_config/<id>/monster.mm -> per-map monster spawn groups

Both are AMF3 serialized (see amf3.py). The loader is read-only and never
edits the tables; it only reports what the legacy server would load.
"""
import logging
import os
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


def load_equip_attribute_table(path):
    """Rows of sys_config/ZhuangBeiFuJiaShuXingBiao.jat keyed by goods id.

    This is EquipFuJiaAttributeConfig: the flat base columns, the Njichubili
    rank rates and the starN<attr> 强化 columns EquipAttributeService reads.
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


def load_vip_table(path):
    """Rows of sys_config/vipbiao.jat keyed by vip level."""
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of vip rows')
    return {int(r['lv']): r for r in rows
            if isinstance(r, dict) and r.get('lv') is not None}


def load_shuxingdan_table(path):
    """Rows of sys_config/shuxingdan.jat (permanent attribute pills) by id."""
    rows = _load(path)
    if not isinstance(rows, list):
        raise ValueError(f'{path}: expected a list of shuxingdan rows')
    return {str(r['id']): r for r in rows if isinstance(r, dict) and r.get('id')}


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
        self._vip = None

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
        """Random 附加 affix bonuses for one item's fujia pairs at its fujia level.

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
        """Cache-buster for 32000: the mall row count as a string.

        Java compares the client's sign against a framework-computed config
        sign whose exact derivation is unresolved; any deterministic value
        preserves the behavior (mismatch -> full list, match -> [-1, echo]).
        """
        return str(sum(len(items) for items in self.mall_table().values()))

    def mall_shop_list(self, category):
        """Raw mall rows for a modelid (the source map IS the row).

        WuPinChuShouConfig.setMap stores the raw .jat row and getAllData
        returns those maps, so the client entries are the rows themselves.
        """
        return list(self.mall_table().get(str(category), []))

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

    def vip_fight(self, vip_level):
        """VipConfig.getZhanli for a level (vipZHanLi); 0 when unlisted."""
        row = self.vip_table().get(int(vip_level or 0))
        return int(row.get('zhanli') or 0) if row else 0

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

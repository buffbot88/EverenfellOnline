"""Loaders for the legacy binary config tables the Java server reads.

  sys_config/MapLine.jat     -> per-map MapLineConfig rows (maptype, maxlinevalue, ...)
  map_config/<id>/monster.mm -> per-map monster spawn groups

Both are AMF3 serialized (see amf3.py). The loader is read-only and never
edits the tables; it only reports what the legacy server would load.
"""
import logging
import os

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


class GameConfig:
    """Lazily loads the legacy tables from a config directory; missing files are reported, not faked."""

    def __init__(self, config_dir=DEFAULT_CONFIG_DIR):
        self.config_dir = config_dir
        self._map_lines = None
        self._monsters = {}
        self._templates = None

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

    def monsters(self, map_id):
        """Monster spawn records for a map (empty list if the map has no monster.mm)."""
        key = str(map_id)
        if key not in self._monsters:
            path = os.path.join(self.config_dir, 'map_config', key, 'monster.mm')
            self._monsters[key] = load_monsters(path) if os.path.isfile(path) else []
        return self._monsters[key]

    def monster_templates(self):
        """Monster template rows from sys_config/GuaiWuBiao.jat, keyed by template id."""
        if self._templates is None:
            path = os.path.join(self.config_dir, 'sys_config', 'GuaiWuBiao.jat')
            rows = _load(path) if os.path.isfile(path) else []
            self._templates = {str(r['id']): r for r in rows
                               if isinstance(r, dict) and r.get('id')}
        return self._templates

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

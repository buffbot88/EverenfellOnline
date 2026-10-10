"""SQLite persistence for accounts, characters, sessions, and game state."""
import os
import sqlite3
import threading
import time

SCHEMA = '''
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  pass_hash TEXT NOT NULL,
  created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  uid TEXT NOT NULL,
  created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS role_settings (
  role_id INTEGER PRIMARY KEY,
  quickbar_info TEXT,
  panel_config BLOB,
  ui_info BLOB,
  guaji_info BLOB,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Mirrors the legacy MySQL `role_stage` table (see docs/mysql-to-sqlite-migration.md).
-- Stage/stat/live-state columns live here instead of growing `characters`.
CREATE TABLE IF NOT EXISTS role_stage (
  role_id INTEGER PRIMARY KEY,
  map_id TEXT,
  map_x INTEGER,
  map_y INTEGER,
  line_no INTEGER DEFAULT 0,
  hp INTEGER,
  mp INTEGER,
  max_hp INTEGER,
  max_mp INTEGER,
  buff TEXT,
  props TEXT,
  state INTEGER DEFAULT 0,
  map_node TEXT,
  ti_li INTEGER DEFAULT 0,
  shanbi_val INTEGER DEFAULT 0,
  pk_info TEXT,
  meiren_info TEXT,
  zuoqi_info TEXT,
  copy_info TEXT,
  free_fly_count INTEGER DEFAULT 0,
  fly_count_refresh_time INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS role_equip (
  role_id INTEGER NOT NULL,
  slot_num INTEGER NOT NULL,
  goods_id TEXT NOT NULL,
  rare_level INTEGER DEFAULT 0,
  item_level INTEGER DEFAULT 0,
  attributes TEXT,
  PRIMARY KEY(role_id, slot_num),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS role_attr_buff (
  role_id INTEGER NOT NULL,
  attribute_id TEXT NOT NULL,
  count INTEGER DEFAULT 0,
  PRIMARY KEY(role_id, attribute_id),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS role_vip (
  role_id INTEGER PRIMARY KEY,
  vip_level INTEGER DEFAULT 0,
  state_day INTEGER DEFAULT 0,
  state_week INTEGER DEFAULT 0,
  state_tejia TEXT,
  prop_value INTEGER DEFAULT 0,
  tody_prop_value INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS characters (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  legacy_id TEXT,
  account TEXT NOT NULL,
  server_id TEXT NOT NULL,
  name TEXT NOT NULL,
  job TEXT NOT NULL DEFAULT 'A',
  sex INTEGER NOT NULL DEFAULT 0,
  face TEXT DEFAULT '',
  level INTEGER NOT NULL DEFAULT 1,
  exp INTEGER,
  map_id TEXT,
  map_x INTEGER,
  map_y INTEGER,
  hp INTEGER,
  mp INTEGER,
  max_hp INTEGER,
  max_mp INTEGER,
  tongqian INTEGER,
  bind_lingshi INTEGER,
  lingshi INTEGER,
  recive_yb INTEGER,
  zhenqi INTEGER,
  shengwang INTEGER,
  created INTEGER NOT NULL,
  UNIQUE(account, server_id, name)
);
'''

# Columns that may be added to an existing characters table.
CHARACTER_COLUMNS = {
    'legacy_id': 'TEXT',
    'level': 'INTEGER NOT NULL DEFAULT 1',
    'exp': 'INTEGER',
    'map_id': 'TEXT',
    'map_x': 'INTEGER',
    'map_y': 'INTEGER',
    'hp': 'INTEGER',
    'mp': 'INTEGER',
    'max_hp': 'INTEGER',
    'max_mp': 'INTEGER',
    'tongqian': 'INTEGER',
    'bind_lingshi': 'INTEGER',
    'lingshi': 'INTEGER',
    'recive_yb': 'INTEGER',
    # user_role.zhenqi/shengwang (UserRole entity; the migrator already reads
    # both but only stored them once these columns existed).
    'zhenqi': 'INTEGER',
    'shengwang': 'INTEGER',
}

# role_stage columns accepted by save_role_stage (legacy MySQL names).
STAGE_COLUMNS = {
    'map_id': 'TEXT',
    'map_x': 'INTEGER',
    'map_y': 'INTEGER',
    'line_no': 'INTEGER',
    'hp': 'INTEGER',
    'mp': 'INTEGER',
    'max_hp': 'INTEGER',
    'max_mp': 'INTEGER',
    'buff': 'TEXT',
    'props': 'TEXT',
    'state': 'INTEGER',
    'map_node': 'TEXT',
    'ti_li': 'INTEGER',
    'shanbi_val': 'INTEGER',
    'pk_info': 'TEXT',
    'meiren_info': 'TEXT',
    'zuoqi_info': 'TEXT',
    'copy_info': 'TEXT',
    'free_fly_count': 'INTEGER',
    'fly_count_refresh_time': 'INTEGER',
}


class Store:
    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)
            present = {row['name'] for row in self.db.execute(
                'PRAGMA table_info(characters)')}
            for name, declaration in CHARACTER_COLUMNS.items():
                if name not in present:
                    self.db.execute(
                        f'ALTER TABLE characters ADD COLUMN {name} {declaration}')
            self.db.commit()

    def create_account(self, username, pass_hash):
        with self.lock:
            try:
                self.db.execute(
                    'INSERT INTO accounts(username, pass_hash, created) VALUES(?,?,?)',
                    (username, pass_hash, int(time.time())))
                self.db.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def create_session(self, token, uid):
        with self.lock:
            self.db.execute(
                'INSERT OR REPLACE INTO sessions(token, uid, created) VALUES(?,?,?)',
                (token, uid, int(time.time())))
            self.db.commit()

    def get_session(self, token):
        with self.lock:
            row = self.db.execute(
                'SELECT token, uid, created FROM sessions WHERE token=?',
                (token,)).fetchone()
            return dict(row) if row else None

    def get_account(self, username):
        with self.lock:
            row = self.db.execute(
                'SELECT * FROM accounts WHERE username=?', (username,)).fetchone()
            return dict(row) if row else None

    def close(self):
        with self.lock:
            self.db.close()

    def create_character(self, account, server_id, name, job='A', sex=0,
                         face='', **state):
        """Insert a character and supplied authoritative state; returns its id."""
        unknown = set(state) - set(CHARACTER_COLUMNS)
        if unknown:
            raise ValueError(f'unknown character state fields: {sorted(unknown)}')
        fields = ['account', 'server_id', 'name', 'job', 'sex', 'face',
                  *state.keys(), 'created']
        values = [account, server_id, name, str(job), sex, face,
                  *state.values(), int(time.time())]
        placeholders = ','.join('?' for _ in fields)
        with self.lock:
            try:
                cur = self.db.execute(
                    f"INSERT INTO characters({','.join(fields)}) VALUES({placeholders})",
                    values)
                self.db.commit()
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return None

    def update_character_state(self, role_id, **state):
        """Persist authoritative gameplay fields for an owned role ID."""
        if not state or set(state) - set(CHARACTER_COLUMNS):
            raise ValueError('state must contain known gameplay fields')
        fields = list(state)
        with self.lock:
            cur = self.db.execute(
                'UPDATE characters SET ' + ', '.join(f'{f}=?' for f in fields)
                + ' WHERE CAST(id AS TEXT)=?', [*state.values(), str(role_id)])
            self.db.commit()
            return cur.rowcount == 1

    def list_roles(self, account, server_id):
        """Roles for an account; a role_stage row wins over characters columns."""
        with self.lock:
            rows = self.db.execute(
                'SELECT c.id, c.legacy_id, c.name, c.job, c.sex, c.face, c.level,'
                ' c.exp, COALESCE(s.map_id, c.map_id) AS map_id,'
                ' COALESCE(s.map_x, c.map_x) AS map_x,'
                ' COALESCE(s.map_y, c.map_y) AS map_y,'
                ' COALESCE(s.hp, c.hp) AS hp, COALESCE(s.mp, c.mp) AS mp,'
                ' COALESCE(s.max_hp, c.max_hp) AS max_hp,'
                ' COALESCE(s.max_mp, c.max_mp) AS max_mp,'
                ' c.tongqian, c.bind_lingshi, c.lingshi, c.recive_yb,'
                ' c.zhenqi, c.shengwang,'
                ' COALESCE(s.shanbi_val, 0) AS shanbi_val,'
                ' s.zuoqi_info AS zuoqi_info,'
                ' c.created'
                ' FROM characters c LEFT JOIN role_stage s ON s.role_id=c.id'
                ' WHERE c.account=? AND c.server_id=? ORDER BY c.id',
                (account, server_id)).fetchall()
            return [dict(row) for row in rows]

    def get_role_equip(self, role_id):
        """Equipped rows for a role (legacy role_equip_slot subset)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT slot_num, goods_id, rare_level, item_level, attributes'
                ' FROM role_equip WHERE role_id=? ORDER BY slot_num',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def save_role_equip(self, role_id, items):
        """Replace a role's equipped rows; items carry slot/goods/levels/blob."""
        with self.lock:
            self.db.execute('DELETE FROM role_equip WHERE role_id=?',
                            (str(role_id),))
            for item in items or []:
                self.db.execute(
                    'INSERT INTO role_equip(role_id, slot_num, goods_id,'
                    ' rare_level, item_level, attributes)'
                    ' VALUES(?,?,?,?,?,?)',
                    (str(role_id), item.get('slot_num'), item.get('goods_id'),
                     item.get('rare_level') or 0, item.get('item_level') or 0,
                     item.get('attributes')))
            self.db.commit()
            return True

    def get_role_attr_buffs(self, role_id):
        """Attribute-pill rows for a role (legacy role_attribute_buff subset)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT attribute_id, count FROM role_attr_buff'
                ' WHERE role_id=? ORDER BY attribute_id',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def save_role_attr_buffs(self, role_id, buffs):
        """Replace a role's attribute-pill rows; buffs carry id + count."""
        with self.lock:
            self.db.execute('DELETE FROM role_attr_buff WHERE role_id=?',
                            (str(role_id),))
            for buff in buffs or []:
                self.db.execute(
                    'INSERT INTO role_attr_buff(role_id, attribute_id, count)'
                    ' VALUES(?,?,?)',
                    (str(role_id), buff.get('attribute_id'),
                     buff.get('count') or 0))
            self.db.commit()
            return True

    def get_role_vip(self, role_id):
        """VIP row for a role (legacy role_vip subset), or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT vip_level, state_day, state_week, state_tejia,'
                ' prop_value, tody_prop_value FROM role_vip WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_vip(self, role_id, **fields):
        """Upsert a role's VIP row; only known role_vip columns."""
        allowed = {'vip_level', 'state_day', 'state_week', 'state_tejia',
                   'prop_value', 'tody_prop_value'}
        if not fields or set(fields) - allowed:
            raise ValueError(f'unknown vip fields: {sorted(set(fields) - allowed)}')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_vip(role_id,{names}) VALUES(?,{placeholders}) '
                f'ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_role_stage(self, role_id):
        with self.lock:
            row = self.db.execute(
                'SELECT * FROM role_stage WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_stage(self, role_id, **fields):
        """Upsert legacy stage/live-state fields for a role."""
        if not fields or set(fields) - set(STAGE_COLUMNS):
            raise ValueError(f'unknown stage fields: {sorted(set(fields) - set(STAGE_COLUMNS))}')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_stage(role_id,{names}) VALUES(?,{placeholders}) '
                f'ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_role_settings(self, role_id, account, server_id):
        """Read legacy-compatible per-role UI settings for an owned role."""
        with self.lock:
            row = self.db.execute(
                'SELECT s.quickbar_info, s.panel_config, s.ui_info, s.guaji_info '
                'FROM characters c LEFT JOIN role_settings s ON s.role_id=c.id '
                'WHERE CAST(c.id AS TEXT)=? AND c.account=? AND c.server_id=?',
                (str(role_id), account, server_id)).fetchone()
            if not row:
                return None
            result = dict(row)
            for field in ('panel_config', 'ui_info', 'guaji_info'):
                if result[field] is not None:
                    result[field] = bytes(result[field])
            return result

    def save_role_settings(self, role_id, account, server_id, **settings):
        """Update setting fields only when the role belongs to account/server."""
        allowed = {'quickbar_info', 'panel_config', 'ui_info', 'guaji_info'}
        if not settings or set(settings) - allowed:
            raise ValueError('unknown or empty role settings update')
        fields = ', '.join(f'{name}=excluded.{name}' for name in settings)
        names = ', '.join(settings)
        values = [bytes(value) if name in {'panel_config', 'ui_info', 'guaji_info'}
                  and value is not None else value
                  for name, value in settings.items()]
        with self.lock:
            row = self.db.execute(
                'SELECT id FROM characters WHERE CAST(id AS TEXT)=? AND account=? AND server_id=?',
                (str(role_id), account, server_id)).fetchone()
            if not row:
                return False
            rid = row['id']
            self.db.execute(
                f'INSERT INTO role_settings(role_id,{names}) VALUES(?,{",".join("?" for _ in values)}) '
                f'ON CONFLICT(role_id) DO UPDATE SET {fields}', [rid, *values])
            self.db.commit()
            return True

    def get_character(self, role_id, account, server_id):
        with self.lock:
            row = self.db.execute(
                'SELECT id, account, server_id, name, job, sex, face, level, exp,'
                ' map_id, map_x, map_y, hp, mp, max_hp, max_mp, tongqian,'
                ' bind_lingshi, lingshi, recive_yb, created FROM characters '
                'WHERE CAST(id AS TEXT)=? AND account=? AND server_id=?',
                (str(role_id), account, server_id)).fetchone()
            return dict(row) if row else None

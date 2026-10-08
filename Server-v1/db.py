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
CREATE TABLE IF NOT EXISTS characters (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
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
  created INTEGER NOT NULL,
  UNIQUE(account, server_id, name)
);
'''

CHARACTER_COLUMNS = {
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
        with self.lock:
            rows = self.db.execute(
                'SELECT id, name, job, sex, face, level, exp, map_id, map_x, map_y,'
                ' hp, mp, max_hp, max_mp, tongqian, bind_lingshi, lingshi,'
                ' recive_yb, created FROM characters '
                'WHERE account=? AND server_id=? ORDER BY id',
                (account, server_id)).fetchall()
            return [dict(row) for row in rows]

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

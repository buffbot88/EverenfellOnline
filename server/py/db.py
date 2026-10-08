"""SQLite persistence: accounts + characters. Replaces MySQL dntg/caonima."""
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
CREATE TABLE IF NOT EXISTS characters (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account TEXT NOT NULL,
  server_id TEXT NOT NULL,
  name TEXT NOT NULL,
  job INTEGER DEFAULT 0,
  sex INTEGER DEFAULT 0,
  face TEXT DEFAULT '',
  level INTEGER DEFAULT 1,
  created INTEGER NOT NULL,
  UNIQUE(account, server_id, name)
);
'''


class Store:
    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)

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

    def create_character(self, account, server_id, name, job=0, sex=0, face=''):
        """Insert a character; returns its id, or None if the name is taken
        on that account+server."""
        with self.lock:
            try:
                cur = self.db.execute(
                    'INSERT INTO characters(account, server_id, name, job, sex,'
                    ' face, created) VALUES(?,?,?,?,?,?,?)',
                    (account, server_id, name, job, sex, face, int(time.time())))
                self.db.commit()
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return None

    def list_roles(self, account, server_id):
        with self.lock:
            rows = self.db.execute(
                'SELECT id, name, job, sex, face, level, created FROM characters '
                'WHERE account=? AND server_id=? ORDER BY id',
                (account, server_id)).fetchall()
            return [dict(r) for r in rows]

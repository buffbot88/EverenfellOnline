"""SQLite persistence for accounts, characters, sessions, and game state."""
import os
import sqlite3
import threading
import time
import uuid

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
CREATE TABLE IF NOT EXISTS role_skill (
  role_id INTEGER NOT NULL,
  skill_key TEXT NOT NULL,
  category TEXT NOT NULL,
  level INTEGER DEFAULT 0,
  PRIMARY KEY(role_id, skill_key),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS role_shenjiang (
  role_id INTEGER NOT NULL,
  shenjiang_key TEXT NOT NULL,
  shenjiang_id TEXT NOT NULL,
  jiangxing_id TEXT,
  jiangxing_rank INTEGER DEFAULT 1,
  skills TEXT,
  PRIMARY KEY(role_id, shenjiang_key),
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
  day_time INTEGER DEFAULT 0,
  week_time INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Kaifu lottery state per role (legacy RoleVipKaifu subset: the claimed
-- id map plus the used lottery count; the row is ensured on first read
-- like RoleVipKaifuDao use in roleLogin).
CREATE TABLE IF NOT EXISTS role_vip_kaifu (
  role_id INTEGER PRIMARY KEY,
  lingqu_reward TEXT DEFAULT '{}',
  lotter_reward INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Appraisal state per role (no legacy source table; local-only like
-- role_settings): jianding count/time/exp plus the hecheng count that
-- 34006 reports alongside the exp.
CREATE TABLE IF NOT EXISTS role_jianding (
  role_id INTEGER PRIMARY KEY,
  jianding_count INTEGER DEFAULT 0,
  jianding_time INTEGER DEFAULT 0,
  jianding_exp INTEGER DEFAULT 0,
  hecheng_count INTEGER DEFAULT 0,
  hecheng_time INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Xianjie/chenghao id arrays for a role (legacy role_xianjiechenhao
-- subset: the JSON id lists the title bags resolve through).
CREATE TABLE IF NOT EXISTS role_xianjiechenhao (
  role_id INTEGER PRIMARY KEY,
  xianjie_id TEXT,
  chenhao_id TEXT,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Mount rank per role (legacy role_zuoqi subset: rank gates the ZUOQI bag
-- via ZuoQiWrapper, cur_rank is informational; attribute_goods_id is NULL
-- for every migrated role so it is not copied).
CREATE TABLE IF NOT EXISTS role_zuoqi (
  role_id INTEGER PRIMARY KEY,
  zuoqi_rank INTEGER DEFAULT 0,
  zuoqi_cur_rank INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Owned meiren per role (legacy role_meiren subset: the id/level/heti
-- triple replaceMeirenAttribute resolves through meiren.jat).
CREATE TABLE IF NOT EXISTS role_meiren (
  role_id INTEGER NOT NULL,
  meiren_id TEXT NOT NULL,
  meiren_level INTEGER DEFAULT 0,
  meiren_heti INTEGER DEFAULT 0,
  PRIMARY KEY(role_id, meiren_id),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Bag slots per role (legacy role_bag_slot subset: slot rows 1..150 are the
-- bag, 151+ the storage; attributes holds the GoodsEquipVo/ExpVo JSON).
CREATE TABLE IF NOT EXISTS role_bag_slot (
  role_id INTEGER NOT NULL,
  slot_num INTEGER NOT NULL,
  bag_id TEXT,
  goods_id TEXT NOT NULL,
  count INTEGER DEFAULT 0,
  bind INTEGER DEFAULT 0,
  expire_time INTEGER,
  rare_level INTEGER DEFAULT 0,
  item_level INTEGER DEFAULT 0,
  attributes TEXT,
  PRIMARY KEY(role_id, slot_num),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Skillbook equip slots per role (legacy role_skillbook_slot subset: the
-- 10001..10056 worn books; same StoreGoods columns as role_bag_slot).
CREATE TABLE IF NOT EXISTS role_skillbook_slot (
  role_id INTEGER NOT NULL,
  slot_num INTEGER NOT NULL,
  bag_id TEXT,
  goods_id TEXT NOT NULL,
  count INTEGER DEFAULT 0,
  bind INTEGER DEFAULT 0,
  expire_time INTEGER,
  rare_level INTEGER DEFAULT 0,
  item_level INTEGER DEFAULT 0,
  attributes TEXT,
  PRIMARY KEY(role_id, slot_num),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Sold-item buyback per role (legacy role_bag_buyback subset: the id is the
-- sold bag row's guid, slot_num its origin slot; createtime orders eviction).
CREATE TABLE IF NOT EXISTS role_bag_buyback (
  role_id INTEGER NOT NULL,
  buyback_id TEXT NOT NULL,
  slot_num INTEGER,
  goods_id TEXT NOT NULL,
  count INTEGER DEFAULT 0,
  bind INTEGER DEFAULT 0,
  expire_time INTEGER,
  rare_level INTEGER DEFAULT 0,
  item_level INTEGER DEFAULT 0,
  attributes TEXT,
  createtime INTEGER DEFAULT 0,
  PRIMARY KEY(role_id, buyback_id),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Special-type prop use counts per role (legacy role_prop subset: daily
-- useCount per goods id feeds the 30307 count query).
CREATE TABLE IF NOT EXISTS role_prop (
  role_id INTEGER NOT NULL,
  goods_id TEXT NOT NULL,
  use_start_time INTEGER,
  use_stop_time INTEGER,
  surplus_value INTEGER,
  surplus_time INTEGER,
  use_count INTEGER DEFAULT 0,
  PRIMARY KEY(role_id, goods_id),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Vip event state per role (legacy role_vip_huodong subset: the fixed
-- reward and lottery marks keyed by vip tier).
CREATE TABLE IF NOT EXISTS role_vip_huodong (
  role_id INTEGER NOT NULL,
  vip INTEGER NOT NULL,
  choujiang_state INTEGER DEFAULT 0,
  lingqu_state INTEGER DEFAULT 0,
  PRIMARY KEY(role_id, vip),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Running main quest per role (legacy task_main subset: current task, state,
-- kill-condition string, receive/create times; one row per role).
CREATE TABLE IF NOT EXISTS task_main (
  role_id INTEGER PRIMARY KEY,
  task_uid TEXT,
  task_id TEXT,
  state INTEGER DEFAULT 0,
  condition TEXT,
  recevie_time INTEGER,
  create_time INTEGER,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Bag dummy goods per role (legacy role_bag_dummy: goods a bagdummy query
-- lists back to the client; the id is the legacy row guid).
CREATE TABLE IF NOT EXISTS role_bag_dummy (
  id TEXT PRIMARY KEY,
  role_id INTEGER NOT NULL,
  goods_id TEXT NOT NULL,
  goods_count INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Bag unlock state per role (legacy role_bag_state subset: capacities gate
-- the 30000 lock VOs; *_slot_time feeds the unlock countdown).
CREATE TABLE IF NOT EXISTS role_bag_state (
  role_id INTEGER PRIMARY KEY,
  bag_capacity INTEGER DEFAULT 0,
  bag_slot_time INTEGER DEFAULT 0,
  bag_update_slot_time INTEGER DEFAULT 0,
  storage_capacity INTEGER DEFAULT 0,
  storage_slot_time INTEGER DEFAULT 0,
  storage_update_slot_time INTEGER DEFAULT 0,
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
            except sqlite3.IntegrityError:
                return False
            self.db.commit()
            return True

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

    def get_role_skills(self, role_id):
        """Owned skills for a role as [{category, level}] (legacy role_skill rows)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT category, level FROM role_skill WHERE role_id=?'
                ' ORDER BY skill_key',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def save_role_skill(self, role_id, category, level):
        """Learn/update one role_skill row keyed by category."""
        with self.lock:
            self.db.execute(
                'INSERT INTO role_skill(role_id, skill_key, category, level)'
                ' VALUES(?,?,?,?)'
                ' ON CONFLICT(role_id, skill_key) DO UPDATE SET'
                ' level=excluded.level',
                (str(role_id), str(category), str(category), int(level)))
            self.db.commit()
            return True

    def get_role_shenjiang(self, role_id):
        """Owned shenjiang rows for a role (legacy role_shenjiang subset)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT shenjiang_id, jiangxing_id, jiangxing_rank, skills'
                ' FROM role_shenjiang WHERE role_id=? ORDER BY shenjiang_key',
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
                ' prop_value, tody_prop_value, day_time, week_time'
                ' FROM role_vip WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def get_role_vip_kaifu(self, role_id):
        """Kaifu lottery row for a role, or None when never ensured."""
        with self.lock:
            row = self.db.execute(
                'SELECT lingqu_reward, lotter_reward FROM role_vip_kaifu'
                ' WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_vip_kaifu(self, role_id, **fields):
        """Upsert a role's kaifu row; only known columns."""
        allowed = {'lingqu_reward', 'lotter_reward'}
        if not fields or set(fields) - allowed:
            raise ValueError(
                f'unknown kaifu fields: {sorted(set(fields) - allowed)}')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_vip_kaifu(role_id,{names})'
                f' VALUES(?,{placeholders})'
                f' ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def save_role_vip(self, role_id, **fields):
        """Upsert a role's VIP row; only known role_vip columns."""
        allowed = {'vip_level', 'state_day', 'state_week', 'state_tejia',
                   'prop_value', 'tody_prop_value', 'day_time', 'week_time'}
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

    def get_role_jianding(self, role_id):
        """Appraisal state row for a role, or None when never appraised."""
        with self.lock:
            row = self.db.execute(
                'SELECT jianding_count, jianding_time, jianding_exp,'
                ' hecheng_count, hecheng_time FROM role_jianding'
                ' WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_jianding(self, role_id, **fields):
        """Upsert a role's appraisal state; only known columns."""
        allowed = {'jianding_count', 'jianding_time', 'jianding_exp',
                   'hecheng_count', 'hecheng_time'}
        if not fields or set(fields) - allowed:
            raise ValueError(
                f'unknown jianding fields: {sorted(set(fields) - allowed)}')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_jianding(role_id,{names})'
                f' VALUES(?,{placeholders})'
                f' ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_role_xianjiechenhao(self, role_id):
        """Xianjie/chenghao id row for a role, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT xianjie_id, chenhao_id FROM role_xianjiechenhao'
                ' WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_xianjiechenhao(self, role_id, xianjie_id=None,
                                 chenhao_id=None):
        """Upsert a role's xianjie/chenghao id lists (JSON texts)."""
        with self.lock:
            self.db.execute(
                'INSERT INTO role_xianjiechenhao(role_id, xianjie_id, chenhao_id)'
                ' VALUES(?,?,?)'
                ' ON CONFLICT(role_id) DO UPDATE SET'
                ' xianjie_id=excluded.xianjie_id, chenhao_id=excluded.chenhao_id',
                (str(role_id), xianjie_id, chenhao_id))
            self.db.commit()
            return True

    def get_role_zuoqi(self, role_id):
        """Mount-rank row for a role (legacy role_zuoqi subset), or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT zuoqi_rank, zuoqi_cur_rank FROM role_zuoqi'
                ' WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_zuoqi(self, role_id, zuoqi_rank=None, zuoqi_cur_rank=None):
        """Upsert a role's mount ranks (legacy role_zuoqi rank/cur_rank)."""
        with self.lock:
            self.db.execute(
                'INSERT INTO role_zuoqi(role_id, zuoqi_rank, zuoqi_cur_rank)'
                ' VALUES(?,?,?)'
                ' ON CONFLICT(role_id) DO UPDATE SET'
                ' zuoqi_rank=excluded.zuoqi_rank,'
                ' zuoqi_cur_rank=excluded.zuoqi_cur_rank',
                (str(role_id), zuoqi_rank, zuoqi_cur_rank))
            self.db.commit()
            return True

    def get_role_bag_slots(self, role_id, min_slot=1, max_slot=150):
        """Bag slot rows for a role in [min_slot, max_slot] (slot order)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT slot_num, bag_id, goods_id, count, bind, expire_time,'
                ' rare_level, item_level, attributes FROM role_bag_slot'
                ' WHERE role_id=? AND slot_num>=? AND slot_num<=?'
                ' ORDER BY slot_num',
                (str(role_id), min_slot, max_slot)).fetchall()
            return [dict(row) for row in rows]

    def save_role_bag_slots(self, role_id, rows):
        """Replace a role's bag slot rows; rows carry slot/goods/count/blob."""
        with self.lock:
            self.db.execute('DELETE FROM role_bag_slot WHERE role_id=?',
                            (str(role_id),))
            for row in rows or []:
                if row.get('slot_num') is None or not row.get('goods_id'):
                    continue
                # Locally created rows need a stable row id: Java's IdGen
                # issues one at creation, and moveGoodses looks rows up by it.
                bag_id = row.get('bag_id') or f'py{uuid.uuid4().hex[:16]}'
                self.db.execute(
                    'INSERT INTO role_bag_slot(role_id, slot_num, bag_id, goods_id,'
                    ' count, bind, expire_time, rare_level, item_level, attributes)'
                    ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (str(role_id), row.get('slot_num'), bag_id,
                     row.get('goods_id'), row.get('count') or 0,
                     row.get('bind') or 0, row.get('expire_time'),
                     row.get('rare_level') or 0, row.get('item_level') or 0,
                     row.get('attributes')))
            self.db.commit()
            return True

    def get_role_bag_slot(self, role_id, slot_num):
        """One bag slot row for a role, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT slot_num, bag_id, goods_id, count, bind, expire_time,'
                ' rare_level, item_level, attributes FROM role_bag_slot'
                ' WHERE role_id=? AND slot_num=?',
                (str(role_id), slot_num)).fetchone()
            return dict(row) if row else None

    def get_role_bag_slot_by_bag_id(self, role_id, bag_id):
        """One bag slot row by its legacy row id, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT slot_num, bag_id, goods_id, count, bind, expire_time,'
                ' rare_level, item_level, attributes FROM role_bag_slot'
                ' WHERE role_id=? AND bag_id=?',
                (str(role_id), bag_id)).fetchone()
            return dict(row) if row else None

    def update_role_bag_slot(self, role_id, slot_num, **fields):
        """Update known columns of one bag slot row."""
        known = {'bag_id', 'goods_id', 'count', 'bind', 'expire_time',
                 'rare_level', 'item_level', 'attributes'}
        if not fields or set(fields) - known:
            raise ValueError('fields must contain known bag slot columns')
        sets = ', '.join(f'{f}=?' for f in fields)
        with self.lock:
            cur = self.db.execute(
                f'UPDATE role_bag_slot SET {sets}'
                ' WHERE role_id=? AND slot_num=?',
                [*fields.values(), str(role_id), slot_num])
            self.db.commit()
            return cur.rowcount == 1

    def move_role_bag_slot(self, role_id, from_slot, to_slot):
        """Move a bag row between slots (swap when occupied)."""
        with self.lock:
            src = self.db.execute(
                'SELECT * FROM role_bag_slot WHERE role_id=? AND slot_num=?',
                (str(role_id), from_slot)).fetchone()
            if src is None:
                return False
            dst = self.db.execute(
                'SELECT slot_num FROM role_bag_slot WHERE role_id=? AND slot_num=?',
                (str(role_id), to_slot)).fetchone()
            if dst is None:
                self.db.execute(
                    'UPDATE role_bag_slot SET slot_num=?'
                    ' WHERE role_id=? AND slot_num=?',
                    (to_slot, str(role_id), from_slot))
            else:
                self.db.execute(
                    'UPDATE role_bag_slot SET slot_num=?'
                    ' WHERE role_id=? AND slot_num=?',
                    (-1, str(role_id), to_slot))
                self.db.execute(
                    'UPDATE role_bag_slot SET slot_num=?'
                    ' WHERE role_id=? AND slot_num=?',
                    (to_slot, str(role_id), from_slot))
                self.db.execute(
                    'UPDATE role_bag_slot SET slot_num=?'
                    ' WHERE role_id=? AND slot_num=?',
                    (from_slot, str(role_id), -1))
            self.db.commit()
            return True

    def insert_role_bag_slot(self, role_id, row):
        """Insert one bag slot row; returns its row id (generated when absent)."""
        bag_id = row.get('bag_id') or f'py{uuid.uuid4().hex[:16]}'
        with self.lock:
            self.db.execute(
                'INSERT INTO role_bag_slot(role_id, slot_num, bag_id, goods_id,'
                ' count, bind, expire_time, rare_level, item_level, attributes)'
                ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                (str(role_id), row.get('slot_num'), bag_id,
                 row.get('goods_id'), row.get('count') or 0,
                 row.get('bind') or 0, row.get('expire_time'),
                 row.get('rare_level') or 0, row.get('item_level') or 0,
                 row.get('attributes')))
            self.db.commit()
            return bag_id

    def delete_role_bag_slot(self, role_id, slot_num):
        """Delete one bag slot row."""
        with self.lock:
            cur = self.db.execute(
                'DELETE FROM role_bag_slot WHERE role_id=? AND slot_num=?',
                (str(role_id), slot_num))
            self.db.commit()
            return cur.rowcount == 1

    def rewrite_role_bag_slots(self, role_id, rows, min_slot, max_slot):
        """Replace a role's slot rows in [min_slot, max_slot] with rows.

        The tidy-up compacts renumbered, merged rows back in one step; row
        ids are kept (Java updates the same entities) and rows left out of
        the rewrite (merged-away, zero-count) disappear with the delete.
        """
        with self.lock:
            self.db.execute(
                'DELETE FROM role_bag_slot'
                ' WHERE role_id=? AND slot_num>=? AND slot_num<=?',
                (str(role_id), min_slot, max_slot))
            for row in rows or []:
                if row.get('slot_num') is None or not row.get('goods_id') \
                        or not row.get('bag_id'):
                    continue
                self.db.execute(
                    'INSERT INTO role_bag_slot(role_id, slot_num, bag_id, goods_id,'
                    ' count, bind, expire_time, rare_level, item_level, attributes)'
                    ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (str(role_id), row.get('slot_num'), row.get('bag_id'),
                     row.get('goods_id'), row.get('count') or 0,
                     row.get('bind') or 0, row.get('expire_time'),
                     row.get('rare_level') or 0, row.get('item_level') or 0,
                     row.get('attributes')))
            self.db.commit()
            return True

    def get_task_main(self, role_id):
        """A role's running main quest (legacy task_main subset), or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT task_uid, task_id, state, condition, recevie_time,'
                ' create_time FROM task_main WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_task_main(self, role_id, **fields):
        """Upsert a role's running main quest (known columns only)."""
        known = {'task_uid', 'task_id', 'state', 'condition',
                 'recevie_time', 'create_time'}
        if not fields or set(fields) - known:
            raise ValueError('fields must contain known task_main columns')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO task_main(role_id,{names}) VALUES(?,{placeholders}) '
                f'ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_role_skillbook_slots(self, role_id, min_slot=10001,
                                 max_slot=10056):
        """Skillbook slot rows for a role in [min_slot, max_slot]."""
        with self.lock:
            rows = self.db.execute(
                'SELECT slot_num, bag_id, goods_id, count, bind, expire_time,'
                ' rare_level, item_level, attributes FROM role_skillbook_slot'
                ' WHERE role_id=? AND slot_num>=? AND slot_num<=?'
                ' ORDER BY slot_num',
                (str(role_id), min_slot, max_slot)).fetchall()
            return [dict(row) for row in rows]

    def get_role_skillbook_slot(self, role_id, slot_num):
        """One skillbook slot row for a role, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT slot_num, bag_id, goods_id, count, bind, expire_time,'
                ' rare_level, item_level, attributes FROM role_skillbook_slot'
                ' WHERE role_id=? AND slot_num=?',
                (str(role_id), slot_num)).fetchone()
            return dict(row) if row else None

    def insert_role_skillbook_slot(self, role_id, row):
        """Insert one skillbook slot row; returns its row id."""
        bag_id = row.get('bag_id') or f'py{uuid.uuid4().hex[:16]}'
        with self.lock:
            self.db.execute(
                'INSERT INTO role_skillbook_slot(role_id, slot_num, bag_id,'
                ' goods_id, count, bind, expire_time, rare_level, item_level,'
                ' attributes) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (str(role_id), row.get('slot_num'), bag_id,
                 row.get('goods_id'), row.get('count') or 0,
                 row.get('bind') or 0, row.get('expire_time'),
                 row.get('rare_level') or 0, row.get('item_level') or 0,
                 row.get('attributes')))
            self.db.commit()
            return bag_id

    def update_role_skillbook_slot(self, role_id, slot, **fields):
        """Update known columns of one skillbook slot row."""
        known = {'slot_num', 'bag_id', 'goods_id', 'count', 'bind',
                 'expire_time', 'rare_level', 'item_level', 'attributes'}
        if not fields or set(fields) - known:
            raise ValueError('fields must contain known skillbook columns')
        sets = ', '.join(f'{f}=?' for f in fields)
        with self.lock:
            cur = self.db.execute(
                f'UPDATE role_skillbook_slot SET {sets}'
                ' WHERE role_id=? AND slot_num=?',
                [*fields.values(), str(role_id), slot])
            self.db.commit()
            return cur.rowcount == 1

    def delete_role_skillbook_slot(self, role_id, slot_num):
        """Delete one skillbook slot row."""
        with self.lock:
            cur = self.db.execute(
                'DELETE FROM role_skillbook_slot'
                ' WHERE role_id=? AND slot_num=?',
                (str(role_id), slot_num))
            self.db.commit()
            return cur.rowcount == 1

    def get_role_buyback_all(self, role_id):
        """Every buyback row for a role, oldest createtime first."""
        with self.lock:
            rows = self.db.execute(
                'SELECT buyback_id, slot_num, goods_id, count, bind,'
                ' expire_time, rare_level, item_level, attributes, createtime'
                ' FROM role_bag_buyback WHERE role_id=?'
                ' ORDER BY createtime, buyback_id',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def get_role_buyback(self, role_id, buyback_id):
        """One buyback row by its id (the sold bag guid), or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT buyback_id, slot_num, goods_id, count, bind,'
                ' expire_time, rare_level, item_level, attributes, createtime'
                ' FROM role_bag_buyback WHERE role_id=? AND buyback_id=?',
                (str(role_id), buyback_id)).fetchone()
            return dict(row) if row else None

    def insert_role_buyback(self, role_id, row):
        """Insert one buyback row; the id is the sold bag guid."""
        with self.lock:
            self.db.execute(
                'INSERT INTO role_bag_buyback(role_id, buyback_id, slot_num,'
                ' goods_id, count, bind, expire_time, rare_level, item_level,'
                ' attributes, createtime) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (str(role_id), row.get('buyback_id'),
                 row.get('slot_num'), row.get('goods_id'),
                 row.get('count') or 0, row.get('bind') or 0,
                 row.get('expire_time'), row.get('rare_level') or 0,
                 row.get('item_level') or 0, row.get('attributes'),
                 row.get('createtime') or 0))
            self.db.commit()
            return True

    def delete_role_buyback(self, role_id, buyback_id):
        """Delete one buyback row; True when a row was removed."""
        with self.lock:
            cur = self.db.execute(
                'DELETE FROM role_bag_buyback'
                ' WHERE role_id=? AND buyback_id=?',
                (str(role_id), buyback_id))
            self.db.commit()
            return cur.rowcount == 1

    def get_role_bag_dummy(self, role_id):
        """Bag dummy goods for a role as dicts of goods_id and goods_count."""
        with self.lock:
            rows = self.db.execute(
                'SELECT goods_id, goods_count FROM role_bag_dummy'
                ' WHERE role_id=? ORDER BY id',
                (str(role_id),)).fetchall()
            return [dict(r) for r in rows]

    def get_role_prop(self, role_id, goods_id):
        """One role_prop row by role and goods id, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT goods_id, use_start_time, use_stop_time,'
                ' surplus_value, surplus_time, use_count'
                ' FROM role_prop WHERE role_id=? AND goods_id=?',
                (str(role_id), str(goods_id))).fetchone()
            return dict(row) if row else None

    def save_role_prop(self, role_id, goods_id, **fields):
        """Upsert one role_prop row (only known columns are written)."""
        cols = ('use_start_time', 'use_stop_time', 'surplus_value',
                'surplus_time', 'use_count')
        sets = {k: v for k, v in fields.items() if k in cols}
        with self.lock:
            self.db.execute(
                'INSERT INTO role_prop(role_id, goods_id) VALUES(?,?)'
                ' ON CONFLICT(role_id, goods_id) DO NOTHING',
                (str(role_id), str(goods_id)))
            for key, val in sets.items():
                self.db.execute(
                    f'UPDATE role_prop SET {key}=?'
                    ' WHERE role_id=? AND goods_id=?',
                    (val, str(role_id), str(goods_id)))
            self.db.commit()
            return True

    def get_role_vip_huodong_all(self, role_id):
        """Every vip event row for a role (tier plus both marks)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT vip, choujiang_state, lingqu_state'
                ' FROM role_vip_huodong WHERE role_id=?',
                (str(role_id),)).fetchall()
            return [dict(r) for r in rows]

    def get_role_vip_huodong(self, role_id, vip):
        """Vip event row for a role tier, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT choujiang_state, lingqu_state FROM role_vip_huodong'
                ' WHERE role_id=? AND vip=?',
                (str(role_id), int(vip))).fetchone()
            return dict(row) if row else None

    def save_role_vip_huodong(self, role_id, vip, **fields):
        """Upsert a role's vip event row; only known huodong columns."""
        allowed = {'choujiang_state', 'lingqu_state'}
        if not fields or set(fields) - allowed:
            raise ValueError('unknown huodong fields: '
                             f'{sorted(set(fields) - allowed)}')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_vip_huodong(role_id, vip, {names})'
                f' VALUES(?,?,{placeholders})'
                f' ON CONFLICT(role_id, vip) DO UPDATE SET {updates}',
                (str(role_id), int(vip), *[int(v) for v in fields.values()]))
            self.db.commit()
            return True

    def get_role_bag_state(self, role_id):
        """Bag unlock state for a role (legacy role_bag_state subset), or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT bag_capacity, bag_slot_time, bag_update_slot_time,'
                ' storage_capacity, storage_slot_time, storage_update_slot_time'
                ' FROM role_bag_state WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_bag_state(self, role_id, **fields):
        """Upsert a role's bag unlock state (known state columns only)."""
        known = {'bag_capacity', 'bag_slot_time', 'bag_update_slot_time',
                 'storage_capacity', 'storage_slot_time',
                 'storage_update_slot_time'}
        if not fields or set(fields) - known:
            raise ValueError('state must contain known bag state fields')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_bag_state(role_id,{names}) VALUES(?,{placeholders}) '
                f'ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_role_meiren(self, role_id):
        """Owned-meiren rows for a role (legacy role_meiren subset)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT meiren_id, meiren_level, meiren_heti FROM role_meiren'
                ' WHERE role_id=? ORDER BY meiren_id',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def save_role_meiren(self, role_id, rows):
        """Replace a role's owned-meiren rows; rows carry id/level/heti."""
        with self.lock:
            self.db.execute('DELETE FROM role_meiren WHERE role_id=?',
                            (str(role_id),))
            for row in rows or []:
                if not row.get('meiren_id'):
                    continue
                self.db.execute(
                    'INSERT INTO role_meiren(role_id, meiren_id, meiren_level,'
                    ' meiren_heti) VALUES(?,?,?,?)',
                    (str(role_id), row.get('meiren_id'),
                     row.get('meiren_level') or 0, row.get('meiren_heti') or 0))
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

    def find_roles_by_name(self, name):
        """Characters whose name contains the query (RoleDao.getRolesLikeName)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT id, name, sex, face, level, job FROM characters'
                ' WHERE name LIKE ? ORDER BY id',
                ('%' + name + '%',)).fetchall()
            return [dict(r) for r in rows]

    def get_character(self, role_id, account, server_id):
        with self.lock:
            row = self.db.execute(
                'SELECT id, account, server_id, name, job, sex, face, level, exp,'
                ' map_id, map_x, map_y, hp, mp, max_hp, max_mp, tongqian,'
                ' bind_lingshi, lingshi, recive_yb, created FROM characters '
                'WHERE CAST(id AS TEXT)=? AND account=? AND server_id=?',
                (str(role_id), account, server_id)).fetchone()
            return dict(row) if row else None

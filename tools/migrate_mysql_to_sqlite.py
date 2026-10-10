"""Migrate the legacy MySQL data the Python server needs into its SQLite DB.

Read-only on MySQL (uses the bundled mysql.exe client). Passwords are converted
from the legacy plaintext to the server's PBKDF2 format, so no plaintext lands
in SQLite. Repeatable: existing accounts/roles are left alone.

Only the named accounts are migrated (default: `stress`); the legacy database
holds thousands of obsolete registrations that are not wanted.

Usage: migrate_mysql_to_sqlite.py [--users a,b] [--dry-run] [--db PATH]
                                   [--report PATH] [--mysql PATH]
"""
import argparse
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'Server-v1'))
from auth import hash_password  # noqa: E402  (PBKDF2 helper)

ESSAMP = os.path.join(ROOT, 'reference', 'TonNgoKhong', 'server', 'ESSamp')
DEFAULT_MYSQL = os.path.join(ESSAMP, 'MySQL5', 'bin', 'mysql.exe')
DEFAULT_DB = os.path.join(ROOT, 'Server-v1', 'data', 'mko.db')
PHP_CONFIG = os.path.join(ESSAMP, 'wwwroot', 'configuration', 'config.inc.php')

# Columns pulled per source table. Order matters: it is the row layout.
ACCOUNT_COLS = ['id', 'name', 'password', 'last_login_time']
ROLE_COLS = ['id', 'user_id', 'name', 'job', 'sex', 'exp', 'level', 'face',
             'zhenqi', 'shengwang', 'server_id', 'create_time']


def mysql_password():
    """Read the DB password from the PHP config without printing it."""
    text = open(PHP_CONFIG, encoding='utf-8', errors='replace').read()
    m = re.search(r"\$db_password\s*=\s*'([^']*)'", text)
    if not m:
        raise SystemExit(f'no db_password in {PHP_CONFIG}')
    return m.group(1)


def parse_batch(raw):
    """Decode `mysql -N -B` output into rows of str/None.

    The client is run with --default-character-set=utf8, so the bytes are
    UTF-8. Batch mode renders a SQL NULL as the literal text `NULL`.
    """
    rows = []
    for line in raw.decode('utf-8', 'replace').splitlines():
        if not line:
            continue
        rows.append([None if v == 'NULL' else v for v in line.split('\t')])
    return rows


class MySql:
    """Read-only client wrapper.

    The server is MySQL 5.1, whose bundled client has no utf8mb4; `utf8` is the
    right choice for its utf8 columns (3-byte UTF-8, which is all the data
    uses). Without it the client connects as latin1 and every CJK character is
    silently replaced by `?` before it reaches us.

    Batch mode prints a SQL NULL as the literal text `NULL`, so that is the
    sentinel we map back to None; a stored four-character string `NULL` in a
    text column would be indistinguishable (no such values exist here).
    """

    def __init__(self, exe, password):
        self.exe = exe
        self.env = dict(os.environ, MYSQL_PWD=password)  # not in argv

    def query(self, database, sql):
        out = subprocess.run(
            [self.exe, '-h127.0.0.1', '-uroot', '-N', '-B',
             '--default-character-set=utf8', '-e', sql, database],
            capture_output=True, env=self.env, timeout=120)
        if out.returncode != 0:
            raise SystemExit(f'mysql failed: {out.stderr.decode("utf-8", "replace").strip()[:200]}')
        return parse_batch(out.stdout)


def as_int(value):
    if value is None or value == '':
        return None
    return int(value)


def quote_list(values):
    """Render a SQL string IN-list from already-trusted config values."""
    return ', '.join("'" + v.replace("'", "''") + "'" for v in values)


def selected_role_ids(mysql, users):
    """Legacy role ids belonging to the selected accounts."""
    rows = mysql.query('dntg', 'select id from user_role where user_id in '
                               f'({quote_list(users)})')
    return [r[0] for r in rows if r[0]]


def role_filter(role_ids):
    """WHERE fragment limiting per-role tables to the selected roles."""
    if not role_ids:
        return 'where 0'
    return f'where user_role_id in ({quote_list(role_ids)})'


def plan_counts(mysql, users):
    """Row counts for the tables in scope."""
    role_ids = selected_role_ids(mysql, users)
    where = {'account': f' where name in ({quote_list(users)})',
             'user_role': f' where user_id in ({quote_list(users)})',
             'role_stage': ' ' + role_filter(role_ids),
             'role_account': ' ' + role_filter(role_ids),
             'role_equip_slot': ' ' + role_filter(role_ids),
             'role_attribute_buff': ' ' + role_filter(role_ids),
             'role_vip': ' ' + role_filter(role_ids),
             'role_xianjiechenhao': ' ' + role_filter(role_ids),
             'role_meiren': ' ' + role_filter(role_ids)}
    tables = {'account': ('caonima', 'account'),
              'user_role': ('dntg', 'user_role'),
              'role_stage': ('dntg', 'role_stage'),
              'role_account': ('dntg', 'role_account'),
              'role_equip_slot': ('dntg', 'role_equip_slot'),
              'role_attribute_buff': ('dntg', 'role_attribute_buff'),
              'role_vip': ('dntg', 'role_vip'),
              'role_xianjiechenhao': ('dntg', 'role_xianjiechenhao'),
              'role_meiren': ('dntg', 'role_meiren')}
    counts = {}
    for label, (db, table) in tables.items():
        rows = mysql.query(db, f'select count(*) from {table}{where[label]}')
        counts[label] = int(rows[0][0]) if rows else 0
    return counts


def migrate(mysql, db_path, users, dry_run=False):
    """Copy the in-scope rows for `users`; returns a report dict."""
    report = {'users': ','.join(users), 'accounts_added': 0, 'accounts_skipped': 0,
              'roles_added': 0, 'roles_skipped': 0,
              'stages_written': 0, 'currency_written': 0,
              'equip_written': 0, 'attr_buffs_written': 0, 'vip_written': 0,
              'xianjiechenhao_written': 0, 'meiren_written': 0,
              'roles_missing_account': [], 'notes': []}
    accounts = mysql.query('caonima',
                           'select ' + ','.join(ACCOUNT_COLS) + ' from account'
                           f' where name in ({quote_list(users)}) order by id')
    roles = mysql.query('dntg', 'select ' + ','.join(ROLE_COLS)
                        + f' from user_role where user_id in '
                          f'({quote_list(users)}) order by id')
    role_ids = [r[0] for r in roles if r and r[0]]
    role_where = role_filter(role_ids)
    stages = mysql.query('dntg',
                         'select user_role_id,map_id,map_x,map_y,hp,mp,max_hp,'
                         'max_mp,buff,props,state,map_node,ti_li,line_no,'
                         'shanbi_val,meiren_info,zuoqi_info,copy_info,'
                         'free_fly_count from role_stage ' + role_where)
    currency = mysql.query('dntg', 'select user_role_id,tongqian,bind_lingshi'
                                  ' from role_account ' + role_where)
    equips = mysql.query('dntg', 'select user_role_id,slot_num,goods_id,'
                                 'rare_level,item_level,attributes'
                                 ' from role_equip_slot ' + role_where
                                 + ' order by user_role_id,slot_num')
    attr_buffs = mysql.query('dntg', 'select user_role_id,attribute_id,count'
                                     ' from role_attribute_buff ' + role_where
                                     + ' order by user_role_id,attribute_id')
    vips = mysql.query('dntg', 'select user_role_id,vip_level,state_day,'
                               'state_week,state_tejia,prop_value,tody_prop_value'
                               ' from role_vip ' + role_where)
    xianjiechenhao = mysql.query('dntg', 'select user_role_id,xianjie_id,chenhao_id'
                                         ' from role_xianjiechenhao ' + role_where)
    meiren = mysql.query('dntg', 'select user_role_id,meiren_id,meiren_level,'
                                 'meiren_heti from role_meiren ' + role_where
                                 + ' order by user_role_id,meiren_id')
    if dry_run:
        report['accounts_added'] = len(accounts)
        report['roles_added'] = len(roles)
        report['stages_written'] = len(stages)
        report['currency_written'] = len(currency)
        report['equip_written'] = len(equips)
        report['attr_buffs_written'] = len(attr_buffs)
        report['vip_written'] = len(vips)
        report['xianjiechenhao_written'] = len(xianjiechenhao)
        report['meiren_written'] = len(meiren)
        return report

    # Back up before writing anything.
    if os.path.exists(db_path):
        backup = f'{db_path}.pre-migration-{time.strftime("%Y%m%d-%H%M%S")}'
        shutil.copy2(db_path, backup)
        report['notes'].append(f'backup: {backup}')

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # accounts: plaintext -> PBKDF2 (only the hash is stored)
        account_by_name = {}
        for row in accounts:
            legacy_id, name, password, _last_login = (row + [None] * 4)[:4]
            if not name:
                continue
            account_by_name[name] = legacy_id
            existing = conn.execute('SELECT id FROM accounts WHERE username=?',
                                    (name,)).fetchone()
            if existing:
                report['accounts_skipped'] += 1
                continue
            conn.execute(
                'INSERT INTO accounts(username, pass_hash, created) VALUES(?,?,?)',
                (name, hash_password(password or ''), int(time.time())))
            report['accounts_added'] += 1
        conn.commit()

        # roles -> characters (+ legacy_id), then stage and currency
        legacy_to_local = {}
        for row in roles:
            legacy_id, user_id, name, job, sex, exp, level, face, \
                zhenqi, shengwang, server_id, _created = (row + [None] * 12)[:12]
            if not name or not user_id:
                continue
            existing = conn.execute(
                'SELECT id FROM characters WHERE legacy_id=? OR '
                '(account=? AND server_id=? AND name=?)',
                (legacy_id, user_id, server_id, name)).fetchone()
            if existing:
                legacy_to_local[legacy_id] = existing['id']
                report['roles_skipped'] += 1
            else:
                if conn.execute('SELECT 1 FROM accounts WHERE username=?',
                                (user_id,)).fetchone() is None:
                    report['roles_missing_account'].append(
                        f'{legacy_id} ({user_id})')
                cur = conn.execute(
                    'INSERT INTO characters(legacy_id, account, server_id, name,'
                    ' job, sex, face, level, exp, zhenqi, shengwang, created)'
                    ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (legacy_id, user_id, server_id, name, job or 'A',
                     as_int(sex) or 0, face, as_int(level) or 1,
                     as_int(exp), as_int(zhenqi), as_int(shengwang),
                     int(time.time())))
                legacy_to_local[legacy_id] = cur.lastrowid
                report['roles_added'] += 1
        conn.commit()

        stage_names = ['map_id', 'map_x', 'map_y', 'hp', 'mp', 'max_hp',
                       'max_mp', 'buff', 'props', 'state', 'map_node', 'ti_li',
                       'line_no', 'shanbi_val', 'meiren_info', 'zuoqi_info',
                       'copy_info', 'free_fly_count']
        for row in stages:
            user_role_id = row[0]
            local_id = legacy_to_local.get(user_role_id)
            if local_id is None:
                continue
            values = [as_int(v) if k in ('map_x', 'map_y', 'hp', 'mp', 'max_hp',
                                         'max_mp', 'state', 'ti_li', 'line_no',
                                         'shanbi_val', 'free_fly_count')
                      else v
                      for k, v in zip(stage_names, row[1:])]
            names = ', '.join(stage_names)
            placeholders = ', '.join('?' for _ in stage_names)
            updates = ', '.join(f'{n}=excluded.{n}' for n in stage_names)
            conn.execute(
                f'INSERT INTO role_stage(role_id,{names}) VALUES(?,{placeholders})'
                f' ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [local_id, *values])
            report['stages_written'] += 1

        conn.execute('CREATE TABLE IF NOT EXISTS role_equip(role_id INTEGER NOT NULL,'
                     ' slot_num INTEGER NOT NULL, goods_id TEXT NOT NULL,'
                     ' rare_level INTEGER DEFAULT 0, item_level INTEGER DEFAULT 0,'
                     ' attributes TEXT, PRIMARY KEY(role_id, slot_num))')
        conn.execute('CREATE TABLE IF NOT EXISTS role_attr_buff(role_id INTEGER NOT NULL,'
                     ' attribute_id TEXT NOT NULL, count INTEGER DEFAULT 0,'
                     ' PRIMARY KEY(role_id, attribute_id))')
        for row in equips:
            user_role_id, slot_num, goods_id, rare_level, item_level, \
                attributes = (row + [None] * 6)[:6]
            local_id = legacy_to_local.get(user_role_id)
            if local_id is None or not goods_id:
                continue
            conn.execute(
                'INSERT INTO role_equip(role_id, slot_num, goods_id,'
                ' rare_level, item_level, attributes)'
                ' VALUES(?,?,?,?,?,?)'
                ' ON CONFLICT(role_id, slot_num) DO UPDATE SET'
                ' goods_id=excluded.goods_id, rare_level=excluded.rare_level,'
                ' item_level=excluded.item_level, attributes=excluded.attributes',
                (local_id, as_int(slot_num) or 0, goods_id,
                 as_int(rare_level) or 0, as_int(item_level) or 0, attributes))
            report['equip_written'] += 1
        for row in attr_buffs:
            user_role_id, attribute_id, count = (row + [None] * 3)[:3]
            local_id = legacy_to_local.get(user_role_id)
            if local_id is None or not attribute_id:
                continue
            conn.execute(
                'INSERT INTO role_attr_buff(role_id, attribute_id, count)'
                ' VALUES(?,?,?)'
                ' ON CONFLICT(role_id, attribute_id) DO UPDATE SET'
                ' count=excluded.count',
                (local_id, attribute_id, as_int(count) or 0))
            report['attr_buffs_written'] += 1

        conn.execute('CREATE TABLE IF NOT EXISTS role_vip(role_id INTEGER PRIMARY KEY,'
                     ' vip_level INTEGER DEFAULT 0, state_day INTEGER DEFAULT 0,'
                     ' state_week INTEGER DEFAULT 0, state_tejia TEXT,'
                     ' prop_value INTEGER DEFAULT 0, tody_prop_value INTEGER DEFAULT 0)')
        for row in vips:
            user_role_id, vip_level, state_day, state_week, state_tejia, \
                prop_value, tody_prop_value = (row + [None] * 7)[:7]
            local_id = legacy_to_local.get(user_role_id)
            if local_id is None:
                continue
            conn.execute(
                'INSERT INTO role_vip(role_id, vip_level, state_day, state_week,'
                ' state_tejia, prop_value, tody_prop_value)'
                ' VALUES(?,?,?,?,?,?,?)'
                ' ON CONFLICT(role_id) DO UPDATE SET'
                ' vip_level=excluded.vip_level, state_day=excluded.state_day,'
                ' state_week=excluded.state_week, state_tejia=excluded.state_tejia,'
                ' prop_value=excluded.prop_value,'
                ' tody_prop_value=excluded.tody_prop_value',
                (local_id, as_int(vip_level) or 0, as_int(state_day) or 0,
                 as_int(state_week) or 0, state_tejia, as_int(prop_value) or 0,
                 as_int(tody_prop_value) or 0))
            report['vip_written'] += 1

        conn.execute('CREATE TABLE IF NOT EXISTS role_xianjiechenhao(role_id INTEGER PRIMARY KEY,'
                     ' xianjie_id TEXT, chenhao_id TEXT)')
        for row in xianjiechenhao:
            user_role_id, xianjie_id, chenhao_id = (row + [None] * 3)[:3]
            local_id = legacy_to_local.get(user_role_id)
            if local_id is None:
                continue
            conn.execute(
                'INSERT INTO role_xianjiechenhao(role_id, xianjie_id, chenhao_id)'
                ' VALUES(?,?,?)'
                ' ON CONFLICT(role_id) DO UPDATE SET'
                ' xianjie_id=excluded.xianjie_id, chenhao_id=excluded.chenhao_id',
                (local_id, xianjie_id, chenhao_id))
            report['xianjiechenhao_written'] += 1

        conn.execute('CREATE TABLE IF NOT EXISTS role_meiren(role_id INTEGER NOT NULL,'
                     ' meiren_id TEXT NOT NULL, meiren_level INTEGER DEFAULT 0,'
                     ' meiren_heti INTEGER DEFAULT 0,'
                     ' PRIMARY KEY(role_id, meiren_id))')
        for row in meiren:
            user_role_id, meiren_id, meiren_level, meiren_heti = (row + [None] * 4)[:4]
            local_id = legacy_to_local.get(user_role_id)
            if local_id is None or not meiren_id:
                continue
            conn.execute(
                'INSERT INTO role_meiren(role_id, meiren_id, meiren_level, meiren_heti)'
                ' VALUES(?,?,?,?)'
                ' ON CONFLICT(role_id, meiren_id) DO UPDATE SET'
                ' meiren_level=excluded.meiren_level,'
                ' meiren_heti=excluded.meiren_heti',
                (local_id, meiren_id, as_int(meiren_level) or 0,
                 as_int(meiren_heti) or 0))
            report['meiren_written'] += 1

        for user_role_id, tongqian, bind_lingshi in currency:
            local_id = legacy_to_local.get(user_role_id)
            if local_id is None:
                continue
            conn.execute(
                'UPDATE characters SET tongqian=?, bind_lingshi=? WHERE id=?',
                (as_int(tongqian), as_int(bind_lingshi), local_id))
            report['currency_written'] += 1
        conn.commit()
    finally:
        conn.close()
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--mysql', default=DEFAULT_MYSQL)
    ap.add_argument('--report')
    ap.add_argument('--users', default='stress',
                    help='comma-separated legacy account names to migrate')
    args = ap.parse_args()
    users = [u.strip() for u in args.users.split(',') if u.strip()]
    if not users:
        raise SystemExit('--users needs at least one account name')
    if not os.path.exists(args.mysql):
        raise SystemExit(f'mysql client not found: {args.mysql}')
    mysql = MySql(args.mysql, mysql_password())
    print('users:', users)
    print('source counts:', plan_counts(mysql, users))
    report = migrate(mysql, args.db, users, dry_run=args.dry_run)
    for key, value in report.items():
        if key != 'notes':
            print(f'{key}: {value}')
    for note in report['notes']:
        print('note:', note)
    if args.report:
        with open(args.report, 'w', encoding='utf-8', newline='\n') as out:
            for key, value in report.items():
                out.write(f'{key}: {value}\n')


if __name__ == '__main__':
    main()

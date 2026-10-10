#!/usr/bin/env python3
"""Clean the legacy MySQL oracle: back up both schemas, then delete obsolete rows.

Keeps the accounts named by `--keep` (default `stress,111111`) and removes every
other `caonima.account` row plus the rows in either schema whose value belongs to
a deleted account or role. Nothing is written without `--apply`, and a
`mysqldump` of `caonima` + `dntg` is written first.

Usage: mysql_cleanup.py [--keep stress,111111] [--apply] [--reset-oracle]
                        [--backup-dir output/orig-stack]
"""
import argparse
import importlib.util
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATOR = os.path.join(ROOT, 'tools', 'migrate_mysql_to_sqlite.py')

# Columns that can carry an account name or a role id, per schema table.
ROLE_COLUMNS = {'user_role_id', 'role_id', 'roleid', 'user_roleid'}
ACCOUNT_COLUMNS = {'user_id', 'userid', 'account', 'account_id', 'username',
                   'user_name', 'name'}
# Handled explicitly (dedupe / keep-list) rather than by the generic sweep.
EXPLICIT = {('caonima', 'account'), ('dntg', 'user_role')}
# Staging table for the values about to be deleted (argv has a length limit).
STAGE_TABLE = '_mko_doomed'

# The captured level-56 role (account 111111): the equipment-bearing subject
# whose 12000/23009 the port is verified against.
ORACLE_ROLE = 'fu0UR1-0-1-1'
ORACLE_STAGE = {'map_id': '5', 'map_x': 44, 'map_y': 33,
                'hp': 5226, 'max_hp': 5466, 'mp': 1811, 'max_mp': 1811}


def load_migrator():
    """The migrator module (dashed filename), for its MySQL wrapper + password."""
    spec = importlib.util.spec_from_file_location('migrate_mysql_to_sqlite', MIGRATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dump(password, mysql_exe, backup_dir, stamp):
    """mysqldump both schemas; returns the backup path (verified non-empty)."""
    exe = os.path.join(os.path.dirname(mysql_exe), 'mysqldump.exe')
    path = os.path.join(backup_dir, f'mysql-backup-{stamp}.sql')
    env = dict(os.environ, MYSQL_PWD=password)
    with open(path, 'wb') as out:
        proc = subprocess.run(
            [exe, '-h127.0.0.1', '-uroot', '--default-character-set=utf8',
             '--databases', 'caonima', 'dntg'],
            stdout=out, stderr=subprocess.PIPE, env=env, timeout=600)
    size = os.path.getsize(path)
    if proc.returncode != 0:
        raise SystemExit(f'mysqldump failed: {proc.stderr.decode("utf-8", "replace")[:200]}')
    if size < 10000 or b'CREATE TABLE' not in open(path, 'rb').read(200000):
        raise SystemExit(f'backup looks wrong: {path} ({size} bytes)')
    print(f'backup: {path} ({size} bytes)')
    return path


def scalar(mysql, db, sql):
    rows = mysql.query(db, sql)
    return rows[0][0] if rows and rows[0] else None


def candidate_columns(mysql):
    """(schema, table, column) pairs whose values may reference accounts/roles."""
    names = sorted(ROLE_COLUMNS | ACCOUNT_COLUMNS)
    rows = mysql.query('information_schema',
                       'select table_schema, table_name, column_name '
                       'from columns where table_schema in (\'caonima\',\'dntg\') '
                       f'and column_name in ({", ".join(chr(39) + n + chr(39) for n in names)}) '
                       'order by table_schema, table_name, column_name')
    return [tuple(r) for r in rows if (r[0], r[1]) not in EXPLICIT]


def census(mysql, keep):
    """Counts that describe the current state; also returns the id sets to drop."""
    accounts = mysql.query('caonima', 'select name, count(*) from account group by name')
    dupes = sum(int(c) - 1 for _n, c in accounts)
    roles = mysql.query('dntg', 'select id, user_id from user_role')
    deleted_names = [n for n, _c in accounts if n not in keep]
    deleted_roles = [r[0] for r in roles if r[1] not in keep]
    return {
        'account_rows': sum(int(c) for _n, c in accounts),
        'distinct_names': len(accounts),
        'duplicate_rows': dupes,
        'role_rows': len(roles),
        'roles_kept': sorted(r[1] for r in roles if r[1] in keep),
        'deleted_names': deleted_names,
        'deleted_roles': deleted_roles,
    }


def stage_doomed(mysql, deleted_names, deleted_roles):
    """Park the doomed values in a real table: 6k names cannot ride in argv."""
    mysql.query('dntg', f'create table if not exists {STAGE_TABLE} '
                        '(kind varchar(8) not null, value varchar(96) not null, '
                        'key kind_value (kind, value))')
    mysql.query('dntg', f'delete from {STAGE_TABLE}')
    rows = [('account', v) for v in deleted_names] + [('role', v) for v in deleted_roles]
    for i in range(0, len(rows), 400):
        chunk = ','.join("('" + k + "','" + v.replace("'", "''") + "')"
                         for k, v in rows[i:i + 400])
        mysql.query('dntg', f'insert into {STAGE_TABLE}(kind, value) values {chunk}')
    print(f'staged {len(rows)} doomed values in dntg.{STAGE_TABLE}')


def doomed_values(kind):
    """Subquery selecting the staged values of one kind (dntg-qualified: it is
    read from caonima tables too)."""
    return f"select value from dntg.{STAGE_TABLE} where kind='{kind}'"


def sweep_plan(mysql):
    """Per-table delete counts: only rows whose value IS one of the doomed ids."""
    plan = []
    for schema, table, column in candidate_columns(mysql):
        kind = 'role' if column.lower() in ROLE_COLUMNS else 'account'
        try:
            count = scalar(mysql, schema, f'select count(*) from `{table}` '
                                          f'where `{column}` in ({doomed_values(kind)})')
        except SystemExit as e:                      # table vanished / not readable
            print(f'  skip {schema}.{table}.{column}: {e}')
            continue
        n = int(count or 0)
        if n:
            plan.append((schema, table, column, kind, n))
    return plan


def apply_sweep(mysql, plan):
    """Run the reviewed deletes; returns rows removed per table."""
    done = []
    for schema, table, column, kind, expected in plan:
        mysql.query(schema, f'delete from `{table}` where `{column}` in ({doomed_values(kind)})')
        done.append((f'{schema}.{table}.{column}', expected))
    return done


def reset_oracle(mysql):
    """Put the captured level-56 role back at its documented entry state."""
    where = f"user_role_id='{ORACLE_ROLE}'"
    exists = scalar(mysql, 'dntg', f'select count(*) from role_stage where {where}')
    if not int(exists or 0):
        print(f'oracle reset skipped: no role_stage row for {ORACLE_ROLE}')
        return
    sets = ', '.join(f'{k}={v if isinstance(v, int) else chr(39) + v + chr(39)}'
                     for k, v in ORACLE_STAGE.items())
    mysql.query('dntg', f'update role_stage set {sets} where {where}')
    print(f'oracle reset: {ORACLE_ROLE} -> map {ORACLE_STAGE["map_id"]} '
          f'({ORACLE_STAGE["map_x"]},{ORACLE_STAGE["map_y"]})')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--keep', default='stress,111111')
    ap.add_argument('--apply', action='store_true', help='write the changes')
    ap.add_argument('--reset-oracle', action='store_true',
                    help='restore the captured role_stage entry position too')
    ap.add_argument('--backup-dir', default=os.path.join(ROOT, 'output', 'orig-stack'))
    ap.add_argument('--mysql', default=None)
    a = ap.parse_args()
    keep = [u.strip() for u in a.keep.split(',') if u.strip()]

    mig = load_migrator()
    mysql_exe = a.mysql or mig.DEFAULT_MYSQL
    password = mig.mysql_password()
    mysql = mig.MySql(mysql_exe, password)
    os.makedirs(a.backup_dir, exist_ok=True)

    print(f'keep: {keep}')
    before = census(mysql, keep)
    print(f'before: {before["account_rows"]} account rows '
          f'({before["distinct_names"]} distinct, {before["duplicate_rows"]} duplicates), '
          f'{before["role_rows"]} roles, keeping roles of {before["roles_kept"]}')
    print(f'would delete: {len(before["deleted_names"])} account names, '
          f'{len(before["deleted_roles"])} roles')

    stage_doomed(mysql, before['deleted_names'], before['deleted_roles'])
    plan = sweep_plan(mysql)
    print(f'scoped rows in other tables: {len(plan)} table/column pairs, '
          f'{sum(n for *_x, n in plan)} rows')
    for schema, table, column, _kind, n in plan[:15]:
        print(f'  {schema}.{table}.{column}: {n}')
    if len(plan) > 15:
        print(f'  ... {len(plan) - 15} more')

    if not a.apply:
        mysql.query('dntg', f'drop table if exists {STAGE_TABLE}')
        print('report only; re-run with --apply to write (backup happens first)')
        return

    stamp = time.strftime('%Y%m%d-%H%M%S')
    dump(password, mysql_exe, a.backup_dir, stamp)

    # 1. duplicate account names: keep the lowest id per name
    dupes = scalar(mysql, 'caonima',
                   'select count(*) from account where id not in '
                   '(select * from (select min(id) from account group by name) t)')
    mysql.query('caonima', 'delete from account where id not in '
                           '(select * from (select min(id) from account group by name) t)')
    print(f'duplicate account rows removed: {dupes}')

    # 2. obsolete accounts + their roles
    mysql.query('caonima', 'delete from account where name not in ('
                           + ','.join("'" + k + "'" for k in keep) + ')')
    mysql.query('dntg', 'delete from user_role where user_id not in ('
                        + ','.join("'" + k + "'" for k in keep) + ')')

    # 3. every other table, scoped to the values just deleted
    for label, n in apply_sweep(mysql, plan):
        print(f'  pruned {label}: {n} rows')
    mysql.query('dntg', f'drop table if exists {STAGE_TABLE}')

    if a.reset_oracle:
        reset_oracle(mysql)

    after = census(mysql, keep)
    print(f'after: {after["account_rows"]} account rows '
          f'({after["distinct_names"]} distinct), {after["role_rows"]} roles, '
          f'keeping roles of {after["roles_kept"]}')
    print(f'done (backup {stamp})')


if __name__ == '__main__':
    main()

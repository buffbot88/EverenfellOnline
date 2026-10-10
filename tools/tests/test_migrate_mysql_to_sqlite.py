"""Tests for tools/migrate_mysql_to_sqlite.py's client-output parsing.

The live MySQL (5.1) is not required: these cover the two encoding traps that
bit the real migration — the client silently replacing CJK with `?` when it
connects as latin1, and NULL arriving as the literal text `NULL`.
"""
import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
_spec = importlib.util.spec_from_file_location(
    'migrate_mysql_to_sqlite', os.path.join(TOOLS, 'migrate_mysql_to_sqlite.py'))
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

# The migrator writes into an existing Server-v1 schema; load its DDL only.
_db_spec = importlib.util.spec_from_file_location(
    'mko_db', os.path.join(os.path.dirname(TOOLS), 'Server-v1', 'db.py'))
mko_db = importlib.util.module_from_spec(_db_spec)
_db_spec.loader.exec_module(mko_db)


class ParseBatchTest(unittest.TestCase):
    def test_utf8_text_survives(self):
        # The exact bytes the legacy client returns for role 'fu0UR1-10-0-1'.
        raw = b'Tuan565.\xe9\x85\x86\xe8\x8a\xb7\xe2\x97\x8b\xe8\xa8\xaa\xe8\x95\x8a\n'
        self.assertEqual(mig.parse_batch(raw), [['Tuan565.酆芷○訪蕊']])

    def test_null_becomes_none_not_the_string_null(self):
        raw = b'NULL\t1\tNULL\t0\n'
        self.assertEqual(mig.parse_batch(raw), [[None, '1', None, '0']])

    def test_blank_lines_and_multiple_rows(self):
        raw = b'a\tb\n\nc\td\n'
        self.assertEqual(mig.parse_batch(raw), [['a', 'b'], ['c', 'd']])

    def test_empty_output_is_no_rows(self):
        self.assertEqual(mig.parse_batch(b''), [])


class HelperTest(unittest.TestCase):
    def test_quote_list_escapes_quotes(self):
        self.assertEqual(mig.quote_list(['stress', "o'brien"]),
                         "'stress', 'o''brien'")

    def test_as_int_passes_through_blank_and_none(self):
        self.assertIsNone(mig.as_int(None))
        self.assertIsNone(mig.as_int(''))
        self.assertEqual(mig.as_int('144'), 144)


class FakeMySql:
    """Records SQL and answers the role-id lookup, else a count of one."""

    def __init__(self, role_ids):
        self.role_ids = role_ids
        self.queries = []

    def query(self, database, sql):
        self.queries.append(sql)
        if 'select id from user_role' in sql:
            return [[r] for r in self.role_ids]
        return [['1']]


class ScopeTest(unittest.TestCase):
    def test_plan_counts_covers_the_six_tables(self):
        counts = mig.plan_counts(FakeMySql(['7']), ['stress'])
        self.assertEqual(counts, {'account': 1, 'user_role': 1,
                                  'role_stage': 1, 'role_account': 1,
                                  'role_equip_slot': 1,
                                  'role_attribute_buff': 1})

    def test_stage_and_currency_counts_follow_the_selected_roles(self):
        fake = FakeMySql(['7', '9'])
        mig.plan_counts(fake, ['stress'])
        for sql in fake.queries:
            if 'from role_stage' in sql or 'from role_account' in sql:
                self.assertIn("user_role_id in ('7', '9')", sql)

    def test_no_roles_means_no_stage_or_currency_rows(self):
        fake = FakeMySql([])
        mig.plan_counts(fake, ['stress'])
        for sql in fake.queries:
            if 'from role_stage' in sql or 'from role_account' in sql:
                self.assertIn('where 0', sql)

    def test_role_filter_matches_nothing_when_no_roles(self):
        self.assertEqual(mig.role_filter([]), 'where 0')
        self.assertEqual(mig.role_filter(['7']), "where user_role_id in ('7')")


class FakeDataMySql:
    """Answers migrate()'s four queries with parse_batch-shaped string rows."""

    def query(self, database, sql):
        if 'from account' in sql:
            return [[3, 'stress', 'pw', None]]
        if 'from user_role' in sql:
            # ROLE_COLS: legacy_id, user_id, name, job, sex, exp, level, face,
            # zhenqi, shengwang, server_id, created.
            return [['7', 'stress', '悟空', 'A', '1', '1310', '7', '1',
                     '565260', '987', 'fu1304', '2014-02-24 21:37:40']]
        if 'from role_stage' in sql:
            return [['7', '2', 10, 150, 144, 96, 144, 96, None, None, 1,
                     None, 1, 1, 1, None, None, None, 0]]
        if 'from role_account' in sql:
            return [['7', '1000', '50']]
        if 'from role_equip_slot' in sql:
            return [['7', '0', 'zj0201', '2', '7',
                     '{"fjattrstr":"{}","qhxingxing":"[[1,1]]"}']]
        if 'from role_attribute_buff' in sql:
            return [['7', 'sm_001', '3']]
        raise AssertionError(f'unexpected query: {sql}')


class MigrateCharactersTest(unittest.TestCase):
    """End-to-end copy into a temp SQLite: currencies must land on characters."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db_path = os.path.join(self.tmp, 'mko.db')
        conn = sqlite3.connect(self.db_path)
        conn.executescript(mko_db.SCHEMA)
        conn.close()

    def test_role_currencies_and_stage_land_on_the_local_rows(self):
        report = mig.migrate(FakeDataMySql(), self.db_path, ['stress'])
        self.assertEqual(report['accounts_added'], 1)
        self.assertEqual(report['roles_added'], 1)
        self.assertEqual(report['stages_written'], 1)
        self.assertEqual(report['currency_written'], 1)
        self.assertEqual(report['roles_missing_account'], [])

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM characters').fetchone()
        self.assertEqual(row['legacy_id'], '7')
        self.assertEqual(row['name'], '悟空')
        self.assertEqual(row['zhenqi'], 565260)   # user_role.zhenqi -> column
        self.assertEqual(row['shengwang'], 987)
        self.assertEqual(row['tongqian'], 1000)   # role_account -> currency
        self.assertEqual(row['bind_lingshi'], 50)
        stage = conn.execute('SELECT * FROM role_stage').fetchone()
        self.assertEqual(stage['map_id'], '2')
        self.assertEqual(stage['shanbi_val'], 1)
        equip = conn.execute('SELECT * FROM role_equip').fetchone()
        self.assertEqual(equip['goods_id'], 'zj0201')
        self.assertEqual(equip['rare_level'], 2)
        buff = conn.execute('SELECT * FROM role_attr_buff').fetchone()
        self.assertEqual(buff['attribute_id'], 'sm_001')
        self.assertEqual(buff['count'], 3)
        conn.close()


if __name__ == '__main__':
    unittest.main()

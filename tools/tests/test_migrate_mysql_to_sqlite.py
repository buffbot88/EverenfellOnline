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
    def test_plan_counts_covers_the_twelve_tables(self):
        counts = mig.plan_counts(FakeMySql(['7']), ['stress'])
        self.assertEqual(counts, {'account': 1, 'user_role': 1,
                                  'role_stage': 1, 'role_account': 1,
                                  'role_equip_slot': 1,
                                  'role_attribute_buff': 1, 'role_vip': 1,
                                  'role_xianjiechenhao': 1, 'role_meiren': 1,
                                  'role_zuoqi': 1, 'role_pet': 1,
                                  'role_pet_zhenfa': 1, 'role_skill': 1,
                                  'role_shenjiang': 1, 'role_bag_slot': 1,
                                  'role_bag_buyback': 1,
                                  'role_bag_dummy': 1,
                                  'role_prop': 1, 'role_qiandao': 1,
                                  'role_skillbook_slot': 1,
                                  'role_bag_state': 1,
                                  'role_qq_list': 1, 'vip_qq': 1,
                                  'task_main': 1})

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
        if 'from role_vip' in sql:
            return [['7', '10', '3', '1', '{"a": 2}', '7', '9']]
        if 'from role_qq_list' in sql:
            return [['7', '12345', '0', 'gm']]
        if 'from vip_qq' in sql:
            return [['100', 'pic1', '80000']]
        if 'from role_xianjiechenhao' in sql:
            return [['7', '["1"]', '["2"]']]
        if 'from role_meiren' in sql:
            return []
        if 'from role_zuoqi' in sql:
            return [['7', '1', '1']]
        if 'from role_pet_zhenfa' in sql:
            return [['7', '1', None, '0', '{}', '0']]
        if 'from role_pet' in sql:
            return []
        if 'from role_shenjiang' in sql:
            return [['1', '7', 'sj0101', '', '1', '{"xiaolongnv": 2}']]
        if 'from role_skillbook_slot' in sql:
            return [['fu0RBS1-0-1-78', '10001', '7', 'zuoqijineng1', '1',
                     '1', '0', '3', '1', '{"exp":0}']]
        if 'from role_skill' in sql:
            # skill_key, user_role_id, skill_category_id, skill_level.
            return [['fu0RS1-0-1-1', '7', 'niumowang1', '1']]
        if 'from role_bag_buyback' in sql:
            return [['fu0RBS1-0-1-77', '36', '7', 'silver50', '1', '1',
                     '0', '3', '1', None, '1394468076000']]
        if 'from role_bag_slot' in sql:
            return [['fu0RBS1-0-1-77', '36', '7', 'silver50', '1', '1',
                     '0', '3', '1', None]]
        if 'from role_bag_dummy' in sql:
            return [['fu0RBD1-0-1-1', '7', 'silver50', '3']]
        if 'from role_prop' in sql:
            return [['7', 'teshu_fire', '1394468076000', None, None,
                     None, '3']]
        if 'from role_qiandao' in sql:
            return [['7', '1', '10', '', '', '', '43', '0',
                     '1394468593406', '1792360479694']]
        if 'from task_main' in sql:
            # id, user_role_id, current_task_id, current_state,
            # current_condition, current_recevie_time, create_time.
            return [['106', '7', 'c001010', '0', 'D010006;1',
                     '1393226660', '1393226660']]
        if 'from role_bag_state' in sql:
            return [['7', '144', '1548096', '1394468956781', '31',
                     '2428331', '1394468076546']]
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
        vip = conn.execute('SELECT * FROM role_vip').fetchone()
        self.assertEqual(vip['vip_level'], 10)
        self.assertEqual(vip['state_tejia'], '{"a": 2}')
        xianjie = conn.execute('SELECT * FROM role_xianjiechenhao').fetchone()
        self.assertEqual(xianjie['xianjie_id'], '["1"]')
        self.assertEqual(xianjie['chenhao_id'], '["2"]')
        meiren = conn.execute('SELECT * FROM role_meiren').fetchall()
        self.assertEqual(meiren, [])   # no meiren rows for this role
        zuoqi = conn.execute('SELECT * FROM role_zuoqi').fetchone()
        self.assertEqual(zuoqi['zuoqi_rank'], 1)
        self.assertEqual(zuoqi['zuoqi_cur_rank'], 1)
        pets = conn.execute('SELECT * FROM role_pet').fetchall()
        self.assertEqual(pets, [])   # no pet rows for this role
        self.assertEqual(report['pets_written'], 0)
        zhenfa = conn.execute('SELECT * FROM role_pet_zhenfa').fetchone()
        self.assertEqual(zhenfa['zhenfa_id'], '1')
        self.assertEqual(zhenfa['upgrade_exp'], 0)
        self.assertEqual(zhenfa['zhenfa_pet'], '{}')
        self.assertEqual(zhenfa['pet_upgrade_count'], 0)
        self.assertEqual(report['pet_zhenfa_written'], 1)
        shenjiang = conn.execute('SELECT * FROM role_shenjiang').fetchone()
        self.assertEqual(shenjiang['shenjiang_id'], 'sj0101')
        self.assertEqual(shenjiang['skills'], '{"xiaolongnv": 2}')
        task = conn.execute('SELECT * FROM task_main').fetchone()
        self.assertEqual(task['task_id'], 'c001010')
        self.assertEqual(task['condition'], 'D010006;1')
        self.assertEqual(report['task_main_written'], 1)
        bag = conn.execute('SELECT * FROM role_bag_slot').fetchone()
        self.assertEqual(bag['slot_num'], 36)
        self.assertEqual(bag['bag_id'], 'fu0RBS1-0-1-77')
        self.assertEqual(bag['goods_id'], 'silver50')
        self.assertEqual(bag['bind'], 1)
        bag_state = conn.execute('SELECT * FROM role_bag_state').fetchone()
        self.assertEqual(bag_state['bag_capacity'], 144)
        self.assertEqual(bag_state['storage_capacity'], 31)
        self.assertEqual(report['bag_slots_written'], 1)
        buyback = conn.execute('SELECT * FROM role_bag_buyback').fetchone()
        self.assertEqual(buyback['buyback_id'], 'fu0RBS1-0-1-77')
        self.assertEqual(buyback['goods_id'], 'silver50')
        self.assertEqual(buyback['createtime'], 1394468076000)
        self.assertEqual(report['buyback_written'], 1)
        prop = conn.execute('SELECT * FROM role_prop').fetchone()
        self.assertEqual(prop['goods_id'], 'teshu_fire')
        self.assertEqual(prop['use_count'], 3)
        self.assertEqual(prop['use_start_time'], 1394468076000)
        self.assertEqual(report['role_prop_written'], 1)
        qiandao = conn.execute('SELECT * FROM role_qiandao').fetchone()
        self.assertEqual(qiandao['total_qiandao_count'], 1)
        self.assertEqual(qiandao['month'], 10)
        self.assertEqual(qiandao['month_qiandao'], '')
        self.assertEqual(qiandao['week'], 43)
        self.assertEqual(qiandao['qiandao_time'], 1394468593406)
        self.assertEqual(report['role_qiandao_written'], 1)
        self.assertEqual(report['bag_state_written'], 1)
        book = conn.execute('SELECT * FROM role_skillbook_slot').fetchone()
        self.assertEqual(book['slot_num'], 10001)
        self.assertEqual(book['goods_id'], 'zuoqijineng1')
        self.assertEqual(book['attributes'], '{"exp":0}')
        self.assertEqual(report['skillbook_slots_written'], 1)
        skill = conn.execute('SELECT * FROM role_skill').fetchone()
        self.assertEqual(skill['skill_key'], 'fu0RS1-0-1-1')
        self.assertEqual(skill['category'], 'niumowang1')
        self.assertEqual(skill['level'], 1)
        self.assertEqual(report['skills_written'], 1)
        dummy = conn.execute('SELECT * FROM role_bag_dummy').fetchone()
        self.assertEqual(dummy['id'], 'fu0RBD1-0-1-1')
        self.assertEqual(dummy['role_id'], row['id'])   # legacy 7 -> local id
        self.assertEqual(dummy['goods_id'], 'silver50')
        self.assertEqual(dummy['goods_count'], 3)
        qq = conn.execute('SELECT * FROM role_qq_list').fetchone()
        self.assertEqual(qq['role_id'], row['id'])
        self.assertEqual(qq['qq'], '12345')
        self.assertEqual(qq['user_name'], 'gm')
        self.assertEqual(report['qq_lists_written'], 1)
        vqq = conn.execute('SELECT * FROM vip_qq').fetchone()
        self.assertEqual(vqq['min_recharge'], 100)
        self.assertEqual(vqq['qq'], '80000')
        self.assertEqual(report['vip_qq_written'], 1)
        conn.close()


if __name__ == '__main__':
    unittest.main()

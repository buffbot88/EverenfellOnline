"""Architecture audit: parsers must read the real artifacts, not guesses."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import architecture_audit as aa  # noqa: E402


class PythonDispatchTest(unittest.TestCase):
    def test_dispatched_ids_come_from_cmd_constants(self):
        ids = aa.load_python_commands()
        self.assertIn('42002', ids)   # CMD_SKILL_FIRE
        self.assertIn('10001', ids)   # CMD_LOGIN

    def test_observed_unknown_is_not_counted_as_dispatched(self):
        # 53021 is logged, never routed (CMD_UNKNOWN_OBSERVED).
        self.assertNotIn('53021', aa.load_python_commands())


class MysqlSchemaTest(unittest.TestCase):
    def test_dump_yields_the_legacy_tables_we_map(self):
        tables = aa.load_mysql_tables()
        if not tables:
            self.skipTest('no MySQL dump in output/orig-stack')
        for name in aa.MYSQL_TO_SQLITE:
            self.assertIn(name, tables)


class LedgerTest(unittest.TestCase):
    def test_status_needs_a_route_and_a_test_for_golden(self):
        self.assertEqual(aa.ledger_status('42002', {'42002'}, {'x.py'}),
                         'golden-tested')
        self.assertEqual(aa.ledger_status('42002', {'42002'}, set()),
                         'dispatched')
        self.assertEqual(aa.ledger_status('42002', set(), {'x.py'}),
                         'not started')

    def test_push_ids_need_emission_and_a_test_for_golden(self):
        self.assertEqual(aa.ledger_status('12001', set(), {'x.py'}, True),
                         'push-golden-tested')
        self.assertEqual(aa.ledger_status('12001', set(), set(), True),
                         'emitted')

    def test_emitted_ids_come_from_outbound_frames(self):
        emitted = aa.load_python_emitted()
        self.assertIn('12001', emitted)   # literal list head in combat.py
        self.assertIn('12050', emitted)   # str(CMD_ROLE_ZHENQI_CAP)

    def test_golden_becomes_persisted_when_the_test_reads_back_the_store(self):
        refs = {'x.py'}
        self.assertEqual(aa.ledger_status('42002', {'42002'}, refs,
                                          readback_files={'x.py'}), 'persisted')
        self.assertEqual(aa.ledger_status('42002', {'42002'}, refs,
                                          readback_files={'y.py'}),
                         'golden-tested')

    def test_readback_regex_needs_a_store_getter_or_lister(self):
        self.assertIsNotNone(aa.STORE_READBACK.search(
            'row = self.store.get_role_bag_slot(1, 36)'))
        self.assertIsNotNone(aa.STORE_READBACK.search(
            'rows = self.store.list_roles("u", "s")'))
        self.assertIsNone(aa.STORE_READBACK.search(
            'self.store.create_character("hero")'))

    def test_test_refs_match_whole_ids_only(self):
        refs = aa.find_test_refs({'1000', '10001'})
        # '10001' contains '1000' only as a substring; it must not count for '1000'.
        for path in refs['1000']:
            self.assertTrue(path.startswith(('Server-v1/', 'tools/')))
        self.assertIn('Server-v1/tests/test_protocol.py', refs['10001'])

    def test_non_command_ids_are_excluded_from_the_jar_scan(self):
        self.assertEqual(aa.NON_COMMAND_IDS,
                         frozenset({'2000', '1003', '1006', '430405',
                                    '794000', '794001', '794002'}))
        commands, _ = aa.load_java()
        for cmd in aa.NON_COMMAND_IDS:
            self.assertNotIn(cmd, commands)
        # 88005 stays: vipQqOK pushes it (service-internal like 62003).
        self.assertIn('88005', commands)

    def test_ledger_covers_every_java_id(self):
        commands = {'10001': [], '99999': []}
        text, counts = aa.render_ledger(commands, {}, {'10001'})
        self.assertEqual(sum(counts.values()), 2)
        self.assertIn('| `10001` |', text)
        self.assertIn('| `99999` |', text)


class SqliteSchemaTest(unittest.TestCase):
    def test_schema_tables_are_read(self):
        tables = aa.load_sqlite_tables()
        self.assertIn('characters', tables)
        self.assertIn('role_stage', tables)
        self.assertIn('role_shenjiang', tables)


if __name__ == '__main__':
    unittest.main()

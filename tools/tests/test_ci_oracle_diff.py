"""Tests for tools/ci-oracle-diff.py: provisioning helpers and gate contract.

No live Java, MySQL or Python server is needed. The socket test uses a loopback
listener, the process test a short-lived child, and the schema test a temporary
SQLite file.
"""
import argparse
import importlib.util
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(os.path.dirname(TOOLS), 'Server-v1'))

_spec = importlib.util.spec_from_file_location(
    'ci_oracle_diff', os.path.join(TOOLS, 'ci-oracle-diff.py'))
ci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci)


class PortTest(unittest.TestCase):
    def test_free_port_can_be_bound(self):
        port = ci.free_port()
        self.assertIsInstance(port, int)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', port))

    def test_game_and_web_ports_differ(self):
        game, web = ci.two_free_ports()
        self.assertNotEqual(game, web)


class WaitTest(unittest.TestCase):
    def test_closed_port_times_out(self):
        port = ci.free_port()
        started = __import__('time').monotonic()
        self.assertFalse(ci.wait_for_tcp('127.0.0.1', port, 0.3))
        self.assertLess(__import__('time').monotonic() - started, 2.0)

    def test_listening_port_is_detected(self):
        server = socket.socket()
        self.addCleanup(server.close)
        server.bind(('127.0.0.1', 0))
        server.listen(1)
        port = server.getsockname()[1]
        self.assertTrue(ci.wait_for_tcp('127.0.0.1', port, 2.0))


class SqlLiteralTest(unittest.TestCase):
    def test_quotes_and_escapes(self):
        self.assertEqual(ci.sql_literal('stress'), "'stress'")
        self.assertEqual(ci.sql_literal("o'brien"), "'o''brien'")


class LegacyPasswordTest(unittest.TestCase):
    class FakeMySql:
        def __init__(self, rows):
            self.rows = rows
            self.calls = []

        def query(self, database, sql):
            self.calls.append((database, sql))
            return self.rows

    def test_returns_the_stored_password(self):
        mysql = self.FakeMySql([['hunter2']])
        self.assertEqual(ci.legacy_password(mysql, 'stress'), 'hunter2')
        self.assertEqual(mysql.calls[0][0], 'caonima')
        self.assertIn("name = 'stress'", mysql.calls[0][1])

    def test_missing_account_is_an_error(self):
        with self.assertRaises(LookupError):
            ci.legacy_password(self.FakeMySql([]), 'stress')

    def test_null_password_is_an_error(self):
        with self.assertRaises(LookupError):
            ci.legacy_password(self.FakeMySql([[None]]), 'stress')


class DiffArgvTest(unittest.TestCase):
    def _args(self, **overrides):
        defaults = dict(java='127.0.0.1:8008', baseline='base.json',
                        user='stress', timeout=4.0, push_window=3.0,
                        notify_window=1.0, cmd=['50001', '35011'],
                        report='report.txt')
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_every_command_and_the_baseline_are_forwarded(self):
        argv = ci.diff_argv(self._args(), '127.0.0.1:9001',
                            'http://127.0.0.1:9002')
        self.assertEqual(argv[:2], [sys.executable, ci.DIFF_TOOL])
        self.assertEqual(argv[argv.index('--cmd') + 1], '50001')
        self.assertEqual(argv.count('--cmd'), 2)
        self.assertEqual(argv[argv.index('--baseline') + 1], 'base.json')
        self.assertEqual(argv[argv.index('--python-web') + 1],
                         'http://127.0.0.1:9002')
        self.assertEqual(argv[argv.index('--report') + 1], 'report.txt')

    def test_the_password_never_reaches_argv(self):
        argv = ci.diff_argv(self._args(), '127.0.0.1:9001',
                            'http://127.0.0.1:9002')
        self.assertNotIn('--password', argv)
        self.assertNotIn('secret', ' '.join(argv))

    def test_no_report_flag_when_unset(self):
        argv = ci.diff_argv(self._args(report=''), '127.0.0.1:9001',
                            'http://127.0.0.1:9002')
        self.assertNotIn('--report', argv)


class InitSchemaTest(unittest.TestCase):
    def test_creates_the_tables_the_migrator_writes_into(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(tmp, True))
        db_path = os.path.join(tmp, 'mko.db')
        ci.init_schema(db_path)
        conn = sqlite3.connect(db_path)
        self.addCleanup(conn.close)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for name in ('accounts', 'characters', 'sessions', 'role_settings'):
            self.assertIn(name, tables)


class StopTest(unittest.TestCase):
    def test_terminates_a_running_child(self):
        proc = subprocess.Popen([sys.executable, '-c',
                                 'import time; time.sleep(30)'])
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        ci.stop(proc, grace=5.0)
        self.assertIsNotNone(proc.poll())

    def test_already_exited_child_is_left_alone(self):
        proc = subprocess.Popen([sys.executable, '-c', 'pass'])
        proc.wait()
        ci.stop(proc)
        self.assertEqual(proc.returncode, 0)


class TailTest(unittest.TestCase):
    def test_returns_the_last_lines(self):
        handle = tempfile.NamedTemporaryFile('w', delete=False)
        self.addCleanup(os.unlink, handle.name)
        with handle:
            for index in range(20):
                handle.write(f'line {index}\n')
        self.assertEqual(ci.tail(handle.name, 3),
                         ['line 17', 'line 18', 'line 19'])

    def test_missing_file_is_empty(self):
        self.assertEqual(ci.tail(os.path.join(TOOLS, 'no-such.log')), [])


LISTEN = (
    'import socket, sys, time\n'
    'sock = socket.socket()\n'
    'sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n'
    'sock.bind(("127.0.0.1", int(sys.argv[1])))\n'
    'sock.listen(8)\n'
    'time.sleep(60)\n'
)


class FakeServer:
    """Stand-in process that records how it was started and stopped."""

    def __init__(self, child, argv, events=None, name=''):
        self.child = child
        self.argv = argv
        self.events = events
        self.name = name
        self.terminated = 0

    def poll(self):
        return self.child.poll()

    def terminate(self):
        self.terminated += 1
        if self.events is not None:
            self.events.append(f'terminate:{self.name}')
        self.child.terminate()

    def kill(self):
        self.child.kill()

    def wait(self, timeout=None):
        return self.child.wait(timeout)


class FakeSpawn:
    """`spawn` replacement: the fake server listens on the port in argv."""

    def __init__(self, java_port, events=None, die=False, die_java=False):
        self.java_port = java_port
        self.events = events
        self.die = die
        self.die_java = die_java
        self.calls = []
        self.procs = []

    def port_for(self, argv):
        for arg in argv:
            if arg.startswith('--port='):
                return int(arg.split('=', 1)[1])
        return self.java_port

    def __call__(self, argv, cwd, log_path, env=None):
        self.calls.append((argv, cwd, log_path))
        open(log_path, 'wb').close()
        if self.die or (self.die_java and '-jar' in argv):
            child = subprocess.Popen([sys.executable, '-c', 'pass'])
        else:
            child = subprocess.Popen(
                [sys.executable, '-c', LISTEN, str(self.port_for(argv))])
        name = 'java' if '-jar' in argv else 'mysql'
        proxy = FakeServer(child, argv, self.events, name)
        self.procs.append(proxy)
        return proxy, mock.MagicMock()


class StackPathTest(unittest.TestCase):
    def test_layout_is_relative_to_the_stack_root(self):
        paths = ci.stack_paths(os.path.join('x', 'server'))
        self.assertEqual(paths['root'], os.path.join('x', 'server'))
        self.assertTrue(paths['mysqld'].endswith(
            os.path.join('ESSamp', 'MySQL5', 'bin', 'mysqld.exe')))
        self.assertTrue(paths['java'].endswith(
            os.path.join('jre6', 'bin', 'java.exe')))
        self.assertTrue(paths['jar'].endswith('dntg_start.jar'))

    def test_missing_binaries_lists_every_absent_file(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(tmp, True))
        missing = ci.missing_binaries(ci.stack_paths(tmp))
        self.assertEqual(len(missing), 4)
        self.assertIn(ci.stack_paths(tmp)['mysqld'], missing)

    def test_a_complete_tree_reports_nothing_missing(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(tmp, True))
        paths = ci.stack_paths(tmp)
        for key in ('mysqld', 'mysqladmin', 'java', 'jar'):
            os.makedirs(os.path.dirname(paths[key]), exist_ok=True)
            open(paths[key], 'w').close()
        self.assertEqual(ci.missing_binaries(paths), [])


class StackArgvTest(unittest.TestCase):
    def setUp(self):
        self.paths = ci.stack_paths(os.path.join('repo', 'server'))

    def test_mysqld_gets_explicit_basedir_and_datadir(self):
        argv = ci.mysql_argv(self.paths)
        self.assertEqual(argv[0], self.paths['mysqld'])
        self.assertIn('--basedir=' + self.paths['mysql_basedir'], argv)
        self.assertIn('--datadir=' + self.paths['mysql_datadir'], argv)
        self.assertIn('--port=3306', argv)

    def test_java_matches_server_bat_without_the_gc_log(self):
        argv = ci.java_argv(self.paths)
        self.assertEqual(argv[0], self.paths['java'])
        self.assertIn('./;lib/*;lib/Jetty/*;extensions/__lib__/*', argv)
        for flag in ('-Xms256m', '-Xmx1024m', '-XX:PermSize=256M',
                     '-XX:MaxPermSize=256M'):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index('-jar') + 1], 'dntg_start.jar')
        self.assertFalse([arg for arg in argv if 'Xloggc' in arg])

    def test_shutdown_targets_root_on_loopback(self):
        argv = ci.mysql_shutdown_argv(self.paths)
        self.assertEqual(argv[0], self.paths['mysqladmin'])
        self.assertIn('-h127.0.0.1', argv)
        self.assertIn('-P3306', argv)
        self.assertEqual(argv[-1], 'shutdown')


class StartStackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(self.tmp, True))
        self.paths = ci.stack_paths(os.path.join(self.tmp, 'server'))
        self.mysql_port = ci.free_port()
        self.java_port = ci.free_port()
        while self.java_port == self.mysql_port:
            self.java_port = ci.free_port()

    def _start(self, fake):
        with mock.patch.object(ci, 'spawn', fake), \
                mock.patch('builtins.print'):
            started = ci.start_stack(self.paths, 10.0, self.tmp,
                                     '127.0.0.1', self.java_port,
                                     self.mysql_port)
        self.addCleanup(ci.stop_stack, started, self.paths)
        return started

    def test_boots_mysql_before_java(self):
        fake = FakeSpawn(self.java_port)
        started = self._start(fake)
        self.assertEqual(list(started), ['mysql', 'java'])
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[0][0][0], self.paths['mysqld'])
        self.assertEqual(fake.calls[1][0][0], self.paths['java'])
        self.assertEqual(fake.calls[0][1], self.paths['root'])
        self.assertTrue(ci.port_open('127.0.0.1', self.mysql_port))
        self.assertTrue(ci.port_open('127.0.0.1', self.java_port))

    def test_a_running_server_is_reused_not_restarted(self):
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', self.mysql_port))
        listener.listen(4)
        fake = FakeSpawn(self.java_port)
        started = self._start(fake)
        self.assertNotIn('mysql', started)
        self.assertEqual(len(fake.calls), 1)
        argv, cwd, log_path = fake.calls[0]
        self.assertEqual(argv[0], self.paths['java'])
        self.assertEqual(cwd, self.paths['root'])
        self.assertEqual(log_path, os.path.join(self.tmp, 'legacy-java.log'))

    def test_a_dead_server_fails_without_leaking_the_other(self):
        fake = FakeSpawn(self.java_port, die=True)
        with self.assertRaises(ci.StackError) as caught, \
                mock.patch.object(ci, 'spawn', fake), \
                mock.patch('builtins.print'):
            ci.start_stack(self.paths, 5.0, self.tmp, '127.0.0.1',
                           self.java_port, self.mysql_port)
        self.assertIn('legacy MySQL', str(caught.exception))
        self.assertTrue(caught.exception.log_path.endswith('legacy-mysql.log'))
        self.assertTrue(os.path.exists(caught.exception.log_path))

    def test_a_java_failure_stops_the_mysql_it_started(self):
        events = []
        fake = FakeSpawn(self.java_port, events=events, die_java=True)
        with self.assertRaises(ci.StackError) as caught, \
                mock.patch.object(ci, 'spawn', fake), \
                mock.patch.object(ci, 'shutdown_mysql',
                                  lambda *a, **k: events.append(
                                      'mysql-shutdown')), \
                mock.patch('builtins.print'):
            ci.start_stack(self.paths, 5.0, self.tmp, '127.0.0.1',
                           self.java_port, self.mysql_port)
        self.assertIn('Java oracle', str(caught.exception))
        self.assertIn('mysql-shutdown', events)
        self.assertIn('terminate:mysql', events)


class StopStackTest(unittest.TestCase):
    def _proxy(self, name, events):
        child = subprocess.Popen([sys.executable, '-c', 'import time; '
                                  'time.sleep(30)'])
        self.addCleanup(lambda: child.poll() is None and child.kill())
        return FakeServer(child, [], events, name)

    def test_java_stops_before_mysql_gets_its_shutdown(self):
        events = []
        paths = ci.stack_paths('nowhere')
        started = {'mysql': (self._proxy('mysql', events), None),
                   'java': (self._proxy('java', events), None)}
        with mock.patch.object(ci, 'shutdown_mysql',
                               lambda *a, **k: events.append('mysql-shutdown')):
            ci.stop_stack(started, paths)
        self.assertEqual(events, ['terminate:java', 'mysql-shutdown',
                                  'terminate:mysql'])
        self.assertEqual(started['java'][0].terminated, 1)
        self.assertEqual(started['mysql'][0].terminated, 1)

    def test_nothing_started_means_nothing_stopped(self):
        ci.stop_stack({}, ci.stack_paths('nowhere'))

    def test_shutdown_mysql_survives_a_missing_admin_binary(self):
        ci.shutdown_mysql(ci.stack_paths('nowhere'), 'secret')

    def test_shutdown_mysql_passes_the_password_in_the_environment(self):
        paths = ci.stack_paths('nowhere')
        paths['mysqladmin'] = __file__
        seen = {}

        def fake_run(argv, **kwargs):
            seen['argv'] = argv
            seen['env'] = kwargs.get('env', {})
            return mock.MagicMock(returncode=0)

        with mock.patch.object(ci.subprocess, 'run', fake_run):
            ci.shutdown_mysql(paths, 'hunter2')
        self.assertEqual(seen['env']['MYSQL_PWD'], 'hunter2')
        self.assertNotIn('hunter2', seen['argv'])


class MainGateTest(unittest.TestCase):
    def _main(self, argv):
        with mock.patch.object(sys, 'argv', ['ci-oracle-diff'] + argv):
            return ci.main()

    def test_missing_baseline_fails_closed(self):
        self.assertEqual(self._main(['--baseline',
                                     os.path.join(TOOLS, 'missing.json')]), 2)

    def test_external_python_needs_a_web_base(self):
        self.assertEqual(self._main(['--python', '127.0.0.1:8018',
                                     '--baseline', __file__]), 2)

    def test_unreadable_db_credentials_fail_closed(self):
        real = ci.load_module

        def fake(path, name):
            if path.endswith('migrate_mysql_to_sqlite.py'):
                raise SystemExit('no db_password')
            return real(path, name)

        with mock.patch.object(ci, 'load_module', fake):
            self.assertEqual(self._main(['--baseline', __file__]), 2)

    def test_no_start_stack_reports_the_missing_oracle(self):
        port = ci.free_port()
        with mock.patch.dict(os.environ, {'MKO_DIFF_PASSWORD': 'pw'}):
            status = self._main(['--java', f'127.0.0.1:{port}',
                                 '--python', '127.0.0.1:9',
                                 '--python-web', 'http://127.0.0.1:9',
                                 '--baseline', __file__, '--wait', '0.2',
                                 '--no-start-stack'])
        self.assertEqual(status, 2)

    def test_missing_stack_binaries_are_named(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(tmp, True))
        port = ci.free_port()
        with mock.patch.dict(os.environ, {'MKO_DIFF_PASSWORD': 'pw'}), \
                mock.patch.object(ci.sys, 'platform', 'win32'):
            status = self._main(['--java', f'127.0.0.1:{port}',
                                 '--python', '127.0.0.1:9',
                                 '--python-web', 'http://127.0.0.1:9',
                                 '--baseline', __file__, '--wait', '0.2',
                                 '--stack-root', tmp])
        self.assertEqual(status, 2)

    def test_a_non_windows_host_reports_the_binary_mismatch(self):
        port = ci.free_port()
        with mock.patch.dict(os.environ, {'MKO_DIFF_PASSWORD': 'pw'}), \
                mock.patch.object(ci.sys, 'platform', 'linux'):
            status = self._main(['--java', f'127.0.0.1:{port}',
                                 '--python', '127.0.0.1:9',
                                 '--python-web', 'http://127.0.0.1:9',
                                 '--baseline', __file__, '--wait', '0.2'])
        self.assertEqual(status, 2)


if __name__ == '__main__':
    unittest.main()

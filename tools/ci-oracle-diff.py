#!/usr/bin/env python3
"""CI gate: diff a freshly provisioned Python server against the Java oracle.

One command provisions everything. The legacy MySQL 5.1 and Java oracle are
started when their ports are idle (Windows binaries, see --stack-root); the
`stress` account is migrated into a temporary SQLite DB, Server-v1 starts on
free loopback ports with a throwaway sign secret, and tools/oracle-diff.py
compares it with the oracle. Every reply, push and command notification must
match or be listed in tools/oracle-baseline.json. Only servers this gate
started are stopped again, so a stack already running is reused untouched.

Usage: ci-oracle-diff.py [--cmd 50001] [options]

Exit status: 0 clean, 1 unbaselined reply/push/notification diff, 2 environment
not ready (stack binaries missing, boot failed, migration failed, server did
not start).
"""
import argparse
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, 'Server-v1')
DIFF_TOOL = os.path.join(ROOT, 'tools', 'oracle-diff.py')
MIGRATOR = os.path.join(ROOT, 'tools', 'migrate_mysql_to_sqlite.py')
DEFAULT_BASELINE = os.path.join(ROOT, 'tools', 'oracle-baseline.json')
DEFAULT_STACK = os.path.join(ROOT, 'reference', 'TonNgoKhong', 'server')
DEFAULT_CMDS = ['50001', '35011']
MYSQL_PORT = 3306


def load_module(path, name):
    """Import a hyphenated tool by path."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def free_port():
    """Bind port 0 and return the port the OS handed out."""
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def two_free_ports():
    """Distinct free ports for the game and web listeners."""
    first = free_port()
    second = free_port()
    while second == first:
        second = free_port()
    return first, second


def wait_for_tcp(host, port, timeout, interval=0.25):
    """True once a TCP connect succeeds, False when `timeout` runs out."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(interval)


def wait_for_http(url, timeout, interval=0.25):
    """True once the web server answers at all, including an HTTP error."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except urllib.error.HTTPError:
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(interval)


def port_open(host, port, timeout=1.0):
    """True when something already accepts connections on host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def stack_paths(root=DEFAULT_STACK):
    """Legacy binary paths under the server tree that `root` names."""
    mysql = os.path.join(root, 'ESSamp', 'MySQL5')
    return {'root': root, 'mysql_basedir': mysql,
            'mysql_datadir': os.path.join(mysql, 'data'),
            'mysqld': os.path.join(mysql, 'bin', 'mysqld.exe'),
            'mysqladmin': os.path.join(mysql, 'bin', 'mysqladmin.exe'),
            'java': os.path.join(root, 'jre6', 'bin', 'java.exe'),
            'jar': os.path.join(root, 'dntg_start.jar')}


def missing_binaries(paths):
    """Paths the stack needs that are absent, in a stable order."""
    return [paths[key] for key in ('mysqld', 'mysqladmin', 'java', 'jar')
            if not os.path.exists(paths[key])]


def mysql_argv(paths, port=MYSQL_PORT):
    """mysqld argv; my.ini's D:\\ paths cannot be trusted in a checkout."""
    return [paths['mysqld'], f'--basedir={paths["mysql_basedir"]}',
            f'--datadir={paths["mysql_datadir"]}', f'--port={port}']


def java_argv(paths):
    """server.bat's command line minus the GC log and the trailing pause."""
    return [paths['java'], '-cp', './;lib/*;lib/Jetty/*;extensions/__lib__/*',
            '-server', '-Xms256m', '-Xmx1024m',
            '-XX:PermSize=256M', '-XX:MaxPermSize=256M',
            '-jar', 'dntg_start.jar']


def mysql_shutdown_argv(paths, port=MYSQL_PORT):
    """mysqladmin line that closes the instance the gate started."""
    return [paths['mysqladmin'], '-h127.0.0.1', f'-P{port}', '-uroot',
            'shutdown']


class StackError(RuntimeError):
    """A legacy server this gate started did not become ready."""

    def __init__(self, message, log_path=''):
        super().__init__(message)
        self.log_path = log_path


def spawn(argv, cwd, log_path, env=None):
    """Start a background server with its output attached to `log_path`."""
    log = open(log_path, 'wb')
    try:
        proc = subprocess.Popen(argv, cwd=cwd, env=env,
                                stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT)
    except OSError:
        log.close()
        raise
    return proc, log


def wait_for_started_tcp(proc, host, port, timeout, interval=0.25):
    """Wait for a started server's listener, giving up early if it exits."""
    deadline = time.monotonic() + timeout
    while True:
        if port_open(host, port):
            return True
        if proc.poll() is not None:
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def start_stack(paths, wait, log_dir, java_host, java_port,
                mysql_port=MYSQL_PORT, password=''):
    """Boot the legacy MySQL and Java servers whose ports are still idle.

    Returns only the processes this call started, keyed by name, so shutdown
    never touches a server that was already running.
    """
    started = {}
    try:
        if not port_open('127.0.0.1', mysql_port):
            log_path = os.path.join(log_dir, 'legacy-mysql.log')
            started['mysql'] = spawn(mysql_argv(paths, mysql_port),
                                     paths['root'], log_path)
            if not wait_for_started_tcp(started['mysql'][0], '127.0.0.1',
                                        mysql_port, wait):
                raise StackError(f'legacy MySQL did not open port '
                                 f'{mysql_port} within {wait:g}s', log_path)
            print(f'oracle-ci: started legacy MySQL on 127.0.0.1:{mysql_port}')
        if not port_open(java_host, java_port):
            log_path = os.path.join(log_dir, 'legacy-java.log')
            started['java'] = spawn(java_argv(paths), paths['root'], log_path)
            if not wait_for_started_tcp(started['java'][0], java_host,
                                        java_port, wait):
                raise StackError(f'Java oracle did not open '
                                 f'{java_host}:{java_port} within {wait:g}s',
                                 log_path)
            print(f'oracle-ci: started Java oracle on {java_host}:{java_port}')
    except BaseException:
        stop_stack(started, paths, password)
        raise
    return started


def shutdown_mysql(paths, password='', port=MYSQL_PORT):
    """Ask a gate-started mysqld to close its tables, ignoring any failure."""
    if not os.path.exists(paths['mysqladmin']):
        return
    env = dict(os.environ)
    if password:
        env['MYSQL_PWD'] = password
    try:
        subprocess.run(mysql_shutdown_argv(paths, port), env=env,
                       capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass


def stop_stack(started, paths, password='', port=MYSQL_PORT):
    """Stop what start_stack began: Java first, then MySQL, and cleanly."""
    child = started.get('java')
    if child:
        stop(child[0])
    child = started.get('mysql')
    if child:
        shutdown_mysql(paths, password, port)
        stop(child[0])


def init_schema(db_path):
    """Create the Server-v1 schema the migrator expects to find."""
    store = load_module(os.path.join(SERVER, 'db.py'), 'mko_db').Store(db_path)
    store.close()


def sql_literal(text):
    """Quote a string as a MySQL single-quoted literal."""
    return "'" + str(text).replace("'", "''") + "'"


def legacy_password(mysql, user):
    """The legacy plaintext password used only for the Python web login."""
    rows = mysql.query('caonima', 'select password from account where name = '
                       + sql_literal(user))
    if not rows or not rows[0] or rows[0][0] is None:
        raise LookupError(f'no legacy account named {user!r}')
    return rows[0][0]


def diff_argv(args, python_addr, web_url):
    """oracle-diff arguments; the password travels in the environment only."""
    argv = [sys.executable, DIFF_TOOL,
            '--java', args.java,
            '--python', python_addr,
            '--python-web', web_url,
            '--user', args.user,
            '--baseline', args.baseline,
            '--timeout', f'{args.timeout:g}',
            '--push-window', f'{args.push_window:g}',
            '--notify-window', f'{args.notify_window:g}']
    for cmd in args.cmd:
        argv.extend(['--cmd', cmd])
    if args.report:
        argv.extend(['--report', args.report])
    return argv


def start_python(db_path, game_port, web_port, secret, log_path):
    """Start Server-v1 on loopback and attach its output to `log_path`."""
    env = dict(os.environ, MKO_SIGN_SECRET=secret, PYTHONUNBUFFERED='1')
    return spawn([sys.executable, 'server.py', '--db', db_path,
                  '--game', f'127.0.0.1:{game_port}',
                  '--web', f'127.0.0.1:{web_port}'],
                 SERVER, log_path, env)


def stop(proc, grace=10.0):
    """Terminate a child process, killing it if it ignores the first signal."""
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=grace)


def tail(path, lines=40):
    """Last `lines` of a log file, for failure diagnostics."""
    try:
        with open(path, 'rb') as handle:
            data = handle.read().decode('utf-8', 'replace').splitlines()
    except OSError:
        return []
    return data[-lines:]


def fail(message, log_path='', lines=40):
    """Print a setup failure plus any server log tail and return exit 2."""
    print(f'oracle-ci: {message}', file=sys.stderr)
    for line in tail(log_path, lines) if log_path else []:
        print(f'  | {line}', file=sys.stderr)
    return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--java', default='127.0.0.1:8008',
                        help='Java oracle address, booted when idle')
    parser.add_argument('--python', default='',
                        help='use a already running Python server at '
                             'HOST:PORT instead of starting one; needs '
                             '--python-web and MKO_DIFF_PASSWORD')
    parser.add_argument('--python-web', default='',
                        help='web base for --python')
    parser.add_argument('--baseline', default=DEFAULT_BASELINE)
    parser.add_argument('--user', default='stress',
                        help='legacy account migrated and logged in on both '
                             'sides')
    parser.add_argument('--cmd', action='append', default=[],
                        help='ID or ID:JSON-ARGS, repeatable; defaults to '
                             + ' '.join(DEFAULT_CMDS))
    parser.add_argument('--report', default='',
                        help='also write the diff report to this path')
    parser.add_argument('--timeout', type=float, default=4.0)
    parser.add_argument('--push-window', type=float, default=3.0)
    parser.add_argument('--notify-window', type=float, default=1.0)
    parser.add_argument('--wait', type=float, default=60.0,
                        help='seconds to wait for each server to become ready')
    parser.add_argument('--stack-root', default=DEFAULT_STACK,
                        help='legacy server tree holding jre6/, dntg_start.jar '
                             'and ESSamp/MySQL5 (default: the checkout copy)')
    parser.add_argument('--no-start-stack', action='store_true',
                        help='require MySQL and the Java oracle to be running '
                             'instead of booting them')
    parser.add_argument('--keep-stack', action='store_true',
                        help='leave running the legacy servers the gate '
                             'started')
    parser.add_argument('--keep', action='store_true',
                        help='keep the temporary DB and server log')
    args = parser.parse_args()
    args.cmd = args.cmd or list(DEFAULT_CMDS)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)

    if not os.path.exists(args.baseline):
        return fail(f'baseline not found: {args.baseline}; a new diff could '
                    'not be told from known noise')
    oracle = load_module(DIFF_TOOL, 'oracle_diff_tool')
    if args.python and not args.python_web:
        return fail('--python needs --python-web')
    if args.python and not os.environ.get('MKO_DIFF_PASSWORD'):
        return fail('--python needs MKO_DIFF_PASSWORD')
    if not args.report and os.environ.get('GITHUB_WORKSPACE'):
        args.report = os.path.join(os.environ['GITHUB_WORKSPACE'],
                                   'oracle-diff-report.txt')
    java_host, java_port = oracle.split_hostport(args.java)
    try:
        migrate = load_module(MIGRATOR, 'migrate_mysql_to_sqlite')
        db_password = migrate.mysql_password()
    except (OSError, SystemExit) as exc:
        migrate, db_password = None, ''
        if not args.python:
            return fail(f'cannot read the legacy MySQL credentials: {exc}')
    temp = tempfile.mkdtemp(prefix='mko-oracle-ci-')
    log_path = os.path.join(temp, 'python-server.log')
    paths = stack_paths(args.stack_root)
    proc = None
    log = None
    started = {}
    try:
        idle = (not port_open(java_host, java_port) or
                not port_open('127.0.0.1', MYSQL_PORT))
        if idle and not args.no_start_stack:
            if sys.platform != 'win32':
                return fail('the legacy MySQL and Java servers ship as '
                            'Windows binaries, which this platform cannot '
                            'run; use Windows, or start the stack yourself '
                            'and pass --no-start-stack')
            missing = missing_binaries(paths)
            if missing:
                return fail('legacy stack binaries missing (they are '
                            'gitignored; stage them under ' + args.stack_root
                            + ' or pass --no-start-stack):\n'
                            + '\n'.join(f'  {path}' for path in missing))
            try:
                started = start_stack(paths, args.wait, temp, java_host,
                                      java_port, password=db_password)
            except StackError as exc:
                return fail(str(exc), exc.log_path)
        if not wait_for_tcp(java_host, java_port, args.wait):
            return fail(f'no Java oracle on {args.java} after {args.wait:g}s; '
                        'drop --no-start-stack to let the gate boot it')

        if args.python:
            python_addr, web_url = args.python, args.python_web
            password = os.environ['MKO_DIFF_PASSWORD']
        else:
            if not wait_for_tcp('127.0.0.1', MYSQL_PORT, args.wait):
                return fail(f'no legacy MySQL on 127.0.0.1:{MYSQL_PORT} after '
                            f'{args.wait:g}s; the migration needs it')
            try:
                mysql = migrate.MySql(migrate.DEFAULT_MYSQL, db_password)
                password = legacy_password(mysql, args.user)
                db_path = os.path.join(temp, 'mko.db')
                init_schema(db_path)
                report = migrate.migrate(mysql, db_path, [args.user])
            except (OSError, LookupError, subprocess.SubprocessError,
                    SystemExit) as exc:
                return fail(f'migration failed: {exc}')
            print(f'oracle-ci: migrated {report["accounts_added"]} account(s), '
                  f'{report["roles_added"]} role(s) for {args.user}')
            game_port, web_port = two_free_ports()
            python_addr = f'127.0.0.1:{game_port}'
            web_url = f'http://127.0.0.1:{web_port}'
            secret = os.urandom(16).hex()
            proc, log = start_python(db_path, game_port, web_port, secret,
                                     log_path)
            if not wait_for_http(web_url + '/gamesession.php', args.wait):
                return fail('Python web server did not answer', log_path)
            if not wait_for_tcp('127.0.0.1', game_port, args.wait):
                return fail('Python game socket did not open', log_path)

        print(f'oracle-ci: java {args.java}, python {python_addr}, '
              f'web {web_url}')
        print(f'oracle-ci: commands {" ".join(args.cmd)}')
        env = dict(os.environ, MKO_DIFF_PASSWORD=password)
        status = subprocess.call(diff_argv(args, python_addr, web_url),
                                 env=env)
        if status == 0:
            print('oracle-ci: PASS (no unbaselined replies, pushes or '
                  'notifications)')
            return 0
        if status == 1:
            print('oracle-ci: FAIL (unbaselined reply/push/notification diff; '
                  'see MISMATCH, PUSH-*, NOTIFY-* lines above)', file=sys.stderr)
            if proc is not None and proc.poll() is not None:
                print(f'oracle-ci: the Python server exited '
                      f'({proc.returncode})', file=sys.stderr)
                for line in tail(log_path):
                    print(f'  | {line}', file=sys.stderr)
            return 1
        return fail(f'oracle-diff could not run (exit {status})', log_path)
    finally:
        if log:
            log.close()
        stop(proc)
        if started and args.keep_stack:
            print('oracle-ci: left the legacy stack running (--keep-stack)')
        elif started:
            stop_stack(started, paths, db_password)
        if args.keep:
            print(f'oracle-ci: kept {temp}')
        else:
            shutil.rmtree(temp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())

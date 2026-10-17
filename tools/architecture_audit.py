#!/usr/bin/env python3
"""Compare the legacy Java+MySQL architecture with the Python+SQLite stack.

Reads the generated artifacts (no hand-typed counts):
  output/jar-inventory.json            Java command IDs -> implementing classes
  output/orig-stack/mysql-backup-*.sql  MySQL table definitions (schema dump)
  Server-v1/game/protocol.py           Python command dispatch (CMD_* constants)
  Server-v1/db.py                      SQLite schema

Writes docs/full-architecture-audit.md. Usage (from the repo root):
  python3 tools/architecture_audit.py [--out docs/full-architecture-audit.md]
"""
import argparse
import glob
import json
import os
import re
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
INVENTORY = os.path.join(ROOT, 'output', 'jar-inventory.json')
PROTOCOL = os.path.join(ROOT, 'Server-v1', 'game', 'protocol.py')
DB = os.path.join(ROOT, 'Server-v1', 'db.py')

# Legacy MySQL table -> SQLite table/column that carries the same state.
# Only tables the Python server actually reads or writes are listed.
MYSQL_TO_SQLITE = {
    'user_role': 'characters',
    'account': 'accounts',
    'role_account': 'characters (tongqian, bind_lingshi)',
    'role_stage': 'role_stage',
    'role_setting': 'role_settings',
    'role_equip_slot': 'role_equip',
    'role_attribute_buff': 'role_attr_buff',
    'role_vip': 'role_vip',
    'role_xianjiechenhao': 'role_xianjiechenhao',
    'role_meiren': 'role_meiren',
    'role_zuoqi': 'role_zuoqi',
    'role_skill': 'role_skill',
    'role_shenjiang': 'role_shenjiang',
}


def family_of(classes):
    """Business family from the first com.xianling package segment."""
    for c in classes:
        name = c.get('class', '')
        m = re.match(r'com\.xianling\.(bus\.)?([a-z_0-9]+)', name)
        if m:
            return m.group(2)
    return 'unknown'


# Jar-scan IDs that are not wire commands (verified with tools/javap.py:
# no ModuleInit.getInCmd routes them; only ServiceImpl refs remain).
# 2000 is MallServiceImpl.getGoodsCountPrice; 1003/1006 are GeneralErrorCode
# JB/NOSLOT (protocol.py GENERAL_JB/GENERAL_NOSLOT); 430405 is the 32002
# unknown-goods error payload; 794000/794001/794002 are VipQqErrorCode
# NOTIN_LIST/LINGQU_AGAIN/NOT_CONFIG. 88005 stays: vipQqOK pushes it.
NON_COMMAND_IDS = frozenset({'2000', '1003', '1006', '430405',
                              '794000', '794001', '794002'})


def load_java():
    with open(INVENTORY, encoding='utf-8') as f:
        data = json.load(f)
    commands = {k: v for k, v in data['commands'].items()
                if k not in NON_COMMAND_IDS}
    families = defaultdict(lambda: {'ids': set(), 'classes': 0})
    for cmd_id, classes in commands.items():
        fam = family_of(classes)
        families[fam]['ids'].add(cmd_id)
    for mod in data['modules']:
        fam = family_of([mod])
        families[fam]['classes'] += 1
    return commands, families


def load_python_commands():
    with open(PROTOCOL, encoding='utf-8') as f:
        src = f.read()
    values = {m.group(1): int(m.group(2))
              for m in re.finditer(r'^(CMD_\w+)\s*=\s*(\d+)', src, re.M)}
    used = set(re.findall(r'cmd_num\s*(?:==|in)\s*\(?\s*(CMD_\w+)', src))
    used |= set(re.findall(r'cmd_num\s+in\s+(CMD_\w+)', src))
    return {str(values[name]) for name in used if name in values}


def load_python_emitted():
    """Command IDs the server code sends as outbound frames (pushes and replies)."""
    values = {}
    for path in glob.glob(os.path.join(ROOT, 'Server-v1', 'game', '*.py')):
        with open(path, encoding='utf-8') as f:
            src = f.read()
        values.update({m.group(1): int(m.group(2))
                       for m in re.finditer(r'^(CMD_\w+)\s*=\s*(\d+)', src, re.M)})
    emitted = set()
    for path in glob.glob(os.path.join(ROOT, 'Server-v1', 'game', '*.py')):
        with open(path, encoding='utf-8') as f:
            src = f.read()
        for name in re.findall(r'str\(\s*(CMD_\w+)\s*\)', src):
            if name in values:
                emitted.add(str(values[name]))
        emitted.update(re.findall(r"\[\s*['\"](\d{4,6})['\"]\s*,", src))
    return emitted


def load_mysql_tables():
    dumps = sorted(glob.glob(os.path.join(ROOT, 'output', 'orig-stack',
                                          'mysql-backup-*.sql')))
    if not dumps:
        return set()
    with open(dumps[-1], encoding='utf-8', errors='replace') as f:
        text = f.read()
    return set(re.findall(r'CREATE TABLE `([a-z_0-9]+)`', text))


def load_sqlite_tables():
    with open(DB, encoding='utf-8') as f:
        return set(re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)', f.read()))


# Layer-by-layer comparison. Each row cites the artifact it was read from.
LAYERS = [
    ('Web login/session', 'Apache httpd + PHP5 module (`output/orig-stack/httpd.conf`)',
     '`Server-v1/web.py` on `http.server`, PBKDF2 passwords, SQLite sessions', 'Partial; see parity audit'),
    ('Game socket', 'Java game server (`com.xianling.bus.client`, `com.xianling.io`); transport class not verified from bytecode',
     '`Server-v1/server.py` `ThreadingTCPServer`, one thread per connection', 'Framing and key exchange match captures'),
    ('Persistence', 'MySQL 5.1.37 through iBATIS accessors (`com.kernel.data`, `IIBatisDatabaseAccessor`)',
     'SQLite via `sqlite3` in `Server-v1/db.py`, one lock per Store', 'Only 23 SQLite tables (13 mapped from MySQL); see table section'),
    ('Config data', 'AMF3 `.jat`/`.mm` read through BlazeDS `Amf3Input` (`game-data-inventory.md`)',
     'Own AMF3 codec `game/amf3.py` + loaders in `game/config.py`', 'Decodes all 218 `.jat`; see game-data inventory'),
    ('Scheduling', 'Quartz scheduled jobs (`com.xianling.global`)',
     'Mirror in `game/scheduler.py` (heartbeat, schedule map, quartz cron,'
     ' token runnables) + 1s server tick driving `Session.tick()`', 'Partial: timed stage pushes flow; per-monster stagger still single-clock'),
    ('Event bus / services', 'Event service and ~90 ServiceImpl classes per large family (`com.xianling.eventservice`)',
     '`game/eventbus.py` EventCenter mirror (per-session via `Session.publish`); inner tokens dispatch in `tick()`',
     'Partial: bus exists, no call sites publish yet'),
    ('Cross-server', 'kuafu and messageswap (`com.xianling.bus.kuafu`, `com.xianling.messageswap`)',
     'None', 'Out of scope for single-server play'),
    ('Auth on game socket', 'MD5 of uid + key + timestamp (parity audit, security section)',
     'Same legacy sign, kept for client compatibility', 'Replay-prone; keep behind a trusted boundary'),
]


def render_layers():
    lines = ['## Architecture layers', '',
             '| Layer | Java + MySQL | Python + SQLite | Status |', '|---|---|---|---|']
    for layer, java, py, status in LAYERS:
        lines.append(f'| {layer} | {java} | {py} | {status} |')
    lines.append('')
    return lines


def render(commands, families, py_ids, mysql, sqlite):
    java_ids = set(commands)
    covered = java_ids & py_ids
    lines = []
    w = lines.append
    w('# Full architecture audit: Java+MySQL vs Python+SQLite')
    w('')
    w('Generated by `tools/architecture_audit.py` from `output/jar-inventory.json`, '
      'the MySQL schema dump, `Server-v1/game/protocol.py` and `Server-v1/db.py`. '
      'Re-run after changing either server; do not edit the counts by hand.')
    w('')
    w('"Dispatched" means a `CMD_*` constant is routed in `protocol.py`. It does '
      'not mean the behaviour matches Java; see [java-python-parity-audit.md]'
      '(java-python-parity-audit.md) for behaviour.')
    w('')
    w('## Totals')
    w('')
    w('| Measure | Java + MySQL | Python + SQLite |')
    w('|---|---|---|')
    w(f'| Command IDs | {len(java_ids)} | {len(py_ids)} dispatched |')
    w(f'| Command IDs dispatched by Python | {len(covered)} of {len(java_ids)} '
      f'({100 * len(covered) / max(len(java_ids), 1):.1f}%) | - |')
    w(f'| Python dispatches IDs Java does not list | - | '
      f'{len(py_ids - java_ids)} |')
    w(f'| Tables | {len(mysql)} | {len(sqlite)} |')
    w(f'| Mapped legacy tables present in the dump | '
      f'{len(set(MYSQL_TO_SQLITE) & mysql)} of {len(MYSQL_TO_SQLITE)} | - |')
    w('')
    lines.extend(render_layers())
    w('## Command IDs by family')
    w('')
    w('| Family | Java command IDs | Dispatched by Python | Missing |')
    w('|---|---|---|---|')
    for fam in sorted(families, key=lambda f: -len(families[f]['ids'])):
        ids = families[fam]['ids']
        got = ids & py_ids
        if not ids:
            continue
        w(f'| `{fam}` | {len(ids)} | {len(got)} | {len(ids) - len(got)} |')
    w('')
    w('Java command IDs are not unique to one family: a few numbers such as '
      '`11101` appear under many modules. Family counts can overlap.')
    w('')
    w('## Tables: legacy MySQL to local SQLite')
    w('')
    w('| MySQL table | Local SQLite state | Status |')
    w('|---|---|---|')
    for name in sorted(MYSQL_TO_SQLITE):
        status = 'in dump' if name in mysql else 'missing from dump'
        w(f'| `{name}` | {MYSQL_TO_SQLITE[name]} | {status} |')
    w('')
    unmapped = sorted(mysql - set(MYSQL_TO_SQLITE))
    w(f'Not mapped: {len(unmapped)} MySQL tables have no local equivalent. '
      'These are the unported domain state (guilds, mail, rankings, pets, '
      'shops, events, and so on). They are deliberately out of scope until a '
      'command module needs them; see [mysql-to-sqlite-migration.md]'
      '(mysql-to-sqlite-migration.md).')
    w('')
    w('## Not covered by the Python server')
    w('')
    w('Java command IDs with no Python dispatch are listed in '
      '[java-command-map.md](java-command-map.md). Java IDs such as `000`, `001` '
      'and `002` come from the jar scan and may be non-command noise; they are '
      'not verified here.')
    w('')
    return '\n'.join(lines) + '\n'


TEST_DIRS = [os.path.join(ROOT, 'Server-v1', 'tests'),
             os.path.join(ROOT, 'tools', 'tests')]
CMD_VALUES = {}
with open(PROTOCOL, encoding='utf-8') as _f:
    CMD_VALUES = {m.group(1): str(m.group(2))
                  for m in re.finditer(r'^(CMD_\w+)\s*=\s*(\d+)', _f.read(), re.M)}


def find_test_refs(cmd_ids):
    """Map each command ID to the test files that send or quote it.

    Only command-shaped mentions count: a quoted ID, a list head like `[12010,`,
    or a CMD_ constant. Bare small numbers in fixtures (`001`, `100`) do not.
    IDs under four digits are skipped as too ambiguous to attribute.
    """
    refs = {cmd: set() for cmd in cmd_ids}
    patterns = {}
    for cmd in cmd_ids:
        if len(cmd) < 4:
            continue
        n = re.escape(cmd)
        patterns[cmd] = re.compile(
            r"['\"]" + n + r"['\"]|\[" + n + r"[,\]]|\b" + n + r"\s*\]")
    for test_dir in TEST_DIRS:
        if not os.path.isdir(test_dir):
            continue
        for name in sorted(os.listdir(test_dir)):
            if not name.endswith('.py'):
                continue
            with open(os.path.join(test_dir, name), encoding='utf-8') as f:
                text = f.read()
            rel = os.path.relpath(os.path.join(test_dir, name), ROOT)
            for cmd, pat in patterns.items():
                if pat.search(text):
                    refs[cmd].add(rel.replace(os.sep, '/'))
            # CMD_ constants used in tests: map the constant back to its value.
            for name, value in CMD_VALUES.items():
                if re.search(r'\b' + name + r'\b', text) and value in refs:
                    refs[value].add(rel.replace(os.sep, '/'))
    return refs


# A test file reads state back when it queries the store after the action.
STORE_READBACK = re.compile(r'\.store\.(get_|list_)\w*\s*\(')


def find_store_readback_files():
    """Relative paths of test files that read state back through the store."""
    files = set()
    for test_dir in TEST_DIRS:
        if not os.path.isdir(test_dir):
            continue
        for name in os.listdir(test_dir):
            if not name.endswith('.py'):
                continue
            with open(os.path.join(test_dir, name), encoding='utf-8') as f:
                if STORE_READBACK.search(f.read()):
                    rel = os.path.relpath(os.path.join(test_dir, name), ROOT)
                    files.add(rel.replace(os.sep, '/'))
    return files


def ledger_status(cmd, py_ids, test_refs, emitted=False, readback_files=frozenset()):
    """not started < dispatched < golden-tested < persisted.

    Dispatch alone is not parity. 'persisted' means a test that mentions the
    ID also reads state back through the store (a file-level heuristic).
    Server pushes have no inbound route; they are 'emitted', or
    'push-golden-tested' when a test mentions them.
    """
    if cmd in py_ids and test_refs:
        return 'persisted' if test_refs & readback_files else 'golden-tested'
    if cmd in py_ids:
        return 'dispatched'
    if emitted and test_refs:
        return 'push-golden-tested'
    if emitted:
        return 'emitted'
    return 'not started'


def render_ledger(commands, families, py_ids, emitted=frozenset()):
    """One row per Java command ID: family, status and the tests that mention it."""
    test_refs = find_test_refs(set(commands))
    readback_files = find_store_readback_files()
    id_family = {}
    for fam, data in families.items():
        for cmd in data['ids']:
            id_family.setdefault(cmd, fam)
    lines = ['# Command ledger (generated)', '',
             'Generated by `tools/architecture_audit.py --ledger` from the jar '
             'inventory, `Server-v1/game/protocol.py` and the test suites. One '
             'row per Java command ID. Statuses:',
             '',
             '- `not started`: no `CMD_*` route in `protocol.py`.',
             '- `dispatched`: routed, but no test mentions the ID.',
             '- `golden-tested`: routed and a test file mentions the ID. The test '
             'mention is a weak signal; read the test before trusting it.',
             '- `persisted`: golden-tested, and a test file mentioning the ID also '
             'reads state back through `store.get_*`/`store.list_*`. This is a '
             'file-level heuristic, not proof that the write was checked.',
             '- `emitted`: the server sends the ID as a push or reply, but no '
             '`CMD_*` route exists. No test mentions it.',
             '- `push-golden-tested`: emitted, and a test file mentions the ID.',
             '',
             'Status counts are computed from the artifacts; regenerate instead of '
             'editing by hand.',
             '']
    counts = {'not started': 0, 'dispatched': 0, 'golden-tested': 0,
              'persisted': 0, 'emitted': 0, 'push-golden-tested': 0}
    rows = []
    for cmd in sorted(commands, key=lambda c: (len(c), c)):
        status = ledger_status(cmd, py_ids, test_refs[cmd], cmd in emitted,
                               readback_files)
        counts[status] += 1
        tests = ', '.join(sorted(test_refs[cmd])) or '-'
        rows.append(f'| `{cmd}` | {id_family.get(cmd, "-")} | {status} | {tests} |')
    lines.append('| Totals | ' + ', '.join(f'{k}: {v}' for k, v in counts.items())
                 + ' | | |')
    lines.append('')
    lines.append('| Command | Family | Status | Mentioned in tests |')
    lines.append('|---|---|---|---|')
    lines.extend(rows)
    lines.append('')
    return '\n'.join(lines) + '\n', counts


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', default=os.path.join(
        ROOT, 'docs', 'full-architecture-audit.md'))
    parser.add_argument('--ledger', action='store_true',
                        help='write docs/command-ledger.md instead of the audit')
    parser.add_argument('--ledger-out', default=os.path.join(
        ROOT, 'docs', 'command-ledger.md'))
    args = parser.parse_args()
    commands, families = load_java()
    py_ids = load_python_commands()
    if args.ledger:
        text, counts = render_ledger(commands, families, py_ids,
                                     load_python_emitted())
        with open(args.ledger_out, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'wrote {args.ledger_out}: {counts}')
        return
    mysql = load_mysql_tables()
    sqlite = load_sqlite_tables()
    text = render(commands, families, py_ids, mysql, sqlite)
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f'wrote {args.out}: {len(commands)} java ids, {len(py_ids)} python '
          f'dispatched, {len(mysql)} mysql tables, {len(sqlite)} sqlite tables')


if __name__ == '__main__':
    main()

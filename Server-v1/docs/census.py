"""Generate docs/command-census.md from javap dumps + the Python dispatcher.

Inputs (workspace root): javacmds.txt (javap -constants of every
*Commands class in dntg_start.jar), actionmethods.txt (javap -p of
every *easyaction*Action class). Run from Server-v1/:
`python3 docs/census.py`. Keeps the census short and mechanical: it
counts, it does not re-reverse-engineer handlers.
"""
import ast
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
JAVA_CMDS = os.path.join(ROOT, 'javacmds.txt')
JAVA_METHODS = os.path.join(ROOT, 'actionmethods.txt')
PROTO = os.path.join(os.path.dirname(__file__), '..', 'game', 'protocol.py')
TESTS = os.path.join(os.path.dirname(__file__), '..', 'tests')
OUT = os.path.join(os.path.dirname(__file__), 'command-census.md')

STUB_MARKERS = ('stub', 'deferred', 'no handler', 'not ported',
                'placeholder', 'unported', 'fire-and-forget', 'no-op',
                'noop', 'logged only', 'silent null', 'not implemented')


def java_commands():
    rows = []
    for line in open(JAVA_CMDS, encoding='utf-8', errors='replace'):
        m = re.match(
            r'(\S+) +public static final java\.lang\.String (\S+) = "(.*)";',
            line.strip())
        if m and re.fullmatch(r'\d+', m.group(3)):
            rows.append((m.group(1), m.group(2), m.group(3)))
    return rows


def java_actions():
    methods = defaultdict(list)
    cls = None
    for line in open(JAVA_METHODS, encoding='utf-8', errors='replace'):
        line = line.strip()
        if line.startswith('## '):
            cls = line[3:]
        elif cls and line.startswith('public '):
            m = re.search(r' (\w+)\(', line)
            if m:
                methods[cls].append(m.group(1))
    return methods


def python_dispatch():
    src = open(PROTO, encoding='utf-8').read()
    consts = dict(re.findall(r'^\s*(CMD_[A-Z0-9_]+)\s*=\s*(\d+)',
                             src, re.M))
    observed = set()
    m = re.search(r'CMD_UNKNOWN_OBSERVED\s*=\s*\{([^}]*)\}', src)
    if m:
        for tok in re.findall(r'[A-Z0-9_]+|\d+', m.group(1)):
            observed.add(consts.get(tok, tok))
    handlers = {}
    order = []
    for m in re.finditer(
            r'if cmd_num (==|in) ([A-Z0-9_, \[\]\(\)]+):\n((?:.*\n){1,6}?)',
            src):
        op, expr, body = m.group(1), m.group(2), m.group(3)
        names = ([expr.strip()] if op == '==' else
                 [t for t in re.findall(r'[A-Z0-9_]+|\d+', expr)])
        hm = re.search(r'return self\.(\w+)', body)
        handler = hm.group(1) if hm else None
        for tok in names:
            if tok.isdigit() or tok in consts:
                val = consts.get(tok, tok)
                handlers[val] = handler
                order.append(val)
    tree = ast.parse(src)
    methods = {n.name: n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)}
    return handlers, methods, observed, consts


def classify(handler, methods):
    if handler is None:
        return 'dispatched-no-direct-handler'
    node = methods.get(handler)
    if node is None:
        return 'partial'
    doc = (ast.get_docstring(node) or '').lower()
    if any(k in doc for k in STUB_MARKERS):
        return 'stub'
    return 'implemented'


def main():
    cmds = java_commands()
    by_id = defaultdict(list)
    for cls, name, vid in cmds:
        parts = cls.split('.')
        mod = parts[3] if len(parts) > 4 else '?'
        by_id[vid].append((mod, cls, name))
    handlers, methods, observed, consts = python_dispatch()
    test_src = ''
    for fn in os.listdir(TESTS):
        if fn.endswith('.py'):
            test_src += open(os.path.join(TESTS, fn), encoding='utf-8',
                             errors='replace').read()
    tested = set(re.findall(r"'(1?\d{4,6})'", test_src))
    lines = []
    lines.append('# Java-vs-Python command census')
    lines.append('')
    lines.append('Mechanical diff: `*Commands` string constants from '
                 f'dntg_start.jar` ({len(by_id)} distinct numeric IDs) vs the '
                 f'`Session.handle` dispatcher ({len(handlers)} distinct '
                 'values). Dispatch registration is counted, not '
                 'behavioral parity.')
    lines.append('')
    counts = defaultdict(int)
    mod_rows = defaultdict(lambda: defaultdict(int))
    mod_missing = defaultdict(list)
    for vid in sorted(by_id, key=int):
        mods = sorted(set(m for m, _, _ in by_id[vid]))
        if vid not in handlers:
            status = ('known-unhandled' if vid in observed else 'missing')
        else:
            h = handlers[vid]
            if h is None:
                status = ('known-unhandled'
                          if vid in observed else 'inline')
                if status == 'inline' and vid not in tested:
                    status = 'inline-untested'
            else:
                status = classify(h, methods)
                if status == 'implemented' and vid not in tested:
                    status = 'implemented-untested'
        counts[status] += 1
        for mod in mods:
            mod_rows[mod][status] += 1
        if status in ('missing', 'known-unhandled'):
            mod_missing[mods[0]].append((vid, by_id[vid][0][2]))
    total = len(by_id)
    lines.append('## Totals')
    lines.append('')
    lines.append(f'- total Java numeric command IDs: {total}')
    order = ('implemented', 'implemented-untested', 'partial',
             'dispatched-no-direct-handler', 'inline',
             'inline-untested', 'stub', 'known-unhandled', 'missing')
    for key in order:
        lines.append(f'- {key}: {counts.get(key, 0)}')
    lines.append(f'- accounted: {sum(counts.values())} of {total} '
                 f'({"exact" if sum(counts.values()) == total else "MISMATCH"})')
    lines.append('')
    lines.append('`implemented` = dispatched, handler not stub-marked, and '
                 'the ID string appears in the focused tests. '
                 '`implemented-untested` = same without a test reference.')
    lines.append('')
    lines.append('## Counting methods (why 497 != ~600)')
    lines.append('')
    lines.append('497 counts distinct numeric command IDs (one wire value = '
                 'one row). The earlier ~600 figure counts method mappings: '
                 '`javacmds.txt` holds 684 `*Commands` constant rows (30 '
                 'share a numeric ID with another name; the rest are '
                 'non-numeric strings, not commands), and '
                 '`actionmethods.txt` holds 844 public action methods '
                 '(overloads, push/notify variants, and helpers that share '
                 'one command ID). Neither figure is wrong; progress '
                 'percentages must use one denominator consistently. This '
                 'ledger uses distinct numeric IDs.')
    lines.append('')
    lines.append('## Per-module status (implemented+untested / stub / '
                 'missing+known / total)')
    lines.append('')
    lines.append('| module | done | untested | stub | missing | total |')
    lines.append('| --- | --- | --- | --- | --- | --- |')
    for mod in sorted(mod_rows,
                      key=lambda m: -(mod_rows[m]['missing'] +
                                      mod_rows[m]['known-unhandled'])):
        r = mod_rows[mod]
        done = r['implemented']
        untested = r['implemented-untested'] + r['partial'] + \
            r['dispatched-no-direct-handler'] + r['inline'] + \
            r['inline-untested']
        stub = r['stub']
        missing = r['missing'] + r['known-unhandled']
        lines.append(f'| {mod} | {done} | {untested} | {stub} | '
                     f'{missing} | {done + untested + stub + missing} |')
    lines.append('')
    lines.append('## Missing IDs by module (id: const / python handler)')
    lines.append('')
    for mod in sorted(mod_missing,
                      key=lambda m: -len(mod_missing[m])):
        ids = ', '.join(f'{v} ({n})' for v, n in
                        sorted(mod_missing[mod], key=lambda t: int(t[0])))
        lines.append(f'- {mod} ({len(mod_missing[mod])}): {ids}')
    lines.append('')
    open(OUT, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print(f'{total} java ids, {len(handlers)} dispatched; wrote {OUT}')


if __name__ == '__main__':
    sys.exit(main())

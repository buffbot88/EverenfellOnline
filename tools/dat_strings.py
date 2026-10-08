#!/usr/bin/env python3
"""Extract Chinese text runs from the game's binary .dat/.jat tables.

The tables under res/java/<locale>/ are AMF3-serialized objects (0x06
string markers with U29 lengths), but this tool is deliberately
format-agnostic: it decodes the file as UTF-8 (surrogateescape keeps a 1:1
byte<->char map) and pulls out runs of CJK/fullwidth characters with their
byte offsets. Output feeds the English translation memory (TM).

Usage:
  python3 tools/dat_strings.py <dir> -o .survey/i18n_zh.json [--min 2]
  python3 tools/dat_strings.py <dir> --stats          # scope estimate only

TM schema (JSON):
  { "<source>": {"count": N, "files": {"talk.dat": [offset, ...]}} }
Offsets let a future AMF3-aware rewriter replace strings in place to build
translated locale tables (e.g. res/java/en/) without breaking length prefixes.
"""
import json
import os
import re
import sys

# CJK Unified + Ext A + Compat + CJK punctuation + fullwidth forms.
CJK = (
    r'\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff'
    r'\u3000-\u303f\uff00-\uffef\u2010-\u201f\u00a3\u00a5'
)


def extract_file(path, min_len=2):
    raw = open(path, 'rb').read()
    # surrogateescape: 1 char per byte, so char offsets == byte offsets.
    text = raw.decode('utf-8', errors='surrogateescape')
    pat = re.compile(f'[{CJK}]{{{min_len},}}')
    out = []
    for m in pat.finditer(text):
        s = m.group(0)
        # Drop runs that are actually lone surrogates (invalid UTF-8 bytes).
        if any(0xDC80 <= ord(c) <= 0xDCFF for c in s):
            continue
        out.append((m.start(), s))
    return out


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    src, out, stats_only, min_len = args[0], None, False, 2
    i = 1
    while i < len(args):
        if args[i] == '-o':
            out = args[i + 1]
            i += 2
        elif args[i] == '--stats':
            stats_only = True
            i += 1
        elif args[i] == '--min':
            min_len = int(args[i + 1])
            i += 2
        else:
            i += 1

    tm = {}  # text -> {"count": n, "files": {file: [offsets]}}
    n_files, n_hits = 0, 0
    targets = []
    if os.path.isdir(src):
        for dp, _, fns in os.walk(src):
            for fn in sorted(fns):
                if fn.endswith(('.dat', '.jat')):
                    targets.append(os.path.join(dp, fn))
    else:
        targets = [src]
    for path in sorted(targets):
        fn = os.path.basename(path)
        try:
            hits = extract_file(path, min_len)
        except OSError as e:
            print(f'skip {fn}: {e}', file=sys.stderr)
            continue
        n_files += 1
        n_hits += len(hits)
        for off, s in hits:
            e = tm.setdefault(s, {'count': 0, 'files': {}})
            e['count'] += 1
            e['files'].setdefault(fn, []).append(off)

    print(f'files: {n_files}  occurrences: {n_hits}  unique: {len(tm)}')
    top = sorted(tm.items(), key=lambda kv: -kv[1]['count'])[:10]
    print('top strings by occurrence:')
    for s, e in top:
        print(f'  {e["count"]:5d}x  {s[:60]}')
    if out and not stats_only:
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(tm, f, ensure_ascii=False, indent=1)
        print(f'wrote {out} ({os.path.getsize(out)} bytes)')
    elif stats_only:
        by_file = {}
        for s, e in tm.items():
            for fn, offs in e['files'].items():
                by_file[fn] = by_file.get(fn, 0) + len(offs)
        print('heaviest files:')
        for fn, c in sorted(by_file.items(), key=lambda kv: -kv[1])[:15]:
            print(f'  {c:6d}  {fn}')


if __name__ == '__main__':
    main()

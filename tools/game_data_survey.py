"""Survey the legacy binary game tables (.dat/.jat/.mm) with the Python AMF3 codec.

For every file, tries raw AMF3 and zlib-wrapped AMF3, and records the outcome:
decoded, or the byte offset and marker where decoding stopped. Writes a JSON
report so the gaps can be counted and fixed by marker, not guessed.

Usage: game_data_survey.py [--root DIR] [--out PATH]
"""
import argparse
import collections
import json
import os
import sys
import time
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'Server-v1'))
from game import amf3  # noqa: E402

DEFAULT_ROOT = os.path.join(ROOT, 'reference', 'TonNgoKhong', 'server', 'config')
DEFAULT_OUT = os.path.join(ROOT, 'output', 'game-data-survey.json')
EXTS = ('.dat', '.jat', '.mm')


def try_decode(data):
    """Return (status, detail) for one blob, trying raw then zlib."""
    attempts = [('raw', data)]
    if data[:1] == b'\x78':
        try:
            attempts.append(('zlib', zlib.decompress(data)))
        except zlib.error:
            pass
    last = None
    for label, blob in attempts:
        reader = amf3.Reader(blob)
        try:
            while reader.p < len(blob):
                reader.read()
            return {'status': 'ok', 'format': label, 'bytes': len(blob),
                    'values': _count_values(reader)}
        except Exception as exc:  # any decode failure is data, not a crash
            last = {'status': 'fail', 'format': label, 'bytes': len(blob),
                    'offset': reader.p,
                    'marker': f'0x{blob[reader.p]:02x}' if reader.p < len(blob) else None,
                    'error': f'{type(exc).__name__}: {exc}'[:160]}
    return last


def _count_values(reader):
    return len(reader.objects)


def survey(root):
    results = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not name.lower().endswith(EXTS):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace(os.sep, '/')
            with open(path, 'rb') as fh:
                data = fh.read()
            t0 = time.time()
            result = try_decode(data)
            result['seconds'] = round(time.time() - t0, 3)
            results[rel] = result
    return results


def summary(results):
    by_status = collections.Counter(r['status'] for r in results.values())
    failing = collections.Counter(
        r['marker'] for r in results.values()
        if r['status'] == 'fail' and r.get('marker'))
    return {'files': len(results), 'by_status': dict(by_status),
            'failing_markers': dict(failing.most_common(20))}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', default=DEFAULT_ROOT)
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args()
    results = survey(args.root)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8', newline='\n') as out:
        json.dump({'summary': summary(results), 'files': results},
                  out, ensure_ascii=False, indent=1, sort_keys=True)
    print(json.dumps(summary(results), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()

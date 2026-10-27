"""Resolve HUD targets down to bitmap character IDs with accumulated offsets.

Reuses audit_hud + decode_create_ui to walk sprite placements
recursively and report every bitmap leaf (cid, depth path, at-offset,
bounds). Unlinked children ('?') and imported refs (tg.shared.*) are
reported as gaps, not guessed. Writes output/hud-bitmap-map.json.

Usage (from the repo root):
  python scripts/asset_tools/resolve_hud_bitmaps.py
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swf_inventory as s  # noqa: E402
import audit_hud as A  # noqa: E402
from decode_create_ui import parse_shape  # noqa: E402

FOCUS = ['ui.StateBar', 'ui.MiniMap', 'ui.panel.TaskTrack', 'ui.ChatSkin',
         'ui.ZDLView', 'ui.HpBar', 'ui.HeroBar', 'ui.panel.maiyao',
         'ui.BloodShape', 'ui.panel.Target']


def resolve_module(module, path):
    """Return per-target bitmap leaf rows for one dump file."""
    body, _, link_of, sprites, edittexts, shapes, bitmaps = A.audit(path)
    named = {name: cid for cid, name in link_of.items()}
    shape_cache = {}

    def shape_fills(cid):
        if cid in shape_cache:
            return shape_cache[cid]
        fills = []
        if cid in shapes:
            code, ps, ln = shapes[cid]
            try:
                fills = parse_shape(body, ps, ln, code, bitmaps).get(
                    'bitmap_fills', [])
            except Exception:
                fills = []
        shape_cache[cid] = fills
        return fills

    def walk(cid, at, depth_path, seen):
        rows = []
        if cid in seen:
            return [{'gap': 'cycle', 'at': at, 'path': depth_path}]
        if cid in bitmaps:
            return [{'bitmap': cid, 'at': at, 'path': depth_path}]
        if cid in shapes:
            for fill in shape_fills(cid):
                bid = fill['bitmap'] if isinstance(fill, dict) else fill
                row = {'bitmap': bid, 'via_shape': cid, 'at': at,
                       'path': depth_path}
                if isinstance(fill, dict):
                    row['fill_tx'] = [fill.get('tx_px'), fill.get('ty_px')]
                rows.append(row)
            if not shape_fills(cid):
                rows.append({'gap': 'vector-only shape %d' % cid, 'at': at,
                             'path': depth_path})
            return rows
        if cid in edittexts:
            return [{'edittext': cid, 'at': at, 'path': depth_path}]
        if cid in sprites:
            _, start, end = sprites[cid]
            for code, ps, ln in A.sub_tags(body, start, end):
                if code not in (26, 70):
                    continue
                info = __import__('decode_create_ui').parse_place(
                    body, ps, ln, code == 70,
                    set(sprites) | set(shapes) | set(bitmaps) | set(edittexts))
                nxt = info.get('char')
                tr = (info.get('matrix') or {}).get('translate', [0.0, 0.0])
                nat = [round(at[0] + tr[0], 2), round(at[1] + tr[1], 2)]
                step = 'd%s:%s' % (info.get('depth'),
                                   link_of.get(nxt, '?') if nxt else '?')
                if nxt is None:
                    rows.append({'gap': 'imported ref %s' %
                                 info.get('name', info.get('notes', '?')),
                                 'at': nat, 'path': depth_path + [step]})
                else:
                    rows.extend(walk(nxt, nat, depth_path + [step],
                                     seen | {cid}))
            return rows
        return [{'gap': 'unknown cid %s' % cid, 'at': at, 'path': depth_path}]

    out = {}
    for target in A.TARGETS[module]:
        cid = named.get(target)
        if cid is None:
            out[target] = {'status': 'missing-linkage'}
            continue
        leaves = walk(cid, [0.0, 0.0], [target], set())
        out[target] = {'status': 'ok', 'cid': cid, 'leaves': leaves}
    return out


def main():
    """Resolve focus targets in all three HUD dumps."""
    report = {}
    for module, path in A.DUMPS.items():
        report[module] = resolve_module(module, path)
    out = os.path.join('output', 'hud-bitmap-map.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    for module, targets in report.items():
        for target, entry in targets.items():
            if target not in FOCUS:
                continue
            if entry['status'] != 'ok':
                print('%-24s %s' % (target, entry['status']))
                continue
            bits = sorted({l['bitmap'] for l in entry['leaves']
                           if 'bitmap' in l and isinstance(l['bitmap'], int)})
            gaps = [l['gap'] for l in entry['leaves'] if 'gap' in l]
            edits = [l['edittext'] for l in entry['leaves'] if 'edittext' in l]
            print('%-24s bitmaps=%s edits=%s gaps=%s'
                  % (target, bits, edits, gaps[:3]))
    print('wrote ' + out)


if __name__ == '__main__':
    main()

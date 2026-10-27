"""Dump full per-frame placements for focus HUD components (SWF-first).

audit_hud kept only depth/translate; this keeps the complete decoder
record per placement: flags, full matrix (scale/rotate/translate),
instance name, class name, ratio/cxform presence, and raw notes. Depth
order is preserved. Also reports tag census details the audit skipped
(morph shapes, sounds, DoABC strings) so mask/animation behavior has
evidence instead of guesses.

Usage (from the repo root):
  python scripts/asset_tools/dump_hud_frames.py
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swf_inventory as s  # noqa: E402
import audit_hud as A  # noqa: E402
from decode_create_ui import parse_place  # noqa: E402

FOCUS = ['ui.StateBar', 'ui.MiniMap', 'ui.panel.TaskTrack', 'ui.ChatSkin',
         'ui.ZDLView', 'ui.HpBar', 'ui.HeroBar', 'ui.panel.Target',
         'ui.panel.maiyao']


def placements(body, sprites, cid, link_of, kinds):
    """Full placement rows for every frame of one sprite, depth-ordered."""
    frames, start, end = sprites[cid]
    out = []
    frame = 1
    for code, ps, ln in A.sub_tags(body, start, end):
        if code == 1:
            frame += 1
            continue
        if code not in (26, 70):
            if code not in (0,):
                out.append({'frame': frame, 'tag': code,
                            'note': 'non-placement tag inside sprite'})
            continue
        info = parse_place(body, ps, ln, code == 70, set(kinds))
        row = {'frame': frame, 'tag': info.get('tag'),
               'flags': info.get('flags'), 'depth': info.get('depth')}
        ch = info.get('char')
        if ch is not None:
            row['child_cid'] = ch
            row['child'] = link_of.get(ch, '?')
            row['child_kind'] = kinds.get(ch, '?')
        if 'matrix' in info:
            row['matrix'] = info['matrix']
        for k in ('name', 'class_name', 'modify', 'trailing_hex'):
            if info.get(k) not in (None, ''):
                row[k] = info[k]
        # ratio (morph) / cxform / actions live past the matrix; the
        # decoder parks leftovers in notes — surface them explicitly.
        notes = info.get('notes') or []
        if notes:
            row['notes'] = notes
        out.append(row)
    return sorted(out, key=lambda r: (r['frame'], r.get('depth') or 0))


def extra_census(body):
    """Tag details the audit skipped: morphs, sounds, ABC, labels."""
    extra = {'morph': 0, 'sound': 0, 'abc_strings': [], 'frame_labels': []}
    for _, code, ps, ln in s.walk_tags(body):
        if code in (46,):
            extra['morph'] += 1
        elif code in (14,):
            extra['sound'] += 1
        elif code == 82:
            extra['abc_strings'].append(ln)
        elif code == 43:
            try:
                nul = body.index(b'\x00', ps, ps + ln)
                extra['frame_labels'].append(
                    body[ps:nul].decode('latin1'))
            except ValueError:
                pass
    return extra


def main():
    """Dump focus components with full placement detail."""
    report = {}
    for module, path in A.DUMPS.items():
        body, census, link_of, sprites, edittexts, shapes, bitmaps = \
            A.audit(path)
        kinds = {}
        kinds.update({c: 'sprite' for c in sprites})
        kinds.update({c: 'shape' for c in shapes})
        kinds.update({c: 'bitmap' for c in bitmaps})
        kinds.update({c: 'edittext' for c in edittexts})
        named = {name: cid for cid, name in link_of.items()}
        mod = {'extra': extra_census(body), 'targets': {}}
        for target in A.TARGETS[module]:
            if target not in FOCUS:
                continue
            cid = named.get(target)
            if cid is None or cid not in sprites:
                mod['targets'][target] = {'status': 'unexpanded'}
                continue
            rows = placements(body, sprites, cid, link_of, kinds)
            scaled = [r for r in rows
                      if (r.get('matrix') or {}).get('scale')]
            rotated = [r for r in rows
                       if (r.get('matrix') or {}).get('rotate')]
            mod['targets'][target] = {
                'status': 'ok', 'cid': cid,
                'frames': sprites[cid][0], 'placements': rows,
                'with_scale': len(scaled), 'with_rotate': len(rotated),
            }
        report[module] = mod
    out = os.path.join('output', 'hud-frames.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    for module, mod in report.items():
        print('====', module, mod['extra'])
        for target, entry in mod['targets'].items():
            if entry.get('status') != 'ok':
                print('  %-22s %s' % (target, entry['status']))
                continue
            n_import = sum(1 for r in entry['placements']
                           if r.get('child') == '?' or 'notes' in r)
            print('  %-22s frames=%d rows=%d scaled=%d rotated=%d noted=%d'
                  % (target, entry['frames'], len(entry['placements']),
                     entry['with_scale'], entry['with_rotate'], n_import))
    print('wrote ' + out)


if __name__ == '__main__':
    main()

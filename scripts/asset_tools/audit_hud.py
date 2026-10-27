"""Phase A HUD audit: structure of the gameui + hud-chat + shared-controls dumps.

Reads output/swf-memory/<dump>.swf, walks every tag, resolves SymbolClass
linkages, and expands each target HUD component's DefineSprite frames into
(depth, child linkage, matrix) placements plus EditText variables. Writes
output/hud-audit.json and prints a short human summary.

Usage (from the repo root):
  python scripts/asset_tools/audit_hud.py
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swf_inventory as s  # noqa: E402
from decode_create_ui import (  # noqa: E402
    matrix,
    parse_edittext,
    parse_place,
    parse_shape,
    rect,
)

DUMPS = {
    'gameui': 'output/swf-memory/mem-000010d40020-da6d57518e94.swf',
    'hud-chat': 'output/swf-memory/mem-000010dff020-61972ca56abd.swf',
    'shared-controls': 'output/swf-memory/mem-000006d52078-83c051d9be6e.swf',
}

TARGETS = {
    'gameui': ['ui.HeroBar', 'ui.HpBar', 'ui.BloodShape', 'ui.Gain',
               'ui.ListMenu', 'ui.caijiBar', 'ui.panel.maiyao',
               'ui.panel.NpcTalkPanel', 'ui.panel.TaskTalkPanel',
               'ui.panel.fuhuoPanel', 'ui.auto.GuajiIcon', 'ui.auto.XunluIcon'],
    'hud-chat': ['ui.StateBar', 'ui.MiniMap', 'ui.panel.TaskTrack',
                 'ui.TaskTrackItemRender', 'ui.ChatCombox', 'ui.ChatTabNavi',
                 'ui.ChatSkin', 'ui.ZDLView', 'ui.panel.Target',
                 'ui.Dazuo', 'ui.LoudSpeaker', 'ui.render.Statetip'],
    'shared-controls': ['tg.shared.ui.StateBar', 'shared.ui.PanelBg',
                        'tg.shared.cm.Button', 'tg.shared.cm.CloseButton',
                        'tg.shared.cm.ScrollBar', 'tg.shared.cm.ComboBox',
                        'tg.shared.cm.TabNavi', 'shared.ui.ToolTipBg'],
}


def sub_tags(body, start, end):
    """Yield (code, ps, ln) for tags in a sprite payload range."""
    pos = start
    while pos + 2 <= end:
        word = struct.unpack('<H', body[pos:pos + 2])[0]
        code, length = word >> 6, word & 0x3F
        pos += 2
        if length == 0x3F:
            length = struct.unpack('<I', body[pos:pos + 4])[0]
            pos += 4
        if pos + length > end:
            break
        yield code, pos, length
        pos += length
        if code == 0:
            break


def audit(dump_path):
    """Return census, char tables and expanded target sprites for one dump."""
    raw = open(dump_path, 'rb').read()
    _, _, body = s.normalize(raw)
    census = {}
    link_of = {}
    sprites = {}
    edittexts = {}
    shapes = {}
    bitmaps = set()
    known_cids = set()
    for _, code, ps, ln in s.walk_tags(body):
        census[code] = census.get(code, 0) + 1
        if code in (2, 22, 32):
            cid = struct.unpack('<H', body[ps:ps + 2])[0]
            known_cids.add(cid)
            shapes[cid] = (code, ps, ln)
        elif code in (6, 21, 35, 20, 36):
            cid = struct.unpack('<H', body[ps:ps + 2])[0]
            known_cids.add(cid)
            bitmaps.add(cid)
        elif code == 39:
            cid = struct.unpack('<H', body[ps:ps + 2])[0]
            known_cids.add(cid)
            frames = struct.unpack('<H', body[ps + 2:ps + 4])[0]
            sprites[cid] = (frames, ps + 4, ps + ln)
        elif code == 37:
            cid = struct.unpack('<H', body[ps:ps + 2])[0]
            known_cids.add(cid)
            edittexts[cid] = (ps, ln)
        elif code == 76:
            for cid, name in s.symbol_class(body, ps, ln):
                link_of[cid] = name
    return body, census, link_of, sprites, edittexts, shapes, bitmaps


def expand_sprite(body, cid, frames, start, end, link_of, known_cids,
                  kinds=None):
    """Expand sprite frames to placement rows."""
    out = []
    frame = 1
    for code, ps, ln in sub_tags(body, start, end):
        if code == 1:
            frame += 1
        elif code in (26, 70):
            info = parse_place(body, ps, ln, code == 70, known_cids)
            row = {'frame': frame, 'depth': info.get('depth')}
            if 'char' in info:
                row['child_cid'] = info['char']
                row['child'] = link_of.get(info['char'], '?')
                if kinds:
                    row['child_kind'] = kinds.get(info['char'], '?')
            if 'matrix' in info and isinstance(info['matrix'], dict):
                row['at'] = info['matrix'].get('translate')
            if info.get('name'):
                row['instance'] = info['name']
            out.append(row)
    return out


def main():
    """Audit the three HUD dumps and write output/hud-audit.json."""
    report = {'targets': {}, 'census': {}, 'notes': []}
    for module, path in DUMPS.items():
        body, census, link_of, sprites, edittexts, shapes, bitmaps = audit(path)
        kinds = {}
        kinds.update({c: 'sprite' for c in sprites})
        kinds.update({c: 'shape' for c in shapes})
        kinds.update({c: 'bitmap' for c in bitmaps})
        kinds.update({c: 'edittext' for c in edittexts})
        named = {name: cid for cid, name in link_of.items()}
        report['census'][module] = {
            'tags': sum(census.values()),
            'sprites': len(sprites),
            'shapes': len(shapes),
            'bitmaps': len(bitmaps),
            'edittexts': len(edittexts),
            'linkages': len(link_of),
        }
        for target in TARGETS[module]:
            cid = named.get(target)
            if cid is None:
                report['targets'][target] = {'status': 'missing-linkage'}
                continue
            entry = {'status': 'ok', 'module': module, 'cid': cid}
            if cid in sprites:
                frames, start, end = sprites[cid]
                entry['kind'] = 'sprite'
                entry['frames'] = frames
                entry['placements'] = expand_sprite(
                    body, cid, frames, start, end, link_of, set(sprites) | set(shapes) | set(bitmaps) | set(edittexts), kinds)
                kids = sorted({r.get('child', '?') for r in entry['placements']})
                entry['child_linkages'] = kids
                entry['child_kinds'] = sorted({r.get('child_kind', '?') for r in entry['placements']})
            elif cid in edittexts:
                ps, ln = edittexts[cid]
                entry['kind'] = 'edittext'
                entry['edit'] = parse_edittext(body, ps, ln)
            elif cid in shapes:
                code, ps, ln = shapes[cid]
                entry['kind'] = 'shape'
                try:
                    entry['shape'] = parse_shape(body, ps, ln, code, bitmaps)
                except Exception as exc:  # keep the audit going
                    entry['shape_error'] = str(exc)[:120]
            elif cid in bitmaps:
                entry['kind'] = 'bitmap'
            else:
                entry['kind'] = 'other'
            report['targets'][target] = entry
    out = os.path.join('output', 'hud-audit.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    for target, entry in report['targets'].items():
        if entry['status'] == 'missing-linkage':
            print('MISSING ' + target)
            continue
        extra = ''
        if entry.get('kind') == 'sprite':
            extra = ('frames=%d placements=%d children=%s'
                     % (entry['frames'], len(entry['placements']),
                        ','.join(entry['child_linkages'][:8])))
        print('%-28s %-8s cid=%-6s %s'
              % (target, entry.get('kind'), entry.get('cid'), extra))
    print('wrote ' + out)


if __name__ == '__main__':
    main()

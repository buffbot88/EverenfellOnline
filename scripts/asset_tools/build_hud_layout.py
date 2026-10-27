"""Build Phaser-ready HUD layout from decoder output (SWF-first).

Reads output/hud-bitmap-map.json + hud-chat/gameui manifests and writes
websites/everenfell/src/assets/hud-layout.json: per-component bitmap
leaves with accumulated Flash-px offsets, PNG paths and sizes. Vector-only
and imported leaves are recorded as gaps, not guessed.

Usage (from the repo root):
  python scripts/asset_tools/build_hud_layout.py
"""
import json
import os

MAP = json.load(open('output/hud-bitmap-map.json'))
LAYOUT = {'components': {}}
for module in ('gameui', 'hud-chat'):
    try:
        m = json.load(open('websites/everenfell/assets/ui/%s/manifest.json' % module))
    except FileNotFoundError:
        continue
    info = {r['character_id']: r for r in m['resources'] if r.get('status') == 'ok'}
    for target, entry in MAP.get(module, {}).items():
        if entry.get('status') != 'ok':
            continue
        comp = LAYOUT['components'].setdefault(
            target, {'module': module, 'cid': entry['cid'], 'art': [], 'gaps': []})
        for leaf in entry['leaves']:
            if 'bitmap' not in leaf or not isinstance(leaf['bitmap'], int):
                comp['gaps'].append(leaf.get('gap', leaf.get('edittext', '?')))
                continue
            bid = leaf['bitmap']
            res = info.get(bid)
            if not res:
                comp['gaps'].append('bitmap %d missing from %s export' % (bid, module))
                continue
            comp['art'].append({
                'bitmap': bid,
                'png': 'ui/%s/%s' % (module, res['png']),
                'w': res['width'], 'h': res['height'],
                'x': leaf['at'][0], 'y': leaf['at'][1],
                'path': leaf['path'],
            })

out = os.path.join('websites', 'everenfell', 'src', 'assets', 'hud-layout.json')
with open(out, 'w', encoding='utf-8') as fh:
    json.dump(LAYOUT, fh, ensure_ascii=False, indent=1)
for name, comp in LAYOUT['components'].items():
    print('%-24s art=%-3d gaps=%d' % (name, len(comp['art']), len(comp['gaps'])))
print('wrote ' + out)

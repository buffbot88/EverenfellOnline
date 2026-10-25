"""Export every bitmap resource of one recovered SWF to local PNG files.

Writes, under output/swf-export/<module>/:
  images/<cid>-<kind>.png   one PNG per decoded bitmap (straight alpha)
  manifest.json             module sha256, per-resource status, linkage names
  contact-sheet-NN.png      thumbnails for visual review
Failures are recorded in the manifest and never written as images.

Usage (from the repo root):
  python3 scripts/asset_tools/export_swf_bitmaps.py <recovered.swf> <module-name>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swf_inventory as s  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402

KIND = {6: 'jpeg', 21: 'jpeg2', 35: 'jpeg3', 20: 'lossless', 36: 'lossless2'}
THUMB = 96
COLS = 10
PER_SHEET = 100


def decode_one(body, code, ps, ln, tables):
    if code == 35:
        return s.decode_jpeg3(body, ps, ln)
    if code in (6, 21):
        return s.decode_jpeg(body, ps, ln, tables if tables else None)
    return s.decode_lossless(body, ps, ln, code)


def linkage_map(body):
    """Map character id to linkage names from SymbolClass (76)."""
    out = {}
    for _, code, ps, ln in s.walk_tags(body):
        if code == 76:
            for cid, name in s.symbol_class(body, ps, ln):
                out.setdefault(cid, []).append(name)
    return out


def contact_sheets(entries, out_dir):
    ok = [e for e in entries if e['status'] == 'ok']
    sheets = []
    for n, start in enumerate(range(0, len(ok), PER_SHEET)):
        chunk = ok[start:start + PER_SHEET]
        rows = (len(chunk) + COLS - 1) // COLS
        sheet = Image.new('RGB', (COLS * (THUMB + 8), rows * (THUMB + 18)), (24, 24, 24))
        draw = ImageDraw.Draw(sheet)
        for i, e in enumerate(chunk):
            x = (i % COLS) * (THUMB + 8) + 4
            y = (i // COLS) * (THUMB + 18) + 2
            im = Image.open(os.path.join(out_dir, e['png'])).convert('RGBA')
            im.thumbnail((THUMB, THUMB))
            bg = Image.new('RGBA', (THUMB, THUMB), (70, 70, 70, 255))
            bg.alpha_composite(im, ((THUMB - im.width) // 2, (THUMB - im.height) // 2))
            sheet.paste(bg.convert('RGB'), (x, y))
            draw.text((x, y + THUMB + 1), '%d' % e['character_id'], fill=(220, 220, 220))
        path = os.path.join(out_dir, 'contact-sheet-%02d.png' % (n + 1))
        sheet.save(path)
        sheets.append(os.path.basename(path))
    return sheets


def main(argv):
    if len(argv) != 2:
        raise SystemExit(__doc__)
    src, module = argv
    with open(src, 'rb') as fh:
        raw = fh.read()
    sig, version, body = s.normalize(raw)
    out_dir = os.path.join('output', 'swf-export', module)
    img_dir = os.path.join(out_dir, 'images')
    os.makedirs(img_dir, exist_ok=True)
    tables = None
    for _, code, ps, ln in s.walk_tags(body):
        if code == 8:
            tables = body[ps:ps + ln]
    links = linkage_map(body)
    entries = []
    for cid, code, ps, ln in s.bitmap_tags(body):
        rec = {'character_id': cid, 'tag': s.TAG_NAMES.get(code, code),
               'kind': KIND[code], 'linkage': links.get(cid, [])}
        try:
            im = decode_one(body, code, ps, ln, tables)
            name = '%d-%s.png' % (cid, KIND[code])
            path = os.path.join(img_dir, name)
            im.save(path)
            with Image.open(path) as chk:
                chk.verify()
            with Image.open(path) as chk:
                chk = chk.convert('RGBA')
                alpha = chk.getchannel('A').getextrema()
                rec.update({'status': 'ok', 'png': 'images/' + name,
                            'width': chk.width, 'height': chk.height,
                            'alpha_min': alpha[0], 'alpha_max': alpha[1]})
        except Exception as exc:  # recorded, never written as an image
            rec.update({'status': 'failed', 'error': '%s: %s' % (type(exc).__name__, exc)})
        entries.append(rec)
    sheets = contact_sheets(entries, out_dir)
    manifest = {
        'module': module,
        'source': os.path.relpath(src),
        'source_sha256': __import__('hashlib').sha256(raw).hexdigest(),
        'canonical_sha256': s.canonical_sha256(body),
        'swf_version': version,
        'counts': {
            'bitmap_tags': len(entries),
            'ok': sum(1 for e in entries if e['status'] == 'ok'),
            'failed': sum(1 for e in entries if e['status'] == 'failed'),
        },
        'contact_sheets': sheets,
        'resources': entries,
        'rights': 'unknown: legacy client art, local development only, not for publication',
    }
    with open(os.path.join(out_dir, 'manifest.json'), 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    print(json.dumps(manifest['counts']))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

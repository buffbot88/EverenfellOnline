"""Inventory and contact sheets for the verified Everenfell carved images.

Reads output/everenfell-asset-manifest.json (written by everenfell_assets.py)
and writes, locally under output/:
  everenfell-inventory.csv   one row per extracted image, source-grounded
  contact-sheets/<group>-NN.jpg  thumbnail sheets for visual review

Labels are limited to what the source supports: the container's resource
directory and file name. No role (character, monster, terrain) is inferred.
"""
import csv
import json
import os
import sys

from PIL import Image, ImageDraw

MANIFEST = os.path.join('output', 'everenfell-asset-manifest.json')
OUT_CSV = os.path.join('output', 'everenfell-inventory.csv')
SHEET_DIR = os.path.join('output', 'contact-sheets')
THUMB = 96
COLS = 10
PER_SHEET = 100

RIGHTS = ('unknown: legacy Binjiang-distribution client bytes; internal '
          'development only, never published')


def png_alpha(path):
    """Return the PNG colour type name and whether it carries alpha."""
    with open(path, 'rb') as fh:
        head = fh.read(33)
    if len(head) < 26 or head[12:16] != b'IHDR':
        return 'n/a', False
    colour_type = head[25]
    names = {0: 'gray', 2: 'rgb', 3: 'indexed', 4: 'gray+alpha', 6: 'rgba'}
    return names.get(colour_type, str(colour_type)), colour_type in (4, 6)


def group_of(source):
    """Resource directory under res/tw/r (e.g. n, ef, cj, m, o, em, zq, f)."""
    parts = source.split('/')
    return parts[parts.index('r') + 1] if 'r' in parts else parts[-2]


def build_rows(manifest):
    files = {f['path']: f for f in manifest['files']}
    rows = []
    for img in manifest['images']:
        src = img['source']
        f = files.get(src, {})
        container = f.get('container', {})
        alpha_name, alpha = ('n/a', False)
        if img['kind'] == 'png':
            alpha_name, alpha = png_alpha(img['extracted'])
        else:
            alpha_name = 'jpeg (no alpha)'
        rows.append({
            'extracted': img['extracted'],
            'sha256': img['sha256'],
            'format': img['kind'],
            'width': img['width'],
            'height': img['height'],
            'colour_type': alpha_name,
            'has_alpha': 'yes' if alpha else 'no',
            'resource_group': group_of(src),
            'source_file': src,
            'container_id': container.get('id', container.get('id_hex', '')),
            'container_size': f.get('size', ''),
            'container_sha256': f.get('sha256', ''),
            'payload_offset': img['offset'],
            'payload_length': img['length'],
            'verified': img['verified'],
            'rights': RIGHTS,
        })
    return rows


def write_csv(rows):
    fields = list(rows[0].keys())
    with open(OUT_CSV, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def contact_sheets(rows):
    os.makedirs(SHEET_DIR, exist_ok=True)
    by_group = {}
    for row in rows:
        by_group.setdefault(row['resource_group'], []).append(row)
    written = []
    for group, items in sorted(by_group.items()):
        items.sort(key=lambda r: r['extracted'])
        for sheet_no in range(0, len(items), PER_SHEET):
            chunk = items[sheet_no:sheet_no + PER_SHEET]
            rows_n = (len(chunk) + COLS - 1) // COLS
            sheet = Image.new('RGB', (COLS * (THUMB + 8), rows_n * (THUMB + 22)),
                              (24, 24, 24))
            draw = ImageDraw.Draw(sheet)
            for i, row in enumerate(chunk):
                x = (i % COLS) * (THUMB + 8) + 4
                y = (i // COLS) * (THUMB + 22) + 2
                try:
                    im = Image.open(row['extracted']).convert('RGBA')
                    im.thumbnail((THUMB, THUMB))
                    bg = Image.new('RGBA', (THUMB, THUMB), (60, 60, 60, 255))
                    bg.alpha_composite(im, ((THUMB - im.width) // 2,
                                            (THUMB - im.height) // 2))
                    sheet.paste(bg.convert('RGB'), (x, y))
                except (OSError, ValueError):
                    draw.rectangle([x, y, x + THUMB, y + THUMB], outline=(200, 0, 0))
                label = os.path.basename(row['extracted'])[-28:]
                draw.text((x, y + THUMB + 2), label, fill=(220, 220, 220))
            name = '%s-%02d.jpg' % (group, sheet_no // PER_SHEET + 1)
            dest = os.path.join(SHEET_DIR, name)
            sheet.save(dest, quality=85)
            written.append((dest, len(chunk)))
    return written


def main():
    with open(MANIFEST, encoding='utf-8') as fh:
        manifest = json.load(fh)
    rows = build_rows(manifest)
    write_csv(rows)
    sheets = contact_sheets(rows)
    groups = {}
    for row in rows:
        groups[row['resource_group']] = groups.get(row['resource_group'], 0) + 1
    print('rows=%d csv=%s sheets=%d' % (len(rows), OUT_CSV, len(sheets)))
    print('groups=%s' % json.dumps(dict(sorted(groups.items())), ensure_ascii=False))


if __name__ == '__main__':
    sys.exit(main())

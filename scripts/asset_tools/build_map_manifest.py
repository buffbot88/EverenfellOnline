"""Build the local browser manifest for legacy map 0 (凌霄殿外).

Reads map.json from the original client tree and the tile JPEGs next to it.
Each tile key is row*1000+col, validated by seam continuity (see the asset
ledger). Writes websites/everenfell/src/assets/map0.json with cell positions
and sha256s only. Tile bytes ship with the client under
websites/everenfell/public/maps/map0/ (copied from the original folder,
rights note in websites/everenfell/assets/README.md) and are referenced
by relative URLs that resolve identically in dev and production.
"""
import hashlib
import json
import os
import sys

from PIL import Image

MAP_DIR = os.path.join('MKO_Client', 'Assets', 'res', 'tw', 'r', 'm', '0')
OUT = os.path.join('websites', 'everenfell', 'src', 'assets', 'map0.json')
COLS = 17
ROWS = 24
CELL = 256


def sha256(path):
    with open(path, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    with open(os.path.join(MAP_DIR, 'map.json'), encoding='utf-8') as fh:
        meta = json.load(fh)
    if meta['mapwidth'] != COLS * CELL or meta['mapheight'] != ROWS * CELL:
        sys.exit('map size %sx%s does not match %dx%d grid of %d px cells'
                 % (meta['mapwidth'], meta['mapheight'], COLS, ROWS, CELL))
    tiles = []
    for row in range(ROWS):
        for col in range(COLS):
            key = '%06d' % (row * 1000 + col)
            name = key + '.jpg'
            path = os.path.join(MAP_DIR, name)
            if not os.path.isfile(path):
                sys.exit('missing tile %s' % name)
            with Image.open(path) as im:
                w, h = im.size
            tiles.append({
                'id': key,
                'row': row,
                'col': col,
                'x': col * CELL,
                'y': row * CELL,
                'width': w,
                'height': h,
                # Relative to the client page: public/maps/map0/ ships in
                # dist, so dev and production resolve the same URL.
                'url': 'maps/map0/' + name,
                'sha256': sha256(path),
            })
    doc = {
        'source': 'MKO_Client/Assets/res/tw/r/m/0/map.json',
        'name': meta.get('name'),
        'guid': meta.get('guid'),
        'mapwidth': meta['mapwidth'],
        'mapheight': meta['mapheight'],
        'cell': CELL,
        'cols': COLS,
        'rows': ROWS,
        'rights': 'unknown legacy client bytes: development only, not for deployment',
        'tiles': tiles,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print('tiles=%d out=%s' % (len(tiles), OUT))


if __name__ == '__main__':
    main()

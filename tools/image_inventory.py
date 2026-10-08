#!/usr/bin/env python3
"""Triage loose game images for text-localization work.

Walks res/f + res/global (+ any dirs given), records dimensions/size, and
flags likely-text images by name heuristics (button/banner/logo/title UI
art usually carries baked Chinese). Icon/photo-like files sort low.

Usage: python3 tools/image_inventory.py <resdir>... -o .survey/images.json

Output JSON: [{path, w, h, kb, kind, text_likely, reason}]
`text_likely` is a triage hint, NOT OCR — confirm candidates visually (or
run an OCR pass) before redrawing. SWF-baked bitmaps inside the encrypted
asset packs are out of scope until the pack cipher is solved; see docs.
"""
import json
import os
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit('need Pillow: pip install Pillow')

TEXT_HINTS = ('btn', 'button', 'banner', 'logo', 'title', 'tip', 'notice',
              'board', 'panel', 'dialog', 'txt', 'word', 'font', 'announce',
              'huodong', 'gonggao', 'denglu', 'zhuce', 'kefu')
PHOTO_HINTS = ('icon', 'head', 'face', 'map', 'scene', 'bg', 'photo',
               '37wan', 'item', 'equip', 'skill', 'pet', 'mount')


def classify(name, w, h):
    n = name.lower()
    for hint in TEXT_HINTS:
        if hint in n:
            return True, f'name:{hint}'
    for hint in PHOTO_HINTS:
        if hint in n:
            return False, f'name:{hint}'
    # Wide-short strips and mid-size panels are often text art.
    if w >= 200 and h <= 80:
        return True, 'shape:wide-strip'
    if 150 <= w <= 800 and 60 <= h <= 400:
        return True, 'shape:panel?'
    if w <= 64 and h <= 64:
        return False, 'shape:small-icon'
    return None, 'shape:unknown'


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    out = '.survey/images.json'
    if '-o' in sys.argv:
        out = sys.argv[sys.argv.index('-o') + 1]
    rows = []
    for root in args:
        for dp, _, fns in os.walk(root):
            for fn in sorted(fns):
                if not fn.endswith(('.png', '.jpg', '.jpeg', '.gif')):
                    continue
                p = os.path.join(dp, fn)
                try:
                    with Image.open(p) as im:
                        w, h = im.size
                    kb = os.path.getsize(p) // 1024
                except Exception as e:
                    rows.append({'path': p, 'error': str(e)})
                    continue
                likely, reason = classify(fn, w, h)
                rows.append({'path': os.path.relpath(p), 'w': w, 'h': h,
                             'kb': kb, 'text_likely': likely, 'reason': reason})
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    yes = sum(1 for r in rows if r.get('text_likely') is True)
    maybe = sum(1 for r in rows if r.get('text_likely') is None)
    print(f'images: {len(rows)}  likely-text: {yes}  review: {maybe}')
    print(f'wrote {out}')


if __name__ == '__main__':
    main()

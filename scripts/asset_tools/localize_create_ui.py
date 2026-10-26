"""Localize create-ui text bitmaps: Chinese -> draft English, same sizes/IDs.

Overwrites the PNGs in place (all 24 are git-tracked, so `git checkout`
restores the originals). Layout JSON and Phaser scenes are untouched:
filenames and dimensions never change.

Technique per asset: fresh black canvas for flat text plates (titles,
label); keep-art + erase-glyphs + redraw for composite art (ribbons keep
their icons, stamp keeps its border, start keeps its frame, badge keeps
its emblem). Glyph erasure = brightness mask + iterative neighbor
inpaint, which suits these smooth gradients.
"""

import io
import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = os.path.join('websites', 'everenfell', 'assets', 'ui', 'create-ui',
                    'images')
FONTS = 'C:/Windows/Fonts'


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)


def orig(path):
    """Load the committed original (reruns stay safe after overwrites)."""
    rel = os.path.join(BASE, path).replace(os.sep, '/')
    blob = subprocess.run(['git', 'show', 'HEAD:' + rel],
                            capture_output=True, check=True).stdout
    return Image.open(io.BytesIO(blob)).convert('RGBA')


def dilate(mask, size=5):
    return np.array(
        Image.fromarray(mask).filter(ImageFilter.MaxFilter(size)))


def fit_font(name, text, max_w, max_h, start=40):
    for size in range(start, 7, -1):
        f = font(name, size)
        box = f.getbbox(text)
        if box[2] - box[0] <= max_w and box[3] - box[1] <= max_h:
            return f, size
    return font(name, 8), 8


def gradient_text(text, fnt, top, bottom, glow=None, glow_r=0, outline=None,
                  outline_w=0):
    """RGBA image of text with vertical gradient fill, optional glow."""
    box = fnt.getbbox(text)
    w, h = box[2] - box[0] + glow_r * 4 + outline_w * 2 + 4, \
        box[3] - box[1] + glow_r * 4 + outline_w * 2 + 4
    ox, oy = (w - (box[2] - box[0])) // 2 - box[0], \
        (h - (box[3] - box[1])) // 2 - box[1]
    mask = Image.new('L', (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.text((ox, oy), text, font=fnt, fill=255)
    grad = np.zeros((h, w, 3), np.uint8)
    t = np.array(top, np.float32)
    b = np.array(bottom, np.float32)
    for y in range(h):
        grad[y, :] = (t + (b - t) * y / max(h - 1, 1)).astype(np.uint8)
    grad_img = Image.fromarray(grad)
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    if glow and glow_r:
        blurred = mask.filter(ImageFilter.GaussianBlur(glow_r))
        glow_layer = Image.new('RGBA', (w, h), glow + (0,))
        glow_layer.putalpha(blurred)
        out = Image.alpha_composite(out, glow_layer)
    if outline and outline_w:
        edge = mask.filter(ImageFilter.MaxFilter(outline_w * 2 + 1))
        edge_layer = Image.new('RGBA', (w, h), outline + (0,))
        edge_layer.putalpha(edge)
        out = Image.alpha_composite(out, edge_layer)
    out.paste(grad_img, (0, 0), mask)
    return out


def inpaint(arr, mask, iters=400):
    """Fill masked pixels from known 4-neighbors, iteratively."""
    img = arr.astype(np.float32)
    known = ~mask
    for _ in range(iters):
        if not mask.any():
            break
        filled = np.zeros_like(mask, bool)
        acc = np.zeros_like(img)
        cnt = np.zeros(mask.shape + (1,), np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            src_known = np.roll(known, (-dy, -dx), axis=(0, 1))
            acc += np.roll(img, (-dy, -dx), axis=(0, 1)) * \
                src_known[..., None]
            cnt += src_known[..., None]
        grow = mask & (cnt[..., 0] > 0)
        img[grow] = acc[grow] / cnt[grow]
        known |= grow
        filled |= grow
        mask = mask & ~filled
    return np.clip(img, 0, 255).astype(np.uint8)


def plate(path, text, fnt_name, top, bottom, glow, max_h_frac=0.8):
    # Fresh art on a transparent canvas: originals are borderless
    # glowing text (corners fully transparent).
    w, h = orig(path).size
    fnt, _ = fit_font(fnt_name, text, w - 8, int(h * max_h_frac))
    t = gradient_text(text, fnt, top, bottom, glow, 2)
    canvas = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    canvas.alpha_composite(t, ((w - t.width) // 2, (h - t.height) // 2))
    canvas.save(os.path.join(BASE, path))
    print('plate %-18s %r' % (path, text))


GEO = 'georgiab.ttf'
ARI = 'arialbd.ttf'

# 1-2. Title strips: fresh plates, silver gradient, soft glow.
plate('14-lossless2.png', 'CREATE', GEO, (235, 235, 240), (130, 130, 140),
      (255, 255, 255))
plate('61-lossless2.png', 'SELECT', GEO, (235, 235, 240), (130, 130, 140),
      (255, 255, 255))

# 3. Name label: fresh plate, embossed grey.
plate('40-lossless2.png', 'NAME', ARI, (245, 245, 245), (150, 150, 155),
      (255, 255, 255))

# 4. Class ribbons: keep icon columns, redraw name with class tint.
RIBBONS = {
    '35-jpeg3.png': ('Spirit Monkey', (255, 215, 120)),
    '21-jpeg3.png': ('Nine Tails', (170, 255, 180)),
    '28-jpeg3.png': ('Bull Demon', (255, 120, 120)),
    '5-jpeg3.png': ('Rakshasa', (215, 150, 255)),
}
for path, (name, tint) in RIBBONS.items():
    img = orig(path)
    img_alpha = img.getchannel('A')
    arr = np.array(img.convert('RGB')).astype(np.int16)
    if path == '21-jpeg3.png':
        # Icon art includes a baked glyph right of the dagger: erase the
        # glyph zone first so the split search sees the true icon edge.
        zone = np.zeros(arr.shape[:2], bool)
        zone[:, 30:62] = True
        gm = zone & (arr.sum(axis=2) > 110)
        gm = dilate(gm, 5)
        arr = inpaint(arr.astype(np.uint8), gm,
                      iters=300).astype(np.int16)
        img = Image.fromarray(arr.astype(np.uint8))
        img.putalpha(img_alpha)
    bright = arr.sum(axis=2)
    cols = (bright > 120).any(axis=0)
    w, h = img.size
    lo, hi = int(w * 0.25), int(w * 0.60)
    split = lo + int(np.argmin(cols[lo:hi].astype(np.int8) * 10 +
                               np.arange(hi - lo) * 0))
    arr[:, split:, :] = 0
    # Alpha-aware: original icon keeps its own alpha, text zone is
    # cleared to transparent, new text composites with its own glow.
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    out.alpha_composite(img.crop((0, 0, split, h)), (0, 0))
    fnt, _ = fit_font(GEO, name, w - split - 8, int(h * 0.62), start=30)
    t = gradient_text(name, fnt, (255, 255, 255),
                      tuple(int(c * 0.55) for c in tint), tint, 3)
    y = (h - t.height) // 2
    layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    layer.alpha_composite(t, (split + 2, y))
    out = Image.alpha_composite(out, layer)
    out.save(os.path.join(BASE, path))
    print('ribbon %-16s %r (icon split x=%d)' % (path, name, split))

# 5. Selection stamp: keep fiery border, erase glyphs, redraw tilted.
# Two page-specific words share the 選定 border art: 'Creation' on the
# create screen, 'SELECTION' on the select screen. The stamp follows the
# selected slot at runtime (scene code), so both variants are needed.
for out_name, word in (('50-jpeg3.png', 'Creation'),
                       ('50b-selection.png', 'SELECTION')):
    img = orig('50-jpeg3.png')
    alpha = img.getchannel('A')
    arr = np.array(img.convert('RGB'))
    r, g, b = arr[..., 0].astype(int), arr[..., 1].astype(int), \
        arr[..., 2].astype(int)
    interior = np.zeros(arr.shape[:2], bool)
    interior[22:70, 28:104] = True
    mask = interior & (r > 100) & (g > 45) & (r > b + 20)
    mask = dilate(mask, 5)
    ys, xs = np.nonzero(mask)
    cy, cx = int(ys.mean()), int(xs.mean())
    fixed = inpaint(arr, mask, iters=600)
    base = Image.fromarray(fixed)
    fnt, _ = fit_font(GEO, word, 100, 30, start=34)
    t = gradient_text(word, fnt, (255, 225, 130), (255, 130, 30),
                      (255, 120, 20), 3)
    t = t.rotate(15, expand=True, resample=Image.BICUBIC)
    layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
    layer.alpha_composite(t, (cx - t.width // 2, cy - t.height // 2))
    res = Image.alpha_composite(base.convert('RGBA'), layer)
    res.putalpha(alpha)
    res.save(os.path.join(BASE, out_name))
    print('stamp %-17s %r at (%d,%d)' % (out_name, word, cx, cy))

# 6. Start button: keep frame, row-median fill, redraw gold text.
p = '53-jpeg3.png'
img = orig(p)
alpha = img.getchannel('A')
arr = np.array(img.convert('RGB'))
r, g, b = arr[..., 0].astype(int), arr[..., 1].astype(int), \
    arr[..., 2].astype(int)
roi = np.zeros(arr.shape[:2], bool)
roi[8:-8, 20:205] = True
mask = roi & (r > 95) & (g > 60) & (r > b)
mask = dilate(mask, 5)
fixed = arr.copy()
for y in range(arr.shape[0]):
    row_m = mask[y]
    if row_m.any():
        unm = ~row_m
        if unm.any():
            med = np.median(arr[y][unm], axis=0)
            fixed[y][row_m] = med
base = Image.fromarray(fixed)
fnt, _ = fit_font(GEO, 'START GAME', 160, 34, start=40)
t = gradient_text('START GAME', fnt, (245, 220, 170), (170, 120, 60),
                  (255, 200, 100), 2, outline=(70, 30, 15), outline_w=1)
layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
layer.alpha_composite(t, ((base.width - t.width) // 2,
                           (base.height - t.height) // 2))
res = Image.alpha_composite(base.convert('RGBA'), layer)
res.putalpha(alpha)
res.save(os.path.join(BASE, p))
print('button %-16s %r' % (p, 'START GAME'))

# 7. Empty-slot badge: keep emblem, erase center glyphs, redraw.
p = '63-jpeg3.png'
img = orig(p)
alpha = img.getchannel('A')
arr = np.array(img.convert('RGB'))
r, g, b = arr[..., 0].astype(int), arr[..., 1].astype(int), \
    arr[..., 2].astype(int)
roi = np.zeros(arr.shape[:2], bool)
roi[55:120, 25:150] = True
mask = roi & (g > 120) & (r > 80) & (b < 120)
ys, xs = np.nonzero(mask)
cy, cx = int(ys.mean()), int(xs.mean())
fixed = inpaint(arr, mask, iters=600)
base = Image.fromarray(fixed)
fnt, _ = fit_font(GEO, 'CREATE', 120, 30, start=36)
t = gradient_text('CREATE', fnt, (220, 255, 150), (150, 200, 80),
                  (200, 255, 150), 2, outline=(20, 30, 10), outline_w=1)
layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
layer.alpha_composite(t, (cx - t.width // 2, cy - t.height // 2))
res = Image.alpha_composite(base.convert('RGBA'), layer)
res.putalpha(alpha)
res.save(os.path.join(BASE, p))
print('badge %-17s %r at (%d,%d)' % (p, 'CREATE', cx, cy))

print('done: 11 bitmaps rewritten, 55/57 untouched (state role unverified)')

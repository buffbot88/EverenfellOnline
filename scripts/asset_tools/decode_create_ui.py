"""Decode the create-ui SWF module structure into a reviewable layout JSON.

Reads output/swf-memory/mem-000006eeae18-1c3192dd9965.swf (FWS v10) and
emits websites/everenfell/src/assets/create-ui-layout.json with:
  SymbolClass linkage, shape bounds (authored coords, px), DefineEditText
  geometry + variable/initial text, sprite placement trees (depth, char,
  matrix translate, instance name), DoABC handler names.

PlaceObject flag note: this module's encoder sets HasCharacter=0x04,
a 1-byte identity matrix under 0x02, and an instance name under 0x20
(verified byte-by-byte against tag lengths: 0x26 = char+matrix+name,
0x06 = char+matrix, 0x24 = name-only modify). Every parse is
end-aligned against the known tag length; mismatches are flagged, not
silently accepted.

Usage (repo root): python3 scripts/asset_tools/decode_create_ui.py
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from swf_inventory import normalize, walk_tags

SRC = os.path.join('output', 'swf-memory',
                   'mem-000006eeae18-1c3192dd9965.swf')
DEST = os.path.join('websites', 'everenfell', 'src', 'assets',
                    'create-ui-layout.json')

PO_CHAR = 0x04
PO_MATRIX = 0x02
PO_NAME = 0x20


class Bits:
    """MSB-first bit reader over a bytes-like window."""

    def __init__(self, buf, pos):
        self.buf = buf
        self.pos = pos
        self.bit = 0
        self.cur = 0

    def ub(self, n):
        v = 0
        for _ in range(n):
            if self.bit == 0:
                self.cur = self.buf[self.pos]
                self.pos += 1
                self.bit = 8
            self.bit -= 1
            v = (v << 1) | ((self.cur >> self.bit) & 1)
        return v

    def sb(self, n):
        v = self.ub(n)
        return v - (1 << n) if n and v & (1 << (n - 1)) else v

    def align(self):
        # Drop padding bits of the current byte; pos already advanced
        # past it. Byte fields always start on a byte boundary.
        self.bit = 0


def rect(buf, pos):
    """Parse a RECT; return ((xmin, xmax, ymin, ymax) in px, end pos)."""
    b = Bits(buf, pos)
    n = b.ub(5)
    vals = [b.sb(n) / 20.0 for _ in range(4)]
    b.align()
    return vals, b.pos


def matrix(buf, pos):
    """Parse a MATRIX; return (dict, end pos)."""
    b = Bits(buf, pos)
    out = {}
    if b.ub(1):
        n = b.ub(5)
        out['scale'] = [b.sb(n) / 65536.0, b.sb(n) / 65536.0]
    if b.ub(1):
        n = b.ub(5)
        out['rotate'] = [b.sb(n) / 65536.0, b.sb(n) / 65536.0]
    n = b.ub(5)
    out['translate'] = [b.sb(n) / 20.0, b.sb(n) / 20.0]
    b.align()
    return out, b.pos


def cstring(buf, pos, end):
    """Read a NUL-terminated latin1 string; return (str, end pos)."""
    nul = buf.index(b'\x00', pos, end)
    return buf[pos:nul].decode('latin1'), nul + 1


def parse_place(body, ps, ln, is_v3, known_cids):
    """Parse PlaceObject2/3; return dict (never throws).

    A set character id must be defined in this module; anything else
    is an imported reference (lib.swf) recorded as a name path.
    """
    notes = []
    end = ps + ln
    info = {'tag': 70 if is_v3 else 26}
    try:
        flags = body[ps]
        pos = ps + 1
        info['flags'] = '0x%02x' % flags
        if is_v3:
            info['ext_flags'] = '0x%02x' % body[pos]
            pos += 1
        info['depth'] = struct.unpack('<H', body[pos:pos + 2])[0]
        pos += 2
        has_char = bool(flags & PO_CHAR)
        if has_char:
            cid = struct.unpack('<H', body[pos:pos + 2])[0]
            if cid in known_cids:
                info['char'] = cid
                pos += 2
            else:
                notes.append('char bit set but id %d not defined here '
                             '(imported?)' % cid)
                has_char = False
        if flags & PO_MATRIX and has_char:
            info['matrix'], pos = matrix(body, pos)
        elif flags & PO_MATRIX:
            # No character: a frame-2/3 modify record (color transform
            # on the depth), not a placement. Record raw, not as coords.
            info['modify'] = body[pos:pos + 8].hex()
            notes.append('modify record, not a placement')
            return info
        if flags & PO_NAME:
            info['name'], pos = cstring(body, pos, end)
        elif pos < end and end - pos == 1 and body[pos] == 0:
            info['name'] = ''
            pos += 1
            notes.append('empty name without flag (encoder quirk)')
        if pos < end:
            try:
                cls, pos2 = cstring(body, pos, end)
                if cls and all(32 <= ord(c) < 127 for c in cls):
                    info['class_name'] = cls
                    pos = pos2
            except ValueError:
                pass
        if pos != end:
            notes.append('trailing %d bytes' % (end - pos))
            info['trailing_hex'] = body[pos:end].hex()[:64]
    except Exception as exc:  # keep the tag visible, never abort the run
        notes.append('parse error: %s' % exc)
    info['notes'] = notes
    return info


def parse_shape(body, ps, ln, code, known_bitmaps=()):
    """Bounds plus bitmap-fill references of a DefineShape."""
    cid = struct.unpack('<H', body[ps:ps + 2])[0]
    bounds, pos = rect(body, ps + 2)
    entry = {'cid': cid, 'tag': code,
             'bounds_px': [round(v, 1) for v in bounds],
             'bitmap_fills': []}
    # NOTE: ShapeEdgeBounds exists only in DefineShape4 (tag 83),
    # which this module does not use. DefineShape2/3 follow
    # ShapeBounds directly with the fill styles.
    try:
        b = Bits(body, pos)
        nfill = b.ub(8)
        if nfill == 0xFF:
            nfill = struct.unpack('<H', body[b.pos:b.pos + 2])[0]
            b.pos += 2
        for _ in range(nfill):
            kind = b.ub(8)
            if kind == 0x00:
                b.pos += 3 + (1 if code == 32 else 0)
            elif kind in (0x40, 0x41, 0x42, 0x43):
                bid = struct.unpack('<H', body[b.pos:b.pos + 2])[0]
                b.pos += 2
                if b.ub(1):
                    n = b.ub(5)
                    b.sb(n)
                    b.sb(n)
                if b.ub(1):
                    n = b.ub(5)
                    b.sb(n)
                    b.sb(n)
                n = b.ub(5)
                tx = b.sb(n) / 20.0
                ty = b.sb(n) / 20.0
                b.align()
                if bid in known_bitmaps:
                    entry['bitmap_fills'].append(
                        {'bitmap': bid, 'tx_px': round(tx, 1),
                         'ty_px': round(ty, 1)})
                else:
                    entry.setdefault('notes', []).append(
                        'fill refs undefined bitmap %d (ignored)' % bid)
            elif kind in (0x10, 0x12, 0x13):
                # GradientMatrix MATRIX first, then spread/interp/count
                # and per-stop ratio+color records (gradient panels
                # behind the class portraits use this).
                if b.ub(1):
                    n = b.ub(5)
                    b.sb(n)
                    b.sb(n)
                if b.ub(1):
                    n = b.ub(5)
                    b.sb(n)
                    b.sb(n)
                n = b.ub(5)
                b.sb(n)
                b.sb(n)
                b.align()
                b.ub(2)
                b.ub(2)
                ngrad = b.ub(4)
                entry.setdefault('gradients', []).append(ngrad)
                for _ in range(ngrad):
                    b.ub(8)
                    for _ in range(3 + (1 if code == 32 else 0)):
                        b.ub(8)
                if kind == 0x13:
                    b.ub(16)
            else:
                entry.setdefault('notes', []).append(
                    'unknown fill 0x%02x' % kind)
                break
    except Exception as exc:
        entry.setdefault('notes', []).append('fill parse: %s' % exc)
    return entry


def parse_edittext(body, ps, ln):
    """Geometry, variable name and initial text of a DefineEditText."""
    cid = struct.unpack('<H', body[ps:ps + 2])[0]
    bounds, pos = rect(body, ps + 2)
    end = ps + ln
    f1, f2 = body[pos], body[pos + 1]
    pos += 2
    has_text = (f1 >> 7) & 1
    has_textcolor = (f1 >> 2) & 1
    has_maxlength = (f1 >> 1) & 1
    has_font = f1 & 1
    has_fontclass = (f2 >> 7) & 1
    has_layout = (f2 >> 5) & 1
    entry = {'cid': cid, 'bounds_px': [round(v, 1) for v in bounds],
             'flags': ['0x%02x' % f1, '0x%02x' % f2]}
    if has_font:
        pos += 2
    if has_fontclass:
        pos += 1
    if has_font:
        entry['font_height_px'] = round(
            struct.unpack('<H', body[pos:pos + 2])[0] / 20.0, 1)
        pos += 2
    if has_textcolor:
        entry['color'] = list(body[pos:pos + 4])
        pos += 4
    if has_maxlength:
        pos += 2
    if has_layout:
        pos += 1 + 2 * 4
    entry['variable'], pos = cstring(body, pos, end)
    if has_text:
        try:
            raw_text, pos = cstring(body, pos, end)
            try:
                entry['initial_text'] = raw_text.encode(
                    'latin1').decode('utf-8')
            except UnicodeError:
                entry['initial_text'] = raw_text
        except ValueError:
            entry['initial_text'] = ''
    else:
        entry['initial_text'] = ''
    if pos != end:
        entry['trailing_bytes'] = end - pos
    return entry


def parse_symbolclass(body, ps, ln):
    end = ps + ln
    count = struct.unpack('<H', body[ps:ps + 2])[0]
    pos = ps + 2
    out = []
    for _ in range(count):
        cid = struct.unpack('<H', body[pos:pos + 2])[0]
        pos += 2
        name, pos = cstring(body, pos, end)
        out.append({'cid': cid, 'name': name})
    return out


def main():
    with open(SRC, 'rb') as fh:
        raw = fh.read()
    _, _, body = normalize(raw)
    doc = {'source': os.path.basename(SRC), 'shapes': [], 'edittexts': [],
           'sprites': [], 'symbolclass': [], 'abc_strings': []}
    known_cids = set()
    known_bitmaps = set()
    for _off, code, ps, ln in walk_tags(body):
        if code in (2, 22, 32, 6, 21, 35, 20, 36, 39, 37, 48, 75):
            known_cids.add(struct.unpack('<H', body[ps:ps + 2])[0])
        if code in (6, 21, 35, 20, 36):
            known_bitmaps.add(struct.unpack('<H', body[ps:ps + 2])[0])
    for _off, code, ps, ln in walk_tags(body):
        if code in (2, 22, 32):
            doc['shapes'].append(
                parse_shape(body, ps, ln, code, known_bitmaps))
        elif code == 37:
            doc['edittexts'].append(parse_edittext(body, ps, ln))
        elif code == 76:
            doc['symbolclass'] = parse_symbolclass(body, ps, ln)
        elif code == 82:
            blob = body[ps:ps + ln]
            doc['abc_strings'] = sorted({
                m.decode() for m in __import__('re').findall(
                    rb'[A-Za-z_][\w$:.]{3,}', blob)})
        elif code == 39:
            cid = struct.unpack('<H', body[ps:ps + 2])[0]
            frames = struct.unpack('<H', body[ps + 2:ps + 4])[0]
            frames_out = []
            cur = []
            pos, end = ps + 4, ps + ln
            while pos < end:
                word = struct.unpack('<H', body[pos:pos + 2])[0]
                tcode, tlen = word >> 6, word & 0x3F
                hlen = 2
                if tlen == 0x3F:
                    tlen = struct.unpack('<I', body[pos + 2:pos + 6])[0]
                    hlen = 6
                if tcode in (26, 70):
                    cur.append(parse_place(body, pos + hlen, tlen,
                                           tcode == 70, known_cids))
                elif tcode == 1:
                    frames_out.append(cur)
                    cur = []
                pos += hlen + tlen
                if tcode == 0:
                    break
            doc['sprites'].append({'cid': cid, 'frames': frames_out})
    doc['sprites'].sort(key=lambda s: s['cid'])
    doc['shapes'].sort(key=lambda s: s['cid'])
    doc['edittexts'].sort(key=lambda s: s['cid'])
    with open(DEST, 'w') as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    problems = sum(1 for s in doc['sprites'] for f in s['frames']
                   for p in f if p.get('notes'))
    print('wrote %s (%d sprites, %d shapes, %d edittexts, %d notes)'
          % (DEST, len(doc['sprites']), len(doc['shapes']),
             len(doc['edittexts']), problems))


if __name__ == '__main__':
    main()

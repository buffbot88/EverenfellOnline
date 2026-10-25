"""SWF inventory: normalize, validate and walk the tags of a Flash module.

Pure stdlib plus Pillow for bitmap encoding. Reads FWS/CWS/ZWS input and
never writes to the source file. Canonical hashes are taken over the
decompressed body, so the same module in FWS and CWS form dedups to one id.

Usage (from the repo root):
  python3 scripts/asset_tools/swf_inventory.py <swf> --out output/<name>
"""
import hashlib
import json
import os
import re
import struct
import sys
import zlib

MAX_LEN = 64 * 1024 * 1024


class SwfError(ValueError):
    pass


def normalize(raw):
    """Return (signature, version, fws_bytes). Validates the declared length."""
    sig = raw[:3]
    if len(raw) < 8:
        raise SwfError('too short')
    version = raw[3]
    declared = struct.unpack('<I', raw[4:8])[0]
    if sig == b'FWS':
        body = raw
    elif sig == b'CWS':
        try:
            body = b'FWS' + raw[3:8] + zlib.decompress(raw[8:])
        except zlib.error as exc:
            raise SwfError('zlib: %s' % exc)
    else:
        raise SwfError('unsupported signature %r (ZWS/packed not handled)' % sig)
    if struct.unpack('<I', body[4:8])[0] != len(body):
        raise SwfError('declared length %d != decoded length %d'
                       % (struct.unpack('<I', body[4:8])[0], len(body)))
    if not (1 <= version <= 60) or len(body) > MAX_LEN:
        raise SwfError('implausible version or size')
    return sig.decode('ascii'), version, body


def canonical_sha256(fws_body):
    """Hash of the decompressed body with the header's compression byte cleared."""
    return hashlib.sha256(b'FWS' + fws_body[3:]).hexdigest()


def frame_start(body):
    """Offset of the first tag: RECT (variable bits) + frame rate + frame count."""
    nbits = body[8] >> 3
    rect_bytes = (5 + 4 * nbits + 7) // 8
    return 8 + rect_bytes + 4


def walk_tags(body):
    """Yield (offset, code, payload_start, payload_len) for every tag.

    Raises SwfError when a tag runs past the end or no End tag is reached.
    """
    pos = frame_start(body)
    while True:
        if pos + 2 > len(body):
            raise SwfError('tag header past end at %d' % pos)
        start = pos
        word = struct.unpack('<H', body[pos:pos + 2])[0]
        code, length = word >> 6, word & 0x3F
        pos += 2
        if length == 0x3F:
            if pos + 4 > len(body):
                raise SwfError('long length past end at %d' % start)
            length = struct.unpack('<I', body[pos:pos + 4])[0]
            pos += 4
        if pos + length > len(body):
            raise SwfError('tag %d at %d overruns (len %d)' % (code, start, length))
        yield start, code, pos, length
        pos += length
        if code == 0:
            break
    if pos != len(body):
        raise SwfError('trailing bytes after End tag: %d' % (len(body) - pos))


TAG_NAMES = {
    0: 'End', 1: 'ShowFrame', 2: 'DefineShape', 4: 'PlaceObject',
    5: 'RemoveObject', 6: 'DefineBits', 8: 'JPEGTables', 9: 'SetBackgroundColor',
    11: 'DefineText', 13: 'DefineFontInfo', 20: 'DefineBitsLossless',
    21: 'DefineBitsJPEG2', 22: 'DefineShape2', 26: 'PlaceObject2',
    32: 'DefineShape3', 33: 'DefineText2', 35: 'DefineBitsJPEG3',
    36: 'DefineBitsLossless2', 37: 'DefineEditText', 39: 'DefineSprite',
    46: 'DefineMorphShape', 48: 'DefineFont2', 56: 'ExportAssets',
    57: 'ImportAssets', 59: 'DoInitAction', 70: 'PlaceObject3',
    75: 'DefineFont3', 76: 'SymbolClass', 82: 'DoABC', 88: 'DefineFontName',
}


def decode_lossless(body, ps, ln, code):
    """Decode DefineBitsLossless (20) / Lossless2 (36) to an RGBA PIL image."""
    from PIL import Image
    fmt = body[ps + 2]
    width = struct.unpack('<H', body[ps + 3:ps + 5])[0]
    height = struct.unpack('<H', body[ps + 5:ps + 7])[0]
    if fmt not in (3, 4, 5):
        raise SwfError('unsupported lossless format %d' % fmt)
    try:
        data = zlib.decompress(body[ps + 7:ps + ln])
    except zlib.error as exc:
        raise SwfError('lossless zlib: %s' % exc)
    return _lossless_image(fmt, width, height, data, code)


def _lossless_image(fmt, width, height, data, code):
    """Build the RGBA image from already-inflated pixel data (formats 3, 4 and 5)."""
    from PIL import Image
    if fmt == 5:
        row = width * 4
        out = bytearray()
        for y in range(height):
            out += data[y * row:y * row + width * 4]
        im = Image.frombuffer('RGBA', (width, height), bytes(out), 'raw', 'BGRA', 0, 1)
        if code == 36:
            im = _unpremultiply(im)
        return im
    if fmt == 3:
        ncolors = data[0] + 1
        table_len = ncolors * (4 if code == 36 else 3)
        table = data[1:1 + table_len]
        pixels = data[1 + table_len:]
        stride = (width + 3) & ~3
        palette = []
        for i in range(ncolors):
            r, g, b = table[i * (4 if code == 36 else 3)], table[i * (4 if code == 36 else 3) + 1], table[i * (4 if code == 36 else 3) + 2]
            a = table[i * 4 + 3] if code == 36 else 255
            palette.append((r, g, b, a))
        out = bytearray(width * height * 4)
        for y in range(height):
            for x in range(width):
                r, g, b, a = palette[pixels[y * stride + x]]
                o = (y * width + x) * 4
                out[o:o + 4] = bytes((r, g, b, a))
        return Image.frombuffer('RGBA', (width, height), bytes(out), 'raw', 'RGBA', 0, 1)
    raise SwfError('unsupported lossless format %d' % fmt)


def decode_jpeg3(body, ps, ln, jpeg_tables=None):
    """Decode DefineBitsJPEG3 (35): JPEG colour plus a zlib alpha channel.

    Layout: char id (2), alpha data offset (4), JPEG bytes, then the zlib
    alpha plane (one byte per pixel). Returns straight-alpha RGBA.
    """
    from PIL import Image
    import io
    alpha_off = struct.unpack('<I', body[ps + 2:ps + 6])[0]
    jpg_start = ps + 6
    jpg_end = jpg_start + alpha_off
    end = ps + ln
    jpeg = body[jpg_start:jpg_end]
    if jpeg_tables is not None:
        jpeg = _strip_eoi(jpeg_tables) + _strip_soi(jpeg)
    rgb = Image.open(io.BytesIO(_fix_jpeg(jpeg))).convert('RGB')
    alpha = zlib.decompress(body[jpg_end:end])
    w, h = rgb.size
    if len(alpha) < w * h:
        raise SwfError('alpha plane short: %d < %d' % (len(alpha), w * h))
    rgba = rgb.copy()
    rgba.putalpha(Image.frombytes('L', (w, h), alpha[:w * h]))
    return rgba


def decode_jpeg(body, ps, ln, jpeg_tables=None):
    """Decode DefineBits (6) / DefineBitsJPEG2 (21): JPEG only, no alpha.

    Layout: char id (2) then JPEG bytes. DefineBits (6) reuses the shared
    JPEGTables (tag 8) when the stream has no own quantisation tables.
    """
    from PIL import Image
    import io
    data = body[ps + 2:ps + ln]
    if jpeg_tables is not None:
        data = _strip_eoi(jpeg_tables) + _strip_soi(data)
    return Image.open(io.BytesIO(_fix_jpeg(data))).convert('RGBA')


def _strip_eoi(data):
    return data[:-2] if data[-2:] == b'\xff\xd9' else data


def _strip_soi(data):
    return data[2:] if data[:2] == b'\xff\xd8' else data


def _fix_jpeg(data):
    """Repair SWF JPEG streams with a bad leading 0xFFD9 (mirrors Flash's tolerance)."""
    if data[:4] == b'\xff\xd9\xff\xd8':
        return data[4:]
    return data


def _unpremultiply(im):
    """Convert premultiplied RGBA (DefineBitsLossless2) to straight alpha."""
    import numpy as np
    from PIL import Image
    arr = np.asarray(im).astype(np.float32)
    a = arr[..., 3:4]
    safe = np.where(a == 0, 1.0, a)
    rgb = np.clip(arr[..., :3] * 255.0 / safe, 0, 255)
    rgb = np.where(a == 0, 0, rgb)
    out = np.concatenate([rgb, a], axis=-1).astype(np.uint8)
    return Image.fromarray(out, 'RGBA')


def bitmap_tags(body):
    """Yield (character_id, code, payload_start, payload_len) for bitmap definitions."""
    for off, code, ps, ln in walk_tags(body):
        if code in (6, 21, 35, 20, 36):
            cid = struct.unpack('<H', body[ps:ps + 2])[0]
            yield cid, code, ps, ln


def symbol_class(body, payload_start, payload_len):
    """Parse SymbolClass (76) into a list of (character_id, linkage_name)."""
    end = payload_start + payload_len
    count = struct.unpack('<H', body[payload_start:payload_start + 2])[0]
    pos = payload_start + 2
    out = []
    for _ in range(count):
        cid = struct.unpack('<H', body[pos:pos + 2])[0]
        pos += 2
        nul = body.index(b'\x00', pos, end)
        out.append((cid, body[pos:nul].decode('latin1')))
        pos = nul + 1
    return out

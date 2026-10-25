"""Everenfell asset extractor: carve embedded images from packed containers.

Container framing (recovered empirically from the tw/r tree, NOT guessed):
  file = MARKER1(72 60 6d + u8 type) + ASCII ID + MARKER2(72 60 6d) + blob
  blob = 3-byte plain header (01 XX 00) + payload
  payload = high-entropy table span (cipher TBD, see asset ledger) +
            plaintext regions: frame-script bytes + self-delimiting images.

Only self-delimiting, CRC/structure-verified images are extracted. The
table span is never guessed at: it is recorded as blocked in the manifest.
Provenance (source path, container offsets, sha256) is kept per asset.
"""
import hashlib
import json
import os
import struct
import sys
import zlib

MARKER = bytes([0x72, 0x60, 0x6D])
PNG_SIG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
JPG_SOI = bytes([0xFF, 0xD8, 0xFF])
JPG_EOI = bytes([0xFF, 0xD9])

RES_ROOTS = ('MKO_Client/Assets/res/tw/r', 'MKO_Client/Assets/res/f',
             'MKO_Client/Assets/res/i', 'MKO_Client/Assets/res/p',
             'MKO_Client/Assets/res/z', 'MKO_Client/Assets/res/s',
             'MKO_Client/Assets/res/m', 'MKO_Client/Assets/res/global')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def split_container(data):
    """Return (id_bytes, blob, header_len) or None if not a container."""
    if data[:3] != MARKER:
        return None
    second = data.find(MARKER, 1)
    if second < 0:
        return None
    return data[4:second], data[second + 3:], second + 3


def carve_png(buf, base):
    """Walk PNG chunks with CRC verify. Return (offset, length, w, h) or None."""
    if buf[base:base + 8] != PNG_SIG:
        return None
    pos = base + 8
    width = height = 0
    nch = 0
    while pos + 8 <= len(buf):
        (ln,) = struct.unpack('>I', buf[pos:pos + 4])
        typ = buf[pos + 4:pos + 8]
        if pos + 12 + ln > len(buf):
            return None
        if zlib.crc32(buf[pos + 4:pos + 8 + ln]) & 0xFFFFFFFF != \
                struct.unpack('>I', buf[pos + 8 + ln:pos + 12 + ln])[0]:
            return None
        if typ == b'IHDR' and ln == 13:
            width, height = struct.unpack('>II', buf[pos + 8:pos + 16])
        nch += 1
        pos += 12 + ln
        if typ == b'IEND':
            return (base, pos - base, width, height, nch)
    return None


def carve_jpeg(buf, base):
    """SOI..EOI carve with SOF dimension parse. Return dict or None."""
    if buf[base:base + 3] != JPG_SOI:
        return None
    end = buf.find(JPG_EOI, base + 3)
    if end < 0:
        return None
    end += 2
    width = height = 0
    pos = base + 2
    try:
        while pos + 4 <= end:
            if buf[pos] != 0xFF:
                break
            marker = buf[pos + 1]
            if marker in (0xD8, 0xD9) or (0xD0 <= marker <= 0xD7) or marker == 0x01:
                pos += 2
                continue
            (ln,) = struct.unpack('>H', buf[pos + 2:pos + 4])
            if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                height, width = struct.unpack('>HH', buf[pos + 5:pos + 9])
                break
            pos += 2 + ln
    except (struct.error, IndexError):
        pass
    return {'offset': base, 'length': end - base,
            'width': width, 'height': height}


def carve_images(blob, file_off_base):
    """Carve all verifiable PNG/JPEG images from a blob. Returns entries."""
    out = []
    pos = 0
    while pos < len(blob):
        hit_png = blob.find(PNG_SIG, pos)
        hit_jpg = blob.find(JPG_SOI, pos)
        cands = [(h, k) for h, k in ((hit_png, 'png'), (hit_jpg, 'jpg')) if h >= 0]
        if not cands:
            break
        cands.sort()
        at, kind = cands[0]
        if kind == 'png':
            r = carve_png(blob, at)
            if r is None:
                pos = at + 1
                continue
            off, ln, w, h, nch = r
            out.append({'kind': 'png', 'offset': file_off_base + off,
                        'length': ln, 'width': w, 'height': h,
                        'chunks': nch, 'verified': 'crc'})
            pos = off + ln
        else:
            r = carve_jpeg(blob, at)
            if r is None:
                pos = at + 1
                continue
            r['kind'] = 'jpeg'
            r['offset'] += file_off_base
            r['verified'] = 'soi-eoi' + ('+sof' if r['width'] else '')
            out.append(r)
            pos = r['offset'] - file_off_base + r['length']
    return out


def process_file(path):
    with open(path, 'rb') as fh:
        data = fh.read()
    rec = {'path': path.replace('\\', '/'), 'size': len(data),
           'sha256': sha256(data)}
    hdr = split_container(data)
    if hdr is None:
        rec['container'] = 'raw'
        return rec, []
    ident, blob, hlen = hdr
    try:
        rec['container'] = {'id': ident.decode('ascii'), 'header_len': hlen,
                            'blob_len': len(blob),
                            'head3': blob[:3].hex()}
    except UnicodeDecodeError:
        rec['container'] = {'id_hex': ident.hex(), 'header_len': hlen,
                            'blob_len': len(blob),
                            'head3': blob[:3].hex() if len(blob) >= 3 else ''}
    rec['table_span'] = 'blocked: cipher TBD (see asset ledger)'
    images = carve_images(blob, hlen)
    return rec, images


def main(argv):
    roots = [r for r in RES_ROOTS if os.path.isdir(r)]
    exts = {'.pak', '.ani'}
    if '--all' in argv:
        exts |= {'.png', '.jpg', '.jpeg', '.mp3'}
    files = []
    for root in roots:
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() in exts:
                    files.append(os.path.join(dirpath, fn))
    files.sort()
    out_dir = os.path.join('output', 'everenfell-assets')
    os.makedirs(out_dir, exist_ok=True)
    manifest = {'files': [], 'images': [], 'blocked': []}
    for path in files:
        try:
            rec, images = process_file(path)
        except (OSError, ValueError) as exc:
            manifest['blocked'].append({'path': path, 'reason': str(exc)})
            continue
        manifest['files'].append(rec)
        for img in images:
            with open(path, 'rb') as fh:
                fh.seek(img['offset'])
                payload = fh.read(img['length'])
            rel = os.path.relpath(path, 'MKO_Client/Assets/res')
            stem = '%s@%d.%s' % (rel.replace('/', '_').replace('\\', '_'),
                                 img['offset'],
                                 'png' if img['kind'] == 'png' else 'jpg')
            dest = os.path.join(out_dir, stem)
            with open(dest, 'wb') as fh:
                fh.write(payload)
            manifest['images'].append({
                'source': rec['path'], 'offset': img['offset'],
                'length': img['length'], 'kind': img['kind'],
                'width': img['width'], 'height': img['height'],
                'verified': img['verified'], 'sha256': sha256(payload),
                'extracted': dest.replace('\\', '/')})
    dest_json = os.path.join('output', 'everenfell-asset-manifest.json')
    with open(dest_json, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=1)
    n_img = len(manifest['images'])
    n_ok = sum(1 for i in manifest['images'] if i['width'])
    print('files=%d images=%d with_dims=%d manifest=%s'
          % (len(manifest['files']), n_img, n_ok, dest_json))


if __name__ == '__main__':
    main(sys.argv[1:])

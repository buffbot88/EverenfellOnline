"""Regression tests for the Everenfell container carver (synthetic bytes)."""
import os
import struct
import sys
import unittest
import zlib

sys.path.insert(0, os.path.dirname(__file__))
import everenfell_assets as ea  # noqa: E402


def png_chunk(typ, body):
    crc = zlib.crc32(typ + body) & 0xFFFFFFFF
    return struct.pack('>I', len(body)) + typ + body + struct.pack('>I', crc)


def make_png(width, height):
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return ea.PNG_SIG + png_chunk(b'IHDR', ihdr) + png_chunk(b'IEND', b'')


def make_jpeg_sof(width, height):
    # SOI, SOF0 (height/width at +5..+9), EOI.
    sof_body = bytes([8]) + struct.pack('>HH', height, width) + bytes([1, 1, 0x11, 0])
    sof = b'\xff\xc0' + struct.pack('>H', len(sof_body) + 2) + sof_body
    return b'\xff\xd8' + sof + b'\xff\xd9'


class CarvePngTests(unittest.TestCase):
    def test_carves_verified_png_with_dimensions(self):
        blob = b'\x87\xb0\x2b' + make_png(7, 3) + b'tail'
        hits = ea.carve_images(blob, 100)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['kind'], 'png')
        self.assertEqual((hits[0]['width'], hits[0]['height']), (7, 3))
        self.assertEqual(hits[0]['offset'], 100 + 3)
        self.assertEqual(hits[0]['verified'], 'crc')

    def test_rejects_png_with_bad_crc(self):
        good = make_png(4, 4)
        bad = bytearray(good)
        bad[16 + 13 + 4] ^= 0xFF  # corrupt IHDR CRC byte
        self.assertIsNone(ea.carve_png(bytes(bad), 0))

    def test_truncated_png_is_not_carved(self):
        self.assertIsNone(ea.carve_png(make_png(4, 4)[:-5], 0))


class CarveJpegTests(unittest.TestCase):
    def test_carves_jpeg_with_sof_dimensions(self):
        blob = make_jpeg_sof(256, 128) + b'\x00'
        hits = ea.carve_images(blob, 0)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['kind'], 'jpeg')
        self.assertEqual((hits[0]['width'], hits[0]['height']), (256, 128))
        self.assertEqual(hits[0]['verified'], 'soi-eoi+sof')

    def test_jpeg_without_eoi_is_not_carved(self):
        self.assertEqual(ea.carve_images(b'\xff\xd8\xff\xe0\x00\x02', 0), [])


class ContainerTests(unittest.TestCase):
    def test_split_container_reads_id_and_blob(self):
        # MARKER1 (3 bytes) + type byte 0x08 + ASCII id + MARKER2 + blob.
        data = ea.MARKER + b'\x08' + b'5269bf3e' + ea.MARKER + b'\x01\x1c\x00PAY'
        result = ea.split_container(data)
        self.assertIsNotNone(result)
        ident, blob, hlen = result
        self.assertEqual(ident, b'5269bf3e')
        self.assertEqual(blob[:3], b'\x01\x1c\x00')
        self.assertEqual(hlen, 4 + len(b'5269bf3e') + 3)

    def test_non_container_returns_none(self):
        self.assertIsNone(ea.split_container(b'FWS\x0b\x00\x00'))


if __name__ == '__main__':
    unittest.main()

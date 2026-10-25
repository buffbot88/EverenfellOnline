"""Regression tests for the SWF inventory and bitmap decoders.

The real-sample tests run only when the local recovered gameui module is
present under output/ (it is git-ignored and never committed). Synthetic
tests always run.
"""
import json
import os
import struct
import sys
import unittest
import zlib

sys.path.insert(0, os.path.dirname(__file__))
import swf_inventory as s  # noqa: E402

SAMPLE = os.path.join('output', 'swf-memory', 'mem-000010d40020-da6d57518e94.swf')
MANIFEST = os.path.join('output', 'swf-export', 'gameui', 'manifest.json')


def tag(code, payload):
    if len(payload) < 0x3F:
        return struct.pack('<H', (code << 6) | len(payload)) + payload
    return struct.pack('<HI', (code << 6) | 0x3F, len(payload)) + payload


def minimal_fws(tags):
    rect = bytes([0x78, 0x00, 0x05, 0x5F, 0x00, 0x00, 0x0F, 0xA0, 0x00])
    body = rect + struct.pack('<HH', 24, 1) + b''.join(tags) + tag(0, b'')
    return b'FWS' + bytes([10]) + struct.pack('<I', 8 + len(body)) + body


class SyntheticTests(unittest.TestCase):
    def test_fws_round_trip_and_tag_walk(self):
        raw = minimal_fws([tag(1, b'')])
        sig, ver, body = s.normalize(raw)
        self.assertEqual((sig, ver), ('FWS', 10))
        codes = [code for _, code, _, _ in s.walk_tags(body)]
        self.assertEqual(codes, [1, 0])

    def test_cws_normalizes_to_same_canonical_hash(self):
        fws = minimal_fws([tag(1, b'')])
        cws = b'CWS' + fws[3:8] + zlib.compress(fws[8:])
        _, _, body_a = s.normalize(fws)
        _, _, body_b = s.normalize(cws)
        self.assertEqual(s.canonical_sha256(body_a), s.canonical_sha256(body_b))

    def test_declared_length_mismatch_is_rejected(self):
        raw = bytearray(minimal_fws([tag(1, b'')]))
        raw[4] ^= 0x01
        with self.assertRaises(s.SwfError):
            s.normalize(bytes(raw))

    def test_tag_overrun_is_rejected(self):
        raw = minimal_fws([tag(1, b'')])
        _, _, body = s.normalize(raw)
        broken = body[:-2]
        with self.assertRaises(s.SwfError):
            list(s.walk_tags(broken))

    def test_lossless2_truecolour_is_premultiplied_to_straight(self):
        # Format 5, one ARGB pixel stored as B,G,R,A: alpha 128, premultiplied colour 64.
        pixels = bytes([64, 64, 64, 128])
        im = s._lossless_image(5, 1, 1, pixels, 36)
        self.assertEqual(im.mode, 'RGBA')
        r, g, b, a = im.getpixel((0, 0))
        self.assertEqual(a, 128)
        # Straight colour = 64 * 255 / 128 = 127.5, truncated to 127.
        self.assertEqual(r, 127)
        self.assertEqual(g, 127)
        self.assertEqual(b, 127)


@unittest.skipUnless(os.path.isfile(SAMPLE), 'recovered gameui sample not present')
class RealSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SAMPLE, 'rb') as fh:
            cls.raw = fh.read()
        _, _, cls.body = s.normalize(cls.raw)

    def test_sample_walks_exactly(self):
        tags = list(s.walk_tags(self.body))
        self.assertEqual(len(tags), 759)

    def test_bitmap_census(self):
        codes = [code for _, code, _, _ in s.walk_tags(self.body)
                 if code in (6, 21, 35, 20, 36)]
        self.assertEqual(len(codes), 170)

    def test_exported_manifest_matches_sample(self):
        if not os.path.isfile(MANIFEST):
            self.skipTest('export manifest not generated yet')
        with open(MANIFEST, encoding='utf-8') as fh:
            m = json.load(fh)
        self.assertEqual(m['canonical_sha256'], s.canonical_sha256(self.body))
        self.assertEqual(m['counts'], {'bitmap_tags': 170, 'ok': 170, 'failed': 0})


if __name__ == '__main__':
    unittest.main()

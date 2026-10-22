"""Sealed-traits AMF3 objects must match the Java oracle byte for byte.

The client stalled before scene entry (no 21000) while every reply matched
at the decoded-value level; a skeleton diff against the Oct 18 capture
showed Python sending anonymous-dynamic objects where Java sends sealed
traits (10001 ZoneInfo, 32000 mall rows). These tests pin the sealed shape.
"""
import unittest

from game.amf3 import Obj, SealedObj, decode, encode
from game.config import MALL_ITEM_KEYS

# Captured Java bytes for the 10001 TimeZone slot
# (session-20261018-195420.log): sealed sun.util.calendar.ZoneInfo with
# members rawOffset/ID, no dynamic tail.
JAVA_TZ_HEX = (
    '0a233573756e2e7574696c2e63616c656e6461722e5a6f6e65496e666f'
    '137261774f666673657405494404fbdad7800621416d65726963612f4e'
    '65775f596f726b'
)


class SealedEncodingTest(unittest.TestCase):
    def test_timezone_matches_java_bytes(self):
        tz = SealedObj({'rawOffset': -18000000, 'ID': 'America/New_York'},
                       cname='sun.util.calendar.ZoneInfo',
                       members=('rawOffset', 'ID'))
        self.assertEqual(encode(tz).hex(), JAVA_TZ_HEX)

    def test_repeat_uses_traits_ref_and_round_trips(self):
        from game.amf3 import Writer
        w = Writer()
        mk = lambda v: SealedObj({'a': v}, members=('a',))
        w.write(mk(1))
        w.write(mk(2))
        wire = bytes(w.b)
        # Second object opens with marker 0x0A plus traits-ref index 0.
        self.assertEqual(wire.count(b'\x0a\x01'), 1)
        first = decode(bytes(w.b[:7]))
        self.assertEqual(first, {'a': 1})

    def test_mall_row_is_sealed_with_bean_member_order(self):
        row = SealedObj([(k, '') for k in MALL_ITEM_KEYS],
                        members=MALL_ITEM_KEYS)
        wire = encode(row)
        self.assertEqual(wire[0], 0x0A)
        # Traits word (29 << 4) | 0x03, then the empty class name.
        self.assertEqual(wire[1:4], bytes([0x83, 0x53, 0x01]))
        back = decode(wire)
        self.assertIsInstance(back, Obj)
        self.assertEqual(list(back.keys()), list(MALL_ITEM_KEYS))

    def test_mall_rows_share_one_traits_table(self):
        from game.amf3 import Writer
        w = Writer()
        w.write([SealedObj([(k, str(i)) for k in MALL_ITEM_KEYS],
                           members=MALL_ITEM_KEYS)
                 for i in range(3)])
        wire = bytes(w.b)
        # One inline traits block; rows 2-3 are 0x0A 0x01 traits-refs.
        self.assertEqual(wire.count(bytes([0x83, 0x53])), 1)
        self.assertEqual(wire.count(b'\x0a\x01'), 2)
        back = decode(wire)
        self.assertEqual(len(back), 3)
        self.assertEqual(list(back[0].keys()), list(MALL_ITEM_KEYS))
        self.assertEqual(back[2]['maxcount'], '2')


if __name__ == '__main__':
    unittest.main()

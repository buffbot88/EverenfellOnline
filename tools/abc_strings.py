#!/usr/bin/env python3
"""Extract ActionScript constant-pool strings (and method/multiname names)
from a SWF's DoABC tags. Used to reverse the asset-pack cipher without a
decompiler (no Java/FFDec on this machine).

Usage: python3 tools/abc_strings.py <file.swf> [--names]
"""
import struct
import sys
import zlib


class R:
    def __init__(self, d):
        self.d = d
        self.p = 0

    def u8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def u30(self):
        v = shift = 0
        for i in range(5):
            b = self.u8()
            v |= (b & 0x7F) << shift
            if not b & 0x80:
                return v
            shift += 7
        return v

    def s32(self):
        v = self.u30()
        return v - 0x100000000 if v & 0x80000000 else v

    def d64(self):
        v = struct.unpack("<d", self.d[self.p:self.p + 8])[0]
        self.p += 8
        return v

    def string(self):
        n = self.u30()
        s = self.d[self.p:self.p + n].decode("utf-8", errors="replace")
        self.p += n
        return s


def swf_body(path):
    raw = open(path, "rb").read()
    if raw[:3] == b"CWS":
        return zlib.decompress(raw[8:])
    if raw[:3] == b"FWS":
        return raw[8:]
    raise ValueError("not a plain SWF")


def tags(body):
    # skip RECT
    nbits = (body[0] >> 3) & 0x1F
    off = ((5 + nbits * 4 + 7) // 8) + 4
    pos = off
    while pos + 2 <= len(body):
        hdr = struct.unpack("<H", body[pos:pos + 2])[0]
        pos += 2
        ttype, tlen = hdr >> 6, hdr & 0x3F
        if tlen == 0x3F:
            tlen = struct.unpack("<I", body[pos:pos + 4])[0]
            pos += 4
        yield ttype, body[pos:pos + tlen]
        if ttype == 0:
            break
        pos += tlen


def extract(path):
    """Return (strings, multinames) from all DoABC tags in the SWF."""
    body = swf_body(path)
    strings, multinames = [""], []
    for ttype, data in tags(body):
        # DoABC = 72, DoABCDefine = 82. (Tag 84 is DefineMorphShape2 —
        # parsing it as ABC is what caused "unknown multiname kind" errors.)
        if ttype not in (72, 82):
            continue
        r = R(data)
        if ttype in (72, 82):  # DoABC / DoABCDefine share the layout
            r.p += 4  # flags: fixed U32
            while r.d[r.p] != 0:  # name: NUL-terminated, NOT u30-prefixed
                r.p += 1
            r.p += 1
        r.p += 4  # minor+major
        # ints
        for _ in range(max(0, r.u30() - 1)):
            r.s32()
        # uints
        for _ in range(max(0, r.u30() - 1)):
            r.u30()
        # doubles
        for _ in range(max(0, r.u30() - 1)):
            r.d64()
        # strings
        ns = r.u30()
        pool = [""]
        for _ in range(max(0, ns - 1)):
            pool.append(r.string())
        strings.extend(pool[1:])
        # namespaces
        nn = r.u30()
        nstab = []
        for _ in range(max(0, nn - 1)):
            nstab.append((r.u8(), r.u30()))
        # ns sets
        for _ in range(max(0, r.u30() - 1)):
            for _ in range(r.u30()):
                r.u30()
        # multinames (fault-tolerant: a single obfuscated entry must not
        # discard the strings pool we already recovered from this tag)
        try:
            nm = r.u30()
            for _ in range(max(0, nm - 1)):
                kind = r.u8()
                if kind in (7, 13):
                    ns_i, name_i = r.u30(), r.u30()
                    multinames.append(pool[name_i] if name_i < len(pool) else "?")
                elif kind in (15, 16):
                    name_i = r.u30()
                    multinames.append(pool[name_i] if name_i < len(pool) else "?")
                elif kind in (17, 18):
                    r.u30()
                elif kind in (9, 14):
                    name_i = r.u30()
                    multinames.append(pool[name_i] if name_i < len(pool) else "?")
                    r.u30()  # ns_set index (single u30)
                elif kind in (27, 28):
                    r.u30()  # ns_set index (single u30)
                elif kind == 29:
                    r.u30()
                    for _ in range(r.u30()):
                        r.u30()
                else:
                    # Unknown kind (e.g. packer-obfuscated entry): stop the
                    # multiname walk for this tag, keep what we have.
                    break
        except (ValueError, IndexError):
            pass
    return strings, multinames


def main():
    path = sys.argv[1]
    want_names = "--names" in sys.argv
    strings, multis = extract(path)
    if want_names:
        for m in sorted(set(multis)):
            print(m)
    else:
        for s in sorted(set(strings)):
            if s:
                print(s)


if __name__ == "__main__":
    main()

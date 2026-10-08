#!/usr/bin/env python3
"""Survey Flash files: version, AS2/AS3, transport classes, CJK text volume.

Usage: python3 tools/swf_survey.py [root] [--details]
Walks <root> for *.swf, parses each SWF header + tag stream (FWS/CWS),
and prints a summary table. --details adds per-file rows.
"""
import os
import re
import struct
import sys
import zlib

TAG_NAMES = {
    0: "End", 2: "DefineShape", 6: "DefineBits", 10: "DefineFont",
    11: "DefineText", 12: "DoAction", 14: "DefineFontInfo", 20: "DefineBitsLossless",
    21: "DefineBitsJPEG2", 22: "DefineShape2", 26: "PlaceObject2", 32: "DefineShape3",
    33: "DefineText2", 35: "DefineBitsJPEG3", 36: "DefineBitsLossless2",
    37: "DefineEditText", 39: "DefineSprite", 46: "DefineMorphShape",
    48: "DefineFont2", 59: "DefineFontInfo2", 60: "VideoFrame", 69: "FileAttributes",
    73: "DefineFontAlignZones", 74: "CSMTextSettings", 75: "DefineFont3",
    76: "SymbolClass", 77: "Metadata", 82: "DoABC", 83: "DefineScale9Grid",
    84: "DoABCDefine", 86: "DefineSceneAndFrameLabelData", 87: "DefineBinaryData",
    88: "DefineFontName", 90: "DefineBitsJPEG4",
}
TRANSPORT_MARKERS = [b"XMLSocket", b"flash.net.Socket", b"URLLoader",
                     b"URLStream", b"NetConnection", b"flash.net.Socket",
                     b"Socket", b"ExternalInterface", b"LocalConnection"]
CJK_RUN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]{2,}")


class BitReader:
    def __init__(self, data):
        self.d = data
        self.byte = 0
        self.bit = 0

    def read(self, n):
        val = 0
        for _ in range(n):
            if self.bit == 0:
                self.cur = self.d[self.byte] if self.byte < len(self.d) else 0
                self.byte += 1
            val = (val << 1) | ((self.cur >> (7 - self.bit)) & 1)
            self.bit = (self.bit + 1) % 8
        return val


def parse_swf(path):
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) < 8:
        return {"error": "too small"}
    sig, ver, flen = raw[0:3], raw[3], struct.unpack("<I", raw[4:8])[0]
    if sig == b"FWS":
        body = raw[8:]
    elif sig == b"CWS":
        try:
            body = zlib.decompress(raw[8:])
        except Exception as e:
            return {"error": f"zlib: {e}"}
    else:
        return {"error": f"unsupported sig {sig!r}"}
    # skip RECT + frameRate(2) + frameCount(2)
    br = BitReader(body)
    nbits = br.read(5)
    br.read(nbits * 4)
    off = br.byte + 4
    tags = {}
    pos = off
    while pos + 2 <= len(body):
        hdr = struct.unpack("<H", body[pos:pos + 2])[0]
        pos += 2
        ttype, tlen = hdr >> 6, hdr & 0x3F
        if tlen == 0x3F:
            if pos + 4 > len(body):
                break
            tlen = struct.unpack("<I", body[pos:pos + 4])[0]
            pos += 4
        tags[ttype] = tags.get(ttype, 0) + tlen
        if ttype == 0:
            break
        pos += tlen
        if pos > len(body):
            break
    text = body.decode("utf-8", errors="ignore")
    cjk = set(CJK_RUN.findall(text))
    latin_runs = re.findall(r"[A-Za-z][A-Za-z0-9_ .,'!?()-]{7,}", text)
    latin = set(s.strip() for s in latin_runs if len(s.strip()) > 8)
    return {
        "sig": sig.decode("latin1"), "ver": ver,
        "size": len(raw),
        "tags": tags,
        "has_abc": 82 in tags or 84 in tags,
        "has_action": 12 in tags,
        "has_text": any(t in tags for t in (11, 33, 37)),
        "has_font": any(t in tags for t in (10, 48, 75)),
        "markers": sorted({m.decode() for m in TRANSPORT_MARKERS if m in body}),
        "cjk_count": len(cjk),
        "cjk_sample": sorted(cjk)[:5],
        "latin_count": len(latin),
    }


def main():
    root = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else \
        "TonNgoKhong/server/ESSamp/wwwroot"
    details = "--details" in sys.argv
    files = []
    for dp, _, fns in os.walk(root):
        for fn in fns:
            if fn.lower().endswith(".swf"):
                files.append(os.path.join(dp, fn))
    rows = []
    for p in sorted(files):
        try:
            r = parse_swf(p)
        except Exception as e:  # noqa: BLE001
            r = {"error": str(e)}
        r["path"] = os.path.relpath(p, root)
        rows.append(r)
    ok = [r for r in rows if "error" not in r]
    bad = [r for r in rows if "error" in r]
    vers, as3, as2, txt, fnt = {}, 0, 0, 0, 0
    markers = {}
    total_cjk = 0
    biggest = []
    for r in ok:
        vers[r["ver"]] = vers.get(r["ver"], 0) + 1
        as3 += r["has_abc"]
        as2 += (not r["has_abc"] and r["has_action"])
        txt += r["has_text"]
        fnt += r["has_font"]
        for m in r["markers"]:
            markers[m] = markers.get(m, 0) + 1
        total_cjk += r["cjk_count"]
        biggest.append((r["cjk_count"], r["size"], r["path"]))
    print(f"files: {len(rows)} ok={len(ok)} errors={len(bad)}")
    for r in bad[:10]:
        print(f"  ERR {r['path']}: {r['error']}")
    print(f"versions: {dict(sorted(vers.items()))}")
    print(f"AS3(DoABC): {as3}  AS2-only(DoAction,no ABC): {as2}  "
          f"with text tags: {txt}  with fonts: {fnt}")
    print(f"transport markers (files containing): {markers}")
    print(f"total unique CJK strings (summed per-file): {total_cjk}")
    biggest.sort(reverse=True)
    print("top 15 files by CJK string count:")
    for c, s, p in biggest[:15]:
        print(f"  {c:5d}  {s // 1024:6d}KB  {p}")
    if details:
        print("\nper-file:")
        for r in ok:
            t = ",".join(str(t) for t in sorted(r["tags"]))
            print(f"{r['path']} v{r['ver']} abc={r['has_abc']} "
                  f"cjk={r['cjk_count']} latin={r['latin_count']} "
                  f"markers={r['markers']} tags=[{t}]")


if __name__ == "__main__":
    main()

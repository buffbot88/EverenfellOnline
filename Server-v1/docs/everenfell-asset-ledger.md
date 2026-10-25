# Everenfell asset ledger (Missions 2-3)

## Inventory (reproducible via tools/swf_catalog.py)

199 SWFs under MKO_Client, 32.8 MB: 6 standard, 193 packed-opaque.

- Standard (extractable now): MainLoader.swf (CWS v11, 125 KB),
  PlatformLoader.swf (CWS v14, 83 KB), Main.swf (CWS v15, 17 KB),
  MPlayer.swf (CWS v14, 1.4 KB), lib.swf (FWS v11, 54 bytes, stub),
  playerProductInstall.swf (CWS v6, 657 bytes, Adobe stock).
- Packed: 98 in res/assets/ + 95 in res/assets/tw/ (zhcn/tw locales).
  Headers are not SWF signatures: byte 0 is 0x00 in 192/193 files,
  bytes 1-3 read as small ints (length prefix), the rest is
  high-entropy. No per-filename XOR/MD5 key decodes them (tested
  md5(name), raw name, offsets 0/4 over the first 30 files).

Catalog output (local-only, regenerate anytime):
`output/swf-catalog.json` (path, size, sha256, header class, status).

## Loader chain (static ABC analysis via tools/avm2.py)

res/index.html -> MainLoader.swf -> res/Main.swf ->
res/PlatformLoader.swf, whose Alchemy C module exports `_Md5_decode`
(MD5 + XOR stream, `___xordi3`). Main.swf holds the string
`decodeFunction` and `PlatformLoader.swf?v=` and calls `loadBytes`:
the decoded bytes are loaded as SWFs at runtime. Framework vendor
namespace is `com.youbt.*` (manager/core), entry class
`RFSystemManager`. Resource manifests: res/data/{zhcn,tw,...}_config.xml
(name -> file under assets/{locale}/, `{0}` version slot,
version.txt `1.0.271`) and res/data/hash.dat (zlib AMF listing every
.dat data file with a 10-hex hash).

Complication: all three app ABCs carry a junk multiname region after
the valid entries (Main.swf: 66 valid of 383 declared, 1209-byte
filler of counter-shaped fakes, then a valid method section).
tools/avm2.py rescans and validates to end-of-buffer, so the parse is
exact and the filler span is recorded, not skipped silently.

## Provenance and rights

All MKO_Client bytes are legacy Binjiang-distribution reference
material of unknown redistribution rights. Treat as immutable,
never publish. Asset modernization must use compatible replacements
where rights are unclear; recovered timing/anchors/mappings may guide
original replacements.

## Open items

1. Exact `_Md5_decode` key source: no key literal in PlatformLoader;
   key likely arrives at runtime (flashvars/config version session).
   Next step: disassemble the decode-calling method in Main.swf
   (bodies fully parsed; multiname resolution past the junk region
   still needed to name the call target and its key argument).
2. Full ABC (methods/traits/classes) naming for sprite/behavior
   reference: blocked on the same junk-region name recovery.
3. 193 packed files remain opaque until (1) lands.

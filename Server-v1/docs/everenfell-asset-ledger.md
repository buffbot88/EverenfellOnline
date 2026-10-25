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

res/index.html embeds `Main.swf?<hex-timestamp>` full-window plus a
10x2 `MPlayer.swf` stub, with flashvars `{lcid: <hex time><hex rand>}`.
res/Main.swf (16 KB bootstrap, fully parsed: 228 methods / 227 bodies)
is a static-init bundle holding the strings `PlatformLoader.swf?v=`,
`assets/tg.swf?v=`, `HASH`, `VERSION`, `decodeFunction`, `loadBytes`,
`INIT_COMPLETE` / `INIT_PROGRESS`. It loads res/PlatformLoader.swf,
whose Alchemy C module exports `_Md5_decode` (+ `FSM_Md5_decode`,
`_md5update`, `_md5transform`, `___xordi3` 64-bit XOR, `domainMemory`).
Key-schedule vocabulary in PlatformLoader: `vgl_keyinit`, `vgl_keych`,
`vgl_keymode: `, `vglKeys`, `id2key`, `hashBinary`. Separately,
Assets/MainLoader.swf carries the `mmo.loader` package (LoadingBar,
logoLoader, urlLoader) with an `invalidHash` check: it verifies
assets against the manifest. Framework vendor namespace is
`com.youbt.*` (manager/core), entry class `RFSystemManager`.
Resource manifests: res/data/{zhcn,tw,...}_config.xml (name -> file
under assets/{locale}/, `{0}` version slot, version.txt `1.0.271`)
and res/data/hash.dat (1063-byte zlib AMF object mapping every .dat /
config filename to a 10-hex-digit content hash).

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

## Pack container format (Mission 3 continued, verified 2026-10-25)

`.pak` / `.ani` files under res/tw/r/ are containers, not cipher blobs:
`MARKER1(72 60 6d + u8 type: 01=pak, 08=ani) + ASCII ID + MARKER2(72 60 6d)
+ 3-byte plain header (01 XX 00) + payload`. The XX byte varies per file
(e.g. 28/78/49/15 across four same-set .ani files; plausibly a frame or
entry count, unconfirmed). The payload is a high-entropy table span
followed by PLAINTEXT regions: frame-script bytes and self-delimiting
images. Cipher/stream analysis: the first ~20 payload bytes are
identical across same-set files (shared keystream start OR shared
plaintext header); single-XOR with md5/sha1/hex/id/name-derived keys
all fail (output indistinguishable from random, scored). No further
guessing: table-span decoding waits on the loader bytecode (below).

Carving (tools/everenfell_assets.py, manifest
output/everenfell-asset-manifest.json, extracts under
output/everenfell-assets/): PNGs are chunk-walked with per-chunk CRC
verification, JPEGs SOI..EOI with SOF dimension parse. Yield on
2026-10-25: 1638 container files -> 1350 images (1001 CRC-verified
PNGs + 349 JPEGs, 1347 with decoded dimensions, ~516 MB), 0 unread
files. PIL spot-checks open (e.g. 6767x1187 and 3577x679 sprite
sheets, indexed and RGB). Entry payloads start right after a 3-4 byte
separator (e.g. `87 b0 2b` before PNG, `0c 88 9d 6b` before JPEG).

Fully open (no container) asset groups, confirmed by magic bytes:
res/m/ map tiles (plain JPEG, EXIF; m/0 alone is a numbered tile grid),
res/f/ + res/i/ + res/p/ + res/z/ PNGs, res/s/ MP3s (ID3/frame sync),
res/global/ branding JPG/PNGs. Per-directory census: cj 47 .pak,
ef 544 .ani, em 70 .ani, f 720 PNG, i 2084 PNG, m 129 map dirs (803 MB),
n 901 .pak (466 MB), o 25 .ani, p 9 PNG, s 223 MP3, z 594 PNG,
zq 10 .pak.

## Open items

1. Table-span cipher + packed UI SWF (assets/*.swf, `00 00` header)
cipher + exact `_Md5_decode` key source. All three logic ABCs
(PlatformLoader, MainLoader, MPlayer) fail strict method-table parse
(`no resync` in tools/avm2.py); only the res/Main.swf bootstrap parses
fully. The AS3 caller (`vgl_keyinit`/`id2key`/`hashBinary` path) and
the Alchemy key bytes are therefore still unreachable statically.
Next step: harden tools/avm2.py method-table recovery (junk entries
in the methods region), then disassemble the decode caller.
2. Full ABC (methods/traits/classes) naming for sprite/behavior
reference: blocked on the same methods-region recovery.
3. Frame-script regions (`00 04 ...` opcode-like bytes before embedded
images) are plaintext but unparsed: next step is a script-format
reader producing frame/direction/anchor metadata.
4. Map assembly (tile grid -> scene): tiles are open; layout source
(maps.dat / cj scene .paks / config xmls) not yet traced.
5. No recovered bytes ship publicly: originals stay under MKO_Client/
(immutable reference); output/ extracts are local working material.

## Packed UI SWF decode attempt (2026-10-25, blocked)

Verified facts for `res/assets/*.swf` (98 files tested):

- No file has a plaintext FWS/CWS/ZWS signature in its first 64 bytes.
- First 4 bytes are not a length: big-endian u32 is about size/2, not size-4.
- First two bytes are one of 7 values (0000..0002, 0005, 0006, 081f), so
  the leading bytes are not random.
- The standalone `tools/de_debug.py` decoder is a no-op: `run_de` returns
  its input unchanged (verified on Shop.swf, sha-identical). It exits at
  the first `iffalse` with the loop counter unseeded. It is NOT a decoder.

Blocker: the decode key/state (MD5 seed, `ds` buffer, `_Md5_decode` input
contract) is not recoverable from the bytes alone. Nothing here is decoded.
No artwork is recovered from these SWFs by this path.

Note: `tools/` is git-ignored (`.gitignore: /tools/*`), so the Alchemy
interpreter and avm2 parser fixes are local-only and cannot be committed
from this repository.

## gameUI resource chain (verified 2026-10-25)

Resource resolution, from the locale manifests (`res/data/{tw,zhcn,kokr}_config.xml`):

- `<resource name="gameui" prefix="lan-root" v="1" value="gameui{0}" />`
- `lan-root` is `assets/tw/`, `assets/zhcn/`, or `assets/kokr/` per locale.
- So the tw build loads `assets/tw/gameui.swf` (596,076 bytes). The
  root `assets/gameUI.swf` (47,936 bytes) is a different file the tw
  manifest does not resolve to.
- zhcn loads `assets/zhcn/gameui.gz` or `gameui.mpq`; kokr loads
  `assets/kokr/gameui.gz`.

Format, verified from headers only:

- None of the five gameui files has a plaintext FWS/CWS/ZWS signature.
- `assets/kokr/gameui.gz` is NOT gzip (no 1f8b magic), NOT zlib, and NOT
  raw deflate. Its extension is misleading. It shares the leading-bytes
  family (`00 05`) of the other packed UI containers.
- The gameUI payloads are in the same unresolved packed format as
  `res/assets/*.swf`. Their decode key remains the open blocker.

Not established: which external PNG or embedded symbols gameUI references,
how the HUD is laid out, and whether hash.dat lists gameui (hash.dat inflates
with zlib, but no gameui entry was found in the decompressed text).

## Runtime extraction of gameui: blocked at the launcher (verified 2026-10-25)

Target: `MKO_Client/Assets/res/assets/tw/gameui.swf` (596,076 bytes).

Tooling inspected:

- `MKO_Client/flash-projector/flashplayer363.exe` (Flash Player 32.0.0.363)
- `MKO_Client/flash-projector/flashplayer32_sa_debug.exe` (32.0.0.465, debug build)
- `tools/projector-client.py` launches the projector only after a signed
  session is obtained from the legacy web backend. Its default path
  posts to `AccountHandler.php` and reads `Gamelogin.php`; its
  `--api-base` path calls a separate API. Both need a live backend.

Observed:

- `tools/projector-client.py --dry-run` fails inside urllib with a
  connection error, so no movie URL is produced and the projector is not
  launched.
- Something is listening on `127.0.0.1:8080` (PID 2220). Its identity is
  unverified and it was not started by this investigation.

Conclusion: runtime extraction of gameui cannot start without a live
backend session. Retired PHP/Java must not be revived as production
infrastructure, and this step does not do so. No gameui bytes were
captured by this investigation.

Next step that unblocks this: provide a signed flashvars/session capture
from the original client run (or a verified loader trace) so that the
projector can be launched once, without the backend running at runtime.

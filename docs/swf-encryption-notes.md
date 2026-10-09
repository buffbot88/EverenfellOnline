# Client SWF encryption: findings so far

Status: **not solved.** The 193 encrypted or non-standard SWFs under
`MKO_Client/Assets/` cannot be decompiled yet. Their layouts and strings stay
unavailable until this is solved. Last checked 2026-10-09.

## Facts (measured)

- 199 SWFs total. 6 have a standard `CWS`/`FWS` header. `tg.swf` starts with
  `08 1F 86 EC`, which is not a SWF header. The other 192 start with a
  two-byte prefix, mostly `00 00` (108 files) or `00 01` (46 files), and the
  first byte is never `CWS` or `FWS`.
- Shannon entropy of the encrypted files is 7.99–8.00 bits per byte. The
  data is fully scrambled, not zlib or plain compressed.
- A big-endian `u32` at offset 0 does not match the file length, so it is not
  a length field.
- 8 files contain a `CWS`/`FWS` byte sequence at some offset. The version byte
  after it is 71–242, which is not a valid SWF version, so these look like
  coincidental matches in random bytes.
- The first two bytes are small values (0–6), which suggests a header or key
  index, but two files with the same prefix (`bagUI.swf`, `baicaoyuan.swf`)
  do not share a keystream under a `CWS` plaintext guess.

## Ruled out

- **Length prefix** as a file-size field: no match in any file.
- **Single-byte XOR** (all 256 keys, tested on the first three bytes at offsets
  0 and 2 across 192 files): 0 hits for `CWS` or `FWS`.
- **Per-file XOR key from the `CWS` header:** the implied key bytes differ between
  files with the same prefix, so there is no fixed keystream to reuse.

## Where the decrypt lives (not yet read)

- `RFPluginUtils.decodeFunction` (`output/ffdec/decompiled-main`) decodes only
  blobs whose first byte is ≥ 0x80. These files start with `00`, so the stock
  `de()` passes them through unchanged. The UI SWFs are therefore not decrypted
  by that function.
- The Alchemy C core in `PlatformLoader.swf`, decompiled to 191 AS3 files under
  `output/ffdec/decompiled-pl/scripts/cmodule/ccode/`, is the most likely place
  the real decrypt happens. It has not been read.

## Next steps

1. Read the `cmodule/ccode` AS3 for the decrypt routine: find the function that
   reads a `ByteArray`, transforms it, and passes it to `Loader.loadBytes`.
2. Reproduce that routine in Python and test it on `bagUI.swf` and
   `baicaoyuan.swf`. A valid result starts with `CWS` or `FWS` and passes
   `ffdec-cli` export.
3. Re-run the checks above on the full set once one file decrypts.

## Time-boxed attempt (2026-10-09): result

- The Alchemy runtime in `cmodule/ccode` contains MD5 routines
  (`FSM_md5transform`, `FSM_md5update`, `FSM_Md5_decode`), but no
  game-specific decrypt is named. The app-level C functions are not
  identified in the decompiled output.
- MD5-based keystreams tested on `bagUI.swf`, `baicaoyuan.swf`, and
  `mojieUI.swf`: the raw MD5 repeated and an MD5 chain, each keyed by the file
  name in several forms (basename, `assets/`, `res/assets/`, `tw/`, `1.0.173`),
  at offsets 0 and 2. No candidate yields `CWS` or `FWS`.
- Result: **not decrypted.** The time box is spent. Next steps are in the list
  above; the cheapest is to find the decrypt call site in the Alchemy binary
  (the function that writes to a `ByteArray` before `loadBytes`).

## Second attempt (2026-10-09): C core checked, decrypt not located

- `PlatformLoader.swf` (decompressed, 265,133 bytes) contains **no**
  `decodeFunction`, `RFPluginUtils`, `loadBytes` or `tg.swf` strings. Its C
  core's compiled function names (by file name in `cmodule/ccode`) are libc,
  MD5 (`FSM_MDByteArray`, `FSM_Md5_decode`), and keyboard/mouse routines
  (`vgl_*`). I checked names and strings, not a formal export table. So the C core is not the decryptor, and
  the earlier hypothesis that it patches `decodeFunction` is not supported.
- `EnLoader.as:85` calls `RFPluginUtils.decodeFunction(l)` on every blob. The
  default `de()` (`decompiled-main`) returns any blob whose first byte is below
  0x80 unchanged. `tg.swf` starts `08`, and the UI SWFs start `00`, so the stock
  path passes them through as-is.
- **Hypothesis (untested, could explain the open 99% stall in
  `docs/protocol.md`):** `tg.swf` reaches `Loader.loadBytes` still encrypted,
  fails there, and the loader stops at 99%. The original server may have
  served a different `tg.swf`. A cross-check needs a legitimate copy of the
  original `tg.swf`; none exists in `reference/` (only 4 SWFs are there, none
  from the game UI).
- The embedded `Platform__loc_1.bin` (EnLoader asset, 7,477 bytes, inside
  `Main.swf`) is not on disk, so it could not be checked.

## Status

Not decrypted. Next checks, in order: (1) recover the `Platform__loc_1.bin`
bytes from `res/Main.swf` with ffdec and check whether it is the only place a
real decode is registered; (2) test the stall hypothesis by loading `tg.swf`
through the projector with the bridge log, to see whether `loadBytes` fails.

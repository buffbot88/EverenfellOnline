# Original client boot chain (from FFDec decompilation, output/ffdec/)

All paths relative to the Apache webdir `TonNgoKhong/server/ESSamp/wwwroot/`.
Flashvars come from `Gamelogin.php` (uid/pid/t/seid `fu1304`/sport `8008`/ip/sign).

## 1. `res/Main.swf` (class `Platform`, Flex bootstrapper, 16 KB)

- `Platform()` reads `loaderInfo.loaderURL`, keeps the `?v=` cache-buster in
  `param`, prints progress into a `TextField` (`createTxt`).
- `init()` (on COMPLETE): `ExternalInterface.call("eval", ...completeCallBack...)`,
  adds `new Show(txt)`, then `setTimeout(t, 300)`.
- `t()`: `URLStream`-downloads `PlatformLoader.swf?v=1.0.173`.
- `uc()`: reads the bytes; **only if `length == Version.HASH (82921)`** does
  `Loader.loadBytes` run — else the `eee()` error screen
  ("加载文件失败，请清除浏览器缓存后重新进入游戏！").
  On-disk `PlatformLoader.swf` is exactly 82,921 bytes, so the gate passes.
- `lc()`: `addChild` the PlatformLoader content, then loads the **embedded**
  asset `Platform__loc_1` (`[Embed(source="/_assets/1_Platform__loc_1.bin")]`,
  the `dll("http://www.g.cn/dll.png")` URL is a decoy — the arg is ignored).
- `onComplete()`: builds bytes `[0,1,114]` → `readUTF()` = method name `"r"`,
  calls `content["r"](["assets/tg.swf?v=1.0.173"])`, wires COMPLETE → `done()`
  (removes the "Loading" text), IO_ERROR → `eee()`, PROGRESS → `dllprogress`
  (`"Loading N%"` — the 99% screen).

## 2. Embedded `1_Platform__loc_1.bin` (class `EnLoader`, 7,477 bytes)

- `r([url])` → `ld()` pops one URL and `URLStream`-downloads it, re-dispatching
  PROGRESS (the visible progress bar).
- `c()` (on COMPLETE): `readBytes` → **`RFPluginUtils.decodeFunction(bytes)`**
  → `Loader.loadBytes(decoded)` → next URL, else dispatch COMPLETE and
  `unloadAndStop()`. IO/SECURITY_ERROR → `l()` re-dispatch (→ `eee()` upstream).

## 3. `RFPluginUtils.decodeFunction` (the "decrypt")

- A settable `public static var`, defaulting to private `de()` — identical logic
  in Main.swf's and EnLoader's copies (Main.swf's wins: same
  `ApplicationDomain`, loaded first).
- `de()` decrypts **only blobs whose first byte is ≥ 0x80** (signed
  `readByte`, branch on `b >> 8`); anything else passes through **unchanged**.
  The loop copies bytes where `(b & 0xDD) != 0`, skipping 3 bytes after each,
  and recurses when it meets a byte with `(b & 0xCC) != 0`.
- `res/assets/tg.swf` starts `08 1F 86 EC` (not a SWF signature), so stock
  `de()` is a no-op for it (verified with a byte-exact Python port:
  output == input). A valid SWF never comes out at any offset.

## Consequence (HYPOTHESIS, not verified)

Verified: stock `de()` leaves `tg.swf` unchanged (byte-exact Python port), so
the shipped `decodeFunction` alone cannot yield a loadable SWF.

Not verified: that something at runtime replaces `decodeFunction` with the real
decrypt, or that Ruffle fails to run that step. The var is public and settable,
but no AS3 contains a patch step; if one exists it is inside the compiled-C
Alchemy core in `PlatformLoader.swf`, which is not statically recovered here.

Observed (bridge log, Ruffle 0.7.1 and 0.8.0 nightly): the login handshake
completes (INITKEY, UUID, login, 194-byte reply) and the client then sends no
further bytes. The cause of that silence is unknown.

## Sources

- `output/ffdec/decompiled-main/scripts/Platform.as` (+ `Version.as`,
  `Platform__loc_1.as`, `com/youbt/{asm,manager,utils}/*`)
- `output/ffdec/decompiled-r/scripts/EnLoader.as`
- `output/ffdec/pcode-{r,main}/scripts/com/youbt/utils/RFPluginUtils.pcode`
  (raw ABC, used because the `__asm(...)` marker calls are control-flow
  obfuscation; the AS3 reconstruction was verified against the pcode)
- `output/ffdec/decompiled-pl/scripts/` (PlatformLoader AS3 shell; the C core
  itself is Alchemy machine code, not statically recoverable)

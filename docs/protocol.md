# Game protocol notes (port 8008)

How the original client talks to the legacy server, and how the bridge fits
in. Every claim is labelled. Nothing here invents packets.

```
Ruffle (original Main.swf, unmodified)
  ↓  flash.net.Socket → matched by socketProxy host/port
Browser WebSocket (binary frames, websockify-compatible, no preamble)
  ↓  ws://127.0.0.1:8181
tools/bridge (byte-transparent forwarder, never parses game packets)
  ↓  raw TCP
Legacy game server 127.0.0.1:8008 (MINA NioSocketAcceptor, TcpNoDelay)
```

## Confirmed

- **Endpoint is flashvar-driven, not hardcoded.** `Gamelogin.php` passes
  `ip:'127.0.0.1', sport:'8008'` (plus `uid/t/sign/seid='fu1304'/pid='gmthai'`);
  `gamesession.php` + `client/src/flashvars.js` mirror this. Ruffle's
  `socketProxy` matches the host:port the SWF requests, so no SWF change is
  needed — `client/src/player.js` registers `127.0.0.1:8008` and
  `localhost:8008` → bridge URL (`?bridge=` overrides, `?nobridge=1` opts out).
- **Ruffle socket path is the documented websockify dialect.** Ruffle wiki
  ("How can I connect to a TCPSocket or XMLSocket from the web") prescribes
  `socketProxy: [{host, port, proxyUrl}]` against a websockify-style proxy:
  raw binary WS frames ↔ TCP bytes, no handshake. Our bridge implements that
  server side (also accepting legacy base64 text frames).
- **Relative asset loads need `<base href="/res/">`.** Main.swf resolves
  `PlatformLoader.swf?v=1.0.173` against the page URL (Ruffle behaviour), so
  without the base tag it fetched `/PlatformLoader.swf` (HTML fallback, 406
  B). With the tag (same trick as Gamelogin's `<base>`), the live chain is
  `/res/PlatformLoader.swf` → `/res/assets/tg.swf` → `/res/data/tw_config.xml`
  → `/res/config/tw_branchs/chn.dat` → `/res/assets/tw/lib.swf` (all 200).
  Default locale branch is **tw**.
- **Socket policy is served in-band by the game server.** Jar evidence:
  `NetListener` embeds `<allow-access-from domain="*" to-ports="8000-8889"/>`
  and both `AmfRequestDecoder` and `SafeServiceListener` answer
  `policy-file-request`. On the wire through Ruffle's proxy, **no policy
  request is sent** (Ruffle logs `Security.loadPolicyFile()` as an
  unimplemented stub) — the client goes straight to game bytes.
- **First client frame, captured live** (bridge LOG_PACKETS=1, fake server):
  `00 00 00 09 06 0f 49 4e 49 54 4b 45 59` — i.e. **4-byte big-endian length
  (9)** + AMF3 inline string `06 0F` + `"INITKEY"` (7 chars). So client→server
  framing is **u32be length prefix + payload**, consistent with the encoder
  using MINA `putInt` (present in `AmfResponseEncoder` strings).
- **Payloads are AMF3** (BlazeDS `Amf3Input` server-side; `06 0F` string
  header observed on the wire). **Stream-encrypted** via
  `com/kernel/encrypt/SimpleEncrypt(ticket, key)` with rolling indices
  (`ticketIndex/deTicketIndex/keyIndex/deKeyIndex`); per-session state via
  `initEncrypt(session)` + `ticket`. The SWF holds the matching cipher, so
  the bridge stays transparent and never decrypts.
- **Server reassembles fragments**: decoder keeps `remain_buf` across TCP
  reads (`AmfRequestDecoder` var names). Multiple frames per read are
  therefore legal; the bridge preserves chunk boundaries end to end and both
  directions were tested byte-identical (10/10 `node --test`).
- **Client retries a silent server**: with no server reply, the game opened
  a second TCP connection and re-sent INITKEY (~2 s later), then idled. No
  login packet follows until the server speaks.
- **Ruffle renders the loader without CJK fonts**: `Unknown device font
  "SimSun"` is logged — device Chinese text cannot display in Ruffle web
  (Latin/Noto Sans does). English translation additionally fixes rendering.

## Strongly inferred

- Server→client framing mirrors client→server (u32be + encrypted AMF3;
  `AmfResponseEncoder` uses `putInt` + allocate/flip/write). Unconfirmed:
  the fake server never got a reply to forward.
- Message routing is by AMF3 object content, not numeric opcodes: `NetIoHandler`
  dispatches deserialized objects with session attrs `ip_key/account_key/
  role_key`; no opcode table found in jar strings.
- `sign = md5(uid.'xianlingkey'.t)` (PHP) authenticates the web session; the
  socket `ticket` is likely issued after the socket login — exact link unknown.

## Unknown

- Login/world-entry packet fields, ticket issuance and key derivation (all
  inside encrypted `tg.swf` + server login handler).
- Server→client first bytes (need the real server).
- Whether Ruffle's `Socket` covers every API the game uses (only benign
  stubs seen so far: `URLStream` streaming, `Dictionary` weak keys,
  `Loader` timing, `DateTimeFormatter`, `unloadAndStop`).

## Confirmed — login handshake, end to end (2026-10-07)

The Python server (`server/py`) now drives the real client through login. Two
non-obvious facts, both found by disassembling the jar with `tools/javap.py`
and then confirmed against the live client:

- **Encryption is one-way: only client→server is enciphered.**
  `AmfResponseEncoder.encode()` does `IoBuffer.putInt(len)` + `put(bytes)`
  with no cipher call, and across the whole jar `com/kernel/encrypt/
  SimpleEncrypt` is referenced **only** by `AmfRequestDecoder` (nothing calls
  `encode()`). Consequence: the server's replies are **plaintext AMF3**.
  Encrypting them (our first implementation) made the client try to parse
  ciphertext and abort with `Error dispatching event "socketData":
  RustError("Error: Invalid object")`. Wire check: for session key
  `fcf9710a…`, the first response byte `0xf1` decrypts under
  `(b + 'N' - 'f') mod 256` to `0x09` — an AMF3 array marker — i.e. the
  *unencrypted* byte is the array marker, confirming the reply is cleartext.
- **`InOutput.success` slot 3 is a `java.util.TimeZone` object, not a
  string.** Bytecode: `[1, [serverStartTime.getTime(), currentTimeMillis(),
  this, TimeZone.getDefault(), isGmOpen, hefuTime], [0, 0], roleInfos]`.
  Sending a tz *name* produced
  `ReferenceError #1069: Property rawOffset not found on String at
  com.tian.net.socket::ServerInfoVO/decode()`. The fix is an AMF3 anonymous
  dynamic object (`0x0A 0x0B 0x01 …`) carrying `rawOffset` (plus `ID`,
  `displayName`, `dstSavings`, mirroring the Java bean).

Client-side class names recovered from those runtime errors (the SWF itself
is still encrypted): `com.tian.net.socket::ServerInfoVO`, `com.tian.module.
scene.exec::Conn` (`f_10001` handler), `com.youbt.net::SocketBase` (`onData`).

- **Each role is a positional `Object[8]`, not an object.** Recovered from
  `GetRoleOutput.roleInfo(UserRole)` and confirmed against the client:

  | idx | source | type on the wire |
  |---|---|---|
  | 0 | `getId()` | String (**not** int) |
  | 1 | `getName()` | String |
  | 2 | `getJob()` | String (**not** int) |
  | 3 | `getSex()` | Integer |
  | 4 | `getLevel()` | Integer |
  | 5 | — | always `null` |
  | 6 | `getFace()` | String |
  | 7 | `getCreateTime().getTime()` | Long (ms, >29-bit ⇒ travels as an AMF3 double) |

  `UserRoleServiceImpl.getRoles` builds `Object[]` of these via
  `anewarray java.lang.Object`, which is why the client does `as Array` per
  entry. The empty-roles case hides this: with `[]` the loop never runs, so
  an all-zero test suite passes. Adding one character surfaced it as
  `TypeError #1034: cannot convert Object@… to Array at …Conn/f_10001()`.
  After the fix the client consumes a login reply **containing a character**
  with no AS3 errors at all.

Verified exchange against the Python server (bridge `LOG_PACKETS=1`):

```
CLIENT->SERVER len=13  00 00 00 09 06 0f "INITKEY"
SERVER->CLIENT len=40  00 00 00 24 <uuid key>
CLIENT->SERVER len=80  <encrypted AMF3 login [10001, [uid,t,seid,bfc,sign,0,1]]>
SERVER->CLIENT len=124 09 15 01 06 0b "10001" 09 09 01 04 01 09 0d 01 05 <ms double> …
                       0a 0b 01 13 "rawOffset" 04 00 06 05 "ID" …
```

Unsigned clients get `[0, '16002']` (`InOutput.signError`) — also verified.
Invalid/failed sign leaves the client on its loading screen; no AS3 error.

## Open question — client stalls on its loading bar

The client renders its real splash (`Main.swf` → `PlatformLoader.swf` →
`assets/tg.swf` → `data/tw_config.xml` → `assets/tw/lib.swf`, all 200) and its
progress bar reaches ~99%, but it does not go on to request its UI SWFs
(`assets/tw/gameui.swf`, `createUI.swf`, …) even after a successful login.
Reaching the socket stage is also intermittent — some page loads never dial
`8008` at all. Not yet explained; candidates: a Ruffle stub the loader waits
on (`Security.loadPolicyFile()`, `flash.net.URLStream` streaming and
`Loader.load()` timing are all logged as stubs), or a message the client
expects after login that the original server pushed. The MPlayer.swf sidecar
(second Ruffle instance) was tried and made it worse — reverted.

## Next step for world entry

Boot the real stack (ESSamp Apache+MySQL, then `server.bat` under jre6),
open `player.html` with a logged-in session, and watch the bridge log: expect
`CLIENT->SERVER INITKEY`, then the server's first reply bytes — the first
genuinely unknown protocol data, to be captured with `LOG_PACKETS=1`.

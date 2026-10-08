# Project knowledge

## What this is

A **2014-era Chinese 2D browser MMO server distribution** ("DNTG", Vietnamese client titled *Đại Náo Thiên Không* / folder name `TonNgoKhong` = Sun Wukong). It is a **deployment package, not a source repo**:

- No `.java` sources, no `pom.xml`/`build.xml`, no `package.json`, **not a git repository**.
- Game logic ships compiled inside `TonNgoKhong/server/dntg_start.jar`
  (Main-Class `com.xianling.start.XianlingStart`, Ant-built on JDK 1.6; Spring 3.0.2 + iBatis 2.3.4 + c3p0 + MINA + Log4j, packages under `com.xianling.*` / `com.kernel.*`).
- Everything is **Windows-only**: bundled `jre6` (DLLs), `.bat` launcher, `.lnk` shortcuts, and the ESSamp all-in-one web stack.

```
TonNgoKhong/
├── [0] Java.lnk  [1] ESSamp.lnk  [2] Server.lnk   # intended startup order
├── tools/                  java.exe, jre.7z (portable JRE for the host)
└── server/                 ← the game server (see below)
```

## Where things live (`TonNgoKhong/server/`)

| Path | Purpose |
|---|---|
| `server.bat` | Launcher: bundled `jre6\bin\java`, CMS GC, `-Xms256m -Xmx1024m -XX:PermSize=256M`, `-jar dntg_start.jar` |
| `dntg_start.jar` / `dntg_stop.jar` | Start / stop the game server |
| `pid` | Last recorded PID (stale, from 2014 — don't trust it) |
| `lib/` | Third-party jars (referenced by the jar manifest `Class-Path`) |
| `config/` | **All editable runtime config** (see below) |
| `data/` | Runtime-written data (`msg_statistic`, `shenmizhuanpan`) |
| `logs/` | `error/error.log`, `minute/`, `gc.log` |
| `server/` | A nested near-duplicate copy of jar + config + jre6; **no `server.bat`**, purpose unclear — assume unused |
| `jre6/` | Bundled Windows JRE 6 |
| `ESSamp/` | Bundled Apache + PHP5 + MySQL4/5 + phpMyAdmin stack (`ESSamp.exe`) |
| `ESSamp/wwwroot/` | PHP + Flash client (`MainLoader.swf`, `ClientRes/`, login/pay endpoints) |

### Key config files (all `key = value`, CRLF, some comments are `\uXXXX` escapes)

- `config/data/jdbc.properties` — MySQL `jdbc:mysql://127.0.0.1:3306/dntg`, `root` / `123456`
- `config/net-io.properties` — **client port `8008`**
- `config/node-config.xml` — node topology: `public` 9960, `swap` 9980, `gs1` 9961 (webservice 9990), stages `0..50`
- `config/run-info.properties` — node role switches (`current_node_name=gs1`, `is_gs`, `is_public`, `is_client_io`, `is_swap`, `use_cache`)
- `config/server-info.properties` — `server_id=fu0`, `server_language=zh`
- `config/localization.properties` — locale/economy tuning; says `server_language=th`, `server_country=TW`, `ybodds=2` (**conflicts with `server-info.properties`** — check both when changing locale)
- `config/spring/` — `applicationContext.xml` (component-scans `com.xianling.*`), `ibatis/`, `property/property.xml` (loads `config/data/jdbc.properties`, `config/stage/csl-stage.properties`, `config/gameconfig-info.properties` from the classpath), `init/`, `webservice/`
- `config/easyexecutor/*.xml` — thread pools for io / stage / bus / public
- `config/game/sys_config/*.dat|*.jat` and `config/game/map_config/<stage>/{map.dat,monster.mm,path.mm}` — **binary game data; do not hand-edit**
- `config/bus/` — plain-text name checks / sensitive-word lists per locale (`bs.txt`, `checkname.txt`, `bus-code_*.properties`)
- `config/gameconfig-info.properties` — points at `http://127.0.0.1/gameconfig/` (the PHP site)
- `config/version.properties` — `version=20140224_213740`

### Web side (`ESSamp/`)

- `essamp.ini` — **hardcoded `dir=D:\TonNgoKhong\server\ESSamp`**, `webport=80`, `mysqlport=3306`, `mysqlopt=256M`
- `MySQL5/data/` — databases `dntg` (game) and `caonima` (website), plus `test`
- `wwwroot/configuration/config.inc.php` — web DB creds: `root` / `123456`, `$database='caonima'`, `$database2='dntg'`, `$kg=1` (server open flag), `$chongzhi` = recharge callback URL
- Entry points: `index.php`, `login.php`, `login2.php`, `Gamelogin.php`, `pay.php`; duplicated site under `wwwroot/wangzhan/`
- Uses the **removed `mysql_*` PHP API** → only runs on the bundled PHP 5; won't work on PHP 7+

## Commands

There is **no install/dev/test/lint/build** — no build tooling or test suite exists.

```bat
:: 1) web stack (Apache on :80, MySQL on :3306)
TonNgoKhong\server\ESSamp\ESSamp.exe        :: start Apache + MySQL from its UI

:: 2) game server — MUST be run with CWD = TonNgoKhong\server (log paths are relative)
cd TonNgoKhong\server
server.bat                                  :: start

:: stop
jre6\bin\java -jar dntg_stop.jar
```

To verify a running server: `logs/error/error.log`, `logs/minute/minute`, `logs/gc.log`; client connects to `127.0.0.1:8008`.

## Gotchas / constraints

- **No source, no VCS, no tests.** Changes are config edits, PHP edits, or jar patching only.
- Repo is huge and mostly binary → directory scans and `du` frequently **time out**; search with narrow `find -maxdepth` / `code_search` patterns instead.
- **Java version matters**: `-XX:+UseParNewGC -XX:MaxPermSize` are Java 6–8 flags; modern JDKs reject them. Use the bundled `jre6` (or Java ≤ 8), and it's a Windows build.
- `server.bat` classpath includes `lib/Jetty/*` and `extensions/__lib__/*`, **neither directory exists** in this copy (harmless, but don't be surprised).
- Log paths in `log4j.properties` are relative (`logs/...`) — starting the jar from another cwd scatters logs.
- Plaintext credentials in two places (`config/data/jdbc.properties`, `wwwroot/configuration/config.inc.php`), both `root`/`123456`; everything assumes `127.0.0.1`.
- Absolute Windows path in `ESSamp/essamp.ini` must be updated if the tree moves.
- Text files are **CRLF**; keep that when editing or the Windows tooling may misbehave.
- Stale runtime state exists: `pid`, `logs/*` (2014), `data/*`.

## Version control (git, `main` branch)

Curated commits only — the 2.2 GB tree is mostly binaries. `.gitignore`
excludes: jars/DLLs/EXEs, `jre6/`, `tools/`, the ESSamp stack binaries,
`wwwroot/res/` + `ClientRes/` + `wangzhan/` (1.7 GB Flash assets),
binary game tables (`*.dat/*.jat/*.mm`), all `logs/` dirs (including stray
dumps nested under config), runtime `data/`, `*.log`, build output and
`node_modules/`. `.gitattributes` pins `TonNgoKhong/**` to `-text` so the
legacy CRLF bytes are stored exactly; `client/**` uses normal handling.
Committed: `knowledge.md`, text configs, PHP web code, docs, `client/`.

## Python game server (`server/py/`) — replaces Java + ESSamp + MySQL

Stdlib Python + SQLite (Pillow only for the captcha image). Accounts,
sessions and characters persist in `data/mko.db`; sessions are stored in the
DB so a restart keeps browser logins valid.

```sh
cd server/py
python3 server.py --db data/mko.db --game 127.0.0.1:8008 --web 127.0.0.1:8080
```

It reproduces the legacy PHP HTTP contract (`AjaxRequest/AccountHandler.php`
login/register, `VerifyCode.php`, `gamesession.php`) **and** the game socket
on 8008 (INITKEY handshake, `SimpleEncrypt`, AMF3 codec, command 10001).
Characters are stored (unique per account+server) and returned in the login
reply; `--add-char ACCOUNT:NAME` seeds one, since the client's createRole
command (`10002`) shape is still unrecovered.
Full runbook: `server/py/README.md`; protocol evidence: `docs/protocol.md`.

Two protocol facts that cost real debugging (both proven from bytecode):

- **Only client→server is enciphered**; server replies are plaintext AMF3
  (`AmfResponseEncoder` never encrypts; nothing calls `SimpleEncrypt.encode`).
- **The login result's TimeZone slot is an object** with `rawOffset`
  (`InOutput.success` passes `TimeZone.getDefault()`); a String there raises
  AS3 `Error #1069` in `ServerInfoVO.decode()`.
- **Each role is a positional `Object[8]`** — `[id:String, name, job:String,
  sex, level, null, face, createTimeMs:Long]` per `GetRoleOutput.roleInfo`.
  Sending objects instead raises AS3 `#1034 cannot convert Object to Array`
  inside `Conn/f_10001()`. Note the empty-roles case masks this bug entirely.

A lesson worth keeping: two real protocol bugs (the TimeZone String and the
role Object-vs-Array) were invisible until a character existed and until the
reply was actually fed to the client. Tests over an empty data set passed
both times.

## New HTML5 client (`client/` — Phaser 3 + Vite, milestone 1)

Replaces the Flash `Main.swf` client (Flash Player is EOL). Backend contract:

- `POST /api/AjaxRequest/AccountHandler.php` `{Action:'Login', uName, uPas}`
  → text contains `登陆成功` on success (PHP session cookie set).
  Register (`Action:'Register'` + `sCode`) needs the captcha at
  `configuration/VerifyCode.php` (4 chars, lowercased into session).
- `GET /api/gamesession.php` (new shim, mirrors `Gamelogin.php` flashvars)
  → JSON `{uid, t, sign, seid:'fu1304', sport:8008, ip:'127.0.0.1',
  pid:'gmthai'}`, 401 when not logged in. `sign=md5(uid.'xianlingkey'.t)`.
- Dev proxy `vite.config.js`: `/api/*` → `http://127.0.0.1:80`, so no CORS
  setup and the session cookie stays same-origin.
- Run: ESSamp (Apache :80 + MySQL :3306) must be up, then
  `cd client && npm install && npm run dev` → http://localhost:5173.
- `src/net/GameSocket.js` is a stub: browsers can't open raw TCP to the
  8008 socket, so traffic goes through the WebSocket bridge below (built).

## Milestone 2 — bridge + Python server (DONE)

- `tools/bridge/` — byte-transparent WebSocket↔TCP forwarder (Ruffle
  `socketProxy` → `ws://127.0.0.1:8181` → `8008`). Never parses packets.
- `server/py/` — Python + SQLite replacement for the Java server and the
  PHP/MySQL website. The real Flash client completes the full login
  handshake against it (INITKEY → key exchange → encrypted login → AMF3
  result) with **no AS3 errors**.
- Tooling added: `tools/javap.py` (minimal JVM disassembler — used to recover
  the cipher, framing and login output shapes from `dntg_start.jar`).

**Current wall:** the client renders its real splash and the progress bar
reaches ~99% but it never loads its UI SWFs after login, so the visual login
screen is not reached yet. Reaching the socket stage is intermittent. See
`docs/protocol.md` → "Open question".

## Strategy pivot: run the original Flash client under Ruffle (2026-10)

Rewriting the game in Phaser was shelved — the original `Main.swf` boots
cleanly under **Ruffle 0.7.1 (selfhosted)** with only benign stubs
(`NativeMenuItem`, `Capabilities.isDebugger`, `Times New Roman` device font,
`URLStream` streaming). So `client/` now has two pages (both built by Vite):

- `index.html` — the Phaser login scaffold (milestone 1, still works).
- `player.html` + `src/player.js` — boots the **unmodified** `Main.swf`
  with the real `Gamelogin.php` flashvars (via `src/flashvars.js` +
  `/api/gamesession.php`, demo-session fallback when PHP is offline).

Ruffle integration notes (all verified 2026-10-07):

- `@ruffle-rs/ruffle` is an npm dependency, but its selfhosted build resolves
  core/wasm relative to its `<script>` tag — it must NOT be Vite-bundled.
  `client/scripts/copy-ruffle.js` (auto-run via `predev`/`prebuild`) stages
  `ruffle.js` + core + wasm into `client/public/ruffle/` (gitignored, ~30MB);
  `player.html` loads it with a plain `<script src="/ruffle/ruffle.js">` tag.
- `/res/*` is served straight from the legacy tree in dev by middleware in
  `client/vite.config.js` (`LEGACY_RES`, traversal-checked, SWF MIME set) —
  the 1.7 GB stays out of git and out of the bundle.
- Verified live: `player.html` 200, `ruffle.js` 200, `Main.swf` 200
  (`application/x-shockwave-flash`), Ruffle WASM init + `Loading SWF file
  /res/Main.swf`, active 766×751 canvas, status `game loaded`. The one 500
  is the expected `/api/gamesession.php` proxy error (no Apache here) →
  the demo-session fallback engaged as designed.
- World-entry networking is bridged, not reimplemented: `tools/bridge/`
  (`bridge.js`, Node + `ws`) forwards Ruffle's `socketProxy` WebSocket
  (default `ws://127.0.0.1:8181`, `?bridge=` overrides, `?nobridge=1` opts
  out) to raw TCP `127.0.0.1:8008`, byte-transparent both directions.
  `player.html` also carries `<base href="/res/">` (same trick as
  `Gamelogin.php`) so the SWF's relative loads hit `/res/` instead of `/`.
  Verified live against a fake game server: full chain Ruffle → bridge →
  TCP:8008, client first frame captured (`00 00 00 09 06 0F "INITKEY"` =
  u32be length + AMF3 string). Full findings in `docs/protocol.md`.
  Ruffle decrypts the asset packs itself at runtime (see cipher note below),
  so no asset pipeline is needed just to *run* the game.

## Asset-pack cipher (what we learned without breaking it)

`res/assets/*.swf` (+ `tw/`, `zhcn/`, `kokr/` locale packs) are encrypted
(high entropy ~7.95, bad magic). `tools/abc_strings.py` now extracts
PlatformLoader's ABC pool (1277 strings, see `.survey/plat_abc.txt`): it
contains an Adobe Alchemy/CrossBridge module (`cmodule.ccode`,
`FSM_Md5_decode`, `___xordi3`, `ByteArrayForString`) — i.e. an **MD5-based
decoder compiled from C**, plus raw `Socket`/`sockConnect`. So the pack
cipher is MD5-derived, key derivation still unknown — but irrelevant for
running the game, since the real decoder executes inside Ruffle.
`tools/abc_strings.py` fixes that unblocked this: DoABC tags are 72/82
(tag 84 is DefineMorphShape2 — parsing it as ABC caused the `unknown
multiname kind` crash), plus fault-tolerant multiname walking.

## English translation plan (text + images)

| Source | Scope (measured) | Tool | Status |
|---|---|---|---|
| `res/java/zhcn/*.dat|*.jat` (AMF3 tables: quests, items, skills, dialogue) | 246 files, 16,918 occurrences, **7,520 unique** | `tools/dat_strings.py` → `.survey/i18n_zh.json` (1.2 MB TM with file+offset per string) | extracted, awaiting translation |
| PHP web (`login.php`, `Register.php`, `AccountHandler.php`, …) | 35 files contain CJK | hand-edit (small) | scoped |
| Loose images (`res/f/`, `res/global/`) | 524 files, **58 likely-text** (event banners, vip/shouchong strips, `yd_*` guide icons), 237 to review | `tools/image_inventory.py` → `.survey/images.json` | triaged |
| SWF code pools (`Main`/`PlatformLoader` ABC) | ~0 CJK — UI text comes from tables/packs, not code | — | no work needed |
| Encrypted SWF packs (baked UI text + bitmaps) | ~193 files | phase 2: solve MD5 key derivation → decrypt → extract → repack, or replace art at the `/res` serving layer | blocked on cipher |

Delivery sketch: translate the TM (MT + human review), then build English
locale tables with an AMF3-aware rewriter (length-prefixed strings, so the
byte-offset TM alone isn't enough for write-back) served via the `/res`
layer; PHP pages edited directly; loose images redrawn into an overlay dir.
`tw/` (95 files) and `kokr/` (68) prove the engine is locale-parameterized —
there is just no `us/`/`en/` asset set yet.

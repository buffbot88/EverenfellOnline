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
  8008 MINA socket, so milestone 2 needs a WebSocket→TCP bridge plus packet
  protocol reverse-engineering (see `client/README.md`).

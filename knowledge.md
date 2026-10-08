# Project knowledge

## What this is

A preservation/revival project for **MonkeyKingOnline (DNTG / 大闹天空, "TonNgoKhong")**, a 2014-era Chinese 2D browser MMO. Goal: keep the original Flash client running (Flash is EOL) and replace the Windows-only Java server + PHP/MySQL stack with a portable Python server.

Layout (git repo, branch `main`, curated commits only):

| Path | Purpose |
|---|---|
| `client/` | Vite web client. `player.html` runs the **original `Main.swf` under Ruffle** (primary). `index.html` is a Phaser login scaffold (reference of the PHP contract). |
| `Server-v1/` | Python (stdlib + SQLite, Pillow for captcha) replacement for the game server + web API, with its SQLite DB at `Server-v1/data/mko.db`. `server.py` entry; `game/` protocol/AMF3/cipher; `auth.py`, `db.py`, `web.py`; `tests/`. |
| `tools/bridge/` | Node WebSocket→TCP forwarder (Ruffle `socketProxy` → `127.0.0.1:8008`). Byte-transparent. |
| `tools/*.py` | Reverse-engineering helpers (`javap.py` JVM disassembler, `decode-tap.py`, `tcp-tap.py`, `abc_strings.py`, `dat_strings.py`, `image_inventory.py`, `parse_flashvars.py`, `projector-client.py`). |
| `docs/` | `protocol.md` (wire evidence), `java-python-parity-audit.md` (parity status and security risks). |
| `TonNgoKhong/` | Legacy game distribution (Java jar, bundled JRE6, ESSamp Apache/PHP/MySQL). Not in git-tracked source; large binaries. Gitignored assets (`res/`, `*.dat`, logs, jars). |
| `output/` | Generated artifacts (e.g. `output/ruffle-src/`). |
| `.agents/types/` | Agent definition/tool typings. |

## Commands

**Python server** (run from `Server-v1`):
```sh
python3 server.py --db data/mko.db --game 127.0.0.1:8008 --web 127.0.0.1:8080
python3 server.py --db data/mko.db --add-char ACCOUNT:NAME   # seed a character, then exit
python3 -m unittest discover -s tests                        # tests (26, all pass)
```

**Web client** (run from `client/`):
```sh
npm install
npm run dev      # predev copies Ruffle to public/ruffle/; open http://localhost:5173/player.html
npm run build    # prebuild copies Ruffle; outputs dist/
npm run preview
```

**WebSocket bridge** (run from `tools/bridge/`):
```sh
npm install
npm start        # ws://127.0.0.1:8181 -> 127.0.0.1:8008
npm test         # node --test test/bridge.test.js
```

No lint or typecheck tooling is configured.

Login needs the PHP/web API: either the legacy ESSamp stack (Apache :80, MySQL :3306) or the Python server with `API_TARGET=http://127.0.0.1:8080`. Without a backend, `player.html` still boots using a demo-session fallback.

## Architecture / data flow

```
browser (player.html, Ruffle)
 ├─ /res/*            → dev middleware in client/vite.config.js serves the legacy
 │                      res tree live (TonNgoKhong/server/ESSamp/wwwroot/res)
 ├─ /api/*            → Vite proxy → Apache :80 (legacy) or API_TARGET (Python web API)
 └─ socketProxy ws    → tools/bridge → TCP 127.0.0.1:8008 (Python game server)
```

Game socket protocol (see `docs/protocol.md`):
1. client → `u32be(len) + AMF3 "INITKEY"`; server → plaintext key.
2. client → **encrypted** AMF3 command frames (`SimpleEncrypt`).
3. server → **plaintext** AMF3 replies (server never encrypts).

Implemented: login `10001`, enter-world `10003`, map change `20000`, role settings `13000`, scene entry `21000` (map 5 only). `10002` (createRole) is unimplemented; use `--add-char`.

## Conventions and gotchas

- **Protocol bugs hide in empty data.** Two real bugs (login TimeZone must be an object with `rawOffset`; each role is a positional `Object[8]`, not a keyed object) only surfaced once a character existed. Test with seeded data and feed replies to the real client.
- Auth sign is `md5(uid + 'xianlingkey' + t)`, a legacy scheme that is forgeable and replayable. Do not expose the server to the internet (see `docs/java-python-parity-audit.md`).
- Passwords in the Python server use PBKDF2; the legacy stack stores plaintext and unsanitized SQL. Do not reintroduce either.
- The Java game server is still the behavioral oracle; port subsystems incrementally and compare packet sequences.
- Ruffle must NOT be Vite-bundled. It resolves core/wasm relative to its `<script>` tag, so it is copied to `public/ruffle/` (gitignored).
- `/res/*` is never copied into the repo or bundle; keep the 1.7 GB legacy tree out of git.
- Legacy text files are **CRLF** and `.gitattributes` marks `TonNgoKhong/**` as `-text`; preserve bytes when editing there.
- `TonNgoKhong/server/essamp.ini` hardcodes an absolute Windows path; update it if the tree moves.
- Binary game tables (`*.dat`, `*.jat`, `*.mm`) must not be hand-edited.
- Runtime state (`logs/`, `data/`, `pid`, `Server-v1/server.log`, `*.pid`) is not source; don't commit it.
- Current wall: the Flash client renders the splash and reaches ~99% load, but does not yet get to the visual login screen. Socket-stage reachability is intermittent. See `docs/protocol.md` ("Open question").
- Translation (Chinese → English) is scoped but not done; the Ruffle renderer cannot draw SimSun, so text shows as bitmap or fails.
- Project rules in `VOWS.md`: ask before consequential decisions, run tests before declaring changes done, keep docstrings to 1–2 sentences, and release only after tests pass.

# Project knowledge

## What this is

A preservation/revival project for **MonkeyKingOnline (DNTG / 大闹天空, "TonNgoKhong")**, a 2014-era Chinese 2D MMO. Goal: keep the original Flash client running (Flash is EOL) and replace the Windows-only Java server + PHP/MySQL stack with a portable Python server. The end goal is a **downloadable desktop client**.

## Current state (read first)

- **Target client:** the original Flash client in the **Adobe Flash Player projector** (Flash 32.0.0.363) at `MKO_Client/flash-projector/flashplayer363.exe` (the path `tools/projector-client.py` uses). Native sockets go straight to the game server on `127.0.0.1:8008`, with no bridge.
- **`client/` (Vite web client) is not in this checkout.** Do not build workflows around it. The Ruffle/bridge path under `tools/bridge/` is the only web-side piece that remains.
- **Projector login (settled).** With no positional arguments, `tools/projector-client.py` reads `<username>/<password>` from `MKO_Client/config.json` (gitignored), calls the Python API for a gamesession, and passes only `uid/t/sign/seid/sport/ip` in flashvars. The password never enters a URL. Point it at the new stack with `--api-base http://127.0.0.1:8080 --movie-base http://127.0.0.1:8081/res` (the asset host on 8081 is `python -m http.server` rooted at `MKO_Client/Assets/`; port 80 also serves `/res` via `Alias`, but only 8081's docroot mirrors `gameconfig/`, which the client fetches relative to the movie URL — without that mirror every gameconfig request 404s).
- **Open blocker:** the client reaches ~99% load but has not yet shown the visual login screen. Socket reachability is intermittent (see `docs/protocol.md`, "Open question").
- **Client SWFs stay unmodified.** The stock files work with the Java stack, so do not patch them. Encrypted UI SWF decryption is unsolved; see [docs/swf-encryption-notes.md](docs/swf-encryption-notes.md) (session 2026-10-18).

## Layout

| Path | Purpose |
|---|---|
| `Server-v1/` | Python (stdlib + SQLite, Pillow for captcha only) replacement for the game server and web API. `server.py` entry; `game/` (protocol, AMF3, cipher, config); `auth.py`, `db.py`, `web.py`; `tests/`; `data/mko.db` (runtime, not source). |
| `tools/projector-client.py` | Logs in and launches the projector with the signed flashvars. |
| `tools/parse_flashvars.py` | Extracts flashvars from a saved `Gamelogin.php` page. |
| `tools/bridge/` | Node WebSocket→TCP forwarder (`bridge.js`). Byte-transparent. Not needed for the projector. |
| `tools/migrate_mysql_to_sqlite.py` | Copies the legacy MySQL rows the server needs into SQLite, scoped to named accounts. Read-only on MySQL. See `docs/mysql-to-sqlite-migration.md`. |
| `tools/*.py` | Reverse-engineering helpers (`javap.py`, `decode-tap.py`, `tcp-tap.py`, `abc_strings.py`, `dat_strings.py`, `image_inventory.py`, `swf_survey.py`, `game_data_survey.py`, `jar_inventory.py`, `record-session.py`, `login-gui.py`, `oracle-diff.py`). |
| `docs/` | `protocol.md` (wire evidence), `boot-chain.md` (original client boot sequence), `java-command-map.md` (command id → Java class), `java-python-parity-audit.md` (parity status and security risks), `mysql-to-sqlite-migration.md` (legacy data mapping), `game-data-inventory.md`. |
| `reference/TonNgoKhong/` | Legacy game distribution (Java jar, bundled JRE, ESSamp Apache/PHP/MySQL). Large binaries; `reference/` is versioned in git. |
| `reference/NEW-STACK-BOOT.md`, `OLD-STACK-BOOT.md` | Boot notes for the new and legacy stacks. |
| `skills/` | Agent skills: `brain-*` memory skills plus vendored `ui-ux-pro-max` (upstream `.claude/skills/ui-ux-pro-max`, flagship only). |
| `agents.json` | Skill/agent registry: paths, when-to-use, and the co-use rule (brain context first, then the ui-ux skill for visual work). |
| `output/` | Generated artifacts and runtime logs/pid files (surveys, inventories, migration report, `desktop-client/`). The projector executable is not here; it lives in `MKO_Client/`. |

## Commands

**Python server** (run from `Server-v1/`):
```sh
python3 server.py --db data/mko.db --game 127.0.0.1:8008 --web 127.0.0.1:8080
python3 server.py --db data/mko.db --add-char ACCOUNT:NAME   # seed a character, then exit
python3 -m unittest discover -s tests                        # server tests (1690, all pass)
```

**Tools tests** (from `tools/`): `python3 -m unittest discover -s tests` (44 tests).

**Legacy data migration** (from the repo root; MySQL must be running, it is only read):
```sh
python3 tools/migrate_mysql_to_sqlite.py --dry-run      # counts only
python3 tools/migrate_mysql_to_sqlite.py --users stress # migrate one account
```

**Projector launch** (from the repo root; needs the Python server running). Without `--api-base` the script targets the legacy Apache stack on port 80, so pass the Python API explicitly:
```sh
python3 tools/projector-client.py <user> <password> --api-base http://127.0.0.1:8080 --dry-run   # prints the movie URL, does not launch
```
The projector's real login path is still open (see Current state).

**WebSocket bridge** (from `tools/bridge/`): `npm install`, `npm start` (ws `127.0.0.1:8181` → TCP `8008`), `npm test` (`node --test test/bridge.test.js`).

No lint or typecheck tooling is configured. Setup beyond the Python 3 standard library is not needed (Pillow only for captcha).

## Architecture / data flow

```
Flash projector (flashplayer363.exe) running Main.swf
 ├─ /res/*            → legacy res tree (reference/TonNgoKhong/server/ESSamp/wwwroot/res), served locally
 ├─ HTTP account API  → Server-v1 web API on 127.0.0.1:8080
 └─ game socket       → Server-v1 TCP on 127.0.0.1:8008 (native, no bridge)
```

Original boot chain: `docs/boot-chain.md`. Game socket protocol: `docs/protocol.md`.
1. client → `u32be(len) + AMF3 "INITKEY"`; server → plaintext key.
2. client → **encrypted** AMF3 command frames (`SimpleEncrypt`).
3. server → **plaintext** AMF3 replies (server never encrypts).

Implemented: login `10001`, createRole `10002`, enter-world `10003`, map change `20000`, role settings `13000`, scene entry `21000` (map 5 only), plus bag/equip/vip/mall/skill, mounts, pets (partial), companions, dungeons (story/clan/guild), party/team, guild, booth, friends, marriage and more — 240 command IDs with tests in v1.5. Every command id maps to a Java class in `docs/java-command-map.md`; per-family parity status lives in `Server-v1/docs/*-ledger.md` and `Server-v1/docs/command-census.md`.

Role state lives in a `role_stage` table mirroring the legacy MySQL table, joined into `list_roles` so `10003`/`20000` report the migrated map, coordinates and HP/MP.

## Conventions and gotchas

- **Protocol bugs hide in empty data.** Two real bugs (login TimeZone must be an object with `rawOffset`; each role is a positional `Object[8]`, not a keyed object) only surfaced once a character existed. Test with seeded data and feed replies to the real client.
- Auth sign is HMAC-SHA256 over `uid|t` with a server secret (`MKO_SIGN_SECRET`, else per-process random) and a 300s freshness window; the legacy `md5(uid + 'xianlingkey' + t)` is rejected. Do not expose the server to the internet (see `docs/java-python-parity-audit.md`).
- Passwords in the Python server use PBKDF2; the legacy stack stores plaintext and unsanitized SQL. Do not reintroduce either.
- The Java game server is still the behavioral oracle; port subsystems incrementally and compare packet sequences.
- `reference/TonNgoKhong/server/ESSamp/essamp.ini` hardcodes an absolute Windows path; update it if the tree moves.
- Legacy text files are **CRLF**. `.gitattributes` marks `TonNgoKhong/**` as `-text`, but the tree now lives at `reference/TonNgoKhong/`, so that rule no longer matches. Preserve bytes when editing legacy files.
- Binary game tables (`*.dat`, `*.jat`, `*.mm`) must not be hand-edited.
- Runtime state (`logs/`, `data/`, `*.pid`, `*.log`, `*.db`) is not source; don't commit it. `.gitignore` covers most of it, but some `output/*.pid` and log files are present in the checkout.
- Only the accounts named with `--users` are migrated; the legacy `caonima.account` table holds 6,388 obsolete web registrations that must stay behind. The bundled MySQL client is 5.1 and needs `--default-character-set=utf8`, or CJK text silently becomes `?`.
- Translation (Chinese → English) is scoped but not done. The Ruffle renderer cannot draw SimSun, so text shows as bitmap or fails.

## Project rules

`VOWS.md` governs development: ask before consequential decisions, get approval for a build plan before implementing, run tests before declaring changes done, keep docstrings to 1–2 sentences, and release only after tests pass.

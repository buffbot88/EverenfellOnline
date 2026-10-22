# MonkeyKingOnline Python Server (DNTG / 大闹天空)

A portable **Python replacement for the Windows-only Java game server +
PHP/MySQL stack** behind MonkeyKingOnline, a 2014-era 2D MMO. It serves the
original Flash client's account HTTP API and game socket from one process,
using only the Python standard library plus Pillow (captcha image) —
accounts, sessions and characters persist in **SQLite**.

This is a preservation project: every reply shape and error code is ported
from the legacy server's bytecode and golden-tested (`Server-v1/tests/`,
1083 tests). v1.4 routes 164 command IDs with tests (153 persisted to
SQLite) plus 71 server-push IDs.

## Quickstart

Requires Python 3.10+ and Pillow (`pip install pillow`) for captcha only.

```sh
cd Server-v1
python3 server.py --db data/mko.db --game 127.0.0.1:8008 --web 127.0.0.1:8080
python3 -m unittest discover -s tests   # server tests, all pass
```

| Flag | Default | Meaning |
|---|---|---|
| `--db` | `data/mko.db` | SQLite file (accounts, sessions, characters) |
| `--game` | `127.0.0.1:8008` | game TCP listener (the port the Flash client dials) |
| `--web` | `127.0.0.1:8080` | HTTP account API |
| `--config-dir` | (legacy tree) | game config tables from your own install (see below) |
| `--captcha` | off | require the captcha on register (off so scripts can register) |
| `--add-char ACCOUNT:NAME` | — | create a character, then exit |
| `--server-id` | `fu1304` | server id characters are scoped to |

## Config data (your own install)

Map/monster/goods/skill tables (`*.jat`/`*.mm`) belong to the original game
distribution and are **not** shipped here. Start the server with
`--config-dir <your-install>/server/config/game` to enable them. Without it
the server still boots — each missing table is logged and the commands that
need it stay silent or empty. Nothing phones home; only local files are read.

## Protocol

```text
Flash client running Main.swf
 ├─ HTTP account API → Server-v1 web API on 127.0.0.1:8080
 └─ game socket     → Server-v1 TCP on 127.0.0.1:8008
```

1. client → `u32be(len) + AMF3 "INITKEY"`; server → plaintext key.
2. client → **encrypted** AMF3 command frames (`SimpleEncrypt`).
3. server → **plaintext** AMF3 replies (the server never encrypts).

Details per family live in `Server-v1/README.md`; release history in
`CHANGELOG.md`.

## Rules & security

- Auth sign is HMAC-SHA256 (`MKO_SIGN_SECRET`, 300s window); legacy MD5 is
  rejected. Rate limits cover web logins and game frames. The server binds
  loopback by default — do not expose it to the internet without TLS,
  session expiry and an origin check on web POSTs in front of it.
- Passwords are PBKDF2; the legacy stack's plaintext must not return.
- License: Apache-2.0 (`LICENSE`).

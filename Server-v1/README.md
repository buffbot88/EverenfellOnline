# Python game server (`Server-v1`)

Drop-in replacement for the legacy **Java game server + ESSamp Apache/PHP +
MySQL** stack, using only the Python standard library plus Pillow (captcha
image) — accounts, sessions and characters persist in **SQLite**.

```
python server.py [--db data/mko.db] [--game 127.0.0.1:8008]
                 [--web 127.0.0.1:8080] [--captcha] [--debug]
```

| Flag | Default | Meaning |
|---|---|---|
| `--db` | `data/mko.db` | SQLite file (accounts, sessions, characters) |
| `--game` | `127.0.0.1:8008` | game TCP listener (the port the Flash client dials) |
| `--web` | `127.0.0.1:8080` | HTTP account API (point the client's `API_TARGET` here) |
| `--captcha` | off | require the captcha on register (off so scripts can register) |
| `--debug` | off | DEBUG-level logging |
| `--add-char ACCOUNT:NAME` | — | create a character, then exit |
| `--server-id` | `fu1304` | server id characters are scoped to |
| `--config-dir` | `../reference/.../config/game` | legacy game config tables (see below) |

### Config data

Game data tables (maps, monsters, goods, skills: `*.jat`/`*.mm`) ship with
the original game distribution and are **not** included here. Point
`--config-dir` at your own copy's `server/config/game` tree to enable
them. Without it the server still boots — every table load is guarded and
logs what is missing — but config-driven commands stay silent or empty
(no maps, no goods, no skill data). Nothing phones home; the server only
reads local files.

### Characters

Characters live in the `characters` table, scoped by `(account, server_id,
name)` — the name is unique per account per server. Seed one and it shows up
in the command-10001 reply as an AMF3 object:

```sh
python3 server.py --db data/mko.db --add-char wukong:SunWukong
# created character id=1 name=SunWukong account=wukong server=fu1304
```

## HTTP API — same contract as the legacy PHP

| Endpoint | Behaviour |
|---|---|
| `POST /AjaxRequest/AccountHandler.php` `Action=Login` | `登陆成功` + `mko_session` cookie, or `用户名或者密码错误` |
| `POST ...` `Action=Register` (`uName`,`uPas`,`sCode`) | `注册成功` + session cookie (auto-login), or a Chinese error string |
| `GET /configuration/VerifyCode.php` | 4-char captcha PNG |
| `GET /gamesession.php` | `{ok,uid,t,sign,seid,sport,ip,pid}`; 401 when logged out |

`sign` is HMAC-SHA256 over `uid|t` with a server secret (`MKO_SIGN_SECRET`, else per-process random) and a 300s freshness window; the legacy `md5(uid + 'xianlingkey' + t)` is rejected.
Passwords are **PBKDF2**, not the legacy plaintext. Sessions live in SQLite,
so restarting the server does not invalidate browser logins.

## Game socket (port 8008)

Faithful to the bytecode recovered from the legacy `dntg_start.jar`
(every reply shape and error code is golden-tested in `tests/`):

1. client → `u32be(9) + AMF3 "INITKEY"`
2. server → `u32be(36) + <uuid key>` (plaintext; the client's cipher needs it)
3. client → **encrypted** AMF3 command frames (`SimpleEncrypt(key, NITABAHAIZHENGEINIPOLE)`)
4. server → **plaintext** AMF3 replies — the protocol is asymmetric:
   `AmfResponseEncoder` never encrypts and nothing in the jar calls `encode()`

Served commands: `10001` login (sign check + role list), `10002` createRole
(validation + error codes from bytecode; success shape matches
`CreateRoleOutput`), enter-world `10003`, map change `20000`, role settings
`13000`, scene entry `21000` with `23002` monster snapshot and `23009` mount
pet, plus the world-entry stat pushes (`12004`/`12005`/`12050`/`12000`) and
SQLite-backed `32010`/`12011`. Progression families: bag/equip/vip/mall/
skill + buyback, zuoqi ranks and longhun pills, meiren companions, shenjiang
star charts, baoshi gems, chengjiu achievements, qiandao sign-in, yingyin
mount skins, email inbox with item/JB/YB claims, pet panel, quest tails
(task/richang/juqing/zuwu), teleport/inner-fly/revive, chat and scheduler
ticks, party/team groups, guild lifecycle, guild dungeons, and the
marriage system (proposals, wedding, divorce, ring strengthening,
spouse teleport). The login result's TimeZone slot is an AMF3 object
carrying `rawOffset`, as `ServerInfoVO.decode()` requires. Each role is a
positional `Object[8]` per `GetRoleOutput.roleInfo`. v1.5 routes 240
command IDs with tests plus 26 server-push IDs (313 of 497 Java IDs
dispatched; per-family status in `docs/*-ledger.md` and
`docs/command-census.md`).

## Layout

- `server.py` — entry point, wires TCP + HTTP
- `game/protocol.py` — framing, handshake, commands
- `game/amf3.py` — AMF3 codec (incl. anonymous objects)
- `game/cipher.py` — `SimpleEncrypt`
- `auth.py` / `db.py` / `web.py` — sign, SQLite store, account API
- `tests/` — `python3 -m unittest discover -s tests` (945 tests, all passing; oracle-dependent cases skip when the legacy config tree is absent). Long-stable internals (AMF3 codec, AI/combat formulas, scheduler, eventbus, stage registry, attribute/buff maps, client map parsing) are frozen and ship without exhaustive golden suites; gameplay families keep full golden coverage

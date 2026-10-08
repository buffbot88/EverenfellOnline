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

`sign = md5(uid + 'xianlingkey' + t)` — identical to `LoginHelper` / the PHP.
Passwords are **PBKDF2**, not the legacy plaintext. Sessions live in SQLite,
so restarting the server does not invalidate browser logins.

## Game socket (port 8008)

Faithful to the bytecode recovered from `dntg_start.jar` (see
`docs/protocol.md` for evidence):

1. client → `u32be(9) + AMF3 "INITKEY"`
2. server → `u32be(36) + <uuid key>` (plaintext; the client's cipher needs it)
3. client → **encrypted** AMF3 command frames (`SimpleEncrypt(key, NITABAHAIZHENGEINIPOLE)`)
4. server → **plaintext** AMF3 replies — the protocol is asymmetric:
   `AmfResponseEncoder` never encrypts and nothing in the jar calls `encode()`

Served commands: `10001` login (sign check + role list), `10002` createRole
(recognised, not yet answered — its wire shape is unrecovered, so in-game
character creation is not possible yet; use `--add-char`). The login result's
TimeZone slot is an AMF3 object carrying `rawOffset`, as
`ServerInfoVO.decode()` requires. Role entries are sent as AMF3 objects, but
the **field names inside a role are unverified** — the client has never
reached the screen that reads them.

## Layout

- `server.py` — entry point, wires TCP + HTTP
- `game/protocol.py` — framing, handshake, commands
- `game/amf3.py` — AMF3 codec (incl. anonymous objects)
- `game/cipher.py` — `SimpleEncrypt`
- `auth.py` / `db.py` / `web.py` — sign, SQLite store, account API
- `tests/` — `python3 -m unittest discover -s tests` (15 tests)

# Website accounts and S1 architecture

## 1. Confirmed existing authentication (inspected, not assumed)

Two identity systems exist. Neither is replaced or duplicated.

### 1a. Studio member system (canonical website identity) — EXTERNAL

`website/index.html` (temporary maintenance homepage, **untouched**) signs
members in against `https://www.agpstudios.org/api`:

- `POST /auth/login {identifier, password}` and `POST /auth/register
  {username, email, password, display_name}` (JSON, `credentials:
  include`), `POST /auth/logout` (CSRF header `X-CSRF-Token` from the
  `ashat_csrf` cookie), `GET /auth/session` (returns `{authenticated,
  user: {username, display_name, email}}`).
- Session is a cookie on agpstudios.org. The Python server holds no
  credential for that API, so it cannot validate those sessions
  server-side today. No bridge is built here (see 5).

### 1b. Game website backend (established game session model) — LOCAL

`Server-v1/web.py` mirrors the legacy site backend (`AccountHandler.php`,
`gamesession.php`, `VerifyCode.php`) with the Python + SQLite stack:

- `accounts(username UNIQUE, pass_hash PBKDF2, created)`; registration
  creates ONLY this row plus a login session — never characters, roles,
  or per-server records.
- `sessions(token PK, uid, created)`; `mko_session` cookie is HttpOnly +
  SameSite=Strict. `gamesession.php` mints the HMAC game sign
  (`uid|timestamp`, 5-minute window) the Flash client logged in with.
- `Server-v1/gateway.py` already authenticates through this model:
  `auth.session {token}` validates the token server-side against the
  sessions store, then runs the headless 10001 login. Passwords never
  reach game databases beyond the PBKDF2 account row, and never cross
  the gateway at all.

### 1c. Browser client today (to be corrected)

`websites/everenfell/src/net/auth.ts` collects raw username + password
and replays the legacy login — a duplicate member path that must go
(see 3). It also calls `world.enter {session}` without a prior
`auth.session`, so role select arrives empty.

## 2. S1 binding (what this milestone implements)

One website membership identity; separate gameplay databases per game
server, beginning with S1 only.

- **Server registry.** The gateway accepts a `server` selector id and
  validates it against an allowlist (`SERVERS`, S1 only). S1 maps to
  the existing game scope (`server_id 'fu1304'`, frozen protocol) and
  the existing Python + SQLite backend. Unknown ids are refused; the
  browser id is never trusted beyond the allowlist check.
- **Lazy member link.** `member_links(member, server_id, game_account,
  verified, created)` records the website-member → per-server game
  account association. The row is written on first successful game
  entry only — registration (wherever it happens) never creates it.
  For S1 the game account defaults to the member name in the same
  store; the row still exists so later servers can map to their own
  databases and the AGP member id has a recorded home.
- **Session transport.** The browser proves its website session without
  touching passwords or tokens in JS: the WebSocket upgrade handshake
  carries the `mko_session` cookie (same host) and the gateway reads
  the token from it server-side. `body.token` stays as an explicit
  override for tests and non-browser tools. No account, server, or
  character id from the browser is trusted: the gateway derives the
  member from the validated session, the scope from the registry, and
  the character from the owned-roles list.
- **Ownership enforcement.** `world.snapshot {roleId}` is refused
  unless the role is in the session's post-login roles for that
  account + server. `player.move` acts on the session-bound role, not
  on any browser-supplied id.

## 3. Client changes (no duplicate member system)

The Everenfell login view keeps no password or registration form. It
checks the website session (`gamesession.php` over the dev proxy with
cookies); signed-out visitors get a link to the website homepage to
sign in. Signed-in members pick a server (S1-only selector, ready for
more entries) and the client runs `auth.session {server}` →
`world.enter` → select → `world.snapshot`.

## 4. Data isolation and scope

Gameplay data stays isolated per game server: every character and
gameplay row is already scoped by `(account, server_id)`, and S1 uses
the single existing database file. Adding S2 later means a new entry
in the registry with its own database; no shared tables.

## 5. Explicit non-goals (documented stubs)

- **Cross-server play**: no inter-server networking, presence, or
  battles. The registry shape reserves it; nothing implements it.
- **AGP server-side validation**: until the studio exposes a session
  introspection contract the Python server may call, links whose
  member id is asserted from the website flow stay `verified=0`.
  Minting or validating AGP sessions is a separate integration, not
  this milestone.
- **Asset work stays primary**: this milestone is deliberately small
  (registry + link table + enforcement + session-only client).

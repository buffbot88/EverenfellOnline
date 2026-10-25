# Website accounts and S1 architecture

## 1. Confirmed existing authentication (inspected, not assumed)

Two identity systems exist. Neither is replaced or duplicated.

### 1a. Studio member system (canonical website identity) — EXTERNAL

`website/` (Vite + React site; the former temporary maintenance homepage
is now the `/` route with a shared navbar on every route) signs members
in against `https://www.agpstudios.org/api`:

- `POST /auth/login {identifier, password}` and `POST /auth/register
  {username, email, password, display_name}` (JSON, `credentials:
  include`), `POST /auth/logout` (CSRF header `X-CSRF-Token` from the
  `ashat_csrf` cookie), `GET /auth/session` (returns `{authenticated,
  user: {username, display_name, email}}`).
- Session is a cookie on agpstudios.org. The Python server holds no
  credential for that API, so it cannot validate those sessions
  server-side today. No bridge is built here (see 5).

### 1b. Legacy game-site backend (compatibility infrastructure) — LOCAL

`Server-v1/web.py` mirrors the legacy site backend (`AccountHandler.php`,
`gamesession.php`, `VerifyCode.php`) with the Python + SQLite stack. This
is legacy compatibility infrastructure for the retired Flash client and
isolated local development — NOT the website membership service and not
a second canonical identity. It must never be described as integrated
with AGP Studios:

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

### 1c. Browser client (corrected this milestone)

`websites/everenfell/src/net/auth.ts` used to collect raw username +
password and replay the legacy login — that duplicate member path is
removed (see 3). The client now rides the website session and calls
`auth.session {server}` before `world.enter`.

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
- **Session transport (authentication boundary).** The browser proves
  its session without touching passwords or tokens in JS: the WebSocket
  upgrade handshake carries the `mko_session` cookie (same host) and
  the gateway reads the token from it server-side. `body.token` stays
  as an explicit override for tests and non-browser tools. What the
  gateway validates is the LOCAL legacy session from §1b — not an AGP
  Studios session. `member_links.verified` is therefore 0 for every
  link written this way. No account, server, or character id from the
  browser is trusted: the gateway derives the member from the validated
  session, the scope from the registry, and the character from the
  owned-roles list.
- **Ownership enforcement.** `world.snapshot {roleId}` is refused
  unless the role is in the session's post-login roles for that
  account + server. `player.move` acts on the session-bound role, not
  on any browser-supplied id.

## 3. Client changes (no duplicate member system)

The Everenfell login view keeps no password or registration form. It
checks the AGP website session directly
(`https://www.agpstudios.org/api/auth/session` with cookies; the retired
`gamesession.php` dev-proxy endpoint is no longer used by the modern
client). Signed-out visitors get a link to the website homepage to sign
in. Signed-in non-admin members see the maintenance gate and the client
never contacts the gateway for them. Admin members pick a server
(S1-only selector, ready for more entries) and the client runs
`auth.session {server}` → `world.enter` → select → `world.snapshot`;
when the gateway answers `invalid session` the client reports that S1
gameplay is closed pending the §5 bridge instead of a generic failure.

## 4. Data isolation and scope

Gameplay data stays isolated per game server: every character and
gameplay row is already scoped by `(account, server_id)`, and S1 uses
the single existing database file. Adding S2 later means a new entry
in the registry with its own database; no shared tables.

## 5. Authentication boundary and integration blocker

- The gateway validates `mko_session` (legacy local session). It does
  NOT validate AGP Studios sessions. These are not the same identity
  provider and must never be described as integrated.
- Canonical identity must ultimately come from AGP Studios (§1a).
  Before public game access, the remaining integration must: identify
  the AGP API's authenticated-session validation contract; verify
  member identity server-side; map the verified member to S1 and its
  owned characters; refuse unverified links (`verified=0`) any public
  entry; preserve the website's registration/password system; never
  trust browser-provided ids; and confirm cookies, origins, and
  deployment domains work with the browser/gateway layout.
- The AGP validation contract is unavailable in this repo, so this
  stays a clearly documented INTEGRATION BLOCKER. No authentication
  protocol is invented here and no duplicate accounts are created.
  The legacy `web.py` path remains development-only on loopback (the
  server logs a warning if the gateway binds elsewhere).
- Alpha root cause (verified from code, 2026-10-25): the deployed alpha
  client has no `/legacy-api` route (that proxy exists only in Vite dev
  toward a loopback `web.py`), so `AuthClient` reported `session refused
  (http 404)`. The fix removes the retired dependency: identity now
  comes from the AGP session endpoint. What is still missing for S1
  gameplay is a server-side way for the Python gateway to verify an AGP
  session (introspection endpoint + credential, or a signed bridge
  token minted by the website backend). Until that contract exists, the
  gateway can only verify sessions it issued itself, the client never
  sends browser-supplied uid/role as proof, and shared S1 gameplay
  access stays closed.
- **Cross-server play**: no inter-server networking, presence, or
  battles. The registry shape reserves it; nothing implements it.
- **Asset work stays primary**: account work stops here (registry +
  link table + enforcement + session-only client + this boundary
  record).

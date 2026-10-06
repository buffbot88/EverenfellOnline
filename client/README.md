# MonkeyKingOnline — HTML5 Web Client (milestone 1)

Phaser 3 + Vite replacement for the legacy Flash client (`Main.swf`, Flash
Player 10 era). Milestone 1 covers **account login / register + game-session
token**, wired to the existing PHP backend. Rendering the game world comes in
milestone 2.

## Prerequisites (backend must be running)

1. Start the ESSamp stack (`TonNgoKhong/server/ESSamp/ESSamp.exe`): Apache on
   **:80**, MySQL on **:3306** with databases `dntg` + `caonima`.
2. Node.js 18+ (Vite 6).

## Run

```sh
cd client
npm install
npm run dev     # -> http://localhost:5173
```

The dev server proxies `/api/*` to `http://127.0.0.1:80` (see
`vite.config.js`), so the PHP session cookie works with no CORS setup.

## How login works

```
browser (:5173) --POST /api/AjaxRequest/AccountHandler.php--> Apache (:80)
   Action=Login, uName, uPas            text contains '登陆成功' => ok
browser (:5173) --GET /api/gamesession.php--> Apache (:80)
   requires PHP session                JSON {uid, t, sign, seid, sport, ip, pid}
```

`gamesession.php` (new, next to the legacy `Gamelogin.php`) issues the exact
token the Flash client got as flashvars: `sign = md5(uid.'xianlingkey'.t)`.
The game socket on **8008** authenticates with `(uid, t, sign)`.

Register additionally needs the captcha at
`/api/configuration/VerifyCode.php` (click the image to refresh).

## Layout

- `src/main.js` — Phaser boot (960×640, FIT scale).
- `src/scenes/BootScene.js` — splash backdrop (placeholder art).
- `src/scenes/LoginScene.js` — DOM login/register overlay + session panel.
- `src/api.js` — PHP backend contract in one place.
- `src/net/GameSocket.js` — **stub**; documents what milestone 2 needs.

## Next milestones

- **M2 — transport + protocol**: WebSocket→TCP bridge to `127.0.0.1:8008`;
  reverse-engineer packet framing/opcodes from `Main.swf` (JPEXS FFDec) and
  the server jar's `com.xianling.io` handlers; document in `docs/protocol.md`.
- **M3 — assets**: extract sprites/maps/audio from the 203 SWFs + PNGs in
  `wwwroot/res/` into `client/public/assets/` (excluded from git for now).
- **M4 — world**: map rendering, movement, chat on top of M2/M3.

## Security notes (inherited, not yet fixed)

Passwords are stored **plaintext** (`caonima.account`) and every legacy PHP
endpoint interpolates SQL unsanitized. This client sends credentials to the
same endpoints the old site used — do not expose this stack to the internet
until the backend is hardened.

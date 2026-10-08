# MonkeyKingOnline — Web Client

Two pages, one backend:

- **`player.html` (primary)** — runs the ORIGINAL Flash client (`Main.swf`)
  under Ruffle (selfhosted 0.7.1). This is the real game, not a rewrite:
  loader, login UI, asset decryption and all content run as shipped in 2014.
- **`index.html`** — Phaser 3 login/register scaffold (milestone 1). Still
  works; kept as the reference implementation of the PHP backend contract.

## Prerequisites

1. Node.js 18+ (Vite 6).
2. For login (not for booting the loader): the ESSamp stack
   (`TonNgoKhong/server/ESSamp/ESSamp.exe`) — Apache on **:80**, MySQL on
   **:3306** with databases `dntg` + `caonima`.
3. For entering the world: the game server (`server.bat`, port **8008**)
   **plus** the WebSocket→TCP bridge (milestone 2, not built yet) — browsers
   can't open raw TCP sockets.

## Run

```sh
cd client
npm install      # also stages Ruffle into public/ruffle/ (predev hook)
npm run dev      # -> http://localhost:5173/player.html
```

No asset copying: `/res/*` is served live from the legacy tree
(`../TonNgoKhong/server/ESSamp/wwwroot/res`) by dev middleware in
`vite.config.js` — the 1.7 GB stays out of git and out of the bundle.
`/api/*` proxies to Apache :80 so the PHP session cookie stays same-origin.

## How it fits together

```
browser (:5173/player.html)
 ├─ /ruffle/ruffle.js            selfhosted Ruffle (NOT bundled — it resolves
 │                                core/wasm relative to its <script> tag;
 │                                see scripts/copy-ruffle.js, predev/prebuild)
 ├─ /res/Main.swf                legacy tree, served by resPlugin middleware
 │     └─ Main.swf → PlatformLoader.swf → assets/tg.swf → game UI
 │        (PlatformLoader decrypts the MD5-packed asset SWFs at runtime)
 └─ /api/gamesession.php         flashvars token {uid,t,sign,seid,sport,ip,pid}
    (demo-session fallback when PHP is offline — loader boots regardless)
```

`src/player.js` — Ruffle boot. `src/flashvars.js` — session→flashvars
mapping (mirrors `Gamelogin.php`). `src/api.js` — PHP contract
(`登陆成功` login check, captcha register, session fetch).

## English translation (text + images)

Status: extracted + scoped, not yet translated. Sources by size:

> **Renderer note:** Ruffle web logs `Unknown device font "SimSun"` — device
> CJK fonts cannot render, so English text is a rendering fix as much as a
> localization one. Bitmap text (most UI art) renders fine.

| Source | Scope | Artifact |
|---|---|---|
| Game tables `res/java/zhcn/*.dat` | 7,520 unique strings | `.survey/i18n_zh.json` via `../tools/dat_strings.py` |
| PHP pages | 35 files with CJK | hand-edit when translating |
| Loose images `res/f/`, `res/global/` | 58 likely-text of 524 | `.survey/images.json` via `../tools/image_inventory.py` |
| Encrypted SWF packs | baked UI text, cipher unsolved | phase 2 (see `../knowledge.md`) |

Workflow once translations exist: build English AMF3 locale tables with an
offset-aware rewriter (length-prefixed strings — can't be patched by hand)
and serve them through the `/res` layer; redraw flagged images into an
overlay dir mounted the same way.

## Next milestones

- **M2 — transport: DONE** (`tools/bridge/`). Byte-transparent WS→TCP
  forwarder (`npm start` there; `ws://127.0.0.1:8181` → `127.0.0.1:8008`),
  wired via Ruffle `socketProxy` in `src/player.js`. Verified live to a fake
  game server; protocol findings in `docs/protocol.md`. Remaining: boot the
  real stack and capture the server's first reply.
- **M3 — translation build**: AMF3 read/write rewriter, `en/` locale tables,
  redrawn banner/button art, translated PHP pages.
- **M4 — asset cipher (optional)**: recover the MD5 key derivation to
  decrypt/repack the 193 asset SWFs for full UI translation.

## Security notes (inherited, not yet fixed)

Passwords are stored **plaintext** (`caonima.account`) and every legacy PHP
endpoint interpolates SQL unsanitized. Do not expose this stack to the
internet until the backend is hardened.

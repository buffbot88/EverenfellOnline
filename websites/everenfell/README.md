# Everenfell browser client

Phaser renders the recovered Map 0 tiles; the Python server owns gameplay and admission.

## Local development

```sh
cd websites/everenfell
npm install
npm run dev
npm run typecheck
npm run build
```

Vite serves source assets from `assets/` for local development and proxies `/api` and `/everenfell` to the loopback Python services. This local source path is not included in `dist/`.

## Alpha access

Sign-in redirects to AGP Studios at `/auth/login`. The Python backend establishes a host-only HttpOnly session; the browser requests a short-lived ticket from `/api/game/ticket` before connecting to `/everenfell` over WSS. Map and original UI files load only through `/protected-assets/`, which checks the same session and S1 entitlement on every request.

`vite.config.ts` disables public-directory copying. Keep original assets under `assets/`; never deploy them as anonymous static files.

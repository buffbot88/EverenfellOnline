# Everenfell browser client

Browser-native 2.5D MMORPG foundation (TypeScript + PixiJS), running
against the frozen Python + SQLite server. This shell establishes
identity, login/select/world views, camera, input, the actor layer, the
window manager, the versioned asset pipeline, and the gateway adapter.
Gameplay logic stays on the server; the client renders validated state.

## Develop

Requirements: Node 18+. No Godot runtime, no Flash.

```sh
cd websites/everenfell
npm install
npm run dev        # http://localhost:5173
npm run typecheck  # strict tsc
npm run build      # production bundle in dist/
```

Dev proxy: `/legacy-api/*` forwards to the Python web API on
`127.0.0.1:8080` (see `vite.config.ts`). The gateway URL defaults to
`ws://127.0.0.1:8091/everenfell` and can be overridden with
`?gateway=ws://host:port/path` (and `?api=` for the web API).

## Gateway contract (Mission 5)

`src/net/protocol.ts` is the contract. The gateway translates the
server's authoritative TCP/AMF3 packets to JSON envelopes
`{ op, seq, body }` with `{ op, seq, ok, body }` replies and seq-0
pushes. Smallest loop: `auth.login -> auth.session -> world.enter ->
world.snapshot -> player.move / actor.moved`. The gateway does not
exist yet; the UI reports that honestly instead of faking a world.

## Assets

`src/assets/manifest.ts` + `cache.ts`: versioned JSON manifest, Cache
Storage with network fallback. Only rights-cleared or independently
original files may ship under `public/assets` (see
`Server-v1/docs/everenfell-asset-ledger.md`). Placeholder tints stand
in until recovered/replacement art lands with matching anchors.

## Conventions

- Views are thin; `net/` owns transport, `world/` owns rendering,
  `ui/` owns panels. No gameplay rules in TypeScript.
- Positions are server tiles (60x30 px); the camera projection is
  explicit in `world/camera.ts` and will track the recovered 2.5D
  projection once sprite anchors land.
- Focused checks only: `npm run typecheck` and `npm run build`.

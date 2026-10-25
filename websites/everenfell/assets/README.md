# Everenfell client assets (recovered originals)

`manifest.json` is the versioned index of everything below. Planned
`characters/`, `monsters/`, `effects/` and `audio/` sections populate
as extraction proceeds; only `ui/` and `maps/` exist so far.

## ui/ — decoded Flash interface modules

Each folder is one verified decoded Flash module recovered from the
running projector's memory (read-only scan, `scripts/asset_tools/`):

- `ui/gameui/` — HUD library, 707,674-byte FWS v10: 170 bitmaps, 0 failed.
- `ui/hud-chat/` — HUD/chat module, 833,792 bytes: 338 bitmaps, 0 failed.
- `ui/create-ui/` — character-creation module, 222,611 bytes: 24 bitmaps.
- `ui/shared-controls/` — shared UI controls, 264,149 bytes: 196 bitmaps.

Layout per module: `images/<characterId>-<kind>.png` (straight-alpha
RGBA PNG, one file per decoded bitmap), `manifest.json` (module sha256,
per-resource character id, tag type, dimensions, alpha range, linkage
names, decode status), `contact-sheet-*.png` (visual review sheets).

Character IDs are the source of truth for wiring bitmaps to MovieClip
timelines and SymbolClass linkage; most HUD pieces are MovieClips
composed of these bitmaps plus vector shapes (sprite/timeline mapping
is the documented next step, not yet built).

## maps/ — world tiles (ships in public/, not here)

`public/maps/map0/` holds the 408 original Map 0 JPEG tiles (17x24 at
256px, 4352x6144), referenced by relative URLs from
`src/assets/map0.json` so dev and production resolve identically.

Rights: legacy Binjiang-distribution client art of unknown commercial
reuse rights. These files ship with the client for development and
faithful reconstruction only. Do not publish or bundle them for public
deployment until rights are confirmed.

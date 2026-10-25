# Everenfell server baseline (frozen)

The Python server is in maintenance/integration mode. Gameplay systems are
frozen at commit `825225a`; only concrete browser-integration needs or
demonstrated defects move it, with focused tests.

## Frozen state

- Runtime: `Server-v1/server.py` + `web.py` + `auth.py` + `db.py` +
  `game/`, stdlib only (Pillow for optional `--captcha`). Game TCP
  `:8008`, web account API `:8080`, one scheduler thread, SQLite.
- Gameplay: login, world entry, movement/AOI, combat, drops/pickups,
  revive, quests/tasks, pets, mounts, guild/team/marriage/dungeon
  (zuwu/juqing/guildfuben) loops, waypoint portals (20001), vitals
  backfill for fresh roles (`_ensure_role_vitals`, 12004 always sent).
- Legacy reference (`reference/TonNgoKhong`, `.jat`/`.dat` tables) and
  the Flash client (`MKO_Client`) are immutable reference material.
- Full-suite verification stays gated on an explicit version-bump
  authorization; the last green neighbor run is recorded in the
  phase-transition report, not repeated here.

## Known integration gaps for the browser client

1. **Transport**: raw TCP with a custom frame cipher + AMF3. Browsers
   need a WebSocket (or HTTP) gateway; packet semantics stay, the
   framing/serialization gets a documented adapter.
2. **Auth**: PHP-compatible web API (`AccountHandler.php`,
   `Gamelogin.php`/`gamesession.php`) plus a game-side sign check.
   Reuse the session model; do not reimplement login in TypeScript.
3. **Single line**: every map is line 1 (`21000` answers `[1, 1,
   mapType]`); line switching (20004/20005/21001) is unimplemented.
4. **Peer records**: surround movement/AOI routing is correct, but the
   exact peer enter/leave record shape is unverified (no two-role
   capture). Solo play is unaffected.
5. **Asset pipeline**: 199 legacy SWFs cataloged (`tools/swf_catalog.py`
  + `output/swf-catalog.json`); 6 standard files extractable, 193
  packed behind the PlatformLoader Md5/XOR step (see Mission 3 notes).
  No rights clearance exists; nothing rights-unclear ships publicly.
6. **Flash-only behaviors**: any remaining client-driven flows without
   captures (line UI, second-client views) stay unimplemented until the
   browser client demonstrates the need.

## Change rules

- No renames of protocol IDs or SQLite structures for branding.
- No new Java-service ports, monetization, or command families.
- Server edits require a browser-integration trigger and a focused
  regression test; update the affected ledger in the same commit.

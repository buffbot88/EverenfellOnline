# Java-retirement blockers (stage/world/dungeon scope)

Inventory after `c18cfa9` (cross-session guild-dungeon eviction
routing). Grounded in `dntg_start.jar` javap, `javacmds.txt` /
`actionmethods.txt`, the `output/orig-stack/` captures, and the
current Python implementation. Out of scope for this report: systems
never censused here (see §D).

## A. Required for core server operation and playable gameplay

No hard blocker remains inside the migrated scope:

- Login, world movement, combat, drops, pickups, revive, and the
  zuwu/juqing/guildfuben enter → fight → reward → leave loops all run
  on the Python server with no Java process (`Server-v1/server.py`
  + SQLite). Ordinary maps keep the shared world; copies isolate
  monsters/drops/AI and return home on quit/expire/victory/
  disconnect (`docs/stage-ledger.md`).
- Waypoint portals (20001 `applyWayPointTeleport`, e.g. `f0002`
  map 0 → map 2) are served from `ChuanSongBiao.jat`: unknown ids
  stay silent, dead/copy/level gates answer `[0, code]` (490011 /
  490013 / 490002 / 490003 per `StageErrorCode`), same-map hops echo
  40100, cross-map hops ride `change_map`. Proven by the live stock
  client, which was stuck on map 0 until this reply existed
  (`tests/test_teleport.py` WaypointTeleportTest, 7 goldens).
- Copy timers ride the acting session's `StageScheduleManager` with
  the Java durations; a dead attempt makes the firing a no-op, and a
  process restart loses only in-memory attempts — the same as Java's
  `DataContainer` stage state. No persisted-schedule gap observed.
- `encodeOfflineCopy` / `isOfflineSaveCopy` is **not** an ops
  blocker: the offline-save rule plus the per-attempt return position
  reproduce login placement without the `copyInfo` column.
- Runtime independence (audited, not assumed): the production path
  (`server.py` + `web.py` + `auth.py` + `db.py` + `game/`) imports
  stdlib only (plus Pillow for the optional `--captcha` image). No
  Java executable, no JAR loading, no JDBC/MySQL, no subprocess, no
  remote service: game TCP on `:8008`, web account API on `:8080`,
  one in-process scheduler thread (`tick_loop`), SQLite persistence.
  The `.jat`/`.dat` tables are Java-*format* data files read by
  `game/config.py`, not a runtime dependency.
- Black-screen cause resolved: pushing the 13000/32010 bootstrap
  with the 10001 login reply wedged the stock client (it never sent
  21000). The pushes now ride world entry just before the 10003
  reply, matching the captures. Pinned by
  `TestLogin.test_login_sends_no_bootstrap` and
  `test_enter_world_pushes_java_bootstrap_before_10003_reply`
  (6/6 pass). No live projector run exists in this environment, so
  end-to-end client reachability past world entry is still unverified.

## B. Required for faithful Java gameplay parity

1. Map lines (20004 APPLY_CHANGE_LINE / 20005 GET_MAP_LINES / 21001
   CHANGE_LINE): every map is line 1 and `21000` answers
   `[1, 1, mapType]`. `StageControllAction` does declare
   `applyChangeLine`/`changeLine`/`getMapLines`, so this is a real
   client-driven inbound flow — but it is **not** a startup or world-
   entry blocker. It gates only the line UI on multi-line maps
   (91 `MapLine.jat` rows ship): a client asking for lines is met
   with silence, while play continues on line 1. No captured
   request/reply exists, so the wire shape stays unimplemented
   until a D1 capture lands.
2. Peer enter/leave records on surround changes: no numeric wire ID
   exists for this — `StageAction.enterStage`/`leaveStage` consume
   the internal `S:ENTER`/`S:LEAVE` bus keys, and no `*Commands`
   constant names a peer frame in any two-role capture.
   Movement/AOI routing itself is correct (fan-out covered by the
   movement/teleport tests); only the exact peer-visible record
   shape is missing. **Not** startup-gating and irrelevant to solo
   play; it gates visual correctness when two clients share a map.
3. ~~Kick/evict/disband home routing~~ — closed: `_guildfuben_evict_home`
   runs on the member's own session (queued via `push_op`
   cross-session), delivering return-home map frames plus the 118004
   notice; offline members get registry cleanup only. Covered in
   `tests/test_stage_instances.py` (GuildCopyTest kick/disband/expire)
   and the `test_guildfuben.py` exit/disband tests.
4. `hisRolePosition` bus history for arbitrary (non-dungeon) stage
   hops: dungeon return-home is stored per attempt and verified; the
   general history stays unported.

## C. Optional / deferred (not Java-retirement blockers)

- Monetization, SWF extraction, client modernization: explicitly out
  of scope, untouched.
- Marriage is **implemented**, not unported: all 7 inbound IDs
  (135000 panel, 135001 proposal, 135002 answer, 135004 divorce,
  135005 spouse teleport, 135006 ring strengthen) are
  complete+tested in `tests/test_marry.py`, with 135002-card /
  135003-result / 11131-wedding pushes asserted in peer outboxes
  (`docs/marry-ledger.md`). Residuals are the three documented
  deviations only (remarriage count vs `ALL_COUNT_KEY`, stricter
  `chuansong` gates, outbox instead of world broadcast). The census
  "marry missing 1" is the `h11101` S2C notice alias — served by
  the `CMD_NOTICE_ALL` push helper, with no inbound handler in Java
  either.
- Kuafu is genuinely absent (0/7: 125000/125001/125008/125009/
  125012/125016; the 7th census ID is the `GLOBALMSG` 11101 alias,
  already served): a cross-server family needing a second game
  server plus `KUAFUSJZD` map type 17. Deferred — nothing in a
  single-server playable session calls it.
- GM is admin tooling, not gameplay (0/24 `GM_100`–`GM_200`; the
  census "gm done 1" is the `GET_BAG_GOODS` 30000 alias,
  implemented as `bag_goods`). The login/world replies already
  carry the `gmOpen`/`gmState` slots the client reads.
- Census S2C aliases are not inbound gaps: juqingfuben's missing 2
  are `SYSTEM_BROADCAST` 11100 + `NOTICE_ALL` 11101, guildfuben's
  missing 2 are the 11003/11130 push wrappers — all server pushes
  with no Java inbound route, like 135003/11131 (already
  `push-only`). The single `client` row (`000` ROLE_IN) is the only
  unclassified census ID and gates nothing observed.
- The juqing dead-code surface (`KillMonsterAwards`,
  `vipAutoFightAwards`, `getTodayRemainCount`, etc.): unported by
  decision, not by protocol ignorance (`docs/juqingfuben-ledger.md`).
- Cosmetic nondeterminism: `108001`/`64001` row ordering, exp-incr
  caps, equip-attribute drop paths with no shipped rows.

## D. Client-protocol / asset evidence still needed

1. Line UI flow: a real-client capture of 20004/20005/21001 on a
   lined map (request bytes + reply frames + the `21000` line field).
2. Two-client surround capture: the exact frame a nearby role
   receives when another role enters/leaves its AOI block.
3. `copyInfo` column sample (optional): a legacy row carrying
   `encodeOfflineCopy` output, only if login placement ever diverges.

D1 gates only the line UI (B1); D2 gates only peer-record parity
(B2). Neither gates startup, world entry, or solo play — and neither
capture can be assumed collectible until the stock client is shown
reaching those screens against Python. Do not begin SWF extraction
or client modernization: guessing the frames would break parity
rather than advance retirement.

## E. Retirement verdict (2026-10-24)

1. Java required at runtime? No — nowhere: no executable, no JAR,
   no MySQL/JDBC, no subprocess, no hosted Java service. Only
   Java-format config data (read as data) and bytecode-derived
   constants remain.
2. Can Python independently host the existing client? Protocol-wise
   yes through world entry (login envelope, sign check, 13000/32010
   bootstrap order, 10003 reply, 20000/21000 stage entry are all
   capture-shaped and test-pinned); end-to-end projector proof is
   still missing.
3. Defects blocking a complete playable session: none known in the
   migrated scope — the solo loop and all three dungeon loops run
   with tests green. The two genuine unknowns are post-entry
   client screens (line UI, second-client surround), still
   uncaptured.
4. Nonblocking parity differences: §B.1–B.2 (lobby/multiplayer
   visual), §B.4 bus history, §C deviations and deferred families.
5. Minimum remaining tasks before freezing Server V1: (a) one
   controlled projector run to confirm the client reaches world
   entry and can move/fight; (b) only then, D1/D2 captures and the
   two small implementations behind them. Everything else is
   freeze-safe as documented.

Python-only smoke (no Java process): Store migration + login-role
read, `StageRegistry` + isolated `MonsterWorld` init, `change_map`
(20000 path), `tick_sessions` round, and shared-registry second
session all pass against the legacy config tree.

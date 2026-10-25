# Stage / World / Instance ledger

Oracle: `dntg_start.jar` via `javap -c` — `StageControllServiceImpl`
(login/logout/applyChangeMap/changeMap/leaveStage/checkStageAndEnter),
`RoleStageServiceImpl.syncRoleStageData`, `StageExportServiceImpl`,
`MapType` (clinit values + `usedForOfflineSave`/`isOfflineSaveCopy`),
plus the `10003`/`20000`/`21000` login burst in
`output/orig-stack/java-session-summary.txt`.

## Status: copies DONE for zuwu/juqing/guildfuben; lines + peer records deferred

The logout and map-move persistence now follows the Java sync instead
of persisting every live position. Zuwu and juqing run as genuine
per-role stage instances, guildfuben as a per-guild shared instance;
all three return home (`applyReturnLastStage`) and destroy the emptied
copy. Line numbers and peer enter/leave wire records remain unported
(see Deferred — both need original-client evidence).

## DONE: offline-save position rule

- `MapType` values from the clinit bytecode: NORMAL 1, ZHUCHENG 2,
  JUQING 3, BOSSTIAOZHAN 4, GUAIWUGONGCHENG 5, JINDI 6, GUOZHAN 7,
  TEAMFUBEN 8, KUANGZHAN 11, CHALLENGE 12, QISHENGBOSS 13,
  PANTAOYUAN 14, ZUWUFUBEN 15, GUILDFUBEN 16, KUAFUSJZD 17.
- `usedForOfflineSave` is exactly {1, 2} (`config.offline_save_map`,
  unknown maps save like before so minimal configs are unaffected).
- Map moves (`change_map`, `apply_stage`, `teleport`, `tile_step`,
  `inner_fly`, same-map revive) persist the row position only on
  save maps (`_stage_save_position`, same call shapes as before:
  x/y-only for same-map moves). The live registry always tracks the
  real tile; `_live_map` reads it with a row fallback.
- Logout (`_stage_on_disconnect`, wired in the server `finally`
  block): a dead role persists the born-config revive roll at full
  HP/MP — never the death tile — and the offline-save rule applies
  after the roll, so dying in a copy wakes at the pre-copy position.
  Living roles need nothing (incremental writes stay current).
- Login placement falls out of the row: `enter_world` reads the
  persisted map, so a fuben logout re-enters at the offline save.

## DONE: dungeon stage copies (zuwu + juqing + guildfuben)

- `StageRegistry` keys live membership by stage key; the base map stays
  the client-visible id (`map_of`/`_live_map`). Ordinary stages use the
  map id as its own key and share the server `MonsterWorld`.
- `create_instance('base', 'ZUWU', rid)` mints the per-role copy
  (`ZUWU-<rid>-<map>`); `change_map(..., stage_key=...)` joins it and
  `_bind_stage_world` repoints monster HP/dead/reg/hatred/leave/spawn
  plus ground items at the isolated world. Wire maps stay base ids.
- Combat, hatred/AI, drops, pickups, expiry notices and frame delivery
  resolve through the bound stage: cross-copy role/monster targets are
  skipped, `_fighter_surround`/`_point_broadcast` stay inside the copy,
  and `deliver_world_frames` fans instance frames to stage members only.
- `zuwu_enter` saves the pre-copy position (`return_map/pos`), `quit` /
  `expire` / `victory` / `disconnect` return there via
  `_zuwu_home_frames` (`applyReturnLastStage`) and destroy the emptied
  copy; kills count only inside the killer's own copy.
- Juqing mirrors it: `JUQING-<rid>-<map>` copies, `stage`/`return_map`/
  `return_pos` ride the `tiaozhan_jindu` marker, kills gate on the
  killer's live copy, victory/expire return home before the `64003`
  result, and disconnect abandons the copy (marker cleared).
- Guildfuben shares one copy per guild: `GUILDFUBEN-<gid>-<main>-<map>`
  (the port's pre-existing stage id, now a real instance key).
  Members join the same stage/world, kills gate on live map + live
  copy + guild ownership, quit/expire return home, and the emptied copy
  is destroyed; killboss/reward rows stay per guild (shared progress).
- `tests/test_stage_instances.py` (11): registry isolation, zuwu
  two-copy independence + quit-home, juqing two-copy independence +
  victory-home + disconnect-abandon, guild shared-copy + two-guild
  isolation + quit/disconnect cleanup.

## Deferred (needs original-client evidence — nothing invented)

- Line numbers (`getStageLine`/`incrLineNo`, 20004 APPLY_CHANGE_LINE /
  20005 GET_MAP_LINES / 21001 CHANGE_LINE): the port has no lines;
  every map is line 1 and `21000` answers `[1, 1, mapType]`. No captured
  20004/20005/21001 request or reply exists in `output/orig-stack/` or
  the census, so the wire shapes stay unported. Blocker to implement:
  a real-client capture of the line UI flow (request bytes + reply
  frames for 20004/20005/21001 on a lined map).
- Peer enter/leave wire records: the changeMap commit calls stage-side
  leave/enter, but no two-role capture or `*Commands` constant names the
  peer-visible record, so the port sends none rather than inventing one.
  Blocker: a two-client capture showing the exact frame a nearby role
  receives when another role enters/leaves its surround.
- `encodeOfflineCopy` / `isOfflineSaveCopy` `copyInfo`: no reader or
  writer in the port; the field stays absent. Not a gameplay blocker:
  the offline-save rule + pre-copy return position reproduce the
  observable behavior (login placement) without the column.
- `hisRolePosition` bus history: the port stores the pre-copy position
  on each attempt (verified return-home for all three families); the
  general bus history for arbitrary stage hops stays unported.
- `encodeZuoQiInfo(role, logoutFlag)` and `encodeMeirenInfo`: the
  port persists zuoqi on change and pk on logout; the boolean-flag
  variants have no verified behavioral delta.
- Expiry/teardown scheduling: Java arms per-copy timers in the stage
  schedule manager; the port arms the same durations on the acting
  session's `StageScheduleManager` (same delays, `tick_sessions`
  drives per-world rounds). No behavioral delta observed.
- Stage business-data pushes are the family payloads and are ported:
  `64009` enter state, `108007` rest timer, `118006` kill log, plus
  kill notices (`108008`, guild `11101` 118009/118010). No separate
  generic business-data channel was found in the censused commands.

## Tests

`tests/test_stage_sync.py` (10): map-type predicate, copy/story
entry and steps skipping the row, alive/dead logout in each case,
missing born config, and re-login placement at the offline save.
`tests/test_stage_instances.py` (11) covers all three copy paths
plus cross-session guild kick/disband/expire home delivery.
Neighbors re-verified: teleport, change_map, movement_enter, revive,
pvp, pickup, combat (consistency + shared), team, guild (19),
ground, juqing fuben (34), zuwu (23), guildfuben (22), monster death.

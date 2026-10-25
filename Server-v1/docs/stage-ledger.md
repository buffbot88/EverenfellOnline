# Stage / World / Instance ledger

Oracle: `dntg_start.jar` via `javap -c` — `StageControllServiceImpl`
(login/logout/applyChangeMap/changeMap/leaveStage/checkStageAndEnter),
`RoleStageServiceImpl.syncRoleStageData`, `StageExportServiceImpl`,
`MapType` (clinit values + `usedForOfflineSave`/`isOfflineSaveCopy`),
plus the `10003`/`20000`/`21000` login burst in
`output/orig-stack/java-session-summary.txt`.

## Status: partial — offline-save sync DONE, zuwu copies DONE, lines deferred

The logout and map-move persistence now follows the Java sync instead
of persisting every live position. Zuwu dungeon copies run as genuine
per-role stage instances; other families still share one world map and
line numbers remain unported (see Deferred).

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

## DONE: zuwu stage copies (one family end-to-end)

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
- `tests/test_stage_instances.py` (3): registry isolation, two-copy
  independence (stages/worlds/AOI/kills), quit-home plus cleanup.

## Deferred (verified in bytecode, needs stage-copy/line architecture)

- Stage copies for the remaining families: `checkStageAndEnter`
  creates per-family copies (`createJuQingCopy`, `createGuildFuBen`,
  ...); juqing/guildfuben still share one world map per fuben (see
  those ledgers). The same `create_instance`/`stage_key` path applies.
- Guild copies will key on the existing
  `GUILDFUBEN-<gid>-<main>-<map>` id so authorized members share one
  copy; juqing copies will key per role like zuwu.
- Line numbers (`getStageLine`/`incrLineNo`, 20004/20005): the port
  has no lines; every map is line 1.
- `hisRolePosition` / `applyReturnLastStage`: the port stores the
  pre-copy position on the zuwu attempt (return-home verified); other
  families still need the bus RoleState history.
- `encodeOfflineCopy` / `isOfflineSaveCopy` `copyInfo`: no reader or
  writer in the port; the field stays absent.
- Role enter/leave wire records: the changeMap commit calls
  stage-side leave/enter, but no two-role capture or `*Commands`
  constant names the peer-visible record, so the port sends none
  rather than inventing one.
- `encodeZuoQiInfo(role, logoutFlag)` and `encodeMeirenInfo`: the
  port persists zuoqi on change and pk on logout; the boolean-flag
  variants have no verified behavioral delta.

## Tests

`tests/test_stage_sync.py` (10): map-type predicate, copy/story
entry and steps skipping the row, alive/dead logout in each case,
missing born config, and re-login placement at the offline save.
`tests/test_stage_instances.py` (3) covers the zuwu copy path.
Neighbors re-verified: teleport, change_map, movement_enter, revive,
pvp, pickup, combat (consistency + shared), team, ground, juqing
fuben, monster death. Guildfuben shows the same 8 failures + 1 error
on and off this change (pre-existing, unported copy routing).

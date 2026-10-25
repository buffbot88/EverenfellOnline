# Java-retirement blockers (stage/world/dungeon scope)

Inventory after `214a03d` (zuwu copies) plus the juqing + guildfuben
copy migration. Grounded in `dntg_start.jar` javap, the
`output/orig-stack/` captures, and the current Python implementation.
Out of scope for this report: systems never censused here (see §D).

## A. Required for core server operation and playable gameplay

No hard blocker remains inside the migrated scope:

- Login, world movement, combat, drops, pickups, revive, and the
  zuwu/juqing/guildfuben enter → fight → reward → leave loops all run
  on the Python server with no Java process (`Server-v1/server.py`
  + SQLite). Ordinary maps keep the shared world; copies isolate
  monsters/drops/AI and return home on quit/expire/victory/
  disconnect (`docs/stage-ledger.md`).
- Copy timers ride the acting session's `StageScheduleManager` with
  the Java durations; a dead attempt makes the firing a no-op, and a
  process restart loses only in-memory attempts — the same as Java's
  `DataContainer` stage state. No persisted-schedule gap observed.
- `encodeOfflineCopy` / `isOfflineSaveCopy` is **not** an ops
  blocker: the offline-save rule plus the per-attempt return position
  reproduce login placement without the `copyInfo` column.

## B. Required for faithful Java gameplay parity

1. Map lines (20004 APPLY_CHANGE_LINE / 20005 GET_MAP_LINES / 21001
   CHANGE_LINE, `getStageLine`/`incrLineNo`): every map is line 1 and
   `21000` answers `[1, 1, mapType]`. No captured request/reply for
   the line flow exists, so multi-line maps cannot be verified.
2. Peer enter/leave records on surround changes: the port sends no
   peer-visible frame (no `*Commands` constant names it in any
   two-role capture). Movement/AOI itself is correct; only the exact
   peer record shape is missing.
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
- Remaining census families (`marry`, `kuafu`, `gm` residuals) and
  the juqing dead-code surface (`KillMonsterAwards`,
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

Do not begin SWF extraction or client modernization: items D1–D2
gate B1–B2, and guessing the frames would break parity rather than
advance retirement.

Python-only smoke (no Java process): Store migration + login-role
read, `StageRegistry` + isolated `MonsterWorld` init, `change_map`
(20000 path), `tick_sessions` round, and shared-registry second
session all pass against the legacy config tree.

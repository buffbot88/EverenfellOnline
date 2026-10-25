# GuildFuBen (guild-dungeon) porting ledger

Authoritative per-command status for the Java guild-dungeon surface.
Evidence: `dntg_start.jar` javap of `GuildFuBenAction`,
`GuildFuBenServiceImpl`, `GuildFuBenOutputWrapper`,
`BangPaiFuBenConfigExportServiceImpl`, `BangPaiFuBenConfig Intelligence`,
`GuildFuBenStageCopyServiceImpl`, `GuildFuBenStageCopy`,
`GuildFuBenUtil` (isEnter), `GuildFubenConstants`, plus the live
`bangpaifuben.jat` / `bangpaifubenboss.jat` rows. Scratch dumps live
under `Server-v1/.jrecon/gfb_*.txt` (not committed).

Status words: complete+tested (wire-exercised through the real
handlers + SQLite store + seeded world), push-only (S2C, asserted in
member outboxes).

## Inbound commands (GuildFuBenAction)

| ID | Java method | Status | Notes |
| -- | ----------- | ------ | ----- |
| 118001 | getInfo | complete+tested | `[1,[openIds],[passedIds],killCount]`-shaped panel: sealed and passed dungeon id lists from the shared `guild_fuben` rows, kill count from the personal `killboss` log; fires the lazy weekly reset on access |
| 118002 | getReward | complete+tested | claims one cleared boss chest: needs a cleared boss and an unclaimed `reward_history` entry; grants the `baoxiangjiangli1..4` items (bag-or-mail, xuni routing like zuwu); duplicate claim is `[0,118005]`; replies `[1,mainid,bossTpl]` |
| 118003 | inFuBen | complete+tested | gates in order: 10-minute re-entry cooldown 118013, unknown dungeon silence, guildless empty reply, sealed dungeon 118006, already-inside silence; entry joins the per-guild copy (`GUILDFUBEN-<gid>-<main>-<map>`) via `change_map(stage_key=...)`, records presence, pushes the 118006 stage payload with the kill log, notifies the guild 118011, replies `[1]` |
| 118004 | quitFuBen | complete+tested | drops presence and the attempt, returns home via `_guildfuben_home_frames` (already-out is still `[1]`); members hear the 118012 guild notice |
| 118007 | relieveSeal | complete+tested | master-only (non-master 118000), guild-money `money` cost from `bangpaifuben.jat` (short 118002), sealed-only; flips `open` to 1 and pushes the 118008 unseal notice to the guild |

118006 is the stage-enter push (`[mainid,[[bossTpl,[...]]],0]`); it
doubles as the sealed-enter error. 118005/118011/118012/118013 are
error/notice payload codes, not inbound commands.

## Lifecycle (the shared-row path)

- One `guild_fuben` row per (guild, mainid): `open` sealed flag,
  `killboss` cleared-boss map, `reward_list`, `log_update_time`.
  Created sealed from the config `isopen` default on first touch.
- Kills count per guild copy: the combat kill hook credits the
  killer's guild row only when the killer's live stage matches the
  attempt copy and the live map matches the dungeon map; the full
  member roster is stored as the claim list. Members share one copy
  and world; two guilds never share a stage, world, or row.
- Unseal spends guild money and opens the row for the whole guild;
  entry needs no team (solo or side-by-side members share progress).
- Weekly reset is lazy: `refreshAll` (clear killboss/rewardList/open)
  fires on access past the `time2` weekday|HH:MM slot boundary, and
  every firing access stamps the accessor's 10-minute re-entry
  cooldown (`setRefMap`/`isEnter`); login prunes expired personal
  claim entries (`clearData` via `_guildfuben_on_enter`).
- Personal claims persist in `guild_fuben_reward`
  (`reward_history` boss->template map, `update_time` last-claim
  stamps) so duplicate claims and cross-session re-entry behave.
- Guild exit/kick/disband hooks evict the role's presence and attempt
  in-session and cross-session (118004 frame), and disband deletes
  the guild's dungeon rows.

## Config (all real records, no invented values)

`bangpaifuben.jat` (mainid/map/initial pos/openrenwu level/money
unseal cost/isopen/mainname/complete need-kills/guaiwuGPS spawns/
time1 copy lifetime/time2 weekly slot),
`bangpaifubenboss.jat` (id-guanka key, bossname,
baoxiangjiangli1..4 chest items).

## Python deliberate deviations (documented)

- Presence/attempt markers live on the session (`_guildfuben_inside`,
  `_guildfuben_attempt` plus `stage`/`return_map`/`return_pos`) instead
  of the stage object; expiry/disconnect run on the session scheduler
  and destroy the emptied copy. Killboss/reward rows stay per guild
  in SQLite (shared progress by design).
- Entry/exit move through `change_map(stage_key=...)` plus
  `_guildfuben_home_frames` (pre-copy position rides the attempt, not
  the bus RoleState history). Kick/evict/disband run
  `_guildfuben_evict_home` on the member's own session (queued via
  `push_op` cross-session, riding that session's tick), so the member
  gets the return-home map frames plus the 118004 notice; offline
  members get registry cleanup only (Java isOnline gate).
- The quartz `refreshAll` schedule runs as a lazy boundary check on
  access; the 10-minute cooldown is a per-session stamp map.
- `11130`/`11003` guild-notice frames reuse the canonical guild
  broadcast path.

## Gaps

- None in the 5-ID inbound family: all complete+tested in
  `tests/test_guildfuben.py` (22 tests: member/nonmember gates,
  master-only + money unseal, entry/state transitions, real-swing
  shared kills, objective completion, guild + personal rewards,
  duplicate-claim blocks, team-less side-by-side progress,
  disconnect/reconnect, login prune, weekly seal + cooldown,
  cross-session evict on exit/kick/disband, encrypted dispatch).
- Copy isolation is covered in `tests/test_stage_instances.py`
  (GuildCopyTest: shared member copy, two-guild isolation, quit-home
  plus disconnect cleanup) alongside the 22 handler tests.
- Next unfinished families per the census: `marry`, `kuafu`, `gm`
  residuals.

# PvP / Player Combat ledger

Oracle: `dntg_start.jar` fight pipeline recovered through `tools/javap.py`
(`BattleMode.convert`, `RoleBattleModeRelation.isEnemy`,
`SkillTargetFilterFactory.stageProtect`, `RolePkManager`,
`RoleEventManager` fireDeadEvent/hanlePkIncr/needGray/enterGrayState,
`FightServiceImpl` newerRevive/goodsRevive/changeBattleMode/pkValCheck/
redNameDropYxb, `PkUtil.calDropYxb`, `PkConfigExportServiceImpl.isRed`).

## Status: DONE

Role-vs-role combat, death, revival, gray/PK value, red-name drop and the
PvP kill-log line are ported and covered by `tests/test_pvp.py` (24 tests,
two sessions on one shared store/registry/clock). The xianjie deferred
item "PvP 91006 kill line (no role-death pipeline)" is now served: the
role-death pipeline exists.

## Commands

- `40600` C> int: `changeBattleMode`, sets the role's mode, answers
  nothing. Out-of-range values read as PEACE. Resets to PEACE on stage
  entry; not persisted.
- `42002` role targets: `SkillProcessHelper.fight` now filters role
  targets through the eligibility gates before any harm is rolled, and
  the 12004/42100/43000/42002 burst is pushed to the attacker's
  3x3 AOI surround (killer-only frames stay on the acting connection).
- `43002`: `newerRevive`, revive where you fell. Level 30+ gets the
  `[0]` notice first; HP/MP reset; `43002 [roleId]` to the surround.
- `43003`: `goodsRevive`, rose (`fuhuo`) revive in place. Living role is
  silent; missing rose answers `[0, 1012]`; success consumes one rose
  and revives like 43002. The manor-war `87060` refusal is deferred (no
  war system), not faked.
- `45000 [roleId, 1/0]`: gray-name enter/leave, to the surround.
- `45001 [roleId, pk]`: PK value change (kill gain, minute decay), to
  the surround.

## Eligibility (bytecode gate order)

Self, level-30 floor, PEACE, target's birth-protection buff
(`SkillTargetFilterFactory.stageProtect`, safe path node), then the
attacker's mode relation: GUILD spares same-guild (guildless attacker
hits everyone), TEAM spares same-team, ALL hits everyone, SHANE hits
only gray/red names. A rejected swing is silent. Starting a fight
strips the attacker's own protection buff even against a rejected
target.

## PK lifecycle (`game/pvp.py` + `role_stage.pk_info`)

- Gray: both killer and victim rows in an active `pkbiao` state
  (`need_gray`) start the 60 s gray stamp on attack; `S:FIGHT_PK_CHECK`
  clears it with `45000 [id, 0]`. Gray blocks PK gain.
- Gain: a role/pet kill earns the victim row's `addpk` (innocent 1, red
  rows 0), unless the killer is gray, SHANE or PKFREE. Broadcast
  `45001`, persisted through `save_role_stage`.
- Decay: `S:PKCHECK` minute tick; one point per span (`safespan` 60 min
  on safe nodes, `unsafespan` 30 min elsewhere), clock folds into
  `pk_info` on logout (`_pvp_on_disconnect`). Red is 7+.
- Red drop: `min(pk-3, 20)` stacks of 5,000 tongqian at the death tile
  as ownerless 150 s money items, capped at the purse; the 32010 money
  push follows. Money pickup credits tongqian (`30103 [1, 'money',
  count, itemId]`).
- Kill log: role-vs-role death writes the PvP `91006;{map|M};{user|ID,NAME}`
  line on the dead role's log. The `91007` monster line stays on the
  killer's own log at monster death; a role dying to a monster writes
  no log (no verified producer).

## Deferred (producer absent, not faked)

Manor-war `43003 [0, 87060]` refusal, PKFREE buff state source, guild-
war/alliance hostility (friendly-guild check reads not-allied), SHANE-
mode Erwerb sources, red-name guard attacks (`guardattack` rows are
config-only until the guard AI exists).

## Tests

`tests/test_pvp.py`: peace/safe/level/birth rejections, team/guild/
shane relations, strip-on-attack, gray broadcast, white-kill (no gain)
and red-kill (+1) with cross-session `45000`/`45001`/`43000` visibility,
decay tick and pre-span keep, red drop + money pickup, newer/goods
revive (success + `[0, 1012]`), battle-mode command, monster-kill
silence, `91006`/`91007` log placement.

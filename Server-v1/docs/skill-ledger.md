# Skills / skill books porting ledger

Authoritative per-entry status for the Java `skill` and `skillbook`
surface. Evidence: `dntg_start.jar` javap of `SkillAction`,
`SkillbookAction`, `SkillServiceImpl` (getSkill/upgradeSkill/
autoStudySkill/autoStudySkill2/createRoleStudySkill/
roleLevelUpgradeSkill/getSkillFighting), `SkillbookServiceImpl`
(getSkillBookInfo/moveSkillBook/peidai/xieZai/move/tunshi/yjTunshi/
checkUpgradeLevel/checkPeiDai), `RoleSkillExportServiceImpl`,
`SkillRoleCreateEventHandler` (role_create), `SkillRoleStudyEventHandler`
(role_level_upgrade), `StudySkillOutput`, `AddSkillEvent`/
`SkillUpgradeEvent`/`UseSkillBookEvent`, `ZhanDouLiModuleInit`
(add_skill/skill_upgrade -> `ZDL:SKILL_FIGHTCHANGE`), plus real
`JiNengBiao.jat`, `jinengshubiao.jat`, `ZhuJueShuXingBiao.jat`,
`ZuoJiBiao.jat` and goods rows.

Status words: complete+tested (wire-exercised), push-only (Java S2C
with no inbound handler, asserted in peer outboxes), genuine-Java-no-op,
deferred.

## Bus actions

| ID | Java method | Status | Notes |
| -- | ----------- | ------ | ----- |
| 42000 | getSkill | complete+tested | `[[category, level]]` per `role_skill` row; empty set answers `[]` |
| 42003 | upgradeSkill | complete+tested | gates in Java order: unknown 420005, level 100 cap 420010, skill >= role level 420006, shenjiang `bianshenneed` rank 420012, config `levelneed` 1000, zhenqi 1001, YXB 1003; costs burn before the `learnodds` roll; success `[1, category, level+1]`, failure `[-1]`; a missing JiNengBiao row stays silent (Java throws) |
| 99000 | getSkillBookInfo | complete+tested | worn mount/zuoqi book slots as `formart` maps; empty set answers `[]` |
| 99001 | moveSkillBook | complete+tested | band routing: bag->worn peidai, worn->bag xieZai, worn->worn move, bag->bag tunshi; 99000 bad slot, 99003 type band, 99004 slot unopened (per-band mutex), 99005 zuoqi rank, 99006 qibing level, 99007 `only` mutex, 99011 wing level, 99001 equipped target, 99002 eater at cap |
| 99002 | yjTunshi | complete+tested | validates every food first (99000/99001/99003/99002), then feeds in order, one 30106 push at the end, reply `[1, [eaterSlot, formart]]`; level-10 eater stops the list early; bound books carry their bind to the eater |

## Skill-book slot bands

`getType`/`isPeiDai`/`isMove` split worn books into three six-slot
bands, and `isOpenSlot` reads a *different* progression source per
band (SkillbookServiceImpl bytecode):

| Band | Slots | Config row | Open cell | Eligibility cell |
| ---- | ----- | ---------- | --------- | ---------------- |
| mount (zuoqi) | 10001..10006 | ZuoJiBiao keyed by `(stratum, ridelv)` | `mutexN` > 0 at the live rank, plus the role-level row | `zuoqilv` <= `getZuoQiRank` |
| qibing | 10031..10036 | `qizhanbingqi.jat` keyed by `rideweapon` | `mutexN` > 0 for `isOpen(binqiLevel, slot-10030)`, read from the **raw** `binqi_level` (a lapsed guoqi trial still counts) | `qibinglv` <= `getQizhanBinLevel` |
| wing | 10051..10056 | GuangYiBiao level rows | `mutexN` > 0 for `isOpenSkillSlot(level, slot-10050)` | `chibanglv` <= `getGuangYiLevel` |

Shipped `qizhanbingqi.jat` has 7 rows: level 1 opens nothing, level
2 opens 10031, and each further level opens one more slot (level 7
opens all six). A role without a `role_qizhanbinqi` row therefore
answers 99004 for the whole band, exactly like Java's empty source.

## Server pushes (server -> client, no client command)

| ID | Producer | Status | Notes |
| -- | -------- | ------ | ----- |
| 42004 | autoStudySkillWithNotify | push-only | `[skillCategory, 1]` after a learn: level-up learns, prop study, `useSkillBook` |
| 30106 | skillbook tunshi | push-only | book-exp refresh after a devour (documented in the item ledger) |

## Learning paths

| Path | Java source | Status | Notes |
| ---- | ----------- | ------ | ----- |
| role create | `P:ROLE_CREATE` -> SkillRoleCreateEventHandler -> createRoleStudySkill | complete+tested | level-1 ZhuJueShuXing `learnskill` tokens, level-1 JiNengBiao row, **needjob gate only** (no owned lookup, no levelneed, no autolearn, no 42004); `insert2DB` per token |
| level up | `P:ROLE_LEVEL_UPGRADE` xN -> roleLevelUpgradeSkill | complete+tested | per gained level, each `learnskill` token via autoStudySkill(needAutoLearn=false): owned skip, no config row skip, levelneed > level skip, needjob mismatch skip; each learn pushes 42004 |
| prop study | `useSkillBook` (goods `zuoqibookskillid` -> `jhzqjn`) -> autoStudySkill2 | complete+tested | served by the `skillBook` prop branch of 32001: 100008 no config, 420007 already owned, 420008 level, 420009 job; consumes the book then pushes 42004 (Java notifies even when the level-1 row's own level is above the role, a dead branch for shipped rows) |
| skill upgrade | upgradeSkill success | complete+tested | inserts level+1 (no 42004; SkillUpgradeEvent publishes with no subscribers) |

`createRoleStudySkill` is a genuine-Java-no-op with the shipped data:
the level-1 tokens are `mb;yx;bh;lx`, whose JiNengBiao `needjob` cell is
empty, and Java's gate rejects anything that is neither `'0'` nor the
role's job. The port reproduces that (nothing is seeded), and the
fixture suite in `tests/test_skill.py` exercises the real contract with
rows that do carry jobs.

Java's last autoStudySkill branch (the level-1 row's own `level` above
the role level) jumps to `return true` **without** inserting, so the
caller still notifies; with roles at level >= 1 and a row loaded at
level 1 it is unreachable, so the port does not carry it.

## Combat, cooldowns, costs

No separate combat-stat layer: `role_skill` rows feed
`GameConfig.skill_fight` (the 12010 `[skill, kangxin]` slots from
JiNengBiao `tabshow`/`combat`), 42002 resolves the fired category
against JiNengBiao and the role's live attributes, and 42005 uses
`CdBiao` `cdtime` scaled by the role's `gongjisudu`. Upgrade costs
(zhenqi/YXB) and the `learnodds` roll are the only resource sinks in
the skill module. Passive contributions arrive through the same 12000
attribute map that combat reads.

## Events

`AddSkillEvent` (`add_skill`), `SkillUpgradeEvent` (`skill_upgrade`) and
`UseSkillBookEvent` are published in Java. Their only registered effect
is the ZhanDouLi refresh command (`ZDL:SKILL_FIGHTCHANGE` ->
`ZDL:JINENG_FIGHT` + `ZDL:SKILL_KANGXIN`); no other handler subscribes
jar-wide. Per port convention events ride no bus, so they are skipped.

## Deferred / gaps

- ~~**12010 fight refresh push.**~~ Done in the ZhanDouLi slice:
  `_skill_auto_learn` and `skill_upgrade` mark the shared fight-change
  flag, so a learn or upgrade pushes one coalesced 12010 after the
  command's own frames (see docs/zhandouli-ledger.md).
- **Skill resets / replacement.** None exist in the jar: SkillServiceImpl
  has no delete/reset/forget entry and no inbound command consumes
  `role_skill` rows. Nothing to port.
- **Skill activation/equipping.** The client fires by category (42001/
  42002) and there is no server-side loadout or skill-bar table; the
  "equipped" surface is the mount/zuoqi/qibing/wing skill-book slots
  (99000-99002), already complete.
- ~~**Zuoqi book fight bucket (12010 [13]).**~~ Wired: `_fighting_frame`
  now calls `_skillbook_band_fight(role, SKILLBOOK_ZUOQI)` for slot
  [13], matching `setZuoqiBook`/`getZuoQiSkillBookZhanLi`.
- **Skill-book passive effects.** Books only feed the 12010 band sums
  (JiNengBiao `combat` through `loadSkillInfoByLevel`); the jar's
  `SkillBookChangeEvent` has no combat-handler subscriber beyond
  `ZDL:*SKILLBOOK`, so no battle-stat layer is missing here.
- **`getSkills` / `getSkillNumber`** (shenjiang and zuoqi wrappers'
  skill maps) are consumed by those families, not by a skill command.

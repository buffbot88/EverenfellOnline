# Character progression / level-up porting ledger

Authoritative per-entry status for the Java level and derived-stat
surface. Evidence: `dntg_start.jar` javap of `UserRoleServiceImpl`
(calUpgradeAndExp/isManji/incrExp/decrExp), `RoleExportServiceImpl`
(incrExp x3, upgradeLevel), `RoleAttributeServiceImpl.roleUpgrade`,
`SkillServiceImpl.roleLevelUpgradeSkill/autoStudySkill`,
`StudySkillOutput.autoStudySkillWithNotify`,
`FightOutputWrapper.outputAttributeChange`,
`ShengJiEventHandler` (role_level_upgrade -> shengJiRecevieMainTask),
plus `ZhuJueShuXingBiao.jat` (95 shipped levels) and the ported
50004 receive chain.

Status words: complete+tested (wire-exercised), parity-unverified
(dispatched but not byte-compared against Java), partial, stub,
genuine-Java-no-op, not-an-inbound-command.

## Service methods

| Java method | Status | Notes |
| ----------- | ------ | ----- |
| calUpgradeAndExp | complete+tested | `combat.apply_exp_gain`: cap banks with no level-up; else each rung with total >= needexp spends it for +1 level and a zeroed bar, recursing on the remainder; unknown needexp banks |
| isManji/loadMaxLevel | complete+tested | `role_max_level` (95 shipped); `role_need_exp` per-level cell |
| RoleExportService.incrExp | complete+tested | `_role_gain_exp`: persists level/exp/max_hp/max_mp, refreshes the role dict, 12001 `[expTotal, level]` leads, then one fan-out per gain |
| RoleLevelUpgradeEvent xN | complete+tested | one event per gained level in Java; the port loops intermediate levels for skill learns and checks the quest gate at the final level (outcome-equivalent: the gate is monotonic in level) |
| roleUpgrade | complete+tested | level row swap + max_hp/max_mp persist; 12000 full map (Java sends changed-attrs only: superset), 12004 unconditional (Java sends only on hp/mp change: superset), 12002, skill learns, quest unlock; current hp/mp unchanged (no refill in Java) |
| outputAttributeChange | complete+tested | 12004/12000 shapes ported; 12005 `[shanbiVal]` self-only on change (dunshandian is flat across all 95 shipped rows, so it stays silent in practice, like Java's conditional); the SHANBI_RECOVERY schedule has no ported scheduler |
| 12002 routing | complete+tested | surround-routed via the registry broadcast (own copy returned), like roleUpgrade's surround 12002; 12004 likewise surround, 12000/12005 self-only |
| roleLevelUpgradeSkill | complete+tested | per-level learnskill tokens through `_skill_auto_learn` (owned / no-row / levelneed / needjob gates, matching autoStudySkill with needAutoLearn=false); each learn pushes 42004 `[skilltype, 1]`; AddSkillEvent has no ported subscribers. Details in docs/skill-ledger.md |
| createRoleStudySkill | complete+tested | `P:ROLE_CREATE` -> `_skill_create_learn`: level-1 learnskill tokens with the needjob gate only (no owned lookup, no levelneed, no 42004); a no-op with the shipped `mb;yx;bh;lx` data whose needjob cell is empty |
| shengJiRecevieMainTask | complete+tested | `_task_on_level`: paid quest whose next recevie_level is met receives through the shared cascade (`_task_receive_next`, also used by dataCheck) |
| upgradeLevel | deferred | GM-style direct-level path; no GM commands exist in the port |
| decrExp/decrExpCheck | deferred | no ported caller spends role exp |
| upgradeTime | deferred | set per level-up in Java but no characters column carries it, so it is not persisted |

## EXP sources routed through `_role_gain_exp`

Monster kills, dazuo timers, jianding exp, shenjiang jihuo
(fail/success addExp), grow-prop exp, bag unlocks, bag-skill prop
exp, main-quest rewards, taofa pay, richang pay, juqing claim/onekey,
zuoqi fail pity. Every source persists through the same path, so
level-ups (with 12000/12004/12002/learn/unlock tails) fire no matter
which system grants the EXP.

## Derived stats and combat

No new stat system: `_fighter_attrs` already reads the live 12000 map
(level row + gear/dan/xianjie/chenghao/meiren/baoshi/zuoqi bags + VIP
effect slots), so level-ups and equip/unequip flow into combat without
further wiring. Rewards that overflow the bag mail instead of dropping
(quest/equip paths); reward mail overflow itself stays a drop with a
warning, as ledgered before.

## Tests (12 new in `tests/test_level.py`)

Threshold/exact-spend/remainder-chain/cap-bank/unknown-table math;
12001-first framing, 12000/12004/12002 order, no-refill max update,
SQLite persistence + reconnect visibility, 4-skill learn at level 5
with dupe suppression, cap silence, paid-quest unlock at the gated
level, `_fighter_attrs` tracking the new map, equip add/remove
recomputation through `_fighter_attrs`.

Focused suites run: test_level, test_task, test_taofa, test_richang,
test_combat, test_equip, test_effect_bags, test_baoshi, test_skill,
test_shenjiang, test_juqing_fuben, test_juqing_zuwu, test_zuoqi,
test_zuwufuben, test_bag (all green). test_protocol had one stale
failure (TestWorldInit asserted storeless 64010/64001/108001 bodies,
but those handlers have required a role since the story-dungeon port;
role-backed coverage lives in test_juqing_zuwu/test_juqing_fuben/
test_zuwufuben): fixed to assertIsNone without touching code.

## Equipment/attribute gap survey (this batch)

Merged real bags for a geared role (capture gear + xianjie + chenghao
+ dan + zuoqi + vip10): only the 8 flat keys plus tiny fujia
mb/mbdk/yxdk/bhdk/xxdk control cells. No shipped source carries
pojia/qiege/shishen/damage/defence/criticalb/c/gedang/poji or
lei/mu/shui/hu/tu elementals, so the combat pipeline's zero defaults
match what Java computes from the same tables. The remaining exotic
sources are active fight buffs (unmigrated buff wiring, a separate
subsystem) — not a small gap, so no new stat system was built.
Monster dodge/dodgedefence/mbdk cells likewise feed only the unported
DiKang path; T7/T8 use baoji/volt, already ported.

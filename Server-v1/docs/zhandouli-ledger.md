# ZhanDouLi / combat-attribute synchronization ledger

Authoritative status for how combat-attribute changes reach the
client. Evidence: `dntg_start.jar` javap of `ZhanDouLiModuleInit`
(event -> `ZDL:*` command table), `ZhanDouLiServiceImpl`
(`changeFight`/`changeFightValue`/`getClientFighting`/
`getZhanDouLiWrapper`), `ZhanDouLiAction` (`getRoleFight`, one method
per change command), `ZhanDouLiWrapper` (25-slot `getFightObject`),
`BusMsgQueue` (`ClientMsg.flush` -> `send2One`), and the producer
bytecode already cited in `skill-ledger.md`, `level-ledger.md`,
`marry-ledger.md` and friends.

## Java chain

1. A producer publishes its event (e.g. `AddSkillEvent`/`add_skill`).
2. `ZhanDouLiModuleInit` maps that event to a command
   (`add_skill` -> `ZDL:SKILL_FIGHTCHANGE`, `role_level_upgrade` ->
   `ZDL:SKILL_FIGHTCHANGE` + `ZDL:ROLELEVEL_FIGHTCHANGE` +
   `ZDL:ZUOQI_FIGHT`, `equip_change` -> `ZDL:EQUIP_FIGHTCHANGE` +
   `ZDL:ZUOQI_EQUIP_FIGHT`, ...).
3. `ZhanDouLiAction` calls the matching `ZhanDouLiServiceImpl` method,
   which runs `changeFight(roleId, bucket)` for each affected bucket.
4. `changeFightValue` stores the new bucket in `RoleZhanDouLi` and ends
   with `send2BusInner(roleId, "12010", null)`.
5. The inner 12010 lands on `getRoleFight`, which builds
   `getClientFighting` -> `getFightObject()` and
   `BusMsgQueue` flushes a **client push** of 12010.

So the Java 12010 push is a full 25-slot wrapper sent to the role
itself (`send2One`); it is not a broadcast, and it is not one of the
`outputAttributeChange` codes (12000/12002/12004/12005).

## Port mechanism

- `Session._fight_changed()` marks `_fight_dirty`; producers call it
  only after the state write succeeded.
- `_feed_unlocked` appends `_fight_refresh_frames()` once per inbound
  frame, after the command's reply and after the queued 70520 pushes;
  `_tick_unlocked` does the same at the end of a tick so scheduled
  work (exp timers, ai ticks, queued cross-session ops) refreshes too.
- `_fight_refresh_frames()` builds the wrapper from the live rows
  (`_fighting_frame`), clears the flag, and answers nothing when there
  is no role or no config.
- Delivery is self-only: no registry push, no surround.

Deliberate deviation: Java fires one inner 12010 per `changeFight`
call, so a level-up with three buckets pushes the wrapper three times
with identical data. The port coalesces to **one** push per request
carrying the final values (the wrapper is rebuilt, not accumulated),
which is outcome-equivalent for the client and avoids duplicate
traffic.

## Producers wired

| Producer | Event / command | Buckets | Where |
| -------- | --------------- | ------- | ----- |
| skill learned (create-time, level-up, prop book) | `add_skill` -> `ZDL:SKILL_FIGHTCHANGE` | [2] | `_skill_auto_learn` |
| skill upgraded | `skill_upgrade` -> `ZDL:SKILL_FIGHTCHANGE` | [2] | `skill_upgrade` success |
| level up | `role_level_upgrade` -> `ZDL:SKILL_FIGHTCHANGE` + `ZDL:ROLELEVEL_FIGHTCHANGE` + `ZDL:ZUOQI_FIGHT` | [1], [2], [3] | `_role_gain_exp` (only when a level was gained) |
| equip worn/removed, jianding (worn gear), qianghua, qianghua clear/max, jinjie | `equip_change` / `equip_jianding` -> `ZDL:EQUIP_FIGHTCHANGE` + `ZDL:ZUOQI_EQUIP_FIGHT` | [0] | `_equip_persist`, `_equip_persist_worn` (only after a successful save), `equip_jinjie` success. Bag-living gear appraisals skip it: they move no worn bucket. `equip_hecheng` only fuses materials into a scroll, so it has no gear write to refresh |
| gem socket / level up | `baoshi_jihuo` / `baoshi_level_upgrade` -> `ZDL:BAOSHI_FIGHTCHANGE` | [4][0] (0 in port) | `_baoshi_save` (only when the save returned True) |
| mount claimed / rank up | `zuoqi_change` -> `ZDL:ZUOQI_FIGHT` | [3] | `zuoqi_claim`, rank-up success |
| LongHun/LongLing pill | `zuoqi_useprop_longHun` -> `ZDL:LINGLONGLINGHUN` | [3][2] | `_prop_longdan` success |
| attribute dan | `attributebuff_change` -> `ZDL:SHUXINDAN` | [9] | `_prop_dan` success |
| qibing trial grant / upgrade / BingHun-BingLing pill | `qizhanbinqi_lingqu` / `qizhanbinqi_upgrade` -> `ZDL:QIZHANBINQI` / `ZDL:BINHUN` | [10] | `qibing_getbinqi`, upgrade success, `_prop_qibing_dan` |
| shenjiang activation / skill up | `shenjiang_activate` -> `ZDL:SHENGJIANG_SKILL_FIGHT`, `shenjiang_skill_upgrade` -> `ZDL:SHENGJIANG_SKILLUPGRADE` | [6][2] | activation and skill-up saves |
| VIP level up | `vip_Level_upgrade` -> `ZDL:VIP_FIGHT` | [5] | `_vip_upgrade` |
| pozhen layer cleared | `pozhen_tongguan` -> `ZDL:POZHENG_FIGHT` | [7] | sweep award paths |
| wing granted/upgraded, card, attribute dan | `guangyi_upgrade_level` / `guangyi_attribute_use` -> `ZDL:GUANGYI` (+ `ZDL:GUANGYI_ATT_DAN`) | [16] | `_guangyi_grant`, `guangyi_upgrade` success, `_prop_guangyi_dan`. Wear (102003) publishes only `guangyi_change`, which no ZDL command maps |

## Slots with no in-port producer (documented, not wired)

`_fighting_frame` reports 0 for these because their source commands or
tables are not ported, so no change can move them yet:

- [4][0] gem **effect** (`baishixiaoguo`) and [0][3]/[0][4] gear effect
  buckets: no attribute-bag source writes them.
- [8] meiren, [11] xianjie, [12] chenghao, [13]/[14] mount/qibing skill
  books, [15] taozhuang, [17] wuhun, [18] touxian,
  [19] zuwu, [20] guild, [21] yuanshen, [22] shenqi, [23] pet zhanfa /
  heti, [24] hunjie: the wrapper's Java buckets exist, but the port
  either has no inbound family (xianjiechenhao, shenqi,
  yuanshen, touxian, wuhun) or computes the value only for 12000.
- [6][0] shenjiang rank fight and [6][1] jiangxing: not modelled.

When any of those families lands, its change point only has to call
`_fight_changed()`; the wrapper already carries the slot.

## Not conflated with other codes

- 12000 (full attribute map), 12004 (hp/mp), 12005 (shanbi), 12002
  (role-upgrade notice) and 12001 (exp notice) keep their existing
  producers in `_role_level_frames` / `_role_gain_exp`.
- 12010 is the wrapper push and nothing else; it never rides the
  surround loop and never doubles as an attribute map.

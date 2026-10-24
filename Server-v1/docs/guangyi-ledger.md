# Wings (GuangYi) ledger

Source of truth: `GuangyiServiceImpl`, `GuangYiExportServiceImpl`,
`GuangYiConfigExportServiceImpl`, `GuangyiAction`, `RoleGuangyi.xml`,
`PropServiceImpl$GuangYi` / `$GuangYiUseAttribute` and the
`ZhanDouLiServiceImpl.getGuangYi*` readers, traced with `javap` against
`dntg_start.jar`. Config rows come from `sys_config/guangyi.jat` (nine
bands, `rideweapon` 1..9).

## Commands

| ID | Action | Status | Notes |
| -- | ------ | ------ | ----- |
| 102000 | `getinfo` -> `guangyiInfo` | complete + tested | `null` with no row; `[worn, level, lucky, wearing, [[dan, count]...]]` |
| 102001 | `upgrade(Boolean)` | complete + tested | pity upgrade; `C>` must be a Boolean or the request is silent |
| 102002 | `buyGuangYi` | complete + tested | charges `cost` in YB, then `propJiHuo(1)` |
| 102003 | `qiehuan(Integer)` | complete + tested | pick / toggle / hide; `[1, worn, wearing]` |
| 102005 | constant only | unhandled | declared in `GuangyiCommands`, absent from `InCmd` and from `GuangyiAction` |

Props (30301 `PropStageAction.consumeGoods` skill switch):

- 49 -> `PropServiceImpl$GuangYi` -> `propJiHuo(goods.zqshengxian)` (the
  `guangyi01` activation card).
- 50 and 51 -> `PropServiceImpl$GuangYiUseAttribute` ->
  `useAttributeDan(roleId, goodsId)` (`yihun`, `yiling`).

## Progression

`upgrade` (102001):

1. `clear()` — before anything else, a row whose `luckyclear` level row
   last ticked on an earlier day drops `failCount` and `luckyValue` and
   stamps `updateTime`. Level 1's `luckyclear` is 1, so this applies to
   every band.
2. Next level must exist, else `[0, 1000]` (LEVEL_NOT_ENOUGH).
3. Role level below the current row's `needleaderlv` -> `[0, 1000]`.
4. `decrCheck(YXB, jinjieneedcoin)` short -> `[0, 1003]`; every shipped
   row carries 0, so this is dormant but ported.
5. `checkSpecialTypeGoodsMoneyEnough({needthingsid: needthingsvalue},
   level, useGold)` — the same bag planner the qibing/baoshi flows use
   (`_baoshi_material_plan`); a refusal answers the plain `[0, code]`
   pair from `GetEquipSlotOutPut.getCodeError(error, null)`.
6. Costs burn: goods (with specialtype substitutes) and `jinjieneedcoin`.
7. `isSuccess(failCount, cfg)`: below `mintims` always fails; inside
   `mintims..maxtimes` it rolls `odds`; above `maxtimes` always succeeds.
8. Failure banks `Lottery.randomInt(addminblessing, addmaxblessing)`
   blessing; reaching `maxblessing` clamps and forces the success. The
   reply is `[-1, level, lucky]`; `updateTime` is stamped and
   `failCount` grows.
9. Success sets `level + 1`, clears `lucky`/`failCount`, stamps
   `upgradeTime`/`updateTime`, auto-wears the new level
   (`peidaiId = level`, `ispeidai = 1`), and broadcasts
   `11101 [102000, [name, level, nextName]]` unconditionally, then
   answers `[1, level, 0, 1]`.
10. Either outcome publishes `ZDL:GUANGYI` -> the shared coalesced
    12010 (see `zhandouli-ledger.md`).

Buy (102002) charges the row-1 `cost` cell (100) in YB through
`decrCheck`/`decr`; `needthingsid`/`needthingsvalue` are the *upgrade*
cost and are not touched at purchase. The grant then runs `propJiHuo`,
which:

- inserts a level-1 row (ignoring the requested level) with
  `peidaiId = 1`, `ispeidai = 1`, `lingquTime`/`upgradeTime`/
  `updateTime` = now and `attributeDan = "{}"`; or
- raises an owned row to a strictly higher requested level, else
  answers `[0, 102001]`;
- pushes `102002 [1, level, lucky]` and publishes
  `guangyi_upgrade_level` + `guangyi_change` -> `ZDL:GUANGYI`.

Wear (102003): `id == null` toggles `ispeidai` (0/absent -> 1, else 0);
an id above the owned level answers `[0, 102002]`; otherwise it becomes
`peidaiId` and `ispeidai` is left untouched (the jar never re-wears on a
pick). The reply is `[1, peidaiId, ispeidai]`.

Dan (`useAttributeDan`, props 50/51):

- No wing row: the jar throws on the one-cell result; the port is
  silent, matching the other "Java NPE -> no frame" paths.
- Cap comes from the row's own level: `xlimit` for `yihun`,
  `perxlimit` for `yiling` (level 1/2 `yihun` cap is 0, level 3 is 100,
  level 4 `yiling` is 10, ...). Over the cap answers `[0, 87104]`.
- Success bumps the `attributeDan` map, persists, and the export sends
  an inner `102000` (the panel) before the pipeline's terminal
  `[1, bagId]`; `guangyi_attribute_use` publishes `ZDL:GUANGYI` and
  `ZDL:GUANGYI_ATT_DAN` -> one coalesced 12010.

Card (prop 49): `propJiHuo(goods.zqshengxian)`; every shipped card
leaves `zqshengxian` blank (0), so a fresh purchase grants level 1.
`PropServiceImpl$GuangYi` returns `result[1]` on every path, which the
pipeline frames as `[0, <that>]` and its early return skips the
post-consume block: a granted card pushes `102002 [1, level, lucky]`,
then answers `[0, 1]` and **stays in the bag**; an owned level answers
`[0, 102001]` with nothing pushed (Java quirk, golden-pinned).

## Storage

`role_guangyi` (one row per role, `RoleGuangyi.xml`): `peidai_id`,
`level` (binqiLevel), `lucky` (luckyValue), `ispeidai`, `attr_dan`
(attributeDan JSON), plus `fail_count`, `upgrade_time`, `lingqu_time`
and `update_time` for the pity window and the daily reset. Older
databases gain the four columns through the `Store` migration.

## Combat integration

- 12010 slot `[16]` is `ZhanDouLiWrapper`'s guangyi triple:
  - `[16][0]` `getGuangYiZhanli`: `getFight` over the level row's
    `attribute2Map` (hitpoints, mana, physicdamage, physicdefence,
    critical, volt, attackrate, velocity, ...).
  - `[16][1]` `getGuangYiAttDanZhanli`: skill-50 pills add their goods
    `attributeMap` once per count; skill-51 pills add the wing level's
    own bag scaled by `sxbfb` per count; then `getFight`.
  - `[16][2]` `getGuangYiSkillBookZhanLi`: sum of
    `loadSkillByLevel(skillid, skillbooklevel).combat` over the worn
    skillbook slots 10051..10056. It counts without a wing row (Java
    never checks the level).
- 12000: `replaceGuangYiAttribute` increments `BaseAttributeType.GUANGYI`
  with the level bag plus the same dan contributions; `role_bags` now
  appends that bag, so the entry attribute map keeps matching the jar.
- Skillbook eligibility: `chibanglv` gates now compare against the live
  wing level (99011 below it) instead of treating the wing as absent,
  and `isOpenSlot` for the 10051..10056 band reads the level's
  `mutex1..6` cells (`isOpenSkillSlot(slot - 10050)`).
- Huodong ct-31 (`getChiBangReward`) keeps reading the same
  `role_guangyi.level`; no monetized event changed.

## Gaps

- 102005 has no Java handler and stays unhandled.
- The 11101 wing notice is emitted on the actor's outbox: the port has
  no cross-session broadcast bus (same as every other 11101 notice).
- The qibing skillbook band still answers closed (its table was never
  migrated) and `qibinglv` books stay gated; both belong to that family.
- Wing skill books' own exp/upgrade flow stays in the skillbook family
  (`skill-ledger.md`); this slice only feeds their fight sum and gates.

## Tests

`tests/test_guangyi.py` (28): panel/null/clear, buy price and owned
code, upgrade gates, below-mintims failure and blessing, blessing cap,
forced success with the 11101 notice and 12010, max-level gate, wear
pick/limit/toggle/silence, both dan kinds with caps and the panel push,
card grant/refusal quirks, 12000 bag and 12010 slot [16], skillbook
fight sum and wing-band eligibility.

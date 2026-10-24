# Xianjie / Chenghao (仙阶 / 称号) ledger

Authoritative status for the Java `xianjiechenhao` and `xianjiehuoyuedu`
families. Evidence: `dntg_start.jar` javap of
`XianjiechenhaoAction`, `XianjiechenhaoServiceImpl`,
`XianjiechenhaoModuleInit` (39 event handlers),
`XianJieConfig`/`ChengHaoConfig` + their export services, `XianJieData`,
`RoleXianjiechenhao`, `XianjiechenhaoErrorCode`, the module's
`event/publish` classes, and the real `xianjie.jat` / `chenghao.jat`
rows. Do not treat the command family alone as "done": the value is the
event-driven title progression.

## Commands

| ID | Java entry | Status |
| -- | ---------- | ------ |
| 91002 | `getXianJieHuoYuedu` -> `getxianJieChengHaoData` | portable now |
| 91003 | `upgradeChengHao(role, id)` | portable now (needs huoyue) |
| 91004 | `qiyongchneghao(role, id)` -> `qiYongChengHao` | portable now |
| 91005 | `getLog` -> `roleDie` page | needs RoleDie table |
| 91006 | push-only: `[chenghaoId]` on every auto-activation | push-only |
| 91007 | `jishaLog` -> client kill-log append | needs RoleDie table |
| 91008 | `S:91008` server-only route | push/handler internal |
| 91009 | `jiHuoChengHao` -> `jihuoChengHao(role, config.limit1)` | portable now |

`XianjiechenhaoErrorCode` is a constant bag `91001..91010`, used as the
second element of `[0, code]` failures and as notice ids.

## Persistence

`role_xianjiechenhao` carries `xianjie_qiyong` (selected rank),
`xianjie_id` (JSON array of owned rank ids), `chenhao_id` (JSON array of
owned title ids), `xianjie_data` (fastjson `XianJieData`), `xianjie_time`
and `log_update_time`. The port's table currently has only the two id
arrays; the other columns are the missing schema step, and its
`xianjie_id_for`/`chenhao_ids_for` ports already match Java's
`getXianjieId` (string-max of the array, `'1'` when empty, `None`
without a row) and `chenHaoIds`.

`getPeiDaiChenHaoId` returns `xianjie_qiyong`, not a title.

## Xianjie rank (91003)

`xianjie.jat` has 8 rows: `id`, `mingcheng`, `shuxing` (attribute map),
`huoyue` (required activity), `gonggao`. Attributes are 150/1000/3000/
6250/11250/20000/33750/52500 activity for ranks 1..8.

`upgradeChengHao`:

1. id other than `"1"` requires the previous rank owned, else
   `[0, 91001]`.
2. already owned -> `[0, 91002]`.
3. missing config row -> silent `null`.
4. `xianjiehuoyuedu.getHuoYueDu(role) < config.huoyue` -> `[0, 91003]`.
5. append the id to `xianjie_id`, save.
6. publish `XianJieChenHaoDuiHuanEvent(role, id, huoyue)`.
7. if `gonggao`: world notice `11101 [91010, [roleName, mingcheng]]`.
8. push `91004` to the role with the new id.
9. re-run `jihuoChengHao` for **every** title type (`getIds().keySet()`).
10. reply `[1, id]`.

## Titles (91002 / 91006 / 91009)

`chenghao.jat` has 72 rows: `chenghaoid`, `chenghao` (name), `xianjieid`
(required rank), `shuxingjiacheng` (attribute map), `gonggao`,
`limit1` (condition type), `value1` (thresholds), `value2` (ids),
`chenghaoicon`, `jishu`, `miaoshu1..3`, `jialibangdingyuanbao` (bind-YB
**reward** paid on activation).

`jihuoChengHao(role, type)`:

- role level must be >= 20, else no-op.
- for each title of that type, in config order: skip when already
  owned, when `value1` is null, when the required `xianjieid` is not
  owned, or when its condition fails.
- on success: append the id, save, credit
  `jialibangdingyuanbao` bind YB, push `91006 [id]`, publish
  `XianJieChenHaoJihuoEvent`, and broadcast
  `11101 [91009, [roleName, chenghao]]` when `gonggao`.

`getxianJieChengHaoData` first re-runs every title type, then answers
`[xianjie_qiyong, huoyue, max owned rank, owned title ids, showData[]]`,
where `showData[i] = [chenghaoid, <live progress cells...>]` (for
example `[id, signInCount]`, `[id, bagUsed, bagCap]`, `[id, storyBuy,
storySell, storyBack]`).

`qiYongChengHao` only accepts an owned rank id, saves it as
`xianjie_qiyong`, publishes `XianJieChenHaoQiYongEvent` and answers
`[1, id]`; anything else is silent `null`.

## Condition engine (`ischeck`, `limit1`)

`limit1` is the title's own condition number (1..27), not the
`XianjiechenhaoServiceImpl.DataType` enum used by `changeData`. Counters
live in `XianJieData` (fastjson field names in parentheses).

| limit1 | Condition | Source / cells |
| ------ | --------- | -------------- |
| 1 | total sign-ins >= v1[0] | jiangli `getTotalQiandaoCount` |
| 2 | bag used >= v1[0] **and** storage used >= v1[1] | bag `getbagStorageNumber` |
| 3 | story_buy >= v1[0], story_sell >= v1[1], story_back >= v1[2] | XianJieData |
| 4 | onhook minutes >= v1[0] | XianJieData |
| 5 | kill_monster **>** v1[0], kill_ghost >= v1[1], kill_god >= v1[2] | XianJieData |
| 6 | friend count >= v1[0], foe count >= v1[1] | friend `getFriendNumber` |
| 7 | zuoqi rank >= v1[0] **and** worn zuoqi books >= v1[1] | zuoqi + skillbook |
| 8 | wing level >= v1[0] **and** worn wing books >= v1[1] | guangyi + skillbook |
| 9 | shenjiang finished(v1[0]) **and** count >= v1[1] | shenjiang |
| 10 | skill count >= v1[0] **and** max level >= v1[1] | skill |
| 11 | has guild **and** banggong >= v1[1] | guild |
| 12 | has team | team |
| 13 | store_yb >= v1[0] **and** store_bind >= v1[1] | XianJieData |
| 14 | fuben_finish >= v1[0] **and** fuben_saodang >= v1[1] | XianJieData |
| 15 | task_finish >= v1[0], task_tunshi >= v1[1], task_miaosha >= v1[2] | XianJieData |
| 16 | meiren count >= v1[0], chanmian count >= v1[1] | meiren |
| 17 | qibing level >= v1[0] **and** worn qibing books >= v1[1] | qibing + skillbook |
| 18 | worn gear >= v1[0], quality count >= v1[1] | equip |
| 19 | fight **>** v1[0] | zhandouli |
| 20 | equip_qianghua >= v1[0] **and** seven-star gear >= v1[1] | XianJieData + equip |
| 21 | tanwei_sell >= v1[0], tanwei_buy >= v1[1] | XianJieData |
| 22 | dazuo_time >= v1[0] | XianJieData |
| 23 | baoshi counts **[1] >= v1[0] and [0] >= v1[1]** (swapped) | baoshi |
| 24 | xianhua/popularity [0] >= v1[0], [1] >= v1[1] | rank |
| 25 | always false | - |
| 26 | v1[0] <= sjjd_putong **and** v1[1] <= sjjd_vip | XianJieData |
| 27 | `value2` task ids finished (both when two) | task |

`changeData(role, DataType, delta)` increments one XianJieData cell,
saves, and then calls `jihuoChengHao(role, DataType.type)` so the
affected title family re-evaluates. `client(role, "4", [minutes])` adds
ONHOOK; `client(role, "22", [minutes])` adds DAZUO_TIME.

`DataType` ordinals are copied verbatim in the jar, which makes the
`changeData` field map surprising: STORE_BUY -> `story_back`,
STORE_BACK -> `story_buy`, STORE_SELL -> `story_sell`, then ONHOOK,
KILL_MONSTER, KILL_GHOST, KILL_GOD, FUBEN_FINISH, FUBEN_SAODANG,
TASK_MIAOSHA, TASK_FINISH, TASK_TUNSHI, EQUIP_QIANGHUA, TANWEI_SELL,
TANWEI_BUY, DAZUO_TIME, LINGQIDAN_COUNT, STORE_BIND, STORE_YB,
SJJD_PUTONG, SJJD_VIP in that order.

## Huoyue (activity) dependency

`upgradeChengHao` cannot pass rank 1 without
`IXianJieHuoYueDuExportService.getHuoYueDu`, i.e. the
`xianjiehuoyuedu` family: commands 90000/90001/91000/91001,
`MeiRiHuoYue.jat` (daily caps per type) + `HuoYueJiangLi.jat` (reward
ladder), `HuoYueDuType` 1..21 (VIP, STORE, STORE_YB, JINDIANZHANYI,
SHENJIANGJINDI, RICHANGRENWU, PK_SHEGUAI, GUIJIANGJINYING,
SHENJIANGDOSS, LINGQI, EXP, MEIRICHANMIAN, QIQIN, GUANGHANGONG,
MEJIERUQING, EQUIP_JIANDING, FENGSHENGZENGBA, TEAMFUBEN, BAIXIAN,
WEIDUAN, BAIXIAN_YXB) and ~20 subscribers feeding it. This is the
prerequisite slice for rank progression.

## Event sources (39 subscribers in the module)

`XianJieChengHao*EventHandler` classes map existing gameplay events to
either a `changeData` counter or a `jihuoChengHao` re-check: online,
bag back/sell/open, booth buy/sell, mall buy, juqing fuben
finish/saodang, miaosha task, tunshi task, monster death, daily task,
history die monster/role, friend/foe add, team add, baoshi activate/
upgrade, equip change/qianghua, gonghui 1/2/3, meiren chanmian/obtain,
qibing jinjie, rank xianhua, shenjiang jinjie/activate/upgrade, skill
upgrade, zhandouli change, zuoqi skill study/upgrade, wing upgrade,
skillbook change and zuoqi skillbook change. Each must fire only after
the underlying gameplay action succeeded; the port's existing systems
already expose the corresponding write points.

## Port plan / status

1. Schema: add `xianjie_qiyong`, `xianjie_data`, `xianjie_time`,
   `log_update_time` to `role_xianjiechenhao` (plus the `role_die` log
   table for 91005/91007).
2. `xianjiehuoyuedu`: daily accumulation with per-type caps, the
   90000/90001/91000/91001 surface and its ~20 producers.
3. Xianjie rank: 91003 + the `91004` self push, 91002 rank cells,
   `_fight_changed()` on a new rank (12010 [11]) and the 12000 bag.
4. Titles: `limit1` condition engine, auto-activation on every
   `changeData`, `91006` push, 91002 show cells, 91009 manual re-check,
   91004 switching, bind-YB reward, `gonggao` notices.
5. Fight/attributes: xianjie bag and title bags already flow through the
   existing `xianjie_id_for`/`chenhao_ids_for` attribute-bag wiring;
   add the `[11]`/`[12]` 12010 cells and the shared refresh.
6. Tests: thresholds, duplicate protection, failed actions, two distinct
   event sources, persistence/reconnect, command dispatch, notices.

Nothing in the command family is wired yet; the port only computes the
xianjie/chenghao attribute bags for migrated roles.

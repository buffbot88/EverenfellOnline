# Huodong (activities/events) ledger

Port of the `com.xianling.bus.huodong` family. Evidence: `HuodongAction`
javap (reply-ID = inbound-ID mapping), `HuodongModuleInit.getInCmd`
(28 numeric inbound + 2 inner events), `EventHandleCommands`
(role_login -> 70100), the service impls, config exporter hierarchy,
and the shipped `kaifuzaixian.jat` (56 rows, 7 days x 8 gifts).

Status words: complete+tested (wire-exercised through the real
handlers + SQLite store), implemented-untested, push-only (S2C, no
inbound handler), internal (event-driven, no wire command), no-op
(registered, empty body), dead (declared constant, zero references in
the jar: no sender, no handler, not in InCmd).

## Full 38-ID classification

| ID | Java source | status | notes |
| --- | --- | --- | --- |
| 70000 | getRechargeInfo | missing | zonghe FIRSTRECHARGE info; needs remote JSON |
| 70001 | lingquRechargeReward | missing | first-recharge claim; needs remote JSON |
| 70100 | role_login event | internal | HuodongService.online + OnlineGift.online run at login; no wire frame in Java either |
| 71002 | FIRST_RECHARGE push | push-only | send2One [configId, yb, 1] from recharge(); unported |
| 70500 | getHuodongInfo | missing | zonghe panel; needs remote JSON |
| 70501 | getAccumulateRecharge | missing | zonghe; needs remote JSON |
| 70502 | getAccumulateComsume | missing | zonghe; needs remote JSON |
| 70503 | declared only | dead | in RoleHuodongCommands, zero jar references |
| 70504 | declared only | dead | in RoleHuodongCommands, zero jar references |
| 70505 | getForeverRecharge | missing | zonghe FINAL; needs remote JSON |
| 70506 | getLimitedMall | missing | zonghe; needs remote JSON |
| 70507 | getLimitedExchange | missing | zonghe; needs remote JSON |
| 70508 | getZuoqiRank | missing | zonghe zuoqi rank; needs remote JSON |
| 70509 | getkingMine | missing | zonghe; needs remote JSON |
| 70510 | declared only | dead | in RoleHuodongCommands, zero jar references |
| 70511 | declared only | dead | in RoleHuodongCommands, zero jar references |
| 70520 | progress push | push-only | queue [configId, 1] from recharge()/decrYb(); unported |
| 70530 | getRechage | missing | pay-panel info; needs remote JSON |
| 70550 | buyHuodongMallGoods | missing | zonghe mall buy; needs remote JSON |
| 70551 | getHuodongReward | missing | generic zonghe claim; needs remote JSON |
| 70552 | xiaoFeiRank | missing | consumption rank; config via remote zonghe |
| 70553 | xiaoFeiFanliInfo | missing | consumption rebate info; config via remote zonghe |
| 70554 | xiaoFeiFanliRew | missing | consumption rebate claim; config via remote zonghe |
| 70556 | ZUOQI_JINJIE decl. | dead | no sender/handler in the jar |
| 70558 | GET_PROP decl. | dead | no sender/handler in the jar |
| 70559 | RECHARGE_YB decl. | dead | no sender/handler in the jar |
| 70580 | getQibingRank | missing | zonghe qibing rank; needs remote JSON |
| 94000 | getTimeHuodongInfo | complete+tested | online gifts (batch 1) |
| 94001 | getTimeHuodongReward | complete+tested | online gifts (batch 1) |
| 94002 | rank94002 | missing | rank-1 list; needs paihang ranks |
| 94003 | rank94003 | missing | rank-1 single; needs paihang ranks |
| 94004 | rank94004 | missing | rank-1 monster; needs paihang ranks |
| 94005 | rank94005 | missing | rank-1 award; needs paihang ranks |
| 94100 | rank94100 | missing | rank-2 list; RankHuodongConfigExportServiceImpl2 is remote-refreshable |
| 94101 | rank94101 | missing | rank-2 single; remote config |
| 94102 | rank94102 | missing | rank-2 monster; remote config |
| 94103 | rank94103 | missing | rank-2 award; remote config |
| 101000 | cmd_101000 | no-op | registered in InCmd; body is a bare return |
| ROLE_RANK_KILLMONSTER | killBoss | internal | combat-hook input to the rank service |
| ROLE_LEVEL_UPGRADE | roleUpgrade | no-op | registered; body is a bare return |
| ROLE_VIP_LEVEL | vipLevel | internal | feeds the rank service via BusMsgQueue |

Dead IDs (70503/70504/70510/70511/70556/70558/70559) are kept as
`missing` in the mechanical census; there is no behavior to port.

## Batch 1: online gifts (94000/94001)

State: the shared `role_huodong` row (full `RoleHuodong` shape for later
batches), `max_count` JSON key `online_gift` ->
`{day, id, logintime, minute[, end]}`, mirroring the jar's
getValue/setValue helpers. Kaifu day = `twoDaysDiffence(role.createTime)
+ 1` (role creation day, date-based; verified against `getKaifuTime`).

- login (`_huodong_on_enter`, wired into `enter_world` like the
  juqing/task/friend hooks): state absent or stale day -> `initToday`
  (day bucket's startId, `minute = seconds * 1000`); same day ->
  refresh `logintime`.
- logout (`_huodong_on_disconnect`, wired into the `server.py` close
  `finally` alongside the friend/juqing/zuwu hooks): same day ->
  `resetRemainderTime` banks `minute - elapsed`; stale day -> re-init.
- 94000: silent when no live state; else `[1, remainderMs,
  [[goodsId, count]...]]` (`RoleOnlineHuodongOutput`, null-safe).
- 94001: no live state -> `[0, 792010]`; immature -> `[2, remainderMs,
  792011]`; bag-full -> `[0, 430212]` with no state change; mature ->
  job-unfiltered `putInBag` grant, `resetToNext` advance, `[1,
  newRemainder, claimedPairs]`, or `[1, -1, claimedPairs]` on the last
  gift (end marker persisted).
- Shipped 7 x 8 ladder verified: day 1 starts at id `1` (60 s), day 7
  ends at id `56` (3600 s); past day 7 initialises `{day, end}`.

## Java quirks reproduced (pinned by tests)

- `minute` config field holds online *seconds* (x1000 to ms in state).
- Thresholds are per-gift windows that reset on advance (logintime =
  now at each advance), not cumulative session time.
- The disconnect bank / login refresh split: elapsed time only persists
  across sessions because logout banks it; a dropped connection without
  the close hook would lose the session (hence the server.py hook).

## Genuine remaining gaps

- Zonghe families need the remote-refresh JSON snapshot
  (`AbsZongheHuodongRemoteRefreshAbleConfigureParser.configureDataResolve`);
  no shipped snapshot exists in `reference/`, so thresholds/rewards
  cannot be grounded. Recovering a snapshot (or deciding on a seeded
  stand-in) is the blocker for 70000/70001/70500-70502/70505-70509/
  70530/70550/70551/70552-70554/70580/70520/71002.
- Rank-1 (94002-94005) additionally needs the paihang ranking source
  (handleLevelRankData/handleZuoqiRankData/handleZhanliRankData/
  handleKillBossRankData + quartz settlement); paihang itself is unported.
- `changeZuoqiRank`/`addMeiRen`/event-bus fan-outs touched by sibling
  families stay unported.
- The shared `role_huodong` row is ready for later batches (refresh,
  day/max-count JSON maps, pay/mall/kill columns present).

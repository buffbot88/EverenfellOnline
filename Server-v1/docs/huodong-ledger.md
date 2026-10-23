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

Zonghe group (19 inbound: 70000/70001 `complete+tested`, rest
`missing`): 70000/70001 (first recharge, batch 2),
70500/70501/70502/70505/70506/70507/70508/70509/70530/70580
(panel/accumulate/limited-mall/exchange/ranks), 70550/70551 (mall
buy/generic claim), 70552/70553/70554 (consumption rank/rebate).
Every one is driven by `ZongheHuodongCategoryConfig` rows from the
GM-pushed remote JSON (`AbsZongheHuodongRemoteRefreshAble-
ConfigureParser`); the authentic `fu0` snapshot ships in the CLIENT
tree (`MKO_Client/.../gameanalyze/compositiveactivity/fu0`, md5-pinned)
— see `docs/zonghe-finding.md` for the verified schema, routing
tables, and the families still absent from that snapshot. Pushes 70520
(`[configId, 1]`) progress stays `push-only` pending the service port;
71002 (`[activityId, yb, 1]` first-recharge, batch 2) is `push-only`.
The old `[categoryId, ...]` ledger shape was wrong: the jar sends the
activity config id (corrected, with tests pinning it).

Rank-1 group (94002-94005, `missing`): classpath config
(`kaifuhuodong.jat` shape matches `RankHuodongConfig` fields) but the
rank source is the unported paihang system (level/zuoqi/zhanli/killBoss
rank data + quartz settlement).

Rank-2 group (94100-94103, `missing`): `RankHuodongConfigExportService-
Impl2` is remote-refreshable like zonghe; no shipped config.

Online gifts (94000/94001, `complete+tested`): batch 1, below.

Remainder, each with zero jar references outside its declaration
(no sender, no handler, not in `InCmd`); there is no behavior to
port and they stay `missing` in the mechanical census:
dead 70503/70504/70510/70511/70556 (ZUOQI_JINJIE)/70558
(GET_PROP)/70559 (RECHARGE_YB); no-op 101000 and
ROLE_LEVEL_UPGRADE (registered, bare-return bodies); internal
70100 (role_login runs both `online()`s, no wire frame in Java),
ROLE_RANK_KILLMONSTER (killBoss combat-hook input),
ROLE_VIP_LEVEL (vipLevel feeds the rank service).

## Batch 1: online gifts (94000/94001)

State: the `role_huodong` row (just the `max_count` JSON map for now;
sibling columns land here only when a batch needs them). The
`max_count` JSON key `online_gift` ->
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

## Batch 2: zonghe loader + first-recharge core (70000/70001 wired)

`GameConfig.zonghe(server_id, kaifu_ms)` reads the fu0 snapshot in
place (13-byte Java-serialization header check, then JSON): unknown
clienttypes dropped with a log (ct 36, proven: convert() has no 36
arm), categories without `activitys` skipped, explicit
starttime/endtime windows pass through, the rest resolve
kaifu-relative `[kaifu + startday, + kaifudays]` days, `con1` stays a
string, and failed reloads keep the previous table (first load with
no snapshot is `{}`). Category `title` mirrors HuodongInit (first
activity's `datatitle`); activities keep the first-recharge display
fields (`name/mm/mmeffect/anniu/jiemian/chufa`), award currencies,
and the full award rows parsed per convertAwardsGoodsesStr
(lasttime hours, `strengthenlv` A|B, rare, fjid). `zonghe_live` is
the `timeIsExpiry` read API. `Session.zonghe_recharge` latches
`charged` and pushes 71002 `[activityId, yb, 1]` when a ct-21
category is live; the 70001 claim grants the job-filtered
(GoodsJobFilter) snapshot items, raises the mount to rank 3 with its
33004 push when below it, persists the activity id under
`zonghe_first.claimed`, and answers [0, code] when uncharged,
claimed, out-of-window, or bag-full (no state change then). Every fu0
first-recharge award carries zero currencies and an empty mm, so the
items-only grant is complete for fu0.

Bytecode-grounded routing (dntg_start.jar javap): 70000
`HuodongAction.getRechargeInfo -> IHuodongService.getFirstRechargeInfo
-> send2One("70000", result)` where result is null (no live
category), `[0, 792005]` (role below need_level or below need_pay_yb),
or `RoleHuodongOutputWrapper.firstrecharge(state, category, config,
claimedCount, job)` — a 13-array `[configId, title, state, [mmId,
mmEffect], startMs, endMs, needPayYb, claimedCount, [jb, lijin,
zhenqi, shengwang, exp, items], jiemian, anniu, chufa, categoryTitle]`
with 7-slot items `[goodsId, count, bind, hours, [qinghua,
qianghua], rare, fjid]`; state is 2 claimed, 1 charged, 0 otherwise
(the trailing job argument is never read). 70001
`HuodongAction.lingquRechargeReward ->
lingquFirstRechargeReward` answers `[1, configId]` or `[0, code]`
(792005 no row, 792002 already claimed, 792001 never recharged,
430212 bag full; the 70001 frame is only sent when non-null) with
`changeZuoqiRank(roleId, 3)` + currency/meiren/item side effects.
71002 is `recharge()`'s FIRST_RECHARGE branch sending
`[activityConfigId, rechargeYb, 1]` via send2One (the constant lives
under `h70002`); no fu0 activity can take that branch (it needs a
non-first-recharge category row with functiontype 94, and the fu0
census has none), so the push is proven-absent for fu0 and the port
sends it from the recharge latch instead. Census: 70000/70001
implemented, 71002 push-only.

Verified-against-bytecode deltas the port keeps (documented, not
fixed): the kaifu window is `TimeConfigVo.calTime` (start =
midnight(serverStart + (startday+1) days) when startday > 0, end =
23:59:59(serverStart + kaifudays days) when kaifudays > 0, then
`real = max(hefu, kaifu, explicit)` on both ends with a
forward-minute shift) while the port uses explicit-wins else
`[kaifu + startday, + kaifudays]`; the claim gates on the `charged`
latch instead of lifetime `getChargeTotal`/`getShouchongInTime`
windows (exact for fu0: need_pay_yb is 0 everywhere); currency
(`incrExp/incr(BIND_YB/YXB)/incrZhenqi`) and `addMeiRen` grants only
run for non-zero/non-empty configs (none in fu0); the 33004 mount
frame reuses the port's 33004 shape.

## Genuine remaining gaps

- Zonghe service port for 70500-70502/70505-70509/
  70530/70550/70551/70552-70554/70580/70520 (wire shapes unrecovered)
  and the families absent from `fu0` (ct 3/4/6/7/8/11-17/19/20/23/35).
  Loader + first-recharge core + 70000/70001 are in (batch 2, above).
  No seeded stand-in.
- Rank-1 (94002-94005) additionally needs the paihang ranking source
  (handleLevelRankData/handleZuoqiRankData/handleZhanliRankData/
  handleKillBossRankData + quartz settlement); paihang itself is unported.
- `addMeiRen`/event-bus fan-outs touched by sibling families stay
  unported (`changeZuoqiRank(roleId, 3)` is ported as the
  first-recharge claim side effect with its 33004 push).

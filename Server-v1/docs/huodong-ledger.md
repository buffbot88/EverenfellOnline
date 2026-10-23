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

Zonghe group (19 inbound, all `missing`): 70000/70001 (first recharge),
70500/70501/70502/70505/70506/70507/70508/70509/70530/70580
(panel/accumulate/limited-mall/exchange/ranks), 70550/70551 (mall
buy/generic claim), 70552/70553/70554 (consumption rank/rebate).
Every one is driven by `ZongheHuodongCategoryConfig` rows from the
GM-pushed remote JSON (`AbsZongheHuodongRemoteRefreshAble-
ConfigureParser`); the authentic `fu0` snapshot ships in the CLIENT
tree (`MKO_Client/.../gameanalyze/compositiveactivity/fu0`, md5-pinned)
— see `docs/zonghe-finding.md` for the verified schema, routing
tables, and the families still absent from that snapshot. Pushes 70520
(`[configId, 1]`) progress and 71002 (`[configId, yb, 1]`
first-recharge) are `push-only` pending the service port.

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

## Batch 2: zonghe loader + first-recharge core (no inbound wire yet)

`GameConfig.zonghe(server_id, kaifu_ms)` reads the fu0 snapshot in
place (13-byte Java-serialization header check, then JSON): unknown
clienttypes dropped with a log (ct 36), categories without `activitys`
skipped, explicit starttime/endtime windows pass through, the rest
resolve kaifu-relative `[kaifu + startday, + kaifudays]` days, `con1`
stays a string, and failed reloads keep the previous table (first load
with no snapshot is `{}`). `zonghe_live` is the `timeIsExpiry` read
API. `Session.zonghe_recharge` latches `charged` and pushes 71002
`[categoryId, yb, 1]` when a ct-21 category is live;
`zonghe_first_claim` grants the snapshot items, persists the activity
id under `zonghe_first.claimed`, and answers None when uncharged,
claimed, out-of-window, or bag-full (no state change then). Every fu0
first-recharge award carries zero currencies, so the items-only grant
is complete. 70000/70001 stay `missing`: their reply shapes are still
unrecovered and are not guessed at.

## Genuine remaining gaps

- Zonghe service port for 70000/70001/70500-70502/70505-70509/
  70530/70550/70551/70552-70554/70580/70520 (wire shapes unrecovered)
  and the families absent from `fu0` (ct 3/4/6/7/8/11-17/19/20/23/35).
  Loader + first-recharge core are in (batch 2, above). No seeded
  stand-in.
- Rank-1 (94002-94005) additionally needs the paihang ranking source
  (handleLevelRankData/handleZuoqiRankData/handleZhanliRankData/
  handleKillBossRankData + quartz settlement); paihang itself is unported.
- `changeZuoqiRank`/`addMeiRen`/event-bus fan-outs touched by sibling
  families stay unported.

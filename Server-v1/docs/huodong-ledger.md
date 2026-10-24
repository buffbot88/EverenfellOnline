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

Zonghe group (19 inbound: 70000/70001/70500/70501/70506/70507/
70550/70551 `complete+tested`, rest `missing`): 70000/70001
(first recharge, batch 2), 70500 (panel, batch 3), 70501
(accumulate-recharge, batch 4), 70506 (discount-mall, batch 5),
70507 (exchange, batch 6), 70550/70551 (durable buy/claim,
batch 7), 70502/70505/70508/70509/70530/70580
(accumulate/limited-mall/exchange/ranks),
70552/70553/70554 (consumption rank/rebate).
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

## Batch 7: 70550/70551 purchase + exchange lifecycle (durable)

`Session.huodong_mall_buy` / `huodong_exchange_claim` port
buyHuodongMallGoods/getHuodongReward's ct-5 ct-9 branches with
their check*/grant/counter helpers, end to end and durable: the
gate answers the jar's `[0, code]` (expired 792003, hidden 792001,
day/max 792008/792009 buy or 792006/792007 claim, full bag
430212); short costs answer `[0, 792001]`, an emptied shelf
`[0, 792004]`. Success debits (YB lingshi, YXB tongqian,
bind-exact bag slots), grants (award parcels plus jb/lijin/zhenqi
credits and exp with its pure level-up fields), bumps day/max by
one (and the per-good buy count plus the global sell count for
70550), and replies the jar's post-claim arrays (`[1, actId,
goodsId|null, state, maxVal, maxLimit, dayVal, dayLimit]`, the buy
with a queued 70506 refresh behind it). Missing
category/activity stays silent like the jar's null; sibling
clienttypes ride their own branches. Persistence: role_huodong
gains day_count + mall_buy_count columns (migrated), huodong_info
holds the global sell JSON, and every write applies in one
Store-held atomic commit — counters increment inside the commit
from in-tx reads (setValue parity, no lost update under
concurrency), debits re-verify inside the commit, and any abort
rolls everything back. The 70506 panel now reads the persisted
buy/sell remains. Tests (23, all fu0 except one labeled
synthetic row for the zero-currency awards): debits, grants,
limits, duplicate/repeat rejection, forced-apply rollback,
restart/reconnect persistence, concurrency consistency, expiry,
the [2]->[0, 792005] regression, and encrypted-wire dispatch.
Census: 70550/70551 implemented (huodong 10/0/0/1/27).

Documented gaps (no invention): no shipped row exercises the
exp level-up fan-out beyond the covered path (fu0 awards carry
zero exp; the synthetic row pins one level-up); the exp absolute
fields compute from a pre-commit read, so two racing exp-granting
claims serialize on value while counters/debits/bag stay exact
(Java's remote calls race worse); zubao rolls stay [] (no
nonzero zubaoid in ct-9/5/1); count < 1 on 70550 answers
[0, 792001] rather than replicating a negative-debit quirk.

## Java quirks reproduced (pinned by tests)

- `minute` config field holds online *seconds* (x1000 to ms in state).
- Missing clienttype category reads `[0, 792005]`, never the bare
  `[2]` (verified against all three display services' null-category
  arms; the port's live-cat helper now matches).
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

## Batch 3: 70500 activity panel (getHuodongInfo)

`Session.huodong_panel_info` ports `IHuodongService.getHuodongInfo`
verbatim: live categories in table order, skipping FIRSTRECHARGE
(ct 21); rows are `[clientType, pattern, button, tag, teamId,
zuoqitu]`, with the `[name, icon, title]` header once ahead of the
first icon-bearing row (HuodongInit reads them from the first
activity's data map). Liveness is the raw service check
(`start <= now < end`, end-exclusive, unlike the claim paths'
`timeIsExpiry`). Tests pin a 5-row fu0 golden, the ct-21 skip,
the exclusive end edge, and the wire dispatch.

Next in family, in dependency order: 70551 generic claim + 70550
mall buy (null-guarded/writes), 70580/70508 rank rows, 70530
pay/band info. 70502 (YB_CONSUME ct 3) and 70505 (FINAL ct 7)
have no fu0 rows and stay blocked on config.

## Batch 5: 70506 discount-mall display (getLimitedMall)

`Session.huodong_limited_mall` ports
`IHuodongService.getLimitedMall` verbatim: the first time-live ct-5
category (inclusive; none reads `[2]`, a missing/empty activity
map reads `[0, 792005]`), else `[1, 5, startMs, endMs, pic, rows]`
with one 14-array per level- and charge-gated activity good:
`[activityId, item, tags, opayYb, npayYb, freeItems, buyRemain,
sellRemain, dayVal, dayLimit, state, order, desc, itemName]`. The
good's item is the 10-slot projection of `(itemId, 1, buyBind,
lastTime)` with no addMesage/lostTime, so the ctor bypasses the
clamp and fu0's `-1` reads `-1.0` (jar-exact); freeItems projects
the gift rows. State is 1 when stock and the per-role limit allow
it and the lingshi purse covers npayYb, 2 when maxBuy or the day
limit is hit. Loader parses the `config[]` lists into
`mall_goods`. Tests pin a 12-row fu0 golden (rich role all state
1; broke role all state 0), the full first row, the level gate,
the `[2]`/`[0, 792005]` edges, and the wire dispatch. Gaps: sell
counts read `maxSell - 0` and buy counts `maxBuy - 0` until the
70550 buy batch persists them.

## Batch 6: 70507 limited-exchange display (getLimitedExchange)

`Session.huodong_limited_exchange` ports
`IHuodongService.getLimitedExchange` verbatim: the first time-live
ct-9 category (inclusive; none reads `[2]`, a missing/empty
activity map reads `[0, 792005]`), else `[1, 9, startMs, endMs,
pic, rows]` with one 10-array per level- and charge-gated
activity: `[activityId, costs, awards, maxVal, maxLimit, dayVal,
dayLimit, state, null, order]`. Costs are the `[goodsId, count,
bind]` triples split from con on `,` then a literal `|` (bind
defaults to 0 for two-part costs like `duihuan1|1`); awards is
the shared 10-slot view. State starts 1, drops to 0 when the role
fails a `yuanbao` (lingshi) or `money` (tongqian) dry-run or the
bag-slot check (id plus exact bind), and reads 2 once the day/max
floor is hit. No new loader work: costs parse from `con1`, awards
reuse `item_views`. Tests pin a 12-row fu0 golden (stocked rich
role all state 1, broke role all state 0), the full first row,
the level gate, the `[2]`/`[0, 792005]` edges, and the wire
dispatch. Gaps: no yuanbao/money cost row is live in fu0, so
those branches are unpinned; the bag check covers slots only;
claim-time persistence belongs to the 70551 batch.

## Batch 4: 70501 accumulate-recharge display (getAccumulateRecharge)

`Session.huodong_accumulate_recharge` ports
`IHuodongService.getAccumulateRecharge` verbatim: the first
time-live ct-1 RECHARGE category (inclusive), else `[1, 1,
startMs, endMs, chargeTotal, pic, rows]` with one 11-array per
level- and charge-gated row: `[id, isAccumulate, con, [awards],
maxVal, maxLimit, dayVal, dayLimit, state, order, choujiang]`. The
awards block is the single 5-array `[null, name, items, null,
desc]` (no chooseAwards or zubao rows in fu0); each item is the
10-slot projection. State follows the jar formula (PER_RECHARGE
gates state 1 on the total covering `con * (claimed + 1)`;
ACCUMULATE_RECHARGE reads 1 with the check deferred to 70551;
the day/max floors force 2). Loader gains `award_name`/
`award_desc` plus parsed `item_views`. Tests pin a 6-row fu0
golden, the level gate, the `[2]`/`[0, 792005]` edges, and the
wire dispatch. Gaps: charge totals read 0 (no recharge-record
service; batch 2 latches `charged` instead); `getChoujiang` reads
[] (no table ships); the 70000 fjid-'' asymmetry stays as-is.

## Genuine remaining gaps

- Zonghe service port for 70502/70505/70508/70509/
  70530/70552-70554/70580/70520 (wire shapes unrecovered
  except routing: all verbatim `send2One` except null-guarded 70530)
  and the families absent from `fu0`
  (ct 3/4/6/7/8/11-17/19/20/23/35). Loader + first-recharge core +
  70000/70001 (batch 2) + 70500 panel (batch 3) + 70501 display
  (batch 4) + 70506 display (batch 5) + 70507 display (batch 6) +
  70550/70551 durable buy/claim lifecycle (batch 7) are in.
  No seeded stand-in.
- Rank-1 (94002-94005) additionally needs the paihang ranking source
  (handleLevelRankData/handleZuoqiRankData/handleZhanliRankData/
  handleKillBossRankData + quartz settlement); paihang itself is unported.
- `addMeiRen`/event-bus fan-outs touched by sibling families stay
  unported (`changeZuoqiRank(roleId, 3)` is ported as the
  first-recharge claim side effect with its 33004 push).

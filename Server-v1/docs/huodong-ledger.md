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

Follow-up fix (in-tx EXP computation): the gain computes inside
the atomic commit from the fresh in-tx row (pure applier closure),
currency credits apply as in-tx increments (the jar's incr
semantics), the tx returns the exact post-commit (old_level,
level, exp, gained) for the 12001/extended frames, and the
extended fan-out reads a freshly re-fetched role. Five racing
exp claims land on five distinct chain states with summed
credits; a forced mid-apply abort rolls level/exp/credits/
counters/stock back together.
Documented gaps (no invention): no shipped row exercises the
exp level-up fan-out beyond the covered path (fu0 awards carry
zero exp; synthetic rows pin it); zubao rolls stay [] (no
nonzero zubaoid in ct-9/5/1); count < 1 on 70550 answers
[0, 792001] rather than replicating a negative-debit quirk.

## Batch 8: 70551 ct-1/ct-10 generic claims (durable)

`huodong_exchange_claim` now also serves getHuodongReward's
RECHARGE (ct-1) and ZUOQI (ct-10) branches: the shared gate
answers the jar's `[0, code]` (expired 792003, hidden 792001,
day 792006, max 792007, full bag 430212, bag checked before the
threshold like checkGetHuodongReward). ct-1 routes PER_RECHARGE
(10; YB_CONSUME/92 shares the arm, no fu0 row uses it) and
ACCUMULATE_RECHARGE (11) through the one threshold formula
`con * (claimed + 1) > windowed total` answering `[0, 792001]`;
other functiontypes stay silent like the jar's null. The windowed
total is an injected `charge_total_in_time` callable (default 0,
exact for fresh roles; no recharge-record service exists) and the
claim echoes the raw chooseId: empty rides the flat award, a
known id rides its choose_awards entry, an unknown id answers
`[0, 792005]` (fu0 rows carry no choose entries, so the loader
parses them but finds none). ct-10 checks the mount rank
(get_role_zuoqi) against con, `[0, 792001]` when short. Both
grant through the batch-7 atomic commit (counters bump in-tx,
abort maps to `[0, 792001]`) and reply the jar's arrays: the
9-array `[1, actId, chooseId, state, maxVal, maxLimit, dayVal,
dayLimit, choujiang]` for ct-1 with the post-claim next-threshold
state (`total >= con * (claimed_post + 1)`), the 8-array without
choujiang for ct-10 with the limits-only state. The choujiang
cell reads None (empty table, the jar's null arm); ct-34 XIAOFEI
and every other clienttype stay silent like the jar's
fall-through null. Tests (11 new, all on real fu0 rows except
one labeled synthetic choose row): PER/ACC short totals, a
covering-total success with persistence and repeat rejection,
the unknown-choose 792005 edge with no side effects, a choose
grant pinning state 1 plus the exp level-up frames, rank short
and success persistence plus the bag-full gate, the ct-34 /
unknown-ctype / unknown-activity silent arms, and encrypted-wire
gate dispatch for both branches. Census unchanged (same 70551
handler: huodong 10/0/0/1/27).

## Batch 9: 70551 ct-3/ct-7/ct-22/ct-30/ct-31/ct-32 claims

`huodong_exchange_claim` serves six more getHuodongReward branches.
ct-22/30/31/32 share one threshold arm with ct-10 (metric < con
answers `[0, 792001]`, then the 8-array `[1, actId, null, state,
maxVal, maxLimit, dayVal, dayLimit]` with the limits-only state):
baoshi gem-level sum (real `role_baoshi` rows), qibing level
(service unported: injected callable reading 0), wing level
(real `role_guangyi.level`), vip level (real `role_vip`).
ct-3 checks `con * (claimed + 1)` against the per-activity payYb
map (new `role_huodong.pay_yb` JSON column, migrated like
`mall_buy_count`; the consume-tracking producer is unported, so
it reads empty until seeded) and replies the 9-array with
chooseId and choujiang like ct-1. ct-7 checks con against the
lifetime charge total (injected, default 0) and replies the
8-array `[1, actId, state, maxVal, maxLimit, dayVal, dayLimit,
choujiang]` with state 1 only while the limits stay open and
the total still covers con. All six reuse the batch-7/8 atomic
commit (counters bump in-tx, abort maps to the jar code) and
the in-tx EXP/credit grant. Tests (15 new): genuine-row short
and success for ct-22 (sum 30), ct-30 (injected 3, plus
restart/reconnect persistence), ct-31 (wing 3), ct-32 (vip 4 in
a kaifu-relative window), bag-full, day-limit repeat,
encrypted-wire expiry gates for all four rank families, and
labeled synthetic fixtures for ct-3 (seeded payYb success,
short, unknown-choose 792005) and ct-7 (short, lifetime
success with state 1) — fu0 holds zero rows for both.
Census unchanged (same 70551 handler: huodong 10/0/0/1/27).

Known limits carried over: zubao rolls stay unrun (no nonzero
zubaoid in fu0).
The real next dependency is a charge/consume-total pipeline
(recharge-record service + consume event hookup) so ct-1 claims
can succeed on live data instead of the 0-total gate shape.

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
[] (no table ships); the 70000 fjid-'' asymmetry stays as-is.## Genuine remaining gaps

Packet handlers vs durable lifecycles: 70000/70001/70500/70501/
70506/70507 are display-only packet handlers (wired shapes,
no persistence); 70550 (mall buy) and 70551 (claims for ct
1/3/7/9/10/22/30/31/32) are durable lifecycles with atomic
`role_huodong` persistence (day/max/mall-buy/pay-yb counters,
global sell counts) and the in-tx EXP/credit grant.

## Batch 10: recharge_record persistence (RechargeRecordService/Dao)

`Store` grows the jar-exact `recharge_record` table (id,
user_role_id, rmb, money_type 2 = YB, money_num, is_calc,
recharge_type, platform_type, recharge_state, order_id,
create_time ms epoch, server_id, user_guid; no UNIQUE on
order_id, like the jar — revoked orders may be re-paid) plus
the service/DAO read half: `save_recharge_yb` (record insert;
the currency grant + `RechargeYBEvent` fan-out stay unported),
`recharge_check_order_repeat` (`order_id=? AND recharge_state
<= '1'`, so live/pending rows block while '9' and 100x rows
do not), `recharge_charge_total` (lifetime Σ over the
account's server-scoped success rows, type 3/4 excluded,
state '0' only — the ct-7/vip source), and
`recharge_charge_total_in_time` (same shape with state <=
'1' so pending offline orders count, inclusive create_time
bounds, None bound unbounded — the ct-1 source). Text state
comparison reproduces the jar's varchar `<=`: '0'/'1'
match while '9' and '1001'-'1005' do not. `recharge_pending`
returns the exact-state-'1' login list oldest-first
(`finishRecharge`'s list; the exact `=` match is why a second
login cannot re-grant) and `recharge_mark_state` flips rows
to '0'/'9'. Tests (14, all on real rows): repeat gating per
state, lifetime/window sums with edge inclusivity and type
and account/server scoping, pending ordering and the
grant-mark-total cycle, unknown-role zeros, and reopen
persistence. Census unchanged (no wire IDs).

## Batch 11: recharge producer + login finish + consume ledger

Grounded in rchg_dao/rchg_svc/rchg_exp/rchg_ep/money dumps (not
inferred): `saveRechargetYb2` gates on checkAccountExist (no
role → 1005), non-positive amount (→ 1001) and order repeat
(→ 1004), persists the row under the outcome state (exception
→ 1003), grants only when online, and pushes 12301 [incr]
plus a `RechargeYBEvent(roleId, incr, !type.equals("1"))`
for YB rows of type 1/2; `finishRecharge` re-grants every
exact-state-'1' row by money type (YB 2 → `recharge`, YXB 1
and BIND_YB 3 → `incr`), re-fetches each row by
order/guid/server, deletes surviving duplicates, flips the
winner to '0', then sends 12301 and the event per YB row;
`getTotalByDayAndAll` returns [all, today] (today = local-day
window); `decrYb` bumps every live YB_CONSUME activity's
payYb by the debited amount (queues 70520 at newly
completed thresholds) plus the category-level accumlatePayYb.
MoneyType intTypes: YXB 1, YB 2, BIND_YB 3.

Ported: `Store.recharge_grant_save_tx` (dup-guarded insert +
lingshi credit, one commit), `Store.recharge_finish_tx`
(pending oldest-first with the getEnableRecharge dedup-delete,
per-type credit, flip to '0'; unknown money types stay
pending), `Store.recharge_charge_today`, `Store.yb_consume_tx`
(debit + payYb bumps, one commit, False with no writes when
short), `Session.recharge_commit` (the 1005/1001/1004/1/1003
entry with the 12301 + zonghe_recharge/vip_upgrade_level
fan-out and a 32010 refresh), `Session.recharge_finish_login`
wired into `enter_world` ahead of the 10003 pair (so
[day, all] includes fresh grants), the `charge_total*`/`charge_today`
callables wired in server.py, and the `_bag_money_decr` YB hook
(old blind debit otherwise, so existing behavior is unchanged
without live ct-3 rows). Tests: 11 new Store tx tests plus
`test_recharge_wire.py` (14) proving ct-1/ct-7/ct-3 claims off
real rows, dup/repeat protection, the 12301 gate (type 3
finishes credit-only), and debit/accounting atomicity.
Census unchanged (12301 is a push, not a dispatch).

Still unported: the 70520 threshold push on consume completion
(no 70520 consumer exists in the port), the category-level
accumlatePayYb column (no reader ported), and
`revocationOrder`. The mall/exchange in-tx YB debits feed
consume via an optional trailing `consume_acts` on both txs
(Session passes the live YB_CONSUME ids; zero-cost grants,
yxb-only debits and empty live sets bump nothing, same-commit
so aborts revert debit and totals together — pinned by
mall/exchange abort tests, the exact-purse boundary and the
yxb exclusion). `calYb` (rmb → YB)
is inferred as ceil(rmb * 10) — the gamerule util bytecode was
not recovered — isolated in one helper per side to fix once.

## Batch 12: 70580/70508 rank-display map (no code)

Traced end to end from HuodongAction + HuodongServiceImpl
bytecode (`hd705_action.txt`, `hd705_svc.txt`), the
CompositiveActivityClientType clinit (`hd705_ct.txt`: ZUOQI 10,
BAOSHI_LEVEL 22, QIBING_RANK 30, CHIBANG_RANK 31, VIP_LEVEL 32;
rank range 11-17 is RANK1-7, a different paihang-backed family)
and HuodongModuleInit (`hd_mod.txt`). No rank feed is a
paihang read — both commands render per-activity threshold rows
against a progression metric, refreshed client-side by 70520
pushes, none of which the port emits yet.

| cmd | action entry | service read | metric source |
| --- | ------------ | ------------ | ------------- |
| 70580 | `getQibingRank(Message)`: roleId + Integer typeId → `getQibingRank(roleId, type)` | Zonghe category `convert(typeId)`; null → `[0, 792005]`; not live → `[2]`; empty map → `[0, 792005]`; per shown activity the 12-array below | `getSingleHuodongConditionVal(roleId, type)`: 30 → `IQiZhanBinQiExportService.getQizhanBinLevel` (unported — the port injects `qibing_level`, default 0); 22 → baoshi `getRoleBaosShilevelSum` (ported); 32 → vip `getRoleVipLevel` (ported); 31 → guangyi `getGuangYiLevel` (ported); else 0 |
| 70508 | `getZuoqiRank(Message)`: roleId only → `getZuoqiRank(roleId)` | ZUOQI (10) category; same three edges as 70580 | `IRoleZuoQiExportService.getZuoQiRank(roleId)` (ported as `_zonghe_zuoqi_rank` off `role_zuoqi`) |

Row shape (identical both commands, built inline — no separate
wrapper class; items via `RoleHuodongOutputWrapper.itemParamVo2Client`):
`[actId, con, items, maxVal, maxLimit, dayVal, dayLimit, state,
order, desc, name, huodongicon]` with state 1 when metric ≥ con
(2 when `isCompletedHuodong`), forced 2 on day/max floors, else 0;
rows gated by `huodongIsShow`. Outer 70508:
`[1, 10, startMs, endMs, pic, rows]`; outer 70580:
`[1, typeId, startMs, endMs, pic, rows]`.

Reset semantics: none — no wipe/reset method exists in the 29
recovered service publics; both displays are pure per-call
recomputes over the shared day/max counters (claims only bump),
and category turnover is by window expiry (`timeIsExpiry`), not
by clearing rows. The only timing hooks are the module-wired
`RankHuodongQuartz/2.execute()` (impl bytecode not recovered)
and qibing `schedule(roleId)` (no reply), which is the
progression timer, not a display reset.

Fan-in that moves these displays: `decrYb`, `zuoqiJinjie`,
`qibingJinjie`, `baoshiLevelUp`, `getProp` and `vipLevel` each
queue `70520 [actId, 1]` when its metric crosses
`con*(max+1)`; the port has the metric readers but emits no
70520. Qibing progression surface (still unported source for
ct-30): `87000 getData` / `87001 upgrade(Boolean)` /
`87002 getbinqi` / `schedule`; service impl and storage were
not recovered, so `getQizhanBinLevel` stays injected.

- Zonghe service port for 70502/70505/70508/70509/
  70530/70552-70554/70580/70520 (70580/70508 shapes recovered
  in batch 12; the rest routing-only: all verbatim `send2One`
  except null-guarded 70530)
  and the families absent from `fu0`
  (ct 4/6/8/11-17/19/20/23/35; ct-3/ct-7 claims are in but
  their 70502/70505 displays stay blocked on config). Loader +
  first-recharge core + 70000/70001 (batch 2) + 70500 panel
  (batch 3) + 70501 display (batch 4) + 70506 display (batch 5)
  + 70507 display (batch 6) + 70550/70551 durable buy/claim
  lifecycle (batch 7) + 70551 ct-1/ct-10 claims (batch 8) +
  70551 ct-3/ct-7/ct-22/ct-30/ct-31/ct-32 claims (batch 9) are
  in. No seeded stand-in.
- Rank-1 (94002-94005) additionally needs the paihang ranking source
  (handleLevelRankData/handleZuoqiRankData/handleZhanliRankData/
  handleKillBossRankData + quartz settlement); paihang itself is unported.
- `addMeiRen`/event-bus fan-outs touched by sibling families stay
  unported (`changeZuoqiRank(roleId, 3)` is ported as the
  first-recharge claim side effect with its 33004 push).

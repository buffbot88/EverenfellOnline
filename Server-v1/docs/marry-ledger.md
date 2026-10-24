# Marriage porting ledger

Authoritative per-entry status for the Java `MarryAction` surface.
Evidence: `dntg_start.jar` javap of `MarryAction`,
`MarryServiceImpl` (gate order, error codes, push shapes),
`MarryOnlineHandler`/`MarryLoginOutHandler` (login/logout),
`HunjieConfig`/`HunjieqianghuaConfig` (`hunjiebiao`/`hunjieqianghua`
fixtures are legacy-absent so the suite writes small tables exercising
the genuine loader contract), `MarryErrorCode`, `MarryQuartz`
(schedule shape), `MarryMoveEvent`/`MarryFlyEvent` (published, no
ported subscribers), `RoleMarry`, `StoreGoodsOutput.formart`.

Status words: complete+tested (wire-exercised), push-only (Java S2C
with no inbound handler, asserted in peer outboxes), genuine-Java-no-op.

## Bus action (client -> server)

| ID | Java method | Status | Notes |
| -- | ----------- | ------ | ----- |
| 135000 | getInfo | complete+tested | 9-slot panel `[flyMs,createMs,spouseId,spouseName,spouseRing,count,myRing,divorced,stamp]`; ring cells are the 18-slot formart map; silent (no frame) when never married |
| 135001 | qiuhun | complete+tested | gates: level 1000 -> proposer married 135001 -> unknown target 135003 -> ring missing 135002 -> target offline 135003 -> target married 135001; YB broadcast cost first (1002 when short), 11101 `[text]` notice, 135002 7-slot card to the target, `[1]` to the proposer; pending recorded on the target side |
| 135002 | acceptQiuhun | complete+tested | accepts only the proposal card inbound; answers ride 135003 (see below) |
| 135004 | lihun | complete+tested | free when the spouse is offline, else `yuanbao_divorce` YB first (1002 when short); both rows flagged, intimacy zeroed; `[1]` to the caller + spouse |
| 135005 | chuansong | complete+tested | unmarried 135004 / spouse offline 135003; teleports to the spouse's tile via `change_map`; ring `skillcd` cooldown 135011 |
| 135006 | qianghua | complete+tested | no row 135004; max tier 135009; stones short 1005; intimacy short 135010; consumes the current tier cost, adopts the next tier goods/tier; replies `[1]` |
| MARRY:LOGIN | online | complete+tested | registers the pair while the spouse is online; resets stale `day_qingmidu` on a new day; auto-divorces when the spouse has been offline `missing_linit` days |
| MARRY:LOGOUT | loginout | complete+tested | drops both pair entries and the leaver's pending proposals |
| MARRY:TICK | scheduleQingmidu | complete+tested | each registered pair gains `qinmi` on both sides while the key side's day counter stays under `maqinmi`; re-arms on the config `time` delay |

There are no other inbound IDs: 135003/11131 are server pushes (see
below); `SCHEDULE_QINGMIDU` is a quartz key, not a wire command.

## Server pushes (server -> client, no client command)

| ID | Producer | Status | Notes |
| -- | -------- | ------ | ----- |
| 135002 | qiuhun | push-only | 7-slot proposal card `[proposerId,name,guildOrNull,level,ringGoodsId,text,ringGuid]` to the target only |
| 135003 | acceptQiuhun / rejectOthers | push-only | `[1,proposerId,1|0]` to both sides on answer; `[1,accepterId,0]` to the remaining proposers |
| 135000 | acceptQiuhun | push-only | the 9-slot panel to both newlyweds alongside the 135003 answer |
| 11131 | acceptQiuhun | push-only | `[accepterName,proposerName]` wedding notice (Java world broadcast; the port pushes it to the couple's outboxes) |
| 11101 | qiuhun | push-only | `[text]` proposal broadcast when the proposer pays `yuanbao_broadcast` |

## Wedding lifecycle (the acceptQiuhun path)

Decline (`accept=0`): 135003 `[1,proposer,0]` to both, no state change.
Accept: accepter-married 135001; proposer-married 135001; ring gone is a
silent return (Java consumes by guid, online `decr` else offline
`houTaiupdate`); both `MarryMoveEvent`s publish; the marriage counter
increments; `addRoleMarray` writes both rows (fresh: intimacy/day 0,
ring tier 1, bind 1, timestamps now); 135000 to both, 135003
`[1,proposer,1]` to both, 11131 wedding, remaining proposers rejected.
Both writes ride one `marry_tx` transaction; the ring debit and the YB
debits are atomic check-and-debits, so two concurrent accepts/spends
cannot double-wed or double-spend.

## Entity (`RoleMarry` -> `role_marry`)

`user_role_id, marry_user_role_id, qingmidu, chuansong_time,
create_time, goods_id, bind, expire_time, rare_level, item_level,
attributes, lihun, day_qingmidu, log_update_time`. `lihun` divorces in
place (row kept, intimacy zeroed), so remarriage reuses the row and the
panel count is rows ever written.

## Config (genuine loader contract, fixture values are test-only)

`hunjiebiao`: needlevel/time/missing_linit/maqinmi/qinmi/
yuanbao_divorce/yuanbao_broadcast. `hunjieqianghua`: per-hunjieid tiers
keyed by rideweapon with needthingsid/needthingsvalue, cohesion,
skillcd, attribute map; the next tier carries the new hunjieid/tier.

## Python deliberate deviations (documented, not parity-verified)

- The pair/pending maps live on the session (`_marry_pairs`,
  `_marry_pending`) instead of the server `DataContainer`; cross-session
  divorce/teleport resolve the peer through the `StageRegistry`.
- `chuansong` enforces the `isCanChuansong` gates (offline 135003,
  manor 135006, dead 135007, copy 135008, cooldown 135011); the Java
  body falls through and teleports regardless. Success teleports via
  `change_map` (20000 shape) instead of the `MarryFlyEvent` stage
  system, whose subscribers are unported.
- `11131`/`11101` ride the couple's/actor's outboxes instead of the
  world broadcast bus; the payloads match.
- `getInfo` count is `COUNT(*)` over `role_marry` (divorced rows stay)
  where Java uses the `ALL_COUNT_KEY` atomic; remarriage of the same
  role undercounts by one against Java. No recharge or premium-event
  paths exist in the Java marriage surface; every cost is ordinary YB.

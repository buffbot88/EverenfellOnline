# Booth / consignment porting ledger

Authoritative per-command status for the Java stall surface.
Evidence: `BoothAction` + `BoothServiceImpl` javap (`boothaction.txt`,
`boothservice.txt`, `boothout1.txt`, `boothout2.txt` at the workspace
root), `BoothErrorCodeOutput` / `GeneralErrorCode` ints, and the legacy
`ZhuJueShuXingBiao` (`dealaddexp`) table. Every trade path settles
inside one SQLite `BEGIN IMMEDIATE` transaction (`Store.booth_tx`);
only `ok` mutates anything, so a competing buyer sees `gone` /
`changed`, a failed write rolls everything back, and money and goods
move together or not at all.

Status words: complete+tested (wire-exercised through the real
handlers + SQLite store), push-only (S2C, no inbound handler needed).

## Inbound commands (BoothAction)

| ID | Java method | Status | Notes |
| -- | ----------- | ------ | ----- |
| 35100 | getOnlineBooths | complete+tested | `[ownRoleId, fomart list or null]` of stalls with listings whose seller session is live |
| 35101 | putInBooth | complete+tested | `[cellGuid, sellYb, sellJb, count]`; cap 8, YB floor 2, no bound goods, no over-count, no expired; shrink-or-clear bag row + insert listing atomically |
| 35102 | outBooth | complete+tested | delist restores goods to the bag; `gone` 424049, full bag 1006, nothing mutated on failure |
| 35103 | changePrice | complete+tested | reprice `[sellId, sellYb, sellJb]`; both-zero 424048 |
| 35104 | changeIndex | complete+tested | move `[sellId, slot]` 0..10, swap on clash, same-slot 424053 |
| 35105 | seachBooth | complete+tested | `-1` YB stalls, `-2` YXB stalls, name LIKE, goods-id match |
| 35106 | getBoothDetailInfos (single) | complete+tested | `[sellerId, goods, ybPair, jbPair]`; offline seller answers `[ref, null]` |
| 35107 | buyBoothGoods | complete+tested | listing/price re-verified inside the tx; funds checked before and debited inside; 1002/1003/1006/424049/424050/424054/424067; seller gets 35115-shape balances + 35108 notify, buyer gets 35107 (plus trade-exp frames when the config grants dealaddexp) |
| 35109 | getBoothLog | complete+tested | own seller-view codes, newest first |
| 35013 | getTradeLog | complete+tested | same seller-log view as 35109 |
| 35110 | upBoothName | complete+tested | CJK-only `checkInputName2` port; reject 424044 |
| 35111 | ybSell | complete+tested | offer YB for YXB (grow/shrink/delist-with-refund); short 1002, missing-row delist 424062 |
| 35112 | jbSell | complete+tested | offer YXB for YB; short 1003, missing-row delist 424061 |
| 35113 | buySellYb | complete+tested | exact triple match or 424067; buyer YXB debited, YB credited to booth balance; mismatch 424067, short 1003 |
| 35114 | buySellJb | complete+tested | exact triple match or 424067; buyer YB debited (fee withheld from seller), YXB credited; short answers 424052, missing listing stays silent like the Java action |
| 35115 | getBoothMoney | complete+tested | own `[boothJb, boothYb]` as doubles |
| 35116 | lingquBoothMoney | complete+tested | collect `[1, jb, yb]`; zeroed in the same tx |
| 35120 | getBoothDetailInfos | complete+tested | per-seller detail maps, null holes stay null; online sellers carry name/level/goods-count/flag |

## Push-only (no inbound handler)

| ID | Java | Status | Notes |
| -- | ---- | ------ | ----- |
| 35108 | SELL_NOTIFY | push-only | seller notify frame fanned out on every sale; asserted in the buyer outbox/seller outbox path |

## Money, fees, trade-exp (all genuine records)

- `trade_shui` is absent from the legacy `localization.properties`, so `trade_fee_rate()` is 0.0 and no fee is withheld with real config (`BoothGenuineConfigTest`). Fee math (`0` without a rate, `1` under 10, `round(amount*rate)` above) is pinned by stub-rate tests (10% of 100 -> 90 credited; 10 -> 9 credited).
- `dealaddexp` drives the 120s-gated trade-exp award: level 1 -> 5, level 56 -> 60 (`ZhuJueShuXingBiao`). Stub config reports 0 so trade tests assert no exp frames.
- Money rides the wire as doubles; `tongqian` = YXB, `lingshi` = YB.

## Python deliberate deviations (documented)

- `save_booth` upsert bound 6 values for 5 columns (extra placeholder); fixed, covered by every test that lists.
- A buy naming a seller with no booth row at all answers silence (`None`) instead of 424049; with a row but no such listing it answers 424049. Tests pin both.
- `isChuShou`-gated jades: reachable bag rows are never socketed, so every reachable state lists (no ported subsystem consumes the gate).
- 35114 mismatch answers 424067 like 35113; only a missing 35114 listing stays silent, matching the action's null-skip.

## Gaps

- None in the 19-ID family: 18 inbound complete+tested, 1 push-only.
- Next unfinished families per the census: `friend` (17), `pozhen` (12), `huodong` (38), `gonghuitask` (11).

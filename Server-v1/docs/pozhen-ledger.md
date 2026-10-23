# Pozhen (battle-formation) ledger

Port of `PoZhenAction` (11 inbound), `RolePozhenServiceImpl` (+ the
`MopupInner` sweep math), `PoZhenUtil` (`splitPZ`/`zuzhiMax`/`megre`),
`PoZhenConfigExportServiceImpl` + `PoZhenShaXinConfigExportServiceImpl`
(`PoZhenBiao.dat`/`PoZhenXinXi`/`PoZhenShuaXin` loaders), wired to the
`role_pozhen` SQLite table. Evidence: impl bytecode (3266 lines),
`PoZhenBiao` semantics verified against the shipped `PoZhenBiao.jat`
(150 rows, 10 layers), `PoZhenShuaXin.jat` (998 rows),
`PoZhenXinXi.jat` (open 55, recovery 240 min, sweep gold 1),
`vipbiao.jat` (`pozhen`/`pozhentime`) and `ZuBaoDiaoLuoBiao.jat`
(`@pozhen001-110` groups).

| ID | Java method | status | notes |
| --- | --- | --- | --- |
| 48001 | getInfo | complete+tested | gated 584000; creates row at full VIP bar; sweep settle + daily reset; 11-field VO |
| 48002 | start | complete+tested | sequential gates (YUEJI/NOT_EXIST/NO_REFRESH); layer-complete S:PZATT is attribute-only (folded into live 12010 reads) |
| 48003 | saodang | complete+tested | [1, single, total]; re-entry SAODANGING; uncleared-layer CANNT_SD |
| 48004 | refresh | complete+tested | resets layers 1..cur to 0; refresh gold charged TWICE (jar double-`decr`, pinned) |
| 48005 | move | complete+tested | [1, loc, idx, sweep ms]; never errors past the row gate |
| 48006 | buyPoZhen | complete+tested | FULL_COUNT/FULL_BUY/50006/1003 gates; +1 point and +1 buy count |
| 48007 | sdOver | complete+tested | TIME_LESS/TOP gates; grants stored+1 cell, spends a point |
| 48008 | quickly | complete+tested | JIASU_YB_LESS carries the cost; instant full-count grant |
| 48009 | recovery | complete+tested | full bar succeeds; TIME_LESS early; timer reset at cap |
| 48010 | stop | complete+tested | clears the sweep, keeps landed progress |
| 48011 | getGoods | complete+tested | void grant (both ids read from data[0], like the jar); silent |
| S:PZATT | POZHEN_ATT | push-only (internal) | stage message recalculating fight power; Python recomputes 12010 [7] live, so no frame is emitted |
| 11100 | SYSTEM_BROADCAST | shared push | also declared in PozhenCommands; attributed to juqingfuben in the census, still missing |

The 12010 fight object slot [7] now carries `getFight` over the
cleared layer's attribute bag (270 for a cleared layer 1, 0 before any
progress, matching Java's null-map contribution).

## Java quirks reproduced (pinned by tests)

- Refresh charges the YB cost twice: the jar `decr()`s once for the
  event payload and again for the charge. `test_refresh_resets_and_charges_twice`
  asserts `lingshi - 2 * refresh_gold`.
- Mid-sweep `info` polls grant cumulatively: `saoDangOnline` feeds the
  cumulative elapsed count against the advancing cursor, so a second
  mid-sweep poll grants from the moved cursor again.
  `test_mid_sweep_repill_grants_cumulatively` pins locations
  `1-2` then `1-4` for one 4.5-single sweep window.
- `PoZhenConfig.min` starts at 1 (constructor `iconst_1`), so
  cross-layer advance resolves to order 1; verified against `addSub`
  bytecode rather than assumed.
- Shipped reward factors pay only exp + bag items: every
  `moneyfactor`/`moneyfactor1`/`zhenqifactor`/`zhenqifactor1` cell is
  zero, so the YXB/zhenqi grant paths are live code with no
  shipped-data effect. The award buff multiplies jb and exp only
  (zhenqi rides unscaled).
- Void successes (48002 start, 48011 grant) are silent, following the
  gonghui 81008 / richang 50209 convention; Java sends null-body
  frames instead (documented divergence, same class as 81008).

## Genuine remaining gaps

- `useAwardProp`/`getPropExpireTime` are ported as internals but have
  no inbound ID: no caller in the jar was found among the ported
  systems (the prop-goods effect that feeds them is unported).
- Level-up fan-out frames from sweep/claim exp land in the reply
  tuple (bus pushes in Java); `getGoods` (48011) discards them with
  its void reply.
- `isPassed`/`getMaxLocation`/`getTodayRemainCount` export surface has
  no caller in the port yet (stage/attribute systems will need
  `isPassed` when they land).
- Guild Management itself stays unported; pozhen has no guild touchpoint.
- `11100` (shared broadcast) still missing under juqingfuben.

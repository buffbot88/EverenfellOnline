# JuQingFuBen (story-dungeon) porting ledger

Authoritative per-entry status for the Java `JuQingFuBenAction` surface.
Evidence: `dntg_start.jar` javap of `JuQingFuBenAction`,
`JuQingFuBenServiceImpl`, `JuQingFuBenUtil`, `JuQingFuBenOutputWrapper`,
`JuQingFuBenConfigExportServiceImpl`, `StageJuQingCopyServiceImpl`,
`JuqingStageCopy`, `ItemCreatorServiceImpl.rollItems`,
`Lottery.getRandomKey2`, `StoreGoodsOutput.formart`.

Status words: complete+tested (wire-exercised), parity-unverified
(dispatched but not byte-compared against Java), partial, stub,
genuine-Java-no-op, not-an-inbound-command.

## Bus action (client -> server)

| ID | Java method | Status | Notes |
| -- | ----------- | ------ | ----- |
| 64001 | getInfo | complete+tested | `[1,[highest,daily,best,offline]]`; daily entries are **strings** (`[[id,count]]`); offline entry is `[oneKey,curId,remainMs]` |
| 64002 | challenge(chapterId) | complete+tested | gates NOT_EXIST/LEVEL/IN_COPY/IS_PASS/NOT_ACTIVATED; `SC:APPLY_COPY` approximated by shared-world entry + `64009` enter state; daily set to 1 at entry |
| 64004 | autoChallenge(chapterId, oneKey) | complete+tested | VIP only when oneKey; needs best time; reply `[1,id,key,fastMs]` |
| 64006 | finishAutoPass (finishSaoDang) | complete+tested | done `[1,id,key]`; running `[-1,id,remainMs]`; idle `[0,NO_AUTOPASS]` |
| 64007 | accelerateAutoChallenge | complete+tested | YB `decrCheck` then `decr` (1002 when short); reply `[1,id,costYb]` |
| 64010 | getAwardInfo | complete+tested | persistent sweep-award list `[[chapter,pingjia]]` or null |
| 64012 | lingquAward | complete+tested | consumes the staged victory PassAwards only; pending cleared **before** grants (crash loses, never duplicates); reply is `lingJiangSuccessResult` `[1,exp,yxb,zq,fixedPairs,rollFormart]` |
| 64013 | oneKeyLingquAward | complete+tested | per-entry fresh passAwards + one lottery draw each; skips chapters with missing config; reply `[exp,yxb,zq,[formarts]]` (no leading 1) |
| JQ:LOGIN | roleLogin | complete+tested | running sweep clock restarts at login |
| JQ:LOGOUT | roleLogout | complete+tested | elapsed millis bank into `usetime` at logout |

There are no other inbound IDs: 64003/64005/64009/64011 are **not**
client commands in the Java mapping (64003/64008/64009 are stage-side
pushes, see below). A previous draft implemented 64003/64005/64011 as
commands; that was wrong and has been removed.

## Stage pushes (server -> client, no client command)

| ID | Producer | Status | Notes |
| -- | -------- | ------ | ----- |
| 64003 | challengeOver / expireCheck | complete+tested | 10-elem `challengeSuccessResult` on win; `[1,chapter,3]` on expiry |
| 64008 | applyLeaveCopy | partial | `[1]` reply ported on expire; full `SC:APPLY_CHANG_MAP` home routing needs stagecontroll (unported), role keeps its map |
| 64009 | JuqingStageCopy.enter | complete+tested | `[restMs,mapId,chapter,killMap]` on entry only; **no** per-kill push exists in Java |

## Victory lifecycle (the 64012 staging path)

`challengeResult(roleId, chapter, ROLE_WIN, costMs, deadTimes)`:
highest/daily(+2)/best persist, `passAwards` computes
`(level*slope+base)*oddsMap[pingjia]` + fixed goods + `rollItems`
candidate map, staged transiently (`DataContainer`, per-process), and
the 10-elem result pushes as 64003. The client claims via 64012, which
grants currencies through the incr services, converts fixed goods,
draws **one** `getRandomKey2` roll item, puts everything in bag-or-mail
(`putInBagOrEmail1`), and removes the staging first.

Python faithful points: per-entry candidate lottery with resolved-odds
weights (nested `@group` flatten via `componentRoll`), first-model-only
truncation, `setId(str(index))`, chapter rollBind overwrite, fixed
`gid|count|bind` cell binds, `min(timeGrade, deadGrade)` rating, raw-ms
cutoff comparison, `Huoyuedu("4")` event has no ported subscriber and
is skipped like other event publishes.

Python deliberate deviations (documented, not parity-verified):
- Staging persists in `role_juqing.pending_award` instead of the
  in-memory `DataContainer`, so a claim survives reconnects (the wire
  protocol allows claiming later; Java would drop it).
- No real copy instances: `isInCopy` is approximated by the active
  attempt marker (`tiaozhan_jindu`, a field Java never reads/writes —
  its attempt state lives in the stage object), shared-world kills
  count toward the wanted total (`killCount >= monsterCount`
  semantics), and expiry/cleanup run on the session scheduler.
- Currency incr caps are not ported: granted amounts equal computed
  amounts (port-wide convention).
- `64001` daily/best rows are sorted for determinism; Java HashMap
  order is nondeterministic.
- Equip-attribute generation in drops is out of scope: no shipped
  JuQing drop chain yields equipment (verified against ZuBao data).
- ZuBao time windows: shipped rows carry no window columns, and
  `checkTimeDropNow` is true when all windows are zero, so every
  group is always droppable.
- `getTodayRemainCount` / `isPassed` / `getZyZhuiHuiCount` /
  `getZiYuanZhuiHuiMaxCount` are export-service helpers for other
  systems (resource reclaim), not client commands: deferred.
- `KillMonsterAwards`, `vipAutoFightAwards`, `autoFightPassAwards`,
  `killMonsterAwardsOutput`, `passAwardsOutput`,
  `JuQingFuBenUtil.awardInfoDecr` are referenced by **no** class in the
  jar: genuine Java dead code, not ported.

## Entity (`RoleJuqingfuben` -> `role_juqing`)

`userRoleId, passedHighestId, passedIdsDaily ('id:count;...'),
autoPassInfo ({onekey,curid,starttime,usetime} JSON),
bestPassedInfo ({chapter:{time,estimate}} JSON),
refreshTime, awardInfo ([{id,pingjia,time}] JSON),
tiaozhanJindu` (attempt marker, see above), plus the port-only
`pending_award` staging cell.

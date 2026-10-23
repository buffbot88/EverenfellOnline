# ZuWuFuBen (clan-dungeon) porting ledger

Authoritative per-entry status for the Java `ZuwufubenAction` surface.
Evidence: `dntg_start.jar` javap of `ZuwufubenAction`,
`ZuwufubenServiceImpl`, `ZuwufubenOutputWrapper`,
`ZuWuFuBenConfig Intelligence`, `ZuWuStageCopyServiceImpl`,
`ZuWuStageCopy`, `ZuwuServiceImpl` (guardian activation),
`VipConfig` (`zuwucishu`/`zuwutime`), `ZuWuCiShuGouMai`,
`SaoDangVo`, `Lottery.isSuccess`, `StoreGoodsOutput.formart2`.

Status words: complete+tested (wire-exercised), parity-unverified
(dispatched but not byte-compared against Java), partial, stub,
genuine-Java-no-op, not-an-inbound-command.

## Bus action (client -> server)

| ID | Java method | Status | Notes |
| -- | ----------- | ------ | ----- |
| 108001 | getInfo | complete+tested | `[1,[passMax,everyday,saodang]]`; rows are `[[idStr,used,total]]` with `total=bought+1`; sweep is `[sdId,endMs,autoPass]` or null; daily refresh + elapsed-sweep settle run inline |
| 108002 | enterFuBen | complete+tested | gates center 114008 / sweeping 114003 / level 1000 / locked 114001 / no-attempts 114002; entry queues the shared-world `change_map` + `108007 [id,restMs]` push, marks center, arms the expiry timer; replies `[1,id]` |
| 108004 | saoDangFuben | complete+tested | running sweep 114003; null id sweeps lowest cleared dungeon with attempts left (114005 when none); explicit id needs unlock 114009 + attempts 114002; burns one attempt, arms the vip-length timer; replies `[1,id,endMs,autoPass]` |
| 108006 | quitFuben | complete+tested | clears center, drops the attempt + expiry timer; replies `[1]` |
| 108009 | buyFightCount | complete+tested | locked dungeon 114004, vip cap 114006, YB `decrCheck`/`decr` first (1002 when short); bought and remaining both grow; replies `[1,id,used,total]` |
| 108010 | refreshFubenCd | complete+tested | idle 114007, auto-pass 114010, wrong id `[0,0.0]`; YB `decrCheck`/`decr` first (1002 when short), then the running sweep settles early with its 108003 push; timer cancelled; replies `[1]` |
| 108011 | buyFightCountAll | complete+tested | no clears `[0]`; no buyable dungeon `[0,114006]`; summed YB `decrCheck`/`decr` first (1002 when short); replies `[1,[[id,used,total]]]` |
| ZW:LOGIN | roleLogin | complete+tested | a running sweep restarts its clock at login |
| ZW:LOGOUT | roleLogout | complete+tested | banks the sweep remainder (50s floor when elapsed), clears center + attempt |

There are no other inbound IDs: 108003/108005/108007/108008 are
server pushes (see below).

## Stage pushes (server -> client, no client command)

| ID | Producer | Status | Notes |
| -- | -------- | ------ | ----- |
| 108003 | finishFuBen / sweep settle / refresh | complete+tested | `[dungeonId,formarts]` victory + manual-sweep + refresh rewards |
| 108005 | auto-pass chain | complete+tested | `[dungeonId,nextId,[nextId,endMs],formarts,used]`; chain advances while dungeons have attempts left |
| 108007 | ZuWuStageCopy.enter | complete+tested | `[dungeonId,restMs]` on entry only |
| 108008 | ZuWuStageCopy.killMonster | complete+tested | `[monsterTplId]` per counted kill; no per-kill reward in Java |

## Victory lifecycle (the finishFuBen path)

Shared-world kills count toward the active attempt's wanted map
(`complete` monster:count pairs); every template must reach its count.
On completion: first clears advance `passMaxId`, activate the guardian
(`jihuoZuwu` level-1 `RoleZuwu` row + refreshed 111000 push) and open
the next dungeon; every clear burns one attempt, clears center, cancels
the expiry timer, grants the fixed `gditem` drops without the zubao
lottery (`finishReward` is called with lottery False), and pushes 108003.

Python faithful points: per-template kill accounting, first-clear
unlock ordering, attempt burn on victory (entries themselves do not
burn), fixed-drop routing (xuni goods to the bag dummy, real goods to
bag-or-mail), `formart2` 18-slot records, sweep settle persistence
before each push (a repeated settle can never grant twice), vip-gated
sweep durations (`zuwutime` ms) and buy caps (`zuwucishu`).

Python deliberate deviations (documented, not parity-verified):
- No real copy instances: the attempt marker lives on the session
  (`_zuwu_attempt`, dropped on quit/expiry/disconnect) instead of the
  stage object; shared-world kills count toward the wanted total;
  expiry/disconnect cleanup runs on the session scheduler.
- `108001` daily rows are sorted for determinism; Java HashMap order
  is nondeterministic.
- `111000` owned guardians render `[id,level,0,0,0]`; the trailing
  mock type cell has no owned-row source in the ported getter.
- `SC:APPLY_COPY` / `SC:APPLY_CHANG_MAP` home routing is approximated
  by shared-world `change_map`; the role keeps its map on quit/expiry
  (needs the unported stagecontroll history).
- `ZuWuFuBenRefreshEvent` and guardian-activation events have no
  ported subscribers and are skipped like every other publish.
- Sweep auto-pass chains settle inline on the timer instead of the
  Java `ZW:FUBENSAODANGFINISH` schedule message; the wire pushes match.

## Entity (`RoleZuwufuben` -> `role_zuwufuben`, `RoleZuwu` -> `role_zuwu`)

`role_zuwufuben`: `pass_max_id`, `everyday_pass_data` ('{"id":left}'
remaining attempts), `buy_count_data` ('{"id":bought}'),
`saodang_data` (SaoDangVo JSON), `everyday_time` (daily touch, ms).
`role_zuwu`: `(role_id,zuwu_id)` with `level,exp,jieshu,fail_count`;
`jihuoZuwu` creates level-1 rows with `jieshu` from ZuWuShuxing.

## Config (all real records, no invented values)

`ZuWuFuBen.jat` (map/pos/level/expire/gold/wanted/fixed/lottery/
guardian), `ZuWuCiShuGouMai.jat` (buyIndex->yuanbao),
`ZuWuShuxing.jat` (guardian tiers), `VipXinXi.jat`
(`zuwucishu` caps, `zuwutime` seconds), `goods.jat` (`xuni` routing).

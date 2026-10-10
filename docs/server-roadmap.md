# Server-Side Development Roadmap (Python port of the Java game server)

Oracle: the live Java server + `reference/TonNgoKhong` configs; captures in
`output/orig-stack/tap-decoded.txt` (727 msgs, 25 server IDs). Rules: port
from bytecode, never invent numbers, golden-test everything, update this file
and the parity audit per phase. No servers start/stop without the user asking.

## Completion tracker (denominator: 71 `*Commands` jar modules)

| Phase | Scope | Modules | Running % |
|---|---|---|---|
| 0 (done) | Socket framing, INITKEY, login/roles/enter-world/map, settings, currency, scene entry, monsters, mount, attr formulas + gear/dan bags | 15 | ~21% |
| 1 (done) | Init burst: 12010 (layout + ZhanLiXiShu values), 62000 (+role_vip), 32000, 35011, 64001/64010, 108001, 111000, 19000 | +8 = 23 | ~32% |
| 2 (done) | Entry buffs: 42100 list, 42005, 40501, 42102 | +3 = 26 | ~37% |
| 3 | Combat loop: 42002 damage, 12004 persist, 43000, 12030, 12001, 24002/23002 | +4 = 30 | ~42% |
| 4 | Monster AI: moves, counterattacks, pet combat | +4 = 34 | ~48% |
| 5 | Effect bags: VIP/xianjie/chenghao/meiren → closes 12000 residual | +3 = 37 | ~52% |
| 6 | Long tail (bag, skills, tasks… as the client requests them) | → 71 | 100% |

## Phase 1 evidence log (all from `dntg_start.jar` via `tools/javap.py`)

- 12010: `ZhanDouLiWrapper.getFightObject` Object[25] slot order; values via
  per-system getters × `ZhanLiXiShu.jat` factors through `getFight`
  (int-accumulated, skips factorless keys). Only level/gear/dan/vip computed;
  other systems need unmigrated tables (zeros = Java's empty-source default).
- 62000: `GetVipOutPut.getVipInfo` Object[5], day/week zeroed at vipLevel 0.
- 32000: `MallAction` (silent on empty category) + `MallServiceImpl.shopList`
  ([1, sign, raw rows]); sign is null (classpath loader), `[-1]` unreachable.
  Categories group `WuPinChuShouBiao.jat` by modelid, pages ascending.
- 35011: `UserAccount.recive_yb` int.
- 64001: `[1, [highestOr0, dailyOrNull, bestOrNull, offlineOrNull]]`; 64010 null
  on missing/empty awardInfo.
- 108001: `[1, [passMaxOrNull, everyday[], saodangOrNull]]`.
- 111000: `[entries[], wuhunFragCount]`; empty role → per-type
  `mockZuwuInfo [firstJieshu1Id,0,0,0,type]` from `ZuWuShuxing.jat`.
- 19000: `PingVo.genInterval` = 5000 + `Random.nextInt(5000)`.

## Phase 2 evidence log (all from `dntg_start.jar` via `tools/javap.py`)

- 42100: `FightOutputWrapper.buffChange` sends
  `[fighterId, addBuffInfos, removeBuffIds]`; `BuffStatistics` returns null
  for empty lists (hence combat `[fid, None, None]`) and clears after flush.
  Adds are `IBuff.getClientMsg`, removes are `getId`.
- `Buff.getClientMsg` (5 slots): `[id, buffId, remainingMs, layer,
  attackerId]`, remaining = duration-(now-start) or -1 when permanent
  (vip010 has no lasttime -> captured -1.0; birthprotect lasttime 10000 ->
  captured 10000.0; removed as `['buff_64_108']` on expiry).
- `PropBuff.getClientMsg` (6 slots): `[id, buffId, remainingOrValue, layer,
  attackerId, timedFlag]`; expfolds (lasttime 3600000, stacked -> 6M-21M
  remaining) show remaining + flag 0, xuechi/lanchi pools (no lasttime)
  show the pool value + flag 1.
- Entry set is role state: VIP buff `vip001..vip012` (effectlevel, all
  permanent) iff vip_level > 0, birthprotect always, pools/expfolds only
  when the role holds them (fresh role in probe-stress: birthprotect
  alone). Order vip -> ... -> birthprotect from probe-111111.
- 42005: `FightServiceImpl.skillReadyFire` ->
  `readyAttackSkill(category, dynamicCd)` = `[skillCategory, cd]`;
  `PublicCdManager.toDynamicCd` = int(cdtime/(1+gongjisudu/2000)), cdtime
  700 for t070 (CdBiao) -> 651 with the captured role's live 147.4 attack
  speed (float32 and float64 agree). Category is role skill state
  (client fires `normal003`); unmigrated roles skip the frame, not fake it.
- 40501: `RoleEventManager.enterFightState2` -> bare role-id string.
- 42102: `FightOutputWrapper.buffValueChange` ->
  `[ownerId, propBuffId, poolValue]` (xuechi regen ticks 327286->328996).
- Wire numbers: Java Longs arrive as AMF3 doubles (durations, pool
  values), Integers as ints (layer, flags) -- builders cast accordingly.
- Buff/pet instance ids are `buff|propbuff_<stage>_<seq>` off JVM-global
  counters (buff_64_101..108, zuoqi_64_109 share one counter); the port
  uses session-local counters restarted per stage entry (unique where the
  client matches them, documented in `Session`).
- Known gaps: pool/expfold entry values need unmigrated item state;
  42102 has no pool-regen scheduler yet (builder tested, unwired).

## Conventions

- New tables follow the role_equip/role_attr_buff/role_vip pattern: minimal
  legacy columns, `save_`/`get_` on `Store`, migrator copies scoped by
  `--users`, mock-tested in `tools/tests`, golden-tested in `Server-v1/tests`.
- Session callbacks default to empty (no-data-safe) so unmigrated roles work.
- Known approximations live in code docstrings: `getFight` HashMap order
  (bounded truncation drift; int-exact maps unaffected), mall page order.

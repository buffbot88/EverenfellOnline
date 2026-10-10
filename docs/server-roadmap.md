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
| 3 (done) | Combat loop: 42002 damage, 12004 persist, 43000, 12030, 12001, 24002 | +4 = 30 | ~42% |
| 4 (done) | Monster AI: moves, counterattacks, pet combat, respawn | +4 = 34 | ~48% |
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

## Phase 3 evidence log (all from `dntg_start.jar` via `tools/javap.py`)

- Combat is client-relayed: every C> 42002 (role 16, pet 21, monster 81) has
  exactly one S> 42002 in the tap. skillFire resolves fighter + skill by
  category (unknown -> silent return), fight() per target, one Object[6]
  broadcast [fighterId, category, index, hits[], arg4, arg5].
- changeOutput order (byte-exact in the tap): 12004(target), 12004(attacker
  iff changed), 42100(target null-flush), 42100(attacker null-flush), 43000
  iff dead; then the 42002; per role-credited kill 12001 then 12030.
- Hit record [targetId, HarmType.getVal, harmVal(int), isDead]: PUTONG 0,
  SHANBI 1 (miss, val 0, and acceptHarm skips it so no 12004 follows),
  BAOJI 2. 12004 carries Java Floats (doubles on the wire).
- Damage (ShanghaiResultCalculator + T21, all goldens reproduce exactly):
  E = max(wuli - max(fangyu*(1-pojia)-qiege,0) * max(1-max(lv gap,0)/100,0),0),
  v = max((fa*E + fb + maxHp*shishen) * max(1+eff122+dmg-def-eff126,0)
  + (eff121-eff125), max(lv*formuleg,0)) + fa * elementals; formulec pow iff
  > 0; crit x max(1.5+b-c,1); block x 0.5; role-vs-role x 0.8; clamp above
  2^31. The lv*formuleg term is a max() floor, not an addend -- that single
  reading reconciles every golden (role 1649 / crit int(1649.84*1.5) = 2474 /
  monster max(10,30) = 30 / pet 100).
- Crit/miss chances (T7/T8, clamped [0.05, 0.95]): role->monster
  baojiA/(sum) * lvA/(sum) * 0.7 (captured ~22% crit rate matches),
  miss shanbiT/(sum) * lvT/(sum) * 0.5 with an inverted roll (hit iff the
  lottery fails); monster->role factors 0.3 / 0.2; voltcalculate=0 (zuoqi11)
  always hits, criticalcalculate=0 never crits (pet always [0,100,0]).
- Exp (AiServiceImpl.monsterExpDrop): (long)(basicExp * (1+(n-1)*0.05) *
  ShaGuaiXiuZheng * JingYanShuaiJian) * (1+serverRate) through calFightExp
  (ewai + exp-fold + guild + VIP + event, else unchanged); incrExp persists
  and sends 12001 [expTotal(Long), level], then 12030 [deadId, templateId,
  exp(Long)]. Captured +51 = base 4 x the role's unmigrated exp-fold buffs.
- 43000 [1, inner]: role killers send the 5-slot inner array, pet killers
  the 6-slot owner variant (IPartner branch, shape-tested, no capture).
  24002 [[fighterId]] builder tested; leaves/respawns are AOI-scheduled
  (~60 msgs after the kill in the tap), so no leave is wired yet (Phase 4).
- Session keeps monster HP + pet state + dead set; role HP/exp persist via
  save_role_state. Skill rows come from JiNengBiao (highest tier), monster
  stats from GuaiWuBiao, decay/correction from JingYanShuaiJianBiao /
  ShaGuaiXiuZhengBiao. Unknown skills/fighters/dead targets are ignored.
- Known gaps: effect attributes/elementals/shishen/damage/defence default 0
  (sources unmigrated); heal calculators, DiKang/skill-resist/fixed-harm
  paths, MP costs, level-up thresholds, pet-HP persist, combat 42005
  refresh triggers, entry-12004 int-vs-Float question.

## Phase 4 evidence log (all from `dntg_start.jar` via `tools/javap.py`)

- Monster readies are server-driven 42001 Object[7] [1, monsterId,
  'monster06', targetPixel, None, 1, roleId] (AiFightServiceImpl.skillExecute
  -> FightOutputWrapper.skillReady); the pixel is the target tile scaled
  x*60/y*30 (role tile 44,33 -> [2640, 990], constant across all 81 captured
  readies). Pet readies carry a path and null target like roles.
- Monster moves are 40000 [x, y, bornFlag, 6, id] (AiFightServiceImpl.move one
  A* step + AiFightOutput.move; bornFlag 0 at born else 1). Pets send kind 2.
- Death -> Monster.deadHandle -> scheduleDisappearHandle ('AI:RETRIEVE'
  after disappearDuration seconds) -> AiServiceImpl.retrieve recycles the
  element (24002 [[deadId]]); the produce team re-enters a 23002 record with
  the respawn flag set (index 15 True vs False at entry, fresh ids m_64_110+
  off the stage counter). GuaiWuBiao gives asheslast 3 / creattime 5 for
  D040011; the tap shows ~58 msgs kill->leave, ~34 leave->respawn.
- Aggro is MonsterHatredManager (damage + eyeshot presence; D040011 eyeshot
  5, maxrange 9 leash, ifactive 1, velocity 450); states XUNLUO -> FIGHT ->
  BACK -> XUNLUO live in refreshState. Pet yetenek mirrors the owner's swing
  (PetFightServiceImpl.skillExecute, same fight pipeline).
- Session drives one ai_tick() after every 42002 in handle() plus explicit
  calls: hatred retaliation (ready + _resolve_fire), greedy walkable chase
  steps (A* degraded, documented), BACK-to-born on hatred loss/leash, pet
  follow steps past 2 tiles, asheslast/creattime leave->respawn clock (1
  tick = 1s). Pet auto-fire rides the owner's swing with a single-waypoint
  path (Java sends the A* path).
- Known gaps: XUNLUO random wandering, HeartBeatRate/XUNLUO_PERIOD scheduler
  cadence (action-driven instead), pet teleport-to-owner, boss/summon/speak
  AI, item/money drops (deadDrop), role-vs-role hatred, tile->pixel offsets
  while moving.

## Conventions

- New tables follow the role_equip/role_attr_buff/role_vip pattern: minimal
  legacy columns, `save_`/`get_` on `Store`, migrator copies scoped by
  `--users`, mock-tested in `tools/tests`, golden-tested in `Server-v1/tests`.
- Session callbacks default to empty (no-data-safe) so unmigrated roles work.
- Known approximations live in code docstrings: `getFight` HashMap order
  (bounded truncation drift; int-exact maps unaffected), mall page order.

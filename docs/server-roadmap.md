# Server-Side Development Roadmap (Python port of the Java game server)

Oracle: the live Java server + `reference/TonNgoKhong` configs; captures in
`output/orig-stack/tap-decoded.txt` (727 msgs, 25 server IDs). Rules: port
from bytecode, never invent numbers, golden-test everything, update this file
and the parity audit per phase. No servers start/stop without the user asking.

## Completion tracker (primary denominator: 886 command IDs in docs/command-ledger.md; module count secondary)

ID track: 76 of 886 dispatched (8.6%) — 68 golden-tested, 8 dispatched-only, 810 not started. Module track: 40 of 71 `*Commands` modules touched (~56%). Tables: 17 SQLite vs 176 MySQL (163 unmapped). Family counts overlap (IDs repeat across modules); phase totals are approximate. `public_` (183 IDs) is unassigned shared surface needing triage — many entries may be notify/client-only numbers, not server commands.

| Plan phase | Families (IDs) | Golden | Dispatched-only | Left |
|---|---|---|---|---|
| 0 harness+ledger | tooling | ledger generated (886 rows), replay world-entry only | — | `persisted`/`client-verified` ledger statuses; generalized replay; recapture (blocked by no-live-runs rule) |
| 1 core loop (69) | bag 21, equip 13, vip 12, setting 5, role 5, mall 4, account 3, skill 3, skillbook 3 | 52 | 0 | 14: equip 3; bag 5 (incl. 30301 prop-use); mall 2; role 3; account 1 |
| 2 scene (210) | stage | 6 | 0 | 204; no scheduler (ai_tick runs off role actions), no event bus |
| 3 progression (116) | task 26, chengjiu 2, jiangli 29, shenjiang 18, zuoqi 13, pet 12, baoshi 4, xianjiechenhao 7, meiren 5 | 2 | 5 | 109 not started + 5 dispatched-only (50001/50002/50003/50005/50008 report, submit pays) |
| 4 social/events (~130) | email 9, huodong 31, hefuhuodong 7, qianfuhuodong 5, gonghuitask 11, marry 8, guildfuben 7, juqingfuben 8, zuwufuben 9, + wheels/gacha/rankings/pozhen/toubao | 0 | 3 | ~127 |
| 5 GM/framework (~35) | gm 18, jinfeng 5, kuafu 6, + messageswap/eventservice/configure | 0 | 0 | all; needs event-dispatch + multi-node design note first |
| triage | public_ 183, gamerule 13, vipqq 6, xunbao 6, shenqi/shenmi/zhouhuan/jijin/xianshi* | 0 | 0 | classify before assigning to a phase |

Module history (how the 38 touched modules landed): socket framing/login/enter-world/map/settings/currency/scene entry/monsters/mount/attr formulas (15), init burst 12010/62000/32000/35011/64001/64010/108001/111000/19000 (+8), entry buffs (+3), combat loop (+4), monster AI (+4), effect bags (+3), equip 31000 (+1), bag 30000–30302 (+2 families' worth: bag 15, task 6 commands), equip enhance 34000/34003/34009 (+3), equip jinjie 34001 (+1), equip jianding 34004/34005/34006 (+3), equip hecheng 34007/34008 (+2), vip gifts+kaifu 62001/62002/62004/62020/62021/62022 (+6), skill/skillbook 42000/42003/99000/99001/99002 (+5), vip huodong 88000/88001/88002 (+3), setting 13001/13002/13003/13004 (+4), equip dress 31001 (+1), mall buy 32001 (+1). Evidence logs below are unchanged.

## What's left (updated 2026-10-14)

- Phase 0: ledger generator is the only source of counts (never hand-edit); still missing the `persisted` and `client-verified` statuses the definition of done requires — that is a code change to tools/architecture_audit.py plus its tests. Replay generalizes only world entry; recapture and per-phase live projector runs are blocked until a run is explicitly asked for.
- Phase 1: bag is closest (15/21; 30301 needs the Phase 2 stage runtime, 30104/30105 are push-only IDs covered by test mentions). Vip inbound is done (all 10 routable IDs; 62003/62006 service-internal push-only, 62005 a stage push). Setting is done (13000-13004). The equip 3 (30106/31015/31016) have no inbound route jar-wide and are already emitted plus golden-asserted as pushes, so they need no slice. Next largest wins: bag 5, mall 2 (32001 buyGoods landed portable: no guild/coupon-discount; 32002/32006 shop cluster left), role 3. Skill+skillbook inbound is done (42000/42003/99000/99001/99002); 42004 stays push-only like 30104/30105.
- Phase 2: the 1-second scheduler (Quartz mirror) and the in-process event bus are the structural gaps; 204 stage IDs sit behind them.
- Definition-of-done gap (structural): per-command client verification cannot happen under the no-live-runs rule, so no row can reach `client-verified` until the endgame; the phase plan's "live run once per phase, only when asked" is the agreed valve. Do not mark rows verified without a run.
- Security before cutover (from the parity audit): forgeable MD5 game sign, cookie flags, ownership checks on mutating commands, rate limits.
- Data rule unchanged: migrate a table only when a command module needs it, via tools/migrate_mysql_to_sqlite.py; update the audit mapping table.

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
  (~60 msgs after the kill in the tap), now wired through the asheslast timer in `ai_tick` (Phase 4, `test_ai`).
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

## Phase 5 evidence log (all from `dntg_start.jar` via `tools/javap.py`)

- Bags vs buffs: replaceXianJie/ChengHao/MeirenAttribute incrBaseAttribute
  (XIANJIE/CHENGHAO/MEIREN) -- no-effect bags; replaceVipAttribute adds a
  BuffManager buff whose effectPro cells become the numbered effect slots
  the formulas read (BuffFactory.create copies BuffConfig.getEffectPro into
  Buff.attributes; createBuffAttributes maps effectpro1..5 ->
  effectproNvalue1, e.g. vip010 {5:1000, 7:500, 1:2000, 14:0.1, 16:0.1}).
- XianJieConfig.getShuxing / ChengHaoConfig.getAttribute parse 'k:v;k:v'
  via getattMap (';' then ':', Float); chenghao ids sum with
  MapUtil.addMapValue; xianjie takes one id (getXianjieId: null when no
  row, '1' default on empty array, else the String.compareTo maximum --
  '2' beats '10'); chenHaoIds is null on empty, else every id.
- Meiren: getMeiRenAllObj builds [typeId, level, heti] triples (type from
  MeiRenConfig.getMeirenTypeId, unlisted meinvid dropped), business
  chanmianCount is meiren_heti, and replaceMeirenAttribute selects the
  type's level row by chanmianCount (meirenLevelMap keyed by meinvlv,
  null logged and skipped); each bag is
  ConfigAttributeParser.attribute2Map(row) over the 41-key universe.
- Slot polarity from formula bytecode: 6/8/10/12-pct vs 5/7/9/11-flat,
  14/13 and 16/15 pct/flat (ShenFa multiplies by e16), MaxHp =
  hitpoints*(1+e2+shenyou)+e1 (VIP HP+2000 lands on unpushed key 0).
- Captured 12000 decomposition (fu0UR1-0-1-1, lv 56, vip 10, xianjie 1,
  chenghao 2): '6' 147.4 = (1+130+3)*1.1, '7' 616.0 = (550+10)*1.1,
  '1' 1811.0 = persisted max_mp -- all exact; flats '2' 1982.8 (res 67.0),
  '3' 962.8 (res 34.0), '4' 174.65 (res 17.0), '5' 179.65 (res 17.0).
  role_stage pins max_hp 5466 / max_mp 1811. The documented residuals are
  asserted so later phases (shenjiang/zuoqi/guangyi/...) close them loudly.
- Migration: role_xianjiechenhao (id JSON arrays) + role_meiren
  (id/level/heti) join role_vip under `--users` scoping; live DBs need one
  re-run to populate the new tables. role_meiren is empty for the captured
  roles, so the meiren path is golden-tested against real meiren.jat rows.
- Known gaps: the 67/34/17/17 flat residuals, MaxHp push (key 0 never in
  12000), pet/meiren combat-power contributions, VIP exp-fold/pool buffs.

## Phase 6a evidence log (all from `dntg_start.jar` via `tools/javap.py`)

- `replaceZuoqiAttribute` (RoleFactoryHelper): gate is business maxRank
  (RoleZuoqi.rank via ZuoQiWrapper, set only when > 0 in RoleFactory.create),
  level row is `loadByRank(rank)` at `getZuoqiLevel` (role level clamped to
  [0, maxlv]; minLevel is never set in the jar so the floor is 0), bag is
  the row's `attribute2Map` minus velocity (ConfigAnalyzeUtil-
  .refineAttributeMapWithOutMoveGongjiSp drops only that key despite its
  name). The attribute-goods multiplier loop is traced but unwired:
  `attribute_goods_id` is NULL for every role in the legacy DB.
- `replaceZuoqiSudu` is double-gated on rideOrNot (RoleFactory.create +
  inside itself) into a separate ZUOQI_SPEED bag; decodeZuoQiInfo reads
  rideOrNo false from the stage blob at entry, so Java skips it too -- the
  port's empty bag matches, and '7' stays 616.0.
- `replaceShenJiangAttribute` adds each owned shenjiang's jiangxingtu
  attributeMap, but empty jiangxingtuId is skipped; both legacy
  role_shenjiang rows carry empty ids, so the JIANGXINGTU bag is provably
  0 for every migrated role and no role_shenjiang table was added.
- Captured-role proof (rank 1, role 56 -> level 30 row): bag
  {hp 134, mana 101, dmg 67, def 34, crit 17, volt 17} closes the Phase 5
  67/34/17/17 residual exactly; slot '1' is unaffected (persisted max_mp)
  and '7' is unaffected (velocity refined out). 12000 is now exact on all
  eight slots, golden-tested in test_effect_bags.py.
- 23009 slot 12 needs no code change: ZuoQiPet.getYiDongSuDu delegates to
  the owner via PetFightAttribute, and the port already sends the computed
  12000 '7'. The replay's remaining 23009/12000 diffs are bare-scratch-DB
  artifacts (no gear/vip rows seeded), not regressions.
- Migration: role_zuoqi (rank/cur_rank) joins the `--users` scope; live DBs
  need one re-run to populate it. role_stage.zuoqi_info was already
  migrated (curRank/rideOrNot source).
- Known gaps: jiangxingtu activation (no legacy rows), goods
  multiplier, riding-state speed changes.

## Phase 6b evidence log (all from `dntg_start.jar` via `tools/javap.py`)

- `ZhanDouLiServiceImpl.getZuoQiJiChuFight` = getFight over
  `loadByRankLevel(getZuoQiRank, roleLevel).getAttributeMap()`; rank 0
  (or a missing row) returns null, hence 0. `getZuoQiRank` reads
  `RoleZuoqi.rank` (null entity -> 0); `loadByRankLevel` returns null
  for rank 0 and otherwise clamps via getZuoqiLevel; `createZuoQiConfig`
  sets only maxLevel (minLevel never set -> floor 0).
- The `attributeMap` field IS `ConfigAttributeParser.attribute2Map`
  (`createLevelConfig` wraps it in a ReadyOnlyMap), so the fight runs
  over the same cells Phase 6a ported; velocity needs no special case
  because its ZhanLiXiShu factor is 0.0. The 193 is HashMap-order-proof
  (all 720 product permutations truncate to 193 under per-addition f2i).
- `getZuoEquipFight` = one getFight over the merged
  `getEquipAttributeAll` map of the [-105, -100] equip rows
  (`EquipConstants.ZUOQI_SLOT_MIN/MAX`, inclusive between-filter) --
  merged first, unlike body equip's per-item truncation. Live MySQL:
  zero role_equip_slot rows in that range, so 0 for every legacy role.
- `getlongLingOrLongHun` returns 0 on an empty goods map, and
  attribute_goods_id is NULL for every legacy role (live MySQL count
  0) -- longhun stays 0 with no new table.
- Oracle proof: probe-B captured [193, 0, 0] for fu0UR1-0-1-1 (rank 1,
  level 56 -> maxlv 30); probe-A captured [0, 0, 0] with no mount
  state. 12010 slot [3] is now exact, golden-tested in
  test_effect_bags.py (ZuoqiFightTest: 193, rank-0/row-missing zero,
  equip-slot filter, session-level [193, 0, 0]). No migrator change:
  rank flows through the Phase 6a role_zuoqi table and slot_num was
  already migrated with role_equip.

## Phase 7a evidence log (all from `dntg_start.jar` via `tools/javap.py`)

- `RoleEquipSlotServiceImpl.getInfoEquip`: loads role equip slots, then
  `StoreGoodsOutput.formart1(List)` -> `send2One('31000', array)`; an empty
  list sends null. The jianding daily-reset side effect is not ported
  (jianding rows are not migrated).
- `formart1` record = 18 slots: goodsId, StoreGoods.id, slotNum, count,
  userRoleId, itemLevel, rareLevel, bind, expireTime, qhFuJiaAttrClient,
  xingxingLv, null, zhanli (`getEquipFightById` = getFight over
  `getEquipAttributeAll` of the item), '', qhXingXingsClient, exp (Long),
  luckyValue, jingyanyu exp (Long).
- `GoodsEquipVo(String)` reads qhcount, jjfailcount, qhxingxing and
  fjattrstr from the JSON blob. `getQhXingXingsClient`: qhcount 0 -> ten
  zeros; blank -> null; more pairs than qhcount -> null; else pad with 0.
  `getxingxingLv` counts star pairs whose value is 1.
- Approximations (no legacy column): slot 1 uses the goods id (the client's
  use of this id is not verified), count 1 (gear does not stack), bind 0,
  expire null. Category checks assume every role_equip row is gear.
- Golden-tested in `EquipInfoHelpersTest` / `EquipInfoFrameTest`
  (test_effect_bags.py). Server-v1 228/228, tools 26/26.
- Not yet ported from the long tail: the other ~33 modules, including the
  bag (30000-30306), mall purchases, quests, guild, dungeons, and skills.

## Phase 7b evidence log (all from `dntg_start.jar` via `tools/javap.py`)

- 12010 slot [2] = `ZhanDouLiServiceImpl.getRoleJiNengFight` (index 0) and
  `getRoleKangXinJiNengFight` (index 1), both over
  `RoleSkillExportService.getSkillFighting` -> `SkillServiceImpl`: per owned
  `role_skill` row, `loadSkillInfoByLevel(category, level)`; rows with
  `tableShow` 2 add `combat` to the skill bucket, 1 to kangxin.
- `SkillConfigExportServiceImpl.createSkillInfoConfig` reads `combat` and
  `tabshow` from JiNengBiao with object2int. Level-0 rows hold formulas such
  as `x*4`, counted as 0 here (unverified for level 0, which no role holds).
- Golden: captured `[16, 0]` for fu0UR1-0-1-1 equals four level-1
  niumowang skills at combat 4 (`SkillFightTest`).
- Added `role_skill` to the migrator (`--users` scoped) and `Store`.
- Shenjiang slot [4] and the other gaps in this phase remain open.

## Phase 8 evidence log (all from `dntg_start.jar` via `tools/javap.py`)

- 30000: `BagEasyAction.getBagGoods` -> `BagServiceImpl.getBagGoods` ->
  `send2One('30000', Object[5])`: [goodsMapsOrNull (slots 1..150 via
  `StoreSlotFilter`, each `StoreGoodsOutput.formart`), bagLockVoOrNull,
  bagMaxSlot, storageLockVoOrNull, storageMaxSlot]. Lock VOs are
  [configNum, nowMs + remainingMs] or null at max capacity; remaining is
  openTime*1000 minus grown time (now - max(onlineTime, updateSlotTime);
  online time untracked here = Java's null branch), clamped at 0.
- `formart` Map keys mirror the 18 formart1 slots ('0' goodsId .. '17'
  jingyan exp); only the row's category branch parses attributes (equip
  20, skillbook 100, jingyanyu 108, shenqi 107 from `GoodsCategoryUtil`).
- Config: `goods.jat` (outer list holds the 1811-row list; category per
  goods id), `KaiGeFeiYongBiao.jat` (slottype B/C rows keyed by id; max
  B 144 / C 200; init 34/30 proven by untouched live `role_bag_state`
  rows). Missing state rows fall back to the init counts (documented).
- Live oracle: role fu0UR1-0-1-1 carries 36 bag rows + state 144/31
  (migrated under `--users` scope); real rows seed `test_bag.py`
  (consumable map exact, skillbook exp 0, gear qianghua cells, envelope
  `[goods, None, 144, [32, ~now], 200]`, fresh-role `[35, ~now]`/`[31,
  ~now]`). Exp/lucky attribute keys are unverified (no legacy row
  exercises them) and default to 0.
- Migration: `role_bag_slot` (slot rows incl. bag id/count/bind/expire)
  + `role_bag_state` (capacities + slot timers) join the `--users` scope.
- 30002: `getStorageGoods` -> Object[3] [goodsMapsOrNull (slots 301..500),
  storageLockVoOrNull, storageMaxSlot]; same row maps and lock-VO rules.
  Golden-tested in `test_bag.py` (slot-range filter, null-goods envelope).
- 30004: `moveGoodses` -> [0, code] (430206 invalid, 430202 locked) or
  [1, moveVo, moveVo] (`formatMove` [bagId, slot, count, bind]). Zones from
  `BagUtil` (bag 1..150, storage 301..500, zuoqi -104..-101, xunbao
  1001..2000); same-slot moves are silent; stacking merges up to
  `maxstack` (full merge deletes the source, still reported at count 0).
  Mount-gear slots answer 430206 (subsystem unmigrated, logged). Ten
  golden tests in `test_bag.py` (BagMoveTest: move/swap/merge/partial/
  silent/invalid/locked/cross-zone).
- 30100: `splitGoods` decrements the source, inserts the split row (fresh
  row id, like Java's IdGen 'bag'), pushes 30104 [[[rowId, rest]]] then
  30105 [formartMap], and the 30100 reply itself is null. The two slot
  args must be equal (checkSplitGoods, traced literally) and name the
  target; guards and codes 430201/430206/430205/430204/430202. Auto-use
  goods only queue an internal stage message in Java, logged and skipped
  here (no stage bus).
- 30102: `deleteBagGoods` -> [1, [rowId]] (missing rows reply [1, []];
  no bind check in the delete action, matching Java). Five golden tests
  (BagSplitDeleteTest). 30101 has no client action (service-internal
  discard path) and 30301 needs the prop system; both stay open.
- 30001/30003/30006: `clearUp`/`clearUpStorage`/`clearUpXunBaoBag` ->
  formart-map list (empty zone replies null; one row just moves to the
  zone base 1/301/1001). `BagClearUpUtil.pickup` groups by sort group
  (always 0: the jar never sets sortNum), sorts each group by goods id
  (`String.compareTo`), merges stackable rows (`move = min(source,
  maxstack - target)`, taken literally including the zero-maxstack
  case), drops zero-count rows, then bubble passes bind (bound first,
  then count desc across binds) / expire asc / count desc. Survivors
  are renumbered from the base in one rewrite (row ids kept; dropped
  rows vanish). Null bind/expire read as 0 and unknown goods go silent
  (Java would throw instead); the inner 30000 refresh is skipped (no
  bus). Eleven golden tests (BagClearUpTest).
- 30101: `discardBagGoods` -> `discardGoods`: C> [bagRowId, slotArg]
  (slot validated, unused); missing rows are silent, bound rows queue
  30101 [0, 430218] (null bind proceeds, matching the ifnull branch),
  success removes the row and queues 30102 [1, [rowId]]. The stage
  message (S:DISCARD_GOODS) and BagDropGoodsEvent have no bus here
  (logged, skipped). Five golden tests in `test_bag.py`.
- 30005: `getXunBao` -> bare formart-map list or null (slots 1001..2000,
  no lock VOs). Golden-tested.
- 30201/30202: `activationSlot`/`activationSlotStorage` take a slot count
  (non-Integer or <= 0 is silent). Over max -> [0, 430207]; short copper
  [0, 430208] (no YXB-cost kaige slot exists, so that branch is ported
  but unreachable), short lingshi/bind [0, 430209]. Costs come from
  `getActivationSlotParam`: first slot prorated by grown time (float32
  ratio, min charge 1, free when fully grown), rest full costNum; money
  walks [BIND_YB, YB] with `accountTran` conversion (YB x5, bind ceil/5).
  Each deduct pushes 32010, slot exp pushes 12001 (kill-exp no-level-curve
  approximation), reply [1, nextLockVoOrNull] last; missing state rows
  materialize at the live-proven 34/30 init. Fifteen golden tests.
- 30203/30204: `bagSlotGrowUp`/`storageSlotChengZhang` take no args:
  past max [0, 0, -1], still growing [-1, nowMs], grown unlocks free
  (same reply/exp shape as activation). Golden-tested incl. storage.
- 30302: `selGoods` C> [bagRowId, targetRoleId] -> [1, formartMap], or
  [0, 430251] for a missing row (booth preview is unmigrated, so missing
  always reports GOODS_NOT); unresolvable targets are silent (Java's
  not-online branch; only own roles resolve here). Golden-tested.
- 30301: `PropStageAction.consumeGoods` (C> bag-guid string, empty
  silent; non-null `useProp` results flush as 30301) + `useProp`
  (loadGoodsByGuid, skill-keyed handler cache, `userProp`
  tableswitch) + `PropType` pipeline (useCheck/addToCheck,
  consumePrior default true, decrGoodsesById, `GetPropOutPut`
  getError [0, code] / getStuData [1, guid], result '100017' ->
  silent). Dispatch map traced (30 skills; def branch returns null
  so unknown skills are silent). useCheck gates ported: consume
  categories {14,40,11,13,16,15,17,80} (isConsumeProp) -> 100002,
  levelReq -> 100003, job ('0'/'' open) -> 100004.
- Handlers ported (4): ExpType/skill-2 (incrExp(addExp*1), persist +
  12001 like kills; exppill_0001 +50000 golden), ZhenQiType/skill-5
  (incrZhenqi, persist, no direct push; zhenqipill_0001 +2500
  golden), YxbType/skill-14 (account incr(addGold, YXB->tongqian)
  + 32010; all five skill-14 rows have empty addgold so Java incrs
  0 — golden asserts the 0, the consume, and both pushes),
  HpMpPropType/skill-1 (consumePrior false; 1500ms hpcd gate, second
  use silent via the 100017 path; the heal itself is a stage-side
  prop buff (hpadd001 -> yushui_001) so no HP is touched here).
  Events (UseProp/UseMoneyProp) have no bus: logged, skipped. The
  other 26 handlers (LiHe, skillBook, AttributeDan, vip, chests,
  mounts, ...) stay open with the dispatch map as the work list.
- 30104/30105 are server pushes from splitGoods (no inbound route
  can exist): now named constants (`CMD_BAG_SPLIT_COUNT/NEW`) used
  by `bag_split`, shapes golden-tested; the ledger honestly keeps
  them not-started by design (it counts `cmd_num` routes).
- skillBook/skill-37 (traced end to end): `useSkillBook` (null row ->
  false; `autoStudySkill2` over `jhzqjn`, false -> 100008) + its
  internal decr (hence consumePrior null: the pipeline never
  consumes). `autoStudySkill2` learns into role_skill iff unlearned
  (else 42004 STUDY_SKILL 420007), level-1 info exists (else silent
  false), role >= levelNeed (else 42004 STUDY_LEVELNO 420008),
  needJob '0'/equal (else 42004 STUDY_JOBNO 420009); info level >
  role returns true without inserting (literal port, unreachable
  with real rows since need==level==1). Success consumes the book
  and pushes 42004 [category, 1] (`autoStudySkillWithNotify`) then
  30301 [1, guid]; failures push 42004 [0, code] then 30301
  [0, 100008], book intact. New `Store.save_role_skill` +
  `GameConfig.skill_info(category, level)`; five goldens (learn at
  job-'' level-100 role, repeat, level/job gates, unknown info).
  All real skill-37 books need job '' which no jobed role passes,
  so the learn golden uses Java-literal empty-equality (flagged).
  AttributeDan stays open (`eatShuxinDan` needs dan-cap config +
  85010 shape work).
- AttributeDan/skill-36 (traced end to end): `eatShuxinDan` over
  shuxingdan.jat (dan id == goods id) with the ZhuJueShuXingBiao
  per-dan cap column at the role's level (14 dan ids hardcoded in
  `ZhujueAttributeExportServiceImpl`, caps are row cells, e.g. 50
  at 56). Insert path (empty buffs) or update path (existing +
  useCount, ERROR_85001=851003 when already at cap, over-fit
  clamps the decr to what fits); the bag decr runs inside AND the
  pipeline pre-decr runs too (consumePrior default true), so one
  use consumes 2 — ported literally and pinned by goldens. Pushes
  85010 [attributeId, newTotal] then 30301 [1, guid]; cap-hit
  pushes only 30301 [0, 851003] with the pre-decr kept. New
  `GameConfig.dan_buff`; three goldens (first eat, capped,
  partial-fit to exactly 50). The clamp branch is unreachable
  with useCount 1 (noted, like the skillBook skip).

## Phase 8b evidence log (30301 prop-use, all from `dntg_start.jar`)

- Covered above in the Phase 8 entry (consumeGoods/useProp/pipeline
  + Exp/Yxb/ZhenQi/HpMp-gate). Seven golden tests in `test_bag.py`
  (`PropUseTest`: exp persist+12001+consume, zhenqi persist+consume,
  copper-0 +32010+consume, hpcd gate+consume, silent paths, 100003
  level gate with row intact, push-id constants, 5 skillBook goldens
  plus 3 dan goldens). Server-v1 323/323, tools 39/39. Ledger:
  30301 golden-tested (40 total), 838 open.

## Phase 8c evidence log (equip enhance 34000/34003/34009)

- `EquipAction` is pure delegation; `RoleEquipSlotServiceImpl.qiangHuaEquip`
  loads role + slot (null slot is silent), builds `GoodsEquipVo` over the
  attributes blob, and reads `ZhuangBeiQiangHua.jat` at (goodsId, qhcount)
  via `loadQianghuaConfig`. Gates in order: qhcount >= maxQhLevel ->
  [0, 31009], !permitqh -> [0, 31010] (unreachable: no real row pairs
  permitqh 0 with headroom, so it is white-box-pinned), short YXB(qhJb)
  -> [0, 31011], missing cost goods -> [0, 31012], short gold YB ->
  [0, 1002]. Costs burn before the roll; the fail branch still steps
  qhcount +1 (literal quirk, golden-pinned) with a dark star.
- Roll is `Lottery.roll(odds, TENTHOUSAND)`: `rand10000 <= int(odds*10000)`
  with odds = qhodds + glodN rate when the C> slot param is set; the gold
  extra `(int)(1/cost)` is 0 on every real row (literal quirk, pinned).
  qhlv0 rows carry odds 1.00, so first-enhance success is deterministic.
- Replies: 34000 [1|-1, equipId]; 34003 [1, equipId] after charm + qingxiyb
  with qhcount/stars zeroed ([0, 31001] unknown slot, [0, 31012] short YB
  without charm); 34009 [1] stepping +1 (qhcount 11 -> [0, 31034],
  300000 short -> [0, 31011], no jinglianshi -> [0, 1005]) with 11101
  [31035, [roleName, goodsName, '+MAX' at 11]]. Success + qhNotice pushes
  11101 [31015, [roleName, 0, newQh]]; every mutation pushes 30106
  [formart-as-map] before its reply. Slots are addressed by slot-number
  string (Java slot ids have no migrated column). Ten goldens in
  `tests/test_equip.py`. Server-v1 338/338, tools 39/39. Ledger: 34000 /
  34003 / 34009 golden-tested (43 total), 835 open.
- Known gaps: C> flag-true mall auto-buy (materials must be in the bag),
  the 34009 bag-mirror updateGoods (no guid linkage), event publishes
  (no bus).

## Phase 8d evidence log (equip jinjie 34001)

- `jinJieEquip` gates: unknown slot silent; !permitjj or missing target
  goods -> [0, 31013]; role level below target levelreq -> [0, 1000]
  (= LEVEL_NOT_ENOUGH); short YXB(jjcostcoin) -> [0, 31011]; missing
  materials -> [0, 31012]. Costs burn before the pity roll: fails below
  min fail outright, fails at/above max always succeed, else
  Lottery.roll(jjodds) (same port as enhance).
- Success swaps goodsId/itemLevel/qhcount to the target row
  (itemLevel/name/levelreq from the goods table), zeroes the fail count,
  pushes 11101 [31016, [roleName, oldName, newName]] + 30106 [formart],
  replies [1, id]; fail bumps jjfailcount, pushes only 30106, replies
  [-1, id]. Seven goldens in `tests/test_equip.py` (`EquipJinjieTest`:
  deterministic zj0011->zj0201 swap, pity fail/success, mid-pity roll
  proved by a rigged roll, all gates without consume, silent slot, id
  consts). Server-v1 353/353, tools 39/39. Ledger: 34001
  golden-tested (44 total), 834 open.

## Phase 8e evidence log (equip jianding 34004/34005/34006)

- `jianDing` gates in order: unknown gear/material -> [0, 31001]; gear
  without the jianding flag -> [0, 31027]; category-20 material without
  jdcailiao -> [0, 31028]; material itemLevel mismatch -> [0, 31020];
  lotteryKey -1 (pair capped) -> [0, 31021]; vip AND role level both
  short -> [0, 31016] (either passing clears the combined gate);
  equip material with xingxingLv short -> [0, 31017]; short YXB ->
  [0, 1003] (= JB_NOT_ENOUGH). Costs burn first: YXB plus one
  material (count-decrement for category-90 stones, whole-row removal
  otherwise).
- lotteryKey resolves pair args 1/2/3 to slots (1,2)/(3,4)/(5,6): an
  untouched pair opens its first slot, a half-filled pair fills the
  empty half, a full pair below cap lotteries evenly, a capped pair is
  -1. Empty slots roll the winner uniformly (getJianDingfuJiaId builds
  {id: 1.0}); filled slots keep theirs. Category-90 stones force
  success, else isSuccess (fresh-Random nextFloat under the rate) on
  the (winner, fuJiaLevel) row at the gear's rare level. Success rolls
  a weighted count capped at the rare max (empty slots open at the
  rare minimum), bumps the pool count, pushes 30106 [formart], replies
  [1, guid, slot, keyId, keyCount, rolled, 0]. Failure banks
  addexp0*roleLevel+addexp1 into the pool (capped at the role's jdexp)
  and the role with a 12001 push, replies [1, guid, slot, 0, 0, 0,
  added]. Bound stones bind bag-living gear only (role_equip has no
  bind column).
- `jianDingClear` answers [0, 31001] on unknown gear, consumes the
  charm map when covered else BIND_YB/YB gold ([0, 31015] when short),
  removes the affix, pushes 30106, replies [1, guid, slot].
  `getJianDingExp` answers [0] with no pool, resets a stale-day pool,
  replies [exp, hechengCount]. Sixteen goldens in `tests/test_equip.py`
  (`EquipJiandingTest`: all gates without consume, empty-half opening,
  capped count add, exp-bank failure, charm clear, gold-short, exp
  read, id consts). Server-v1 369/369, tools 39/39. Ledger: 34004/
  34005/34006 golden-tested (47 total), 831 open. role_jianding stays
  local-only (no legacy counterpart in the migrator scope, same as the
  role_settings precedent).

## Phase 8f evidence log (equip hecheng 34007/34008)

- `heCheng` fuses 4 material guids into the next-tier scroll (data:
  40->50 up to 100->120). Gates in order: vip hechengci cap reached
  -> [0, 31026] (999 at every vip level, effectively uncapped); arg
  count != 4 -> [0, 31022]; unknown material -> [0, 31001]; equip
  material without jdcailiao -> [0, 31029, name]; stone material under
  a non-juanzhou row -> [0, 31025]; non-cailiao material -> [0, 31024];
  itemLevel mismatch -> [0, 31023]; short synthesis stones -> [0, 1005]
  (= GOODS_NOT_ENOUGH); no bag room -> [0, 1006]
  (= BAG_SLOT_NOT_ENOUGH). Stones burn via decrGoodses (empty in
  data), the 4 materials burn (count-decrement for category-90
  stones, whole-row removal otherwise), the pool hecheng count bumps
  (null initializes to 0) with fresh hecheng_time, every reward lands
  with the any-material-bound flag, reply [1]. Deterministic: no
  lottery anywhere. `gethehengCount` answers [0] with no pool, else
  [hechengCount] with null passthrough. Eleven goldens in
  `tests/test_equip.py` (`EquipHechengTest`: arg count, unknown
  material, named-flag rejection, kind, level match, vip cap, full
  fuse with count+time, bind propagation, full-bag block, count
  read, id consts; the 31025 and stone-short branches have no data
  rows and ride as dead-but-ported). Server-v1 380/380, tools 39/39.
  Ledger: 34007/34008 golden-tested (49 total), 829 open. New
  `role_jianding.hecheng_time` column mirrors the entity field.

## Phase 8g evidence log (vip gifts + kaifu 62001/62002/62004/62020/62021/62022)

- `getVipDay/getVipWeek`: no row silent; vip 0 -> [0, 621002];
  claimed state (2) -> [0, 621001]/[0, 621003]; the level daybag /
  weekbag grants (short room [0, 1006]), state arms to 2 with fresh
  time, reply [1]. `getVipTeJia(level)`: above-level -> [0, 621004],
  claimed -> [0, 621005], job-filtered libaoid (empty at every level
  in data), YB specialprice (0 everywhere; [0, 1002] when short),
  reply [1, level]. Day/week staleness mirrors clearTimes (state
  re-arms to 1; the prop arm stays login-only); new role_vip
  day_time/week_time columns feed it.
- `getKaiFuInfo`: kaifu row ensured empty (roleLogin equivalent),
  reply [1, lotterReward, [[id, mark], ...]]. `lotterReward`: below
  the choujiang vip floor (1) -> [0, 1011]; outside kaifu days 4-6
  (vipchoujiang time) -> [0, 621012]; count formula
  (span==used -> 0 else days-lo+1-used) at 0 -> [0, 621013]; weighted
  prize over all rows grants, bumps use, replies
  [1, prizeId, [[goodsId, count]], [], []]. `lingQuReward(id)`:
  claimed -> [0, 621010], floor -> [0, 1011], off-days -> [0, 621012],
  date mismatch (viplingjiang date vs kaifu day) -> [0, 621011], room
  -> [0, 1006]; grants, marks, replies [1, id, 1]. kaifuDays counts
  calendar days since the session server start. Approximations: the
  lottery reply tails (no grant-delta infra), putInBag1-as-bag, the
  vacuous job filter, dropped expire-hours. New local-only
  role_vip_kaifu table. Eighteen goldens in `tests/test_vip.py`.
  Server-v1 398/398, tools 39/39. Ledger: vip six golden-tested
  (55 total), 823 open.

## Phase 8h evidence log (skill 42000/42003 + skillbook 99000/99001/99002)

- `getSkill` answers [[category, level]] per role_skill row ([] when
  empty). `upgradeSkill` gates in order: unknown skill [0, 420005],
  level 100 [0, 420010], skill at/above role level [0, 420006],
  bianshenneed rank [0, 420012], config levelneed [0, 1000]
  (unreachable in live data: levelneed never exceeds its level),
  zhenqi [0, 1001], YXB [0, 1003]; costs burn before the learnodds
  roll (same Lottery.roll port as enhance), success [1, cat, level],
  fail [-1], missing JiNengBiao row silent (Java throws). 42004 has no
  inbound route in SkillModuleInit (server push only, already emitted
  by prop-use) and stays ledger push-only like 30104/30105.
- `getSkillBookInfo` answers the formart1 worn-book list ([] when
  empty). `moveSkillBook` routes by band: bag->worn peidai, worn->bag
  xieZai, worn->worn move, bag->bag tunshi, else [0, 99000]. peidai:
  unknown book silent-null, wrong band [0, 99003], locked slot
  [0, 99004] (zuoqi mutex1..6 cells; qizhan/guanyi bands stay locked,
  their tables unmigrated), rank gates [0, 99005]/[0, 99006]/[0, 99011]
  (latter two always fire: levels read as 0), only-dupe [0, 99007],
  else wear-or-swap replying [1, [slot, formart], null]. xieZai needs
  the worn row and an empty 1..150 bag slot, replies
  [1, [slot, null], null]. move slides within a band (both rows read
  before either write, like the bytecode) replying
  [1, [to, formart], [from-or-null]]. tunshi needs both books
  category-100 with exp merge (food+eater+eater jcexp) through the
  (ridetype, rare, level+1) ladder, 30106 push, reply
  [1, [foodSlot, formart], [eaterSlot, null]]. `yjTunshi` validates
  the whole food list first (eater-side zhuangbei/level gates, unlike
  tunshi's food-side ones), feeds in order with bind inheritance,
  stops early at level 10, pushes 30106 once, replies
  [1, [eaterSlot, formart]]. New role_skillbook_slot table (migrator
  --users scoped) + jinengshubiao lookups. Thirty-six goldens in
  `tests/test_skill.py` (real JiNengBiao/jinengshubiao/ZuoJiBiao rows;
  synthetic table for the dead levelneed branch, white-box roll patch
  for the fail branch). Server-v1 434/434, tools 39/39. Ledger: five
  golden-tested (60 total), 818 open.

## Phase 8i evidence log (vip huodong 88000/88001/88002)

- `getVipHuoDongData` answers the claimed fixed tiers plus the drawn
  lottery tiers from every role_vip_huodong row ([lingqu, choujiang]).
  `getVipHuoDongJiangLi`/`getVipHuoDongChouJiang` take the vip tier
  (Java parses data[0].toString, so bare ints work) and gate in
  order: already claimed/drawn [0, 621008]/[0, 621009], below the
  tier floor [0, 1011], missing kaifuchoujiang row silent (Java
  null), outside the kaifu window [0, 621007], empty bisong silent,
  short room [0, 1006]. The bisong/jiangpin parcels grant through
  the bag pipeline, a missing row inserts (0, 0) first, the mark sets,
  and the replies are [1, tier] / [1, tier, prizeIndex] (odds roll is
  the same weighted-key port as the kaifu lottery). Events need a
  bus. 62003/62006 have no inbound route in any ModuleInit jar-wide
  (VipCommands push names VIP_CHANGE/VIP_PROP; upgradeVipLevel fires
  from VipRechargeEventHandler, addPropValue from the prop pipeline)
  and 62005 is a stage push (vipChange): all three stay ledger
  push-only. New get_role_vip_huodong_all accessor on the existing
  role_vip_huodong table (no migration change, on-demand policy).
  Fifteen goldens in `tests/test_vip.py` (real kaifuchoujiang rows
  prove the dead-window 621007 gate; synthetic table for success,
  full-bag, and mark paths; white-box roll patch for the draw).
  Server-v1 447/447, tools 39/39. Ledger: three golden-tested
  (63 total), 815 open.

## Phase 8j evidence log (setting 13001/13002/13003/13004)

- `changeQuickbar` takes [slotInt, skillStr] and sends nothing back:
  a missing row (or blank bar) starts [''] * (slot + 1), a short bar
  grows with '' padding, the slot takes the skill, and the bar
  re-joins with ',' (arrayToString; null/'null' cells read back empty
  but only '' or skill strings are ever written). Negative slots and
  mistyped cells are silent (Java throws before persisting).
  `savePanel`/`saveUiInfo`/`saveGuajiInfo` take a raw byte[] C> and
  upsert one blob column each (cacheInsert-or-update). New
  save_role_settings Session callback plus server wiring; the
  role_settings table already existed. Six goldens in
  `tests/test_protocol.py` (fresh/overwrite/grow/bad-slot,
  blob round-trip through the 13000 reply, mistyped silence, id map).
  Server-v1 453/453, tools 39/39. Ledger: four golden-tested
  (67 total), 811 open.

## Phase 8k evidence log (equip dress 31001)

- `dressEquip` takes [equipId, fromSlot, toSlot]: bag->worn wears
  (peiDaiEquip), worn->bag takes off (unLoadEquip), any other band
  pairing stays silent. Worn band is (-105, 0) with slot = -eqpart;
  bag band is [1, 150] (EquipSlotUtils). Wear gates (checkEquip) in
  order: empty bag slot [0, 31001], id mismatch [0, 31002], missing
  goods row [0, 31004] (config gaps stay silent past this, Java NPEs),
  non-equip category [0, 31005], job mismatch [0, 31014], slot
  mismatch [0, 31006], zuoqi rank [0, 31036] (2-elem form) for
  eqpart 101-104 else role level [0, 31007], sex [0, 31008]; the
  yuanshen gate cannot fire (no goods cell, like Java's int-default
  skip). Equip-locked gear binds on wear. Occupied worn slots swap
  (old gear lands back in the freed bag slot); empty slots reply
  [None, newMove]. Unwear needs the worn row [0, 31002], bag room
  [0, 31003] and an empty target [0, 31002], replying the move pair
  with xingxingLv 0. Replies are [1, info, xingxingLv] over
  formatMove [id, slot, count, bind] pairs. Worn ids read as goods
  ids and worn bind as 0, like the 31000 record; events need a bus.
  Sixteen goldens in `tests/test_equip.py` (real goods rows for every
  gate: zj0013 job, zj0601 level, zqzb0101 zuoqi rank; the sex gate is
  unreachable in live data). Server-v1 469/469, tools 39/39. Ledger:
  one golden-tested (68 total), 810 open.

## Conventions

- New tables follow the role_equip/role_attr_buff/role_vip pattern: minimal
  legacy columns, `save_`/`get_` on `Store`, migrator copies scoped by
  `--users`, mock-tested in `tools/tests`, golden-tested in `Server-v1/tests`.
- Session callbacks default to empty (no-data-safe) so unmigrated roles work.
- Known approximations live in code docstrings: `getFight` HashMap order
  (bounded truncation drift; int-exact maps unaffected), mall page order.

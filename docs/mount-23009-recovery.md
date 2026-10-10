# Mount frame `23009` recovery and port (bytecode, 2026-10-09)

Status: **ported**. The wire layout was recovered from `dntg_start.jar`, all
five blockers below were resolved from bytecode/config, and the frame is now
emitted by `Server-v1/game/protocol.py` (`zuoqi_pet_frame`) in the captured
position of the world-entry sequence (tap line 9: after `23002`, before
`12004`). The replay harness scores it `DIFF (1)`: only field 12, the owner's
move speed, which shares the documented equipment-data gap of `12000` key
`7` (Java 616.0 vs Python 550.0 — no `props` gear is migrated). Field 0, the
pet id, is runtime data (`IdUtil.nextString`) and is listed in the replay's
`VOLATILE` paths; fields 1-11 and 13 match the capture.

Command `12102` (inbound mount info) is also answered now
(`Session.zuoqi_info`).

## Push path

`ZuoQiPet.enterStageHandle(IStage)` →
`StageMsgSender.send2One(ownerId, '23009', new Object[]{ getMsgData() })`.

Captured frame (`output/orig-stack/tap-decoded.txt` line 9):

```
S> 23009 [[['zuoqi_64_109', 1, 500.0, 500.0, 'fu0UR1-0-1-1', 's0.萬俊◆一刀', 43, 32, None, 0, 0, 30, 616.0, '0']]]
```

## Record layout — `ZuoQiPet.getMsgData()` (14 fields)

| i | Java source | captured | Python port |
|---|---|---|---|
| 0 | `getId()` = `IdUtil.nextString('zuoqi')` = `zuoqi_<threadId>_<counter>` | `zuoqi_64_109` | `zuoqi_<map>_<seq>` (runtime-unique; volatile in replay) |
| 1 | `rank` (`ZuoQiConfig.getRank()` = `int(stratum)`) | `1` | `id` from `zuoqi_info` |
| 2 | `fightAttribute.getCurHp()` | `500.0` | `hp`, clamped to `[0, maxHp]` (`AbsFightAttribute.setCurHp`) |
| 3 | `fightAttribute.getMaxHp()` | `500.0` | `meinvhp` of the (rank, petLevel) `ZuoJiBiao` row (`attribute2Map(meinvatt, meinvhp)` → `hitpoints`) |
| 4 | `owner.getId()` | `fu0UR1-0-1-1` | `_wire_id(role)` |
| 5 | `owner.getName()` | `s0.萬俊◆一刀` | role name |
| 6/7 | `getPosition()` = `getSurroundValidPoint(rolePos, false, BEING)` | `43, 32` | `GameConfig.surround_valid_point` |
| 8 | `buffManager.getBuffClientMsgs()` | `None` | `None` (fresh pet) |
| 9 | `stateManager.contains(DEAD) ? 1 : 0` | `0` | `0` |
| 10 | `owner.businessData.getSex()` | `0` | role sex |
| 11 | `petLevel` (`Pet.setLevel`) | `30` | `min(roleLevel, maxlv)` |
| 12 | `fightAttribute.getYiDongSuDu()` → delegates to the owner (`PetFightAttribute`) | `616.0` | `entry_attribute_map(...)['7']` = 550.0 (equipment gap) |
| 13 | `roleEquipData.getQizhanbinqiId()`; null → `'0'` | `'0'` | `'0'` (same default; no equipment migrated) |

## Emit condition (all blockers resolved)

`RoleEventManager.createZuoQiPetEnterStage` creates the pet (and only then
does `enterStageHandle` send `23009`) when, in bytecode order:

1. `!zuoQiBussinessData.isRideOrNot()` — `ifeq` jumps to the creation path
   when the flag is false, so **riding suppresses the pet** at entry
   (`rideOrNo: false` in `zuoqi_info`);
2. `pet == null` (no pet yet);
3. `curRank > 0` and `curHp > 0`;
4. `IZuoQiConfigExportService.loadByRank(curRank)` exists;
5. `stage.getSurroundValidPoint(role.position, false, BEING)` finds a point
   (else Java logs `pet cannt find valid point` and skips the pet).

Each miss skips the frame; nothing is invented.

## Pet level — resolved

`RoleFactory.create` → `RoleFactoryHelper.getZuoqiLevel(role, curRank)` =
clamp(role level, `minLevel`, `maxLevel`) where `ZuoQiConfig.minLevel` is
**never set anywhere in the jar** (only the setter exists) and `maxLevel`
comes from the `maxlv` column of the rank's first `ZuoJiBiao.jat` row.
`PetFactory._create` → `Pet.setLevel` stores it as `petLevel`. Captured
check: role level 56, rank 1 `maxlv` 30 → petLevel **30** (real table).

## Config table — resolved

`sys_config/ZuoJiBiao.jat` (AMF3 list, same decoder as the other `.jat`
tables), loaded by `ZuoQiConfigExportServiceImpl` (`configureName =
'ZuoJiBiao.jat'`). Rows carry `stratum` (string like `'001'`, coerced with
`object2int`; the config key is `String.valueOf(int)`), `ridelv`, `maxlv`,
`meinvhp`, `meinvatt`, … Every row is both a rank row and a level row of
its rank. Rank-1 goldens from the real file: `maxlv=30`, level-30 row
`meinvhp=500` / `meinvatt=100` — matching the captured `maxHp` 500.0.

## Pet position — resolved

`AoiStage.getSurroundValidPoint` iterates `PathNode.getSurrounds()` in
`OffConfigUtils` order; `MapExportServiceImpl` always sets
`PathFinderType.AExtend`, so the order is `AExtendOffs`:
`(-1,-1), (0,-1), (1,-1), (-1,0), (1,0), (-1,1), (0,1), (1,1)`.
A surround qualifies when the cell is walkable (its `PathNode` exists) and
not `BEING`-taken; elements take their cell up on stage add
(`AbsAoiStage.addHandle`). From the captured role position (44,33) the
first candidate is **(43,32)** = the captured pet position (walkable on map
5's `path.mm`, not a spawn cell). If every surround is taken Java
random-walks; the port returns the original point (the wrapper's own
fallback) and documents the difference.

## `role_stage.zuoqi_info` format (`RoleStageUtil.decodeZuoQiInfo`)

fastjson **JSON**; empty string returns immediately (defaults). Keys, from
bytecode: `id` (mount rank, `getIntValue`), `hp` (`getIntValue`),
`deadTime`, `useTime` (`obj2long`, `deadTime>0` is rewritten to now),
`rideOrNo` (`getBoolean`). No `level` key — the level is derived, see
above. Decode in Python: `game/protocol.py` `decode_zuoqi_info`.

## Inbound command `12102` — resolved

`StageInfoAction.zuoqiInfo`: `data = (String) msg.getData()` is passed to
`RoleOfflineAttributeService.getZuoqiInfo`, answered with
`StageMsgSender.send2One(roleId, '12102', arr)` where `arr` is
`StageOutputWrapper.outpuZuoqiInfo`'s **`Object[8]`**:

```
[mount(curRank), level(biz.getLevel()), skills(getSkillArrays),
 clothes, longhunCounts[1], longhunCounts[0], zhanli, skillBook]
```

`PropUtil.getLonglingLonghunCount(null)` returns `[0, 0]`, and
`getQizhanbinqiId()` returns `'0'` when unset. Skills/clothes/zhanli/
skillBook live in tables the migration does not carry
(`role_zuoqi_skill`, outfit/zhandouli computation); Java returns null/0
when those sources are empty, which is what the port emits.

## Remaining gaps (documented, not blocking)

1. Field 12 is the owner's live speed, so it carries the same missing
   equipment data as `12000` key `7` (see the parity audit).
2. The random-walk fallback when every surround is taken is not
   reproduced (the port returns the original point).
3. Spawn-cell occupancy is static (the spawn points), with no live
   monster movement — same limitation as the `23002` snapshot.
4. For a mounted role, `12102`'s skills/clothes/zhanli/skillBook would be
   non-default in Java if `role_zuoqi_skill` etc. had rows; no such data is
   migrated.

## Sources

- `tools/javap.py` disassembly of `reference/TonNgoKhong/server/dntg_start.jar`:
  `ZuoQiPet` (`getMsgData`, `enterStageHandle`, `leaveStageHandle` → `24009`),
  `PetFactory.createZuoQiPet`/`_create`, `PetFactoryHelper.replaceZuoqiLevelAttribute`,
  `RoleEventManager.createZuoQiPetEnterStage`, `RoleFactory`/`RoleFactoryHelper.getZuoqiLevel`,
  `ZuoQiConfigExportServiceImpl`, `RoleStageUtil.decodeZuoQiInfo`,
  `AoiStage.getSurroundValidPoint`, `PathInfoConfig.preprocess`,
  `OffConfigUtils` (`AExtendOffs`), `MapExportServiceImpl` (pathfinder type),
  `PathNodeCopy.isNotTakeup`, `AbsAoiStage.addHandle`,
  `AbsFightAttribute.setCurHp`, `RoleEquipData.getQizhanbinqiId`,
  `PropUtil.getLonglingLonghunCount`, `StageInfoAction.zuoqiInfo`,
  `StageOutputWrapper.outpuZuoqiInfo`,
  `RoleOfflineAttributeServiceImpl.parserZuoqiOfflineInfo`,
  `IdUtil`/`Id` (id format).
- `output/orig-stack/tap-decoded.txt` lines 9 (23009), 6-13 (entry order),
  30 (the pet moving as `zuoqi_64_109`).
- Real data: `sys_config/ZuoJiBiao.jat`, `map_config/5/path.mm`.

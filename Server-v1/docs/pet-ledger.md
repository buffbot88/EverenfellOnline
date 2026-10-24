# Pet porting ledger

Authoritative per-entry status for the Java `PetAction` surface.
Evidence: `dntg_start.jar` javap of `PetAction` (@EasyMapping),
`PetServiceImpl` (gate order, costs, pity rolls, reply shapes),
`PetonlineEvent`/`online`/`clearCount` (login seeding, daily resets),
`ChongWu(Biao|ShengJi|TuJian|ShouHu)BiaoConfigExportServiceImpl`
(loader contract), `PetErrorCode`, `PetZhanFaWrapper`
(`getShangZhanPetId` values), `PropServiceImpl$PetBaoBaoActivate`
(dead in this build), `IPetStageServiceImpl` (stage pet sync, heti),
`RolePet`/`RolePetZhenfa` entities + sqlmaps, and
`RoleFactoryHelper.replacePetAttribute` (PETBAOBAO bag).

Status words: complete+tested (handler-exercised), push-only (Java S2C
with no inbound handler, asserted in peer outboxes), genuine-Java-no-op.

## Bus action (client -> server)

| ID | Java method | Status | Notes |
| -- | ----------- | ------ | ----- |
| 136000 | getPetInfo | complete+tested | `[pets, [zhenfaId, upgradeExp, entries], chuzhanId, upgradeCount]`; runs `clearCount` first; null pets/entries on empty, silent with no formation row |
| 136001 | activatePet | complete+tested | rank-1 biao gates level (1000) then items (1005); owned answers `[0, 136000]`; success inserts lv/rank-1 row, answers `[1, petId]` |
| 136002 | upgradePet | complete+tested | maxlv cap `[0, 136001]`; needItem short `[0, 1005]`; exp add with a single level-up on overflow (exp reset, overflow discarded); zhenfa `upgradeExp = petUpgradeCount + 1` quirk kept; answers `[1, petId, lv, exp]` |
| 136003 | petJinJie | complete+tested | non-jinjie rank `[0, 136002]`; goods short `[0, 1005]`; pity `fail<min→F, fail>=max→T` else roll; success `rank = jieshu + 1` + notice `11101 [136009, [roleName, petName, jieshu+1]]`; failure accrues `randomInt(addmin, addmax)` and promotes past maxblessing; `[-1, petId, rank, rankExp]` / `[1, petId, rank, 0]` |
| 136004 | upgradeZhenFa | complete+tested | full jinjie node `[0, 136003]`; `maxlevel <= zhenfaId` `[0, 136011]`; goods short `[0, 1005]`; overflow re-levels (`id + 1`) unless a jinjie node; answers `[1, zhenfaId, upgradeExp]` |
| 136005 | upDownZhen | complete+tested | unknown pet `[0, 136005]`; deployed `[0, 136006]`; slot set/clear with the 136010 push; up pre-clear is dead in Java (Integer-vs-String key), so put wins directly |
| 136006 | chuZhan | complete+tested | unknown pet `[0, 136005]`; formation stripped first (one 136010 push per removed slot); re-call `[0, 136010]`; 136011 `[[old,2]]`/`[[new,1]]`/`[[old,2],[new,1]]`; recall skips the strip like Java; answers `[1]` |
| 136008 | chuanChen | complete+tested | data `[gainer, consumed]`; missing `[0, 136005]`; consumed at-or-above in both level and rank `[0, 136007]`; gainer takes level/rank/both exps (normalized without the +1s), consumed resets to lv/rank 1; answers `[1]` |
| 136009 | jinJieZhenFa | complete+tested | below the exp gate `[0, 136004]`; goods short `[0, 1005]`; pity ceiling is strict (`fail > maxtimes` forces success); success levels the zhenfa, stamps `jinjieData[newId] = 1`, answers `[1, zhenfaId]`; failure bumps the count, answers `[-1, zhenfaId]` |
| PET:LOGIN | online/clearCount | complete+tested | seeds the `zhenfa '1'` formation row on first login; a stale `petUpgradeTime` zeroes the upgrade count; each owned pet whose rank row is lucky-clearing and whose pity stamp is stale loses rankExp/fail |

There are no other inbound IDs: 136007 has no handler jar-wide
(dead route); 136010/136011 are server pushes (see below).

## Server pushes (server -> client, no client command)

| ID | Producer | Status | Notes |
| -- | -------- | ------ | ----- |
| 136010 | upZhen/_downZhen/chuZhan | push-only | `[[pos, petId]...]` in document order (`[]` when empty) |
| 136011 | chuZhan | push-only | `[[old, 2]]` / `[[new, 1]]` / `[[old, 2], [new, 1]]` |
| 11101 | petJinJie succ | push-only | `[136009, [roleName, petName, jieshu+1]]` ahead of the reply (Java world broadcast; the port rides the actor's outbox like every other 11101) |

## Formation attributes (combat effect)

`replacePetAttribute`'s PETBAOBAO bag rides `role_bags` into the 12000
map: deployed pets' shengji attribute bags summed and scaled by the
zhenfa's `zhenfaxiaoguo` factor, plus every fully-owned tujian row's
bag (`getTuJianIds`). A missing formation or shouhu row yields no bag
(Java NPEs on the load miss).

## Entity (`RolePet`/`RolePetZhenfa` -> `role_pet`/`role_pet_zhenfa`)

`role_pet`: pet_lv/pet_lv_exp/pet_rank/pet_rank_exp/pet_rank_fail/
pet_rank_update_time/create_time per role+pet (upsert keyed by the
pair, like `cacheUpdate`). `role_pet_zhenfa`: one row per role with
zhenfa_id/pet_chuzhan_id/upgrade_exp/jinjie_fail_count/jinjie_time/
jinjie_data/zhenfa_pet/pet_upgrade_count/pet_upgrade_time (full-row
overwrite on save).

## Config (genuine loader contract, fixture values are test-only)

`chongwubiao`: id/jieshu key `id-jieshu`; maxlv/jinjie/skillid split on
`:`/fuskillid/name/nengliangtiem/fushentime/fushenshuxing/
needthingsid/shengjieshuxing/maxtimes/mintims/odds/addmaxblessing/
addminblessing/notice/luckyclear/maxblessing/value1 (role-level gate)/
value2 (activation cost). `chongwushengjibiao`: key `id-level`;
thingid cost, needexp/exp, attribute bag, shanghai. `chongwutujianbiao`:
id key, chongwuid split on `;`, attribute bag. `chongwuzshouhubiao`:
Integer zhenfaId key; thingid/needthingsid costs, jinjie/odds/exp/
maxlevel/maxtimes/mintims/needexp/notice/zhenfaxiaoguo. The reference
tree does not ship these tables, so the suite writes small fixture
tables exercising the genuine loader contract (mirroring
test_marry.py).

## Python deliberate deviations and parity gaps (not parity-verified)

- Missing config rows stay silent (no frame) where Java NPEs; the
  loaders stay graceful (`{}` when the file is absent).
- Pet events (`PetActivateEvent`, `PetUpgradeEvent`, `PetJinJieEvent`,
  `PetChuanChenEvent`, `PetChuZhanEvent`, `PetShangZhanEvent`,
  `PetZhenFaUpgradeEvent`) ride no bus, like every other ported upgrade
  flow; no subscriber recon exists in this build.
- `pet_upgrade_count` is a dead counter live (nothing increments it;
  only the daily reset zeroes it), so the 136000 slot and the
  `upgradeExp = count + 1` write are stable at 1/0.
- 136012 stage heti (`petHeTi`: energy gate, fushen buff +
  `S:PET_HETI_END` schedule, `replacePetFuShenAttribute`), the stage
  battle-pet summon (`s:pet_chuzhan` -> `BaoBaoBussinessData`, pet
  auto-attack/teleport aside), and the `S:PET_UPGRADE_JINJIE` /
  `S:PET_REFRESH_ROLE_ATTRIBUTE` refreshes need the ChongWu tables plus
  stage business-data sync that has no ported counterpart; the in-stage
  pet fighter stays unported.
- `PetBaoBaoActivate` item activation is dead in this jar: no
  `userProp` switch case constructs it, and its `useDaoJu` passes a
  constant empty petId. Acquisition runs through 136001.
- No RolePetUpgrade quartz/scheduled job exists in this build; the
  daily resets live in `online()`/`clearCount` and are ported there.
- No recharge or monetized paths exist in the Java pet surface; every
  cost is ordinary bag goods.

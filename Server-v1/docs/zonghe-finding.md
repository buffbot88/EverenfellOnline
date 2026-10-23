# Zonghe remote-JSON finding (Huodong shared dependency)

Verdict: **authentic snapshot FOUND — nothing needs inventing.**
`MKO_Client/Assets/gameconfig/upload/gameanalyze/compositiveactivity/fu0`
is the genuine GM-pushed zonghe payload for server `fu0`, with an md5
sidecar. Prior ledger text claiming "no shipped snapshot exists" was
wrong about the client tree (it is true of `reference/`).

## 1. The artifact (verified by parsing, not by reading code)

- Path: `MKO_Client/Assets/gameconfig/upload/gameanalyze/`
  `compositiveactivity/fu0` (+ `fu0.md5`).
- Format: Java serialization `AC ED 00 05` + `TC_LONGSTRING` (`0x7C`)
  with 8-byte length `487661` == actual body length; body is UTF-8 JSON.
  13-byte header, then raw JSON — no other framing.
- Integrity: `296b282315fcabe2d6d289ab1758c76b` matches the `.md5`
  sidecar (`<hash>,upload/gameanalyze/compositiveactivity/fu0`).
- Shape: JSON object, **79 top-level categories, 574 activities, all
  activity ids unique** (no `HashMap` overwrite collisions in the
  parser). Dates: `starttime`/`endtime` epoch-ms span 2014-02-24 →
  2014-03-08. Only server `fu0` ships; no other server snapshot exists
  in the checkout.

## 2. Fetch path (structure verified, endpoint NOT re-verifiable here)

- Server entry: `AbsZongheHuodongRemoteRefreshAbleConfigureParser.`
  `configureDataResolve(byte[])` (see `hdzh.txt`, the javap of
  `ZongheHuodongConfigExportServiceImpl`, which extends it).
  `getConfigureName()` returns the server id
  (`XianlingConfigUtil.getServerId()`), i.e. one payload per server —
  consistent with the per-server `compositiveactivity/<serverId>` file.
- Failure semantics, straight from bytecode: null/empty string after
  `ConfigParserUtil.getObjectResource1` → **silent return, old data
  kept**; fastjson `parseObject` throw propagates (no catch in the
  method); a category whose `activitys` key is absent/null is
  **skipped, rest still loads**; after all categories,
  `HuodongInit.init()` runs.
- The HTTP URL / poll timer / version check reported from earlier
  game-jar work could NOT be re-verified this pass: the game classes
  are not in this checkout (`reference/` has only third-party libs;
  `config/easyexecutor/` is empty). The client mirror + md5 proves the
  distribution channel exists; do not cite a URL until the jar is
  dumped again.

## 3. Parse → cache → distribute (verified from `hdzh.txt`)

- Category keys (literal JSON, all 79 present, zero violations):
  `activitys, button, clienttype, id, kaifudays, pattern, pic,
  startday, tag, teamid, zhuti, zuoqitu`, plus optional explicit
  `starttime`/`endtime`. Top-level key format is
  `{batch}-{clienttype}-{teamid}` (e.g. `201400001-1-2`).
- Time: `TimeConfigParser.convertTimeNotNeedParseTime(wholeCategoryMap)`
  → `TimeConfigVo` → category `startTime`/`endTime`. 64 categories carry
  explicit `starttime`/`endtime`; **15 do not** (ct 1/5/9/10/21/30/32 —
  counted) and resolve kaifu-relative via `kaifudays`/`startday`.
- Per-category display: element 0 of `activitys` is re-parsed for
  `dataMap → {dicon→icon, dname→name, dtitle→title}`
  (`CompositiveActivityHelper.MAPKEY_AWARDMAP_D*`).
- Branch on `CompositiveActivityClientType.isFirstRechargeType`
  (intType == 21): `createFirstRechargeConfig` (ct 21, 16 acts) vs
  `createZongheHuodongConfigs` (everything else). Stored into
  `IConfigureExportService` as `ZongheHuodongCategoryConfigs` keyed by
  `String.valueOf(clientTypeInt)`, appended per category; each activity
  is ALSO added as an individual `ZongheHuodongConfig` entity keyed by
  its string `id`.
- Read API (all verified signatures): `getZongheHuodongCategoryConfig(`
  `ClientType)`, `...(ClientType, int id)`, `...All()`,
  `...AllNotTime()`, `getXiaoFeiHuoDongConfig()`,
  `checkHuodongIsValid(String[] ids)` (true if ANY listed activity's
  `timeIsExpiry(start,end)`), `timeIsExpiry` = `start<=now<=end &&
  start<=end`, `getSign()`/`getHuodongFile()`.

## 4. Activity schema (verified: 574/574 rows audited programmatically)

- Activity keys: `activity_id, id, order, needlevel, neddpayyb
  (sic — source typo for needpayyb), dailycount, totalcount, data`.
- `data` keys: `awards, con1, config?, dataicon, dataname, datatitle,
  functiontype, id`. `config` present in only 83/574 (discount-mall
  goods lists + first-recharge display/award config); absent elsewhere.
- `awards` (always a dict) union: `lijin, jb, zhenqi, shengwang, exp,
  fabao, fbeffect, des, name, icon, huodongico, zubaoid, zubaoxianshi,
  zubaobind, zubaotime, items, itemtj`. **Every fu0 award carries
  `lijin`** → the parser's `ChooseAwardsConfig` branch (award entries
  without `lijin`) is real code but DORMANT for this snapshot.
- Item (`items[]`) union: `itemid/itemcount/bind/itemlasttime/
  itemeffect/itemunsale?/itembyfinishtime/itemlosttime` →
  `ItemParamVo(id,count,bind,lasttime)` (+ `losttime`→`yyyy-MM-dd
  HH:mm:ss` variant, `byfinishtime` flag variant; `effect`/`unsale`
  ride in `addMesage` JSON). First-recharge award rows additionally
  carry `itemstrengthenlv, itemrarelevel, itemfjid` (exact consumption
  in `createFirstRechargeConfig` lines 330–575, partially mapped:
  `FIRST_RECHARGE_CONFIG_ACTIVITY_PIC/TITLE` + award keys + `CONFIG`).
- Discount-mall goods (`config[]`, ct 5): `itemid, itemname, pic, tag,
  displaypayyb, maxsell, maxbuy, buybind, opayyb, npayyb, opaylj,
  npaylj, lasttime` (+ `gifts[]` with `giftmap itemid/itemcount`).
  Parser branch fires only when `functionType == DISCOUNT_MALL`.

## 5. Routing tables (bytecode values, snapshot counts)

`CompositiveActivityFunctionType` (`hdfn.txt`): 0 BAOSHI_FIGHTRECORD,
1 FABAO_FIGHTRECORD, 2 ZHUANGBEI_FIGHTRECORD, 3 ZUOQI, 4 ROLE_FIGHT_
RECORD, 5 JINGJICHANG_RANK, 6 ROLE_LEVEL, 10 PER_RECHARGE, 11 ACCUMU-
LATE_RECHARGE, 12 ONCE_RECHARGE, 13 ACCUMULATE_COMSUME (sic), 14/15
FINAL_ACCUMULATE(_DAILY), 20 VIP_EXTRA, 21 VIP_MALL, 30 GOODS_EXCHANGE,
40 DISCOUNT_MALL, 50 ZUOQI_LEVEL, 51 BAOSHI_LEVEL, 60 MONSTER_WANTED,
70 FIRST_SKY_KING, 71 FIRST_SKY_MEMBER, 80 QIBING_RANK, 81 CHIBANG_RANK,
90 YB_RECHARGE_RANK, 91 YB_CONSUME_RANK, 92 YB_CONSUME, 93 GOODS_CHANGE,
94 FIRST_RECHARGE, 95 XIAOFEIFANLI, 100 YB_COMSUME.

`CompositiveActivityClientType` (`hdct.txt`, intType in parens): 1
RECHARGE, 3 YB_CONSUME, 4 VIP_EXTRA, 5 DISCOUNT_MALL, 6 MONSTER_WANTED,
7 FINAL, 8 VIP_MALL, 9 GOODS_CHANGE, 10 ZUOQI, 11–17 RANK1–RANK7, 19
YBRECHARGERANK, 20 YBCONSUMERANK, 21 FIRSTRECHARGE, 22 BAOSHI_LEVEL, 23
KING_MINE, 30 QIBING_RANK, 31 CHIBANG_RANK, 32 VIP_LEVEL, 34 XIAOFEI,
35 XIAOFEIFANLI. `isFirstRechargeType` ⇔ 21, `isXaoFeiType` ⇔ 34,
`isYbRankType` ⇔ 19/20; unknown ints hit the
`convert to CompositiveActivityClientType error for intType:` path.

Snapshot coverage (`clienttype → functiontype`, n activities):
1→{10:29, 11:93}, 5→{40:31}, 9→{93:245}, 10→{50:34}, 21→{100:16},
22→{51:25}, 30→{80:34}, 31→{81:21}, 32→{20:5}, 34→{91:36}, 36→{12:5}.

## 6. Anomalies that constrain the next implementation pass

- **clienttype 36 exists in the snapshot (5 ONCE_RECHARGE activities)
  but has NO enum value** (max is 35). `convert(36)` fails, so Java
  cannot serve those rows — any Python port must decide
  drop-with-log vs alias, and must not silently renumber.
- **15 categories lack explicit times** → kaifu-relative resolution is
  load-bearing, not an edge case; needs the server-kaifu source.
- **Absent from fu0** (families still blocked after this find):
  ct 3/4/6/7/8/11–17/19/20/23/35 and ft 0–7/13–15/60/70/71/90/92/94/95/
  100. `HuodongAction` methods naming those families (`getkingMine`,
  `getAccumulateComsume`, `getForeverRecharge`, `xiaoFeiFanli*`,
  VIP-mall/yb-consume/final variants) have NO data to run on.
- `con1` semantics are per-family (recharge thresholds `100…50000`;
  exchange/mall item ids) — the threshold lives in `con1`, NOT in a
  typed field; the port must preserve it as string.
- Per-command (70000/70001/70500/…) → method → category wiring is
  NOT recovered: `HuodongAction` methods (`getRechargeInfo,
  getAccumulateRecharge, getLimitedMall, getLimitedExchange,
  buyHuodongMallGoods, getHuodongReward, lingquRechargeReward,
  getQibingRank, getZuoqiRank, xiaoFeiRank, …`, see
  `actionmethods.txt`) prove family intent, but the inbound-ID→method
  routing table (easyexecutor wiring / module InCmd dispatch) is not
  in this checkout. Next step: dump it from the game jar.
- Rank families (94002–94005, 94100–94103) are NOT zonghe-driven
  (classpath `RankHuodongConfig` + paihang system) — unchanged.

## 7. What the Python port may now use (no invention required)

- Read `.../gameanalyze/compositiveactivity/<serverId>` at boot/GM-
  refresh, strip the 13-byte Java-serialization header, parse JSON.
- Drive eligibility/claims from `clienttype/functiontype/con1/awards/
  items/config` exactly as §3–§5; persist claims in `role_huodong`.
- Treat ct 36, missing-time categories, and absent families per §6 —
  all three are data facts, not guesses.

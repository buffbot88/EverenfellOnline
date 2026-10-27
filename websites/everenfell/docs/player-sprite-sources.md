# Player-sprite sources — res/ investigation (2026-10-27)

Question: where are the authentic in-world character sprites, and how does
the client address them? Method: inventory + table-driven tracing, no
name-guessing as proof.

## 1. res/f/ is NOT character animation (corrected)

379 files. Breakdown by stem:

- `anhei_00–99` (~117x125, 100 frames) + `anhei_100–128` (~84x90, 29
  frames): one monster set ("dark") in two resolution groups. Not a
  player class — no job linkage anywhere.
- `A/B/C/D.png` (79x112): class stills (select-screen scale, distinct
  from the 171x171 createUI portraits). `D1/D11001–D11010`, `A1/B1/C1`
  (80–100px): icon-scale pieces.
- Everything else is 30–80px UI: `ricon*` (49px role icons), `qizhi`
  (55px flags), `zqbb`/`meirentou` (30px), `huli`/`zixia`/`baiguyao`/
  `mogu`/`diao`/`gui`/`zhizhu` (60px NPC/monster heads), `7sicon*`
  (80px), `duorenFB*`/`qinglong*` (40px dungeon icons).

Nothing in res/f/ is a humanoid animation strip. Portraits/icons only.

## 2. tw/r/m/ are MAP tiles, not models (corrected)

`m/0/` holds 24 anim-groups × 17 frames of 256x256 JPEGs = 408 tiles =
Map 0's 17×24 tile grid, plus `map.json` (`MapModel`,
`mapwidth:4352`, name 凌霄殿外), `map.dat`, `monster.mm`, `path.mm`.
129 numeric dirs = 129 maps' tile stores. Do not mine these for sprites.

## 3. World sprites live in tw/r/n/*.pak (901 packs) — addressing proven

`GuaiWuBiao.jat` (209 monster templates) carries a `pak` column
(`tianbing-qiang`, `yao-langren`, `renlei-dadao`, … 21 distinct).
`NpcLieBiao.jat` (45 NPCs) carries `pak` + `face`
(e.g. N010001 孙悟空 → pak `1nanjiangxiumozhe`).
Spot-check: `1n_mengyouer.pak`, `1n_zhuangmen.pak`,
`1nanjiangxiumozhe.png` all exist on disk under the expected paths —
`pak` → `tw/r/n/<pak>.pak`, `face` → `res/f/` portrait.
Zixia validates the pattern end to end: N020001 紫霞仙子 (map 2) →
pak `npc-xiannv1`.

Only GuaiWuBiao and NpcLieBiao carry `pak` (full 246-table scan).
The server never reads it (gameplay only) — the Flash client resolves
it from its own copy of the same tables under `res/java/zhcn/`.

## 4. Class IDs recovered, job→pak mapping still missing

`ZhuJueShuXingBiao.jat` `learnskill`:
`sunwukong1;jiuweihu1;niumowang1;tieshangongzhu1` — the four class
skill lines (A 靈猴 / B 九尾 / C 牛魔 / D 羅刹=鐵扇公主).
No player table maps job → pak; the mapping is hardcoded in client
code (createRoleV2.swf, 796KB, encrypted on disk — see §5).

Name-similar packs exist but are UNVERIFIED and must not be wired by
name: `jiuweihu.pak` (230KB), `luosha.pak` (252KB),
`1yao-houzi.pak` (941KB), `niutou*.pak` (bull-head, likely monsters).

## 5. Blockers (explicit, not worked around)

- `.pak` contents use the same unknown packing as on-disk SWFs
  (`r`m.` header, high entropy — not zlib, not FWS/CWS). No unpacker
  exists; `tools/` has no pak tool.
- No runtime memory dump of createRoleV2/roleUI/chooseRole was ever
  captured (dumps cover only createUI, gameui, hud-chat,
  shared-controls). Without one, the authentic job→pak mapping and
  frame layout cannot be decoded.
- `.ani` animation descriptors (tw/r/ef|em|o) are packed the same way.

## 6. Proposed next decoder step (one class)

1. Capture a decrypted createRoleV2.swf from a live client session
   (same method that produced `output/swf-memory/mem-*.swf`), OR
   crack the pak/SWF packing once and apply it to both.
2. Until then: DO NOT substitute portraits, NPC packs, or anhei
   frames as the player sprite. The dark-silhouette stand-in stays,
   explicitly pending.

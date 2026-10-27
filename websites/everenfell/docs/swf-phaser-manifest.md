# SWF-to-Phaser component manifest — Phase A draft (HUD + player)

Source of truth: decoded display lists, not appearance.
- `scripts/asset_tools/audit_hud.py` → `output/hud-audit.json` (walks
  `output/swf-memory/mem-*.swf`, resolves SymbolClass, expands
  DefineSprite placements + EditText vars).
- `scripts/asset_tools/decode_create_ui.py` → create-ui layout (prior milestone).
- Reference target: `websites/everenfell/docs/inworld-hud-target.jpg` +
  `inworld-hud-target.md` (13-element inventory).

## 1. HUD modules (decoded)

Dump files (canonical):
- gameui: `output/swf-memory/mem-000010d40020-da6d57518e94.swf`
- hud-chat: `output/swf-memory/mem-000010dff020-61972ca56abd.swf`
- shared-controls: `output/swf-memory/mem-000006d52078-83c051d9be6e.swf`

### gameui — CONFIRMED structure, art unmapped to regions
- `ui.HeroBar` (cid 438, 1 frame): shape + `bar2` + `bar` (cids 433/435/437).
- `ui.HpBar` (cid 573): shape 572 + `bar` (437, shared with HeroBar).
- `ui.BloodShape` (cid 275): single shape 274 — likely orb/liquid mask.
- `ui.Gain`, `ui.ListMenu`, `ui.caijiBar`: small sprites, 2–6 placements each.
- `ui.panel.maiyao` (cid 450, shop dialog — matches target #8 購買藥品):
  shape 445 + 4 EditTexts (102,67 / 99,103 / 42,151 / 60,20) + `tg.shared.cm.ybutton`
  + `tg.shared.cm.CloseButton`. Golden frame art lives in gameui bitmaps 1–170.
- `ui.panel.NpcTalkPanel` (427), `ui.panel.TaskTalkPanel` (399),
  `ui.panel.fuhuoPanel` (658, 13 placements) — dialog family, deferred.
- `ui.auto.GuajiIcon` (613, 15 frames, 38 placements), `ui.auto.XunluIcon`
  (273, 15 frames, 37 placements) — autoplay icons (target #13, deferred).

Status: placements decoded in `output/hud-audit.json`. Bitmap→region mapping
(gameui images 1–170 to HUD regions 1/2/10/11) NOT yet done. Next: map
`assets/ui/gameui/images/*` to target regions via sprite containment, same
method as create-ui (SymbolClass containment + placement matrices).

### hud-chat — CONFIRMED structure, art unmapped
- `ui.StateBar` (cid 172, 4 placements) — top-left portrait/status (target #1).
- `ui.MiniMap` (cid 615, 16 placements) — target #4, deferred milestone.
- `ui.panel.TaskTrack` (124, 6 placements) + `ui.TaskTrackItemRender` (60) —
  target #5, quest protocol exists server-side (`task_*`, `test_task`).
- `ui.ChatCombox` (804) + `ui.ChatSkin` (781, 10 placements: shape 719,
  `textArea`, `tab0`→`ui.ChatTabNavi`, `plusBtn`/`subBtn`/`scaleBtn`/`bar`) +
  `ui.ChatTabNavi` (716, 4 frames) — target #9, chat protocol exists (`test_chat`).
- `ui.ZDLView` (1012: shape 1011 + `zdl` sprite 302) — combat-power banner
  (target #1, 戰鬥力 424). Data source unevaluated.
- `ui.panel.Target` (157: tf0/tf1/bar/label/btn_caozuo/closeBtn) — target select frame.
- `ui.Dazuo`, `ui.LoudSpeaker`, `ui.render.Statetip` — minor, deferred.

Status: same as gameui — structure decoded, bitmap→region mapping pending for
`assets/ui/hud-chat/images/*` (343 files).

### shared-controls — CONFIRMED generic kit
- `tg.shared.ui.StateBar` (133), `shared.ui.PanelBg` (252),
  `tg.shared.cm.Button` (534, 4 frames), `CloseButton` (462, 4 frames),
  `ScrollBar` (206), `ComboBox` (455), `TabNavi` (103, 4 frames), `ToolTipBg`.
- Used by maiyao (`ybutton`, `CloseButton`) and dialogs. No per-screen layout.

## 2. Player character — PARTIAL, animation pipeline unproven

Authoritative identity/data (live today):
- `world.enter` → `roles[]`: `{id, name, job (A/B/C/D), level}` + `homeServer`.
- `world.snapshot` → `{mapId, actors[]}`; self actor `{id, kind:'player', x, y,
  vitals:{hp,maxHp,mp,maxMp}}`; others via 23002/23003
  (`monster_actors`/`npc_actors` in `Server-v1/gateway.py:291`).
- Movement: `player.move` → 40000; pushes `actor.moved`. Camera follows tile pos.
- Current renderer: cyan placeholder rectangle + rune ellipse in `WorldScene`
  (`KIND_TINT`, `ActorNode` rectangles). MUST be replaced.

Art candidates (unmapped):
- `MKO_Client/Assets/res/f/A.png B.png C.png D.png (+A1/B1/C1/D1)` — class
  stills, sizes unknown (no PIL here). Likely select-screen or still frames,
  NOT proven world sprites.
- `anhei_00–124` (125 frames), `yd_*` (29), `huli_*` (4), `zixia_*` (4),
  `D11001–11010` (10) — candidate animation strips. No decoder linkage ties
  any strip to job A/B/C/D, idle/walk, or directions.
- `MPlayer.swf` (197 KB, CWS) is a shell with zero audio refs, not a sprite
  bundle (see character-audit §6). No DefineSound anywhere; SFX are external
  (`res/tw/r/s/`, 223 files, UI set vendored).
- createUI bitmaps hold portraits/ribbons only — no world sprites (audit §7.4).

Missing: direction frames, idle/walk timelines, anchor/ground offsets,
shadow/selection-circle art, equipment layers, job→strip mapping.
Next step (Phase B): pick ONE class (suggest B/九尾 — target screenshot shows
L7 Nine Tails + zixia NPC), prove idle+walk loop from one `res/f` strip or
locate the real character package, then extend to all four jobs without
changing gameplay rules.

## 3. What NOT to do
- No generic HUD + pasted PNGs. Bitmap→region mapping must come from sprite
  containment/placement matrices.
- No fake characters or portrait-as-sprite substitution.
- No invented combat power, resources, events, minimap, shop, autoplay.
  Unsupported = authentic chrome preserved, honestly documented.
- No full test suite or version bump without authorization.

## 4. Bitmap-leaf resolution (2026-10-27, `resolve_hud_bitmaps.py`)

Recursive walk of every placement to bitmap/edittext leaves with
accumulated offsets; full depth paths in `output/hud-bitmap-map.json`.
Bitmap IDs are per-dump character IDs (gameui vs hud-chat differ).

| Target | Bitmap leaves | EditTexts | Gaps |
|---|---|---|---|
| `ui.HeroBar` | none — vector-only shapes 433/434/436 | – | vector bar art, no PNG source |
| `ui.HpBar` | none — vector-only shapes 572/436 | – | same shared bar sprite as HeroBar |
| `ui.BloodShape` | none — vector-only shape 274 | – | orb/liquid mask is vector |
| `ui.panel.maiyao` | 444 (frame) | 446/447/448/449 | `tg.shared.cm.ybutton` + `CloseButton` imported (tg.swf host, encrypted) |
| `ui.StateBar` | 166 | 160/162/164/170 | CORRECTION: full dump shows moneyBar/goldBar/bindgoldBar/moneygold at x=0/78/156/232 — the **currency bar row**, not the portrait panel. Portrait cluster = `ui.panel.roleheadskin` (below) |
| `ui.MiniMap` | 522–611 (14) | 525/528/613 | 3 imported refs |
| `ui.panel.TaskTrack` | 64–112 (11) | 110/111 | vector shape 63 + 2 imports |
| `ui.ChatSkin` | 67–766 (14; 67/70/77/84/87 shared with TaskTrack) | 723/742/764/768 | 3 imported refs |
| `ui.ZDLView` | 300 + 1010 | – | none — first fully-mapped component |
| `ui.panel.Target` | 135/139/143/150 | 137/138/142 | 2 imports |

Consequences: HP/orb chrome (HeroBar/HpBar/BloodShape) has no bitmap
source — it must be redrawn as vector/shape work or recovered from a
flash-render capture, not from exported PNGs. ZDLView is the cheapest
first reconstruction (2 bitmaps, zero gaps). All `tg.shared.*` imports
resolve through the encrypted tg.swf loader context and stay undecoded.

## 5. Full-frame decoder pass (2026-10-28, `dump_hud_frames.py`)

`output/hud-frames.json` keeps the complete placement record per row:
flags, full matrix, instance name, class name, trailing bytes. Findings:

- **Portrait cluster found: `ui.panel.roleheadskin` (cid 313).**
  moneyBar-style row is StateBar; the actual top-left cluster is
  roleheadskin: shape 213 → bitmap 212 (361×131 frame), `czbtn` (儲值,
  214), `vipbtn` (221 + `viplevel` digit bitmaps 223/224/245),
  `qiangBtn` (253), event icon buttons + labels, `tf0/tf1` texts, `pk`,
  **`zdl` (reuses sprite 302 — the combat banner lives here)**,
  `buffBtn`. 15 bitmap leaves, 7 edittexts. The portrait photo is
  code-attached (createUI pattern), still to wire to role data.
- **Standalone ZDLView dropped from UIScene FOCUS** — already renders
  inside roleheadskin; drawing both double-draws the banner.
- **MiniMap toggle pairs**: `btn_playerOff`/`btn_player` and
  `btn_yinyueoff`/`btn_yinyue` share positions — visibility-toggled
  states. Phaser must render one and toggle when behavior lands.
- **No morph shapes in focus sprites, no DefineSound, no frame
  labels** — animation/masking is ActionScript-driven, outside SWFs.
  One ~identity scale in ChatSkin; no rotations. Full matrices are on
  record in `hud-frames.json`.
- Shared-controls kit decoded: Button/CloseButton (4 frames each),
  ScrollBar (decArraw/assArraw/track/thumb/barzs), ComboBox, TabNavi —
  `tg.shared.ui.StateBar` is also a currency bar, not a portrait panel.

## 6. Phase B progress (2026-10-28)

- `scripts/asset_tools/build_hud_layout.py` →
  `websites/everenfell/src/assets/hud-layout.json` (per-component art
  leaves with PNG paths, sizes, authored offsets).
- `src/game/scenes/UIScene.ts` renders from the layout: roleheadskin
  (15 art, top-left), StateBar currency row below it, Target,
  ChatSkin, TaskTrack, MiniMap. Intra-component positions are authored
  Flash-px; screen anchors stay documented approximations.
- HeroBar/HpBar/BloodShape stay unrendered (vector-only, zero art).
- Status (prior increment): implemented, typechecked + built on Alpha,
  awaiting visual verification (live screenshot vs reference still to
  run). Superseded by §7 pass (unverified: no node in this shell).

## 7. roleheadskin completion pass (2026-10-28, decoder evidence)

Full-frame + DefineEditText decode (`dump_hud_frames.py`,
`decode_create_ui.parse_edittext`) now binds every live text field:

| Field | SWF evidence | Phaser binding |
|---|---|---|
| tf0 name (cid 304) at (98,13.4) | SimSun 14px #bbae8e, centered, box 34x18, initial "100" | `role.name` from `world.enter` roles[] |
| tf1 level (cid 288) at (132,43) | SimSun 12px #c6b8a5, centered, box 110x18 | live role level, digits only (as authored) |
| qibing label (cid 278) at sprite-rel (-1,50) | SimSun 14px #cfc7aa, 騎戰/兵器 | "CAVALRY" (first English pass) |
| icon11 label (cid 262) at rel (0,41) | SimSun 12px #ffe9a6, 獅駝嶺 | "SHITUO RIDGE" |
| icon12 label (cid 282) at rel (1,41) | SimSun 12px #ffe9a6, 聖誕禮包 | "GIFT PACK" |
| buffBtn label (cid 307) at rel (18.1,5) | 14px #ffe687, 克己 | "RESTRAINT" 10px (box-fit, verify) |
| Target tf0 (137) at (80.5,7.9) | SimSun 14px #fed267, centered | target name (panel hidden without target) |
| Target tf1 (138) at (113,28) | SimSun 12px white | target level |
| Target label (142) at (102,53) | SimSun 12px #dbd3d0, empty initial | target detail |

More decoder facts recorded (not guessed):
- All roleheadskin rows are translate-only; button sprites carry
  4-frame (up/over/down/disabled) color-transform states on vector
  shapes; portraits/vip-digits/combat value are code-attached.
- Portrait circle (56,74) r34 is APPROXIMATE (emblem geometry from
  bitmap 212); class stills A:32/B:16/C:24/D:1 masked into it.
- Combat value unbound: JSON gateway has no 12010/ZhanDouLi push
  (value exists only in game-server AMF). Banner art renders, number
  omitted — documented gap, not a silent zero.
- VIP digits (viplevel sprite 247: 223/224/245) skipped: rank not
  gateway-exposed. Button chrome renders statically; behaviors need
  ActionScript + server features (non-interactive, documented).
- Baked-art Chinese DONE in Blender (`scripts/asset_tools/
  localize_hud_buttons.py` → `images-en/`): 214 TOP UP (Georgia Bold
  cream on preserved button), 253 STR (tight red-plate cover, icon
  intact), 300 POWER (from-scratch gold-gradient face + thin dark
  outline, transparent bg, 44x18). VIP letters already Latin. 300
  verified via large-size diagnostic render (vision-model misread of
  the 44px composite discounted after the 5-glyph proof).
- Anchors now use MEASURED leaf extents (roleheadskin 511x131,
  MiniMap 248x181, TaskTrack 318x619 w/ -74 offset, ChatSkin
  300x276 w/ -244 offset, Target 353x98); right/bottom components
  subtract true size so nothing clips past the viewport. roleheadskin
  (0,0) exact + Target-conditional rule are structural; other anchors
  stay approximations pending ActionScript positioning rules.
- `artPath` now uses full module-relative PNG paths: bitmap ids
  repeat across gameui/hud-chat dumps, basenames alone can collide.
- `client.enterWorld` passes `{playerName, playerLevel, job}` into
  `UI_KEY`; Target renders only when target data is provided.

Status: node 24 installed via wingate; `tsc --noEmit` clean and
`npm run build` clean (dist/index-*.js). In-client verification done
on local vite (Map 0 + UI scene via __evfClient hook):
- roleheadskin renders top-left with live name/level, circular
  portrait (build_portraits.py, transparency verified), TOP UP / STR
  / POWER / CAVALRY / SHITUO RIDGE / GIFT PACK / RESTRAINT all
  legible; no viewport clipping on any anchor; Target appears only
  with target data (verified both states).
- Phaser 4.2 WebGL rejects GeometryMask (setMask warning) — fixed by
  pre-compositing circular portraits in Blender, no runtime mask.
- 300-en needed a thin-outline + brighter-gradient second pass after
  a large-size diagnostic proved the 5-glyph render (the tiny-composite
  misread was discounted, not the asset).
- Remaining baked Chinese lives in other components' art (Target 操作
  button, TaskTrack 任務 headers, minimap 領取 clock, chat art) —
  queued for their per-component passes, not this one.
Pending: portrait circle pixel-fit vs emblem ring, narrow-name-box
behavior for long names, real-gateway data binding, Alpha deploy.

## 8. Phase B entry criteria
1. Map gameui/hud-chat bitmaps to target regions 1/2/10/11 (portrait, orbs,
   action bar, chat) via decoder pass.
2. Prove one-class idle/walk animation from source-grounded frames.
3. Then build coordinated entry: enter → snapshot → visible tiles + sprite +
   HUD shell → camera → input, with real error/retry states.

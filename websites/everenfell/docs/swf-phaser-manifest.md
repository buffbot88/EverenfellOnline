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
| `ui.StateBar` | 166 | 160/162/164/170 | 3× char-26484 imports (tg host) |
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

## 5. Phase B entry criteria
1. Map gameui/hud-chat bitmaps to target regions 1/2/10/11 (portrait, orbs,
   action bar, chat) via decoder pass.
2. Prove one-class idle/walk animation from source-grounded frames.
3. Then build coordinated entry: enter → snapshot → visible tiles + sprite +
   HUD shell → camera → input, with real error/retry states.

# Create/Select localization ledger — single structured pass

Rule: no temporary translations. Every asset touched in this pass ships its
final English version immediately. Screens lock when done; no second cleanup
pass. English strings need user approval first — see
[localization-glossary.md](localization-glossary.md). Nothing below invents
wording: unapproved English cells are empty.Workflow per screen: recover faithfully (done — see
[character-audit.md](character-audit.md)) → inventory text (this file) →
approve glossary → disposition per asset → export same-size PNGs over the
same filenames (layout JSON and scenes keep working untouched) →
screenshot verify → lock.

Status 2026-10-26: all 10 bitmaps rendered with DRAFT English by
`scripts/asset_tools/localize_create_ui.py` (originals safe in git;
55/57 untouched, state role unverified). Fixes since first render:
transparency restored (first pass flattened original alpha to opaque
black; outputs are RGBA again, verified corners alpha 0), ribbon 21's
baked 九 glyph erased, stamp/button ghosting removed via tighter ROIs.
Mottos revamped (not literal) and word-wrapped per column — English
lines run ~3x longer than the 7-glyph originals and overlapped without
wrapping. Screens verified (`?scene=create`, `?scene=select`).
Glossary rows 1–14 approved (C/D mottos refined); flavor text only, not
gameplay promises.

Originals preserved: `assets/ui/create-ui/images-zh/` holds all 24
committed-original PNGs alongside the localized `images/` set, for
comparison and future localization passes.

SELECTED stamp verdict: decoded depths put selectmc (depth 36) ABOVE
all class sprites (depths 2/9/16/23), and the ring renders at inner
depth 3 inside the selected class sprite — Phaser draws selectmc after
the ring, matching exactly. The overlap is original behavior (depth
order, no masks involved), not a layering bug. No nudge.

Functional verification 2026-10-26 (dev-only `__evfGame`/`__evfClient`
hooks): synthetic pointer click on portrait B → `createJob` registry
reads 1, ring follows; START GAME click with overlay name "TestHero" →
`createstart` → `role.create` attempted (fails "gateway not connected"
with no backend, as expected — wiring proven to the gateway boundary).

Round 2 (user-directed): gender symbols Male/Female/Male/Female on
A/B/C/D (bitmap 27 male confirmed purple ♂, bitmap 4 teal ♀; only B's
placement is authored, the rest follow the game's pattern); stamp
re-rendered as page-specific words — "Creation" on create (bitmap 50),
"SELECTION" on select (new bitmap 50b-selection.png, same border art)
— and follows the selected slot on both screens; dice art removed (no
random names supplied); name field is an HTML overlay positioned over
the box art via exported CREATE_GEOM (Phaser has no text input), Enter
or START GAME submits; creation success goes straight into the world
(`enterWorld` with the new role id); select screen tracks a selected
role and START GAME enters with it. Start states 55/57 stay untouched
(role unverified). Name entry → world entry end-to-end still needs the
running Python stack.

## Baked-text bitmaps (must be redrawn with English)

| Bitmap | Size | Chinese | Used as | Disposition |
| --- | --- | --- | --- | --- |
| 14 | 113x27 | 角色創建 | Create title strip | Redraw, PIL: metallic silver gradient + glow on black |
| 61 | 113x27 | 人物選擇 | Select title strip | Redraw, same treatment as 14 |
| 35 | 98x37 | icon + 靈猴 | Class A ribbon | Redraw: keep icon art, replace glyphs, keep gold glow |
| 21 | 101x37 | icon + 九尾 | Class B ribbon | Redraw: keep feather icon, green-tinted glyphs |
| 28 | 106x37 | icon + 牛魔 | Class C ribbon | Redraw: keep blade icon, red-tinted glyphs |
| 5 | 116x37 | icon + 羅刹 | Class D ribbon | Redraw: keep fan icon, purple-tinted glyphs |
| 40 | 88x23 | 角色名稱 | Name label | Redraw: embossed grey gradient |
| 50 | 132x95 | 選定 | selectmc stamp (tilted, fiery border) | Redraw: calligraphic style + orange glow; Blender only if PIL looks weak |
| 53 | 225x68 | 開始遊戲 | Start button, known state | Redraw: keep ornate frame, replace 4 glyphs, gold emboss |
| 55/57 | 225x68 | (assumed 開始遊戲) | Start button, other states, usage unplaced | Verify state role first, then same as 53 |
| 63 | 171x171 | 角色创建 (simplified!) | Empty-slot badge | Redraw with English; note source uses simplified while rest is traditional |

## Runtime text (code change once glossary is approved, no bitmap work)

| Source | Chinese | Where |
| --- | --- | --- |
| EditText 37 | 敢問天地誰主宰 / 滅佛覆天由我來 | Class A motto, rendered by scene |
| EditText 20 | 有情最是無情人 / 滾滾紅塵冷豔容 | Class B motto |
| EditText 30 | 天地血染楓林紅 / 只為魔族千萬魂 | Class C motto |
| EditText 8 | 熊熊焰燃燒我心 / 芭蕉風吹盡世愁 | Class D motto |
| DOM panel | Create character / job buttons / slot counts | Already English; align with glossary |

## Reused as-is (no text)

Backdrop 12, portraits 1/16/24/32, ring 9, input box 39, dice 42, gender
symbols 4/27, badge frame art. Unplaced states 44/46 and male symbol 27:
no English work until their panel role is recovered.

## Blender / Ultima3D scope

2D PIL recreation is the default for every row above. Blender enters only
if a redraw looks weak (stamp 50 is the single candidate) or for new
embellishments. I have no Ultima3D MCP connection in this environment, so
Blender work is a handed-off task, not something I execute here.

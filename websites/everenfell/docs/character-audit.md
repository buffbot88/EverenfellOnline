# Character milestone 1 — audit (class count, assets, gaps)

## 1. Class count: 4 slots, jobs A/B/C/D, real names recovered

- `Server-v1/game/protocol.py:1183`: `MAX_ROLES_PER_ACCOUNT = 4`
  (comment: "Java caps roles per account+server at 4").
- 10002 enforces it with error 2005; duplicate name 2002, illegal name
  2001.
- Job codes observed in tests and data are the strings `A`, `B`, `C`,
  `D` (level-1 skill tokens `mb/yx/bh/lx`, one per job line).
- **Class names (recovered art + containment, not invented):**
  ribbons render 羅刹 (icon 5), 九尾 (icon 21), 牛魔 (icon 28),
  靈猴 (icon 35); SymbolClass containment fixes the pairing —
  sprite 38/A → 35 (靈猴), 23/B → 21 (九尾), 31/C → 28 (牛魔),
  11/D → 5 (羅刹). `protocol.ts` JOB_NAMES records this chain.
- Slot cap 4 = capacity rule, not one-per-class.

## 2. Interface assets — hierarchy decoded AND re-driven

Source SWF `output/swf-memory/mem-000006eeae18-1c3192dd9965.swf`
(FWS v10, 222,611 bytes), decoded by
`scripts/asset_tools/decode_create_ui.py` into
`src/assets/create-ui-layout.json` (machine-readable ground truth).
Key decoder lessons: this encoder sets HasCharacter=0x04 with a 1-byte
identity matrix under 0x02 (PlaceObject), defineShape2/3 have NO
edge-bounds record (only DefineShape4 tag 83 does), and every shape
carries a leading 0xFFFF-bitmap placeholder fill before its real art.

- **SymbolClass (5 entries, names intact):** 67 `ui.asyncpanel.createUI`,
  38 `ui.shared.create.A`, 31 `ui.shared.create.C`, 23
  `ui.shared.create.B`, 11 `ui.shared.create.D`.
- **15 DefineSprite timelines**, 22 shapes, 24 bitmaps, 5 DefineEditText,
  DoABC (22 strings: only `createUI`/`dele_create`/`dele_select` linkage
  names — all logic imported). Single root ShowFrame; the panel is
  code-instantiated (no top-level placements).
- **Root (sprite 67):** backdrop shape 13 (bitmap 12, 935x512 stage) +
  dele_create (sprite 60) at (15,-10) + dele_select (sprite 66) at
  (14,-7.95). Code toggles create/select visibility.
- **Create panel (sprite 60):** class tabs A/B/C/D at
  x = 90/300/516.05/713.95, y = 100 — side-by-side columns, NOT
  stacked (earlier "one origin" claim was a matrix-parse bug).
  Title (shape 15 → bitmap 14, 113x27) at (450,24); selectmc confirm
  (shape 51 → bitmap 50, centered 132x95) at (257,74); name label
  art (shape 41 → bitmap 40, 88x23) at (279,388); dice (sprite 48 →
  bitmap 42, 26x28) at (570.05,383); txt_name field (182x19,
  initial text "等 級", no variable) at (387,392); btn_start
  (sprite 59 → bitmap 53, 225x68) at (375,432); imported
  `tg.shared.cm.ybutton` (char 26484, depth 35, code-positioned).
- **Each class tab (2 frames):** portrait (A=32, B=16, C=24, D=1 —
  the old A=1/D=32 guess was swapped); icon ribbon at local (27,163)
  (A→35 靈猴, B→21 九尾, C→28 牛魔, D→5 羅刹); motto edittext at
  local (2,205), SimSun 13px #ece5cb, two centered lines (A 敢問天地
  誰主宰/滅佛覆天由我來, B 有情最是無情人/滾滾紅塵冷豔容, C 天地血染
  楓林紅/只為魔族千萬魂, D 熊熊焰燃燒我心/芭蕉風吹盡世愁); frame 2
  adds the ring (shape 10 → bitmap 9, 144x143). Class B also shows
  the female symbol (shape 19 → bitmap 4, 30x30) at local (120,120).
- **Select panel (sprite 66):** title (shape 62 → bitmap 61, 人物選擇,
  113x27) at (450,23); selectmc at (274.5,58.95); btn_start at
  (375,432); slot badges b1..b4 (sprite 65 → bitmap 63, 171x171)
  at x = 98/296/516/714, y = 100. Owned-role portraits are
  code-attached (no placements) — role i renders in badge slot i.
- **No ImportAssets2 tag exists in this module** (earlier claim
  withdrawn — tag 57 absent). The ybutton import resolves through
  the loading context. `res/assets/tg.swf` (1.5 MB, the probable
  `tg.shared.*` host) is encrypted/obfuscated on disk, not decoded.
- Name input box art (bitmap 39, 229x40) is unplaced (code-attached).
  Its position (373,377) is inferred from shape-41 bounds (right and
  bottom edges align: label starts x=279, box ends x=602=279+323,
  y=377..417); the txt_name rect (387,392,182x19) sits inside it
  with plausible insets. Marked as inference in scene code.
- Dice states 44/46, start states 55/57, and male symbol (bitmap 27)
  are unplaced — art recovered, usage/positions unknown (55/57 are
  presumably button states; 27's panel role is unknown). 48/59
  frame-2/3 records are color-transform modifies, not placements.
- `assets/ui/shared-controls/` (196), `gameui/` (170), `hud-chat/`
  (338): generic controls/HUD art.
- **No separate character-selection SWF exists** — selection art
  (61, 63) lives inside this same creation module.
- **Resolved conflict:** the "fifth portrait" 63 is not a class at
  all — it is the create-entry badge. Four portraits, four classes.

## 3. Client status (SWF-driven reconstruction)

- `CharacterCreateScene`: letterboxed 935x512 composition from
  `create-ui-layout.json` — backdrop, title strip, four class columns
  at authored x (portrait + ribbon + female symbol on B + two motto
  lines), frame-2 ring on the selected tab, selectmc/name-label/
  input-box/dice/start chrome at authored translates. `jobselect`
  event + `{selected}` restart flow unchanged. Name entry stays in
  the DOM panel; sex stays 0 (no gender selector exists in this
  module — only B's display-only ♀; male symbol unplaced).
- `CharacterSelectScene`: same backdrop, select title, selectmc,
  start skin; role i in badge slot i (corrected portraits A=32,
  B=16, C=24, D=1; name + `class · Lv` below); empty slots show the
  authored badge art (click → `gocreate`); 4/4 full state.
  `roleselect`/`gocreate` events unchanged.
- `client.ts` + `protocol.ts`: JOB_NAMES (evidence-chained above);
  DOM job buttons and role rows show class names with code fallback.
  Flow unchanged: session → ticket → `auth.session` → `world.enter`
  → zero roles ⇒ creation else selection; entry ⇒ `world.snapshot`.
- Loading routes `?scene=select|create|world` for inspection.
- Visual verification 2026-10-26 (controlled local dev, vite
  `everenfell-dev-assets` plugin serves ./assets at /assets/ in
  `vite.config.ts`, dev-only): `?scene=create` renders the full
  composition — backdrop, 角色創建 title, four portraits with ribbons
  + mottos + ♀ on B, name label/box + dice, 開始遊戲 skin, 選定
  stamp on the selected tab. `?scene=select` (no roles) renders
  backdrop, 人物選擇 title, 選定 stamp, four badge-63 empties,
  開始遊戲 skin. Positions are decoded, not eyeballed.
- Motto note: SWF bytes for class D read 芭蕉風吹盡世愁; screenshot
  vision transcribed 畫 for 盡 twice — stylized-font misread is more
  likely than a decoder error. Keep the SWF bytes; confirm against the
  contact sheet before changing.

## 4. Backend rules (unchanged, authoritative)

- `db.create_character` / `list_roles` (server+account scoped),
  `check_role_name`: CJK fullmatch, rejects leading `s`/`S`.
  ASCII names (e.g. `Wukong`) fail validation — creation UI says so.
- `gateway role.create` (new, minimal): validates job A–D, sex 0/1,
  4-slot cap, then forwards 10002 `[account, name, job, sex, face, 0,
  server, '']`; maps 2001/2002/2005 to messages; appends the new role.
- `world.snapshot` refuses unowned `roleId` (unchanged).

## 5. Orion auth branch

- `origin/infra/everenfell-alpha-auth` is merged into `main`
  (only an `agents.json` diff remains). AGP OIDC + S1 gating in
  `main.ts`/`auth.ts` was left intact.

## 6. Audio (shared controller, original SFX)

- No sound code existed; no SWF embeds audio (zero DefineSound tags
  across all recovered modules — Flash loaded audio externally).
- 223 original SFX in `MKO_Client/Assets/res/tw/r/s/`; UI set vendored
  to `assets/sounds/`: clickBtn, closeP, openP, panelOpen, panelClose,
  tab_change. No BGM found anywhere in the res tree: no music/bgm-
  named files, and `res/MPlayer.swf` (decompressed CWS) contains zero
  audio refs — it is a shell, not a music bundle. No authentic music
  exists to play, so no music controller was added (SFX-only scope).
- `src/game/sound.ts`: one shared WebAudio controller (master gain,
  persisted mute, gesture unlock), used by DOM shell and Phaser.
  Navbar 🔊/🔇 toggle in `#sitebar`. Job switches play tab_change,
  panel toggles play panelOpen/Close, confirms play clickBtn.

## 7. Open gaps / conflicts

1. ~~Sprite-timeline re-drive~~ DONE this pass (layout JSON +
   both scenes consume authored translates, frame-2 ring, mottos).
   Remaining timeline work: 48/59 cxform hover states, tab-switch
   single-visible-panel behavior (currently scene restart), shape-10
   vector outline (bitmap used), SimSun font substitution.
2. ~~ImportAssets2~~ corrected: no tag-57 in this module; ybutton
   behavior + dice/name wiring live in the encrypted `tg.swf`
   loader context (undecoded) — start-press and random-name effects
   stay DOM-driven approximations.
3. ~~Job-letter ↔ class-name pairing~~ VERIFIED via containment
   (audit §1, protocol JOB_NAMES).
4. Class previews/animations location: not inside createUI bitmaps;
   likely separate character packages — unlocated.
5. Face options, gender toggle wiring, dice randomizer wiring.
6. Gateway job allowlist (A–D) is stricter than `db.create_character`
   (any string) — matches all observed data but awaits original-client
   confirmation.
7. Name rule is CJK-only; projector-era Latin names would 2001 —
   needs a live-client capture to confirm.

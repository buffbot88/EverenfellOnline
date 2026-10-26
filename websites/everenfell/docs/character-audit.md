# Character milestone 1 — audit (class count, assets, gaps)

## 1. Class count: 4 slots, jobs A/B/C/D, real names recovered

- `Server-v1/game/protocol.py:1183`: `MAX_ROLES_PER_ACCOUNT = 4`
  (comment: "Java caps roles per account+server at 4").
- 10002 enforces it with error 2005; duplicate name 2002, illegal name
  2001.
- Job codes observed in tests and data are the strings `A`, `B`, `C`,
  `D` (level-1 skill tokens `mb/yx/bh/lx`, one per job line).
- **Class names (from the create-ui contact sheet, not invented):**
  羅刹 (icon 5), 九尾 (icon 21), 牛魔 (icon 28), 靈猴 (icon 35).
  Job-letter ↔ name pairing is still unverified.
- Slot cap 4 = capacity rule, not one-per-class.

## 2. Interface assets — hierarchy decoded, not yet re-driven

Direct answer to the open question: the client so far uses PNG export
plus manual Phaser placement only. No MovieClip hierarchy has been
rebuilt; the old manifest recorded `"linkage": []` for every bitmap and
the first-pass scenes carried no timeline data. What follows is the
decoded ground truth the faithful reconstruction must be built from
(source SWF `output/swf-memory/mem-000006eeae18-1c3192dd9965.swf`,
FWS v10, 222,611 bytes, verified 2026-10-26 with `scripts/asset_tools`
plus new PlaceObject/SymbolClass parsing).

- **SymbolClass (5 entries, names intact):** 67 `ui.asyncpanel.createUI`,
  38 `ui.shared.create.A`, 31 `ui.shared.create.C`, 23
  `ui.shared.create.B`, 11 `ui.shared.create.D`. Exactly the module
  names the recovery notes cited.
- **15 DefineSprite timelines**, 22 shapes, 24 bitmaps, 5 DefineEditText,
  1 font, DoABC bytecode, **ImportAssets2 (tag 71) present but with
  count 0 against `lib.swf`** — a vestigial shared-library link; this
  module is self-contained, no missing artwork hides in another SWF.
  DoABC strings confirm the wiring surface: `dele_create`,
  `dele_select` (button delegates), `txt_txt` (text field instance).
  Single root ShowFrame: all composition lives inside sprites.
- **Placement trees (PlaceObject2/3 decoded):** 67 (panel) = shape 13 +
  sprite 60 + sprite 66. 60 (class strip) = class sprites 23/31/38/11
  stacked at one origin (tab-switching via ActionScript, not layout) +
  shape 41 + sprites 48/52/59 + edittext 49. Each class sprite
  (2 frames) = portrait sprite + label shape + class-name edittext;
  frame 2 adds shape 10 (selection highlight). 66 (button row) = shape
  62 + sprites 59/65/52. Sprites 48/59 (3 frames each) are the
  animated bits. No placement carries a matrix — children render at
  authored coordinates (verify against shape bounds next).
- **Contact-sheet semantic map (vision-decoded, authoritative):**
  portraits 1/16/24/32; class icons as above; 12 backdrop; 14 title
  text; 4/27 gender symbols; 39 name input box; 40 name label; 42/44/46
  random-name dice states; 9 selection ring (now the highlight);
  50 confirm (選定); 53/55/57 start-game states; 61 selection title
  (人物選擇); 63 create-entry badge (now on empty slots). Scenes were
  corrected to these semantics; positions stay manual for now.
- `assets/ui/shared-controls/` (196), `gameui/` (170), `hud-chat/`
  (338): generic controls/HUD art.
- **No separate character-selection SWF exists** — selection art
  (61, 63) lives inside this same creation module.
- **Resolved conflict:** the "fifth portrait" 63 is not a class at
  all — it is the create-entry badge. Four portraits, four classes.

## 3. Client status (after milestones 2–3, semantics corrected)

- `CharacterCreateScene`: backdrop 12 + title art 14 + 4 job portraits
  (A–D in bitmap order 1/16/24/32) + authentic ring-9 highlight.
  Name entry stays in the DOM panel (Phaser has no text input); sex
  stays 0 until the gender toggle is reconstructed.
- `CharacterSelectScene`: title art 61, owned roles (portrait by job,
  name, job, level), empty slots as outlined boxes + 63 badge
  (click → creation), 4/4 full state.
- `client.ts`: AGP session → ticket → `auth.session` → `world.enter` →
  zero roles ⇒ creation, else selection; creation success ⇒ re-enter ⇒
  selection; entry ⇒ `world.snapshot` (ownership server-enforced).
- Loading routes `?scene=select|create|world` for inspection.
- No screenshots yet: dev/alpha servers were not started during this
  pass (process rule). The screenshot described in review (HTML
  "Choose your hero" heading, cyan marker) is the pre-reconstruction
  placeholder flow, not these scenes. Verify visually with the stack.

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
  tab_change. No BGM found anywhere in the res tree (deferred).
- `src/game/sound.ts`: one shared WebAudio controller (master gain,
  persisted mute, gesture unlock), used by DOM shell and Phaser.
  Navbar 🔊/🔇 toggle in `#sitebar`. Job switches play tab_change,
  panel toggles play panelOpen/Close, confirms play clickBtn.

## 7. Open gaps / conflicts

1. Sprite-timeline re-drive (positions from shape bounds, frame-2
   highlight states, 48/59 animation, tab-switching) — the faithful
   pass; needs approval before implementation.
2. ImportAssets2 partner SWF unidentified — may hold shared art.
3. Job-letter ↔ class-name pairing unverified.
4. Class previews/animations location: not inside createUI bitmaps;
   likely separate character packages — unlocated.
5. Face options, gender toggle wiring, dice randomizer wiring.
6. Gateway job allowlist (A–D) is stricter than `db.create_character`
   (any string) — matches all observed data but awaits original-client
   confirmation.
7. Name rule is CJK-only; projector-era Latin names would 2001 —
   needs a live-client capture to confirm.

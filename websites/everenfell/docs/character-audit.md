# Character milestone 1 — audit (class count, assets, gaps)

## 1. Class count: 4 slots, jobs A/B/C/D

- `Server-v1/game/protocol.py:1183`: `MAX_ROLES_PER_ACCOUNT = 4`
  (comment: "Java caps roles per account+server at 4").
- 10002 enforces it with error 2005; duplicate name 2002, illegal name 2001.
- Job codes observed in tests and data are the strings `A`, `B`, `C`, `D`
  (e.g. `test_effect_bags.py` creates `job='C'`; level-1 skill tokens are
  `mb/yx/bh/lx`, one per job line).
- **No verified class names exist.** The recovered art and the `.jat` data
  carry no `warrior/mage/...` mapping. The client labels jobs `A/B/C/D`
  only. Slot cap 4 = capacity rule, not one-per-class.

## 2. Recovered interface assets

- `assets/ui/create-ui/` — creation module (222,611-byte SWF): 24 bitmaps,
  all decoded. Backdrop 12 (935x512), title bar 39 (229x40), five 171x171
  portraits (1/16/24/32/63), buttons (5/21/28/35: ~100x37), wide buttons
  (53/55/57: 225x68), labels (14/40/61), frame (9: 144x143), panel
  (50: 132x95), icons (42/44/46). **No SymbolClass linkage names** —
  composition order is inferred from sizes, not decoded timelines.
- `assets/ui/shared-controls/` (196 bitmaps), `gameui/` (170),
  `hud-chat/` (338): generic controls/HUD, usable for buttons/panels.
- **No character-selection module identified.** The select screen reuses
  create-ui portraits by job index; the original selection SWF/module is
  still missing.
- **Conflict — five 171x171 portraits vs four jobs.** Bitmap 63 has no
  verified job mapping. It renders dimmed as UNVERIFIED in the create
  scene rather than becoming a fifth class.

## 3. Client status (after milestones 2–3)

- `CharacterCreateScene`: backdrop + title bar + 4 job portraits (A–D in
  bitmap order 1/16/24/32) + UNVERIFIED fifth; selection highlight.
  Name entry stays in the DOM panel (Phaser has no text input).
- `CharacterSelectScene`: owned roles (portrait by job, name, job, level),
  empty slots as outlined boxes (click → creation), 4/4 full state.
- `client.ts`: AGP session → ticket → `auth.session` → `world.enter` →
  zero roles ⇒ creation, else selection; creation success ⇒ re-enter ⇒
  selection; entry ⇒ `world.snapshot` (ownership server-enforced).
- Loading routes `?scene=select|create|world` for inspection.
- No screenshots yet: dev/alpha servers were not started during this
  pass (process rule). Verify visually with the running stack.

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
  (only an `agents.json` diff remains). No coordination work needed;
  AGP OIDC + S1 gating in `main.ts`/`auth.ts` was left intact.

## 6. Open gaps / conflicts

1. Portrait↔job mapping is positional, not decoded — needs timeline work.
2. Original selection-module SWF unidentified.
3. Class names, face/sex options, creation animation: no source evidence.
4. Gateway job allowlist (A–D) is stricter than `db.create_character`
   (any string) — matches all observed data but awaits original-client
   confirmation.
5. Name rule is CJK-only; projector-era Latin names would 2001 — needs
   a live-client capture to confirm.

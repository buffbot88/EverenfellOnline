# Changelog

All notable changes to the Python game server (`Server-v1/`). Tests are
counted as collected cases via `python3 -m unittest discover -s tests`
from `Server-v1/`.

## v1.5 — 2026-10-24

Gameplay release: 1690 server tests, all passing; 240 command IDs
implemented with tests plus 26 server-push IDs (313 of 497 Java IDs
dispatched). New in v1.5:

- **Marriage** (135000–135006, pushes 135002/135003/11131/11101):
  proposals with ring/broadcast gates, two-sided acceptance, divorce
  (free offline, YB online), spouse teleport, ring strengthening,
  daily intimacy schedule, login/logout presence, reconnect
  persistence. `role_marry` table + atomic wedding/divorce/spend
  transactions (`tests/test_marry.py`, 33; `docs/marry-ledger.md`).
- **Guild dungeons** (118001–118004/118007): two-member entry, seeded
  boss fights, shared kill roster, chest claims, quit/disconnect/
  leave/disband, weekly reset (`tests/test_guildfuben.py`, 22;
  `docs/guildfuben-ledger.md`).
- **Party/team lifecycle** handlers and multiplayer tests
  (`tests/test_team.py`, 26; `docs/team-ledger.md`).
- **Guild lifecycle** handlers and multiplayer tests
  (`tests/test_guild.py`, 19; `docs/gonghui-ledger.md`).
- Census updated (`docs/command-census.md` via `docs/census.py`):
  135003/11131 classified push-only; marry moves from 0/9 to 6
  implemented + 2 push-only. `README.md` gains a per-family
  progression-status table.

Known gaps stay in the family ledgers (guild-dungeon
instance-isolation/scheduling approximations, marriage outbox/bus
and count deviations).

## v1.4 — 2026-10-22

Public-launch release. The repository now ships **only the Python server**
(`Server-v1/`, plus `README.md`, `CHANGELOG.md`, `LICENSE`); legacy client,
Java distribution, tooling and internal docs stay in private history
(`backup/pre-v1.4-full`). 945 server tests, all passing.

Locked-stable internals (AMF3 codec, AI/combat formulas, scheduler,
eventbus, stage registry, attribute/buff maps, client map parsing) are
frozen and ship without their exhaustive golden suites (deleted; full
history retained privately).`game/mapdat.py` is dropped — nothing at runtime imports it. Gameplay families keep full golden coverage.

Also fixed in v1.4: the baoshi family (37000/37001/37002) shipped without its
`role_baoshi` Store table, so its 22 golden tests errored and gem upgrades
did not persist. The table plus `get/save_role_baoshi` and server wiring
are now in; the suite is green.

Pet slice: 136005 upDownZhen (deploy/remove formation slots) and 136006
chuZhan (expedition deploy/recall/switch) with the 136010 formation and
136011 expedition pushes (`tests/test_pet.py`, 15). The @EasyMapping audit
also settled the family map (136009 is jinJieZhenFa, not a gap) and proved
136007 a dead inbound route with no handler jar-wide. 136001/136002/
136003/136004/136008/136009 need the ChongWu config tables, which do not
ship in the reference config tree, so they stay unported.

Ported command families (each golden-tested against the Java oracle's
bytecode shapes and error codes):

- **Meiren** (82000–82003): companion panel, recruit, level/heti upgrade,
  chanmian progression.
- **Email claims** (63003/63006/63007/63008): single-item, JB purse, YB
  purse and one-key sweep claims; `role_email` carries the JB/YB purses.
- **Baoshi** (37000–37002), **shenjiang** activation/skill lines,
  **chengjiu** panel/claim, **qiandao** sign-in, **yingyin** mount-skin
  lines, **zuoqi** rank/longhun pills, **pet** info panel, juqing/zuwu
  quest tails, inner-fly (40101), town revive (43001), AMF3 sealed
  traits, expanded security gates.

State: 164 command IDs routed with tests (153 persisted to SQLite, 11
golden-only) plus 71 server-push IDs emitted with a test mention.

## v1.3 — 2026-10-17

Internal milestone: mount persistence, richang fixes, ledger/audit docs
refresh (118 routed at the time).

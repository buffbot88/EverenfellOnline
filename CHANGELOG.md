# Changelog

All notable changes to the Python game server (`Server-v1/`). Tests are
counted as collected cases via `python3 -m unittest discover -s tests`
from `Server-v1/`.

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

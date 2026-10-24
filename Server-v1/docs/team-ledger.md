# Party/Team porting ledger

Authoritative per-command status for the Java party surface.
Evidence: `TeamAction` / `TeamServiceImpl` / `TeamVoOutput` /
`TeamMemberVoOutput` / `TeamConstants` javap (`.jrecon/team_*.txt`
scratch, not committed), the `DuiWuJiaCheng` exp/life-by-size table,
and the 52xxx wire IDs from the Flash client. The `*Commands`
constants class for team is absent from the `dntg_start.jar` javap
dump, so these IDs sit outside the `docs/command-census.md`
denominator (497 distinct Java IDs); the census regeneration in this
commit only moves the dispatched count 292 -> 302.

Status words: complete+tested (wire-exercised through the real
handlers + `TeamState` + SQLite store), push-only (S2C, asserted in
member outboxes).

## Inbound commands (TeamAction)

| ID | Java method | Status | Notes |
| -- | ----------- | ------ | ----- |
| 52000 | createTeam | complete+tested | solo or explicit-id team led by rid; reply `[1, team VO]` |
| 52001 | getTeam / getTeamByMap | complete+tested | own VO, or teams listed under the leader's map bucket |
| 52002 | invitebegAddTeam / yaoqingAddTeam | complete+tested | invite card 52030 to solo targets, apply card 52035 to teamed leaders; errors ride 52002 |
| 52003 | addTeam | complete+tested | join; 52000 VO to the joiner, 52003 card + 52011 jiacheng fan-out |
| 52004 | leader request (shenqing) | complete+tested | transfer handshake; 52004 updates on completion |
| 52005 | change leader | complete+tested | pending next-leader accept path |
| 52006 | exitTeam | complete+tested | leave; 52006 everywhere, 52011 refresh, earliest-joiner succession |
| 52030 | yaoqingAddTeam answer | complete+tested | invite accept/refuse; both-solo merge covered |
| 52035 | shenqingAddTeam answer | complete+tested | apply accept/refuse via the leader's card |
| 11002 | teamChat | complete+tested | text fanned out to live member sessions |

## Push-only (member fan-out, no inbound handler)

| ID | Java | Status | Notes |
| -- | ---- | ------ | ----- |
| 52003 | member card | push-only | fresh member snapshot to the rest on join |
| 52004 | leader update | push-only | succession / transfer notice |
| 52006 | exit notice | push-only | leave + disband |
| 52011 | jiacheng pair | push-only | `[exp, life]` bonus from `DuiWuJiaCheng` by team size |
| 52012 | map move | push-only | member map change; leader moves the map bucket |
| 52030 / 52035 | invite / apply cards | push-only | pending-handshake cards |

52007/52008/52009 are stage-owned visibility IDs the team service
never sends (52009 is answered by the stage module).

## State, combat, loot, teardown

- `game/team.py` `TeamState` mirrors the DataContainer regions
  (`team`, `role_team`, `map_team`) under one lock: nothing is
  persisted, so a restart drops every team. 4-member cap, T-prefixed
  ids, join-ms stamps for succession order.
- EXP: `AiServiceImpl.monsterExpDrop` team rule -- a teamed killer
  reads the `rankrevise` column with the `(1+(n-1)*0.05)` team-size
  factor (`combat.base_kill_exp`); solo kills use `solorevise`.
- Loot: drops stamp `owner_team_id`; teammates pass the ownership
  gate inside the protection window, strangers wait it out (same
  expiry clock as solo drops).
- Map change tracks the member and re-buckets the team when the
  leader moves (`changeStageTeam`); disconnect exits every owned
  role offline with leader succession, and a one-member team is
  disbanded with a final 52006 (`removeTeam`).

## Python deliberate deviations (documented)

- Only the killer is credited for team kills: no per-harmer damage
  shares are tracked, but the revise column and size factor follow
  the killer's team exactly.
- Stale role links are cleaned on lookup (`_team_lookup` drops
  entries whose team is gone) instead of throwing.
- Void-reply answer flows return silence on the accepting session
  and carry the outcome in the peer pushes, matching the action's
  null-skip convention.

## Gaps

- None in the 10-ID inbound family: all complete+tested in
  `tests/test_team.py` (26 tests: create/invite/join, apply flows,
  both-solo merge, refusals, real-swing team EXP, teammate/stranger
  loot windows, map moves, disconnect succession, teardown).
- Next unfinished families per the census: `marry`, `guildfuben`,
  `kuafu`, `gm` residuals.

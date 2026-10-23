# Guild-task quest porting ledger

Authoritative per-command status for the Java guild-task surface.
Evidence: `GonghuitaskAction` + `GonghuitaskServiceImpl` javap
(inbound 81000-81005 + 81008; pushes 81006/81007/81009/81010),
`IGonghuitaskService`, `GongHuiTaskConstants` and `GonghuitaskErrorCode`
clinit ints, `RoleGonghuiTask` fields, `CreateGongHuiTaskOutPut` /
`GetGongHuiOutPut` shapes, and `GongHuiRenWu(.JiangLi/EWaiJiangLi).jat`
(120 conditions with difficulties 1-12, 290 rewards, 72 loop rewards).

Status words: complete+tested (wire-exercised through the real
handlers + SQLite store), implemented-untested (dispatched, pinned by
a wire test, but the void-reply ID never appears in a reply frame),
push-only (S2C, no inbound handler needed).

Bookkeeping reconciliation (post-pozhen census): 81008 was promoted
to implemented in `command-census.md` under the TESTED_BY_EVIDENCE
rule — a void-reply inbound ID proven by a wire/handler test counts
as implemented (direct handler tests assert the real payout/advance
fan-out; a wire test pins the dispatch route). The mechanical
`'81008'`-in-quotes test-source rule cannot fire for a void reply by
construction. Same treatment as richang 50209.

## Inbound commands (GonghuitaskAction)

| ID | Java method | Status | Notes |
| -- | ----------- | ------ | ----- |
| 81000 | getTaskRichangeInfo | complete+tested | `[quest VO, costs, loop VO]`; 11-field VO + `[jiangDi, tiSheng, direct, 1key, best]` + loop reward VO; init queues its own 81000 before the reply; stale recevie day re-rolls; guild-gated + level 30-gated silence |
| 81001 | decreaseDifficulty | complete+tested | easier condition for 50000 YXB; `[1, 1, parts]`; `81101` done-loop, `81102` difficulty 1, `1003` YB-short |
| 81002 | increaseThick | complete+tested | best reward for 50000 YXB; `[1, 10, rewardPart]`; `81101`, `81103` thick 10, `1003` |
| 81003 | zhijieCompleteCurrentLoop | complete+tested | finish now for 10 YB, then 81006 pay / 81010 stop / 81009 receive fan-out and `[1]` reply |
| 81004 | completeAllLoop | complete+tested | one-key rest for 50 YB (vip-gated `480073`); `[1, fufei]`; `81101` |
| 81005 | completeBestAllLoop | complete+tested | best one-key for 100 YB (vip-gated); best re-roll pushes 81009, replies `[1, fufei, part, thick, difficulty]`; `81101` |
| 81008 | notifyServerLoop | complete+tested (TESTED_BY_EVIDENCE) | fufei payout then advance-or-stop; void reply like Java, so the ID never lands in a reply frame (same void-reply class as richang 50209); direct handler tests pin payout/advance, a wire dispatch test pins the route |

## Push-only (no inbound handler)

| ID | Java | Status | Notes |
| -- | ---- | ------ | ----- |
| 81006 | payTaskRichange result | push-only | `[taskUid, pairs, exp, jb, bindYb, 0, zhenqi]` on every settle; asserted in kill/zhijie/notify frames |
| 81007 | changeTaskRichangMonseter | push-only | `[questId, monsterId, done]` per counted kill |
| 81009 | receiveTaskRiChange | push-only | fresh 11-field quest VO on every loop advance |
| 81010 | stopRefreshRichang | push-only | `[quest VO, loop reward VO]` on the finished final loop |

## Quest lifecycle (all genuine records)

- One `task_gonghui` row per role (same shape as `task_richang`);
  re-rolls daily, 20 loops, costs 50/100/50000/50000/10 from the
  condition export impl (bipush/ldc constants, not invented).
- Monster kills fan out through the shared combat hook alongside
  main/taofa/richang: 81007 progress, state 1 persisted before the
  settle (the jar's shared-entity visibility), then 81006 pay,
  81010 stop or 81009 receive.
- `receiveTaskRiChange` thick quirks ported exactly: loop 19 at
  state 2 draws difficulty 11, loop 14 at state 2 draws difficulty
  12. Thick-11 rewards exist only in sub-90 buckets; thick-12
  rewards exist nowhere, so loop 14 genuinely stalls like Java
  (pinned by test, not worked around).
- Rewards grant exp/YXB/bind-YB/zhenqi/goods like richang, plus
  **banggong via `addRoleGongxian`** accumulating on the member row.
  Prestige stays display-only (no grant column/service found).

## Guild gate (minimal membership, documented)

- Every handler and the kill hook first resolve the guild via
  `guild_member`; a missing row answers silence, exactly like
  Java's null-`GuildWrapper` branch in `getTaskRiChang`.
- Membership rows are written by the unported GuildAction family;
  `save_guild_member` is a test/dev hook, not a guild system.
- Full guild create/invite/rank/guildfuben behavior is unported.

## Python deliberate deviations (documented)

- YB-short failures answer `1003` (GeneralErrorCode.YB_NOT_ENOUGH,
  which the gonghui jar uses), not richang's `430403`.
- `receiveTaskRiChange`/`bestReceiveTaskRichange` carry the quest VO
  (not the full output data) in 81009, mirroring the richang port.
- The richang kill hook's settle-on-completion gap is left untouched;
  only the gonghui hook persists state 1 before paying, per the jar.
- Single-target commands accept the same bare/1-list role forms as
  the rest of the port.

## Gaps

- None in the 11-ID family: 7 inbound complete+tested (81008 via TESTED_BY_EVIDENCE), 4 push-only.
- Guild management itself (GuildAction ~20 methods, guildfuben 8)
  is a separate unported family.

# Quest / Task System porting ledger

Authoritative per-entry status for the Java task surface.
Evidence: `dntg_start.jar` javap of `TaskMainAction`, `TaskTaoFaAction`,
`TaskRiChangAction`, `TaskPublicAction`, `TaskMainServiceImpl`,
`TaskPublicServiceImpl`, `TaskMainConfigExportServiceImpl`,
`TaskConfigUtil`, `TaskDataUtil`, `GetTaskOutPut`,
`CreateTaskOutputWrapper`, plus `ZhuXianRenWu.jat` (444 rows),
`taskTaoFaRenWu.jat`, `taskRiChangRenWu*.jat` and the Vip tables.

Status words: complete+tested (wire-exercised), parity-unverified
(dispatched but not byte-compared against Java), partial, stub,
genuine-Java-no-op, not-an-inbound-command.

## Bus action, main quests (TaskMainAction)

| ID | Java method | Status | Notes |
| -- | ----------- | ------ | ----- |
| 50000 | getRunMainTask | complete+tested | `[taskId,recevieMs,cond,state]`; missing rows init the first quest; state 2 previews next (3 unlocked / 4 level-gated) |
| 50001 | getChapters | complete+tested | 3-arg overload returns null unconditionally, like Java |
| 50002 | getSubChapterInfo | complete+tested | `[detail, simpleVOs]`; per-quest states by sequence |
| 50003 | getSelectTaskInfo | complete+tested | wrapper for one quest |
| 50005 | completeMainTask | complete+tested | pay -> reward -> receive cascade (NPC-less tails pay inline, capped at 64); silent on failure |
| 50008 | getChapterTipsAttribute | complete+tested | `[type, subId, reward-or-null]` |
| 50004 | RECEVIE_TASK_MAIN | complete+tested | push, not a client command |
| 50006 | CHANGE_TASK_MAIN_CONDITION | complete+tested | `[taskId, monsterId, done]` per counted kill |
| 50007 | NOTIFY_TASK_FINISH | complete+tested | task id on completion |
| 50012 | NOTIFY_CHAPTER_COMPLETE | complete+tested | subchapter id when its last quest pays |

## Bus action, side quests (already ported, unchanged by this batch)

| IDs | Java action | Status | Notes |
| --- | ----------- | ------ | ----- |
| 50101/50103 + pushes 50102/50104/50105 | TaskTaoFaAction | complete+tested | list, tunshi merge, kill fan-out with comparator, pay on completion |
| 50201-50206/50209 + pushes 50207/50208/50210/50211 | TaskRiChangAction | complete+tested | info, difficulty/thickness adjust, direct/complete-all/best, loop notify, pay/change/receive/stop |
| BUS:43000 | TaskPublicAction.changeTaskMonster | complete+tested | fans out to main + taofa + richang, like the shared kill hook |

## Service methods (TaskMainServiceImpl)

| Java method | Status | Notes |
| ----------- | ------ | ----- |
| getRunTaskMainInfo | complete+tested | init-first + wrapper, via 50000 |
| getTaskRecevieState | complete+tested | 4 past the level gate, 1 when finished, else 0 |
| taskMainIsFinished | complete+tested | kills cover each monster, bag covers items |
| getChapterList/Tips/State | complete+tested | via 50001/50008/50002 |
| getSubChapterInfo/getTaskState/getSelectTaskInfo | complete+tested | via 50002/50003 |
| recevieMainTask | complete+tested | same/no-same-chapter 50004 (+50002), level gate queues 50000 refresh, NPC-less tails resubmit inline |
| payMainTask | complete+tested | id match, goods check, consume, state 2, 50005 + 50012 |
| reward | partial | currencies/exp/zhenqi, job-filtered bag grants and 50005 result ported; bag overflow drops (Java mails via putInBagOrEmail), shenjiang activation logged, events have no ported subscribers |
| changeMainTaskMonsterCondition | complete+tested | state-0 gate, per-monster cap, 50006, state 1 + 50007, pay_type-1 auto-finish |
| canChangeMonster/isPayTask | complete+tested | state 0 / state 2 predicates |
| dataCheck | complete+tested | NEW this batch: `_task_on_enter` on 10003 (disappeared-quest reset, paid-to-receive cascade, finished flip) |
| shengJiRecevieMainTask | complete+tested | `_task_on_level` on every level-up (`_role_gain_exp` fan-out): paid quest with a satisfied next receives via `_task_receive_next`; see `docs/level-ledger.md` |
| gmTaskUpgrade | deferred | GM/debug path; no GM commands exist in the port |
| getTaskMainFinishedChapterId/getChapterFinish/taskMainIsFiniState/getTaskMainState/isTaskfinsh/getTaskMainId/getTaskLineId | deferred | export helpers for unported consumers; no ported caller |

## Victory/progress lifecycle

Shared kills count toward the running quest (`canChangeMonster` = state 0,
per-monster cap at need, killMap2String persistence). Completion flips
state 0 -> 1 with 50007; pay_type-1 quests auto-submit inline. Submit
pays (goods check + consume), rewards, and receives the next quest;
level-gated next quests queue a 50000 refresh instead. Paid-but-unreceived
(state 2) chains complete on the next login via dataCheck.

## Config (all real records, no invented values)

`ZhuXianRenWu.jat` (444 main quests), `taskTaoFaRenWu.jat`,
`taskRiChangRenWu*.jat`, Vip tables. Shipped-table facts constraining
behavior: zero of 444 main quests carry `completeItem`/`recoverItem`/
`caiji` objectives (main quests are kills-only or talk-only), so the
ported item branches are unreachable by real config; no quest is
NPC-less *and* requirement-free, so every inline auto-submit still
passes through a kill gate or a 50000 refresh.

## Entity (`TaskMain` -> `task_main`)

`task_uid, task_id, state (0 running / 1 finished / 2 paid / 3 next-locked
preview / 4 level-gated), condition ('mid;n,...'), recevie_time,
create_time`. Taofa/richang keep their own tables, unchanged.

## Python deliberate deviations (documented, not parity-verified)

- Failure replies (`isNotNowmainTask`, `GOODS_NOT_ENOUGH`,
  `isTaskComplete`, `isRolelevelNotEnough`) stay silent; the port never
  flushes a partial queue on failure.
- Reward overflow drops with a warning instead of mailing.
- `getTaskMainWrapper` condition part reports only the last monster entry,
  like the Java loop overwrite.
- 50000/50002/50003 rows are sequence-ordered; Java HashMap order is
  nondeterministic.
- Level-gated receive pushes the 50000-shaped wrapper directly; Java
  pushes `getRunTaskMainInfo` plus the error output.

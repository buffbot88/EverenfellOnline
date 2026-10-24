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

## Guild gate (canonical membership, documented)

- Every handler and the kill hook first resolve the guild via
  `guild_member`; a missing row answers silence, exactly like
  Java's null-`GuildWrapper` branch in `getTaskRiChang`.
- Membership rows are written by the GuildAction family below;
  the guild-task gate reads the same canonical `guild_member`
  table (pinned by `test_guild.py::test_create_enables_guild_task_gate`).

## Guild management (GuildAction, 20 commands)

Evidence: `GuildAction` javap (param shapes, reply-vs-void routes,
silent guards), `GuildServiceImpl` bytecode (gate order, error codes,
`PublicMsgQueue` fan-out), `GuildVoOutput` (22-slot card) /
`GuildMemberVoOutput` (15-slot card) / `GuildBannerOutput` (5-slot
cost pairs) / `GuildGongxianOutput` (4-pair goods + 6-slot ledger
cards) / `GuildInfoOutput` / `SimpleClanVoOutput` (10-slot card)
shapes, `GuildErrorCode` clinit, and the `GongHuiChuangJian` (create
cost 1M YXB + `bangpai:1`, level 20), `GongHuiZhiWei` (position
permission flags) and `GongHuiQiZhiBiao` (banner caps) tables.
Tests: `tests/test_guild.py` (19 tests, multi-session wire through
the real handlers + SQLite store + shared `StageRegistry`).

Status words: complete+tested (reply/fan-out asserted through the
real handlers), implemented-untested (dispatched, no test yet).

| ID | Java method | Status | Notes |
| -- | ----------- | ------ | ----- |
| 53000 | createGuild | complete+tested | `[name, bannerName, bannerId, setting, decrType]`; gate order goods-short `1005` → in-guild `470002` → null `470000/470001` → length `470003/470006` → `check_role_name` `470004/470007` → dupes `470005/470008` → level `470010` → money `470009` → banner `470046`; deducts YXB or bag goods; replies `[1, 22-slot VO]` |
| 53001 | applyAddGuild | complete+tested | blank guild id silent; missing guild `470048`; in-guild `470011`; full `470012`; level 20 `470061`; no online admin `470013`; records the apply, pushes `[id, name, level]` as 53002 to online admins, replies `[1, 1]` |
| 53002 | applyIsAddGuild | complete+tested | void; caller guildless silent; non-recruit `470035`, missing guild `470017`, target in-guild `470019`, full `470012` pushed to the responsible side; accept adds member (position 3), pushes 53001 `[1, VO]` + 53002 member card; refuse pushes 53001 `[0, 470125]` |
| 53003 | inviteAddGuild | complete+tested | blank target / caller guildless silent; non-recruit `470062`; target in-guild `470019`, unknown `470018`, low level `470043`, offline `470020`, full `470012`; pushes 53004 `[guildId, name]`, replies `[1, 1]` |
| 53004 | inviteIsAddGuild | complete+tested | void; missing guild `470017`; double-guild `470011`; full `470012`; accept adds member, broadcasts 53003 `[1, member]`; refuse broadcasts 53003 `[0, 470050]` |
| 53005 | exitGuild | complete+tested | caller guildless silent; self-exit deletes the row; master with members transfers to lowest-position/earliest member; last member auto-disbands; kick needs `expel1/2/3` by victim band plus seniority, master unkickable `470024`, stranger `470018`, noperm `470015`; replies `[1, 1]` plus 53005 fan-out |
| 53006 | getGuildByRoleId | complete+tested | VO or explicit null frame when guildless |
| 53007 | getGuildInfos | complete+tested | guildless silent; `[VO, last-100 [time, msg] cards]` |
| 53008 | getGuilds | complete+tested | simple 10-slot cards for every guild |
| 53009 | delGuild | complete+tested | void; caller guildless silent; non-dissolve `470022` to caller; deletes guild + members/applies/ledger/log, pushes 53009 `[1]` to online members |
| 53013 | setGuildSetting | complete+tested | void; bad value / guildless silent; non-`set` `470033`; broadcasts 53013 `[1, setting]` |
| 53014 | updateGuildMessage | complete+tested | guildless silent; non-`notice` `470034`; length `470055`; `check_guild_notice` `470057`; replies `[1, 1]` plus 53014 fan-out |
| 53015 | updatePosition | complete+tested | void; bad shape / stranger silent; master transfer needs `appoint0` (actor becomes vice); vice needs `appoint1` + cap 1 (`470054`); admin needs `appoint2` + cap 3 (`470053`); demote needs seniority, else `470035`; broadcasts 53015 `[1, target, pos]` |
| 53016 | contributeMoney | complete+tested | void; negative silent; guildless silent; YXB-short `1003`; banner `maxMoney` cap `470060`; 1:1 gongxian + ledger row; broadcasts 53016 `[1, money]` plus 53029 refresh |
| 53017 | contributeGoods | complete+tested | void; bad shape/goods silent; bag-short `470038`; per-goods gm-cell cap `470059`; ledger row; broadcasts 53017 `[1, goodsId, count]` plus 53029 refresh |
| 53024 | getGuildByGuildId | complete+tested | VO or explicit null frame |
| 53028 | getBannerConditions | complete+tested | guildless `470018`; `[[qzMoney, ql, bh, zq, xw], [zxMoney, ql, bh, zq, xw]]` from the banner sj/zx cells |
| 53029 | getGongxianInfo | complete+tested | `[spirit goods, caller's ledger cards]`; zeros when guildless |
| 53030 | getGuildByLikeName | complete+tested | blank text replies `[]`; LIKE-escaped substring search |
| 53051 | getGuildById | complete+tested | VO, silent when missing |

Guild lifecycle notes:

- Master exit transfers leadership to the lowest-position, earliest-joined member (vice first by `create_time`); the last member out deletes the guild with its members/applies/ledger/log rows.
- `vice_user_role_id` tracks the single vice (cap 1); admins cap at 3 per `ADMIN_MAX_COUNT`; demotions need the actor senior to the victim.
- Pushes ride `_guild_broadcast`/`_guild_push` (session-first, presence fallback), the port's `PublicMsgQueue` equivalent; void routes return their own self-frames so direct-call tests observe them.
- Money type 1 = YXB (`tongqian`), 2 = YB (`lingshi`), 3 = bind YB; contribution ledgers accumulate per-role gongxian via the same `add_guild_gongxian` the quest port uses.

## Census note

`GuildCommands` (`G_53000`…) ships in a jar outside the
`dntg_start.jar` `*Commands` dump `docs/census.py` counts, so the 20
guild IDs sit outside the 497 denominator; the regenerated census
header (292 dispatched) is the accurate mechanical reflection.

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

- None in the 11-ID quest family: 7 inbound complete+tested (81008 via TESTED_BY_EVIDENCE), 4 push-only.
- Guild management: 20 commands complete+tested (table above). Still
  unported by plan: banner style/name/upgrade (53010-53012),
  diplomacy + login (53018-53021), guild call (53060/53061),
  guild chat (11003), and the 8-ID guildfuben family.
- Monetization-adjacent guild paths (banner upgrade costs, call
  monster fees) stay deferred with recharge.

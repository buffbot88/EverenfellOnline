# Friend / social relationships porting ledger

Authoritative per-command status for the Java friend surface.
Evidence: `FriendAction` + `FriendServiceImpl` javap
(`FriendCommands`, `FriendErrorCodeOutput`, `FriendConstants`,
`FriendVoOutput` clinit ints), `RoleFriend` / `RoleFoe` /
`RoleBlacklist` / `RoleContacts` entity fields, and
`NameFieldCheck.checkInputName` for mood text. Directed rows stay
directed: the port never invents reciprocal state, and acceptance is
the target's own add, exactly like the Java request-flag branch.

Status words: complete+tested (wire-exercised through the real
handlers + SQLite store), push-only (S2C, no inbound handler needed).

## Inbound commands (FriendAction)

| ID | Java method | Status | Notes |
| -- | ----------- | ------ | ----- |
| 51000 | getFriendsInfo | complete+tested | `[count, mood, friends, foes, blacklist, contacts]`; 13-slot `FriendVoOutput` cards (id/name/sex/face/mood/level/type/online/job/mapId/count/order/stall) |
| 51001 | addFriends | complete+tested | one-sided directed row + target `51012` count + `51016` been-add card; mutual once the target adds back; `450001` missing, `450020` self, `450022` dup, `450023` blacklisted target, `450021` past the 30 cap |
| 51002 | delFriends | complete+tested | drops only the caller's directed row, answers `[1, targetId]`; missing link stays silent like Java |
| 51003 | addFoe | complete+tested | directed row + `51017` been-add; `450001` / `450040` self / `450042` dup |
| 51004 | delFoe | complete+tested | `[1, targetId]`; silent when absent |
| 51005 | addBlacklists | complete+tested | `[1, card]`, oldest evicted past 30 with a `51006 [1, evictedTarget]` notice; `450060` self, `450062` dup, `450063` target is a friend |
| 51006 | delBlacklists | complete+tested | `[1, targetId]`; silent when absent |
| 51007 | addContacts | complete+tested | bare card (not `[1, card]`), oldest evicted past 30 with a `51008` notice; self/missing/dup stay silent like Java |
| 51008 | delContacts | complete+tested | `[1, targetId]`; silent when absent |
| 51011 | updateRoleXinqing | complete+tested | `[1, text]` persisted to `friend_info`; same-text idempotent; over-48 answers `[0, 450030, old]`, illegal chars `[0, 450031, old]` |
| 51015 | roleFight | complete+tested | C> `[loserId, winnerId, mapId]`; winner +1 / loser -1 clamped to +/-999 with `51013` pushes, loser auto-added as a foe with a `51003` card when missing; friend/foe followers get the `450026-450049` outcome fan-out |

## Push-only (no inbound handler)

| ID | Java | Status | Notes |
| -- | ---- | ------ | ----- |
| 51010 | ONLINE_FRIEND | push-only | `[roleId, 1/0]` to online followers on login (`_friend_on_enter`) and disconnect (`_friend_on_disconnect`) |
| 51012 | CHANGE_FRIEND_COUNT | push-only | request counter to the target on every add, asserted in the peer outbox |
| 51013 | CHANGE_FOE_COUNT | push-only | `[targetId, count, +/-1]` on each counted spar |
| 51014 | CHANGE_ROLE_INFO | push-only | `[roleId, -1, mapId, null]` map-change notice via `change_map` |
| 51016 | BEENADD_FRIEND | push-only | requester card to an online target on add |
| 51017 | BEENADD_FOE | push-only | requester card to an online target on foe-add |

## Relationship state (SQLite, all genuine records)

- `role_friend` / `role_foe` / `role_blacklist` / `role_contacts` hold
  one-sided directed rows; `role_foe` carries `foe_count`, clamped at
  +/-999 in the same write (`friend_touch_foe_tx`).
- Adds run in one `BEGIN IMMEDIATE` transaction with oldest-first
  eviction at the 30 cap, so concurrent adds of the same pair leave
  exactly one row (pinned by a two-thread test).
- `friend_info` holds `xinqing` mood text and the `friend_count`
  request counter, upserted, surviving reconnect and restart.
- Deletion is directed: removing a friend drops only the caller's row;
  the reverse side keeps its own until it deletes too.
- Login presence (`StageRegistry.mark_online/mark_offline`) is
  placement-independent, so online/offline/map notifies reach followers
  even before the role steps onto a stage.

## Python deliberate deviations (documented)

- Single-target commands accept a bare role-id string or a 1-list;
  Java clients send the bare form.
- The eviction notice names the evicted *target role*, not the internal
  link row.
- `51015` with an unresolvable loser/winner stays silent; Java's
  failure outputs have no ported trigger here.
- Whisper (12200) does not consult the blacklist: no Java
  whisper-side check was found, so none was invented.

## Gaps

- None in the 17-ID family: 11 inbound complete+tested, 6 push-only.

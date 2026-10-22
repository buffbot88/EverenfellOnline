# Java-to-Python Game Server Parity Audit

**Status:** Initial evidence-backed audit; not a certification of full parity or a complete security review.

## Executive conclusion

The Python server is not currently a Java-server replacement. The Java server is a mature game backend with dozens of command modules and substantial persistent/config-driven world behavior; Python now has persisted role-stage/stat/currency fields and role settings, but still lacks the server-pushed map bootstrap and scene simulation. The latest projector run connected through login, enter-world, map change, and periodic heartbeat without disconnecting, but the Python server log shows no scene-bootstrap replies and there is no evidence yet that the world rendered. The mismatch is therefore not a single arithmetic bug.

Recommended route: retain Java as the production gameplay authority while the new web/client stack is integrated, and migrate game capabilities into Python incrementally. Keep Java/MySQL as the behavioral oracle until a subsystem passes packet, persistence, and desktop-client parity tests. Do not remove Java or switch the default client to Python on the basis of current tests.

## Evidence gathered

- Extracted jar inventory: **71 `*Commands.class` modules, 81 `*Action.class` classes, and 271 `*ServiceImpl.class` classes** under `com/xianling/bus`.
- Python's [protocol.py](../Server-v1/game/protocol.py) has a basic signature-checked login/role list, role-backed `10003` enter-world and `20000` map replies, SQLite-backed `32010`/`12011` values, and a `13000` role-settings reply. Several unrelated command handlers remain zero/empty placeholders; `10002` role creation has validation and success replies but its success reply is not yet captured on the wire. These are command dispatch coverage, not gameplay parity.
- The fresh projector run at 2026-10-08 03:01 UTC reached `10001`, `10003`, `20000`, then initialization commands and repeated `19001` heartbeats. It remained connected for at least a minute. The server log did not show a `13000` request during that run, and the Python implementation at that time did not handle Java's `21000`/`23002`/`23009` map bootstrap. The screen/render outcome was not observable from the available process logs. Python now pushes the evidence-backed `13000` and `32010` frames after successful single-role login, and implements the captured `21000` scene-entry confirmation for map 5; both are covered by tests but have not been exercised in a fresh desktop run.
- The original-stack tap captured **727 decodable server messages across 24 command IDs** in one live session. Frequent world traffic included `42100` (238), `42001` (131), `12004` (130), `42002` (118), and `40000` (43); also `42005`, `23002`, `43000`, `12001`, `12030`, `24002`, `42102`, plus login/entry messages. The client moved in the scene and server state changed during the capture.
- Genuine Java replies for role `fu0UR1-0-1-1` established map **5**, coordinates **44,33** in the captured enter-world packet (coordinates changed during play), level **56**, exp **10,692,892**, job/face `C`, HP/max HP **5,226/5,466**, MP/max MP **1,811/1,811**, tongqian **4,509,290**, bound lingshi **360**, and user lingshi **9,986,377**. Python now reads role stage/stat/currency fields and has an owner-scoped SQLite `role_settings` table; tests cover captured state values. The latest desktop run confirms command progression, not rendered scene parity.
- The Java stream's scene bootstrap continues after entry: `21000`, `23002` (monster snapshot), `23009` (mount/actor data), `12004`/`12005`/`12050`/`12000` (stats/resources), `42100` (buffs), and tile/entity updates such as `40000`, `42001`, and `42002`. Python now handles `21000` for map 5 using the observed `[1, lineNo, mapType]` response and the original MapLine config's map type; it does not yet simulate the selected line or send scene population. `23002` is emitted by Java's AOI listener as monsters enter visibility, so its records represent live stage state rather than simply the static spawn config. Python now decodes `monster.mm` and sends one `23002` record per spawn point inside the role's AOI box on scene entry (`game/config.py` `monster_snapshot`, template stats from `sys_config/GuaiWuBiao.jat`; box |dx|<=9, |dy|<=6 from the stage `aoi_width/height` of 600x400 px). NPCs in the same box come from `sys_config/NpcLieBiao.jat` as `23003` `[npcId, x, y]` records (a map-2 entry sends exactly `N020001`, byte-identical to Java). This is still a static spawn snapshot: it does not track live positions, respawn timers, or the unverified record flags (indices 10, 13-17). Python now also sends the mount frame `23009` from `role_stage.zuoqi_info` plus `sys_config/ZuoJiBiao.jat` (pet level clamped by `maxlv`, maxHp from `meinvhp`, position from the `AExtendOffs` surround search over `path.mm`; details in [mount-23009-recovery.md](mount-23009-recovery.md)), and answers inbound `12102`. The replay harness scores `23009` against the capture with only the equipment-dependent speed field differing, and the full entry sequence is now `match=9 diff=3 missing=0` (two diffs are the unmigrated equipment bonuses; the third is the `10003` recharge pair, whose recharge rows are not migrated, so fresh roles correctly report `[0.0, 0.0]`). The tap decoder currently consumes the legacy capture completely (client 10,463/10,463 bytes; server 40,103/40,103 bytes) and decodes the `13000` ByteArray and later messages.
- World-entry stats tail now ported from bytecode + tap: after `12004` Python pushes `12050` (zhenqi + level cap from `ZhuJueShuXingBiao.jat`), `12005` (shanbi value), and `12000` (attribute map from `game/attributes.py`: level row + migrated gear/dan/xianjie/chenghao/meiren/zuoqi bags through the Java formulas, VIP buff effect slots; exact on all eight slots for the captured role) in the fresh-capture order, and the `10001` TimeZone slot matches the capture exactly (`{'rawOffset': -18000000, 'ID': 'America/New_York'}`; `--tz-offset`/`--tz-id` override). Inbound `12000` (`StageInfoAction.info`) is answered, and `zhenqi`/`shengwang` are persisted characters columns the migrator copies. `tools/world_entry_replay.py` scores the whole world-entry sequence **match=9, diff=3, missing=0** (see previous bullet and [mount-23009-recovery.md](mount-23009-recovery.md): `23009` is ported; two diffs are the unmigrated equipment bonuses — the six equipment-dependent `12000` bonuses and the equipment-dependent `23009` speed field — and the third is the unmigrated recharge pair in `10003`).
- The Java client/server exchange proceeds to stage changes and then sustained actor, monster, movement, combat/stat, and buff messages. Returning syntactically valid empty arrays for a few startup commands cannot reproduce this world state.

## Parity matrix

| Area | Current Python status | Audit finding |
|---|---|---|
| Web login/session | Implemented basic login/register/session API; PBKDF2 passwords and SQLite sessions | Partial replacement of PHP behavior. Needs endpoint/edge-case compatibility and security review. |
| Socket framing, policy, key exchange | Implemented and exercised | Strongest parity area; retain captured vectors and add stream tests. |
| Sign-in command `10001` | Implemented against observed envelope and role-array layout | Basic behavior works. Sign is now HMAC-SHA256 with a server secret (`MKO_SIGN_SECRET`, else per-process random) and a 300s freshness window; the legacy MD5 is rejected. Live-client login not re-verified after this change. |
| Role creation `10002` | Validation and error codes ported from bytecode + live capture; success shape matches `CreateRoleOutput` | Name rule (CJK-only, no s/S start) ported from `NameFieldCheck.checkInputName2`; 2001/2002/2005 match `RoleErrorCode`. Gaps: sensitive-word list has no portable equivalent; Java stores names with a server prefix (`s0.`-style) which Python does not; starter map/stats are not in `roleInit` (source unresolved); success reply never captured on the wire. |
| Enter-world `10003` | Reads persisted role stage/stat fields; Java-like response shape | Basic state-backed behavior tested; requires broader Java packet parity. |
| Map change `20000` | Reads role-owned map/coordinates | Basic state-backed behavior tested; scene transition/bootstrap is missing. |
| Role settings `13000` | Relays four persisted settings fields including ByteArray | Producer traced; exact panel bytes imported/tested; fresh projector run did not log this request. |
| Scene entry `21000` | Captured response `[1, 1, 1]`; map type sourced from original config; `20000` answers bare (the client sends `21000` when ready — pushing `21000` unprompted wedged the projector); `21000` pushes the AOI scene `23003`, `23002` (in-range spawns only) + born-flag `40000` tiles, `23009`, `12004`, `12050`, `12005`, `12000`, `42100` | No dynamic line allocation; population is config-backed without live positions, movement, or respawn timers. |
| Account/currency, mall, VIP, role stats, mounts, dungeons | `12010` sends the bytecode-verified 25-slot fight layout (skill/kangxin slot [2] from `role_skill` + JiNengBiao, shenjiang still 0) with `ZhanLiXiShu` values for level/gear/dan/vip plus the zuoqi slot `[193, 0, 0]` from `role_zuoqi.rank` (mount-gear/longhun 0: no legacy rows/goods; other systems 0: sources unmigrated); `62000` sends `GetVipOutPut`'s Object[5] from migrated `role_vip`; `62006` stamps `role_vip.prop_use_time` in milliseconds after the `tody_prop_value` update, as `VipServiceImpl.addPropValue` does (`tools/javap.py`), and `62003` pushes only on a level change; `32000` stays silent on empty category, else `[1, sign, raw WuPinChuShouBiao rows]` with the gameconfig-published sign (and `[-1, category]` when the client's sign matches, per `MallServiceImpl.shopList` bytecode); buyback `32002` sells the whole stack for recycle x count YXB (evicting the oldest past 27 rows with a `32005` push), `32003` buys back for the same price (`1003`/`1006` GeneralErrorCode gates, `430405` unknown-goods payload: all three ServiceImpl-only, excluded from the ledger), `32004` lists, `32006` stays null without the guild mall; vipqq `88003` answers `[1, minRecharge, flag, pic, qq]` from migrated `vip_qq`/`role_qq_list` (flag 2 claimed, 1 recharge reached, else 0; `794002` without config), `88004` grants `chaojihuiyuan.jat` parcels then claims (`794000` unbound, `794001` claimed, `430212` full bag), and `88005` pushes null on QQ bind like `vipQqOK` (`794000`-`794002` are VipQqErrorCode strings); prop gift-box
  inbound mount commands `33001` (panel: [1, [rank, clamped level, lucky,
  fight], [], kaifu, 0] with [0, [520005]] empty / [0, [520006]] unconfigured
  cases), `33000` (ride clamps curRank and pushes [roleId, rank]), and
  `33004` (free rank-1 claim, silent past the gate), and `33003` (jinjie:
  level/YXB gates, pill consume with specialtype substitutes and mall
  auto-buy, per-attempt cost-count banking, pity lottery with fail exp,
  success notice), tested in `tests/test_zuoqi.py` with `role_zuoqi`
  pity + `kaifu_data` columns; `33005` (fanhuan refund of the tracked
  spend, bind 1, guoqi-hour expiry, feed row), `33007` ([cost, feed]
  list), `33006` (kaifu meiren grant ahead of the `82001` push), and
  `33011` (claimable-now award ranks) and `33008` (mount fight total:
  jichu + mount-equip fight, longhun 0) are likewise tested there;
  meiren inbound `82000` (owned [[type, level, heti]] panel),
  `82001` (recruit with level/qiandao/item/zhenqi gates),
  `82002` (zhenqi level-up), and `82003` (zhenqi + YXB chanmian)
  are tested in `tests/test_meiren.py` against the real meiren.jat
  (82004 stays service-internal; the 11101 obtain broadcast is not
  emitted; qiandao reads 0 so two types stay ungated-blocked);
  longhun stays unported (33010/33012 are service-internal with no
  inbound route; the prop-use flow that feeds attribute goods is
  unported). Prop
  gift-box
  selection `30305`/`30306` consume one box, check YB then bag space, and
  push `30304` [configId, [[goodsId, count]]] ahead of `[1, bagId]`
  (`1005`/`1002`/`1006` gates, `100009`/`100008` take errors, silent
  unknown boxes/choices), `30307` answers the daily RoleProp use count
  (stale-day reset, 0 when missing), and `30303` stays unrouted (no
  handler jar-wide); `35011` reads `characters.recive_yb`; `64001` sends the fresh-row `[1, [0, None, None, None]]`; `64010` sends null; `111000` sends per-type mocks + 0 fragments from `ZuWuShuxing.jat`; `108001` sends the fresh-row `[1, [0, [['1', 0, 1]], None]]` (per `ZuwufubenServiceImpl.getInfo` bytecode; no `role_zuwufuben` table is migrated); `31000` sends `getInfoEquip`'s 18-field records from `role_equip` (zhanli and qh star/affix fields traced; slot 1 id, count, bind and expiry are approximated since the legacy row lacks them); `19000` answers `5000 + nextInt(5000)`; inbound mount info `12102` answered from `zuoqi_info` + `ZuoJiBiao`, and `23009` pushed at scene entry | Shapes alone do not implement Java service rules, configs, persistence, or side effects. `12102`'s skills/clothes/zhanli/skillBook slots stay null/0 because their source tables (`role_zuoqi_skill` etc.) are not migrated. `12010`'s remaining systems need their tables (meiren, xianjie, skills…); see [server-roadmap.md](server-roadmap.md). |
| Scene actors/maps/combat/buffs | Combat loop ported (Phase 3): client-relayed `42002` resolves Shanghai/T21 damage (capture goldens 1649/2474/30/100), persists role HP/exp, and emits the bytecode order `12004`/`42100`x2/`43000`/`42002` + `12001`/`12030` per kill; `24002` leave wired: the asheslast timer in `ai_tick` emits it, covered by `test_ai` kill->leave->respawn. Movement (`42001`) decoded, `23002`/`23009`/`12000` derived at entry, `53021` still logged | Monster AI/respawn (Phase 4: hatred retaliation, chase/leash moves, pet mirror-fire + follow, asheslast/creattime leave->respawn) now server-driven off role actions; remaining gaps are wander behavior, per-monster heartbeat stagger (one clock per Session.tick; helpers in game/scheduler.py), pet teleport, boss/summon AI, drops, and the documented formula gaps (heals, resists, MP costs, level-ups). 27 captured IDs are a lower bound, not a complete command inventory. |
| Task systems: taofa `50101`-`50105`, richang `50201` | Taofa: 90-row `taofaid` config loaded; list/receive/absorb/monster-change handlers and per-role state implemented and unit-tested (25 tests in `tests/test_taofa.py`), with no live client capture yet. Richang: `50201` creates or reuses the role's row and rolls its three configs (level 40 gate), tested in `tests/test_richang.py`. | Richang `50202`-`50209` handlers are implemented; `tests/test_richang.py` covers the money, VIP and state gates of 50202, 50204, 50205, 50206 and 50209, plus the 50203 re-roll (short money, max-thick reject, 50000 YB charge), the 50208 kill-progress emit, and the 50207 pay-out (row settles, reward jb credited). The ledger still lists the range as dispatched. The MySQL migrator does not copy `task_taofa` or `task_richang` because the Java reference has no schema for them. Shapes are not confirmed against the original client. |
| Persistence | SQLite accounts, sessions, character stage/stats/currencies, per-role UI settings, equipped gear (`role_equip`), attribute pills (`role_attr_buff`), VIP rows (`role_vip`), title id lists (`role_xianjiechenhao`), owned meiren (`role_meiren`), mount ranks (`role_zuoqi`), sold-item buyback rows (`role_bag_buyback`),
  and special-type prop use counts (`role_prop`), mount kaifu state
  (`role_zuoqi.kaifu_data`) and the global refund feed (`zuoqi_fanhuan`);
  the requested stage (`20000`) and reported movement (`42001`) now
  persist to the role row | Buffs, progression, mount skills/goods state, jiangxingtu activation, and other domain state remain missing. |
| Data/config | Python loads `MapLine.jat` (map types), `map_config/<id>/monster.mm` (spawn points), and `GuaiWuBiao.jat` (monster stats) | Map definitions beyond map type, NPC spawns, the other config tables, and formulas are not reproduced. Four spawn ids (`D100019`, `D100020`, `D100021`, `G100070`) have no template row and are skipped. |
| Security | PBKDF2 for passwords; HMAC-SHA256 game sign with freshness window; `mko_session` is HttpOnly + SameSite=Strict; per-IP login rate limit (5 failures / 300s); role reads/writes scoped to the authenticated account and server | Still not for internet exposure: no TLS (Secure flag omitted on loopback HTTP), no CSRF/origin check, no session expiry. |

## Security risks to address before public deployment

These are review findings from inspected code, not an exhaustive penetration test:

1. Fixed: socket sign was `md5(uid + 'xianlingkey' + timestamp)` (public key, no freshness). It is now HMAC-SHA256 over `uid|timestamp` with a server secret and a 300s window; `tests/test_security.py` covers it. Remaining: the sign is still a bearer token for 300s, so TLS is needed off loopback.
2. Partly fixed: `mko_session` now sets `HttpOnly` and `SameSite=Strict` (`web.session_cookie`). `Secure` is omitted because the server speaks plain HTTP on loopback; add it with TLS. Session expiry/revocation is still missing.
3. Audited: mutating role commands resolve roles only from `get_roles(authed_user, server_id)`, and `get_role_settings`/`save_role_settings` require `account` and `server_id` in the SQL `WHERE`. Foreign role ids are rejected by tests. Each new mutating command still needs the same scoping.
4. Fixed: failed web logins and registrations are limited to 5 per client IP per 300s (`web.FailLimiter`, HTTP 429). Game-socket commands have no rate limit yet.
4. Password reset was performed directly in local SQLite during troubleshooting. No public password-reset/admin workflow or audit trail is included in the Python service.

## Recommended migration strategy

### Stage 0 — freeze the oracle and improve evidence tooling

Keep Java/MySQL runnable, preserve known-good original boot, and capture reproducible signed-in sessions. The tap decoder now handles captured TCP stream framing, AMF ByteArray (`0x0c`), and multiple envelopes in a frame; retain the raw capture and continue recording command, request/response shape, state changes, and required config/database rows. The current 727-message trace is evidence, not a full protocol specification. `tools/oracle-diff.py` now replays a command list against both servers — Java with the legacy forged socket sign, Python through its own `gamesession.php` — and prints the first differing field, or a missing reply, per command. It also diffs the server-initiated push stream collected after world entry: ids present on one side only, and the payload of commands that arrive once on each side (repeated timed pushes are compared by presence only). Each reply is compared the same way against the notifications that arrived before it and within `--notify-window` seconds after it; those baseline keys are `<trigger>:<pushed>`. The window also catches timed updates that were not caused by the command, so a diff there needs the same judgement as a push diff. Known noise lives in `tools/oracle-baseline.json`, which has a `push` and a `reply` section (each an `ignore` list plus recorded diffs); it currently holds the `12004` HP difference and the volatile `42100` buff id. `--write-baseline` records observed diffs, so new or changed diffs still fail the run. Run it against every ported handler before trusting a golden test.

`tools/ci-oracle-diff.py` wraps that in a gate: it starts the legacy MySQL 5.1 and Java oracle itself when their ports (3306, 8008) are idle — `mysqld` with explicit `--basedir/--datadir` because `my.ini` hardcodes the original `D:\` install, Java with the `server.bat` flags minus the GC log — and reuses a stack that is already listening, stopping only the processes it started (`mysqladmin shutdown` for MySQL, `--no-start-stack` to refuse booting, `--keep-stack` to leave a booted stack up). It then creates a temporary SQLite DB from the Server-v1 schema, migrates the `stress` account from the legacy MySQL, starts a throwaway Python server on free loopback ports (random sign secret, password passed to the diff in the environment, never argv), runs the diff with `tools/oracle-baseline.json`, and exits 0 only when every reply, push and notification matches or is baselined. Exit 1 marks an unbaselined diff; exit 2 means the environment was not ready (stack binaries missing, boot, migration or startup failure). One command now reproduces the CI job locally, and the workflow contains no boot steps of its own. Default commands are `50001` and `35011`; `--cmd` widens coverage. `.github/workflows/oracle-diff.yml` runs it on pushes to main, nightly and on dispatch. Pull requests get it only when the `ORACLE_RUNNER` repository variable names a runner where the legacy stack is staged, because the JRE 6 launcher, `dntg_start.jar` and MySQL 5.1 are gitignored binaries that a clean hosted checkout does not contain.

### Stage 1 — playable core vertical slice

Role-stage persistence, role settings storage, and basic `10003`/`20000` replies are in place and tested. Python also emits the tested successful-login sequence `10001`, `13000`, `32010` and a map-5 `21000` scene-entry confirmation. Exercise these changes with a fresh desktop connection. The NPC snapshot (`23003`), the AOI-filtered `23002`, and inbound `12102` are now ported alongside the mount pet `23009` and the stat/buff packets. Compare complete normalized packet sequences with Java and test the same desktop client against both backends. Do not use zero-filled stubs for required state.

### Stage 2 — capability-by-capability migration

For each command module: trace command constants and action routing; inspect service implementation, output wrappers, DAOs/entities, config inputs, and SQL; create golden request/reply/state-transition tests; port transactionally; validate behavior against Java. Migrate core movement, combat, inventory/equipment, currency, quests/progression, and account systems before secondary events/social/GM modules.

### Stage 3 — hardening and cutover

Threat-model the protocol and web surface, validate ownership/isolation and replay protection, add rate limiting/auditability, and run protocol fuzzing plus multi-account persistence tests. Cut over only after an explicit supported-feature matrix and regression suite pass. “100%” needs a defined scope: all 71 command modules and the supporting config/data, not just the commands observed in one session.

## Recommendation

Use a **hybrid now, parity migration over time**. Let the new web/frontend stack coexist with Java for gameplay while the Python server is built as a drop-in replacement in measured slices. Replacing Java immediately with current Python will not render the world; trying to clone all 71 modules in one step is high risk and cannot be validated as a single change.

## Client commands with no Python handler (2026-10-19)

Measured from the Java capture `output/orig-stack/session-20261018-195420.log` (conn 2, 180 client commands) against `Server-v1/game/protocol.py`. The Python session (`session-20261018-204822.log`) sent only 15 client commands and stopped at `108001`, so the commands below appear only after map entry (`21000`).

Fifteen client commands the Java client sends have no Python handler:

| Command | Java class (`docs/java-command-map.md`) |
|---|---|
| 81000 | `gonghuitask` `getTaskRichangeInfo()` |
| 83008 | `stage.husong` `getDaJieCount()` |
| 86003 | `toubao` `getToubaoInfo()` |
| 97001 | `xunbao` `roleinfo()` |
| 105000 | `dafuwong` `getDaFuWongInfo()` |
| 105003 | `dafuwong` `getClientData()` |
| 107000 | `zyzhuihui` `getinfo()` |
| 114000 | `shenmizhuanpan` `getConfig()` |
| 127000 | `loginlibao` `getConfig()` |
| 41000 | `shenjiang` `getShenjiangInfo()` |
| 41023 | `shenjiang` `getInfo()` |
| 58000 | `lvlibao` `laQuLvLiBao()` |
| 58003 | `jiangli` `getOnlineTimeRewardInfo()` |
| 58011 | `jiangli` `getQiandaoInfo()` |
| 63001 | `email` `list()` |

Most of the Java session's client commands are answered by handlers that Python already has. The one that gates these is `21000`, which Python never receives. Until that is fixed, these handlers cannot be exercised in the Python stack.

### Correction to batching (2026-10-19)

- `114000` (`shenmizhuanpan` `getConfig`) is not a plain config read. `ShenmizhuanpanServiceImpl.getConfig` returns a formatted list only when the event is in its time window. Otherwise it returns a placeholder built by `mockThings`, and when the window is open it reads per-role state (`getRoleShenmizhuanpan`, creating the row if missing) and time bounds. It needs the role table and time config, not just config tables.
- So the 15 handlers can't be batched by "config only". Each needs its own read of the Java service before implementation.
- Source: `reference/TonNgoKhong/server/dntg_start.jar`, read with `tools/javap.py`.

### Handler complexity survey (2026-10-19, read-only)

Read from `reference/TonNgoKhong/server/dntg_start.jar` with `tools/javap.py`; full listings in `output/swfdec/trace/handler_survey.txt`. "Lines" is bytecode lines of the service method, a rough size proxy.

| Batch | Command | Service method | Lines | Storage | Config refs | Time-gated |
|---|---|---|---|---|---|---|
| 1 | 105003 | `dafuwong.getClientData` | 48 | none | 0 | no |
| 1 | 41023 | `shenjiang.IShenJiangSlotService.getInfo` | 71 | none | 0 | no |
| 1 | 58011 | `jiangli.getQiandaoInfo` | 57 | cache | 0 | no |
| 1 | 58000 | `lvlibao.laQuLvLiBao` | 61 | cache | 0 | no |
| 1 | 105000 | `dafuwong.getDaFuWongInfo` | 61 | cache | 0 | no |
| 1 | 107000 | `zyzhuihui.getInfo` | 85 | cache | 0 | no |
| 2 | 81000 | `gonghuitask.getTaskRiChang` | 97 | none | 6 | no |
| 2 | 127000 | `loginlibao.getConfig` | 83 | cache | 6 | no |
| 2 | 97001 | `xunbao.getXunbaoRoleInfo` | 99 | cache | 4 | yes |
| 2 | 58003 | `jiangli.getOnlineRewardInfo` | 122 | cache | 6 | yes |
| 2 | 41000 | `shenjiang.getRoleShenjiang` | 128 | cache all | 3 | no |
| 3 | 86003 | `toubao.getToubaoInfos` | 131 | paged DB | 0 | no |
| 3 | 63001 | `email.list` | 293 | DB and cache writes | 0 | yes |
| 3 | 83008 | `husong` (`getDaJieCount`) | not read | unknown | unknown | unknown |

- The heuristics are rough. A low line count doesn't guarantee an easy handler, and the time flag only means the code mentions a time type.
- `83008` lives under `com/xianling/stage/husong`, not `bus`, so the first lookup missed it. It needs its own read.
- Batch 1 has Java replies in the capture (`output/swfdec/trace/replies.txt`) for every command in it, so each can be checked against the oracle.

### 105003 progress (2026-10-19)

- Reply shape from the Java capture: `['105003', [sign, [{itemtype, id, icon, item, diban}, ...]]]`. The full reply is in `output/swfdec/trace/reply105003.txt`.
- The sign is verified. It is the MD5 of three `gameconfig` `.jat` files in order: `dafuwengzhubiao-1390186829068`, `dafuwengduihuan-1394171020776`, `dafuwengguanggao-1390194975618`. The concatenation equals the captured 96-hex-character sign.
- Implemented (`dafuweng_info` in `game/protocol.py`, `dafuweng_reply` in `game/config.py`). The sign and the row sets match the capture, and `tests/test_config.py` pins both. Open: row order differs from Java's capture (file order is used), and a missing table sends no reply, not Java's zero-array fallback.

### 41023 progress (2026-10-19)

- Java path: `ShenjiangAction.getInfo` calls `ShenJiangSlotServiceImpl.getInfo(roleId, id)`, which answers `[1, id, slots]`. Slots come from `role_shenjiang_slot` and are null when there are no rows.
- The legacy `role_shenjiang_slot.MYD` is 0 bytes, so every role's slot list is null. The captured replies agree (`sj0101`, `sj0199`, `sj0202`).
- Implemented as `shenjiang_slot_info` in `game/protocol.py`: always null slots, a non-string id is silent. Tested in `tests/test_protocol.py`. Limit: if slot rows are ever written, this must read them.

### 58011 progress (2026-10-19)

- Java path: `JiangliAction.getQiandaoInfo` → `JiangliServiceImpl.getQiandaoInfo(roleId)`. A missing `RoleQiandao` gives `[1, null, 0, null, null]`; a row is formatted by `QiandaoOutput.getQiandaoInfo`.
- Row format from the bytecode: `[1, toInteger(monthQiandao), totalQiandaoCount, toString(monthQiandaoReward), toString(totalQiandaoReward)]`. Both helpers split on `,`; a null or empty column becomes an empty array (not null), and `toInteger` maps each element through `Integer.parseInt`.
- The live MySQL `role_qiandao` has exactly one row, `fu0UR1-0-1-1`: `total_qiandao_count=1, month=10`, and all three list columns are `''`. So Java's answer for that role is `[1, [], 1, [], []]`.
- Implemented both branches in `qiandao_info` (`game/protocol.py`), backed by the new `role_qiandao` SQLite table (`db.Store.get_role_qiandao/save_role_qiandao`) and a migration copy in `tools/migrate_mysql_to_sqlite.py`. Tested in `tests/test_protocol.py` (captured no-row reply, the real legacy row's empty-list shape, and dispatch through `handle`).
- The earlier capture only held the no-row answer, so the row branch was checked against the original server directly (2026-10-19). `tools/java_probe.py`'s world-entry replay as account `111111` / role `fu0UR1-0-1-1`, followed by `58011 [null]`, got `['58011', [1, [], 1, [], []]]` — identical to Python's reply for the migrated row. Raw capture: `output/orig-stack/java-58011-row-20261019-231702.log`; decoded line: `output/swfdec/trace/reply58011-row.txt` (script: `output/swfdec/trace/capture_58011_row.py`).

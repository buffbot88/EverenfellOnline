# Java-to-Python Game Server Parity Audit

**Status:** Initial evidence-backed audit; not a certification of full parity or a complete security review.

## Executive conclusion

The Python server is not currently a Java-server replacement. The Java server is a mature game backend with dozens of command modules and substantial persistent/config-driven world behavior; Python now has persisted role-stage/stat/currency fields and role settings, but still lacks the server-pushed map bootstrap and scene simulation. The latest projector run connected through login, enter-world, map change, and periodic heartbeat without disconnecting, but the Python server log shows no scene-bootstrap replies and there is no evidence yet that the world rendered. The mismatch is therefore not a single arithmetic bug.

Recommended route: retain Java as the production gameplay authority while the new web/client stack is integrated, and migrate game capabilities into Python incrementally. Keep Java/MySQL as the behavioral oracle until a subsystem passes packet, persistence, and desktop-client parity tests. Do not remove Java or switch the default client to Python on the basis of current tests.

## Evidence gathered

- Extracted jar inventory: **71 `*Commands.class` modules, 81 `*Action.class` classes, and 271 `*ServiceImpl.class` classes** under `com/xianling/bus`.
- Python's [protocol.py](../Server-v1/game/protocol.py) has a basic signature-checked login/role list, role-backed `10003` enter-world and `20000` map replies, SQLite-backed `32010`/`12011` values, and a `13000` role-settings reply. Several unrelated command handlers remain zero/empty placeholders; `10002` remains unimplemented. These are command dispatch coverage, not gameplay parity.
- The fresh projector run at 2026-10-08 03:01 UTC reached `10001`, `10003`, `20000`, then initialization commands and repeated `19001` heartbeats. It remained connected for at least a minute. The server log did not show a `13000` request during that run, and the Python implementation at that time did not handle Java's `21000`/`23002`/`23009` map bootstrap. The screen/render outcome was not observable from the available process logs. Python now pushes the evidence-backed `13000` and `32010` frames after successful single-role login, and implements the captured `21000` scene-entry confirmation for map 5; both are covered by tests but have not been exercised in a fresh desktop run.
- The original-stack tap captured **727 decodable server messages across 24 command IDs** in one live session. Frequent world traffic included `42100` (238), `42001` (131), `12004` (130), `42002` (118), and `40000` (43); also `42005`, `23002`, `43000`, `12001`, `12030`, `24002`, `42102`, plus login/entry messages. The client moved in the scene and server state changed during the capture.
- Genuine Java replies for role `fu0UR1-0-1-1` established map **5**, coordinates **44,33** in the captured enter-world packet (coordinates changed during play), level **56**, exp **10,692,892**, job/face `C`, HP/max HP **5,226/5,466**, MP/max MP **1,811/1,811**, tongqian **4,509,290**, bound lingshi **360**, and user lingshi **9,986,377**. Python now reads role stage/stat/currency fields and has an owner-scoped SQLite `role_settings` table; tests cover captured state values. The latest desktop run confirms command progression, not rendered scene parity.
- The Java stream's scene bootstrap continues after entry: `21000`, `23002` (monster snapshot), `23009` (mount/actor data), `12004`/`12005`/`12050`/`12000` (stats/resources), `42100` (buffs), and tile/entity updates such as `40000`, `42001`, and `42002`. Python now handles `21000` for map 5 using the observed `[1, lineNo, mapType]` response and the original MapLine config's map type; it does not yet simulate the selected line or send scene population. `23002` is emitted by Java's AOI listener as monsters enter visibility, so its records represent live stage state rather than simply the static spawn config. The map-5 `monster.mm` uses AMF3 markers beyond Python's current codec; do not synthesize the monster list until those data and runtime rules are understood. The tap decoder currently consumes the legacy capture completely (client 10,463/10,463 bytes; server 40,103/40,103 bytes) and decodes the `13000` ByteArray and later messages.
- The Java client/server exchange proceeds to stage changes and then sustained actor, monster, movement, combat/stat, and buff messages. Returning syntactically valid empty arrays for a few startup commands cannot reproduce this world state.

## Parity matrix

| Area | Current Python status | Audit finding |
|---|---|---|
| Web login/session | Implemented basic login/register/session API; PBKDF2 passwords and SQLite sessions | Partial replacement of PHP behavior. Needs endpoint/edge-case compatibility and security review. |
| Socket framing, policy, key exchange | Implemented and exercised | Strongest parity area; retain captured vectors and add stream tests. |
| Sign-in command `10001` | Implemented against observed envelope and role-array layout | Basic behavior works, but legacy MD5 sign is forgeable/replayable and role data is incomplete. |
| Role creation `10002` | Explicitly unimplemented | Missing workflow and original constraints/side effects. |
| Enter-world `10003` | Reads persisted role stage/stat fields; Java-like response shape | Basic state-backed behavior tested; requires broader Java packet parity. |
| Map change `20000` | Reads role-owned map/coordinates | Basic state-backed behavior tested; scene transition/bootstrap is missing. |
| Role settings `13000` | Relays four persisted settings fields including ByteArray | Producer traced; exact panel bytes imported/tested; fresh projector run did not log this request. |
| Scene entry `21000` | Map-5 captured response `[1, 1, 1]`; map type sourced from original config | No dynamic line allocation or map types beyond map 5 yet; does not populate the scene. |
| Account/currency, mall, VIP, role stats, mounts, dungeons | Mostly zero/null/empty stubs | Shapes alone do not implement Java service rules, configs, persistence, or side effects. |
| Scene actors/maps/combat/buffs | Not implemented | High-volume Java functionality required for a live scene; 24 captured IDs are a lower bound, not a complete command inventory. |
| Persistence | SQLite accounts, sessions, character stage/stats/currencies, per-role UI settings | Equipment, buffs, mount, progression, and other domain state remain missing. |
| Data/config | No equivalent runtime loading of the Java game's configuration set in Python | World population, map definitions, assets/config IDs, monster/NPC spawns, and formulas are not reproduced. |
| Security | PBKDF2 used for local passwords; game sign mirrors legacy MD5 scheme | Do not expose as an internet-facing service without a dedicated threat review and a compatible hardening design. |

## Security risks to address before public deployment

These are review findings from inspected code, not an exhaustive penetration test:

1. Socket authentication is `md5(uid + 'xianlingkey' + timestamp)`. The key is embedded/public legacy protocol material, with no freshness window checked in the Python handler; a valid sign can be forged/replayed. Preserve legacy compatibility only behind a trusted boundary until an authenticated replacement protocol is designed.
2. HTTP sessions use an `mko_session` cookie without `HttpOnly`, `Secure`, or `SameSite` attributes in the inspected setter. The current server binds loopback by default, but changing that boundary requires TLS, cookie flags, origin/CSRF protection, rate limits, and session expiry/revocation.
3. No demonstrated role ownership authorization beyond filtering `get_roles(account, server)` is enough to establish complete command-level authorization; each mutating game action will need explicit authenticated role/session ownership checks.
4. Password reset was performed directly in local SQLite during troubleshooting. No public password-reset/admin workflow or audit trail is included in the Python service.

## Recommended migration strategy

### Stage 0 — freeze the oracle and improve evidence tooling

Keep Java/MySQL runnable, preserve known-good original boot, and capture reproducible signed-in sessions. The tap decoder now handles captured TCP stream framing, AMF ByteArray (`0x0c`), and multiple envelopes in a frame; retain the raw capture and continue recording command, request/response shape, state changes, and required config/database rows. The current 727-message trace is evidence, not a full protocol specification.

### Stage 1 — playable core vertical slice

Role-stage persistence, role settings storage, and basic `10003`/`20000` replies are in place and tested. Python also emits the tested successful-login sequence `10001`, `13000`, `32010` and a map-5 `21000` scene-entry confirmation. Exercise these changes with a fresh desktop connection. Then decode original map data and implement the initial scene's config-backed actor/monster/NPC snapshot plus required stat/buff packets. Compare complete normalized packet sequences with Java and test the same desktop client against both backends. Do not use zero-filled stubs for required state.

### Stage 2 — capability-by-capability migration

For each command module: trace command constants and action routing; inspect service implementation, output wrappers, DAOs/entities, config inputs, and SQL; create golden request/reply/state-transition tests; port transactionally; validate behavior against Java. Migrate core movement, combat, inventory/equipment, currency, quests/progression, and account systems before secondary events/social/GM modules.

### Stage 3 — hardening and cutover

Threat-model the protocol and web surface, validate ownership/isolation and replay protection, add rate limiting/auditability, and run protocol fuzzing plus multi-account persistence tests. Cut over only after an explicit supported-feature matrix and regression suite pass. “100%” needs a defined scope: all 71 command modules and the supporting config/data, not just the commands observed in one session.

## Recommendation

Use a **hybrid now, parity migration over time**. Let the new web/frontend stack coexist with Java for gameplay while the Python server is built as a drop-in replacement in measured slices. Replacing Java immediately with current Python will not render the world; trying to clone all 71 modules in one step is high risk and cannot be validated as a single change.

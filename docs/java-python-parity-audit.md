# Java-to-Python Game Server Parity Audit

**Status:** Initial evidence-backed audit; not a certification of full parity or a complete security review.

## Executive conclusion

The Python server is not currently a Java-server replacement. The Java server is a mature game backend with dozens of command modules and substantial persistent/config-driven world behavior; Python currently covers the web account flow, basic framing/handshake, login, a provisional enter-world reply, and a small set of command stubs. Java was observed rendering and simulating the world using the same desktop client, while the Python client remained black. The mismatch is therefore not a single arithmetic bug.

Recommended route: retain Java as the production gameplay authority while the new web/client stack is integrated, and migrate game capabilities into Python incrementally. Keep Java/MySQL as the behavioral oracle until a subsystem passes packet, persistence, and desktop-client parity tests. Do not remove Java or switch the default client to Python on the basis of current tests.

## Evidence gathered

- Extracted jar inventory: **71 `*Commands.class` modules, 81 `*Action.class` classes, and 271 `*ServiceImpl.class` classes** under `com/xianling/bus`.
- Python's [protocol.py](../server/py/game/protocol.py) declares 15 command constants. Login (`10001`) has a working signature check and role list. `10003` and `20000` return provisional values. Several other declared commands return zero/empty placeholder data; `10002` remains unimplemented. These are command dispatch coverage, not gameplay parity.
- The original-stack tap captured **727 decodable server messages across 24 command IDs** in one live session. Frequent world traffic included `42100` (238), `42001` (131), `12004` (130), `42002` (118), and `40000` (43); also `42005`, `23002`, `43000`, `12001`, `12030`, `24002`, `42102`, plus login/entry messages. The client moved in the scene and server state changed during the capture.
- Genuine Java replies for role `fu0UR1-0-1-1` established map **5**, coordinates **45,31** in the database snapshot, level **56**, exp **10,692,892**, job/face `C`, HP/max HP **5,226/5,466**, MP/max MP **1,811/1,811**, tongqian **4,509,290**, bound lingshi **360**, and user lingshi **9,986,377**. The Python reply instead used map `0`, coordinates `57,148`, level `1`, zeroed values, and no stage/account tables. That is a direct semantic mismatch in the entry response.
- Immediately after login the Java stream also included a large `13000` response containing an AMF3 ByteArray marker (`0x0c`) and opaque binary payload. The current Python AMF3 reader does not support ByteArray; the tap decoder also does not yet reassemble/decode multiple AMF objects in one frame robustly. Do not fabricate this response: trace its producer and contents before implementing it.
- The Java client/server exchange proceeds to stage changes and then sustained actor, monster, movement, combat/stat, and buff messages. Returning syntactically valid empty arrays for a few startup commands cannot reproduce this world state.

## Parity matrix

| Area | Current Python status | Audit finding |
|---|---|---|
| Web login/session | Implemented basic login/register/session API; PBKDF2 passwords and SQLite sessions | Partial replacement of PHP behavior. Needs endpoint/edge-case compatibility and security review. |
| Socket framing, policy, key exchange | Implemented and exercised | Strongest parity area; retain captured vectors and add stream tests. |
| Sign-in command `10001` | Implemented against observed envelope and role-array layout | Basic behavior works, but legacy MD5 sign is forgeable/replayable and role data is incomplete. |
| Role creation `10002` | Explicitly unimplemented | Missing workflow and original constraints/side effects. |
| Enter-world `10003` | Dispatch exists, response is guessed/placeholder | Proven wrong: original role/stage/stat values differ substantially. |
| Map change `20000` | Dispatch exists, fixed map/coordinates | Proven wrong for the captured character; must read/write role stage state. |
| Account/currency, mall, VIP, role stats, mounts, dungeons | Mostly zero/null/empty stubs | Shapes alone do not implement Java service rules, configs, persistence, or side effects. |
| Scene actors/maps/combat/buffs | Not implemented | High-volume Java functionality required for a live scene; 24 captured IDs are a lower bound, not a complete command inventory. |
| Persistence | SQLite accounts, sessions, basic characters only | Missing role-stage, account/role currency, stats/equipment, buffs, mount, progression, and other domain state. |
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

Keep Java/MySQL runnable, preserve known-good original boot, and capture reproducible signed-in sessions. Fix the tap decoder to handle TCP fragmentation/coalescing, AMF ByteArray (`0x0c`), and multiple envelopes in one packet; retain raw captures with timestamps and checksums. Record command, request shape, response shape, state changes, and required config/database rows. The current 727-message trace is evidence, not a full protocol specification.

### Stage 1 — playable core vertical slice

Port real account-to-role authorization, role and role-stage persistence, map 5's data/config, login/enter-world/map-change replies, and the genuine `13000` bootstrap. Then implement the initial scene's config-backed actor/monster/NPC snapshot and required stat/buff packets. Compare complete normalized packet sequences with Java and test the same desktop client against both backends. Do not use zero-filled stubs for required state.

### Stage 2 — capability-by-capability migration

For each command module: trace command constants and action routing; inspect service implementation, output wrappers, DAOs/entities, config inputs, and SQL; create golden request/reply/state-transition tests; port transactionally; validate behavior against Java. Migrate core movement, combat, inventory/equipment, currency, quests/progression, and account systems before secondary events/social/GM modules.

### Stage 3 — hardening and cutover

Threat-model the protocol and web surface, validate ownership/isolation and replay protection, add rate limiting/auditability, and run protocol fuzzing plus multi-account persistence tests. Cut over only after an explicit supported-feature matrix and regression suite pass. “100%” needs a defined scope: all 71 command modules and the supporting config/data, not just the commands observed in one session.

## Recommendation

Use a **hybrid now, parity migration over time**. Let the new web/frontend stack coexist with Java for gameplay while the Python server is built as a drop-in replacement in measured slices. Replacing Java immediately with current Python will not render the world; trying to clone all 71 modules in one step is high risk and cannot be validated as a single change.

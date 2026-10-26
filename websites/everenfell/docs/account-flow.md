# Everenfell account flow: one AGP account, one home server

Final behavior: server selection is a one-time onboarding step, not
navigation. The Servers link is gone from the Everenfell navbar; the only
picker in the client appears once for first-time players and is never
linked anywhere.

Ownership: Freebuff Desktop implements all of this locally (React,
Phaser, Python, SQLite, tests). Orion performs no feature work — it
pulls approved GitHub changes to the VPS on instruction.

## Client flow (implemented)

Two distinct local states per AGP account (both device-local hints,
never proof of assignment):

| State | Stored as | Behavior |
| --- | --- | --- |
| No selection | nothing | Show the server picker |
| Server picked, nothing created | `evf-home-server-pending:<account>` | Picker pre-selects it; freely changeable |
| First character created | `evf-home-server:<account>` (pending cleared) | Auto-connect, skip picker |
| Authoritative value received | overwrites permanent cache, clears pending | Backend always wins (e.g. after an admin change) |

Resolution order in `checkWebsiteSession` (before any gateway
connection):

1. Signed in + session reports a bound `homeServer` → adopt it
   (overwrite caches) and auto-connect. A `?server=` URL parameter can
   never override this.
2. Signed in + unbound (`homeServer: null`) → drop any stale permanent
   cache and show the picker. The provisional choice (or a `?server=`
   hint) only pre-selects the dropdown — it never auto-connects.
3. Backend unreachable (session fetch fails) → connection error, never a
   guess from stale cache.

- Four character slots on the assigned server, any class combination
  (slot cap already enforced by `role.create` / protocol 10002).
- Deleting all characters changes nothing: the cache and the server
  assignment remain.

All localStorage entries here are per-device convenience caches only.
They grant nothing: the gateway verifies every request, and the
authoritative assignment lives server-side.

## Backend (implemented, Freebuff — Python side)

Assignment lives in the shared account store (`home_servers` table in
`Server-v1/db.py`), not in any gameplay database, so it resolves before
a particular game server is selected and stays correct when S2/S3
arrive with their own databases.

1. `Store.get_home_server(member)` → bound server id or `None`.
   `Store.bind_home_server(member, server)` → binds atomically
   (`INSERT OR IGNORE` in one transaction: concurrent first creations
   race to a single winner) and returns the winning server. Never
   overwrites. `Store.delete_character(role_id)` removes a
   just-created row for lost-race cleanup.
2. Binding moment: `op_role_create` pre-checks the member's binding and
   refuses cross-server creation; after a successful 10002 it binds,
   and a lost race deletes the orphan character and reports which home
   server won.
3. Enforcement on every character path: `role.create` pre-check,
   `/api/game/ticket` issuance (403 when bound elsewhere),
   `auth.session` and `world.enter` both return authoritative
   `homeServer`, and `/api/auth/session` carries `homeServer`
   (null = unbound) so the client routes before connecting.
4. Deleting all characters keeps the assignment; changing it requires
   an explicit authorized administrative process.

# Everenfell account flow: one AGP account, one home server

Final behavior: server selection is a one-time onboarding step, not
navigation. The Servers link is gone from the Everenfell navbar; the only
picker in the client appears once for first-time players and is never
linked anywhere.

## Client flow (implemented)

Two distinct local states per AGP account (both device-local hints,
never proof of assignment):

| State | Stored as | Behavior |
| --- | --- | --- |
| No selection | nothing | Show the server picker |
| Server picked, nothing created | `evf-home-server-pending:<account>` | Picker pre-selects it; freely changeable |
| First character created | `evf-home-server:<account>` (pending cleared) | Auto-connect, skip picker |
| Authoritative value received | overwrites permanent cache, clears pending | Backend always wins (e.g. after an admin change) |

Superseded rules (kept for history):

- Signed-in AGP member with a cached home server → auto-connects to it.
  A `?server=` URL parameter can never override the cache.
- No cache → one-time "Choose your home server" picker (internal step).
  First successful character creation re-affirms the cache.
- Four character slots on the assigned server, any class combination
  (slot cap already enforced by `role.create` / protocol 10002).
- Deleting all characters changes nothing: the cache (and, once
  implemented, the server assignment) remains.

All localStorage entries here are per-device convenience caches only.
They grant nothing: the gateway verifies every request, and the
authoritative assignment lives server-side.

## Backend contract (Orion — Python side)

The client deliberately does NOT implement assignment; it needs this
contract from the backend, enforced atomically:

1. Store the home server against the verified AGP identity in
   Everenfell's account data (not browser storage) so it follows the
   player across devices.
2. Bind on first successful character creation — not on server click.
   Abandoning creation must leave the account unbound. The check and
   the insert must be atomic (one transaction around the 10002 success)
   so two simultaneous creation requests cannot bind different servers.
3. Enforce on every character operation, not just entry: `role.create`,
   ticket issuance, `auth.session`, and `world.enter` all resolve the
   assigned server and reject cross-server requests. A direct creation
   request to another server must fail even outside the client flow.
4. Distinguish bound from unbound in session responses: `world.enter`
   should return the authoritative `homeServer` (and ideally a `bound`
   flag) so a stale browser cache — including after an administrative
   home-server change — is overwritten by the backend value. The
   client already adopts `homeServer` when present.
5. Deleting all characters keeps the assignment; changing it requires
   an explicit authorized administrative process.
6. Until this lands, S1 stays the only reachable server and the client
   cache is best-effort. Coordinate through GitHub; do not duplicate
   the logic client-side beyond the cache above.

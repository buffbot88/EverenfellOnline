/** Everenfell gateway protocol contract (Mission 5).

The Python server stays authoritative (auth, movement, combat,
progression, persistence). Browsers cannot speak its raw TCP framing, so
a WebSocket gateway will translate. Packet semantics stay identical to
the game protocol; only the transport/serialization is adapted, and it
is documented here — never reverse-engineered ad hoc in views.

Gateway envelope (JSON over WebSocket, client <-> gateway):
  { "op": "<domain>.<action>", "seq": n, "body": {...} }
The gateway answers { op, seq, ok, body } and pushes
{ op, seq: 0, body } broadcasts (actor motion, snapshots, vitals).

Smallest playable loop ops:
  auth.login -> auth.session -> world.enter -> world.snapshot ->
  actor.moved (push) / player.move
Later domains reuse server command semantics: npc.list, mob.list,
combat.fire, combat.resolved, bag.*, skills.*, quests.*.
*/

/** Browser-facing game servers. S1 only; later entries get their own
 *  databases (see Server-v1/docs/website-accounts-s1.md). The id is
 *  validated against the gateway registry — never trusted blindly. */
export interface GameServerRef {
  id: string;
  name: string;
}

export const GAME_SERVERS: GameServerRef[] = [{ id: 'S1', name: 'S1' }];

/** Domains the gateway will serve, in expansion order. */
export const GATEWAY_OPS = [
  'auth.login',
  'auth.session',
  'role.create',
  'world.enter',
  'world.snapshot',
  'player.move',
  'actor.moved',
] as const;

export type GatewayOp = (typeof GATEWAY_OPS)[number];

export interface GatewayRequest {
  op: GatewayOp | string;
  seq: number;
  body: Record<string, unknown>;
}

export interface GatewayResponse {
  op: string;
  seq: number;
  ok: boolean;
  body: Record<string, unknown>;
}

/** Owned character entry (subset of the 10001 roleInfo array). */
export interface RoleRef {
  id: string;
  name: string;
  job: string;
  level: number;
}

/** Maximum characters per account per game server (protocol MAX_ROLES_PER_ACCOUNT). */
export const MAX_ROLES_PER_ACCOUNT = 4;

/** Playable job codes (A/B/C/D). Class names are recovered, not
 * invented: the create-ui ribbon bitmaps render them as art, and
 * SymbolClass containment fixes the mapping (sprite 38/A -> bitmap 35,
 * 23/B -> 21, 31/C -> 28, 11/D -> 5). */
export const JOB_CODES = ['A', 'B', 'C', 'D'] as const;

export const JOB_NAMES: Record<JobCode, string> = {
  A: 'Spirit Monkey',
  B: 'Nine Tails',
  C: 'Bull Demon',
  D: 'Rakshasa',
};

/** Display name for a job code; unknown codes pass through unchanged. */
export function jobName(job: string): string {
  if ((JOB_CODES as readonly string[]).includes(job)) {
    return JOB_NAMES[job as JobCode];
  }
  return job;
}

export type JobCode = (typeof JOB_CODES)[number];

/** World snapshot: validated actors the client renders. Positions are
 *  server tiles (60x30 px), matching the Python stage registry. */
export interface ActorSnapshot {
  id: string;
  kind: 'player' | 'mob' | 'npc';
  template?: string;
  name?: string;
  level?: number;
  hp?: number;
  maxHp?: number;
  x: number;
  y: number;
}

export interface WorldSnapshot {
  mapId: string;
  actors: ActorSnapshot[];
}

/** Tile size in world pixels (mirrors Server-v1 stage geometry). */
export const TILE_W = 60;
export const TILE_H = 30;

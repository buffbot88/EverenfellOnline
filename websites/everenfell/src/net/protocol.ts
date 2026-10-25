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

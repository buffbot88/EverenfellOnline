/** Actor layer: validated snapshots -> sprites, nothing more.

The server is authoritative for positions; this layer tweens between
validated states for smoothness but never predicts gameplay (no
client-side hits, pickups, or kills). Sprite look is a placeholder
tint per kind until the asset pipeline supplies recovered or
replacement art with matching anchors.

2.5D model: actors sort by tile y (painter's algorithm) and anchor at
feet-center, the convention the recovered sprite sheets must follow.
*/
import { Container, Graphics } from 'pixi.js';
import type { ActorSnapshot } from '../net/protocol';
import { TILE_H, TILE_W } from '../net/protocol';
import type { Camera } from './camera';

const KIND_TINT: Record<ActorSnapshot['kind'], number> = {
  player: 0x4fc3f7,
  mob: 0xef5350,
  npc: 0x9ccc65,
};

export class ActorLayer {
  readonly root = new Container();
  private nodes = new Map<string, { gfx: Graphics; x: number; y: number; tx: number; ty: number }>();

  constructor(private readonly camera: Camera) {
    this.root.sortableChildren = true;
  }

  /** Replace the full actor set (world.snapshot). */
  setAll(actors: ActorSnapshot[]): void {
    const seen = new Set<string>();
    for (const actor of actors) {
      seen.add(actor.id);
      this.upsert(actor);
    }
    for (const id of [...this.nodes.keys()]) {
      if (!seen.has(id)) {
        const node = this.nodes.get(id);
        node?.gfx.destroy();
        this.nodes.delete(id);
      }
    }
  }

  /** Apply one validated motion (actor.moved). */
  move(id: string, x: number, y: number): void {
    const node = this.nodes.get(id);
    if (node) {
      node.tx = x;
      node.ty = y;
    }
  }

  /** Ease nodes toward validated tiles; call every frame. */
  tick(alpha: number): void {
    for (const node of this.nodes.values()) {
      node.x += (node.tx - node.x) * Math.min(1, alpha * 0.35);
      node.y += (node.ty - node.y) * Math.min(1, alpha * 0.35);
      const screen = this.camera.toScreen(node.x, node.y);
      node.gfx.position.set(screen.x, screen.y);
      node.gfx.zIndex = node.y;
    }
  }

  private upsert(actor: ActorSnapshot): void {
    let node = this.nodes.get(actor.id);
    if (!node) {
      const gfx = new Graphics();
      const w = Math.max(12, TILE_W * 0.5);
      const h = Math.max(18, TILE_H * 1.1);
      gfx.rect(-w / 2, -h, w, h).fill(KIND_TINT[actor.kind]);
      gfx.rect(-w / 2, -h, w, 4).fill(0x101418);
      if (actor.maxHp && actor.maxHp > 0) {
        const ratio = Math.max(0, Math.min(1, (actor.hp ?? actor.maxHp) / actor.maxHp));
        gfx.rect(-w / 2, -h, w * ratio, 4).fill(actor.kind === 'mob' ? 0xff5252 : 0x69f0ae);
      }
      this.root.addChild(gfx);
      node = { gfx, x: actor.x, y: actor.y, tx: actor.x, ty: actor.y };
      this.nodes.set(actor.id, node);
    } else {
      node.tx = actor.x;
      node.ty = actor.y;
    }
  }
}

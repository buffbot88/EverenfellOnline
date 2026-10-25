/** World scene: original Map 0 tiles at native pixels (dev-only source).
 *
 * 408 JPEG tiles, 17x24 @256px, 4352x6144. Positions come from the
 * verified manifest; missing tiles fail the load visibly instead of
 * showing substitute art. View-only: no gateway, no session, no intents.
 * Phaser culls offscreen sprites from draw automatically; textures stay
 * cached for pan smoothness on this single map.
 */
import Phaser from 'phaser';
import type { ActorSnapshot } from '../../net/protocol';
import { TILE_H, TILE_W } from '../../net/protocol';
import type { Camera } from '../../world/camera';
import { MAP_H, MAP_TILES, MAP_W, tileKey } from '../mapManifest';

export const WORLD_KEY = 'world';

const MIN_ZOOM = 0.1;
const MAX_ZOOM = 2;
const PAN_STEP = 80;

declare global {
  interface Window {
    __evfMapStatus?: {
      loaded: number;
      failed: string[];
      tileCount: number;
      zoom: number;
    };
  }
}

const KIND_TINT: Record<ActorSnapshot['kind'], number> = {
  player: 0x4fc3f7,
  mob: 0xef5350,
  npc: 0x9ccf65,
};

interface ActorNode {
  body: Phaser.GameObjects.Rectangle;
  bar: Phaser.GameObjects.Rectangle;
  x: number;
  y: number;
  tx: number;
  ty: number;
}

export class WorldScene extends Phaser.Scene {
  private failures: string[] = [];
  private actorCamera: Camera | null = null;
  private actorNodes = new Map<string, ActorNode>();

  constructor() {
    super(WORLD_KEY);
  }

  preload(): void {
    for (const tile of MAP_TILES) {
      this.load.image(tileKey(tile), tile.url);
    }
  }

  create(): void {
    let loaded = 0;
    for (const tile of MAP_TILES) {
      const key = tileKey(tile);
      if (!this.textures.exists(key)) {
        this.failures.push(`${tile.id}: texture missing`);
        continue;
      }
      this.add.image(tile.x + tile.width / 2, tile.y + tile.height / 2, key);
      loaded += 1;
    }

    const cam = this.cameras.main;
    cam.setBackgroundColor('#0a141d');
    // In Scale.RESIZE mode the camera viewport does not track the canvas
    // on its own; sync it now and on every resize, else centerOn uses a
    // stale size and the map sits off-center.
    cam.setViewport(0, 0, this.scale.width, this.scale.height);
    const fit = Math.min(cam.width / MAP_W, cam.height / MAP_H);
    const startZoom = Math.min(1, fit);
    cam.setZoom(startZoom);
    cam.centerOn(MAP_W / 2, MAP_H / 2);
    clampCam(cam);
    this.scale.on('resize', (gameSize: Phaser.Structs.Size) => {
      cam.setViewport(0, 0, gameSize.width, gameSize.height);
      clampCam(cam);
    });

    this.enablePanZoom(cam);
    this.enableKeys(cam);
    this.scene.launch('ui');

    this.scale.on('resize', () => {
      this.positionActors();
    });

    window.__evfMapStatus = {
      loaded,
      failed: this.failures,
      tileCount: MAP_TILES.length,
      zoom: cam.zoom,
    };
    if (this.failures.length > 0) {
      throw new Error(
        `${this.failures.length} of ${MAP_TILES.length} tiles failed (first: ${this.failures[0]})`,
      );
    }
  }

  /** Bind the gameplay projection; actors render in screen space. */
  bindActorCamera(camera: Camera): void {
    this.actorCamera = camera;
    this.positionActors();
  }

  /** Replace the full actor set (world.snapshot). */
  setActors(actors: ActorSnapshot[]): void {
    const seen = new Set<string>();
    for (const actor of actors) {
      seen.add(actor.id);
      this.upsertActor(actor);
    }
    for (const [id, node] of [...this.actorNodes]) {
      if (!seen.has(id)) {
        node.body.destroy();
        node.bar.destroy();
        this.actorNodes.delete(id);
      }
    }
    this.positionActors();
  }

  /** Apply one validated motion (actor.moved). */
  moveActor(id: string, x: number, y: number): void {
    const node = this.actorNodes.get(id);
    if (node) {
      node.tx = x;
      node.ty = y;
    }
  }

  update(_time: number, delta: number): void {
    if (this.actorNodes.size === 0) return;
    const alpha = Math.min(1, delta / 16.6);
    let moved = false;
    for (const node of this.actorNodes.values()) {
      node.x += (node.tx - node.x) * Math.min(1, alpha * 0.35);
      node.y += (node.ty - node.y) * Math.min(1, alpha * 0.35);
      moved = true;
    }
    if (moved) this.positionActors();
  }

  private upsertActor(actor: ActorSnapshot): void {
    let node = this.actorNodes.get(actor.id);
    if (!node) {
      const w = Math.max(12, TILE_W * 0.5);
      const h = Math.max(18, TILE_H * 1.1);
      const body = this.add
        .rectangle(0, 0, w, h, KIND_TINT[actor.kind])
        .setScrollFactor(0)
        .setOrigin(0.5, 1)
        .setDepth(actor.y);
      const bar = this.add
        .rectangle(0, 0, w, 4, 0x101418)
        .setScrollFactor(0)
        .setOrigin(0.5, 1)
        .setDepth(actor.y + 0.1);
      this.children.bringToTop(bar);
      node = { body, bar, x: actor.x, y: actor.y, tx: actor.x, ty: actor.y };
      this.actorNodes.set(actor.id, node);
    } else {
      node.tx = actor.x;
      node.ty = actor.y;
    }
    if (actor.maxHp && actor.maxHp > 0) {
      const ratio = Math.max(0, Math.min(1, (actor.hp ?? actor.maxHp) / actor.maxHp));
      node.bar.setFillStyle(actor.kind === 'mob' ? 0xff5252 : 0x69f0ae);
      node.bar.setSize(node.body.width * ratio, 4);
    }
  }

  private positionActors(): void {
    const cam = this.actorCamera;
    if (!cam) return;
    cam.resize(this.cameras.main.width, this.cameras.main.height);
    for (const node of this.actorNodes.values()) {
      const screen = cam.toScreen(node.x, node.y);
      node.body.setPosition(screen.x, screen.y).setDepth(node.y);
      node.bar.setPosition(screen.x, screen.y - node.body.height).setDepth(node.y + 0.1);
    }
  }

  /** Drag to pan; wheel zooms around the cursor; clamped like MapViewer. */
  private enablePanZoom(cam: Phaser.Cameras.Scene2D.Camera): void {
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    this.input.on('pointerdown', (pointer: Phaser.Input.Pointer) => {
      dragging = true;
      lastX = pointer.x;
      lastY = pointer.y;
    });
    this.input.on('pointermove', (pointer: Phaser.Input.Pointer) => {
      if (!dragging || !pointer.isDown) return;
      cam.scrollX -= (pointer.x - lastX) / cam.zoom;
      cam.scrollY -= (pointer.y - lastY) / cam.zoom;
      clampCam(cam);
      lastX = pointer.x;
      lastY = pointer.y;
    });
    this.input.on('pointerup', () => {
      dragging = false;
    });
    this.input.on(
      'wheel',
      (
        _pointer: Phaser.Input.Pointer,
        _targets: unknown[],
        _dx: number,
        dy: number,
      ) => {
        const pointer = this.input.activePointer;
        const factor = dy < 0 ? 1.1 : 1 / 1.1;
        const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, cam.zoom * factor));
        const before = cam.getWorldPoint(pointer.x, pointer.y);
        cam.setZoom(next);
        const after = cam.getWorldPoint(pointer.x, pointer.y);
        cam.scrollX += before.x - after.x;
        cam.scrollY += before.y - after.y;
        clampCam(cam);
        if (window.__evfMapStatus) window.__evfMapStatus.zoom = next;
      },
    );
  }

  private enableKeys(cam: Phaser.Cameras.Scene2D.Camera): void {
    const keys = this.input.keyboard?.addKeys('UP,DOWN,LEFT,RIGHT') as
      | Record<string, Phaser.Input.Keyboard.Key>
      | undefined;
    if (!keys) return;
    const step = PAN_STEP;
    const onKey = (code: string) => {
      if (code === 'ArrowLeft' || code === 'LEFT') cam.scrollX -= step / cam.zoom;
      if (code === 'ArrowRight' || code === 'RIGHT') cam.scrollX += step / cam.zoom;
      if (code === 'ArrowUp' || code === 'UP') cam.scrollY -= step / cam.zoom;
      if (code === 'ArrowDown' || code === 'DOWN') cam.scrollY += step / cam.zoom;
      clampCam(cam);
    };
    this.input.keyboard?.on('keydown', (event: KeyboardEvent) => {
      onKey(event.code);
    });
  }
}

/** Keep the view on the map: center when zoomed out, clamp when zoomed in. */
function clampCam(cam: Phaser.Cameras.Scene2D.Camera): void {
  const viewW = cam.width / cam.zoom;
  const viewH = cam.height / cam.zoom;
  cam.scrollX =
    viewW >= MAP_W ? (MAP_W - viewW) / 2 : Phaser.Math.Clamp(cam.scrollX, 0, MAP_W - viewW);
  cam.scrollY =
    viewH >= MAP_H ? (MAP_H - viewH) / 2 : Phaser.Math.Clamp(cam.scrollY, 0, MAP_H - viewH);
}

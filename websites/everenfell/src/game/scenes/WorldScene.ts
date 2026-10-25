/** World scene: the original map is a world, not a background image.
 *
 * 408 JPEG tiles at native 256px cells (17x24, 4352x6144 px) placed at
 * their original world coordinates. Nothing is ever scaled to fit the
 * viewport: the camera decides what part of the world is visible and
 * follows the player. Zoom and bounds are camera settings, independent
 * of the artwork, so browser resizing never reflows the map.
 *
 * Tiles are loaded progressively: a tile is only handed to the texture
 * manager when it enters the camera's view (plus a margin), so players
 * never download or upload the whole 11 MB map up front.
 */
import Phaser from 'phaser';
import type { ActorSnapshot } from '../../net/protocol';
import { TILE_H, TILE_W } from '../../net/protocol';
import type { Camera } from '../../world/camera';
import { MAP_H, MAP_TILES, MAP_W, tileKey, type MapTile } from '../mapManifest';

export const WORLD_KEY = 'world';

const MIN_ZOOM = 0.35;
const MAX_ZOOM = 2;
const START_ZOOM = 1;
/** Extra ring of tiles loaded beyond the viewport to hide pan seams. */
const MARGIN_PX = 512;

declare global {
  interface Window {
    __evfMapStatus?: {
      loaded: number;
      failed: string[];
      tileCount: number;
      zoom: number;
      /** True once every tile in the current view finished loading. */
      ready: boolean;
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

interface TileRecord {
  tile: MapTile;
  image: Phaser.GameObjects.Image | null;
  state: 'pending' | 'loading' | 'ready' | 'failed';
}

export class WorldScene extends Phaser.Scene {
  private failures: string[] = [];
  private actorCamera: Camera | null = null;
  private actorNodes = new Map<string, ActorNode>();
  private tiles: TileRecord[] = [];
  private player: Phaser.GameObjects.Container | null = null;
  private marker: Phaser.GameObjects.Ellipse | null = null;
  private view = { x: 0, y: -1, w: 0, h: 0 };

  constructor() {
    super(WORLD_KEY);
  }

  create(): void {
    this.tiles = MAP_TILES.map((tile) => ({ tile, image: null, state: 'pending' }));
    // One shared failure handler for every on-demand tile load.
    this.load.on('loaderror', (file: { key?: string }) => {
      const rec = this.tiles.find(
        (entry) => entry.state === 'loading' && tileKey(entry.tile) === file.key,
      );
      if (rec) {
        rec.state = 'failed';
        this.failures.push(`${rec.tile.id}: load failed`);
        this.updateStatus();
      }
    });

    const cam = this.cameras.main;
    cam.setBackgroundColor('#0a141d');
    cam.setBounds(0, 0, MAP_W, MAP_H);
    cam.setZoom(START_ZOOM);
    // Start at the map's centre in world pixels; the camera keeps that
    // framing regardless of window size because it never fits the image.
    this.focusPoint(MAP_W / 2, MAP_H / 2);

    this.createPlayerMarker();
    this.enablePanZoom(cam);
    this.enableKeys(cam);
    this.scale.on('resize', () => {
      this.syncViewport();
      this.loadVisibleTiles();
    });
    this.syncViewport();
    this.loadVisibleTiles();
    this.scene.launch('ui');
  }

  /** Bind the gameplay projection; actors render at world tile positions. */
  bindActorCamera(camera: Camera): void {
    this.actorCamera = camera;
    this.positionActors();
  }

  /** Camera follows a world tile position (player). */
  followTile(tileX: number, tileY: number): void {
    this.actorCamera?.follow(tileX, tileY);
    const wx = tileX * TILE_W;
    const wy = tileY * TILE_H;
    this.focusPoint(wx, wy);
    this.player?.setPosition(wx, wy);
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
    const cam = this.cameras.main;
    if (
      cam.worldView.x !== this.view.x ||
      cam.worldView.y !== this.view.y ||
      cam.worldView.width !== this.view.w ||
      cam.worldView.height !== this.view.h
    ) {
      this.syncViewport();
      this.loadVisibleTiles();
    }
    if (this.actorNodes.size === 0) return;
    const alpha = Math.min(1, delta / 16.6);
    for (const node of this.actorNodes.values()) {
      node.x += (node.tx - node.x) * Math.min(1, alpha * 0.35);
      node.y += (node.ty - node.y) * Math.min(1, alpha * 0.35);
    }
    this.positionActors();
  }

  private syncViewport(): void {
    const w = this.cameras.main.worldView;
    this.view = { x: w.x, y: w.y, w: w.width, h: w.height };
    // Camera viewport must track the canvas in Scale.RESIZE mode.
    this.cameras.main.setViewport(0, 0, this.scale.width, this.scale.height);
  }

  /** Point the camera at a world pixel, clamped to the map bounds. */
  private focusPoint(x: number, y: number): void {
    const cam = this.cameras.main;
    cam.centerOn(
      Phaser.Math.Clamp(x, 0, MAP_W),
      Phaser.Math.Clamp(y, 0, MAP_H),
    );
  }

  /** Load only tiles inside the current view plus a margin. */
  private loadVisibleTiles(): void {
    const { x, y, w, h } = this.view;
    const x0 = x - MARGIN_PX;
    const y0 = y - MARGIN_PX;
    const x1 = x + w + MARGIN_PX;
    const y1 = y + h + MARGIN_PX;
    let queued = false;
    for (const rec of this.tiles) {
      if (rec.state !== 'pending') continue;
      const { tile } = rec;
      const inside =
        tile.x + tile.width > x0 &&
        tile.x < x1 &&
        tile.y + tile.height > y0 &&
        tile.y < y1;
      if (!inside) continue;
      rec.state = 'loading';
      const key = tileKey(tile);
      this.load.image(key, tile.url);
      this.load.once(`filecomplete-image-${key}`, () => {
        if (rec.state !== 'loading') return;
        rec.state = 'ready';
        rec.image = this.add.image(
          tile.x + tile.width / 2,
          tile.y + tile.height / 2,
          key,
        );
        this.children.sendToBack(rec.image);
        this.updateStatus();
      });
      queued = true;
    }
    if (queued && !this.load.isLoading()) {
      this.load.start();
    }
    this.updateStatus();
  }

  private updateStatus(): void {
    const loaded = this.tiles.filter((rec) => rec.state === 'ready').length;
    const { x, y, w, h } = this.view;
    const x0 = x - MARGIN_PX;
    const y0 = y - MARGIN_PX;
    const x1 = x + w + MARGIN_PX;
    const y1 = y + h + MARGIN_PX;
    const ready = this.tiles.every((rec) => {
      if (rec.state === 'ready' || rec.state === 'failed') return true;
      const { tile } = rec;
      return !(
        tile.x + tile.width > x0 &&
        tile.x < x1 &&
        tile.y + tile.height > y0 &&
        tile.y < y1
      );
    });
    window.__evfMapStatus = {
      loaded,
      failed: this.failures,
      tileCount: this.tiles.length,
      zoom: this.cameras.main.zoom,
      ready,
    };
  }

  private createPlayerMarker(): void {
    const g = this.add.graphics();
    g.fillStyle(0x4fc3f7, 1);
    g.fillRect(-8, -8, 16, 16);
    this.marker = this.add.ellipse(0, 0, 22, 10, 0x000000, 0.35);
    this.player = this.add.container(MAP_W / 2, MAP_H / 2, [this.marker, g]);
    this.player.setDepth(1e9);
  }

  private upsertActor(actor: ActorSnapshot): void {
    let node = this.actorNodes.get(actor.id);
    if (!node) {
      const w = Math.max(12, TILE_W * 0.5);
      const h = Math.max(18, TILE_H * 1.1);
      const body = this.add
        .rectangle(0, 0, w, h, KIND_TINT[actor.kind])
        .setOrigin(0.5, 1)
        .setDepth(actor.y);
      const bar = this.add
        .rectangle(0, 0, w, 4, 0x101418)
        .setOrigin(0.5, 1)
        .setDepth(actor.y + 0.1);
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

  /** Actors live in world space: no per-frame screen projection needed. */
  private positionActors(): void {
    for (const node of this.actorNodes.values()) {
      const wx = node.x * TILE_W;
      const wy = node.y * TILE_H;
      node.body.setPosition(wx, wy).setDepth(wy);
      node.bar.setPosition(wx, wy - node.body.height).setDepth(wy + 0.5);
    }
  }

  /** Drag to pan; wheel zooms around the cursor; arrows pan. */
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
      lastX = pointer.x;
      lastY = pointer.y;
    });
    this.input.on('pointerup', () => {
      dragging = false;
    });
    this.input.on(
      'wheel',
      (_p: Phaser.Input.Pointer, _t: unknown[], _dx: number, dy: number) => {
        const pointer = this.input.activePointer;
        const factor = dy < 0 ? 1.1 : 1 / 1.1;
        const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, cam.zoom * factor));
        const before = cam.getWorldPoint(pointer.x, pointer.y);
        cam.setZoom(next);
        const after = cam.getWorldPoint(pointer.x, pointer.y);
        cam.scrollX += before.x - after.x;
        cam.scrollY += before.y - after.y;
        if (window.__evfMapStatus) window.__evfMapStatus.zoom = next;
        this.loadVisibleTiles();
      },
    );
  }

  private enableKeys(cam: Phaser.Cameras.Scene2D.Camera): void {
    this.input.keyboard?.on('keydown', (event: KeyboardEvent) => {
      const step = 80 / cam.zoom;
      if (event.code === 'ArrowLeft') cam.scrollX -= step;
      if (event.code === 'ArrowRight') cam.scrollX += step;
      if (event.code === 'ArrowUp') cam.scrollY -= step;
      if (event.code === 'ArrowDown') cam.scrollY += step;
      if (event.code.startsWith('Arrow')) this.loadVisibleTiles();
    });
  }
}

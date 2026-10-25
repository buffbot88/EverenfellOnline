/** World scene: original Map 0 tiles at native pixels (dev-only source).
 *
 * 408 JPEG tiles, 17x24 @256px, 4352x6144. Positions come from the
 * verified manifest; missing tiles fail the load visibly instead of
 * showing substitute art. View-only: no gateway, no session, no intents.
 * Phaser culls offscreen sprites from draw automatically; textures stay
 * cached for pan smoothness on this single map.
 */
import Phaser from 'phaser';
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

export class WorldScene extends Phaser.Scene {
  private failures: string[] = [];

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
    cam.setBounds(0, 0, MAP_W, MAP_H);
    cam.setBackgroundColor('#0a141d');
    const fit = Math.min(cam.width / MAP_W, cam.height / MAP_H);
    const startZoom = Math.min(1, fit);
    cam.setZoom(startZoom);
    cam.centerOn(MAP_W / 2, MAP_H / 2);

    this.enablePanZoom(cam);
    this.enableKeys(cam);
    this.scene.launch('ui');

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
    };
    this.input.keyboard?.on('keydown', (event: KeyboardEvent) => {
      onKey(event.code);
    });
  }
}

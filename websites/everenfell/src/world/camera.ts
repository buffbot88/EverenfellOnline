/** Camera: world tiles <-> screen projection, follow, zoom.

World units are server tiles (TILE_W x TILE_H px). The projection is
kept explicit and replaceable: the legacy client renders an isometric
2.5D scene, and the final projection must match recovered anchor/timing
data. Until then this orthogonal projection keeps gameplay (movement,
AOI, ranges) testable without pretending to be the final look.
*/
import { TILE_H, TILE_W } from '../net/protocol';

export interface CameraOptions {
  viewWidth: number;
  viewHeight: number;
}

export class Camera {
  x = 0;
  y = 0;
  zoom = 1;

  constructor(private options: CameraOptions) {}

  resize(width: number, height: number): void {
    this.options.viewWidth = width;
    this.options.viewHeight = height;
  }

  /** Center the view on a tile position. */
  follow(tileX: number, tileY: number): void {
    this.x = tileX * TILE_W;
    this.y = tileY * TILE_H;
  }

  toScreen(tileX: number, tileY: number): { x: number; y: number } {
    return {
      x: (tileX * TILE_W - this.x) * this.zoom + this.options.viewWidth / 2,
      y: (tileY * TILE_H - this.y) * this.zoom + this.options.viewHeight / 2,
    };
  }

  toTile(screenX: number, screenY: number): { x: number; y: number } {
    return {
      x: Math.round(
        (this.x + (screenX - this.options.viewWidth / 2) / this.zoom) / TILE_W,
      ),
      y: Math.round(
        (this.y + (screenY - this.options.viewHeight / 2) / this.zoom) / TILE_H,
      ),
    };
  }
}

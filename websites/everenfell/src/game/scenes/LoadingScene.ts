/** Loading screen slot: original Flash loading art lands here.
 *
 * Shows a status line while Map 0 tiles stream in WorldScene. Routes to
 * ?scene=select|create when requested, else to the world map. Original
 * gameui loading bitmaps (PanelLoading etc.) are not yet wired; no
 * substitute art is drawn.
 */
import Phaser from 'phaser';
import { HOLDING_KEY } from './HoldingScene';

export const LOADING_KEY = 'loading';

/** Set by the client before constructing the game on the gameplay path.
 * Stopping the world after construction races scene boot and loses, so
 * LoadingScene routes gameplay boots to the holding scene instead of
 * ever starting the world. Map-inspect mode is unaffected. */
let suppressWorld = false;

export function setSuppressWorld(value: boolean): void {
  suppressWorld = value;
}

export class LoadingScene extends Phaser.Scene {
  constructor() {
    super(LOADING_KEY);
  }

  create(): void {
    const params = new URLSearchParams(window.location.search);
    const next = params.get('scene') ?? 'world';
    if (suppressWorld && next === 'world') {
      this.scene.start(HOLDING_KEY);
      return;
    }
    const label = this.add
      .text(16, 16, 'Everenfell loading… (original screen pending)', {
        fontSize: '16px',
        color: '#cfe3f0',
      })
      .setScrollFactor(0)
      .setDepth(1000);
    label.setName('loading-label');
    const allowed = new Set(['world', 'select', 'create']);
    this.scene.start(allowed.has(next) ? next : 'world');
  }
}

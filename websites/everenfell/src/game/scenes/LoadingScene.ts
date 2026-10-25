/** Loading screen slot: original Flash loading art lands here.
 *
 * Shows a status line while Map 0 tiles stream in WorldScene. Routes to
 * ?scene=select|create when requested, else to the world map. Original
 * gameui loading bitmaps (PanelLoading etc.) are not yet wired; no
 * substitute art is drawn.
 */
import Phaser from 'phaser';

export const LOADING_KEY = 'loading';

export class LoadingScene extends Phaser.Scene {
  constructor() {
    super(LOADING_KEY);
  }

  create(): void {
    const params = new URLSearchParams(window.location.search);
    const next = params.get('scene') ?? 'world';
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

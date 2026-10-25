/** HUD overlay: runs above WorldScene; original HUD art lands here. */
import Phaser from 'phaser';

export const UI_KEY = 'ui';

export class UIScene extends Phaser.Scene {
  constructor() {
    super(UI_KEY);
  }

  create(): void {
    const label = this.add.text(16, 16, 'HUD overlay (original art pending)', {
      fontSize: '14px',
      color: '#9fc3d8',
    });
    label.setScrollFactor(0).setDepth(1000);
  }
}

/** Boot: asset initialization entry. Starts the loading scene. */
import Phaser from 'phaser';

export const BOOT_KEY = 'boot';

export class BootScene extends Phaser.Scene {
  constructor() {
    super(BOOT_KEY);
  }

  create(): void {
    this.scene.start('loading');
  }
}

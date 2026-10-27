/** Holding scene: owns the canvas while character screens are in charge.
 *
 * Phaser always needs an active scene, but the world map must never boot
 * on the gameplay path before START GAME (stopping it after construction
 * races scene boot and loses). LoadingScene routes gameplay boots here:
 * a black canvas that starts nothing, shows nothing, and loads nothing
 * until showScene()/enterWorld() direct the real scenes.
 */
import Phaser from 'phaser';

export const HOLDING_KEY = 'holding';

export class HoldingScene extends Phaser.Scene {
  constructor() {
    super(HOLDING_KEY);
  }

  create(): void {
    this.cameras.main.setBackgroundColor('#000000');
  }
}

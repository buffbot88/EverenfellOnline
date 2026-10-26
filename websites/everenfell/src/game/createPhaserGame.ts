/** Phaser game factory: Boot/Loading/Select/Create/World + HUD overlay.
 *
 * Rendering only: no gateway, no session, no gameplay rules. The Python
 * server stays authoritative; Phaser never simulates movement or combat.
 * Canvas fills #app via Scale.RESIZE and follows browser resizing.
 */
import Phaser from 'phaser';
import { BootScene } from './scenes/BootScene';
import { LoadingScene } from './scenes/LoadingScene';
import { CharacterSelectScene } from './scenes/CharacterSelectScene';
import { CharacterCreateScene } from './scenes/CharacterCreateScene';
import { WorldScene } from './scenes/WorldScene';
import { UIScene } from './scenes/UIScene';

export function createPhaserGame(parent: HTMLElement): Phaser.Game {
  const config: Phaser.Types.Core.GameConfig = {
    type: Phaser.AUTO,
    parent,
    backgroundColor: '#000000',
    scale: {
      mode: Phaser.Scale.RESIZE,
      parent,
      width: '100%',
      height: '100%',
    },
    render: { antialias: true, pixelArt: false },
    scene: [
      BootScene,
      LoadingScene,
      CharacterSelectScene,
      CharacterCreateScene,
      WorldScene,
      UIScene,
    ],
  };
  const game = new Phaser.Game(config);
  if (import.meta.env.DEV) {
    // Test hook: lets interaction checks drive scenes without a backend.
    (window as unknown as { __evfGame?: Phaser.Game }).__evfGame = game;
  }
  return game;
}

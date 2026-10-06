import Phaser from 'phaser';
import './style.css';
import BootScene from './scenes/BootScene.js';
import LoginScene from './scenes/LoginScene.js';

// Original Flash client ran at full browser size; keep a fixed 960x640
// game area scaled to fit, matching the classic client proportions.
new Phaser.Game({
  type: Phaser.AUTO,
  parent: 'game',
  width: 960,
  height: 640,
  backgroundColor: '#0b0e1a',
  scale: {
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_BOTH,
  },
  scene: [BootScene, LoginScene],
});

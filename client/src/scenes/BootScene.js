import Phaser from 'phaser';

// Splash backdrop behind the DOM login overlay. Later milestones will load
// extracted legacy art (res/ pipeline) here instead of drawn shapes.
export default class BootScene extends Phaser.Scene {
  constructor() {
    super('boot');
  }

  create() {
    const { width, height } = this.scale;

    // Night-sky gradient backdrop.
    const g = this.add.graphics();
    g.fillGradientStyle(0x0b0e1a, 0x0b0e1a, 0x1a2350, 0x1a2350, 1);
    g.fillRect(0, 0, width, height);

    // Scattered "stars".
    for (let i = 0; i < 160; i++) {
      const x = Math.random() * width;
      const y = Math.random() * height * 0.7;
      const r = Math.random() * 1.6 + 0.4;
      g.fillStyle(0xffffff, 0.25 + Math.random() * 0.6);
      g.fillCircle(x, y, r);
    }

    // Title above the login card.
    this.add
      .text(width / 2, 120, 'MONKEY KING ONLINE', {
        fontFamily: 'Georgia, serif',
        fontSize: '44px',
        color: '#ffd76a',
        letterSpacing: 4,
      })
      .setOrigin(0.5);
    this.add
      .text(width / 2, 162, '大 鬧 天 空 · HTML5 CLIENT', {
        fontSize: '16px',
        color: '#9aa3c7',
      })
      .setOrigin(0.5);

    this.scene.start('login');
  }
}

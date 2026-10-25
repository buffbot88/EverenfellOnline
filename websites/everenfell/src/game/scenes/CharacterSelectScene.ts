/** Character selection slot: verified selection art lands here. */
import Phaser from 'phaser';

export const SELECT_KEY = 'select';

export class CharacterSelectScene extends Phaser.Scene {
  constructor() {
    super(SELECT_KEY);
  }

  create(): void {
    this.add.text(16, 16, 'Character selection (original art pending)', {
      fontSize: '16px',
      color: '#cfe3f0',
    });
  }
}

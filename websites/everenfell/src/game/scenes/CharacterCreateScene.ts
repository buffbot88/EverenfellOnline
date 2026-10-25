/** Character creation slot: ui.asyncpanel.createUI art lands here. */
import Phaser from 'phaser';

export const CREATE_KEY = 'create';

export class CharacterCreateScene extends Phaser.Scene {
  constructor() {
    super(CREATE_KEY);
  }

  create(): void {
    this.add.text(16, 16, 'Character creation (original art pending)', {
      fontSize: '16px',
      color: '#cfe3f0',
    });
  }
}

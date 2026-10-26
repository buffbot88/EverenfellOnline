/** Character selection: owned roles from world.enter plus empty slots.
 *
 * Roles arrive as {id, name, job, level}; slot cap is 4 (protocol
 * MAX_ROLES_PER_ACCOUNT). Portraits reuse the create-ui job bitmaps by
 * job index (A=0..D=3); unknown jobs get a labeled box. Empty slots are
 * outlined boxes, never fake characters. Entry keeps flowing through
 * world.snapshot so ownership stays server-enforced.
 */
import Phaser from 'phaser';
import { MAX_ROLES_PER_ACCOUNT, type RoleRef } from '../../net/protocol';

export const SELECT_KEY = 'select';

const JOB_PORTRAIT: Record<string, string> = {
  A: 'select-job-0',
  B: 'select-job-1',
  C: 'select-job-2',
  D: 'select-job-3',
};

function assetUrl(path: string): string {
  return `${import.meta.env.DEV ? '/assets/' : '/protected-assets/'}${path}`;
}

export class CharacterSelectScene extends Phaser.Scene {
  constructor() {
    super(SELECT_KEY);
  }

  preload(): void {
    const ids = [1, 16, 24, 32];
    ids.forEach((id, i) => {
      this.load.image(
        `select-job-${i}`,
        assetUrl(`ui/create-ui/images/${id}-jpeg3.png`),
      );
    });
  }

  create(data: { roles?: RoleRef[] } = {}): void {
    const roles = data.roles ?? [];
    const cx = this.scale.width / 2;
    this.cameras.main.setBackgroundColor('#0a141d');

    this.add
      .text(cx, 48, 'Select character', { fontSize: '18px', color: '#f0e2c0' })
      .setOrigin(0.5);

    const rowY = (i: number): number => 140 + i * 110;
    roles.slice(0, MAX_ROLES_PER_ACCOUNT).forEach((role, i) => {
      const y = rowY(i);
      const key = JOB_PORTRAIT[role.job];
      if (key && this.textures.exists(key)) {
        this.add.image(cx - 220, y, key).setScale(0.42);
      } else {
        this.add.rectangle(cx - 220, y, 72, 72, 0x14202c).setStrokeStyle(1, 0x8a97a3);
        this.add
          .text(cx - 220, y, `job ${role.job || '?'}`, {
            fontSize: '11px',
            color: '#8a97a3',
          })
          .setOrigin(0.5);
      }
      const label = this.add
        .text(cx - 160, y - 18, role.name, { fontSize: '16px', color: '#e8f2fa' })
        .setInteractive({ useHandCursor: true });
      this.add.text(cx - 160, y + 8, `Job ${role.job} · Lv ${role.level}`, {
        fontSize: '13px',
        color: '#9fc3d8',
      });
      const hit = this.add
        .rectangle(cx, y, 460, 92)
        .setStrokeStyle(1, 0x2c3f52)
        .setInteractive({ useHandCursor: true });
      const pick = (): void => {
        this.events.emit('roleselect', { id: role.id });
      };
      label.on('pointerdown', pick);
      hit.on('pointerdown', pick);
      hit.on('pointerover', () => hit.setStrokeStyle(2, 0xffd76a));
      hit.on('pointerout', () => hit.setStrokeStyle(1, 0x2c3f52));
    });

    const empty = MAX_ROLES_PER_ACCOUNT - Math.min(roles.length, MAX_ROLES_PER_ACCOUNT);
    for (let i = 0; i < empty; i += 1) {
      const y = rowY(roles.length + i);
      const slot = this.add
        .rectangle(cx, y, 460, 92)
        .setStrokeStyle(1, 0x2c3f52, 0.6)
        .setInteractive({ useHandCursor: true });
      this.add
        .text(cx, y, empty > 0 && roles.length < MAX_ROLES_PER_ACCOUNT ? 'Empty slot — create' : 'Empty slot', {
          fontSize: '13px',
          color: '#8a97a3',
        })
        .setOrigin(0.5);
      slot.on('pointerdown', () => this.events.emit('gocreate', {}));
    }

    if (roles.length >= MAX_ROLES_PER_ACCOUNT) {
      this.add
        .text(cx, rowY(MAX_ROLES_PER_ACCOUNT) + 10, 'Slots full (4/4).', {
          fontSize: '12px',
          color: '#8a97a3',
        })
        .setOrigin(0.5);
    }

    this.add
      .text(cx, rowY(MAX_ROLES_PER_ACCOUNT) + 34, 'Art: recovered create-ui bitmaps. Layout follows the module; timeline effects pending decode.', {
        fontSize: '11px',
        color: '#5c6b78',
      })
      .setOrigin(0.5);
  }
}

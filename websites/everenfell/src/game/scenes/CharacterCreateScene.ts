/** Character creation: recovered create-ui module art, server-authoritative data.
 *
 * Bitmap semantics decoded from the module contact sheet (not guessed):
 * 12 = backdrop banner, 14 = title text, 1/16/24/32 = class portraits,
 * 5/21/28/35 = class icons, 4/27 = gender symbols, 39 = name input box,
 * 40 = name label, 42/44/46 = random-name dice states, 9 = selection ring,
 * 50 = confirm button, 53/55/57 = start-game button states, 63 = the
 * create-screen entry badge (shown on the selection screen).
 *
 * Layout is still provisional: the SWF's 15 DefineSprite timelines
 * (ui.asyncpanel.createUI + ui.shared.create.A/B/C/D) have been decoded
 * to placement trees but are not yet re-driven in Phaser, so positions
 * here are manual. Name entry stays in the DOM panel (Phaser has no
 * text input); sex stays 0 until the gender toggle is reconstructed.
 */
import Phaser from 'phaser';

export const CREATE_KEY = 'create';

/** create-ui bitmaps that exist on disk (websites/everenfell/assets/ui/create-ui). */
const BG = 'create-bg';
const TITLE = 'create-title';
const RING = 'create-ring';
const PORTRAIT_IDS = [1, 16, 24, 32] as const;

function assetUrl(path: string): string {
  return `${import.meta.env.DEV ? '/assets/' : '/protected-assets/'}${path}`;
}

function img(id: number, kind: string): string {
  return `ui/create-ui/images/${id}-${kind}.png`;
}

export class CharacterCreateScene extends Phaser.Scene {
  constructor() {
    super(CREATE_KEY);
  }

  preload(): void {
    this.load.image(BG, assetUrl(img(12, 'jpeg3')));
    this.load.image(TITLE, assetUrl(img(14, 'lossless2')));
    this.load.image(RING, assetUrl(img(9, 'jpeg3')));
    PORTRAIT_IDS.forEach((id, i) => {
      this.load.image(`create-job-${i}`, assetUrl(img(id, 'jpeg3')));
    });
  }

  create(data: { selected?: number } = {}): void {
    const selected = data.selected ?? 0;
    const cx = this.scale.width / 2;
    this.cameras.main.setBackgroundColor('#0a141d');
    const missing: string[] = [];
    const need = (key: string): boolean => {
      if (!this.textures.exists(key)) {
        missing.push(key);
        return false;
      }
      return true;
    };

    if (need(BG)) {
      const bg = this.add.image(cx, 300, BG);
      bg.setDisplaySize(
        Math.min(this.scale.width - 32, (bg.width / bg.height) * 512),
        Math.min(512, ((this.scale.width - 32) / bg.width) * bg.height),
      );
    }
    if (need(TITLE)) this.add.image(cx, 64, TITLE);
    this.add
      .text(cx, 100, 'Create character', { fontSize: '14px', color: '#f0e2c0' })
      .setOrigin(0.5);

    const jobs = ['A', 'B', 'C', 'D'];
    const startX = cx - 1.5 * 190;
    PORTRAIT_IDS.forEach((_, i) => {
      const key = `create-job-${i}`;
      const x = startX + i * 190;
      const y = 300;
      if (need(key)) {
        const portrait = this.add
          .image(x, y, key)
          .setInteractive({ useHandCursor: true });
        portrait.setScale(0.85);
        portrait.setAlpha(i === selected ? 1 : 0.55);
        portrait.on('pointerdown', () => {
          this.registry.set('createJob', i);
          this.events.emit('jobselect', { index: i, job: jobs[i] });
          this.scene.restart({ selected: i });
        });
        if (i === selected && this.textures.exists(RING)) {
          this.add.image(x, y, RING).setScale(0.95);
        }
      } else {
        this.add.rectangle(x, y, 150, 150, 0x14202c).setStrokeStyle(1, 0x8a97a3);
      }
      this.add
        .text(x, y + 95, `Job ${jobs[i]}`, { fontSize: '13px', color: '#cfe3f0' })
        .setOrigin(0.5);
    });

    if (missing.length > 0) {
      this.add
        .text(cx, 500, `Missing art (shown as defect, not replaced): ${missing.join(', ')}`, {
          fontSize: '11px',
          color: '#8a97a3',
        })
        .setOrigin(0.5);
    } else {
      this.add
        .text(
          cx,
          500,
          'Portraits: recovered create-ui bitmaps 1/16/24/32. Name entry is in the panel below.',
          { fontSize: '12px', color: '#8a97a3' },
        )
        .setOrigin(0.5);
    }
  }
}

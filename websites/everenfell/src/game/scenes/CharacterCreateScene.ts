/** Character creation: recovered create-ui module art, server-authoritative data.
 *
 * Layout is evidence-driven, not a redesign: the 935x512 panel (12) is the
 * backdrop, the four 171x171 portraits (1/16/24/32) select jobs A/B/C/D in
 * order, the 229x40 bar (39) is the title strip. Portrait 63 (fifth
 * 171x171) has no verified job mapping and is shown dimmed as UNVERIFIED
 * rather than hidden. Buttons/labels (5/21/28/35/14/40/61) land in later
 * passes once timeline order is decoded; missing files render as labeled
 * boxes, never silent blanks. Name entry lives in the DOM panel (client.ts)
 * because Phaser has no native text input; the scene owns art + selection.
 */
import Phaser from 'phaser';

export const CREATE_KEY = 'create';

/** create-ui bitmaps that exist on disk (websites/everenfell/assets/ui/create-ui). */
const BG = 'create-bg';
const TITLE_BAR = 'create-title';
const PORTRAIT_IDS = [1, 16, 24, 32] as const;
const UNVERIFIED_PORTRAIT_ID = 63;

function assetUrl(path: string): string {
  return `${import.meta.env.DEV ? '/assets/' : '/protected-assets/'}${path}`;
}

function img(id: number, kind: string): string {
  return `ui/create-ui/images/${id}-${kind}.png`;
}

export class CharacterCreateScene extends Phaser.Scene {
  private missing: string[] = [];

  constructor() {
    super(CREATE_KEY);
  }

  preload(): void {
    this.missing = [];
    this.load.image(BG, assetUrl(img(12, 'jpeg3')));
    this.load.image(TITLE_BAR, assetUrl(img(39, 'jpeg3')));
    PORTRAIT_IDS.forEach((id, i) => {
      this.load.image(`create-job-${i}`, assetUrl(img(id, 'jpeg3')));
    });
    this.load.image(
      'create-job-unverified',
      assetUrl(img(UNVERIFIED_PORTRAIT_ID, 'jpeg3')),
    );
    this.load.on('loaderror', (file: { key?: string }) => {
      if (file?.key) this.missing.push(file.key);
    });
  }

  create(data: { selected?: number } = {}): void {
    const selected = data.selected ?? 0;
    const cx = this.scale.width / 2;
    this.cameras.main.setBackgroundColor('#0a141d');

    if (this.textures.exists(BG)) {
      const bg = this.add.image(cx, 300, BG);
      bg.setDisplaySize(
        Math.min(this.scale.width - 32, (bg.width / bg.height) * 512),
        Math.min(512, ((this.scale.width - 32) / bg.width) * bg.height),
      );
    } else {
      this.box(cx, 300, 700, 512, 'missing backdrop 12');
    }

    if (this.textures.exists(TITLE_BAR)) {
      this.add.image(cx, 64, TITLE_BAR);
    }
    this.add
      .text(cx, 64, 'Create character (original art)', {
        fontSize: '14px',
        color: '#f0e2c0',
      })
      .setOrigin(0.5);

    const jobs = ['A', 'B', 'C', 'D'];
    const startX = cx - 1.5 * 190;
    PORTRAIT_IDS.forEach((_, i) => {
      const key = `create-job-${i}`;
      const x = startX + i * 190;
      const y = 300;
      if (this.textures.exists(key)) {
        const portrait = this.add.image(x, y, key).setInteractive({ useHandCursor: true });
        portrait.setScale(0.85);
        portrait.setAlpha(i === selected ? 1 : 0.55);
        portrait.setData('jobIndex', i);
        portrait.on('pointerdown', () => {
          this.registry.set('createJob', i);
          this.events.emit('jobselect', { index: i, job: jobs[i] });
          this.scene.restart({ selected: i });
        });
        if (i === selected) {
          this.add.rectangle(x, y, 150, 150).setStrokeStyle(3, 0xffd76a);
        }
      } else {
        this.box(x, y, 150, 150, `missing portrait ${PORTRAIT_IDS[i]}`);
      }
      this.add
        .text(x, y + 95, `Job ${jobs[i]}`, { fontSize: '13px', color: '#cfe3f0' })
        .setOrigin(0.5);
    });

    // Fifth 171x171 portrait: recovered but unmapped. Shown dimmed and
    // labeled, never silently dropped or promoted to a fifth class.
    const ux = startX + 4 * 190;
    if (this.textures.exists('create-job-unverified')) {
      this.add.image(ux, 300, 'create-job-unverified').setScale(0.5).setAlpha(0.35);
    } else {
      this.box(ux, 300, 90, 90, 'missing portrait 63');
    }
    this.add
      .text(ux, 360, 'UNVERIFIED', { fontSize: '11px', color: '#8a97a3' })
      .setOrigin(0.5);

    this.add
      .text(
        cx,
        500,
        'Portraits: recovered create-ui bitmaps 1/16/24/32. Name entry is in the panel below.',
        { fontSize: '12px', color: '#8a97a3' },
      )
      .setOrigin(0.5);
  }

  private box(x: number, y: number, w: number, h: number, label: string): void {
    this.add.rectangle(x, y, w, h, 0x14202c).setStrokeStyle(1, 0x8a97a3);
    this.add
      .text(x, y, label, { fontSize: '11px', color: '#8a97a3' })
      .setOrigin(0.5);
  }
}

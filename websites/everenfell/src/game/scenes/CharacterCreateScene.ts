/** Character creation: SWF-driven reconstruction of ui.asyncpanel.createUI.
 *
 * Geometry comes from scripts/asset_tools/decode_create_ui.py output
 * (websites/everenfell/src/assets/create-ui-layout.json), not manual
 * placement. Authored Flash stage is 935x512 (shape 13 bounds); sprite 60
 * (dele_create, at panel offset +15,-10 in sprite 67) places class tabs
 * A/B/C/D at (90/300/516.05/713.95,100), the title strip (shape 15 ->
 * bitmap 14) at (450,24), the name label (shape 41 -> bitmap 40) at
 * (279,388), txt_name at (387,392), and btn_start (sprite 59 -> bitmap
 * 53) at (375,432). Each class sprite carries its portrait, icon ribbon
 * (A=35, B=21, C=28, D=5) at local (27,163), motto edittext at local
 * (2,205), and a frame-2 highlight ring (shape 10 -> bitmap 9).
 *
 * Product decisions layered on the reconstruction (see
 * docs/create-ui-localization.md): gender symbols render Male, Female,
 * Male, Female across A/B/C/D (bitmap 27 male, bitmap 4 female — only
 * B's placement is authored, the rest follow the game's own pattern);
 * the stamp (bitmap 50, now reading "Creation") follows the selected
 * slot instead of its fixed selectmc position; the random-name dice is
 * not rendered (no random names supplied); the name field is an HTML
 * overlay on the box art (CREATE_GEOM below gives the client its rect);
 * START GAME is clickable and creates the character straight into the
 * world. The "等 級" initial text of txt_name is not rendered.
 */
import Phaser from 'phaser';
import { letterbox, STAGE_H, STAGE_W } from '../stage';

export const CREATE_KEY = 'create';

/** Flash stage size (backdrop shape 13 bounds). */
const FLASH_W = STAGE_W;
const FLASH_H = STAGE_H;

/** Panel offset of dele_create (sprite 60) inside createUI (sprite 67). */
const PANEL_X = 15;
const PANEL_Y = -10;

/** Geometry the client needs to overlay the HTML name field on the box. */
export const CREATE_GEOM = {
  FLASH_W,
  FLASH_H,
  PANEL_X,
  PANEL_Y,
  NAME_FIELD: { x: 387, y: 392, w: 182, h: 19 },
} as const;

/** Class tabs in screen order: job, slot origin, portrait/ribbon art. */
const SLOTS = [
  { job: 'A', x: 90, y: 100, portrait: 32, ribbon: 35, ringDx: 0, bgDx: 0, gender: 27 },
  { job: 'B', x: 300, y: 100, portrait: 16, ribbon: 21, ringDx: -4, bgDx: -4, gender: 4 },
  { job: 'C', x: 516.05, y: 100, portrait: 24, ribbon: 28, ringDx: -1, bgDx: 0, gender: 27 },
  { job: 'D', x: 713.95, y: 100, portrait: 1, ribbon: 5, ringDx: 0, bgDx: 0, gender: 4 },
] as const;

/** Motto lines (layout JSON edittexts 37/20/30/8; approved English from
 * the localization glossary — flavor text, not gameplay promises). */
const MOTTOS: Record<string, [string, string]> = {
  A: ['A fearless trickster born of stone and storm.', 'Too swift to catch, too bold to cage.'],
  B: ['Grace and guile in the shape of a fox.', 'Her beauty charms; her bite kills.'],
  C: ['A towering warrior of raw strength and iron will.', 'Nothing can stand in his path.'],
  D: ['A fierce warrior wreathed in hellfire.', 'Her fury leaves only ashes behind.'],
};

function assetUrl(path: string): string {
  return `${import.meta.env.DEV ? '/assets/' : '/protected-assets/'}${path}`;
}

function img(id: number, kind: string): string {
  return `ui/create-ui/images/${id}-${kind}.png`;
}

const BITMAP_KIND: Record<number, string> = {
  1: 'jpeg3', 4: 'lossless2', 5: 'jpeg3', 9: 'jpeg3', 12: 'jpeg3',
  14: 'lossless2', 16: 'jpeg3', 21: 'jpeg3', 24: 'jpeg3', 28: 'jpeg3',
  32: 'jpeg3', 35: 'jpeg3', 39: 'jpeg3', 40: 'lossless2',
  50: 'jpeg3', 53: 'jpeg3', 27: 'lossless2',
};

export class CharacterCreateScene extends Phaser.Scene {
  constructor() {
    super(CREATE_KEY);
  }

  preload(): void {
    const ids = new Set<number>([12, 14, 9, 40, 39, 50, 53, 4, 27]);
    for (const slot of SLOTS) {
      ids.add(slot.portrait);
      ids.add(slot.ribbon);
    }
    ids.forEach((id) => {
      this.load.image(`cu-${id}`, assetUrl(img(id, BITMAP_KIND[id])));
    });
  }

  create(data: { selected?: number } = {}): void {
    const selected = data.selected ?? 0;
    const viewW = this.scale.width;
    const viewH = this.scale.height;
    this.cameras.main.setBackgroundColor('#000000');
    const { s, ox, oy } = letterbox(viewW, viewH);
    if (!(s > 0)) return;
    const X = (x: number): number => ox + (PANEL_X + x) * s;
    const Y = (y: number): number => oy + (PANEL_Y + y) * s;
    /** Stage-space (pre-panel-offset) placement, e.g. the backdrop. */
    const SX = (x: number): number => ox + x * s;
    const SY = (y: number): number => oy + y * s;

    const missing: string[] = [];
    const need = (key: string): boolean => {
      if (!this.textures.exists(key)) {
        missing.push(key);
        return false;
      }
      return true;
    };
    /** Top-left-anchored art: authored translate is the bitmap origin. */
    const art = (key: string, x: number, y: number, usePanel = true): void => {
      if (!need(key)) return;
      const px = usePanel ? X(x) : SX(x);
      const py = usePanel ? Y(y) : SY(y);
      this.add.image(px, py, key).setOrigin(0, 0).setScale(s);
    };

    // Backdrop (shape 13 -> bitmap 12, stage origin, no panel offset).
    if (need('cu-12')) {
      this.add.image(SX(0), SY(0), 'cu-12').setOrigin(0, 0).setDisplaySize(FLASH_W * s, FLASH_H * s);
    }
    // Title strip (shape 15 -> bitmap 14 at (450,24)).
    art('cu-14', 450, 24);

    const jobs = SLOTS.map((slot) => slot.job);
    SLOTS.forEach((slot, i) => {
      const key = `cu-${slot.portrait}`;
      if (need(key)) {
        const portrait = this.add
          .image(X(slot.x + slot.bgDx), Y(slot.y), key)
          .setOrigin(0, 0)
          .setScale(s)
          .setInteractive({ useHandCursor: true });
        portrait.setAlpha(i === selected ? 1 : 0.55);
        portrait.on('pointerdown', () => {
          this.registry.set('createJob', i);
          this.events.emit('jobselect', { index: i, job: jobs[i] });
          this.scene.restart({ selected: i });
        });
      }
      // Icon ribbon (shape 6/22/29/36 -> bitmap at local (27,163)).
      art(`cu-${slot.ribbon}`, slot.x + 27, slot.y + 163);
      // Gender symbols: Male, Female, Male, Female across A/B/C/D at the
      // local offset authored for B (shape 19 at (120,120)).
      art(`cu-${slot.gender}`, slot.x + 120, slot.y + 120);
      // Motto zone at local (2,205), 171px wide #ece5cb. English lines run
      // far longer than the 7-glyph Chinese originals, so the blurb wraps
      // inside its own column instead of bleeding into the neighboring
      // class. Georgia suits the Latin glyphs; CJK fallback stays for any
      // untranslated string.
      const motto = MOTTOS[slot.job];
      const blurb = Array.isArray(motto) ? motto.join('\n') : '';
      this.add
        .text(X(slot.x + 2 + 85.5), Y(slot.y + 205), blurb, {
          fontFamily: 'Georgia, "SimSun", "Songti SC", serif',
          fontSize: `${Math.max(10, Math.round(12 * s))}px`,
          color: '#ece5cb',
          align: 'center',
          wordWrap: { width: 195 * s },
          lineSpacing: 6,
        })
        .setOrigin(0.5, 0);
      // Frame-2 highlight ring on the selected tab.
      if (i === selected) art('cu-9', slot.x + slot.ringDx + 13, slot.y + 11);
    });

    // "Creation" stamp follows the selected slot, centered on its
    // top-left corner (replaces the fixed selectmc position).
    const sel = SLOTS[selected] ?? SLOTS[0];
    if (need('cu-50')) {
      this.add
        .image(X(sel.x), Y(sel.y), 'cu-50')
        .setOrigin(0.5, 0.5)
        .setScale(s);
    }
    // Name label art (shape 41 -> bitmap 40 at (279,388)).
    art('cu-40', 279, 388);
    // Name input box art (bitmap 39, code-attached; position inferred
    // from shape-41 bounds). The functional field is an HTML overlay
    // (see CREATE_GEOM); the dice is intentionally not rendered.
    art('cu-39', 373, 377);
    // START GAME (sprite 59 -> bitmap 53 at (375,432)): clickable, creates
    // the character straight into the world via 'createstart'.
    if (need('cu-53')) {
      const start = this.add
        .image(X(375), Y(432), 'cu-53')
        .setOrigin(0, 0)
        .setScale(s)
        .setInteractive({ useHandCursor: true });
      start.on('pointerover', () => start.setTint(0xfff2cc));
      start.on('pointerout', () => start.clearTint());
      start.on('pointerdown', () => this.events.emit('createstart', {}));
    }

    if (missing.length > 0) {
      this.add
        .text(viewW / 2, viewH - 24, `Missing art (shown as defect, not replaced): ${missing.join(', ')}`, {
          fontSize: '11px',
          color: '#8a97a3',
          backgroundColor: '#000000',
        })
        .setOrigin(0.5);
    }
  }
}

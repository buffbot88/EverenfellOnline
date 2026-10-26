/** Character selection: SWF-driven reconstruction of the dele_select panel.
 *
 * Geometry comes from scripts/asset_tools/decode_create_ui.py output
 * (websites/everenfell/src/assets/create-ui-layout.json). Sprite 66
 * (dele_select, at panel offset +14,-7.95 in sprite 67) places the title
 * strip (shape 62 -> bitmap 61, SELECT) at (450,23) and four slot badges
 * b1..b4 (sprite 65 -> bitmap 63, 171x171) at x = 98/296/516/714,
 * y = 100. Both panels share the createUI root backdrop (sprite 67:
 * shape 13 -> bitmap 12, 935x512 stage), so it renders here too.
 *
 * Owned characters are code-attached in the original (no portrait
 * placements in sprite 66): role i occupies badge slot i with its class
 * portrait (A=32, B=16, C=24, D=1 from SymbolClass containment) and
 * name/level in the motto zone below. Empty slots keep the authored
 * badge art; clicking one emits 'gocreate'.
 *
 * Product behavior layered on the reconstruction: clicking a portrait
 * selects it (the "SELECTION" stamp, bitmap 50b, follows the selected
 * slot), and START GAME (bitmap 53) enters the world with the selected
 * character via 'startworld'. Entry still flows through world.snapshot
 * so ownership stays server-enforced.
 */
import Phaser from 'phaser';
import { MAX_ROLES_PER_ACCOUNT, jobName, type RoleRef } from '../../net/protocol';
import { letterbox, STAGE_H, STAGE_W } from '../stage';

export const SELECT_KEY = 'select';

/** Flash stage size (backdrop shape 13 bounds). */
const FLASH_W = STAGE_W;
const FLASH_H = STAGE_H;

/** Panel offset of dele_select (sprite 66) inside createUI (sprite 67). */
const PANEL_X = 14;
const PANEL_Y = -7.95;

/** Badge slot origins (sprite 66 depths 4/6/8/10, pre-panel-offset). */
const BADGE_X = [98, 296, 516, 714] as const;
const BADGE_Y = 100;

/** Class portrait bitmap by job (class sprites 38/23/31/11). */
const JOB_PORTRAIT: Record<string, number> = { A: 32, B: 16, C: 24, D: 1 };

function assetUrl(path: string): string {
  return `${import.meta.env.DEV ? '/assets/' : '/protected-assets/'}${path}`;
}

function img(id: number, kind: string): string {
  return `ui/create-ui/images/${id}-${kind}.png`;
}

export class CharacterSelectScene extends Phaser.Scene {
  constructor() {
    super(SELECT_KEY);
  }

  preload(): void {
    this.load.image('sel-bg', assetUrl(img(12, 'jpeg3')));
    this.load.image('sel-title', assetUrl(img(61, 'lossless2')));
    this.load.image('sel-badge', assetUrl(img(63, 'jpeg3')));
    this.load.image('sel-stamp', assetUrl('ui/create-ui/images/50b-selection.png'));
    this.load.image('sel-start', assetUrl(img(53, 'jpeg3')));
    for (const id of new Set(Object.values(JOB_PORTRAIT))) {
      this.load.image(`sel-job-${id}`, assetUrl(img(id, 'jpeg3')));
    }
  }

  create(data: { roles?: RoleRef[]; selected?: string | null } = {}): void {
    const roles = (data.roles ?? []).slice(0, MAX_ROLES_PER_ACCOUNT);
    const selectedId = data.selected ?? roles[0]?.id ?? null;
    const viewW = this.scale.width;
    const viewH = this.scale.height;
    this.cameras.main.setBackgroundColor('#000000');
    const { s, ox, oy } = letterbox(viewW, viewH);
    if (!(s > 0)) return;
    const X = (x: number): number => ox + (PANEL_X + x) * s;
    const Y = (y: number): number => oy + (PANEL_Y + y) * s;
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

    if (need('sel-bg')) {
      this.add.image(SX(0), SY(0), 'sel-bg').setOrigin(0, 0).setDisplaySize(FLASH_W * s, FLASH_H * s);
    }
    if (need('sel-title')) {
      this.add.image(X(450), Y(23), 'sel-title').setOrigin(0, 0).setScale(s);
    }

    const fontSize = (px: number): string => `${Math.max(10, Math.round(px * s))}px`;
    BADGE_X.forEach((bx, i) => {
      const role = roles[i];
      if (role) {
        const key = `sel-job-${JOB_PORTRAIT[role.job] ?? 1}`;
        if (need(key)) {
          const portrait = this.add
            .image(X(bx), Y(BADGE_Y), key)
            .setOrigin(0, 0)
            .setScale(s)
            .setInteractive({ useHandCursor: true });
          portrait.setAlpha(role.id === selectedId ? 1 : 0.55);
          portrait.on('pointerdown', () => {
            this.events.emit('roleselect', { id: role.id });
            this.scene.restart({ roles, selected: role.id });
          });
        }
        this.add
          .text(X(bx + 85.5), Y(BADGE_Y + 218), role.name, {
            fontFamily: 'Georgia, "SimSun", "Songti SC", serif',
            fontSize: fontSize(16),
            color: '#e8f2fa',
          })
          .setOrigin(0.5);
        this.add
          .text(X(bx + 85.5), Y(BADGE_Y + 238), `${jobName(role.job)} · Lv ${role.level}`, {
            fontFamily: 'Georgia, "SimSun", "Songti SC", serif',
            fontSize: fontSize(13),
            color: '#9fc3d8',
          })
          .setOrigin(0.5);
        // "SELECTION" stamp follows the selected slot.
        if (role.id === selectedId && need('sel-stamp')) {
          this.add
            .image(X(bx), Y(BADGE_Y), 'sel-stamp')
            .setOrigin(0.5, 0.5)
            .setScale(s);
        }
      } else {
        if (need('sel-badge')) {
          const badge = this.add
            .image(X(bx), Y(BADGE_Y), 'sel-badge')
            .setOrigin(0, 0)
            .setScale(s)
            .setInteractive({ useHandCursor: true });
          badge.on('pointerdown', () => this.events.emit('gocreate', {}));
        }
      }
    });

    // START GAME enters the world with the selected character.
    if (need('sel-start')) {
      const start = this.add
        .image(X(375), Y(432), 'sel-start')
        .setOrigin(0, 0)
        .setScale(s)
        .setInteractive({ useHandCursor: true });
      start.on('pointerover', () => start.setTint(0xfff2cc));
      start.on('pointerout', () => start.clearTint());
      start.on('pointerdown', () => {
        if (selectedId) this.events.emit('startworld', { id: selectedId });
      });
    }

    if (roles.length >= MAX_ROLES_PER_ACCOUNT) {
      this.add
        .text(viewW / 2, viewH - 40, 'Slots full (4/4).', {
          fontSize: '12px',
          color: '#8a97a3',
          backgroundColor: '#000000',
        })
        .setOrigin(0.5);
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

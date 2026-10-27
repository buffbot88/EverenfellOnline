/** HUD overlay: SWF-driven reconstruction (hud-layout.json).
 *
 * Each component renders its decoded bitmap leaves at authored Flash-px
 * offsets (accumulated PlaceObject translates, see
 * scripts/asset_tools/resolve_hud_bitmaps.py). Components are anchored to
 * screen regions from the locked reference (docs/inworld-hud-target.jpg);
 * global positions are code-positioned in the original, so anchors are
 * documented approximations, but every bitmap position *within* a
 * component is authored, not eyeballed.
 *
 * Zero-art components (ui.HeroBar/HpBar/BloodShape: vector-only shapes)
 * are skipped until vector/shape recovery lands. Imported tg.shared.*
 * leaves are gaps, not guessed.
 */
import Phaser from 'phaser';
import layout from '../../assets/hud-layout.json';

export const UI_KEY = 'ui';

function assetUrl(path: string): string {
  return `${import.meta.env.DEV ? '/assets/' : '/protected-assets/'}${path}`;
}

interface ArtLeaf {
  bitmap: number;
  png: string;
  w: number;
  h: number;
  x: number;
  y: number;
}

/** Screen anchors per component (region approximations; intra-artwork is authored). */
const ANCHORS: Record<string, { x: number; y: number; originX: number; originY: number }> = {
  'ui.StateBar': { x: 12, y: 12, originX: 0, originY: 0 },
  'ui.ZDLView': { x: 12, y: 64, originX: 0, originY: 0 },
  'ui.panel.Target': { x: 0.5, y: 0, originX: 0.5, originY: 0 },
  'ui.ChatSkin': { x: 12, y: -12, originX: 0, originY: 1 },
  'ui.panel.TaskTrack': { x: -12, y: 200, originX: 1, originY: 0 },
  'ui.MiniMap': { x: -12, y: 12, originX: 1, originY: 0 },
};

const FOCUS = ['ui.StateBar', 'ui.ZDLView', 'ui.panel.Target', 'ui.ChatSkin', 'ui.panel.TaskTrack', 'ui.MiniMap'];

export class UIScene extends Phaser.Scene {
  constructor() {
    super(UI_KEY);
  }

  preload(): void {
    const comps = (layout as { components: Record<string, { art: ArtLeaf[] }> }).components;
    for (const name of FOCUS) {
      const comp = comps[name];
      if (!comp) continue;
      for (const leaf of comp.art) {
        const key = `hud-${name}-${leaf.bitmap}`;
        this.load.image(key, assetUrl(leaf.png));
      }
    }
  }

  create(): void {
    const comps = (layout as { components: Record<string, { art: ArtLeaf[] }> }).components;
    const W = this.scale.width;
    const H = this.scale.height;
    let missing = 0;
    for (const name of FOCUS) {
      const comp = comps[name];
      const anchor = ANCHORS[name];
      if (!comp || !anchor) continue;
      // Normalize: shift leaves so the component's min corner is local (0,0).
      let minX = Infinity;
      let minY = Infinity;
      for (const leaf of comp.art) {
        minX = Math.min(minX, leaf.x);
        minY = Math.min(minY, leaf.y);
      }
      if (!Number.isFinite(minX)) continue;
      // anchor.x: 0.5 with originX 0.5 = horizontal center; negative =
      // offset from the right edge; otherwise absolute px from left.
      // anchor.y: negative = offset from bottom; otherwise px from top.
      // The component's min corner sits at the anchor point.
      const baseX = anchor.originX === 0.5 ? W * anchor.x : anchor.x < 0 ? W + anchor.x : anchor.x;
      const baseY = anchor.y < 0 ? H + anchor.y : anchor.y;
      for (const leaf of comp.art) {
        const key = `hud-${name}-${leaf.bitmap}`;
        if (!this.textures.exists(key)) {
          missing += 1;
          continue;
        }
        const img = this.add.image(baseX + (leaf.x - minX), baseY + (leaf.y - minY), key);
        img.setOrigin(0, 0).setScrollFactor(0).setDepth(1000);
      }
    }
    if (missing > 0) {
      const label = this.add.text(16, H - 28, `HUD: ${missing} art missing (see manifest gaps)`, {
        fontSize: '12px',
        color: '#8a93a0',
      });
      label.setScrollFactor(0).setDepth(1001);
    }
  }
}

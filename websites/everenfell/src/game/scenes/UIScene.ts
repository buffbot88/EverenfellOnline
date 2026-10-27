/** In-world HUD: SWF-driven reconstruction, roleheadskin first.
 *
 * Source: hud-chat / gameui recovered modules, decoded with
 * scripts/asset_tools (dump_hud_frames.py, parse_edittext). The layout
 * table (hud-layout.json) carries authored Flash-px leaf offsets; global
 * screen anchors below are documented approximations EXCEPT roleheadskin
 * at (0,0) top-left and the conditional Target rule.
 *
 * Provenance per roleheadskin (ui.panel.roleheadskin, cid 313, hud-chat):
 * - Frame is a single-frame sprite; every row below is translate-only
 *   (no scale/rotate anywhere in the component), so authored offsets
 *   stand as drawn. Full matrices on record in output/hud-frames.json.
 * - Base art: bitmap 212 (361x131) at (0,0), vector shape 213.
 * - Portrait photo is code-attached (no portrait placement in the SWF,
 *   same pattern as createUI badges). Circle geometry is APPROXIMATE:
 *   center (56,74) r34 estimated from the bitmap-212 emblem; the class
 *   portrait (create-ui stills A:32 B:16 C:24 D:1) is masked into it.
 *   Verify against the running screenshot before refining.
 * - tf0 name (edittext 288? no: 304) at (98,13.4): SimSun 14px #bbae8e,
 *   centered, bounds 34x18, initial "100".
 * - tf1 level (edittext 288) at (132,43), above the qiangBtn: SimSun
 *   12px #c6b8a5, centered, bounds 110x18. Gateway exposes the role
 *   level, so this binds live digits; the original shows digits only.
 * - zdl combat banner (sprite 302) at (156,59): shape 301 vector chrome
 *   (unrenderable gap) + bitmap 300 (44x18 战闘力 label) at (156,68).
 *   The numeric value was code-set text; the JSON gateway does not
 *   expose 12010/ZhanDouLi, so NO value is rendered (inventing one
 *   would be fabrication). Banner art only, gap documented.
 * - Buttons are 4-frame sprites (up/over/down/disabled via color
 *   transforms on vector shapes) with bitmap icons layered on top:
 *   czbtn (220: shape 215 + 214 儲值 art) at (288,38);
 *   vipbtn (252: shape + 221 art + viplevel digit sprite 247 holding
 *   223/224/245) at (236,38) — VIP rank is not gateway-exposed, so
 *   the digit layer is skipped, gap documented;
 *   qiangBtn (259: shape 254 + 253 強 art) at (131,65);
 *   btn_icon11 (267: shape 261 + 260 demon-face art) at (391,37) with
 *   label (262) 獅駝嶺 at rel (0,41);
 *   btn_qibing (279: shape 269 + 268 staff art) at (394,30) with label
 *   bg 270 at rel (0,47) and label (278) 騎戰/兵器 at rel (-1,50);
 *   btn_icon12 (287: shape 281 + 280 art) at (456,37) with label (282)
 *   聖誕禮包 at rel (1,41);
 *   pk (299, 5-frame shape cycle + 289 crossed-swords art) at (0,63);
 *   buffBtn (312: shape 306 + 305 plate art) at (44,104) with label
 *   (307) 克己 at rel (18.1,5).
 * - Button behaviors, VIP/digit states, and buff/pk actions need the
 *   original ActionScript plus server features: buttons render as
 *   static art (non-interactive), gaps documented, not stubbed.
 * - Chinese label textfields are localized in-code (first English
 *   pass): CAVALRY / SHITUO RIDGE / GIFT PACK / RESTRAINT. Baked-art
 *   Chinese (214 儲值, 253 強, 300 戦闘力, VIP letters) still needs the
 *   Ultima3D/Blender rebuild — queued, not faked with overlay text.
 *
 * Contextual visibility (from SWF structure, not aesthetics):
 * - ui.panel.Target renders ONLY when a target is provided. It has its
 *   own close button (closeBtn at (318.45,66)) and op button in the
 *   source, i.e. it is a state-driven panel, not persistent chrome.
 * - Dialog/panel components (maiyao, NpcTalkPanel, TaskTalkPanel,
 *   fuhuoPanel, ListMenu, caijiBar, Gain, Dazuo, ChatCombox ...) are
 *   not persistent HUD and stay unrendered until their systems exist.
 *
 * Anchoring: component extents below are MEASURED from hud-layout.json
 * leaf bounds (ChatSkin y -244..32, TaskTrack x -74..244 included), so
 * right/bottom-anchored components subtract their true size instead of
 * clipping past the viewport edge (the previous right-edge fragments).
 * Top-left roleheadskin is exact; the rest remain approximations of the
 * original code-positioned layout until ActionScript rules are found.
 */
import Phaser from 'phaser';
import hudLayout from '../../assets/hud-layout.json';

export const UI_KEY = 'ui';

/** Minimal target state the HUD will show; absent = panel hidden. */
export interface UITarget {
  name: string;
  level?: number;
  detail?: string;
}

export interface UIProps {
  playerName?: string;
  playerLevel?: number;
  job?: string;
  target?: UITarget | null;
}

interface ArtLeaf {
  bitmap: number;
  png: string;
  w: number;
  h: number;
  x: number;
  y: number;
  path: string[];
}

interface HudComponent {
  module: string;
  cid: number;
  art: ArtLeaf[];
  gaps: unknown[];
}

/** Measured leaf extents per component (Flash px): full size plus the
 *  offset that maps negative-authored leaves into a zero-based box. */
const DIMS: Record<string, { w: number; h: number; ox: number; oy: number }> = {
  'ui.panel.roleheadskin': { w: 511, h: 131, ox: 0, oy: 0 },
  'ui.StateBar': { w: 248, h: 15, ox: 0, oy: 0 },
  'ui.MiniMap': { w: 248, h: 181, ox: 0, oy: 0 },
  'ui.panel.TaskTrack': { w: 318, h: 619, ox: 74, oy: 0 },
  'ui.ChatSkin': { w: 300, h: 276, ox: 0, oy: 244 },
  'ui.panel.Target': { w: 353, h: 98, ox: 0, oy: 0 },
};

/** Class portrait stills (create-ui bitmap ids by job). */
const PORTRAIT_IMG: Record<string, number> = { A: 32, B: 16, C: 24, D: 1 };

/** Portrait socket: APPROXIMATE circle from the bitmap-212 emblem.
 *  Verify against the running screenshot before refining. */
const PORTRAIT_CX = 56;
const PORTRAIT_CY = 74;
const PORTRAIT_R = 34;

function assetUrl(path: string): string {
  return `${import.meta.env.DEV ? '/assets/' : '/protected-assets/'}${path}`;
}

export class UIScene extends Phaser.Scene {
  constructor() {
    super(UI_KEY);
  }

  preload(): void {
    const layout = hudLayout as unknown as { components: Record<string, HudComponent> };
    const wanted = [
      'ui.panel.roleheadskin',
      'ui.StateBar',
      'ui.MiniMap',
      'ui.panel.TaskTrack',
      'ui.ChatSkin',
      'ui.panel.Target',
    ];
    for (const key of wanted) {
      const comp = layout.components[key];
      if (!comp) continue;
      for (const leaf of comp.art) {
        // Full module-relative path: bitmap ids repeat across gameui
        // and hud-chat dumps, so the basename alone can collide.
        this.load.image(`hud-${key}-${leaf.bitmap}`, assetUrl(leaf.png));
      }
    }
    for (const [job, id] of Object.entries(PORTRAIT_IMG)) {
      this.load.image(`ui-portrait-${job}`, assetUrl(`ui/create-ui/images/${id}-jpeg3.png`));
    }
  }

  create(data: UIProps = {}): void {
    const viewW = this.scale.width;
    const viewH = this.scale.height;
    const layout = hudLayout as unknown as { components: Record<string, HudComponent> };

    /** Draw every art leaf of a component at authored offsets. */
    const drawArt = (key: string, atX: number, atY: number): void => {
      const comp = layout.components[key];
      const dims = DIMS[key];
      if (!comp || !dims) return;
      for (const leaf of comp.art) {
        const tex = `hud-${key}-${leaf.bitmap}`;
        if (!this.textures.exists(tex)) continue;
        this.add
          .image(atX + leaf.x + dims.ox, atY + leaf.y + dims.oy, tex)
          .setOrigin(0, 0);
      }
    };

    // -- Upper-left character cluster: exact top-left anchor. --
    drawArt('ui.panel.roleheadskin', 0, 0);
    this.drawRoleheadData(data);

    // -- Currency bar row (mostly imported vectors; one art leaf). --
    drawArt('ui.StateBar', 350, 20);

    // -- Right column: true-size-anchored so nothing clips past edges. --
    drawArt('ui.MiniMap', viewW - DIMS['ui.MiniMap'].w - 8, 8);
    drawArt(
      'ui.panel.TaskTrack',
      viewW - 8 - 244,
      8 + DIMS['ui.MiniMap'].h + 8,
    );

    // -- Chat: bottom-left, height-corrected for negative leaves. --
    drawArt('ui.ChatSkin', 8, viewH - 8 - DIMS['ui.ChatSkin'].h);

    // -- Target panel: only with a live target, top-center. --
    if (data.target) {
      const tx = Math.max(0, (viewW - DIMS['ui.panel.Target'].w) / 2);
      drawArt('ui.panel.Target', tx, 8);
      this.drawTargetData(data.target, tx, 8);
    }
    // No standalone ZDLView: the combat banner renders once, as the zdl
    // child inside roleheadskin (bitmap 300 at its authored offset).
  }

  /** Live role data over the roleheadskin art (fonts/colors/alignment
   *  decoded from the DefineEditText tags; see module docstring). */
  private drawRoleheadData(data: UIProps): void {
    const serif = '"SimSun", "Songti SC", Georgia, serif';
    if (data.job && PORTRAIT_IMG[data.job] !== undefined && this.textures.exists(`ui-portrait-${data.job}`)) {
      const photo = this.add
        .image(PORTRAIT_CX, PORTRAIT_CY, `ui-portrait-${data.job}`)
        .setDisplaySize(PORTRAIT_R * 2, PORTRAIT_R * 2);
      const maskShape = this.make.graphics({});
      maskShape.fillCircle(PORTRAIT_CX, PORTRAIT_CY, PORTRAIT_R);
      photo.setMask(maskShape.createGeometryMask());
    }
    if (data.playerName) {
      // tf0 (cid 304): centered on its 34x18 box at (98,13.4).
      this.add
        .text(113, 20.4, data.playerName, {
          fontFamily: serif,
          fontSize: '14px',
          color: '#bbae8e',
        })
        .setOrigin(0.5, 0.5);
    }
    if (data.playerLevel !== undefined) {
      // tf1 (cid 288): centered on its 110x18 box at (132,43).
      this.add
        .text(184, 50, String(data.playerLevel), {
          fontFamily: serif,
          fontSize: '12px',
          color: '#c6b8a5',
        })
        .setOrigin(0.5, 0.5);
    }
    // Localized button labels (first English pass; baked-art Chinese
    // on 214/253/300 still queued for the Ultima3D/Blender rebuild).
    const label = (x: number, y: number, text: string, size: string, color: string): void => {
      this.add
        .text(x, y, text, { fontFamily: serif, fontSize: size, color })
        .setOrigin(0.5, 0.5);
    };
    // btn_qibing label (cid 278, 騎戰兵器) at sprite (394,30)+(-1,50).
    label(421, 98, 'CAVALRY', '12px', '#cfc7aa');
    // btn_icon11 label (cid 262, 獅駝嶺) at sprite (391,37)+(0,41).
    label(420, 87, 'SHITUO RIDGE', '12px', '#ffe9a6');
    // btn_icon12 label (cid 282, 聖誕禮包) at sprite (456,37)+(1,41).
    label(486, 87, 'GIFT PACK', '12px', '#ffe9a6');
    // buffBtn label (cid 307, 克己) at sprite (44,104)+(18.1,5).
    label(78.5, 116, 'RESTRAINT', '10px', '#ffe687');
  }

  /** Target name/level/detail over the Target art (only when targeted). */
  private drawTargetData(target: UITarget, atX: number, atY: number): void {
    const serif = '"SimSun", "Songti SC", Georgia, serif';
    // tf0 (cid 137, 14px #fed267) centered on 34x18 at (80.5,7.9).
    this.add
      .text(atX + 95.5, atY + 14.9, target.name, {
        fontFamily: serif,
        fontSize: '14px',
        color: '#fed267',
      })
      .setOrigin(0.5, 0.5);
    if (target.level !== undefined) {
      // tf1 (cid 138, 12px white) centered on 137x18 at (113,28).
      this.add
        .text(atX + 179.5, atY + 35, String(target.level), {
          fontFamily: serif,
          fontSize: '12px',
          color: '#ffffff',
        })
        .setOrigin(0.5, 0.5);
    }
    if (target.detail) {
      // label (cid 142, 12px #dbd3d0) centered on 216x25 at (102,53).
      this.add
        .text(atX + 208, atY + 63.5, target.detail, {
          fontFamily: serif,
          fontSize: '12px',
          color: '#dbd3d0',
        })
        .setOrigin(0.5, 0.5);
    }
  }
}

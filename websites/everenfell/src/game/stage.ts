/** Native Flash stage geometry (backdrop shape 13 bounds: 935x512).
 *
 * Standalone module (no imports) so scenes, the game factory, and DOM
 * overlays can share it without import cycles.
 */

/** Native Flash stage size. */
export const STAGE_W = 935;
export const STAGE_H = 512;

/** Top margin when the viewport is taller than the stage. The composition
 * anchors under the navbar; leftover space falls below, never above. */
export const TOP_MARGIN = 12;

/** Proportional scale + offsets shared by every 935x512 scene and by the
 * DOM overlays that sit on scene art (name field). */
export function letterbox(
  viewW: number,
  viewH: number,
): { s: number; ox: number; oy: number } {
  const s = Math.min(viewW / STAGE_W, viewH / STAGE_H);
  const needH = STAGE_H * s;
  const oy = viewH - needH > TOP_MARGIN * 2 ? TOP_MARGIN : Math.max(0, (viewH - needH) / 2);
  return { s, ox: (viewW - STAGE_W * s) / 2, oy };
}

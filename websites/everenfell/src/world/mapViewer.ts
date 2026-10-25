/** Local map inspection: pan and zoom only.

Rendering mode uses this to move the viewport over the recovered map. It
changes only the view container's position and scale. It never produces
gameplay intents, never calls the gateway, and never changes server state.

Controls: drag with the pointer to pan; mouse wheel zooms around the cursor;
the arrow keys pan by a fixed step. Zoom is clamped so the map stays usable.
*/
import type { Container } from 'pixi.js';

const MIN_ZOOM = 0.1;
const MAX_ZOOM = 2;
const PAN_STEP = 80;

export class MapViewer {
  private dragging = false;
  private last = { x: 0, y: 0 };
  private detach: (() => void) | null = null;

  constructor(
    private readonly target: Container,
    private readonly canvas: HTMLElement,
  ) {}

  /** Attach pointer, wheel and key controls. Returns nothing; use detach(). */
  attach(): void {
    const down = (e: PointerEvent) => {
      this.dragging = true;
      this.last = { x: e.clientX, y: e.clientY };
      this.canvas.setPointerCapture?.(e.pointerId);
    };
    const move = (e: PointerEvent) => {
      if (!this.dragging) return;
      this.target.position.set(
        this.target.position.x + (e.clientX - this.last.x),
        this.target.position.y + (e.clientY - this.last.y),
      );
      this.last = { x: e.clientX, y: e.clientY };
    };
    const up = () => {
      this.dragging = false;
    };
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
      this.zoomAt(factor, e.offsetX, e.offsetY);
    };
    const key = (e: KeyboardEvent) => {
      const step = {
        ArrowLeft: [PAN_STEP, 0],
        ArrowRight: [-PAN_STEP, 0],
        ArrowUp: [0, PAN_STEP],
        ArrowDown: [0, -PAN_STEP],
      }[e.code];
      if (!step) return;
      e.preventDefault();
      this.target.position.set(
        this.target.position.x + step[0],
        this.target.position.y + step[1],
      );
    };
    this.canvas.addEventListener('pointerdown', down);
    this.canvas.addEventListener('pointermove', move);
    this.canvas.addEventListener('pointerup', up);
    this.canvas.addEventListener('pointercancel', up);
    this.canvas.addEventListener('wheel', wheel, { passive: false });
    window.addEventListener('keydown', key);
    this.detach = () => {
      this.canvas.removeEventListener('pointerdown', down);
      this.canvas.removeEventListener('pointermove', move);
      this.canvas.removeEventListener('pointerup', up);
      this.canvas.removeEventListener('pointercancel', up);
      this.canvas.removeEventListener('wheel', wheel);
      window.removeEventListener('keydown', key);
    };
  }

  detachControls(): void {
    this.detach?.();
    this.detach = null;
  }

  /** Zoom by `factor` keeping the screen point fixed. Clamped. */
  zoomAt(factor: number, sx: number, sy: number): void {
    const oldScale = this.target.scale.x;
    const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, oldScale * factor));
    const ratio = next / oldScale;
    this.target.position.set(
      sx - (sx - this.target.position.x) * ratio,
      sy - (sy - this.target.position.y) * ratio,
    );
    this.target.scale.set(next);
  }

  get zoom(): number {
    return this.target.scale.x;
  }
}

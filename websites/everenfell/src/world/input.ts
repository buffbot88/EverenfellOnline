/** Input abstraction: devices -> tile intents.

Views and the world loop consume intents ({ dx, dy } tile steps,
interact, cancel), never raw key codes or pointer pixels. This keeps
remapping (click-to-move, WASD, virtual joystick) a local change and
keeps the network layer sending only validated tile moves.
*/

export interface MoveIntent {
  dx: number;
  dy: number;
}

export class Input {
  private keys = new Set<string>();
  private onMove: ((intent: MoveIntent) => void) | null = null;
  private onCancel: (() => void) | null = null;
  private detach: (() => void) | null = null;

  attach(target: HTMLElement): void {
    const down = (event: KeyboardEvent) => {
      this.keys.add(event.code);
      const intent = this.poll();
      if (intent) {
        event.preventDefault();
        this.onMove?.(intent);
      } else if (event.code === 'Escape') {
        this.onCancel?.();
      }
    };
    const up = (event: KeyboardEvent) => {
      this.keys.delete(event.code);
    };
    const blur = () => this.keys.clear();
    target.tabIndex = Math.max(target.tabIndex, 0);
    target.addEventListener('keydown', down);
    target.addEventListener('keyup', up);
    window.addEventListener('blur', blur);
    this.detach = () => {
      target.removeEventListener('keydown', down);
      target.removeEventListener('keyup', up);
      window.removeEventListener('blur', blur);
    };
  }

  onMoveIntent(handler: (intent: MoveIntent) => void): void {
    this.onMove = handler;
  }

  onCancelIntent(handler: () => void): void {
    this.onCancel = handler;
  }

  release(): void {
    this.detach?.();
    this.detach = null;
    this.keys.clear();
  }

  private poll(): MoveIntent | null {
    let dx = 0;
    let dy = 0;
    if (this.keys.has('ArrowLeft') || this.keys.has('KeyA')) dx -= 1;
    if (this.keys.has('ArrowRight') || this.keys.has('KeyD')) dx += 1;
    if (this.keys.has('ArrowUp') || this.keys.has('KeyW')) dy -= 1;
    if (this.keys.has('ArrowDown') || this.keys.has('KeyS')) dy += 1;
    if (dx === 0 && dy === 0) return null;
    return { dx, dy };
  }
}

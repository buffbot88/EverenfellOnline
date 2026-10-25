/** Window manager: inventory, skills, quests and future panels.

One registry, one open/close protocol, DOM-based. The 3D/2D viewport
stays in Pixi; windows are DOM so they remain accessible and cheap.
Each window renders server-provided data only — no local simulation.
Panels start as labeled placeholders wired to real gateway ops as the
browser loop expands (bag.*, skills.*, quests.*).
*/

export type WindowId = 'bag' | 'skills' | 'quests' | 'character';

export interface WindowDef {
  id: WindowId;
  title: string;
  /** Gateway op that supplies this window's data (wired incrementally). */
  dataOp: string;
}

const DEFS: WindowDef[] = [
  { id: 'bag', title: 'Bag', dataOp: 'bag.list' },
  { id: 'skills', title: 'Skills', dataOp: 'skills.list' },
  { id: 'quests', title: 'Quests', dataOp: 'quests.list' },
  { id: 'character', title: 'Character', dataOp: 'role.info' },
];

export class WindowManager {
  private root: HTMLElement;
  private open = new Set<WindowId>();

  constructor(mount: HTMLElement) {
    this.root = document.createElement('div');
    this.root.className = 'ev-windows';
    mount.appendChild(this.root);
  }

  toggle(id: WindowId): void {
    if (this.open.has(id)) this.close(id);
    else this.openWindow(id);
  }

  openWindow(id: WindowId): void {
    if (this.open.has(id)) return;
    const def = DEFS.find((entry) => entry.id === id);
    if (!def) return;
    this.open.add(id);
    const panel = document.createElement('section');
    panel.className = 'ev-window';
    panel.dataset.window = id;
    panel.innerHTML =
      `<header><h2></h2><button type="button" aria-label="Close">×</button></header>` +
      `<p class="ev-window-empty"></p>`;
    panel.querySelector('h2')!.textContent = def.title;
    panel.querySelector('p')!.textContent =
      `Waiting on gateway op ${def.dataOp} (Mission 5 expansion).`;
    panel.querySelector('button')!.addEventListener('click', () => this.close(id));
    this.root.appendChild(panel);
  }

  close(id: WindowId): void {
    this.open.delete(id);
    this.root.querySelector(`[data-window="${id}"]`)?.remove();
  }

  get openWindows(): WindowId[] {
    return [...this.open];
  }
}

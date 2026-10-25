/** Everenfell shell: login -> character select -> world views.

Owns the Pixi application, the gateway, and view switching. Views are
thin: login collects credentials for AuthClient, select lists roles
from world.enter eligibility, world renders snapshots and sends tile
intents. The smallest playable loop ends at Render Player + Movement;
NPCs, combat, inventory and quests attach as gateway ops land.
*/
import { Application, Graphics } from 'pixi.js';
import { AuthClient } from './net/auth';
import { Gateway } from './net/gateway';
import type { ActorSnapshot, WorldSnapshot } from './net/protocol';
import { ActorLayer } from './world/actors';
import { Camera } from './world/camera';
import { Input } from './world/input';
import { WindowManager } from './ui/windows';

export type ViewState = 'login' | 'select' | 'world' | 'offline';

export interface AppOptions {
  mount: HTMLElement;
  uiMount: HTMLElement;
  apiBase: string;
  gatewayUrl: string;
}

const GRID_STEP_TILES = 4;

export class App {
  private pixi = new Application();
  private camera: Camera;
  private actors: ActorLayer;
  private input = new Input();
  private windows: WindowManager;
  private gateway: Gateway;
  private auth: AuthClient;
  private state: ViewState = 'login';
  private statusEl: HTMLElement;
  private selfId: string | null = null;
  private selfTile = { x: 0, y: 0 };
  private grid: Graphics | null = null;

  constructor(private readonly options: AppOptions) {
    this.camera = new Camera({ viewWidth: 1, viewHeight: 1 });
    this.actors = new ActorLayer(this.camera);
    this.windows = new WindowManager(options.uiMount);
    this.gateway = new Gateway({ url: options.gatewayUrl });
    this.auth = new AuthClient(options.apiBase);
    this.statusEl = document.createElement('p');
    this.statusEl.className = 'ev-status';
    options.uiMount.appendChild(this.statusEl);
  }

  async start(): Promise<void> {
    await this.pixi.init({
      background: '#0a141d',
      resizeTo: this.options.mount,
    });
    this.options.mount.appendChild(this.pixi.canvas);
    this.camera.resize(this.pixi.screen.width, this.pixi.screen.height);
    this.pixi.renderer.on('resize', (width: number, height: number) => {
      this.camera.resize(width, height);
    });
    this.pixi.stage.addChild(this.actors.root);
    this.pixi.ticker.add(() => {
      this.actors.tick(this.pixi.ticker.deltaMS / 16.6);
    });
    this.input.attach(this.pixi.canvas);
    this.input.onMoveIntent(({ dx, dy }) => {
      void this.sendMove(dx, dy);
    });
    this.renderLogin();
    this.setStatus('Sign in to enter Everenfell.');
  }

  destroy(): void {
    this.input.release();
    this.gateway.disconnect();
    this.pixi.destroy({ removeView: true }, true);
  }

  private setStatus(text: string): void {
    this.statusEl.textContent = text;
  }

  private clearUi(): void {
    this.options.uiMount.querySelectorAll('.ev-view').forEach((node) => node.remove());
  }

  private renderLogin(): void {
    this.state = 'login';
    this.clearUi();
    const form = document.createElement('form');
    form.className = 'ev-view ev-login';
    form.innerHTML =
      `<h1>Everenfell</h1>` +
      `<label>Account<input name="username" autocomplete="username" required /></label>` +
      `<label>Password<input name="password" type="password" autocomplete="current-password" required /></label>` +
      `<button type="submit">Enter world</button>`;
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const data = new FormData(form);
      void this.login(String(data.get('username') ?? ''), String(data.get('password') ?? ''));
    });
    this.options.uiMount.appendChild(form);
  }

  private async login(username: string, password: string): Promise<void> {
    this.setStatus('Signing in…');
    try {
      const session = await this.auth.login(username, password);
      await this.gateway.connect();
      const roles = (await this.gateway.request('world.enter', {
        session,
      })) as { roles?: { id: string; name: string }[] };
      this.renderSelect(roles.roles ?? []);
    } catch (err) {
      this.setStatus(err instanceof Error ? err.message : 'Sign in failed.');
    }
  }

  private renderSelect(roles: { id: string; name: string }[]): void {
    this.state = 'select';
    this.clearUi();
    const panel = document.createElement('div');
    panel.className = 'ev-view ev-select';
    const title = document.createElement('h1');
    title.textContent = 'Choose your hero';
    panel.appendChild(title);
    if (roles.length === 0) {
      const empty = document.createElement('p');
      empty.textContent = 'No heroes yet — creation arrives with the next milestone.';
      panel.appendChild(empty);
    }
    for (const role of roles) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = role.name;
      button.addEventListener('click', () => {
        void this.enterWorld(role.id);
      });
      panel.appendChild(button);
    }
    this.options.uiMount.appendChild(panel);
  }

  private async enterWorld(roleId: string): Promise<void> {
    this.setStatus('Entering world…');
    try {
      const snapshot = (await this.gateway.request('world.snapshot', {
        roleId,
      })) as unknown as WorldSnapshot;
      this.selfId = roleId;
      this.state = 'world';
      this.clearUi();
      this.drawGrid(snapshot.mapId);
      this.applySnapshot(snapshot);
      this.gateway.onPush('actor.moved', (body) => {
        const id = String(body['id'] ?? '');
        const x = Number(body['x'] ?? NaN);
        const y = Number(body['y'] ?? NaN);
        if (id && Number.isFinite(x) && Number.isFinite(y)) {
          if (id === this.selfId) {
            this.selfTile = { x, y };
            this.camera.follow(x, y);
          }
          this.actors.move(id, x, y);
        }
      });
      this.renderWorldChrome();
      this.setStatus('Use WASD/arrows to move. B/S/Q open panels.');
      window.addEventListener('keydown', this.panelKeys);
    } catch (err) {
      this.setStatus(err instanceof Error ? err.message : 'World entry failed.');
    }
  }

  private panelKeys = (event: KeyboardEvent): void => {
    if (this.state !== 'world') return;
    if (event.code === 'KeyB') this.windows.toggle('bag');
    if (event.code === 'KeyS') this.windows.toggle('skills');
    if (event.code === 'KeyQ') this.windows.toggle('quests');
  };

  private applySnapshot(snapshot: WorldSnapshot): void {
    const actors: ActorSnapshot[] = snapshot.actors ?? [];
    this.actors.setAll(actors);
    const self = actors.find((actor) => actor.id === this.selfId);
    const anchor = self ?? actors[0];
    if (anchor) {
      this.selfTile = { x: anchor.x, y: anchor.y };
      this.camera.follow(anchor.x, anchor.y);
    }
  }

  private async sendMove(dx: number, dy: number): Promise<void> {
    if (this.state !== 'world' || !this.selfId) return;
    const x = this.selfTile.x + dx;
    const y = this.selfTile.y + dy;
    try {
      await this.gateway.request('player.move', { x, y });
    } catch {
      // Server rejects illegal tiles; the next validated push re-syncs.
    }
  }

  private drawGrid(mapId: string): void {
    this.grid?.destroy();
    const grid = new Graphics();
    const stepX = GRID_STEP_TILES * 60;
    const stepY = GRID_STEP_TILES * 30;
    const w = this.pixi.screen.width + stepX * 2;
    const h = this.pixi.screen.height + stepY * 2;
    grid.setStrokeStyle({ width: 1, color: 0x1d3a4a, alpha: 0.6 });
    for (let x = 0; x <= w; x += stepX) {
      grid.moveTo(x, 0).lineTo(x, h);
    }
    for (let y = 0; y <= h; y += stepY) {
      grid.moveTo(0, y).lineTo(w, y);
    }
    grid.stroke();
    grid.zIndex = -1;
    this.pixi.stage.addChildAt(grid, 0);
    this.grid = grid;
    void mapId;
  }

  private renderWorldChrome(): void {
    const bar = document.createElement('div');
    bar.className = 'ev-view ev-bar';
    for (const [label, id] of [
      ['Bag (B)', 'bag'],
      ['Skills (S)', 'skills'],
      ['Quests (Q)', 'quests'],
    ] as const) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = label;
      button.addEventListener('click', () => this.windows.toggle(id));
      bar.appendChild(button);
    }
    this.options.uiMount.appendChild(bar);
  }
}

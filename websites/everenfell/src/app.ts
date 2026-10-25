/** Everenfell shell: login -> character select -> world views.

Owns the Pixi application, the gateway, and view switching. Views are
thin: login collects credentials for AuthClient, select lists roles
from world.enter eligibility, world renders snapshots and sends tile
intents. The smallest playable loop ends at Render Player + Movement;
NPCs, combat, inventory and quests attach as gateway ops land.
*/
import { Application } from 'pixi.js';
import { AuthClient } from './net/auth';
import { Gateway } from './net/gateway';
import type { ActorSnapshot, WorldSnapshot } from './net/protocol';
import { GAME_SERVERS } from './net/protocol';
import { ActorLayer } from './world/actors';
import { MapLayer } from './world/mapLayer';
import { Camera } from './world/camera';
import { Input } from './world/input';
import { WindowManager } from './ui/windows';

export type ViewState = 'login' | 'select' | 'world' | 'offline';

export interface AppOptions {
  mount: HTMLElement;
  uiMount: HTMLElement;
  apiBase: string;
  gatewayUrl: string;
  /** Website homepage for signed-out visitors (`?website=` override). */
  websiteUrl: string;
  /** Server selected on the website's server-selection page. */
  serverId?: string;
}

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
  private map: MapLayer | null = null;

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

  /** Website-session gate: no password or registration form lives here.
   *  Signed-out visitors go to the website homepage to sign in; members
   *  pick a server and continue on the existing website session. */
  private renderLogin(): void {
    this.state = 'login';
    this.clearUi();
    void this.checkWebsiteSession();
  }

  private async checkWebsiteSession(): Promise<void> {
    this.setStatus('Checking website session…');
    let signedIn = false;
    try {
      signedIn = (await this.auth.session()) !== null;
    } catch (err) {
      this.setStatus(err instanceof Error ? err.message : 'Website unavailable.');
      return;
    }
    this.clearUi();
    if (!signedIn) {
      const panel = document.createElement('div');
      panel.className = 'ev-view ev-login';
      const title = document.createElement('h1');
      title.textContent = 'Everenfell';
      panel.appendChild(title);
      const note = document.createElement('p');
      note.textContent = 'Sign in with your website account to enter the world.';
      panel.appendChild(note);
      const link = document.createElement('a');
      link.href = this.options.websiteUrl;
      link.textContent = 'Sign in on the website';
      panel.appendChild(link);
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.textContent = 'I signed in — continue';
      retry.addEventListener('click', () => {
        void this.checkWebsiteSession();
      });
      panel.appendChild(retry);
      this.options.uiMount.appendChild(panel);
      this.setStatus('Signed out.');
      return;
    }
    if (this.options.serverId && GAME_SERVERS.some((server) => server.id === this.options.serverId)) {
      await this.login(this.options.serverId);
      return;
    }
    const panel = document.createElement('div');
    panel.className = 'ev-view ev-login';
    const title = document.createElement('h1');
    title.textContent = 'Everenfell';
    panel.appendChild(title);
    const label = document.createElement('label');
    label.textContent = 'Server';
    const select = document.createElement('select');
    for (const server of GAME_SERVERS) {
      const option = document.createElement('option');
      option.value = server.id;
      option.textContent = server.name;
      select.appendChild(option);
    }
    label.appendChild(select);
    panel.appendChild(label);
    const enter = document.createElement('button');
    enter.type = 'button';
    enter.textContent = 'Enter world';
    enter.addEventListener('click', () => {
      void this.login(select.value);
    });
    panel.appendChild(enter);
    this.options.uiMount.appendChild(panel);
    this.setStatus('Website account connected. Choose a server.');
  }

  private async login(serverId: string): Promise<void> {
    this.setStatus('Connecting…');
    try {
      await this.gateway.connect();
      await this.gateway.request('auth.session', { server: serverId });
      const entered = (await this.gateway.request('world.enter', {})) as {
        roles?: { id: string; name: string }[];
      };
      this.renderSelect(entered.roles ?? []);
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
      await this.drawMap();
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

  /** Original map 0 tiles at native pixels (dev-only local asset source). */
  private async drawMap(): Promise<void> {
    this.map?.root.destroy({ children: true });
    const map = new MapLayer();
    await map.load();
    map.root.zIndex = -2;
    this.pixi.stage.addChildAt(map.root, 0);
    this.map = map;
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

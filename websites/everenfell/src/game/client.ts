/** Everenfell Phaser client: map rendering + website-session gateway flow.
 *
 * Phaser is the only renderer. Map 0 renders immediately with no session
 * and no gateway (local rendering mode). When a server id is given, the
 * client checks the website session and, only when signed in, connects
 * the Python gateway (auth boundary enforced server-side as well).
 * Views are thin: the server owns positions, auth and progression.
 */
import { AuthClient, canPlay, type SiteUser } from '../net/auth';
import { Gateway } from '../net/gateway';
import type { ActorSnapshot, WorldSnapshot } from '../net/protocol';
import { GAME_SERVERS } from '../net/protocol';
import { Camera } from '../world/camera';
import { Input } from '../world/input';
import { WindowManager } from '../ui/windows';
import { createPhaserGame } from './createPhaserGame';
import { WORLD_KEY, WorldScene } from './scenes/WorldScene';

export type ViewState = 'loading' | 'select' | 'world';

export interface ClientOptions {
  mount: HTMLElement;
  uiMount: HTMLElement;
  gatewayUrl: string;
  serverId?: string;
}

export class PhaserClient {
  private game: Phaser.Game | null = null;
  private camera = new Camera({ viewWidth: 1, viewHeight: 1 });
  private input = new Input();
  private windows: WindowManager;
  private gateway: Gateway;
  private auth: AuthClient;
  private statusEl: HTMLElement;
  private selfId: string | null = null;
  private selfTile = { x: 0, y: 0 };

  constructor(private readonly options: ClientOptions) {
    this.windows = new WindowManager(options.uiMount);
    this.gateway = new Gateway({ url: options.gatewayUrl });
    this.auth = new AuthClient();
    this.statusEl = document.createElement('p');
    this.statusEl.className = 'ev-status';
    options.uiMount.appendChild(this.statusEl);
  }

  /** Boot Phaser and render Map 0. Never touches session or gateway. */
  async start(): Promise<void> {
    this.setStatus('Loading recovered Map 0…');
    this.game = createPhaserGame(this.options.mount);
    await this.waitForMap();
    const world = this.worldScene();
    world?.bindActorCamera(this.camera);
    this.setStatus('Rendering recovered Map 0 (original tiles).');
    this.input.attach(this.game.canvas);
    this.input.onMoveIntent(({ dx, dy }) => {
      void this.sendMove(dx, dy);
    });
  }

  /** Gameplay path: website session gate, then the Python gateway. */
  startGameplay(): void {
    this.renderLogin();
  }

  destroy(): void {
    this.input.release();
    this.gateway.disconnect();
    this.game?.destroy(true);
    this.game = null;
  }

  private worldScene(): WorldScene | null {
    const scene = this.game?.scene.getScene(WORLD_KEY);
    return scene instanceof WorldScene ? scene : null;
  }

  private waitForMap(timeoutMs = 120000): Promise<void> {
    const started = Date.now();
    return new Promise((resolve, reject) => {
      const poll = () => {
        const status = window.__evfMapStatus;
        // Progressive loading: proceed once the current view is ready;
        // offscreen tiles keep streaming as the camera moves.
        if (status && status.ready) {
          resolve();
          return;
        }
        if (status && status.failed.length > 0) {
          reject(new Error(`Map failed to load (${status.failed[0]})`));
          return;
        }
        if (Date.now() - started > timeoutMs) {
          reject(new Error('Map load timed out'));
          return;
        }
        window.setTimeout(poll, 100);
      };
      poll();
    });
  }

  private setStatus(text: string): void {
    this.statusEl.textContent = text;
  }

  private renderLogin(): void {
    this.clearViews();
    void this.checkWebsiteSession();
  }

  private clearViews(): void {
    this.options.uiMount.querySelectorAll('.ev-view').forEach((node) => node.remove());
  }

  private async checkWebsiteSession(): Promise<void> {
    this.setStatus('Checking website session…');
    let user: SiteUser | null;
    try {
      user = await this.auth.session();
    } catch (err) {
      this.setStatus(err instanceof Error ? err.message : 'Website unavailable.');
      return;
    }
    this.clearViews();
    if (user !== null && !canPlay(user)) {
      this.setStatus(
        `Signed in as ${user.display_name || user.username}: this account is not entitled to Everenfell S1.`,
      );
      return;
    }
    if (user === null) {
      this.clearViews();
      const panel = document.createElement('div');
      panel.className = 'ev-view ev-login';
      const title = document.createElement('h1');
      title.textContent = 'Everenfell';
      panel.appendChild(title);
      const note = document.createElement('p');
      note.textContent = 'Sign in with your website account to enter the world.';
      panel.appendChild(note);
      const link = document.createElement('a');
      link.href = '/auth/login';
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
      this.setStatus('Signed out. Map remains inspectable.');
      return;
    }
    const serverId = this.options.serverId;
    if (serverId && GAME_SERVERS.some((server) => server.id === serverId)) {
      await this.login(serverId);
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
      const ticket = await this.auth.ticket(serverId);
      await this.gateway.request('auth.session', { ticket, server: serverId });
      const entered = (await this.gateway.request('world.enter', {})) as {
        roles?: { id: string; name: string }[];
      };
      this.renderSelect(entered.roles ?? []);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Sign in failed.';
      // The gateway only accepts sessions it issued itself; until a
      // server-side AGP verification contract exists it cannot verify
      // website members, so S1 gameplay stays closed by default.
      this.setStatus(
        message.includes('invalid session')
          ? 'S1 gameplay is closed: the gateway cannot verify website sessions yet (server-side AGP check pending). Map remains inspectable.'
          : message,
      );
    }
  }

  private renderSelect(roles: { id: string; name: string }[]): void {
    this.clearViews();
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
      this.clearViews();
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
          this.worldScene()?.moveActor(id, x, y);
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
    if (!this.selfId) return;
    if (event.code === 'KeyB') this.windows.toggle('bag');
    if (event.code === 'KeyS') this.windows.toggle('skills');
    if (event.code === 'KeyQ') this.windows.toggle('quests');
  };

  private applySnapshot(snapshot: WorldSnapshot): void {
    const actors: ActorSnapshot[] = snapshot.actors ?? [];
    this.worldScene()?.setActors(actors);
    const self = actors.find((actor) => actor.id === this.selfId);
    const anchor = self ?? actors[0];
    if (anchor) {
      this.selfTile = { x: anchor.x, y: anchor.y };
      this.camera.follow(anchor.x, anchor.y);
      this.worldScene()?.bindActorCamera(this.camera);
    }
  }

  private async sendMove(dx: number, dy: number): Promise<void> {
    if (!this.selfId) return;
    const x = this.selfTile.x + dx;
    const y = this.selfTile.y + dy;
    try {
      await this.gateway.request('player.move', { x, y });
    } catch {
      // Server rejects illegal tiles; the next validated push re-syncs.
    }
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

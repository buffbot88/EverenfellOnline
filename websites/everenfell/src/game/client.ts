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
import {
  GAME_SERVERS,
  JOB_CODES,
  MAX_ROLES_PER_ACCOUNT,
  jobName,
  type RoleRef,
} from '../net/protocol';
import { CREATE_GEOM, CREATE_KEY } from './scenes/CharacterCreateScene';
import { letterbox } from './stage';
import { SELECT_KEY } from './scenes/CharacterSelectScene';
import { Camera } from '../world/camera';
import { Input } from '../world/input';
import { WindowManager } from '../ui/windows';
import { createPhaserGame } from './createPhaserGame';
import { sound } from './sound';
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
  private nameOverlay: HTMLInputElement | null = null;

  constructor(private readonly options: ClientOptions) {
    this.windows = new WindowManager(options.uiMount);
    this.windows.onToggle((opened) => sound.panel(opened));
    this.gateway = new Gateway({ url: options.gatewayUrl });
    this.auth = new AuthClient();
    this.statusEl = document.createElement('p');
    this.statusEl.className = 'ev-status';
    options.uiMount.appendChild(this.statusEl);
  }

  /** Boot Phaser. Map tiles load on world entry, not on select/create. */
  async start(): Promise<void> {
    this.game = createPhaserGame(this.options.mount);
    const scene = new URLSearchParams(window.location.search).get('scene');
    if (scene === 'select' || scene === 'create') {
      // Character screens are self-describing; no status line.
      this.setStatusVisible(false);
      this.input.attach(this.game.canvas);
      this.input.onMoveIntent(({ dx, dy }) => {
        void this.sendMove(dx, dy);
      });
      return;
    }
    this.setStatusVisible(true);
    this.setStatus('Loading recovered Map 0…');
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

  private setStatusVisible(visible: boolean): void {
    this.statusEl.style.display = visible ? '' : 'none';
  }

  private renderLogin(): void {
    this.clearViews();
    void this.checkWebsiteSession();
  }

  private clearViews(): void {
    this.options.uiMount.querySelectorAll('.ev-view').forEach((node) => node.remove());
    this.nameOverlay?.remove();
    this.nameOverlay = null;
    window.removeEventListener('resize', this.repositionOverlay);
  }

  private repositionOverlay = (): void => {
    this.positionNameOverlay();
  };

  /** Place the HTML name field over the box art (Phaser has no text input). */
  private positionNameOverlay(): void {
    const overlay = this.nameOverlay;
    const canvas = this.game?.canvas;
    if (!overlay || !canvas) return;
    const rect = canvas.getBoundingClientRect();
    const ui = this.options.uiMount.getBoundingClientRect();
    const { s, ox, oy } = letterbox(rect.width, rect.height);
    if (!(s > 0)) return;
    const f = CREATE_GEOM.NAME_FIELD;
    overlay.style.left = `${rect.left - ui.left + ox + (CREATE_GEOM.PANEL_X + f.x) * s}px`;
    overlay.style.top = `${rect.top - ui.top + oy + (CREATE_GEOM.PANEL_Y + f.y) * s}px`;
    overlay.style.width = `${f.w * s}px`;
    overlay.style.height = `${f.h * s}px`;
    overlay.style.fontSize = `${Math.max(10, Math.round(15 * s))}px`;
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
        roles?: RoleRef[];
      };
      const roles = entered.roles ?? [];
      // Original entry behavior: no characters -> creation, else selection.
      if (roles.length === 0) this.renderCreate(roles);
      else this.renderSelect(roles);
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

  /** Character selection: owned roles plus empty slots up to the cap. */
  private renderSelect(roles: RoleRef[], selected?: string): void {
    this.clearViews();
    this.showScene(SELECT_KEY, { roles, selected });
    const select = this.scene(SELECT_KEY);
    select?.events.off('roleselect');
    select?.events.on('roleselect', (picked: { id: string }) => {
      sound.click();
      this.renderSelect(roles, picked.id);
    });
    select?.events.off('startworld');
    select?.events.on('startworld', (picked: { id: string }) => {
      sound.click();
      void this.enterWorld(picked.id);
    });
    select?.events.off('gocreate');
    select?.events.on('gocreate', () => {
      sound.click();
      if (roles.length < MAX_ROLES_PER_ACCOUNT) this.renderCreate(roles);
    });
    const panel = document.createElement('div');
    panel.className = 'ev-view ev-select';
    const title = document.createElement('h1');
    title.textContent = 'Choose your hero';
    panel.appendChild(title);
    const sub = document.createElement('p');
    sub.textContent = `${roles.length}/${MAX_ROLES_PER_ACCOUNT} slots used. Art: recovered create-ui bitmaps.`;
    panel.appendChild(sub);
    for (const role of roles) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = `${role.name} (${jobName(role.job)} · Lv ${role.level})`;
      button.addEventListener('click', () => {
        sound.click();
        void this.enterWorld(role.id);
      });
      panel.appendChild(button);
    }
    if (roles.length < MAX_ROLES_PER_ACCOUNT) {
      const create = document.createElement('button');
      create.type = 'button';
      create.textContent = 'Create character';
      create.addEventListener('click', () => {
        sound.click();
        this.renderCreate(roles);
      });
      panel.appendChild(create);
    } else {
      const full = document.createElement('p');
      full.textContent = 'Slots full (4/4).';
      panel.appendChild(full);
    }
    this.options.uiMount.appendChild(panel);
    this.setStatusVisible(false);
  }

  /** Character creation: job art in Phaser, name field overlaid on the box. */
  private renderCreate(existing: RoleRef[]): void {
    this.clearViews();
    let jobIndex = 0;
    this.showScene(CREATE_KEY, { selected: jobIndex });
    const scene = this.scene(CREATE_KEY);
    const panel = document.createElement('div');
    panel.className = 'ev-view ev-create';
    const title = document.createElement('h1');
    title.textContent = 'Create character';
    panel.appendChild(title);
    const note = document.createElement('p');
    note.textContent =
      `Slot ${existing.length + 1}/${MAX_ROLES_PER_ACCOUNT}. ` +
      'Names use Chinese characters (backend rule); nothing is created until the server accepts it.';
    panel.appendChild(note);
    // No DOM job buttons: the Phaser portraits are the class picker.
    // (A leftover button row used to sit here — removed as debug UI.)
    const highlight = (index: number): void => {
      jobIndex = index;
    };
    highlight(0);
    const error = document.createElement('p');
    error.className = 'ev-error';
    panel.appendChild(error);
    if (existing.length > 0) {
      const back = document.createElement('button');
      back.type = 'button';
      back.textContent = 'Back to selection';
      back.addEventListener('click', () => {
        sound.close();
        this.renderSelect(existing);
      });
      panel.appendChild(back);
    }
    this.options.uiMount.appendChild(panel);
    // Name field floats over the box art (Phaser has no text input).
    const field = document.createElement('input');
    field.type = 'text';
    field.className = 'ev-name-overlay';
    field.placeholder = 'Name';
    field.setAttribute('aria-label', 'Character name');
    field.maxLength = 14;
    field.autocomplete = 'off';
    field.spellcheck = false;
    Object.assign(field.style, {
      position: 'absolute',
      background: 'transparent',
      border: 'none',
      outline: 'none',
      color: '#f2e6c8',
      fontFamily: 'Georgia, "SimSun", serif',
      textAlign: 'center',
      padding: '0',
    });
    field.addEventListener('keydown', (event) => {
      event.stopPropagation();
      if (event.key === 'Enter') {
        sound.click();
        void this.createCharacter(field.value.trim(), JOB_CODES[jobIndex], existing, error);
      }
    });
    this.options.uiMount.appendChild(field);
    this.nameOverlay = field;
    this.positionNameOverlay();
    window.addEventListener('resize', this.repositionOverlay);
    scene?.events.off('jobselect');
    scene?.events.on('jobselect', (picked: { index: number }) => {
      sound.tab();
      highlight(picked.index);
    });
    scene?.events.off('createstart');
    scene?.events.on('createstart', () => {
      sound.click();
      void this.createCharacter(field.value.trim(), JOB_CODES[jobIndex], existing, error);
    });
    this.setStatusVisible(false);
  }

  private async createCharacter(
    name: string,
    job: string,
    existing: RoleRef[],
    errorEl: HTMLElement,
  ): Promise<void> {
    if (!name) {
      errorEl.textContent = 'Enter a name first.';
      return;
    }
    if (this.nameOverlay) this.nameOverlay.disabled = true;
    errorEl.textContent = 'Creating character…';
    try {
      const created = (await this.gateway.request('role.create', {
        name,
        job,
        sex: 0,
        face: '',
      })) as { role?: RoleRef; roles?: RoleRef[] };
      errorEl.textContent = '';
      // START GAME goes straight into the world with the new character.
      if (created.role?.id) {
        await this.enterWorld(created.role.id);
        return;
      }
      this.renderSelect(created.roles ?? [...existing]);
    } catch (err) {
      errorEl.textContent = err instanceof Error ? err.message : 'Creation failed.';
    } finally {
      if (this.nameOverlay) this.nameOverlay.disabled = false;
    }
  }

  private showScene(key: string, data?: Record<string, unknown>): void {
    if (!this.game) return;
    this.game.scene.stop('world');
    if (this.game.scene.isActive(key)) this.game.scene.stop(key);
    this.game.scene.start(key, data);
  }

  /** Return to the map scene after selection/creation screens. */
  private restartWorld(): void {
    if (!this.game) return;
    for (const key of [SELECT_KEY, CREATE_KEY]) {
      if (this.game.scene.isActive(key)) this.game.scene.stop(key);
    }
    if (this.game.scene.isActive('world')) this.game.scene.stop('world');
    this.game.scene.start('world');
  }

  private scene(key: string): { events: Phaser.Events.EventEmitter } | null {
    const scene = this.game?.scene.getScene(key) as unknown as {
      events: Phaser.Events.EventEmitter;
    } | null;
    return scene ?? null;
  }

  private async enterWorld(roleId: string): Promise<void> {
    this.setStatusVisible(true);
    this.setStatus('Entering world…');
    try {
      const snapshot = (await this.gateway.request('world.snapshot', {
        roleId,
      })) as unknown as WorldSnapshot;
      this.selfId = roleId;
      this.clearViews();
      this.restartWorld();
      await this.waitForMap();
      this.worldScene()?.bindActorCamera(this.camera);
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
      button.addEventListener('click', () => {
        this.windows.toggle(id);
      });
      bar.appendChild(button);
    }
    this.options.uiMount.appendChild(bar);
  }
}

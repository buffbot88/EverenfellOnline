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
  type RoleRef,
} from '../net/protocol';
import { setSuppressWorld } from './scenes/LoadingScene';
import { CREATE_GEOM, CREATE_KEY } from './scenes/CharacterCreateScene';
import { UI_KEY } from './scenes/UIScene';
import { letterbox } from './stage';

import { SELECT_KEY } from './scenes/CharacterSelectScene';
import { Camera } from '../world/camera';
import { Input } from '../world/input';
import { WindowManager } from '../ui/windows';
import { createPhaserGame } from './createPhaserGame';
import { sound } from './sound';
import { WORLD_KEY, WorldScene } from './scenes/WorldScene';

/** Device-local home-server cache (per AGP account). Convenience only:
 * skips the one-time picker on known devices. The backend owns the real
 * assignment and verifies every request (docs/account-flow.md). */
const HOME_KEY = 'evf-home-server';
const PENDING_KEY = 'evf-home-server-pending';

function cachedServer(key: string, account: string): string | null {
  try {
    const value = window.localStorage.getItem(`${key}:${account}`);
    return value && GAME_SERVERS.some((server) => server.id === value) ? value : null;
  } catch {
    return null;
  }
}

function storeServer(key: string, account: string, server: string): void {
  try {
    window.localStorage.setItem(`${key}:${account}`, server);
  } catch {
    // Private mode: the cache lasts for this session only.
  }
}

function clearCachedServer(key: string, account: string): void {
  try {
    window.localStorage.removeItem(`${key}:${account}`);
  } catch {
    // Private mode: nothing persisted.
  }
}

/** Permanent device cache: written only from the authoritative backend
 * value (pre-connect session resolution, world.enter confirmation, or
 * first successful creation on the connected server). Never read back
 * for routing — the session response decides before every connect. */
function setHomeServer(account: string, server: string): void {
  storeServer(HOME_KEY, account, server);
}

/** Provisional choice: remembered so the picker can offer it again, but
 * freely changeable until the first character is created. */
function pendingServer(account: string): string | null {
  return cachedServer(PENDING_KEY, account);
}

function setPendingServer(account: string, server: string): void {
  storeServer(PENDING_KEY, account, server);
}

export type ViewState = 'loading' | 'select' | 'world';

export interface ClientOptions {
  mount: HTMLElement;
  uiMount: HTMLElement;
  gatewayUrl: string;
  serverId?: string;
  /** True when startGameplay() will run (server flow or ?mode=play).
   * Only then are gameplay scenes suppressed at boot; otherwise the
   * client is a map-inspection renderer with no character screens. */
  gameplay?: boolean;
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
  /** Verified AGP account + connected game server for this session. */
  private accountId: string | null = null;
  private gameServer: string | null = null;

  constructor(private readonly options: ClientOptions) {
    this.windows = new WindowManager(options.uiMount);
    this.windows.onToggle((opened) => sound.panel(opened));
    this.gateway = new Gateway({ url: options.gatewayUrl });
    this.auth = new AuthClient();
    this.statusEl = document.createElement('p');
    this.statusEl.className = 'ev-status';
    options.uiMount.appendChild(this.statusEl);
  }

  /** Boot Phaser. On the gameplay path, gameplay scenes never own the
   * display before START GAME: LoadingScene auto-starts the world, so it
   * (and the HUD) is stopped immediately and character screens own the
   * canvas until a successful world.snapshot. Map-inspect mode keeps the
   * legacy direct-to-map rendering (no character screens exist there). */
  async start(): Promise<void> {
    // Must run before construction: LoadingScene reads it during boot.
    // Stopping scenes after construction races their boot and loses.
    setSuppressWorld(this.options.gameplay === true);
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
    if (this.options.gameplay) {
      // World/UI never started (holding scene owns the canvas); nothing
      // to stop. Character screens take over from renderLogin().
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

  /** World + HUD must never render behind/over character screens.
   * Stopping is idempotent; call before any character-screen display
   * and on world-entry failure. */
  private stopGameplayScenes(): void {
    if (!this.game) return;
    for (const key of [WORLD_KEY, UI_KEY]) {
      if (this.game.scene.isActive(key)) this.game.scene.stop(key);
    }
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
    // Login/picker/selection display without gameplay behind them.
    this.stopGameplayScenes();
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
    // One AGP account, one home server. The authoritative assignment lives
    // server-side (see docs/account-flow.md) and is resolved BEFORE any
    // gateway connection: the session response carries it, and backend
    // data always wins over local caches. A stale cache or ?server= URL
    // can never drive a connection to the wrong gateway. Neither cache is
    // trusted for access — the gateway verifies every request.
    const account = user.username || user.display_name || 'member';
    const validServer = (id: unknown): id is string =>
      typeof id === 'string' && GAME_SERVERS.some((server) => server.id === id);
    // null means the backend confirmed the account is unbound. Anything
    // else that is not a known server means the assignment is UNKNOWN
    // (never guess: a failed request already returned above, so a
    // missing/malformed field must not degrade to the picker).
    if (user.homeServer !== null && !validServer(user.homeServer)) {
      this.setStatus('Account server status unavailable. Please try again.');
      return;
    }
    const authoritative = user.homeServer;
    if (authoritative) {
      setHomeServer(account, authoritative);
      clearCachedServer(PENDING_KEY, account);
      await this.login(authoritative, account);
      return;
    }
    // Unbound account: a permanent cache here is stale (backend says no
    // binding), so drop it instead of connecting somewhere wrong.
    clearCachedServer(HOME_KEY, account);
    // First-time onboarding: the only server picker in the client. It is
    // reached until a permanent home server exists, never linked from the
    // navbar. A provisional earlier choice is pre-selected but changeable.
    const panel = document.createElement('div');
    panel.className = 'ev-view ev-login';
    const title = document.createElement('h1');
    title.textContent = 'Everenfell';
    panel.appendChild(title);
    const note = document.createElement('p');
    note.textContent =
      'Choose your home server. You can change your mind until your first character is created — after that it is permanent.';
    panel.appendChild(note);
    const label = document.createElement('label');
    label.textContent = 'Home server';
    const select = document.createElement('select');
    for (const server of GAME_SERVERS) {
      const option = document.createElement('option');
      option.value = server.id;
      option.textContent = server.name;
      select.appendChild(option);
    }
    // Pre-select: provisional choice first, then a ?server= hint, then
    // the first entry. Selection is never an auto-connect.
    const pending = pendingServer(account);
    const hinted = this.options.serverId;
    if (pending) select.value = pending;
    else if (validServer(hinted)) select.value = hinted;
    label.appendChild(select);
    panel.appendChild(label);
    const enter = document.createElement('button');
    enter.type = 'button';
    enter.textContent = 'Continue';
    enter.addEventListener('click', () => {
      void this.login(select.value, account);
    });
    panel.appendChild(enter);
    this.options.uiMount.appendChild(panel);
    this.setStatus('Welcome. Choose your home server.');
  }

  private async login(serverId: string, account: string): Promise<void> {
    this.accountId = account;
    this.gameServer = serverId;
    // Provisional only: choosing a server binds nothing. The permanent
    // cache is written on first successful creation (or overwritten by
    // the authoritative backend value below).
    setPendingServer(account, serverId);
    this.setStatus('Connecting…');
    try {
      await this.gateway.connect();
      const ticket = await this.auth.ticket(serverId);
      await this.gateway.request('auth.session', { ticket, server: serverId });
      const entered = (await this.gateway.request('world.enter', {})) as {
        roles?: RoleRef[];
        homeServer?: string;
      };
      // Backend assignment always wins over any local cache (including
      // after an administrative home-server change).
      if (entered.homeServer && GAME_SERVERS.some((server) => server.id === entered.homeServer)) {
        setHomeServer(account, entered.homeServer);
        clearCachedServer(PENDING_KEY, account);
      }
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
      const role = roles.find((entry) => entry.id === picked.id);
      if (role) void this.enterWorld(role);
    });
    select?.events.off('gocreate');
    select?.events.on('gocreate', () => {
      sound.click();
      if (roles.length < MAX_ROLES_PER_ACCOUNT) this.renderCreate(roles);
    });
    // No DOM role list: the Phaser select scene renders owned roles in
    // badge slots and emits roleselect/startworld/gocreate. DOM buttons
    // here would duplicate it with unstyled placeholders.
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
      // First successful creation commits the permanent home server
      // (device cache; the authoritative binding is enforced by the
      // backend) and clears the provisional choice.
      if (this.accountId && this.gameServer) {
        setHomeServer(this.accountId, this.gameServer);
        clearCachedServer(PENDING_KEY, this.accountId);
      }
      // START GAME goes straight into the world with the new character.
      if (created.role?.id) {
        await this.enterWorld(created.role);
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
    // Character screens own the display: gameplay scenes stay stopped.
    this.stopGameplayScenes();
    if (this.game.scene.isActive(key)) this.game.scene.stop(key);
    this.game.scene.start(key, data);
  }

  /** Start the map scene for world entry (HUD launches separately below). */
  private restartWorld(): void {
    if (!this.game) return;
    for (const key of [SELECT_KEY, CREATE_KEY]) {
      if (this.game.scene.isActive(key)) this.game.scene.stop(key);
    }
    this.stopGameplayScenes();
    this.game.scene.start(WORLD_KEY);
  }

  private scene(key: string): { events: Phaser.Events.EventEmitter } | null {
    const scene = this.game?.scene.getScene(key) as unknown as {
      events: Phaser.Events.EventEmitter;
    } | null;
    return scene ?? null;
  }

  private async enterWorld(role: RoleRef): Promise<void> {
    this.setStatusVisible(true);
    this.setStatus('Entering world…');
    try {
      const snapshot = (await this.gateway.request('world.snapshot', {
        roleId: role.id,
      })) as unknown as WorldSnapshot;
      this.selfId = role.id;
      this.clearViews();
      this.restartWorld();
      await this.waitForMap();
      this.worldScene()?.bindActorCamera(this.camera);
      this.applySnapshot(snapshot);
      // World + HUD reveal together only after the snapshot is applied;
      // a failed entry below stops both, never exposing bare gameplay.
      // (SceneManager has start/stop; launch lives on ScenePlugin.)
      // Role data rides into the HUD so roleheadskin binds live values.
      this.game?.scene.start(UI_KEY, {
        playerName: role.name,
        playerLevel: role.level,
        job: role.job,
      });
      this.movedUnsub?.();
      this.movedUnsub = this.gateway.onPush('actor.moved', (body) => {
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
      this.setStatusVisible(false);
      window.addEventListener('keydown', this.panelKeys);
    } catch (err) {
      this.movedUnsub?.();
      this.movedUnsub = null;
      this.selfId = null;
      this.stopGameplayScenes();
      this.setStatusVisible(true);
      this.setStatus(err instanceof Error ? err.message : 'World entry failed.');
    }
  }

  private movedUnsub: (() => void) | null = null;

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
    // Placeholder Bag/Skills/Quests bar removed: it is modern generic UI,
    // not recovered Flash art. Keyboard shortcuts (B/S/Q) still toggle
    // the windows; the authentic menu row lands with the HUD milestone.
  }
}

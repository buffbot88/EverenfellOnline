/** Everenfell entry point.

Rendering mode (default) boots the PixiJS renderer and recovered Map 0 with
no website session and no gateway. Gameplay mode (`?mode=play`) runs the
website-session and gateway flow, opted into explicitly. Gateway or session
failures are reported in the UI and never stop the renderer.
*/
import { App } from './app';
import { createPhaserGame } from './game/createPhaserGame';
import { resolveMode } from './mode';

const mount = document.querySelector<HTMLElement>('#app');
const uiMount = document.querySelector<HTMLElement>('#ui');

if (!mount || !uiMount) {
  throw new Error('missing #app or #ui mount');
}

const params = new URLSearchParams(window.location.search);
const mode = resolveMode(window.location.search, window.location.hostname);

const renderer = params.get('renderer') ?? 'pixi';
if (renderer === 'phaser') {
  createPhaserGame(mount);
  const note = document.createElement('p');
  note.className = 'ev-status';
  note.textContent =
    mode === 'play'
      ? 'Phaser renderer active (rendering only; gameplay still uses the gateway).'
      : 'Phaser renderer: recovered Map 0, local rendering mode.';
  uiMount.appendChild(note);
} else {
  const app = new App({
    mount,
    uiMount,
    apiBase: params.get('api') ?? '/legacy-api',
    gatewayUrl: params.get('gateway') ?? 'ws://127.0.0.1:8091/everenfell',
    websiteUrl: params.get('website') ?? 'https://www.agpstudios.org/',
    serverId: params.get('server') ?? undefined,
  });
  app
    .start()
    .then(() => {
      if (mode === 'play') {
        app.startGameplay();
      }
    })
    .catch((err: unknown) => {
      // Boot failures must surface, never leave a black canvas.
      const message = err instanceof Error ? err.message : String(err);
      const banner = document.createElement('p');
      banner.className = 'ev-status ev-fatal';
      banner.textContent = `Everenfell failed to start: ${message}`;
      uiMount.appendChild(banner);
    });
}

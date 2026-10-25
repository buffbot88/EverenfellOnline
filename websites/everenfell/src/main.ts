/** Everenfell entry point: Phaser renders recovered Map 0 on every load.

The map renders with no session and no gateway (local rendering mode).
When `?server=<id>` is present, the client also checks the website
session and connects the Python gateway for signed-in players. Gateway
or session failures are reported in the UI and never stop the renderer.
*/
import { PhaserClient } from './game/client';
import { AuthClient } from './net/auth';
import { resolveMode } from './mode';

const mount = document.querySelector<HTMLElement>('#app');
const uiMount = document.querySelector<HTMLElement>('#ui');

if (!mount || !uiMount) {
  throw new Error('missing #app or #ui mount');
}

const params = new URLSearchParams(window.location.search);
const mode = resolveMode(window.location.search, window.location.hostname);

// Slim site bar account state (decorative; the auth boundary lives server-side).
try {
  const account = document.querySelector('#sitebar-account');
  if (account) {
    void new AuthClient()
      .session()
      .then((user) => {
        const name = user?.display_name || user?.username || '';
        account.textContent = name !== '' ? `Signed in (${name})` : '';
        if (name === '') {
          const link = document.createElement('a');
          link.href = 'https://www.agpstudios.org/';
          link.textContent = 'Sign in';
          account.appendChild(link);
        }
      })
      .catch(() => {});
  }
} catch {
  // Site bar stays on its static sign-in link; never blocks the client.
}

const client = new PhaserClient({
  mount,
  uiMount,
  gatewayUrl: params.get('gateway') ?? 'ws://127.0.0.1:8091/everenfell',
  websiteUrl: params.get('website') ?? 'https://www.agpstudios.org/',
  serverId: params.get('server') ?? undefined,
});

client
  .start()
  .then(() => {
    // A server id means the visitor came from server selection: run the
    // website-session gate and connect the gateway when signed in.
    // Plain loads (and ?mode=play) start gameplay too; the map renders
    // either way and signed-out visitors keep map inspection.
    if (params.get('server') !== null || mode === 'play') {
      client.startGameplay();
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

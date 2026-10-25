/** Everenfell entry point: mount the shell with dev defaults. */
import { App } from './app';

const mount = document.querySelector<HTMLElement>('#app');
const uiMount = document.querySelector<HTMLElement>('#ui');

if (!mount || !uiMount) {
  throw new Error('missing #app or #ui mount');
}

const params = new URLSearchParams(window.location.search);

const app = new App({
  mount,
  uiMount,
  apiBase: params.get('api') ?? '/legacy-api',
  gatewayUrl: params.get('gateway') ?? 'ws://127.0.0.1:8091/everenfell',
  websiteUrl: params.get('website') ?? 'https://www.agpstudios.org/',
});

app.start().catch((err: unknown) => {
  // Boot failures must surface, never leave a black canvas.
  const message = err instanceof Error ? err.message : String(err);
  const banner = document.createElement('p');
  banner.className = 'ev-status ev-fatal';
  banner.textContent = `Everenfell failed to start: ${message}`;
  uiMount.appendChild(banner);
});

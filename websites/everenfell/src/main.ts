/** Everenfell entry point: enforce the website's member gate, then mount the client. */
import { App } from './app';

type Member = { role?: unknown };

declare global {
  interface Window {
    EverenfellAccess: {
      session(): Promise<Member | null>;
      canPlay(user: Member | null): boolean;
    };
  }
}

const mount = document.querySelector<HTMLElement>('#app');
const uiMount = document.querySelector<HTMLElement>('#ui');

if (!mount || !uiMount) {
  throw new Error('missing #app or #ui mount');
}
const appMount: HTMLElement = mount;
const appUiMount: HTMLElement = uiMount;

function showMessage(message: string, link?: string): void {
  const banner = document.createElement('p');
  banner.className = 'ev-status';
  banner.textContent = message;
  if (link) {
    const anchor = document.createElement('a');
    anchor.href = link;
    anchor.textContent = ' Sign in at AGP Studios.';
    banner.appendChild(anchor);
  }
  appUiMount.appendChild(banner);
}

async function start(): Promise<void> {
  let user: Member | null;
  try {
    user = await window.EverenfellAccess.session();
  } catch {
    showMessage('Unable to check your AGP Studios session.');
    return;
  }
  if (!window.EverenfellAccess.canPlay(user)) {
    showMessage(user ? 'Everenfell is under maintenance; only admins can play right now.' : 'Sign in with your AGP Studios account to play.', user ? undefined : 'https://www.agpstudios.org/');
    return;
  }

  const params = new URLSearchParams(window.location.search);
  const app = new App({
    mount: appMount,
    uiMount: appUiMount,
    apiBase: params.get('api') ?? '/legacy-api',
    gatewayUrl: params.get('gateway') ?? (window.location.hostname === 'localhost'
      ? 'ws://127.0.0.1:8091/everenfell'
      : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/everenfell`),
    websiteUrl: params.get('website') ?? 'https://www.agpstudios.org/',
    serverId: params.get('server') ?? undefined,
  });

  try {
    await app.start();
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    showMessage(`Everenfell failed to start: ${message}`);
  }
}

void start();

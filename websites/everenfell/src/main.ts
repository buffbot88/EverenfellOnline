/** Everenfell entry point: verified alpha users load protected Map 0 and S1. */
import { PhaserClient } from './game/client';
import { sound } from './game/sound';
import { AuthClient, canPlay, type SiteUser } from './net/auth';
import { resolveMode } from './mode';

const mount = document.querySelector<HTMLElement>('#app');
const uiMount = document.querySelector<HTMLElement>('#ui');

if (!mount || !uiMount) throw new Error('missing #app or #ui mount');

/** Navbar mute toggle: original UI sounds on/off, persisted. */
function wireMuteButton(): void {
  const button = document.querySelector<HTMLButtonElement>('#sitebar-mute');
  if (!button) return;
  const render = (muted: boolean): void => {
    button.textContent = muted ? '🔇' : '🔊';
    button.setAttribute('aria-pressed', String(muted));
    button.setAttribute('aria-label', muted ? 'Unmute sound' : 'Mute sound');
  };
  render(sound.isMuted);
  sound.onMuteChange(render);
  button.addEventListener('click', () => {
    sound.unlock();
    sound.setMuted(!sound.isMuted);
    if (!sound.isMuted) sound.click();
  });
  window.addEventListener('pointerdown', () => sound.unlock(), { once: true });
}

wireMuteButton();

const params = new URLSearchParams(window.location.search);
const mode = resolveMode(window.location.search, window.location.hostname);
const auth = new AuthClient();
const gatewayUrl =
  `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/everenfell`;
const client = new PhaserClient({
  mount,
  uiMount,
  gatewayUrl,
  serverId: params.get('server') ?? undefined,
});

function showGate(message: string, signIn = false): void {
  const panel = document.createElement('div');
  panel.className = 'ev-view ev-login';
  const title = document.createElement('h1');
  title.textContent = 'Everenfell';
  const note = document.createElement('p');
  note.textContent = message;
  panel.append(title, note);
  if (signIn) {
    const link = document.createElement('a');
    link.href = '/auth/login';
    link.textContent = 'Sign in with AGP Studios';
    panel.appendChild(link);
  }
  uiMount!.appendChild(panel);
}

async function boot(): Promise<void> {
  if (!import.meta.env.DEV) {
    let user: SiteUser | null;
    try {
      user = await auth.session();
    } catch {
      showGate('Everenfell access could not be verified. Please try again.');
      return;
    }
    const account = document.querySelector('#sitebar-account');
    if (user && account) account.textContent = `Signed in (${user.display_name || user.username})`;
    if (!canPlay(user)) {
      showGate(
        user
          ? 'Only AGP administrators explicitly entitled to S1 may enter during alpha.'
          : 'Sign in with your AGP Studios account to continue.',
        !user,
      );
      return;
    }
  }

  await client.start();
  if (params.has('server') || mode === 'play') client.startGameplay();
}

void boot().catch((err: unknown) => {
  const banner = document.createElement('p');
  banner.className = 'ev-status ev-fatal';
  banner.textContent = `Everenfell failed to start: ${err instanceof Error ? err.message : String(err)}`;
  uiMount.appendChild(banner);
});

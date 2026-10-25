/** Client mode: rendering inspection vs live gameplay.

- `render` (default): draws recovered Map 0 with no website session, no
  gateway, no account, and no gameplay commands. Shown when a visitor opens
  the page without asking to play.
- `play`: the gameplay path. Checks the website session, then connects to
  the Python gateway. Entered only from the server-selection flow.
- `local`: a development-only rendering mode, allowed only on loopback
  hosts. It is the same renderer as `render`, labelled as local development,
  and it is never a production authentication bypass.

The server enforces the real access rules; this module only chooses which
view to show. Nothing here grants access to gameplay.
*/

export type ClientMode = 'render' | 'play' | 'local';

const LOOPBACK = new Set(['localhost', '127.0.0.1', '[::1]']);

export function isLoopbackHost(hostname: string): boolean {
  return LOOPBACK.has(hostname);
}

/** Resolve the mode from the URL. `local` is refused off loopback hosts. */
export function resolveMode(search: string, hostname: string): ClientMode {
  const requested = new URLSearchParams(search).get('mode');
  if (requested === 'play') return 'play';
  if (requested === 'local') {
    return isLoopbackHost(hostname) ? 'local' : 'render';
  }
  return 'render';
}

/** Website session client: the game reuses the website member session.
 *
 * No passwords or registration live here (see
 * Server-v1/docs/website-accounts-s1.md). The website signs members in
 * and holds the session cookie; the client only asks the website backend
 * whether that cookie is valid (gamesession.php over the same-origin
 * API proxy, credentials included). The gateway reads the same cookie
 * from the WebSocket handshake server-side, so the token never passes
 * through JavaScript.
 */

export interface GameSession {
  ok: boolean;
  uid?: string;
  t?: string;
  sign?: string;
  server?: string;
  [key: string]: unknown;
}

export class AuthClient {
  constructor(private readonly apiBase: string) {}

  /** Current website session, or null when signed out (HTTP 401). */
  async session(): Promise<GameSession | null> {
    let res: Response;
    try {
      res = await fetch(`${this.apiBase}/gamesession.php`, {
        credentials: 'include',
      });
    } catch {
      throw new Error('website unavailable');
    }
    if (res.status === 401) {
      return null;
    }
    if (!res.ok) {
      throw new Error(`session refused (http ${res.status})`);
    }
    const session = (await res.json()) as GameSession;
    return session.ok ? session : null;
  }
}

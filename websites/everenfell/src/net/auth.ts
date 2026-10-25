/** Web account API client (PHP-compatible surface, new stack).

Mirrors tools/projector-client.py login_api: POST AccountHandler.php
with Action=Login, then GET gamesession.php on the same cookie jar.
Keep this the single place that knows the legacy web shapes; the
gateway will accept the resulting session, never raw passwords.
*/

export interface GameSession {
  ok: boolean;
  user?: string;
  sign?: string;
  server?: string;
  [key: string]: unknown;
}

export class AuthClient {
  constructor(private readonly apiBase: string) {}

  async login(username: string, password: string): Promise<GameSession> {
    const form = new URLSearchParams({
      Action: 'Login',
      uName: username,
      uPas: password,
    });
    const loginRes = await fetch(`${this.apiBase}/AjaxRequest/AccountHandler.php`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form.toString(),
      credentials: 'include',
    });
    if (!loginRes.ok) {
      throw new Error(`login refused (http ${loginRes.status})`);
    }
    const sessionRes = await fetch(`${this.apiBase}/gamesession.php`, {
      credentials: 'include',
    });
    if (!sessionRes.ok) {
      throw new Error(`session refused (http ${sessionRes.status})`);
    }
    const session = (await sessionRes.json()) as GameSession;
    if (!session.ok) {
      throw new Error('session refused');
    }
    return session;
  }
}

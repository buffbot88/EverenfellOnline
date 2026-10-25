/** Website session client: the game reuses the website member session.

No passwords or registration live here (see
Server-v1/docs/website-accounts-s1.md). The website signs members in
and holds the session cookie. This client only asks the legacy-compatible
session endpoint whether the cookie is valid. It is used for gameplay mode
only; rendering mode never calls it. The gateway reads the same cookie from
the WebSocket handshake server-side, so the token never passes through
JavaScript.
*/

export interface GameSession {
  ok: boolean;
  uid?: string;
  t?: string;
  sign?: string;
  server?: string;
  [key: string]: unknown;
}

/** Raised when an API answers with something other than the expected JSON. */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'ApiError';
  }
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
      throw new ApiError('website unavailable', 0);
    }
    if (res.status === 401) {
      return null;
    }
    if (!res.ok) {
      throw new ApiError(`session refused (http ${res.status})`, res.status);
    }
    const type = res.headers.get('content-type') ?? '';
    const text = await res.text();
    if (!type.includes('application/json')) {
      throw new ApiError(
        'session endpoint returned a non-JSON page; the website backend is not serving the game API',
        res.status,
      );
    }
    let session: GameSession;
    try {
      session = JSON.parse(text) as GameSession;
    } catch {
      throw new ApiError('session endpoint returned malformed JSON', res.status);
    }
    return session.ok ? session : null;
  }
}

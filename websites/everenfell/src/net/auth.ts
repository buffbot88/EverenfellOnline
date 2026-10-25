/** Website session client: the game reuses the AGP Studios member session.
 *
 * Identity comes from the existing website membership system
 * (https://www.agpstudios.org/api/auth/session), never from a second
 * login system and never from the retired PHP-compatible gamesession.php
 * endpoint (see Server-v1/docs/website-accounts-s1.md). The browser
 * session cookie is HttpOnly and is never read by JavaScript.
 *
 * This proves *website identity* only. Gameplay authorization is decided
 * independently by the Python gateway handshake server-side; a
 * browser-supplied role or account id is never accepted as proof there.
 * Until server-side AGP verification exists, S1 gameplay stays closed
 * and this client only gates the UI (map stays inspectable).
 */

export interface SiteUser {
  username: string;
  display_name?: string;
  email?: string;
  role?: string;
}

const AGP_SESSION_URL = 'https://www.agpstudios.org/api/auth/session';

/** Mirrors the website's own play gate: maintenance allows admins only. */
export function canPlay(user: SiteUser | null): boolean {
  if (!user) return false;
  return typeof user.role === 'string' && user.role.toLowerCase() === 'admin';
}

/** Raised when the session endpoint answers unexpectedly. */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'ApiError';
  }
}

export class AuthClient {
  /** Current website user, or null when signed out (HTTP 401 / not authenticated). */
  async session(): Promise<SiteUser | null> {
    let res: Response;
    try {
      res = await fetch(AGP_SESSION_URL, { credentials: 'include' });
    } catch {
      throw new ApiError('website unavailable', 0);
    }
    if (res.status === 401) {
      return null;
    }
    if (!res.ok) {
      throw new ApiError(`session refused (http ${res.status})`, res.status);
    }
    let body: { authenticated?: boolean; user?: SiteUser };
    try {
      body = (await res.json()) as { authenticated?: boolean; user?: SiteUser };
    } catch {
      throw new ApiError('session endpoint returned malformed JSON', res.status);
    }
    return body.authenticated && body.user ? body.user : null;
  }
}

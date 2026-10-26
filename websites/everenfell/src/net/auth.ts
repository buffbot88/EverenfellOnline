/** AGP identity and gameplay admission use the same-origin Python APIs. */

export interface SiteUser {
  username: string;
  display_name?: string;
  email?: string;
  role?: string;
  everenfell_s1?: boolean;
  can_play?: boolean;
}

export function canPlay(user: SiteUser | null): boolean {
  return user?.can_play === true;
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'ApiError';
  }
}

function csrfToken(): string {
  const cookie = document.cookie.split('; ').find((item) => item.startsWith('evf_csrf='));
  return decodeURIComponent(cookie?.slice('evf_csrf='.length) ?? '');
}

export class AuthClient {
  async session(): Promise<SiteUser | null> {
    let res: Response;
    try {
      res = await fetch('/api/auth/session', {
        credentials: 'same-origin',
        cache: 'no-store',
      });
    } catch {
      throw new ApiError('Everenfell session service unavailable', 0);
    }
    if (!res.ok) throw new ApiError(`session refused (http ${res.status})`, res.status);
    let body: { authenticated?: boolean; user?: SiteUser };
    try {
      body = (await res.json()) as { authenticated?: boolean; user?: SiteUser };
    } catch {
      throw new ApiError('session endpoint returned malformed JSON', res.status);
    }
    return body.authenticated && body.user ? body.user : null;
  }

  async ticket(server: string): Promise<string> {
    const res = await fetch('/api/game/ticket', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrfToken(),
      },
      body: JSON.stringify({ server }),
    });
    if (!res.ok) throw new ApiError(`S1 access refused (http ${res.status})`, res.status);
    const body = (await res.json()) as { ticket?: unknown };
    if (typeof body.ticket !== 'string' || !body.ticket) {
      throw new ApiError('ticket endpoint returned malformed JSON', res.status);
    }
    return body.ticket;
  }
}

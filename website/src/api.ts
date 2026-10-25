/** AGP Studios account client (ported from access.js + homepage logic).
 *
 * Session cookies are HttpOnly; the browser sends them via
 * credentials:include and never sees token values. Sign-out carries the
 * CSRF token exactly like the original page.
 */
const API = 'https://www.agpstudios.org/api';

export interface SiteUser {
  username: string;
  display_name?: string;
  email?: string;
  role?: string;
}

export const MAINTENANCE = true;

export function canPlay(user: SiteUser | null): boolean {
  return (
    !!user &&
    (!MAINTENANCE || (typeof user.role === 'string' && user.role.toLowerCase() === 'admin'))
  );
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...options,
    credentials: 'include',
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers ?? {}),
    },
  });
  const body = (response.status === 204 ? {} : await response.json()) as {
    error?: { message?: string } | string;
  } & T;
  if (!response.ok) {
    const message =
      typeof body.error === 'string'
        ? body.error
        : (body.error?.message ?? `Request failed (${response.status})`);
    throw new Error(message);
  }
  return body;
}

export async function fetchSession(): Promise<SiteUser | null> {
  const result = await request<{ authenticated: boolean; user: SiteUser }>('/auth/session');
  return result.authenticated ? result.user : null;
}

export async function login(identifier: string, password: string): Promise<SiteUser> {
  const result = await request<{ user: SiteUser }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ identifier, password }),
  });
  return result.user;
}

export async function register(
  username: string,
  email: string,
  password: string,
): Promise<void> {
  await request('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username, email, password, display_name: username }),
  });
}

function csrfToken(): string {
  const found = document.cookie
    .split('; ')
    .find((item) => item.startsWith('ashat_csrf='));
  return decodeURIComponent(found?.slice('ashat_csrf='.length) ?? '');
}

export async function logout(): Promise<void> {
  await request('/auth/logout', {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken() },
  });
}

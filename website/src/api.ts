/** Same-origin API for AGP OIDC sessions and Everenfell access. */
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

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    credentials: 'same-origin',
    cache: 'no-store',
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers ?? {}),
    },
  });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return (await response.json()) as T;
}

export async function fetchSession(): Promise<SiteUser | null> {
  const result = await request<{ authenticated: boolean; user?: SiteUser }>('/auth/session');
  return result.authenticated ? result.user ?? null : null;
}

function csrfToken(): string {
  const cookie = document.cookie.split('; ').find((item) => item.startsWith('evf_csrf='));
  return decodeURIComponent(cookie?.slice('evf_csrf='.length) ?? '');
}

export async function logout(): Promise<void> {
  await request('/auth/logout', {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken() },
  });
}

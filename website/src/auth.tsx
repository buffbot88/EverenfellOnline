/** Same-origin session state and AGP-hosted OIDC sign-in. */
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { canPlay, fetchSession, logout, type SiteUser } from './api';

interface AuthState {
  user: SiteUser | null;
  ready: boolean;
  openDialog: () => void;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  user: null,
  ready: false,
  openDialog: () => {},
  signOut: async () => {},
});

export function useAuth(): AuthState {
  return useContext(AuthContext);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SiteUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    fetchSession()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setReady(true));
  }, []);

  const openDialog = useCallback(() => {
    window.location.assign('/auth/login');
  }, []);

  const signOut = useCallback(async () => {
    await logout();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, ready, openDialog, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function Navbar() {
  const { user, openDialog, signOut } = useAuth();
  const playable = canPlay(user);
  return (
    <header className="header">
      <nav className="nav" aria-label="Main navigation">
        <a className="brand" href="/">
          <b>AGP</b> STUDIOS
        </a>
        <div className="links">
          <a href="/">Home</a>
          {playable && <a className="nav-action" href="/servers/">Play</a>}
          {!user && <a href="https://www.agpstudios.org/">AGP Studios</a>}
        </div>
        {!user && (
          <button className="nav-action" type="button" onClick={openDialog}>
            Sign in
          </button>
        )}
        {user && (
          <details className="account">
            <summary>{user.display_name || user.username}</summary>
            <div className="account-panel">
              <strong>Signed in as {user.username}</strong>
              <p>{user.email}</p>
              <button
                className="button secondary"
                type="button"
                onClick={() => void signOut().catch(() => {})}
              >
                Sign out
              </button>
            </div>
          </details>
        )}
      </nav>
    </header>
  );
}

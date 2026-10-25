/** Shared navbar + auth dialog with full homepage behavior parity.
 *
 * Rendered on every website route. Owns session restore, the sign-in /
 * register dialog, sign-out, and the admin-gated Play link.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { canPlay, fetchSession, login, logout, register, type SiteUser } from './api';

interface AuthState {
  user: SiteUser | null;
  ready: boolean;
  openDialog: (mode?: 'login' | 'register') => void;
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
  const [dialogMode, setDialogMode] = useState<'login' | 'register' | null>(null);

  useEffect(() => {
    fetchSession()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setReady(true));
  }, []);

  const openDialog = useCallback((mode: 'login' | 'register' = 'login') => {
    setDialogMode(mode);
  }, []);

  const signOut = useCallback(async () => {
    await logout();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, ready, openDialog, signOut }}>
      {children}
      {dialogMode !== null && (
        <AuthDialog
          mode={dialogMode}
          onSwitch={setDialogMode}
          onClose={() => setDialogMode(null)}
          onSignedIn={(next) => {
            setUser(next);
            setDialogMode(null);
          }}
        />
      )}
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
          {playable && (
            <a className="nav-action" href="/servers/">
              Play
            </a>
          )}
          {!user && <a href="/#preregister">Pre-register</a>}
        </div>
        {!user && (
          <button className="nav-action" type="button" onClick={() => openDialog('login')}>
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

function AuthDialog({
  mode,
  onSwitch,
  onClose,
  onSignedIn,
}: {
  mode: 'login' | 'register';
  onSwitch: (mode: 'login' | 'register') => void;
  onClose: () => void;
  onSignedIn: (user: SiteUser) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [identifier, setIdentifier] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState('');
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage('Please wait…');
    setFailed(false);
    try {
      if (mode === 'register') {
        await register(identifier, email, password);
        onSwitch('login');
        setMessage('Account created. Sign in to continue.');
        return;
      }
      onSignedIn(await login(identifier, password));
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : 'Authentication unavailable.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog ref={dialogRef} aria-labelledby="auth-title" onClose={onClose}>
      <form className="auth" onSubmit={(event) => void submit(event)}>
        <div className="auth-head">
          <span className="eyebrow" style={{ margin: 0 }}>
            AGP Studios account
          </span>
          <button className="close" type="button" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        <h2 id="auth-title">{mode === 'login' ? 'Welcome back' : 'Create your account'}</h2>
        <div className="tabs" role="tablist" aria-label="Account action">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'login'}
            onClick={() => onSwitch('login')}
          >
            Sign in
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'register'}
            onClick={() => onSwitch('register')}
          >
            Create account
          </button>
        </div>
        <label htmlFor="identifier">Username or email</label>
        <input
          id="identifier"
          name="identifier"
          autoComplete="username"
          required
          value={identifier}
          onChange={(event) => setIdentifier(event.target.value)}
        />
        {mode === 'register' && (
          <>
            <label htmlFor="email-input">Email</label>
            <input
              id="email-input"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </>
        )}
        <label htmlFor="password">Password</label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <button className="button" type="submit" disabled={busy}>
          {mode === 'login' ? 'Sign in' : 'Create account'}
        </button>
        <p className={failed ? 'status error' : 'status'} role="status" aria-live="polite">
          {message}
        </p>
      </form>
    </dialog>
  );
}

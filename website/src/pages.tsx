/** Website routes: maintenance homepage and server selection. */
import { useEffect, useState } from 'react';
import { canPlay, fetchSession, type SiteUser } from './api';
import { useAuth } from './auth';

export function HomePage() {
  const { user, ready, openDialog } = useAuth();
  return (
    <main id="top">
      <section className="card" id="game" aria-labelledby="title">
        <div className="icon" aria-hidden="true">
          🐒
        </div>
        <div className="eyebrow">Everenfell</div>
        <h1 id="title">Under Construction</h1>
        <p>
          We’re preparing the world for its next adventure. Sign in with your AGP Studios
          account, or pre-register for updates while we get things ready.
        </p>
        {!user && (
          <div className="actions" id="preregister">
            <a className="button" href="https://www.agpstudios.org/">
              Pre-register at AGP Studios
            </a>
            <button
              className="button secondary"
              type="button"
              onClick={openDialog}
            >
              Sign in to your account
            </button>
          </div>
        )}
        <p className="status" role="status" aria-live="polite">
          {ready && user && canPlay(user) && 'Your account is ready. Play Everenfell.'}
          {ready &&
            user &&
            !canPlay(user) &&
            'Everenfell alpha access is limited to explicitly entitled administrators.'}
        </p>
      </section>
    </main>
  );
}

export function ServersPage() {
  const [user, setUser] = useState<SiteUser | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetchSession().then(setUser).catch(() => setFailed(true));
  }, []);

  const playable = canPlay(user);
  return (
    <main className="servers-wrap">
      <div className="card servers-card">
        <div className="brand">Everenfell</div>
        <h1>Choose a server</h1>
        <p id="intro">
          {failed
            ? 'Your account could not be checked.'
            : !user
              ? 'Checking your AGP Studios account…'
              : playable
                ? 'Select a server to launch the game client.'
                : 'You are signed in.'}
        </p>
        {playable && (
          <a className="server" href="/websites/everenfell/?server=S1">
            <strong>S1</strong>
            <span>Enter Everenfell</span>
          </a>
        )}
        <p className="message" role="status" aria-live="polite">
          {failed && 'Please try again later.'}
          {user && !playable && !failed &&
            'Everenfell alpha access is limited to explicitly entitled administrators.'}
          {!user && !failed && (
            <a className="back" href="/auth/login">
              Sign in with AGP Studios
            </a>
          )}
        </p>
        <a className="back" href="/">
          ← Back to Everenfell
        </a>
      </div>
    </main>
  );
}

/** Website entry: pathname routing without extra dependencies. */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { AuthProvider, Navbar } from './auth';
import { HomePage, ServersPage } from './pages';
import './styles.css';

const route = window.location.pathname.startsWith('/servers') ? 'servers' : 'home';

createRoot(document.querySelector('#root')!).render(
  <StrictMode>
    <AuthProvider>
      <Navbar />
      {route === 'servers' ? <ServersPage /> : <HomePage />}
    </AuthProvider>
  </StrictMode>,
);

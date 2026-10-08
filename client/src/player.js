// Ruffle boot for the ORIGINAL Flash client (Main.swf).
// This runs the real game — no reimplementation. Same flashvars the PHP
// Gamelogin.php gave the Flash client; falls back to a demo session so the
// loader/login UI boots while Apache+MySQL are offline.
//
// Requires: npm install (provides @ruffle-rs/ruffle), and /res/* served
// from the legacy tree (see vite.config.js resPlugin — no 1.7GB copied).
// NOTE: Ruffle itself loads via <script src="/ruffle/ruffle.js"> in
// player.html (selfhosted build; must NOT be bundled — it resolves its
// core/wasm relative to the script tag). See scripts/copy-ruffle.js.
import { getFlashVars } from './flashvars.js';

const status = document.getElementById('status');
const diagnosticPanel = document.getElementById('diagnostics');
const diagnosticList = document.getElementById('diagnostics-list');
const diagnosticToggle = document.getElementById('diagnostics-toggle');
const diagnostics = [];
const MAX_DIAGNOSTICS = 250;

function formatDiagnostic(value) {
  if (value instanceof Error) return `${value.name}: ${value.message}${value.stack ? `\n${value.stack}` : ''}`;
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value); } catch { return String(value); }
}

function renderDiagnostics() {
  const errors = diagnostics.filter((item) => item.level === 'error').length;
  const warnings = diagnostics.filter((item) => item.level === 'warn').length;
  diagnosticToggle.textContent = `Diagnostics · ${errors} error${errors === 1 ? '' : 's'} · ${warnings} warning${warnings === 1 ? '' : 's'}`;
  diagnosticToggle.classList.toggle('has-errors', errors > 0);
  diagnosticList.replaceChildren();
  if (!diagnostics.length) {
    const empty = document.createElement('span');
    empty.id = 'diagnostics-empty';
    empty.textContent = 'No client warnings or errors captured.';
    diagnosticList.append(empty);
    return;
  }
  for (const item of diagnostics) {
    const line = document.createElement('span');
    line.className = `diag-${item.level}`;
    line.textContent = `[${item.time}] ${item.level.toUpperCase()} ${item.message}\n`;
    diagnosticList.append(line);
  }
  diagnosticList.scrollTop = diagnosticList.scrollHeight;
}

function cleanRuffleMessage(text) {
  const match = text.match(/%c(INFO|WARN|ERROR|DEBUG)%c\s*([^%]+?)%c\s*(.*)/);
  if (!match) return text;
  const detail = match[3].replace(/\s+color:\s*[^;]+;.*$/, '').trim();
  return `${match[1]} ${match[2].trim()} ${detail}`;
}

function report(level, ...values) {
  const message = values.map(formatDiagnostic).join(' ');
  diagnostics.push({ level, message: message.slice(0, 3000), time: new Date().toLocaleTimeString() });
  if (diagnostics.length > MAX_DIAGNOSTICS) diagnostics.shift();
  renderDiagnostics();
  if (level === 'error') {
    diagnosticPanel.classList.add('open');
    diagnosticToggle.setAttribute('aria-expanded', 'true');
  }
}

const originalConsole = { log: console.log.bind(console), warn: console.warn.bind(console), error: console.error.bind(console) };
for (const method of ['log', 'warn', 'error']) {
  console[method] = (...args) => {
    originalConsole[method](...args);
    const text = args.map(formatDiagnostic).join(' ');
    const ruffleLevel = text.match(/%c(INFO|WARN|ERROR|DEBUG)%c/);
    if (method === 'error' || method === 'warn') {
      const level = ruffleLevel?.[1] === 'ERROR' ? 'error' : ruffleLevel?.[1] === 'WARN' ? 'warn' : method;
      report(level, cleanRuffleMessage(text));
    } else if (ruffleLevel && ruffleLevel[1] !== 'INFO' && ruffleLevel[1] !== 'DEBUG') {
      report(ruffleLevel[1] === 'ERROR' ? 'error' : 'warn', cleanRuffleMessage(text));
    }
  };
}

window.addEventListener('error', (event) => report('error', event.error || event.message));
window.addEventListener('unhandledrejection', (event) => report('error', 'Unhandled promise rejection:', event.reason));

diagnosticToggle.addEventListener('click', () => {
  const open = diagnosticPanel.classList.toggle('open');
  diagnosticToggle.setAttribute('aria-expanded', String(open));
});
document.getElementById('diagnostics-close').addEventListener('click', () => {
  diagnosticPanel.classList.remove('open');
  diagnosticToggle.setAttribute('aria-expanded', 'false');
});
document.getElementById('diagnostics-clear').addEventListener('click', () => {
  diagnostics.length = 0;
  renderDiagnostics();
});
document.getElementById('diagnostics-copy').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(diagnostics.map((item) => `[${item.time}] ${item.level.toUpperCase()} ${item.message}`).join('\n'));
    report('info', 'Diagnostics copied to clipboard.');
  } catch (error) {
    report('error', 'Could not copy diagnostics:', error);
  }
});

const say = (t) => {
  status.innerHTML = t;
};

renderDiagnostics();
report('info', `Diagnostics ready (${navigator.userAgent})`);

// Ruffle itself uses console output for its log API; the wrappers above mirror
// warnings/errors into the visible panel while preserving the browser console.
window.addEventListener('beforeunload', () => {
  console.log = originalConsole.log;
  console.warn = originalConsole.warn;
  console.error = originalConsole.error;
});

window.addEventListener('error', (event) => {
  if (event.target instanceof HTMLScriptElement) report('error', `Script failed to load: ${event.target.src}`);
}, true);

// Record resource failures, which often explain stalls before the game can
// request its next SWF or config file.
new PerformanceObserver((list) => {
  for (const entry of list.getEntries()) {
    if (entry instanceof PerformanceResourceTiming && entry.responseStatus >= 400) {
      report('error', `Resource ${entry.responseStatus}: ${entry.name}`);
    }
  }
}).observe({ type: 'resource', buffered: true });

report('info', 'Player initialized');

async function boot() {
  try {
    await startPlayer();
  } catch (error) {
    report('error', 'Player boot failed:', error);
    say('<b>Error:</b> Player boot failed. Open Diagnostics for details.');
  }
}

async function startPlayer() {
  
  if (!window.RufflePlayer) {
    report('error', 'Ruffle failed to load. Check /ruffle/ruffle.js and the client install.');
    say('<b>Error:</b> Ruffle failed to load. Open Diagnostics for details.');
    return;
  }
  // The game opens a raw TCP socket to ip:sport from its flashvars
  // (Gamelogin.php: ip 127.0.0.1, sport 8008). Browsers can't do raw TCP,
  // so Ruffle forwards matching sockets through the WS->TCP bridge
  // (tools/bridge, websockify-compatible, default ws://127.0.0.1:8181).
  // Override: player.html?bridge=ws://host:port  |  disable: ?nobridge=1
  // The SWF, its protocol and its packets are untouched — the bridge only
  // swaps the transport. Policy requests also tunnel through: the legacy
  // NetListener answers <policy-file-request/> in-band on the game port.
  const qs = new URLSearchParams(location.search);
  const bridgeUrl = qs.get('bridge') || 'ws://127.0.0.1:8181';
  const socketProxy = qs.has('nobridge')
    ? []
    : [
        // Hosts the SWF may request: flashvars `ip` is 127.0.0.1 in
        // production (gamesession.php) and in the demo fallback.
        { host: '127.0.0.1', port: 8008, proxyUrl: bridgeUrl },
        { host: 'localhost', port: 8008, proxyUrl: bridgeUrl },
      ];
  // Silence the "this SWF wants to play audio" overlay: the game has its
  // own mute control (MPlayer.swf), and the overlay blocks input.
  window.RufflePlayer.config = {
    autoplay: 'on',
    unmuteOverlay: 'hidden',
    logLevel: 'warn',
    socketProxy,
  };
  const ruffle = window.RufflePlayer.newest();
  const player = ruffle.createPlayer();
  document.getElementById('game').appendChild(player);

  // Production flashvars come from /api/gamesession.php (logged-in
  // session); the fallback lets the loader/login UI boot without PHP.
  const flashvars = await getFlashVars().catch((e) => {
    report('warn', 'Backend session unavailable; using demo flashvars:', e);
    say(`<b>Backend offline</b> (${e.message}) — booting with demo session.`);
    return null;
  });

  say('loading Main.swf…');
  try {
    await player.load({
      url: '/res/Main.swf',
      backgroundColor: '#000000',
      parameters: flashvars || {},
    });
    report('info', 'Ruffle player.load() resolved for /res/Main.swf');
  } catch (error) {
    report('error', 'Ruffle failed to load Main.swf:', error);
    say('<b>Error:</b> Main.swf failed to load. Open Diagnostics for details.');
    throw error;
  }

  // NOTE: the original page also embedded MPlayer.swf as a 10x2px sidecar
  // (music control). Loading it in a second Ruffle instance was tried and
  // made things worse — the client then stalled *before* opening the game
  // socket instead of completing the login handshake. Reverted; see
  // knowledge.md "Open questions" before retrying it.
  say(
    socketProxy.length
      ? 'game loaded — <b>socket traffic proxied to the bridge; start it with `npm start` in tools/bridge</b>.'
      : 'game loaded — <b>bridge disabled (?nobridge=1): world entry unavailable</b>.',
  );
}

boot();

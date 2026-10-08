// mko-ws-tcp-bridge — WebSocket <-> raw TCP forwarder.
//
// Lets the ORIGINAL Flash client (running under Ruffle, which cannot open
// raw TCP sockets from a browser) reach the UNMODIFIED legacy game server.
// This bridge is transport-only: it never parses, builds, or alters game
// packets. Bytes in = bytes out, both directions.
//
// Wire protocol: websockify-compatible (the dialect Ruffle's `socketProxy`
// points at). Each WebSocket connection gets its own TCP connection:
//   WS binary message  -> TCP bytes
//   TCP bytes          -> WS binary message
// Text WS frames are accepted as base64 (legacy websockify clients) and
// decoded before forwarding. No handshake preamble, no framing of our own —
// packet boundaries are the game's business (3-byte length-prefixed AMF3
// frames per AmfRequestDecoder), and TCP fragmentation is preserved end to
// end because we forward every chunk as it arrives.
//
// Env:
//   LEGACY_HOST=127.0.0.1  LEGACY_PORT=8008      game server TCP endpoint
//   BRIDGE_HOST=127.0.0.1  BRIDGE_PORT=8181      where this bridge listens
//   LOG_LEVEL=info|warn|error (default info)
//   LOG_PACKETS=1            dev-only hex dump (length + first 96 bytes,
//                            policy/auth-looking frames are labelled, never
//                            fully dumped). Default off: lengths only.

const net = require('node:net');
const { WebSocketServer, WebSocket } = require('ws');

const LEGACY_HOST = process.env.LEGACY_HOST || '127.0.0.1';
const LEGACY_PORT = parseInt(process.env.LEGACY_PORT || '8008', 10);
const BRIDGE_HOST = process.env.BRIDGE_HOST || '127.0.0.1';
const BRIDGE_PORT = parseInt(process.env.BRIDGE_PORT || '8181', 10);
const LOG_LEVEL = process.env.LOG_LEVEL || 'info';
const LOG_PACKETS = process.env.LOG_PACKETS === '1';
const HEX_CAP = 96;

let nextId = 1;
const peers = new Map(); // id -> { ws, tcp, upBytes, downBytes }

function log(level, ...args) {
  const order = { error: 0, warn: 1, info: 2 };
  if ((order[level] ?? 2) <= (order[LOG_LEVEL] ?? 2)) {
    console.log(new Date().toISOString(), `[${level}]`, ...args);
  }
}

// Looks like the Flash socket-policy handshake or a login/session frame?
// We can recognise these by shape without decoding game semantics:
// a policy request is the well-known ASCII token; anything else is opaque.
function classify(buf) {
  if (buf.includes('policy-file-request')) return 'socket-policy-handshake';
  return 'game-bytes';
}

function dumpPacket(id, dir, buf) {
  if (!LOG_PACKETS) {
    log('info', `#${id} ${dir} len=${buf.length} kind=${classify(buf)}`);
    return;
  }
  // Dev-only detail. Payloads may carry session tokens: cap the dump and
  // never print policy/auth-shaped frames in full.
  const kind = classify(buf);
  const slice = buf.subarray(0, HEX_CAP);
  const hex = Buffer.from(slice).toString('hex').replace(/(..)/g, '$1 ').trim();
  const clipped = buf.length > HEX_CAP ? ` (+${buf.length - HEX_CAP} more)` : '';
  log('info', `#${id} ${dir} len=${buf.length} kind=${kind} hex=[${hex}]${clipped}`);
}

function closePeer(id, reason) {
  const p = peers.get(id);
  if (!p) return;
  peers.delete(id);
  log('info', `#${id} closed (${reason}) up=${p.upBytes}B down=${p.downBytes}B`);
  try { p.ws.close(); } catch { /* already gone */ }
  try { p.tcp.destroy(); } catch { /* already gone */ }
}

function start(opts = {}) {
  const legacyHost = opts.legacyHost || LEGACY_HOST;
  const legacyPort = opts.legacyPort || LEGACY_PORT;
  const bridgeHost = opts.bridgeHost || BRIDGE_HOST;
  const bridgePort = opts.bridgePort || BRIDGE_PORT;
  const wss = new WebSocketServer({ host: bridgeHost, port: bridgePort });
  wss.on('listening', () => {
    log('info', `bridge up: ws://${bridgeHost}:${bridgePort} -> ${legacyHost}:${legacyPort}`);
    if (LOG_PACKETS) log('warn', 'LOG_PACKETS=1: payload bytes are logged (may include session tokens). Dev only.');
  });
  wss.on('error', (err) => {
    log('error', 'websocket server error:', err.message);
    process.exitCode = 1;
  });

  wss.on('connection', (ws) => {
    const id = nextId++;
    const tcp = net.connect(legacyPort, legacyHost);
    const peer = { ws, tcp, upBytes: 0, downBytes: 0 };
    peers.set(id, peer);
    log('info', `#${id} ws connected, dialing ${legacyHost}:${legacyPort}`);

    tcp.on('connect', () => log('info', `#${id} tcp established`));
    tcp.on('data', (chunk) => {
      peer.downBytes += chunk.length;
      dumpPacket(id, 'SERVER->CLIENT', chunk);
      if (ws.readyState === WebSocket.OPEN) ws.send(chunk);
    });
    tcp.on('error', (err) => {
      log('warn', `#${id} tcp error: ${err.code || err.message}`);
      if (ws.readyState === WebSocket.OPEN) ws.close(1011, `tcp: ${err.code || 'error'}`);
      else closePeer(id, `tcp-error ${err.code || ''}`);
    });
    tcp.on('close', () => closePeer(id, 'tcp-closed'));

    ws.on('message', (data, isBinary) => {
      let buf;
      if (isBinary) {
        buf = Buffer.from(data);
      } else {
        // Legacy websockify text frames carry base64.
        try {
          buf = Buffer.from(String(data), 'base64');
        } catch {
          log('warn', `#${id} dropping undecodable text frame`);
          return;
        }
      }
      peer.upBytes += buf.length;
      dumpPacket(id, 'CLIENT->SERVER', buf);
      tcp.write(buf);
    });
    ws.on('close', (code) => closePeer(id, `ws-closed ${code}`));
    ws.on('error', (err) => {
      log('warn', `#${id} ws error: ${err.message}`);
      closePeer(id, 'ws-error');
    });
  });

  const shutdown = () => {
    log('info', 'shutting down...');
    for (const id of [...peers.keys()]) closePeer(id, 'shutdown');
    wss.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 2000).unref();
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
  return wss;
}

if (require.main === module) start();
module.exports = { start };

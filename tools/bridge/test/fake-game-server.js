// Fake legacy game server for integration tests. NOT a game implementation:
// it only proves the transport path Ruffle -> bridge -> TCP:8008 is live.
// Behaviour mirrors what the jar evidences (NetListener serves the Flash
// socket policy in-band on the game port), then records raw bytes.
const net = require('node:net');

const PORT = parseInt(process.env.FAKE_GAME_PORT || '8008', 10);
const POLICY = '<cross-domain-policy><allow-access-from domain="*" to-ports="8000-8889"/></cross-domain-policy>\0';

const server = net.createServer((sock) => {
  console.log(`[fake] connection from ${sock.remoteAddress}:${sock.remotePort}`);
  sock.on('data', (chunk) => {
    const head = chunk.subarray(0, 64).toString('utf8').replace(/[^\x20-\x7e]/g, '.');
    console.log(`[fake] ${chunk.length} bytes, head: ${head}`);
    if (chunk.includes('policy-file-request')) {
      console.log('[fake] policy request -> answering in-band (like NetListener)');
      sock.write(POLICY);
    }
  });
  sock.on('close', () => console.log('[fake] connection closed'));
  sock.on('error', (e) => console.log('[fake] error', e.message));
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[fake] listening on 127.0.0.1:${PORT}`);
});

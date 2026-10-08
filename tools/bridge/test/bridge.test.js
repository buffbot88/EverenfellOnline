// Tests for the WS<->TCP bridge. Transport tests use a deterministic fake
// TCP server (no game semantics). Protocol tests only assert properties we
// actually evidenced from the legacy tree (see docs/protocol.md):
//   - the Flash socket-policy handshake token passes through byte-identical
//   - 3-byte length-prefixed frames (AmfRequestDecoder reads bytes1..3 +
//     length) survive split TCP writes without bridge buffering/corruption
// Nothing here invents opcodes, login fields, or server responses.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const net = require('node:net');
const WebSocket = require('ws');
const { start } = require('../bridge');

const FAKE_PORT = 18008;
const BRIDGE_PORT = 18181;
const DEAD_PORT = 19999; // nothing listens: TCP-refused path

let fake;
let conns = []; // { sock, chunks, closed } — one per fake-server connection
let wss;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function waitFor(cond, timeout = 3000) {
  const t0 = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => (cond() ? resolve() : Date.now() - t0 > timeout
      ? reject(new Error('timeout')) : setTimeout(tick, 10));
    tick();
  });
}

before(async () => {
  fake = net.createServer((sock) => {
    const conn = { sock, chunks: [], closed: false };
    conns.push(conn);
    sock.on('data', (c) => conn.chunks.push(Buffer.from(c)));
    sock.on('close', () => { conn.closed = true; });
  });
  await new Promise((r) => fake.listen(FAKE_PORT, '127.0.0.1', r));
  wss = start({ legacyPort: FAKE_PORT, bridgePort: BRIDGE_PORT, bridgeHost: '127.0.0.1' });
  await new Promise((r) => wss.on('listening', r));
});

after(async () => {
  for (const c of conns) c.sock.destroy();
  fake.close();
  wss.close();
});

function dial() {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(`ws://127.0.0.1:${BRIDGE_PORT}`);
    ws.on('open', () => resolve(ws));
    ws.on('error', reject);
  });
}

// A fresh WS+TCP pair belonging to THIS test only — immune to cross-test
// close races from earlier tests.
async function freshPair() {
  const n = conns.length;
  const ws = await dial();
  await waitFor(() => conns.length === n + 1);
  const conn = conns[conns.length - 1];
  await waitFor(() => !conn.sock.destroyed);
  return { ws, conn };
}

function nextMessage(ws, timeout = 3000) {
  return new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error('no ws message')), timeout);
    ws.on('message', function h(d) {
      clearTimeout(t);
      ws.removeListener('message', h);
      res(Buffer.from(d));
    });
  });
}

test('websocket connects and a TCP connection is created', async () => {
  const n = conns.length;
  const ws = await dial();
  await waitFor(() => conns.length === n + 1);
  ws.close();
});

test('binary travels WS -> TCP byte-identical', async () => {
  const { ws, conn } = await freshPair();
  const payload = Buffer.from([0x00, 0x01, 0x02, 0xff, 0x00, 0x06, 0x43, 0x61, 0x74]);
  ws.send(payload);
  await sleep(100);
  ws.close();
  await waitFor(() => conn.closed);
  assert.deepEqual(Buffer.concat(conn.chunks), payload);
});

test('binary travels TCP -> WS byte-identical', async () => {
  const { ws, conn } = await freshPair();
  const payload = Buffer.from('server-bytes-\x00\xff-ok');
  const got = nextMessage(ws);
  conn.sock.write(payload);
  assert.deepEqual(await got, payload);
  ws.close();
});

test('multiple messages and a large message survive', async () => {
  const { ws, conn } = await freshPair();
  const parts = [Buffer.from('a'), Buffer.from('b'.repeat(1000)), Buffer.from([0, 255])];
  for (const p of parts) ws.send(p);
  const big = Buffer.alloc(262144);
  for (let i = 0; i < big.length; i++) big[i] = i & 0xff;
  ws.send(big);
  await sleep(300);
  ws.close();
  await waitFor(() => conn.closed);
  assert.deepEqual(Buffer.concat(conn.chunks), Buffer.concat([...parts, big]));
});

test('fragmented TCP writes arrive intact (no bridge buffering)', async () => {
  const { ws, conn } = await freshPair();
  // Synthetic 3-byte length-prefixed frame, as AmfRequestDecoder frames
  // (bytes1..3 + length): split across three TCP writes on purpose.
  const body = Buffer.from('x'.repeat(5000));
  const frame = Buffer.concat([Buffer.from([0x00, 0x13, 0x89]), body]);
  const received = [];
  ws.on('message', (d) => received.push(Buffer.from(d)));
  conn.sock.write(frame.subarray(0, 1));
  await sleep(50);
  conn.sock.write(frame.subarray(1, 100));
  await sleep(50);
  conn.sock.write(frame.subarray(100));
  await waitFor(() => Buffer.concat(received).length === frame.length);
  assert.deepEqual(Buffer.concat(received), frame);
  ws.close();
});

test('several frames in one TCP read all pass through', async () => {
  const { ws, conn } = await freshPair();
  const batch = Buffer.concat([Buffer.from([0, 0, 3, 1, 2, 3]), Buffer.from([0, 0, 2, 4, 5])]);
  const received = [];
  ws.on('message', (d) => received.push(Buffer.from(d)));
  conn.sock.write(batch);
  await waitFor(() => Buffer.concat(received).length === batch.length);
  assert.deepEqual(Buffer.concat(received), batch);
  ws.close();
});

test('socket-policy handshake passes through byte-identical', async () => {
  const { ws, conn } = await freshPair();
  // Exact token Flash sends (NUL-terminated); the legacy NetListener answers
  // the policy in-band, so the bridge must forward it untouched.
  const req = Buffer.from('<policy-file-request/>\0', 'utf8');
  const policy = '<cross-domain-policy><allow-access-from domain="*" to-ports="8000-8889"/></cross-domain-policy>\0';
  const got = nextMessage(ws);
  ws.send(req);
  conn.sock.write(Buffer.from(policy, 'utf8'));
  assert.equal((await got).toString('utf8'), policy);
  await sleep(100);
  ws.close();
  await waitFor(() => conn.closed);
  assert.deepEqual(Buffer.concat(conn.chunks).subarray(0, req.length), req);
});

test('two clients are isolated on separate TCP connections', async () => {
  const a = await freshPair();
  const b = await freshPair();
  assert.notEqual(a.conn, b.conn);
  a.ws.send(Buffer.from('from-A'));
  b.ws.send(Buffer.from('from-B'));
  await sleep(150);
  a.ws.close();
  b.ws.close();
  await waitFor(() => a.conn.closed && b.conn.closed);
  assert.equal(Buffer.concat(a.conn.chunks).toString(), 'from-A');
  assert.equal(Buffer.concat(b.conn.chunks).toString(), 'from-B');
});

test('clean disconnect tears down the TCP side', async () => {
  const { ws, conn } = await freshPair();
  const closed = new Promise((res) => conn.sock.on('close', () => res(true)));
  ws.close();
  assert.equal(await closed, true);
});

test('TCP connection failure is reported to the websocket', async () => {
  const bad = start({ legacyPort: DEAD_PORT, bridgePort: BRIDGE_PORT + 1, bridgeHost: '127.0.0.1' });
  await new Promise((r) => bad.on('listening', r));
  const ws = new WebSocket(`ws://127.0.0.1:${BRIDGE_PORT + 1}`);
  const code = await new Promise((res) => {
    ws.on('close', (c) => res(c));
    ws.on('error', () => {});
  });
  assert.equal(code, 1011);
  bad.close();
});

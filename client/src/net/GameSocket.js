// Milestone 2 stub: connection to the Java game server (127.0.0.1:8008).
//
// Why a stub? Browsers cannot open raw TCP sockets, and the game server
// speaks a proprietary binary protocol over TCP (Apache MINA, see
// config/net-io.properties `client_io_port = 8008`). The Flash client
// authenticated with the (uid, t, sign) token from gamesession.php and then
// exchanged binary packets. Two things are needed before this class can work:
//
//   1. Transport: a small WebSocket->TCP bridge (e.g. a Node process that
//      accepts ws:// connections from this client and relays bytes to
//      127.0.0.1:8008), OR WebSocket support added server-side.
//   2. Protocol: reverse-engineer packet framing/opcodes from Main.swf
//      (decompile with JPEXS FFDec) + the server jar's com.xianling.io
//      handlers, and document them under docs/protocol.md.
//
// Usage once implemented:
//   const sock = new GameSocket('ws://127.0.0.1:8080');
//   await sock.connect(session); // session = fetchGameSession()
//   sock.send(opcode, payload);

export default class GameSocket {
  constructor(url) {
    this.url = url;
    this.ws = null;
    this.session = null;
  }

  // eslint-disable-next-line no-unused-vars
  async connect(session) {
    this.session = session;
    throw new Error(
      'GameSocket: no transport yet. Milestone 2 must add a WebSocket->TCP ' +
        'bridge to 127.0.0.1:8008 and implement the binary packet protocol.',
    );
  }

  // eslint-disable-next-line no-unused-vars
  send(opcode, payload) {
    throw new Error('GameSocket: not connected (see connect()).');
  }

  close() {
    if (this.ws) this.ws.close();
    this.ws = null;
  }
}

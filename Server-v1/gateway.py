"""WebSocket gateway: browsers <-> Python game server (Mission 5).

Browsers cannot speak the raw TCP game socket, so this in-process
gateway translates. Packet semantics stay identical; only the transport
is adapted, per the contract in websites/everenfell/src/net/protocol.ts:

  <-> JSON envelopes { op, seq, body }; replies { op, seq, ok, body };
  server pushes use seq 0 (actor.moved).

The server stays authoritative: the gateway holds one headless upstream
game connection per browser (INITKEY + cipher + 10001 login with a
freshly minted sign, exactly like the stock client), forwards validated
snapshots, and sends only tile intents the server re-validates. No
gameplay rules live here.

Smallest loop: auth.session -> world.enter -> world.snapshot ->
player.move / actor.moved. Everything else answers not-implemented
until its gateway op lands with the browser UI that needs it.

Wire notes (from the captures and the protocol tests):
- TCP framing is u32be length + payload both directions; client->server
  payloads are SimpleEncrypt-enciphered after INITKEY, server->client
  stays plaintext asymmetric transport.
- Login: [10001, [user, ts_float, server, False, sign, 0, 1]].
- Entry: [10003, role] -> [20000, [role, map]] -> [21000, role].
- Move: [40000, [x, y, 0, 0, role]]; the server echoes 40000 tiles and
  23002 enter bursts for newly visible monsters.
- 23002 records: [id, template, name, level, hp, ...] with x, y at
  indexes 11, 12. 23003: [npcId, x, y]. 12004: [rid, hp, max, mp, max].
"""
import base64
import hashlib
import json
import socket
import struct
import threading
import time
from collections import deque

from game.amf3 import decode as amf3_decode
from game.amf3 import encode as amf3_encode
from game.cipher import SimpleEncrypt

WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
INITKEY = 'INITKEY'

# Game server selector registry (see docs/website-accounts-s1.md). Keys
# are the browser-facing ids; values are the game-scope server ids
# characters are scoped to. S1 only: each future server gets its own
# entry (and database). Cross-server play is a documented stub: nothing
# here talks across entries.
SERVERS = {'S1': 'fu1304'}

WS_AUDIENCES = {'everenfell-gateway'}
WS_ORIGINS = {
    'https://everenfell.agpstudios.org',
    'http://localhost:5173',
    'http://127.0.0.1:5173',
}


def ws_accept_key(key):
    """RFC 6455 accept header for a client key (includes the test vector)."""
    digest = hashlib.sha1((key + WS_GUID).encode()).digest()
    return base64.b64encode(digest).decode()


def ws_encode_text(payload):
    """Server->client unmasked text frame for a str or bytes payload."""
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    header = bytes([0x81])
    length = len(payload)
    if length < 126:
        header += bytes([length])
    elif length < 65536:
        header += bytes([126]) + struct.pack('>H', length)
    else:
        header += bytes([127]) + struct.pack('>Q', length)
    return header + payload


class WsFrameReader:
    """Incremental client->server frame decoder (masked text/close/ping).

    Server->client frames are never masked; client->server frames always
    are. Control frames are answered inline (ping->p and close echo are
    built by the caller from the returned events).
    """

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        """Consume bytes; return a list of ('text', str) / ('ping', bytes) / ('close', None)."""
        self.buf += data
        events = []
        while True:
            if len(self.buf) < 2:
                break
            first, second = self.buf[0], self.buf[1]
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            pos = 2
            if length == 126:
                if len(self.buf) < pos + 2:
                    break
                length = struct.unpack('>H', bytes(self.buf[pos:pos + 2]))[0]
                pos += 2
            elif length == 127:
                if len(self.buf) < pos + 8:
                    break
                length = struct.unpack('>Q', bytes(self.buf[pos:pos + 8]))[0]
                pos += 8
            if masked:
                if len(self.buf) < pos + 4:
                    break
                mask = bytes(self.buf[pos:pos + 4])
                pos += 4
            if len(self.buf) < pos + length:
                break
            payload = bytes(self.buf[pos:pos + length])
            del self.buf[:pos + length]
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x1:
                events.append(('text', payload.decode('utf-8', 'replace')))
            elif opcode == 0x9:
                events.append(('ping', payload))
            elif opcode == 0x8:
                events.append(('close', None))
            elif opcode == 0xA:
                continue
            else:
                raise ValueError('unsupported ws opcode 0x%02X' % opcode)
        return events


def ws_handshake_response(request_text):
    """Build the 101 response for the Everenfell WebSocket route, or None."""
    lines = request_text.split('\r\n')
    request = lines[0].split() if lines else []
    if len(request) != 3 or request[0] != 'GET' or request[1].split('?', 1)[0] != '/everenfell' or request[2] != 'HTTP/1.1':
        return None
    headers = {}
    for line in lines[1:]:
        if ':' in line:
            name, value = line.split(':', 1)
            headers[name.strip().lower()] = value.strip()
    if headers.get('upgrade', '').lower() != 'websocket':
        return None
    if 'upgrade' not in {value.strip().lower() for value in headers.get('connection', '').split(',')}:
        return None
    if headers.get('sec-websocket-version') != '13':
        return None
    origin = headers.get('origin')
    if origin and origin not in WS_ORIGINS:
        return None
    key = headers.get('sec-websocket-key')
    try:
        if len(base64.b64decode(key, validate=True)) != 16:
            return None
    except (TypeError, ValueError):
        return None
    accept = ws_accept_key(key)
    return ('HTTP/1.1 101 Switching Protocols\r\n'
            'Upgrade: websocket\r\n'
            'Connection: Upgrade\r\n'
            'Sec-WebSocket-Accept: ' + accept + '\r\n\r\n').encode()


class GameLink:
    """Headless upstream game connection (one per browser session)."""

    def __init__(self):
        self.sock = None
        self.cipher = None
        self.queue = deque()
        self.cond = threading.Condition()
        self.reader = None
        self.alive = False

    def connect(self, host, port, timeout=10):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self._send_raw(_tcp_frame(amf3_encode(INITKEY)))
        key = _tcp_read_frame(self.sock)
        self.cipher = SimpleEncrypt(key.decode())
        self.alive = True
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def close(self):
        self.alive = False
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass

    def _send_raw(self, data):
        self.sock.sendall(data)

    def send(self, cmd):
        payload = self.cipher.encode(amf3_encode(cmd))
        self._send_raw(_tcp_frame(payload))

    def _read_loop(self):
        buf = bytearray()
        try:
            while self.alive:
                try:
                    chunk = self.sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
                while len(buf) >= 4:
                    (length,) = struct.unpack('>I', bytes(buf[:4]))
                    if len(buf) < 4 + length:
                        break
                    payload = bytes(buf[4:4 + length])
                    del buf[:4 + length]
                    try:
                        msg = amf3_decode(payload)
                    except Exception:
                        continue
                    with self.cond:
                        self.queue.append(msg)
                        self.cond.notify_all()
        except OSError:
            pass
        finally:
            self.alive = False
            with self.cond:
                self.cond.notify_all()

    def wait_for(self, cmd, timeout=3.0):
        """Pop the first queued reply whose head equals cmd (str/int)."""
        deadline = time.time() + timeout
        with self.cond:
            while True:
                for _ in range(len(self.queue)):
                    msg = self.queue.popleft()
                    head = msg[0] if isinstance(msg, list) and msg else None
                    if str(head) == str(cmd):
                        return msg
                    self.queue.append(msg)
                remain = deadline - time.time()
                if remain <= 0:
                    return None
                self.cond.wait(timeout=remain)

    def drain(self, timeout=0.2):
        """Collect every message currently arriving within the window."""
        deadline = time.time() + timeout
        found = []
        with self.cond:
            while True:
                while self.queue:
                    found.append(self.queue.popleft())
                remain = deadline - time.time()
                if remain <= 0:
                    return found
                self.cond.wait(timeout=remain)


def _tcp_frame(payload):
    return struct.pack('>I', len(payload)) + payload


def _tcp_read_frame(sock):
    buf = bytearray()
    while len(buf) < 4:
        chunk = sock.recv(4 - len(buf))
        if not chunk:
            raise ConnectionError('upstream closed during handshake')
        buf += chunk
    (length,) = struct.unpack('>I', bytes(buf[:4]))
    body = bytearray()
    while len(body) < length:
        chunk = sock.recv(length - len(body))
        if not chunk:
            raise ConnectionError('upstream closed during handshake')
        body += chunk
    return bytes(body)


def monster_actors(records):
    """23002 records -> browser actor dicts (kinds: mob)."""
    actors = []
    for rec in records or []:
        try:
            actors.append({
                'id': str(rec[0]),
                'kind': 'mob',
                'template': str(rec[1]),
                'name': rec[2],
                'level': int(rec[3]),
                'hp': float(rec[4]),
                'x': int(rec[11]),
                'y': int(rec[12]),
            })
        except (IndexError, TypeError, ValueError):
            continue
    return actors


def npc_actors(records):
    """23003 records -> browser actor dicts (kind: npc)."""
    actors = []
    for rec in records or []:
        try:
            actors.append({
                'id': str(rec[0]),
                'kind': 'npc',
                'x': int(rec[1]),
                'y': int(rec[2]),
            })
        except (IndexError, TypeError, ValueError):
            continue
    return actors


class GatewaySession:
    """One browser connection: WS JSON ops over a headless game link."""

    SNAPSHOT_WAIT_S = 2.5
    MOVE_WAIT_S = 1.0

    def __init__(self, conn, game_host, game_port,
                 make_sign, server_id='fu1304', store=None,
                 servers=None):
        self.conn = conn
        self.game_host = game_host
        self.game_port = game_port
        self.make_sign = make_sign
        self.server_id = server_id
        self.store = store
        self.servers = dict(servers) if servers else dict(SERVERS)
        if 'S1' not in self.servers:
            self.servers['S1'] = server_id
        self.username = None
        self.member = None
        self.game_server_id = server_id
        self.roles = []
        self.link = GameLink()
        self.reader = WsFrameReader()
        self.role_id = None

    def run(self):
        try:
            request = self._read_http_request()
            response = ws_handshake_response(request)
            if response is None:
                self.conn.close()
                return
            self.conn.sendall(response)
            self._serve()
        except (OSError, ValueError):
            pass
        finally:
            self.link.close()
            try:
                self.conn.close()
            except OSError:
                pass

    def _read_http_request(self):
        data = b''
        while b'\r\n\r\n' not in data:
            chunk = self.conn.recv(4096)
            if not chunk:
                raise ConnectionError('closed during handshake')
            data += chunk
            if len(data) > 65536:
                raise ValueError('oversize handshake')
        return data.decode('latin-1')

    def _send(self, op, seq, ok, body):
        self.conn.sendall(ws_encode_text(json.dumps({
            'op': op, 'seq': seq, 'ok': ok, 'body': body})))

    def _push(self, op, body):
        self.conn.sendall(ws_encode_text(json.dumps({
            'op': op, 'seq': 0, 'body': body})))

    def _serve(self):
        while True:
            try:
                data = self.conn.recv(65536)
            except socket.timeout:
                continue
            if not data:
                return
            for kind, payload in self.reader.feed(data):
                if kind == 'ping':
                    self.conn.sendall(bytes([0x8A, len(payload)]) + payload)
                elif kind == 'close':
                    self.conn.sendall(bytes([0x88, 0x00]))
                    return
                elif kind == 'text':
                    self._handle_request(payload)

    def _handle_request(self, text):
        try:
            msg = json.loads(text)
            op, seq = msg['op'], int(msg.get('seq') or 0)
            body = msg.get('body') or {}
        except (ValueError, KeyError, TypeError):
            return
        try:
            if op == 'auth.session':
                result = self.op_auth_session(body)
            elif op == 'role.create':
                result = self.op_role_create(body)
            elif op == 'world.enter':
                result = self.op_world_enter(body)
            elif op == 'world.snapshot':
                result = self.op_world_snapshot(body)
            elif op == 'player.move':
                result = self.op_player_move(body)
            else:
                return self._send(op, seq, False,
                                  {'error': 'unknown op: %s' % op})
        except GatewayError as err:
            return self._send(op, seq, False, {'error': str(err)})
        except (OSError, ValueError) as err:
            return self._send(op, seq, False, {'error': 'upstream: %s' % err})
        except Exception as err:
            return self._send(op, seq, False,
                              {'error': 'gateway: %s' % err})
        self._send(op, seq, True, result)

    def op_auth_session(self, body):
        token = body.get('ticket')
        if not isinstance(token, str) or not token or self.store is None:
            raise GatewayError('valid one-use ticket required')
        ticket = self.store.consume_gateway_ticket(token)
        if not ticket:
            raise GatewayError('invalid or expired ticket')
        server = ticket['server']
        game_server_id = self.servers.get(server)
        if (ticket['game'] != 'everenfell' or server != 'S1'
                or game_server_id != self.server_id
                or ticket['game_server_id'] != game_server_id
                or ticket['audience'] not in WS_AUDIENCES
                or ticket['expires'] <= int(time.time())
                or str(ticket['role']).strip().casefold() != 'admin'
                or not ticket['entitled']):
            raise GatewayError('ticket not authorized for this gateway')
        if body.get('server') not in (None, server):
            raise GatewayError('ticket server mismatch')
        member = ticket['sub']
        if not member:
            raise GatewayError('invalid ticket identity')
        game_account = 'agp_' + hashlib.sha256(
            (member + '\0' + game_server_id).encode()).hexdigest()[:32]
        game_account = self.store.ensure_server_binding(
            member, game_server_id, game_account, verified=True)
        if not game_account:
            raise GatewayError('existing legacy game account is not linked')
        self.member = member
        self.username = game_account
        self.game_server_id = game_server_id
        self.browser_server = server
        self.link.connect(self.game_host, self.game_port)
        stamp = str(int(time.time()))
        sign = self.make_sign(self.username, stamp)
        self.link.send([10001, [self.username, float(stamp),
                                self.game_server_id, False, sign, 0, 1]])
        reply = self.link.wait_for('10001', timeout=5.0)
        if not reply or len(reply) < 2 or not reply[1][0]:
            raise GatewayError('game login refused')
        roles = reply[1][3] if len(reply[1]) > 3 else []
        # role_info arrays: [id, name, job, sex, level, None, face, ms].
        self.roles = [
            {'id': str(r[0]), 'name': r[1], 'job': r[2],
             'level': r[4]}
            for r in roles
            if isinstance(r, list) and len(r) > 4]
        get_home = getattr(self.store, 'get_home_server', None)
        return {'roles': self.roles, 'server': server,
                'homeServer': get_home(member) if get_home else None}

    def op_role_create(self, body):
        """Create a character via 10002; the server stays authoritative."""
        if not self.username:
            raise GatewayError('auth.session first')
        name = body.get('name')
        job = str(body.get('job') or '')
        try:
            sex = int(body.get('sex', 0))
        except (TypeError, ValueError):
            raise GatewayError('sex must be 0 or 1')
        face = str(body.get('face') or '')
        if not isinstance(name, str) or not name:
            raise GatewayError('name required')
        if job not in ('A', 'B', 'C', 'D'):
            raise GatewayError('job must be A, B, C or D')
        if sex not in (0, 1):
            raise GatewayError('sex must be 0 or 1')
        if len(self.roles or []) >= 4:
            raise GatewayError('character slots full (4)')
        server = getattr(self, 'browser_server', None)
        if server is None:
            server = next((browser_id for browser_id, game_id
                           in self.servers.items()
                           if game_id == self.game_server_id), 'S1')
        get_home = getattr(self.store, 'get_home_server', None)
        bind_home = getattr(self.store, 'bind_home_server', None)
        member = getattr(self, 'member', None)
        if get_home and member:
            bound = get_home(member)
            if bound is not None and bound != server:
                raise GatewayError(
                    'home server is %s; this gateway serves %s'
                    % (bound, server))
        self.link.send([10002, [self.username, name, job, sex, face,
                                0, self.game_server_id, '']])
        reply = self.link.wait_for('10002', timeout=5.0)
        if not reply or len(reply) < 2 or not isinstance(reply[1], list):
            raise GatewayError('creation refused by game server')
        status = reply[1][0] if reply[1] else 0
        if not status:
            code = reply[1][1] if len(reply[1]) > 1 else 0
            if code == 2005:
                raise GatewayError('character slots full (4)')
            if code == 2002:
                raise GatewayError('name already taken')
            raise GatewayError('illegal name (2001)')
        role = reply[1][1] if len(reply[1]) > 1 else []
        entry = {'id': str(role[0]), 'name': role[1], 'job': role[2],
                 'level': role[4]} if isinstance(role, list) and len(role) > 4 else {}
        if bind_home and member:
            bound = bind_home(member, server)
            if bound != server:
                delete = getattr(self.store, 'delete_character', None)
                if delete and entry.get('id'):
                    delete(entry['id'])
                raise GatewayError(
                    'home server is %s; this gateway serves %s'
                    % (bound, server))
        self.roles = list(self.roles or []) + ([entry] if entry else [])
        return {'role': entry, 'roles': self.roles}

    def op_world_enter(self, _body):
        if not self.username:
            raise GatewayError('auth.session first')
        get_home = getattr(self.store, 'get_home_server', None)
        return {'roles': getattr(self, 'roles', []),
                'homeServer': get_home(self.member) if get_home else None}

    def _collect_snapshot(self, role_id, wait_s):
        self.link.send([10003, role_id])
        self.link.wait_for('10003', timeout=5.0)
        self.link.send([20000, [role_id, '']])
        apply = self.link.wait_for('20000', timeout=5.0)
        map_id, at = '0', [0, 0]
        if apply and len(apply) > 1 and isinstance(apply[1], list):
            map_id = str(apply[1][1]) if len(apply[1]) > 1 else '0'
            at = apply[1][2] if len(apply[1]) > 2 else [0, 0]
        self.link.send([21000, role_id])
        frames = self.link.drain(timeout=wait_s)
        return map_id, at, frames

    @staticmethod
    def _frames_to_snapshot(map_id, frames, self_role):
        actors, vitals = [], {}
        for msg in frames:
            if not isinstance(msg, list) or len(msg) < 2:
                continue
            cmd, data = str(msg[0]), msg[1]
            if cmd == '23002':
                actors.extend(monster_actors(data))
            elif cmd == '23003':
                actors.extend(npc_actors(data))
            elif cmd == '12004' and isinstance(data, list) and len(data) > 4:
                vitals = {'hp': data[1], 'maxHp': data[2],
                          'mp': data[3], 'maxMp': data[4]}
        if self_role:
            actors.append({'id': self_role, 'kind': 'player',
                           'x': 0, 'y': 0, 'vitals': vitals})
        return {'mapId': map_id, 'actors': actors}

    def op_world_snapshot(self, body):
        if not self.username:
            raise GatewayError('auth.session first')
        role_id = str(body.get('roleId') or '')
        if not role_id:
            raise GatewayError('roleId required')
        owned = {r['id'] for r in (self.roles or []) if 'id' in r}
        if role_id not in owned:
            raise GatewayError('character not owned on this server')
        self.role_id = role_id
        map_id, at, frames = self._collect_snapshot(
            role_id, self.SNAPSHOT_WAIT_S)
        snapshot = self._frames_to_snapshot(map_id, frames, role_id)
        for actor in snapshot['actors']:
            if actor['id'] == role_id and actor['kind'] == 'player':
                try:
                    actor['x'] = int(at[0])
                    actor['y'] = int(at[1])
                except (IndexError, TypeError, ValueError):
                    pass
        return snapshot

    def op_player_move(self, body):
        if not self.username or not self.role_id:
            raise GatewayError('world.snapshot first')
        try:
            x, y = int(body['x']), int(body['y'])
        except (KeyError, TypeError, ValueError):
            raise GatewayError('integer x/y required')
        # tile_step never echoes 40000 to the mover (the stock client
        # predicts its own step); only 23002 enter bursts come back.
        # Accept optimistically like the stock client: the server logs
        # and ignores illegal steps, and the next snapshot re-syncs.
        self.link.send([40000, [x, y, 0, 0, self.role_id]])
        for msg in self.link.drain(timeout=self.MOVE_WAIT_S):
            if not isinstance(msg, list) or len(msg) < 2:
                continue
            if str(msg[0]) == '23002':
                for actor in monster_actors(msg[1]):
                    self._push('actor.moved', actor)
        return {'x': x, 'y': y}


class GatewayError(Exception):
    """Refused browser op: reported as { ok: false, error } verbatim."""


class GatewayServer:
    """TCP accept loop for browser WebSocket connections (daemon threads)."""

    def __init__(self, host, port, game_host, game_port,
                 make_sign, server_id='fu1304', store=None,
                 servers=None):
        self.host = host
        self.port = port
        self.game_host = game_host
        self.game_port = game_port
        self.make_sign = make_sign
        self.server_id = server_id
        self.store = store
        self.servers = servers
        self.sock = None

    def serve_forever(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen(50)
        while True:
            conn, _addr = self.sock.accept()
            conn.settimeout(60)
            session = GatewaySession(conn, self.game_host, self.game_port,
                                     self.make_sign, self.server_id,
                                     store=self.store, servers=self.servers)
            thread = threading.Thread(target=session.run, daemon=True)
            thread.start()

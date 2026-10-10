#!/usr/bin/env python3
"""Ask the running original Java server for frames, printed tap-style.

Usage: java_probe.py [--host 127.0.0.1] [--port 8008] [--uid 111111]
                     [--server fu1304] [--role fu0UR1-0-1-1]
                     [--cmd 10003] [--read SECONDS] [--raw]

Without --cmd it replays the captured world entry (login, 10003, 20000, 21000)
and prints every server frame as `S> <cmd> <args>` — the same shape as
output/orig-stack/tap-decoded.txt, so Java replies diff directly against the
Python server's. The legacy sign is forged (md5(uid+'xianlingkey'+t)).
"""
import argparse
import hashlib
import json
import os
import socket
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'Server-v1'))

from game import amf3                      # noqa: E402
from game.cipher import SimpleEncrypt      # noqa: E402
from game.protocol import frame            # noqa: E402

SIGN_SALT = 'xianlingkey'


def sign_for(uid, t):
    """The legacy game sign: md5(uid + 'xianlingkey' + t)."""
    return hashlib.md5(f'{uid}{SIGN_SALT}{t}'.encode()).hexdigest()


def recv_exact(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError('server closed the connection')
        buf += chunk
    return buf


def recv_frame(sock):
    """One length-prefixed frame payload, or None when the peer went away."""
    try:
        ln = int.from_bytes(recv_exact(sock, 4), 'big')
    except ConnectionError:
        return None
    if ln == 0 or ln > 48 * 1024 * 1024:
        return None
    return recv_exact(sock, ln)


def show(payload, raw=False):
    """Print one server payload as a tap-style line; `raw` also dumps hex."""
    try:
        msg = amf3.decode(payload)
    except Exception as e:
        print(f'S> <undecodable: {e}> len={len(payload)}')
        return
    if isinstance(msg, list) and msg:
        text = f'S> {msg[0]} {msg[1:]!r}'
    else:
        text = f'S> {msg!r}'
    print(text, flush=True)
    if raw:
        print('   hex=[' + ' '.join(f'{b:02x}' for b in payload) + ']', flush=True)


def reader(sock, stop):
    """Drain server frames until `stop` is set (or the socket closes)."""
    while not stop.is_set():
        payload = recv_frame(sock)
        if payload is None:
            print('S> <connection closed>', flush=True)
            return
        show(payload)


def connect(host, port, uid, timeout=10.0):
    """Handshake: INITKEY -> key, returning (socket, SimpleEncrypt cipher)."""
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(30.0)
    sock.sendall(frame(amf3.encode('INITKEY')))
    key = recv_frame(sock)
    if key is None:
        raise SystemExit('no key reply (is the Java server up?)')
    text = key.decode('utf-8', 'replace')
    print(f'# key received ({len(text)} chars: {text[:8]}...)', flush=True)
    return sock, SimpleEncrypt(text)


def world_entry(uid, server, role, t):
    """The captured client sequence: login, enter world, apply stage, 21000."""
    return [
        (10001, [[uid, float(t), server, False, sign_for(uid, t), False, 0, 0, 0]]),
        (10003, [role]),
        (20000, [[role, '5']]),
        (21000, [[role, '5']]),
    ]


def parse_cmd(text):
    """`10003:["role-id"]` or `19001` -> (cmd:int, args:list)."""
    cmd, _, payload = text.partition(':')
    args = json.loads(payload) if payload else []
    return int(cmd), args


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8008)
    ap.add_argument('--uid', default='111111')
    ap.add_argument('--server', default='fu1304')
    ap.add_argument('--role', default='fu0UR1-0-1-1')
    ap.add_argument('--cmd', action='append', default=[],
                    help='custom command, e.g. --cmd 53021 or --cmd 19001:[]')
    ap.add_argument('--read', type=float, default=4.0,
                    help='seconds to keep draining after each send')
    ap.add_argument('--raw', action='store_true', help='also dump frame hex')
    a = ap.parse_args()

    t = int(time.time())
    plan = ([parse_cmd(c) for c in a.cmd] if a.cmd
            else world_entry(a.uid, a.server, a.role, t))

    sock, cipher = connect(a.host, a.port, a.uid)
    stop = threading.Event()
    worker = threading.Thread(target=reader, args=(sock, stop), daemon=True)
    worker.start()
    try:
        for cmd, args in plan:
            print(f'C> {cmd} {args!r}', flush=True)
            sock.sendall(frame(cipher.encode(amf3.encode([cmd, *args]))))
            time.sleep(a.read)
    finally:
        stop.set()
        if a.read > 0:
            time.sleep(0.3)
        sock.close()
    print('# done', flush=True)


if __name__ == '__main__':
    main()

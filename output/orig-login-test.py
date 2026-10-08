"""Throwaway probe: raw TCP login against the ORIGINAL Java game server.

Touches only 127.0.0.1:8008 (Java) + its MySQL. No Vite, bridge, Ruffle,
or Python game server involved. Run: python3 output/orig-login-test.py
"""
import hashlib
import socket
import struct
import sys
import time

sys.path.insert(0, 'Server-v1')
from game.amf3 import decode as amf3_decode
from game.amf3 import encode as amf3_encode
from game.cipher import SimpleEncrypt

HOST, PORT = '127.0.0.1', 8008
UID, SEID = '111111', 'fu1304'


def frame(payload):
    return struct.pack('>I', len(payload)) + payload


def read_frame(sock):
    hdr = b''
    while len(hdr) < 4:
        chunk = sock.recv(4 - len(hdr))
        if not chunk:
            raise ConnectionError('closed waiting for header')
        hdr += chunk
    ln = struct.unpack('>I', hdr)[0]
    body = b''
    while len(body) < ln:
        chunk = sock.recv(ln - len(body))
        if not chunk:
            raise ConnectionError('closed waiting for body')
        body += chunk
    return body


sock = socket.create_connection((HOST, PORT), timeout=15)
sock.sendall(frame(amf3_encode('INITKEY')))
key = read_frame(sock).decode()
print('key exchange ok, key len:', len(key))
cipher = SimpleEncrypt(key)
t = str(int(time.time()))
sign = hashlib.md5((UID + 'xianlingkey' + t).encode()).hexdigest()
login = [10001, [UID, float(t), SEID, False, sign, 0, 1]]
sock.sendall(frame(cipher.encode(amf3_encode(login))))
reply = amf3_decode(read_frame(sock))
print('cmd:', reply[0])
print('result[0]:', reply[1][0])
print('server line:', reply[1][1][2])
print('roles:', reply[1][3])
print('envelope tail:', reply[2:])
sock.close()

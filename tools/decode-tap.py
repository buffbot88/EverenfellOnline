"""Reassemble tap.log TCP segments into frames and decode both directions.

Usage: python3 tools/decode-tap.py [tap.log]
Server->client is AMF3 plaintext; client->server is SimpleEncrypt'd
(session key taken from the key-exchange frame).
"""
import struct
import sys

sys.path.insert(0, 'server/py')
from game.amf3 import decode
from game.cipher import SimpleEncrypt

path = sys.argv[1] if len(sys.argv) > 1 else 'output/orig-stack/tap.log'
streams = {'C>S': bytearray(), 'S>C': bytearray()}
for ln in open(path, encoding='utf-8').read().splitlines():
    tag = 'C>S' if ' C>S ' in ln else ('S>C' if ' S>C ' in ln else None)
    if not tag or 'hex=[' not in ln:
        continue
    hexpart = ln.split('hex=[')[1].split(']')[0]
    streams[tag] += bytes(int(b, 16) for b in hexpart.split())

key = None
buf = bytes(streams['S>C'])
frames_s, i = [], 0
while i + 4 <= len(buf):
    (ln,) = struct.unpack('>I', buf[i:i + 4])
    if i + 4 + ln > len(buf):
        break
    frames_s.append(buf[i + 4:i + 4 + ln])
    i += 4 + ln
for f in frames_s:
    if f.startswith(b'<policy'):
        print('SRV POLICY')
    elif len(f) == 36:
        key = f.decode()
        print('SRV KEYEX')
    else:
        try:
            env = decode(f)
            print('SRV', repr(env[0]), '->', repr(env[1])[:280])
        except Exception as e:
            print('SRV FAIL len=%d head=%s %s' % (len(f), f[:24].hex(), e))

print('=== client ===')
cipher = SimpleEncrypt(key) if key else None
buf = bytes(streams['C>S'])
i = 0
while i + 4 <= len(buf):
    if buf[i:i + 4] == b'<pol':
        j = buf.index(b'\x00', i) + 1
        print('CLI POLICY')
        i = j
        continue
    (ln,) = struct.unpack('>I', buf[i:i + 4])
    if i + 4 + ln > len(buf):
        break
    payload = buf[i + 4:i + 4 + ln]
    i += 4 + ln
    if payload == b'\x06\x0fINITKEY':
        continue
    try:
        msg = decode(cipher.decode(payload))
        print('CLI', repr(msg[0]), '->', repr(msg[1:])[:200])
    except Exception as e:
        print('CLI FAIL len=%d head=%s %s' % (len(payload), payload[:24].hex(), e))

"""Decode per-connection frames from tools/tcp-tap.py logs."""
import struct
import sys

sys.path.insert(0, 'Server-v1')
sys.path.insert(0, '.')
from game.amf3 import Reader
from game.cipher import SimpleEncrypt


def parse_log(path):
    streams = {}
    with open(path, encoding='ascii') as source:
        for line in source:
            if 'hex=[' not in line:
                continue
            fields = line.split()
            try:
                conn = next((field[5:] for field in fields
                             if field.startswith('conn=')), 'legacy')
                direction = next(field for field in fields if field in ('C>S', 'S>C'))
                data = bytes.fromhex(line.split('hex=[', 1)[1].split(']', 1)[0])
            except (StopIteration, ValueError):
                continue
            streams.setdefault(conn, {'C>S': bytearray(), 'S>C': bytearray()})[direction].extend(data)
    return streams


def read_frames(data, allow_policy=False):
    frames, offset = [], 0
    if allow_policy and data.startswith(b'<policy-file-request'):
        end = data.find(b'\x00')
        if end < 0:
            return frames, offset
        frames.append(('policy', data[:end + 1]))
        offset = end + 1
    while len(data) - offset >= 4:
        length = struct.unpack('>I', data[offset:offset + 4])[0]
        if length > 48 * 1024 * 1024:
            raise ValueError(f'invalid frame length {length} at {offset}')
        end = offset + 4 + length
        if end > len(data):
            break
        frames.append(('frame', data[offset + 4:end]))
        offset = end
    return frames, offset


def decode_server(frames):
    for kind, payload in frames:
        if kind == 'policy':
            yield ('policy', payload)
        elif len(payload) == 36:
            yield ('key', payload.decode('ascii', 'replace'))
        else:
            reader = Reader(payload)
            try:
                while reader.p < len(payload):
                    yield ('message', reader.read())
            except Exception as exc:
                yield ('error', f'{len(payload)} bytes at AMF offset {reader.p}: {exc}')


def decode_client(frames, key):
    cipher = SimpleEncrypt(key) if key else None
    for kind, payload in frames:
        if kind == 'policy' or payload == b'\x06\x0fINITKEY':
            continue
        if cipher is None:
            yield ('error', 'encrypted client frame without key exchange')
            continue
        try:
            yield ('message', Reader(cipher.decode(payload)).read())
        except Exception as exc:
            yield ('error', f'{len(payload)} bytes: {exc}')


def summarize(path):
    for conn, stream in parse_log(path).items():
        srv, srv_used = read_frames(bytes(stream['S>C']))
        cli, cli_used = read_frames(bytes(stream['C>S']), allow_policy=True)
        key = next((value.decode('ascii') for kind, value in srv
                    if kind == 'frame' and len(value) == 36), None)
        print(f'CONNECTION {conn} key={bool(key)} '
              f'client={cli_used}/{len(stream["C>S"])} '
              f'server={srv_used}/{len(stream["S>C"])}')
        for kind, value in decode_server(srv):
            if kind == 'message' and isinstance(value, list) and value:
                print(' S>', value[0], repr(value[1:])[:260])
            elif kind == 'error':
                print(' S!>', value)
        for kind, value in decode_client(cli, key):
            if kind == 'message' and isinstance(value, list) and value:
                print(' C>', value[0], repr(value[1:])[:200])
            elif kind == 'error':
                print(' C!>', value)


if __name__ == '__main__':
    summarize(sys.argv[1] if len(sys.argv) > 1 else 'output/orig-stack/tap.log')

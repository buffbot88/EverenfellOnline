"""Relay projector traffic to the game server, logging every byte in both directions.

Usage: record-session.py [--listen 127.0.0.1:8009] [--target 127.0.0.1:8008]
Each run writes a new output/orig-stack/session-<time>.log, then a decoded
summary (session-<time>.decoded.txt) when stopped with Ctrl+C.
"""
import importlib.util
import itertools
import os
import socket
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, 'output', 'orig-stack')
_next_conn = itertools.count(1)
_log_lock = threading.Lock()


def parse_addr(text):
    host, port = text.rsplit(':', 1)
    return host, int(port)


def hexdump(log, conn_id, tag, data):
    line = (f'{time.strftime("%H:%M:%S")} conn={conn_id} {tag} len={len(data)} '
            f'hex=[{" ".join(f"{b:02x}" for b in data)}]\n')
    with _log_lock:
        log.write(line)
        log.flush()


def pipe(log, conn_id, src, dst, tag):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            hexdump(log, conn_id, tag, data)
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle(log, target, conn_id, client):
    server = None
    try:
        server = socket.create_connection(target)
        up = threading.Thread(target=pipe,
                              args=(log, conn_id, client, server, 'C>S'), daemon=True)
        up.start()
        pipe(log, conn_id, server, client, 'S>C')
        up.join(timeout=2)
    except OSError as exc:
        hexdump(log, conn_id, 'ERROR', str(exc).encode('ascii', 'replace'))
    finally:
        client.close()
        if server:
            server.close()


def decode_summary(log_path, out_path):
    """Run tools/decode-tap.py's summary over the new log and save it."""
    spec = importlib.util.spec_from_file_location(
        'decode_tap', os.path.join(ROOT, 'tools', 'decode-tap.py'))
    decode_tap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(decode_tap)
    previous = sys.stdout
    with open(out_path, 'w', encoding='utf-8') as out:
        sys.stdout = out
        try:
            decode_tap.summarize(log_path)
        finally:
            sys.stdout = previous


def main(argv):
    listen = parse_addr(argv[argv.index('--listen') + 1]) if '--listen' in argv \
        else ('127.0.0.1', 8009)
    target = parse_addr(argv[argv.index('--target') + 1]) if '--target' in argv \
        else ('127.0.0.1', 8008)
    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    log_path = os.path.join(OUT_DIR, f'session-{stamp}.log')
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(listen)
    server.listen(10)
    print(f'recording {listen} -> {target}, log: {log_path}', flush=True)
    with open(log_path, 'a', encoding='ascii') as log:
        try:
            while True:
                client, _ = server.accept()
                cid = next(_next_conn)
                threading.Thread(target=handle,
                                 args=(log, target, cid, client), daemon=True).start()
        except KeyboardInterrupt:
            print('stopping', flush=True)
        finally:
            server.close()
    decoded = os.path.join(OUT_DIR, f'session-{stamp}.decoded.txt')
    decode_summary(log_path, decoded)
    print(f'decoded summary: {decoded}', flush=True)


if __name__ == '__main__':
    main(sys.argv)

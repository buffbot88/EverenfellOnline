"""Forward TCP between projector and Java while recording each byte stream."""
import itertools
import os
import socket
import threading
import time

LISTEN = ('127.0.0.1', 8009)
TARGET = ('127.0.0.1', 8008)
LOG = 'output/orig-stack/tap.log'
_next_conn = itertools.count(1)
_log_lock = threading.Lock()


def hexdump(conn_id, tag, data):
    line = (f'{time.strftime("%H:%M:%S")} conn={conn_id} {tag} len={len(data)} '
            f'hex=[{" ".join(f"{b:02x}" for b in data)}]\n')
    with _log_lock:
        with open(LOG, 'a', encoding='ascii') as log:
            log.write(line)
            log.flush()


def pipe(conn_id, src, dst, tag):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            hexdump(conn_id, tag, data)
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle(conn_id, client):
    server = None
    try:
        server = socket.create_connection(TARGET)
        up = threading.Thread(target=pipe,
                              args=(conn_id, client, server, 'C>S'), daemon=True)
        up.start()
        pipe(conn_id, server, client, 'S>C')
        up.join(timeout=2)
    except OSError as exc:
        hexdump(conn_id, 'ERROR', str(exc).encode('ascii', 'replace'))
    finally:
        client.close()
        if server:
            server.close()


os.makedirs(os.path.dirname(LOG), exist_ok=True)
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(LISTEN)
server.listen(10)
print(f'tap up: {LISTEN} -> {TARGET}', flush=True)
while True:
    client, _ = server.accept()
    cid = next(_next_conn)
    threading.Thread(target=handle, args=(cid, client), daemon=True).start()

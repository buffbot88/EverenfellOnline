"""Transparent TCP tap: listen :8009, forward to :8008, hex-log everything.

Lets the projector play the genuine Java server while every frame is
captured to output/orig-stack/tap.log for later decoding (bridge can't
do this: the projector uses raw TCP, not WebSockets).
"""
import socket
import threading
import time

LISTEN = ('127.0.0.1', 8009)
TARGET = ('127.0.0.1', 8008)
LOG = 'output/orig-stack/tap.log'
CAP = 8192


def hexdump(tag, data):
    line = f'{time.strftime("%H:%M:%S")} {tag} len={len(data)} hex=[{" ".join(f"{b:02x}" for b in data[:CAP])}]'
    if len(data) > CAP:
        line += f' ...(+{len(data) - CAP})'
    with open(LOG, 'a') as f:
        f.write(line + '\n')


def pipe(src, dst, tag):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            hexdump(tag, data)
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle(client):
    server = socket.create_connection(TARGET)
    threading.Thread(target=pipe, args=(client, server, 'C>S'), daemon=True).start()
    pipe(server, client, 'S>C')
    client.close()
    server.close()


srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(LISTEN)
srv.listen(10)
print(f'tap up: {LISTEN} -> {TARGET}', flush=True)
while True:
    c, _ = srv.accept()
    threading.Thread(target=handle, args=(c,), daemon=True).start()

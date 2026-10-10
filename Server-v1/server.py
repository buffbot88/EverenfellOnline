"""MonkeyKingOnline Python server: game TCP :8008 + web account API.

Replaces the Java game server + ESSamp Apache/PHP + MySQL with stdlib
Python + SQLite (Pillow only for the captcha image).

  python server.py [--db data/mko.db] [--game 127.0.0.1:8008]
                   [--web 127.0.0.1:8080] [--captcha] [--debug]
"""
import argparse
import logging
import socketserver
import time

from auth import Sessions, check_sign
from db import Store
from game.config import DEFAULT_CONFIG_DIR, GameConfig
from game.protocol import Session as GameSession
from web import serve as serve_web

log = logging.getLogger()


import itertools as _itertools
_conn_ids = _itertools.count(1)


class GameTCPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        sess = GameSession(
            # Small monotonic ids: they stay AMF3 ints (BlazeDS emits Long
            # values as ints when they fit U29), avoiding double coercion.
            conn_id=next(_conn_ids),
            check_sign=self.server.check_sign,
            get_roles=self.server.get_roles,
            server_start_ms=self.server.server_start_ms,
            get_role_settings=self.server.get_role_settings,
            create_role=self.server.create_role,
            save_role_state=self.server.save_role_state,
            get_role_equip=self.server.get_role_equip,
            get_role_attr_buffs=self.server.get_role_attr_buffs,
            get_role_vip=self.server.get_role_vip,
            tz_raw_offset=self.server.tz_raw_offset,
            tz_id=self.server.tz_id,
            config=self.server.game_config)
        log.info('game conn from %s', self.client_address)
        try:
            while True:
                data = self.request.recv(65536)
                if not data:
                    break
                for out in sess.feed(data):
                    if self.server.log_frames:
                        from game.amf3 import decode as _amf3_decode
                        try:
                            log.info('conn %d: -> %r', sess.conn_id,
                                     _amf3_decode(out[4:]))
                        except Exception:
                            log.info('conn %d: -> %d raw bytes',
                                     sess.conn_id, len(out))
                    self.request.sendall(out)
        except (ConnectionResetError, BrokenPipeError, ValueError) as e:
            log.info('game conn closed: %s', e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/mko.db')
    ap.add_argument('--game', default='127.0.0.1:8008')
    ap.add_argument('--web', default='127.0.0.1:8080')
    ap.add_argument('--captcha', action='store_true')
    ap.add_argument('--config-dir', default=DEFAULT_CONFIG_DIR,
                    help='legacy config tree (sys_config/MapLine.jat, map_config/)')
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--log-frames', action='store_true',
                    help='log decoded server->client frames (diagnosis)')
    ap.add_argument('--tz-offset', type=int, default=-18000000,
                    help='client TimeZone.rawOffset in ms (the captured Java '
                         'server sent America/New_York: -18000000)')
    ap.add_argument('--tz-id', default='America/New_York',
                    help='client TimeZone ID/displayName (captured value: '
                         'America/New_York)')
    ap.add_argument('--add-char', metavar='ACCOUNT:NAME',
                    help='create a character for an account, then exit')
    ap.add_argument('--server-id', default='fu1304',
                    help='server id characters are scoped to')
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.debug else logging.INFO,
                        format='%(asctime)s [%(name)s] %(message)s')
    g_host, g_port = a.game.rsplit(':', 1)
    w_host, w_port = a.web.rsplit(':', 1)
    store = Store(a.db)
    sessions = Sessions(store)  # persisted: restart keeps logins valid

    if a.add_char:
        acct, _, name = a.add_char.partition(':')
        if not acct or not name:
            raise SystemExit('--add-char wants ACCOUNT:NAME')
        if not store.get_account(acct):
            raise SystemExit(f'no such account: {acct}')
        cid = store.create_character(acct, a.server_id, name)
        if cid is None:
            raise SystemExit(f'character {name} already exists for {acct}')
        print(f'created character id={cid} name={name} account={acct} '
              f'server={a.server_id}')
        return

    tcpd = socketserver.ThreadingTCPServer((g_host, int(g_port)), GameTCPHandler)
    tcpd.daemon_threads = True
    tcpd.check_sign = staticmethod(check_sign)
    tcpd.get_roles = lambda u, s: [
        dict(r)
        for r in store.list_roles(u, s)]
    tcpd.get_role_settings = store.get_role_settings
    tcpd.create_role = lambda acct, sid, name, job, sex, face: store.create_character(
        acct, sid, name, job=job, sex=sex, face=face)
    tcpd.save_role_state = store.update_character_state
    tcpd.get_role_equip = store.get_role_equip
    tcpd.get_role_attr_buffs = store.get_role_attr_buffs
    tcpd.get_role_vip = store.get_role_vip
    tcpd.log_frames = a.log_frames
    tcpd.tz_raw_offset = a.tz_offset
    tcpd.tz_id = a.tz_id
    tcpd.game_config = GameConfig(a.config_dir)
    tcpd.server_start_ms = int(time.time() * 1000)

    import threading
    threading.Thread(target=tcpd.serve_forever, daemon=True).start()
    log.info('game up: %s:%s', g_host, g_port)
    try:
        serve_web(store, sessions, w_host, int(w_port), a.captcha)
    except KeyboardInterrupt:
        pass
    tcpd.shutdown()


if __name__ == '__main__':
    main()

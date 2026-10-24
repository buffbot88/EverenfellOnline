"""MonkeyKingOnline Python server: game TCP :8008 + web account API.

Replaces the Java game server + ESSamp Apache/PHP + MySQL with stdlib
Python + SQLite (Pillow only for the captcha image).

  python server.py [--db data/mko.db] [--game 127.0.0.1:8008]
                   [--web 127.0.0.1:8080] [--captcha] [--debug]
"""
import argparse
import logging
import os
import socket
import socketserver
import threading
import time

from auth import Sessions, check_sign
from db import Store
from game import scheduler as scheduler_lib
from game.config import DEFAULT_CONFIG_DIR, GameConfig
from game.protocol import Session as GameSession
from game.stage_registry import StageRegistry
from web import serve as serve_web

log = logging.getLogger()


def tick_loop(server, interval):
    """1-second scheduler cadence: tick every session, push due frames."""
    while True:
        time.sleep(interval)
        try:
            with server.sessions_lock:
                pairs = list(server.sessions.items())
            scheduler_lib.tick_sessions(pairs)
        except Exception:
            log.warning('tick loop failed', exc_info=True)


import itertools as _itertools
_conn_ids = _itertools.count(1)


class GameTCPServer(socketserver.ThreadingTCPServer):
    """Game listener with TCP_NODELAY, matching the Java MINA acceptor."""

    def get_request(self):
        conn, addr = super().get_request()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return conn, addr


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
            save_role_settings=self.server.save_role_settings,
            create_role=self.server.create_role,
            save_role_state=self.server.save_role_state,
            find_roles_by_name=self.server.find_roles_by_name,
            get_role_equip=self.server.get_role_equip,
            save_role_equip=self.server.save_role_equip,
            get_role_jianding=self.server.get_role_jianding,
            save_role_jianding=self.server.save_role_jianding,
            get_role_dengluqi=self.server.get_role_dengluqi,
            save_role_dengluqi=self.server.save_role_dengluqi,
            get_role_online_reward=self.server.get_role_online_reward,
            save_role_online_reward=self.server.save_role_online_reward,
            get_role_qiandao=self.server.get_role_qiandao,
            save_role_qiandao=self.server.save_role_qiandao,
            get_role_jiangli_list=self.server.get_role_jiangli_list,
            save_role_jiangli_list=self.server.save_role_jiangli_list,
            get_role_husong=self.server.get_role_husong,
            save_role_husong=self.server.save_role_husong,
            get_role_loginlibao=self.server.get_role_loginlibao,
            save_role_loginlibao=self.server.save_role_loginlibao,
            get_role_loginlingjiang=self.server.get_role_loginlingjiang,
            save_role_loginlingjiang=self.server.save_role_loginlingjiang,
            get_role_touxian=self.server.get_role_touxian,
            save_role_touxian=self.server.save_role_touxian,
            get_role_guangyi=self.server.get_role_guangyi,
            save_role_guangyi=self.server.save_role_guangyi,
            get_role_baixian=self.server.get_role_baixian,
            save_role_baixian=self.server.save_role_baixian,
            get_role_zhuihui=self.server.get_role_zhuihui,
            save_role_zhuihui=self.server.save_role_zhuihui,
            get_role_dafuwong=self.server.get_role_dafuwong,
            save_role_dafuwong=self.server.save_role_dafuwong,
            get_role_xianshibuy=self.server.get_role_xianshibuy,
            save_role_xianshibuy=self.server.save_role_xianshibuy,
            get_xianshi_buy=self.server.get_xianshi_buy,
            save_xianshi_buy=self.server.save_xianshi_buy,
            get_role_lvlibao=self.server.get_role_lvlibao,
            save_role_lvlibao=self.server.save_role_lvlibao,
            list_role_email=self.server.list_role_email,
            get_role_email=self.server.get_role_email,
            save_role_email=self.server.save_role_email,
            update_role_email=self.server.update_role_email,
            delete_role_email=self.server.delete_role_email,
            save_role_vip=self.server.save_role_vip,
            get_role_vip_kaifu=self.server.get_role_vip_kaifu,
            save_role_vip_kaifu=self.server.save_role_vip_kaifu,
            get_role_vip_huodong_all=self.server.get_role_vip_huodong_all,
            get_role_vip_huodong=self.server.get_role_vip_huodong,
            save_role_vip_huodong=self.server.save_role_vip_huodong,
            get_role_qq_list=self.server.get_role_qq_list,
            save_role_qq_list=self.server.save_role_qq_list,
            get_vip_qq=self.server.get_vip_qq,
            save_vip_qq=self.server.save_vip_qq,
            get_role_attr_buffs=self.server.get_role_attr_buffs,
            get_role_vip=self.server.get_role_vip,
            get_role_xianjiechenhao=self.server.get_role_xianjiechenhao,
            get_role_meiren=self.server.get_role_meiren,
            save_role_meiren=self.server.save_role_meiren,
            get_role_baoshi=self.server.get_role_baoshi,
            save_role_baoshi=self.server.save_role_baoshi,
            get_role_zuoqi=self.server.get_role_zuoqi,
            save_role_zuoqi=self.server.save_role_zuoqi,
            get_role_pets=self.server.get_role_pets,
            save_role_pet=self.server.save_role_pet,
            get_role_pet_zhenfa=self.server.get_role_pet_zhenfa,
            save_role_pet_zhenfa=self.server.save_role_pet_zhenfa,
            get_zuoqi_fanhuan=self.server.get_zuoqi_fanhuan,
            save_zuoqi_fanhuan=self.server.save_zuoqi_fanhuan,
            get_role_skills=self.server.get_role_skills,
            get_role_shenjiang=self.server.get_role_shenjiang,
            save_role_shenjiang=self.server.save_role_shenjiang,
            get_role_chengjiu=self.server.get_role_chengjiu,
            save_role_chengjiu=self.server.save_role_chengjiu,
            save_role_skill=self.server.save_role_skill,
            save_role_stage=self.server.save_role_stage,
            get_role_bag_slots=self.server.get_role_bag_slots,
            get_role_bag_state=self.server.get_role_bag_state,
            get_role_bag_dummy=self.server.get_role_bag_dummy,
            add_role_bag_dummy=self.server.add_role_bag_dummy,
            get_role_zuwufuben=self.server.get_role_zuwufuben,
            save_role_zuwufuben=self.server.save_role_zuwufuben,
            get_role_zuwu=self.server.get_role_zuwu,
            list_role_zuwu=self.server.list_role_zuwu,
            save_role_zuwu=self.server.save_role_zuwu,
            get_role_bag_slot=self.server.get_role_bag_slot,
            get_role_bag_slot_by_bag_id=self.server.get_role_bag_slot_by_bag_id,
            update_role_bag_slot=self.server.update_role_bag_slot,
            delete_role_bag_slot=self.server.delete_role_bag_slot,
            get_booth=self.server.get_booth,
            save_booth=self.server.save_booth,
            get_booth_sell=self.server.get_booth_sell,
            get_booth_sell_by_slot=self.server.get_booth_sell_by_slot,
            list_friend_links=self.server.list_friend_links,
            has_friend_link=self.server.has_friend_link,
            count_friend_links=self.server.count_friend_links,
            follower_ids=self.server.follower_ids,
            friend_add_tx=self.server.friend_add_tx,
            friend_del_tx=self.server.friend_del_tx,
            friend_touch_foe_tx=self.server.friend_touch_foe_tx,
            get_friend_info=self.server.get_friend_info,
            save_friend_info=self.server.save_friend_info,
            friend_add_count_tx=self.server.friend_add_count_tx,
            list_booth_sells=self.server.list_booth_sells,
            save_booth_sell=self.server.save_booth_sell,
            delete_booth_sell=self.server.delete_booth_sell,
            list_public_booths=self.server.list_public_booths,
            list_booth_trade_logs=self.server.list_booth_trade_logs,
            save_booth_trade_log=self.server.save_booth_trade_log,
            get_role_brief=self.server.get_role_brief,
            move_role_bag_slot=self.server.move_role_bag_slot,
            insert_role_bag_slot=self.server.insert_role_bag_slot,
            rewrite_role_bag_slots=self.server.rewrite_role_bag_slots,
            save_role_bag_state=self.server.save_role_bag_state,
            get_task_main=self.server.get_task_main,
            save_task_main=self.server.save_task_main,
            get_task_taofa=self.server.get_task_taofa,
            get_task_taofas=self.server.get_task_taofas,
            insert_task_taofa=self.server.insert_task_taofa,
            update_task_taofa=self.server.update_task_taofa,
            delete_task_taofa=self.server.delete_task_taofa,
            get_task_taofa_state=self.server.get_task_taofa_state,
            save_task_taofa_state=self.server.save_task_taofa_state,
            get_task_richang=self.server.get_task_richang,
            save_task_richang=self.server.save_task_richang,
            delete_task_richang=self.server.delete_task_richang,
            get_task_gonghui=self.server.get_task_gonghui,
            save_task_gonghui=self.server.save_task_gonghui,
            delete_task_gonghui=self.server.delete_task_gonghui,
            get_role_huodong=self.server.get_role_huodong,
            save_role_huodong=self.server.save_role_huodong,
            get_huodong_info=self.server.get_huodong_info,
            huodong_exchange_tx=self.server.huodong_exchange_tx,
            huodong_mall_buy_tx=self.server.huodong_mall_buy_tx,
            charge_total_in_time=self.server.recharge_charge_total_in_time,
            charge_total=self.server.recharge_charge_total,
            charge_today=self.server.recharge_charge_today,
            save_recharge_yb=self.server.save_recharge_yb,
            recharge_check_order_repeat=
            self.server.recharge_check_order_repeat,
            recharge_grant_save_tx=self.server.recharge_grant_save_tx,
            recharge_finish_tx=self.server.recharge_finish_tx,
            yb_consume_tx=self.server.yb_consume_tx,
            get_role_pozhen=self.server.get_role_pozhen,
            save_role_pozhen=self.server.save_role_pozhen,
            get_guild_id=self.server.get_guild_id,
            save_guild_member=self.server.save_guild_member,
            add_guild_gongxian=self.server.add_guild_gongxian,
            tz_raw_offset=self.server.tz_raw_offset,
            tz_id=self.server.tz_id,
            config=self.server.game_config,
            stage_registry=self.server.stage_registry)
        log.info('game conn from %s', self.client_address)
        sess.send_lock = threading.Lock()
        sender = lambda frames: [self.request.sendall(f) for f in frames]
        with self.server.sessions_lock:
            self.server.sessions[sess] = sender
        try:
            while True:
                data = self.request.recv(65536)
                if not data:
                    break
                pace_ms = int(os.environ.get('MKO_PACE_MS', '0') or 0)
                for out in sess.feed(data):
                    if pace_ms > 0:
                        # TEMPORARY E3 experiment: mimic Java reply tempo.
                        # Revert after the verdict.
                        time.sleep(pace_ms / 1000.0)
                    if self.server.log_frames:
                        from game.amf3 import decode as _amf3_decode
                        try:
                            log.info('conn %d: -> %r', sess.conn_id,
                                     _amf3_decode(out[4:]))
                        except Exception:
                            log.info('conn %d: -> %d raw bytes',
                                     sess.conn_id, len(out))
                    with sess.send_lock:
                        self.request.sendall(out)
        except (ConnectionResetError, BrokenPipeError, ValueError) as e:
            log.info('game conn closed: %s', e)
        finally:
            try:
                # Notifies ride the followers' sessions; nothing goes
                # back down the closing connection.
                sess._friend_on_disconnect()
            except Exception:
                pass
            try:
                sess._juqing_on_disconnect()
            except Exception:
                pass
            try:
                sess._zuwu_on_disconnect()
            except Exception:
                pass
            try:
                sess._huodong_on_disconnect()
            except Exception:
                pass
            with self.server.sessions_lock:
                self.server.sessions.pop(sess, None)
            self.server.stage_registry.unregister_session(sess)


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
    ap.add_argument('--tick-interval', type=float, default=1.0,
                    help='scheduler tick seconds (0 disables the tick loop)')
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

    tcpd = GameTCPServer((g_host, int(g_port)), GameTCPHandler)
    tcpd.daemon_threads = True
    tcpd.sessions = {}
    tcpd.sessions_lock = threading.Lock()
    tcpd.check_sign = staticmethod(check_sign)
    tcpd.get_roles = lambda u, s: [
        dict(r)
        for r in store.list_roles(u, s)]
    tcpd.get_role_settings = store.get_role_settings
    tcpd.save_role_settings = store.save_role_settings
    tcpd.create_role = lambda acct, sid, name, job, sex, face: store.create_character(
        acct, sid, name, job=job, sex=sex, face=face)
    tcpd.save_role_state = store.update_character_state
    tcpd.find_roles_by_name = store.find_roles_by_name
    tcpd.get_role_equip = store.get_role_equip
    tcpd.save_role_equip = store.save_role_equip
    tcpd.get_role_jianding = store.get_role_jianding
    tcpd.save_role_jianding = store.save_role_jianding
    tcpd.save_role_vip = store.save_role_vip
    tcpd.get_role_vip_kaifu = store.get_role_vip_kaifu
    tcpd.save_role_vip_kaifu = store.save_role_vip_kaifu
    tcpd.get_role_vip_huodong_all = store.get_role_vip_huodong_all
    tcpd.get_role_qq_list = store.get_role_qq_list
    tcpd.save_role_qq_list = store.save_role_qq_list
    tcpd.get_vip_qq = store.get_vip_qq
    tcpd.save_vip_qq = store.save_vip_qq
    tcpd.get_role_vip_huodong = store.get_role_vip_huodong
    tcpd.save_role_vip_huodong = store.save_role_vip_huodong
    tcpd.get_role_attr_buffs = store.get_role_attr_buffs
    tcpd.get_role_vip = store.get_role_vip
    tcpd.get_role_xianjiechenhao = store.get_role_xianjiechenhao
    tcpd.get_role_meiren = store.get_role_meiren
    tcpd.save_role_meiren = store.save_role_meiren
    tcpd.get_role_baoshi = store.get_role_baoshi
    tcpd.save_role_baoshi = store.save_role_baoshi
    tcpd.get_role_zuoqi = store.get_role_zuoqi
    tcpd.save_role_zuoqi = store.save_role_zuoqi
    tcpd.get_role_pets = store.get_role_pets
    tcpd.save_role_pet = store.save_role_pet
    tcpd.get_role_pet_zhenfa = store.get_role_pet_zhenfa
    tcpd.save_role_pet_zhenfa = store.save_role_pet_zhenfa
    tcpd.get_zuoqi_fanhuan = store.get_zuoqi_fanhuan
    tcpd.save_zuoqi_fanhuan = store.save_zuoqi_fanhuan
    tcpd.get_role_skills = store.get_role_skills
    tcpd.get_role_shenjiang = store.get_role_shenjiang
    tcpd.save_role_shenjiang = store.save_role_shenjiang
    tcpd.get_role_chengjiu = store.get_role_chengjiu
    tcpd.save_role_chengjiu = store.save_role_chengjiu
    tcpd.save_role_skill = store.save_role_skill
    tcpd.save_role_stage = store.save_role_stage
    tcpd.get_role_bag_slots = store.get_role_bag_slots
    tcpd.get_role_bag_state = store.get_role_bag_state
    tcpd.get_role_bag_slot = store.get_role_bag_slot
    tcpd.get_role_bag_slot_by_bag_id = store.get_role_bag_slot_by_bag_id
    tcpd.get_role_skillbook_slots = store.get_role_skillbook_slots
    tcpd.get_role_skillbook_slot = store.get_role_skillbook_slot
    tcpd.insert_role_skillbook_slot = store.insert_role_skillbook_slot
    tcpd.update_role_skillbook_slot = store.update_role_skillbook_slot
    tcpd.delete_role_skillbook_slot = store.delete_role_skillbook_slot
    tcpd.get_role_buyback_all = store.get_role_buyback_all
    tcpd.get_role_buyback = store.get_role_buyback
    tcpd.get_role_bag_dummy = store.get_role_bag_dummy
    tcpd.add_role_bag_dummy = store.add_role_bag_dummy
    tcpd.get_role_zuwufuben = store.get_role_zuwufuben
    tcpd.save_role_zuwufuben = store.save_role_zuwufuben
    tcpd.get_role_zuwu = store.get_role_zuwu
    tcpd.list_role_zuwu = store.list_role_zuwu
    tcpd.save_role_zuwu = store.save_role_zuwu
    tcpd.insert_role_buyback = store.insert_role_buyback
    tcpd.delete_role_buyback = store.delete_role_buyback
    tcpd.get_role_prop = store.get_role_prop
    tcpd.save_role_prop = store.save_role_prop
    tcpd.get_role_loginlibao = store.get_role_loginlibao
    tcpd.save_role_loginlibao = store.save_role_loginlibao
    tcpd.get_role_loginlingjiang = store.get_role_loginlingjiang
    tcpd.save_role_loginlingjiang = store.save_role_loginlingjiang
    tcpd.get_role_touxian = store.get_role_touxian
    tcpd.save_role_touxian = store.save_role_touxian
    tcpd.get_role_guangyi = store.get_role_guangyi
    tcpd.save_role_guangyi = store.save_role_guangyi
    tcpd.get_role_baixian = store.get_role_baixian
    tcpd.save_role_baixian = store.save_role_baixian
    tcpd.get_role_zhuihui = store.get_role_zhuihui
    tcpd.save_role_zhuihui = store.save_role_zhuihui
    tcpd.get_role_dafuwong = store.get_role_dafuwong
    tcpd.save_role_dafuwong = store.save_role_dafuwong
    tcpd.get_role_xianshibuy = store.get_role_xianshibuy
    tcpd.save_role_xianshibuy = store.save_role_xianshibuy
    tcpd.get_xianshi_buy = store.get_xianshi_buy
    tcpd.save_xianshi_buy = store.save_xianshi_buy
    tcpd.get_role_lvlibao = store.get_role_lvlibao
    tcpd.save_role_lvlibao = store.save_role_lvlibao
    tcpd.list_role_email = store.list_role_email
    tcpd.get_role_email = store.get_role_email
    tcpd.save_role_email = store.save_role_email
    tcpd.update_role_email = store.update_role_email
    tcpd.delete_role_email = store.delete_role_email
    tcpd.get_role_qiandao = store.get_role_qiandao
    tcpd.save_role_qiandao = store.save_role_qiandao
    tcpd.get_role_jiangli_list = store.get_role_jiangli_list
    tcpd.save_role_jiangli_list = store.save_role_jiangli_list
    tcpd.get_role_dengluqi = store.get_role_dengluqi
    tcpd.save_role_dengluqi = store.save_role_dengluqi
    tcpd.get_role_online_reward = store.get_role_online_reward
    tcpd.save_role_online_reward = store.save_role_online_reward
    tcpd.get_role_husong = store.get_role_husong
    tcpd.save_role_husong = store.save_role_husong
    tcpd.update_role_bag_slot = store.update_role_bag_slot
    tcpd.delete_role_bag_slot = store.delete_role_bag_slot
    tcpd.move_role_bag_slot = store.move_role_bag_slot
    tcpd.insert_role_bag_slot = store.insert_role_bag_slot
    tcpd.rewrite_role_bag_slots = store.rewrite_role_bag_slots
    tcpd.save_role_bag_state = store.save_role_bag_state
    tcpd.get_booth = store.get_booth
    tcpd.save_booth = store.save_booth
    tcpd.get_booth_sell = store.get_booth_sell
    tcpd.get_booth_sell_by_slot = store.get_booth_sell_by_slot
    tcpd.list_booth_sells = store.list_booth_sells
    tcpd.save_booth_sell = store.save_booth_sell
    tcpd.delete_booth_sell = store.delete_booth_sell
    tcpd.list_public_booths = store.list_public_booths
    tcpd.list_booth_trade_logs = store.list_booth_trade_logs
    tcpd.save_booth_trade_log = store.save_booth_trade_log
    tcpd.list_friend_links = store.list_friend_links
    tcpd.has_friend_link = store.has_friend_link
    tcpd.count_friend_links = store.count_friend_links
    tcpd.follower_ids = store.follower_ids
    tcpd.friend_add_tx = store.friend_add_tx
    tcpd.friend_del_tx = store.friend_del_tx
    tcpd.friend_touch_foe_tx = store.friend_touch_foe_tx
    tcpd.get_friend_info = store.get_friend_info
    tcpd.save_friend_info = store.save_friend_info
    tcpd.friend_add_count_tx = store.friend_add_count_tx
    tcpd.get_role_brief = store.get_role_brief
    tcpd.get_task_main = store.get_task_main
    tcpd.save_task_main = store.save_task_main
    tcpd.get_task_taofa = store.get_task_taofa
    tcpd.get_task_taofas = store.get_task_taofas
    tcpd.insert_task_taofa = store.insert_task_taofa
    tcpd.update_task_taofa = store.update_task_taofa
    tcpd.delete_task_taofa = store.delete_task_taofa
    tcpd.get_task_taofa_state = store.get_task_taofa_state
    tcpd.save_task_taofa_state = store.save_task_taofa_state
    tcpd.get_task_richang = store.get_task_richang
    tcpd.save_task_richang = store.save_task_richang
    tcpd.delete_task_richang = store.delete_task_richang
    tcpd.get_task_gonghui = store.get_task_gonghui
    tcpd.save_task_gonghui = store.save_task_gonghui
    tcpd.delete_task_gonghui = store.delete_task_gonghui
    tcpd.get_role_huodong = store.get_role_huodong
    tcpd.save_role_huodong = store.save_role_huodong
    tcpd.get_huodong_info = store.get_huodong_info
    tcpd.huodong_exchange_tx = store.huodong_exchange_tx
    tcpd.huodong_mall_buy_tx = store.huodong_mall_buy_tx
    tcpd.recharge_charge_total_in_time = store.recharge_charge_total_in_time
    tcpd.recharge_charge_total = store.recharge_charge_total
    tcpd.recharge_charge_today = store.recharge_charge_today
    tcpd.save_recharge_yb = store.save_recharge_yb
    tcpd.recharge_check_order_repeat = store.recharge_check_order_repeat
    tcpd.recharge_grant_save_tx = store.recharge_grant_save_tx
    tcpd.recharge_finish_tx = store.recharge_finish_tx
    tcpd.yb_consume_tx = store.yb_consume_tx
    tcpd.get_role_pozhen = store.get_role_pozhen
    tcpd.save_role_pozhen = store.save_role_pozhen
    tcpd.get_guild_id = store.get_guild_id
    tcpd.save_guild_member = store.save_guild_member
    tcpd.add_guild_gongxian = store.add_guild_gongxian
    tcpd.log_frames = a.log_frames
    tcpd.tz_raw_offset = a.tz_offset
    tcpd.tz_id = a.tz_id
    tcpd.game_config = GameConfig(a.config_dir).warm()
    tcpd.stage_registry = StageRegistry()
    # Server open time echoed in the 10001 login reply (slot 0). The Java
    # server sends this fixed value (2014-03-10, the fu0 open date; captured
    # in session-20261018-040230), not its boot time. Mirrored exactly: the
    # client derives kaifu-day math from it (cf. _vip_kaifu_days).
    tcpd.server_start_ms = 1394466091000

    threading.Thread(target=tcpd.serve_forever, daemon=True).start()
    if a.tick_interval > 0:
        threading.Thread(target=tick_loop, args=(tcpd, a.tick_interval),
                         daemon=True).start()
        log.info('scheduler tick every %ss', a.tick_interval)
    log.info('game up: %s:%s', g_host, g_port)
    try:
        serve_web(store, sessions, w_host, int(w_port), a.captcha,
                  g_host, int(g_port))
    except KeyboardInterrupt:
        pass
    tcpd.shutdown()


if __name__ == '__main__':
    main()

"""Game wire protocol (port 8008), recovered from the jar via tools/javap.py.

Framing (AmfRequestDecoder/AmfResponseEncoder bytecode):
  every frame = u32be length + payload bytes. Server accumulates fragments
  (remain_buf) and loops over coalesced frames. Policy strings go raw.
Handshake:
  client -> u32be(9) + AMF3 "INITKEY"  (consumed, triggers key exchange)
  server -> u32be(36) + random UUID key bytes (no AMF3 wrapper)
  both sides init SimpleEncrypt(key, 'NITABAHAIZHENGEINIPOLE').
Messages (NetIoHandler/LoginAction/InOutput/PublicMsgSender bytecode):
  client -> [10001 int, [userId str, timestamp double, serverId str,
             needFangChenMi bool, verify str, ?, loginType int, ?, gmLogin bool?],
             ?,?,?,?,?, ip str, ...]
  server -> ['10001' str, result]  (2-element envelope, PublicMsgSender$2 path;
             byte-verified against genuine Java via raw-TCP probe — the
             10-element shape belongs to a different sender and the client
             drops it)
  client -> [19001, null]  (role GETTIME heartbeat; server -> ['19001', nowMs])
  client -> [20000, [?, mapId]]  (stagecontroll APPLY_CHANGE_STAGE after
             login; server -> ['20000', [1, mapId, [x, y]]] per
             StageControllOutputWrapper.applyChangeMap bytecode)
  client -> [10003, roleId str]  (stagecontroll LOGIN: enter world)
  server -> ['10003' str, result]  with result =
             [1, [face, level, exp, sex, job, chenmi, chenmiTime,
                   vipLevel, rechargeArr, gmState], [mapId, mapX, mapY]]
             per StageControllOutputWrapper.login bytecode
  success result = [1, [serverStartMs, nowMs, null, tzName, gmOpen, hefuMs],
                    [0,0], roles]
  signError result = [0, '16002']
Deviations from the original (all logged, to refine against the live client):
  - slot 2 -> "serverId-gsVersion" string (fu0-20140224_213740); TimeZone
    slot -> sealed sun.util.calendar.ZoneInfo with rawOffset/ID members.
  - role entries: shape unknown, so only the empty-roles case is served.
"""
import datetime
import json
import logging
import math
import random
import re
import struct
import threading
import time
import uuid

from .amf3 import ByteArray, Obj, SealedObj
from .attributes import entry_attribute_map
from .buffs import buff_change, buff_value, dynamic_cd, prop_buff, timed_buff
from . import ai as ai_lib
from . import loot as loot_lib
from .ground_items import can_pick_up as _ground_can_pick_up
from . import combat as combat_lib
from . import eventbus as eventbus_lib
from . import scheduler as scheduler_lib
from .ratelimit import TokenBucket
from .monster_world import MonsterWorld
from .amf3 import decode as amf3_decode
from .config import MALL_PRICE_COLUMNS, TASK_ATTRIBUTE_INDEX, convert_index_attribute, equip_vo, fujia_client_map, qh_xingxings_client, richang_condition_interval, richang_loop_interval, richang_reward_interval, xingxing_lv
from .amf3 import encode as amf3_encode
from .cipher import SimpleEncrypt, new_key

log = logging.getLogger('game')

POLICY_REQ = b'<policy-file-request'
POLICY_XML = ('<cross-domain-policy>'
              '<allow-access-from domain="*" to-ports="8000-8889"/>'
              '</cross-domain-policy>\x00').encode()

# Original server values (config/server-info.properties, config/version.properties).
GS_SIGNATURE = 'fu0-20140224_213740'

CMD_PING = 19000
CMD_LOGIN = 10001
CMD_CREATE_ROLE = 10002
CMD_ENTER_WORLD = 10003
CMD_GETTIME = 19001
CMD_APPLY_STAGE = 20000
CMD_CHANGE_STAGE = 21000
CMD_MONEY = 32010

# Java sends MapLineConfig.maptype in 21000 on every stage entry:
#   StageServiceImpl.roleEnterStage -> { Integer(1), stage.getLineNo(),
#                                        MapLineConfig.getMapType() }
# so the frame is [1, lineNo, mapType]. It is read from MapLine.jat via
# game/config.py. Maps missing from the table fall back to DEFAULT_MAP_TYPE and
# every fallback is logged, so a guess never passes silently as data.
DEFAULT_MAP_TYPE = 1
CMD_ROLE_EWAI = 12011
CMD_FIGHTING = 12010
CMD_RECIVE_YB = 35011
CMD_RECIVE_YB_CLAIM = 35012
CMD_ROLE_QUERY_NAME = 12200
# AccountServiceImpl.reciveYb codes (lingshi overflow and nothing pending).
RECIVE_YB_ERR_ZERO = 424016
RECIVE_YB_ERR_OVERFLOW = 424017
INT64_MAX = 9223372036854775807
CMD_MALL = 32000
CMD_MALL_BUY = 32001
CMD_DAFUWENG = 105003
CMD_DAFUWONG_INFO = 105000
CMD_DAFUWONG_ROLL = 105001
CMD_DAFUWONG_EXCHANGE = 105002
# Dafuwong errors: jifen short (CODE_105000), coin-roll cap (CODE_105001),
# empty board (RoleHuodongErrorCode.k792005). Xianshibuy errors are the
# XianshibuyErrorCode values (equal to their command numbers).
DAFUWONG_ERR_JIFEN = 105000
DAFUWONG_ERR_VIPROLLS = 105001
DAFUWONG_ERR_NOBOARD = 792005
CMD_XIANSHIBUY_CLIENT = 119000
CMD_XIANSHIBUY_INFO = 119001
CMD_XIANSHIBUY_BUY = 119002
CMD_XIANSHIBUY_CLEARCD = 119003
XSBUY_ERR_CLOSED = 119000
XSBUY_ERR_SOLDOUT = 119001
XSBUY_ERR_PMAX = 119002
XSBUY_ERR_CD = 119003
XSBUY_ERR_NOCD = 119004
CMD_SHENJIANG_INFO = 41023
CMD_SHENJIANG_ACTIVATE = 41001
CMD_SHENJIANG_SKILLUP = 41002
CMD_SHENJIANG_CANJIHUO = 41003
CMD_SHENJIANG_JIHUO = 41004
CMD_SHENJIANG_JINJIE = 41021
# 41005 has no Action (expShare is service-internal); 41010/41011 are
# stage-side transformation pushes; 41022 needs the wuhun goods mapping
# (no local source); 41024 needs the slot subsystem. All four deferred.
# ShenjiangErrorCode ints (jar clinit) and String codes ([0, code]).
SHENJIANG_ERR_NOSKILLCFG = 420001
SHENJIANG_ERR_MAXSKILL = 420010
SHENJIANG_ERR_FRAG = 420011
SHENJIANG_ERR_LV = 420012
SHENJIANG_ERR_SKILLLV = 420013
SHENJIANG_ERR_420015 = 420015
SHENJIANG_ERR_420016 = 420016
SHENJIANG_ERR_420017 = 420017
SHENJIANG_ERR_420018 = 420018
SHENJIANG_ERR_ACTIVED = '423000'
SHENJIANG_ERR_BEFORE = '423001'
SHENJIANG_ERR_MONEY = '423002'
SHENJIANG_ERR_LVNOTTOP = '423004'
SHENJIANG_ERR_RANKTOP = '423005'
SHENJIANG_ERR_LVTOP = '423006'
# MoneyType intType for jiangxingtu costs (YXB=1, YB=2, BIND_YB=3).
SHENJIANG_MONEY_NAMES = {1: 'YXB', 2: 'YB', 3: 'BIND_YB'}
CMD_QIANDAO_INFO = 58011
CMD_QIANDAO_SIGN = 58012
CMD_QIANDAO_BUQIAN = 58013
CMD_QIANDAO_REWARD = 58014
CMD_QIANDAO_MEIREN = 58015
CMD_YINGYIN_XIAZAI = 58017
CMD_YINGYIN_STATE = 58018
CMD_YINGYIN_REWARD = 58019
CMD_WEIDAN_STATE = 10060
CMD_WEIDAN_REWARD = 10061
CMD_ONLINE_INFO = 58003
CMD_ONLINE_YAOJIANG = 58004
CMD_ONLINE_LINGQU = 58005
CMD_HUSONG_POSITION = 83000
CMD_HUSONG_INFO = 83001
CMD_HUSONG_DAJIE = 83008
# JiangliErrorCodeOutput codes are Strings on the wire ([0, code]).
WEIDAN_ERR_NOT_MICRO = '592011'
WEIDAN_ERR_CLAIMED = '592012'
ONLINE_ERR_BAG_FULL = '592001'
QIANDAO_ERR_NOT_REPEAT = '592000'
QIANDAO_ERR_REWARD_REPEAT = '592001'
QIANDAO_ERR_COUNT_SHORT = '592002'
QIANDAO_ERR_VIP_CFG_NULL = '592007'
QIANDAO_ERR_CANNOT_BUQIAN = '592010'
YINGYIN_ERR_CLAIMED = '592013'
YINGYIN_ERR_PAST_WINDOW = '592014'
ONLINE_ERR_NOT_REPEAT = '592003'
ONLINE_ERR_TIME_SHORT = '592004'
ONLINE_ERR_MONTH_LIMIT = '592005'
ONLINE_ERR_NO_BINDYB = '592006'
# 32002 is declared in MallCommands (SELL_GOODS) but its inbound route lives
# in BuyBackModuleInit; 32005 is a server push with no inbound route (like
# the 30104/30105 split pushes).
CMD_BUYBACK_SELL = 32002
CMD_BUYBACK_HUIGOU = 32003
CMD_BUYBACK_LIST = 32004
CMD_BAGDUMMY_DUIHUAN = 93002
CMD_BUYBACK_EVICT = 32005
CMD_GONGHUI_MALL_COUNT = 32006
# GoodsBuyBackError codes are Strings on the wire (unlike the int General
# codes), so the buyback replies carry '1003'/'1006'/'430405' as strings.
BUYBACK_ERR_NO_CONFIG = '430405'
BUYBACK_ERR_JB_SHORT = '1003'
BUYBACK_ERR_NO_SLOT = '1006'
BUYBACK_MAX_ROWS = 27
CMD_JUQING_AWARD = 64010
CMD_JUQING_INFO = 64001
CMD_JUQING_CHALLENGE = 64002
CMD_JUQING_SAODANG = 64004
CMD_JUQING_FINISH = 64006
CMD_JUQING_ACCEL = 64007
CMD_JUQING_LINGQU = 64012
CMD_JUQING_ONEKEY = 64013
CMD_VIP = 62000
CMD_ZUWU = 111000
CMD_ZUWUFUBEN = 108001
CMD_ZUWU_ENTER = 108002
CMD_ZUWU_SAODANG = 108004
CMD_ZUWU_QUIT = 108006
CMD_ZUWU_BUY = 108009
CMD_ZUWU_REFRESH = 108010
CMD_ZUWU_BUYALL = 108011
CMD_ROLE_SETTINGS = 13000
CMD_SETTING_QUICKBAR = 13001
CMD_SETTING_PANEL = 13002
CMD_SETTING_UI = 13003
CMD_SETTING_GUAJI = 13004
CMD_ROLE_ATTRS = 12000
CMD_ROLE_EXP_PUSH = 12001
CMD_ROLE_ZHENQI_CAP = 12050
CMD_ZUOQI_INFO = 12102
CMD_EQUIP_INFO = 31000
CMD_EQUIP_QIANGHUA = 34000
CMD_EQUIP_JINJIE = 34001
CMD_EQUIP_QIANGHUA_CLEAR = 34003
CMD_EQUIP_JIANDING = 34004
CMD_EQUIP_JIANDING_CLEAR = 34005
CMD_EQUIP_JIANDING_EXP = 34006
CMD_EQUIP_HECHENG = 34007
CMD_EQUIP_HECHENG_COUNT = 34008
CMD_VIP_DAY = 62001
CMD_VIP_WEEK = 62002
CMD_VIP_TEJIA = 62004
CMD_VIP_KAIFU = 62020
CMD_VIP_LOTTERY = 62021
CMD_VIP_LINGJIANG = 62022
CMD_VIP_HUODONG = 88000
CMD_VIP_HUODONG_GUDING = 88001
CMD_VIP_HUODONG_CHOUJIANG = 88002
# Service-internal pushes (no inbound route): vip level change and prop value.
CMD_VIP_LEVEL_UP = 62003
CMD_VIP_PROP_VALUE = 62006
CMD_VIPQQ_INFO = 88003
CMD_VIPQQ_REWARDS = 88004
# CAN_REWARDS push (no inbound route): vipQqOK after QQ binding.
CMD_VIPQQ_BIND_PUSH = 88005
# VipQqErrorCode (String fields; values equal names).
VIPQQ_ERR_NOBIND = '794000'
VIPQQ_ERR_CLAIMED = '794001'
VIPQQ_ERR_NOCONFIG = '794002'
# BagErroeCodes.BAG_SLOT_LESS (clinit value).
BAG_ERR_SLOT_LESS = 430212
DAY_MS = 86400000
VIP_ERR_HUODONG_TIME = 621007
VIP_ERR_HUODONG_CLAIMED = 621008
VIP_ERR_HUODONG_DRAWN = 621009
# VipErrorCode (values equal names) + the one GeneralErrorCode used here.
VIP_ERR_CLAIMED_DAY = 621001
VIP_ERR_NOVIP = 621002
VIP_ERR_CLAIMED_WEEK = 621003
VIP_ERR_ABOVE_LEVEL = 621004
VIP_ERR_CLAIMED_TEJIA = 621005
VIP_ERR_CLAIMED_KAIFU = 621010
VIP_ERR_DAY_MISMATCH = 621011
VIP_ERR_NO_LOTTERY = 621012
VIP_ERR_NO_COUNT = 621013
GENERAL_VIP_LEVEL = 1011
GENERAL_ZUOQI_RANK = 1013
CMD_EQUIP_QIANGHUA_MAX = 34009
# 31015 rides inside the 11101 broadcast; 30106 is a session-directed push.
# Neither has an inbound route (like the 30104/30105 split pushes).
CMD_EQUIP_NOTICE = 31015
CMD_EQUIP_JINJIE_NOTICE = 31016
CMD_EQUIP_MAX_NOTICE = 31035
CMD_EQUIP_CHANGE = 30106
CMD_EQUIP_DRESS = 31001
CMD_NOTICE_ALL = 11101
# EquipErrorCode (equip/output/EquipErrorCode clinit; values equal names).
EQUIP_ERROR_NOSLOT = 31001
# Dress codes (31001 doubles as the dress command id, same number space).
EQUIP_ERROR_DRESS_MISMATCH = 31002
EQUIP_ERROR_DRESS_NOROOM = 31003
EQUIP_ERROR_DRESS_NOCONFIG = 31004
EQUIP_ERROR_DRESS_NOTEQUIP = 31005
EQUIP_ERROR_DRESS_BADSLOT = 31006
EQUIP_ERROR_DRESS_LEVEL = 31007
EQUIP_ERROR_DRESS_SEX = 31008
EQUIP_ERROR_DRESS_JOB = 31014
EQUIP_ERROR_DRESS_ZUOQIRANK = 31036
EQUIP_ERROR_DRESS_YUANSHEN = 31038
EQUIP_ERROR_MAXED = 31009
EQUIP_ERROR_NOQH = 31010
EQUIP_ERROR_MONEY = 31011
EQUIP_ERROR_GOODS = 31012
EQUIP_ERROR_NOJJ = 31013
# Jianding codes (EquipErrorCode; 31015/31016 reuse the push ids above,
# same number space as the original). 1003 rides on GENERAL_JB.
EQUIP_ERROR_JD_NOGOLD = 31015
EQUIP_ERROR_JD_VIPLV = 31016
EQUIP_ERROR_JD_EQLV = 31017
EQUIP_ERROR_JD_LVLMATCH = 31020
EQUIP_ERROR_JD_SLOT = 31021
EQUIP_ERROR_JD_NOTJD = 31027
EQUIP_ERROR_JD_MAT = 31028
# Hecheng codes (EquipErrorCode; stone/bag-space ride GeneralErrorCode).
EQUIP_ERROR_HC_ARGS = 31022
EQUIP_ERROR_HC_LEVEL = 31023
EQUIP_ERROR_HC_KIND = 31024
EQUIP_ERROR_HC_JUAN = 31025
EQUIP_ERROR_HC_LIMIT = 31026
EQUIP_ERROR_HC_MAT = 31029
# GoodsCategoryUtil codes: equip gear vs appraisal-stone materials.
GOODS_CATEGORY_EQUIP = '20'
GOODS_CATEGORY_JDCAILIAO = '90'
EQUIP_ERROR_MAXED11 = 31034
GENERAL_YB_SHORT = 1002
CMD_BAG_GOODS = 30000
CMD_BAG_CLEARUP = 30001
CMD_STORAGE_GOODS = 30002
CMD_STORAGE_CLEARUP = 30003
CMD_BAG_MOVE = 30004
CMD_XUNBAO_GOODS = 30005
CMD_XUNBAO_CLEARUP = 30006
CMD_BAG_ACTIVATE = 30201
CMD_STORAGE_ACTIVATE = 30202
CMD_BAG_GROWUP = 30203
CMD_STORAGE_GROWUP = 30204
CMD_BAG_INSPECT = 30302
CMD_MAIN_TASK = 50000
CMD_CHAPTERS = 50001
CMD_SUBCHAPTER = 50002
CMD_TASK_INFO = 50003
CMD_SUBMIT_TASK = 50005
CMD_CHAPTER_TIPS = 50008
CMD_TAOFA_LIST = 50101
CMD_TAOFA_TUNSHI = 50103
CMD_ZUOQI_RIDE = 33000
CMD_ZUOQI_PANEL = 33001
CMD_ZUOQI_HP = 33022
CMD_ZUOQI_JINJIE = 33003
CMD_ZUOQI_CLAIM = 33004
CMD_ZUOQI_FANHUAN = 33005
CMD_ZUOQI_MEIREN = 33006
CMD_ZUOQI_FANHUAN_LIST = 33007
CMD_ZUOQI_ZHANLI = 33008
CMD_ZUOQI_AWARD = 33011
CMD_ZUOQI_FULLHP = 33020
CMD_ZUOQI_REVIVE = 33021
CMD_ZUOQI_FREEREVIVE = 33023
CMD_ZUOQI_DEADINFO = 33024
# StageErrorCode mount cells (dntg_start.jar clinit values): 82140 not
# revivable, 82143 short on YB, 82144 already full, 82147 short on YXB.
ZUOQI_ERR_NEED_REVIVE = 82140
ZUOQI_ERR_REVIVE_YB = 82143
ZUOQI_ERR_FULLHP_STATE = 82144
ZUOQI_ERR_FULLHP_MONEY = 82147
# Mount pill pushes (RoleZuoQiServiceImpl.useLongHun/useLongLing, reached
# only through the 30301 prop flow); ZuoQiModuleInit routes neither id, so
# the ledger tracks them as emitted pushes, like CMD_MEIREN_ADD below.
CMD_ZUOQI_LONGHUN = 33010
CMD_ZUOQI_LONGLING = 33012
# ZuoQiErrorCode cells used by the pill flow (dntg_start.jar clinit
# values): 520004 rank short, 520011 per-goods cap hit.
ZUOQI_RANK_CODE = 520004
ZUOQI_ATT_CAP_CODE = 520011
# addMeiRen's 82001 push (CreateMeirenOutPut.getMeiRen), emitted by 33006.
CMD_MEIREN_ADD = 82001
# Inbound meiren routes (MeirenModuleInit.getInCmd: 82000-82003 only).
CMD_MEIREN_PANEL = 82000
CMD_MEIREN_UPGRADE = 82002
CMD_MEIREN_CHANMIAN = 82003
# Inbound pet routes (PetModuleInit.getInCmd: 136000-136009; method map
# from @EasyMapping: 136000 getPetInfo, 136001 activatePet, 136002
# upgradePet, 136003 petJinJie, 136004 upgradeZhenFa, 136005 upDownZhen,
# 136006 chuZhan, 136008 chuanChen, 136009 jinJieZhenFa). 136007 has no
# handler jar-wide (dead route, like 58016); 136010/136011 are pushes.
# 136001/136002/136003/136004/136008/136009 need the ChongWu(Biao/
# ShengJi/ZhenFa) config tables, which do not ship in the reference
# config tree, so they stay unported. PetErrorCode.CODE_13600x is the
# command id itself.
CMD_PET_INFO = 136000
CMD_PET_UPDOWN = 136005
CMD_PET_CHUZHAN = 136006
CMD_PET_ZHENFA_PUSH = 136010
CMD_PET_CHUZHAN_PUSH = 136011
PET_ERR_NO_PET = 136005
PET_ERR_DEPLOYED = 136006
PET_ERR_CHUZHAN_DUP = 136010
# Inbound email claim routes (EmailModuleInit.getInCmd: 63003/63006/63007/
# 63008; 63005/63009 are server pushes). EmailErrorCode clinit values:
# 60001 missing mail, 60002 no attachment, 60005/60006 empty JB/YB
# purse, 60007 bag full, 60008 expired (validTime, unseeded here).
EMAIL_ERR_NOT_FOUND = 60001
EMAIL_ERR_NO_ATTACHMENT = 60002
EMAIL_ERR_NO_JB = 60005
EMAIL_ERR_NO_YB = 60006
EMAIL_ERR_BAG_LESS = 60007
EMAIL_ERR_EXPIRED = 60008
# Inbound baoshi routes (BaoShiModuleInit.getInCmd: 37000/37001/37002).
CMD_BAOSHI_INFO = 37000
CMD_BAOSHI_JIHUO = 37001
CMD_BAOSHI_UPGRADE = 37002
# BaoShiErrorCode (530001-530011; NEED_JIHUO has no use site in the
# ported flow, and the 530011 broadcast rides no bus, like 11101).
BAOSHI_ERR_JIHUOED = 530001
BAOSHI_ERR_CANNOT = 530002
BAOSHI_ERR_GOODS_J = 530003
BAOSHI_ERR_ZHENQI_J = 530004
BAOSHI_ERR_NEED_JIHUO = 530005
BAOSHI_ERR_TOP = 530006
BAOSHI_ERR_GOODS_U = 530007
BAOSHI_ERR_ZHENQI_U = 530008
BAOSHI_ERR_LEVEL = 530009
BAOSHI_ERR_GRADE = 530010
BAOSHI_ERR_NOTIFY = 530011
# Shared bag checks surfacing through baoshi (BagErroeCodes).
BAG_ERR_MALL = 430249
BAG_ERR_TRY = 430250
# Inbound chengjiu routes (ChengjiuModuleInit.getInCmd: 89000/89005 only).
CMD_CHENGJIU_PANEL = 89000
CMD_CHENGJIU_CLAIM = 89005
CMD_RICHANG_INFO = 50201
CMD_RICHANG_DECREASE = 50202
CMD_RICHANG_INCREASE = 50203
CMD_RICHANG_ZHIJIE = 50204
CMD_RICHANG_COMPLETE_ALL = 50205
CMD_RICHANG_COMPLETE_BEST = 50206
CMD_RICHANG_NOTIFY_LOOP = 50209
# Server pushes with no inbound route (TaskTaoFaAction only serves
# 50101/50103; TaskRiChangAction only 50201-50206/50209).
CMD_TAOFA_RECEIVE = 50102
CMD_TAOFA_CHANGE = 50104
CMD_TAOFA_PAY = 50105
CMD_RICHANG_PAY = 50207
CMD_RICHANG_CHANGE = 50208
CMD_RICHANG_RECEIVE = 50210
CMD_RICHANG_STOP = 50211
# TaskErrorCode (task/output/TaskErrorCode clinit) for taofa/richang.
TASK_ERR_TAOFA_NO_GOODS = 480040
TASK_ERR_TAOFA_USE_MAX = 480041
TASK_ERR_TAOFA_RECEIVE_MAX = 480042
TASK_ERR_TAOFA_NO_EXIST = 480044
TASK_ERR_TAOFA_TUNSHI_MAX = 480045
TASK_ERR_TAOFA_NO_TUNSHI = 480046
TASK_ERR_TAOFA_CONFIG = 480048
TASK_ERR_RICHANG_MAX_LOOP = 480060
TASK_ERR_RICHANG_DIFF_MIN = 480061
TASK_ERR_RICHANG_THICK_MAX = 480062
TASK_ERR_NOT_RICHANG = 480073
# TaskTaoFaConstants/TaskConfigConstants + richang costs (game/config.py
# carries the same values beside the tables they govern).
TAOFA_MAX_TUNSHI = 5
TAOFA_MAX_USE = 10
TAOFA_RECEIVE_MAX = 20
RICHANG_MIN_LEVEL = 40
RICHANG_MAX_LOOP = 20
RICHANG_THICK_MAX = 10
RICHANG_COST_ONEKEY = 50
RICHANG_COST_ONEKEY_BEST = 100
RICHANG_COST_JIANGDI = 50000
RICHANG_COST_TISHENG = 50000
RICHANG_COST_DIRECT = 10
# Gonghuitask inbound routes (GonghuitaskAction) and server pushes.
CMD_GONGHUI_INFO = 81000
CMD_GONGHUI_DECREASE = 81001
CMD_GONGHUI_INCREASE = 81002
CMD_GONGHUI_ZHIJIE = 81003
CMD_GONGHUI_COMPLETE_ALL = 81004
CMD_GONGHUI_COMPLETE_BEST = 81005
CMD_GONGHUI_NOTIFY_LOOP = 81008
# Server pushes with no inbound route (change/pay/receive/stop fan out
# from the kill hook, zhijie/notify and the loop advance).
CMD_GONGHUI_PAY = 81006
CMD_GONGHUI_CHANGE = 81007
CMD_GONGHUI_RECEIVE = 81009
CMD_GONGHUI_STOP = 81010
# GonghuitaskErrorCode (gonghuitask/output clinit) + GeneralErrorCode.
TASK_ERR_GONGHUI_DONE = 81101
TASK_ERR_GONGHUI_DIFF_MIN = 81102
TASK_ERR_GONGHUI_THICK_MAX = 81103
TASK_ERR_GONGHUI_YB_SHORT = 1003
# Pozhen inbound routes (PoZhenAction): 48001 info, 48002 start,
# 48003 saodang, 48004 refresh, 48005 move, 48006 buy count, 48007 sweep
# end, 48008 quick sweep, 48009 recovery, 48010 stop, 48011 claim goods
# (a void grant: the action discards the service result, so, like the
# gonghui 81008 void reply, success is silent on the wire).
CMD_POZHEN_INFO = 48001
CMD_POZHEN_START = 48002
CMD_POZHEN_SAODANG = 48003
CMD_POZHEN_REFRESH = 48004
CMD_POZHEN_MOVE = 48005
CMD_POZHEN_BUY = 48006
CMD_POZHEN_SDOVER = 48007
CMD_POZHEN_QUICKLY = 48008
CMD_POZHEN_RECOVERY = 48009
CMD_POZHEN_STOP = 48010
CMD_POZHEN_GET_GOODS = 48011
# PozhenErrorCode (pozhen/output/PozhenErrorCode clinit) + GeneralErrorCode
# YB_NOT_ENOUGH (1003) and the shared 50006 gate. FULL_COUNT is 584006
# and YB_LESS 584005 (swapped vs declaration order); the unused codes
# (YB_LESS, JB_LESS, BAG_FULL, NOT_YET, AREADY_PASS, MAX_REFRESH_COUNT,
# JIASU_SAODANG_COUNT_LESS, BROADCAST) have no call site in these paths.
POZHEN_ERR_LEVEL_LESS = 584000
POZHEN_ERR_DIANSHU_LESS = 584001
POZHEN_ERR_YUEJI = 584002
POZHEN_ERR_NOT_EXIST = 584003
POZHEN_ERR_FULL_BUY = 584004
POZHEN_ERR_FULL_COUNT = 584006
POZHEN_ERR_NO_SAODANG = 584007
POZHEN_ERR_SAODANGING = 584008
POZHEN_ERR_CANNT_SD = 584011
POZHEN_ERR_TOP = 584012
POZHEN_ERR_JIASU_YB_LESS = 584013
POZHEN_ERR_NO_REFRESH = 584020
POZHEN_ERR_TIME_LESS = 584015
POZHEN_ERR_YB_SHORT = 1003
POZHEN_ERR_LEVEL_GATE = 50006
# Online-gift inbound routes (HuodongAction via OnlineGiftServiceImpl):
# 94000 getTimeHuodongInfo, 94001 getTimeHuodongReward (null reply stays
# silent, like the void-reply convention).
CMD_HUODONG_ONLINE_INFO = 94000
CMD_HUODONG_ONLINE_REWARD = 94001
# RoleHuodongErrorCode (huodong/output clinit: values equal names).
HUODONG_ERR_NO_GIFT = 792010
HUODONG_ERR_NOT_YET = 792011
# HuodongAction first-recharge routes (EasyMapping + HuodongServiceImpl
# bytecode): 70000 getRechargeInfo, 70001 lingquRechargeReward (the
# action only sends 70001 when the service result is non-null; the
# 70000 result goes out verbatim, including null).
CMD_HUODONG_FIRST_INFO = 70000
CMD_HUODONG_FIRST_REWARD = 70001
# RoleHuodongErrorCode for the first-recharge claim (clinit values).
HUODONG_ERR_FIRST_UNCHARGED = 792001
HUODONG_ERR_FIRST_CLAIMED = 792002
HUODONG_ERR_FIRST_NO_CONFIG = 792005
# GongHuiTaskConstants (jar clinit) + condition export impl costs.
GONGHUI_MIN_LEVEL = 30
GONGHUI_MAX_LOOP = 20
GONGHUI_DIFFICULTY_MAX = 10
GONGHUI_THICK_MAX = 10
GONGHUI_COST_ONEKEY = 50
GONGHUI_COST_ONEKEY_BEST = 100
GONGHUI_COST_JIANGDI = 50000
GONGHUI_COST_TISHENG = 50000
GONGHUI_COST_DIRECT = 10
# TaskErrorCode (task/output/TaskErrorCode clinit) + GeneralErrorCode.
TASK_ERR_NOT_COMPLETE = 480000
TASK_ERR_NOT_NOW_MAIN = 480005
TASK_ERR_NO_RECEVIE_LEVEL = 480002
TASK_ERR_GOODS_NOT_ENOUGH = 1005
BAG_ERR_EXCEED_MAX = 430207
BAG_ERR_TONGQIAN = 430208
BAG_ERR_LINGSHI_BIND = 430209
BAG_ERR_GOODS_NOT = 430251
# MallServiceImpl/BuyMallOutput codes (MallErrorCode + bag slot code).
MALL_ERR_NO_GOODS = 430201
MALL_ERR_JB_NO_ENOUGHT = 430208
MALL_ERR_BAG_NO_SLOT = 430214
MALL_ERR_YB_NO_ENOUGHT = 430403
MALL_ERR_BYB_NO_ENOUGHT = 430404
MALL_ERR_NO_IN_BUY_LIST = 430402
MALL_ERR_GOODS_NOW_EXPIRE = 430408
MALL_ERR_BANGGONG_NO_ENOUGHT = 430412
MALL_ERR_YOUHUI_EXPIRE = 430416
MALL_ERR_YOUHUI_CAN_NOT_USE = 430417
MALL_ERR_YOUHUI_CAN_NOT_USE_MONEY = 430418
MALL_ERR_ACCOUNT_TYPE_ERROR = 430401
# MoneyType intType: YXB=1, YB=2, BIND_YB=3, BANGGONG=5 (FROZEN_YB=4
# never prices a mall row).
MALL_MONEY_NAMES = {1: 'YXB', 2: 'YB', 3: 'BIND_YB', 5: 'BANGGONG'}
MALL_NO_ENOUGH = {1: MALL_ERR_JB_NO_ENOUGHT, 2: MALL_ERR_YB_NO_ENOUGHT,
                  3: MALL_ERR_BYB_NO_ENOUGHT,
                  5: MALL_ERR_BANGGONG_NO_ENOUGHT}
# RoleAccount/UserAccount columns per MoneyType (AccountServiceImpl decr
# mapping: YXB -> tongqian, BIND_YB -> bindLingshi, YB -> lingshi).
BAG_MONEY_COLUMNS = {'YXB': 'tongqian', 'BIND_YB': 'bind_lingshi',
                     'YB': 'lingshi'}
CMD_BAG_SPLIT = 30100
CMD_BAG_DISCARD = 30101
CMD_BAG_DELETE = 30102
CMD_GOODS_PICKUP = 30103
CMD_PROP_USE = 30301
CMD_PROP_DUOXUAN = 30305
CMD_PROP_YOUHUI = 30306
CMD_PROP_TESHU = 30307
PROP_ERROR_100009 = 100009
CMD_BAG_SPLIT_COUNT = 30104
CMD_BAG_SPLIT_NEW = 30105
CMD_STUDY_SKILL = 42004
CMD_SKILL_INFO = 42000
CMD_SKILL_UPGRADE = 42003
CMD_SKILLBOOK_INFO = 99000
CMD_SKILLBOOK_MOVE = 99001
CMD_SKILLBOOK_TUNSHI = 99002
# SkillErrorCode (jar clinit) and GeneralErrorCode values used by upgrade.
SKILL_ERROR_MAX_LEVEL = 420010
SKILL_ERROR_SHENGJI = 420012
# Upgrade-specific SkillErrorCode cells (distinct from the prop-use
# SKILL_ERROR_* above, which carry the study/report numbers).
SKILL_UPGRADE_NOT = 420005
SKILL_UPGRADE_LEVEL = 420006
GENERAL_ZHENQI = 1001
# SkillbookErrorCode (jar clinit).
SKILLBOOK_ERR = 99000
SKILLBOOK_ERR_ZHUANG_BEI = 99001
SKILLBOOK_ERR_MAX_LEVEL = 99002
SKILLBOOK_ERR_TYPE = 99003
SKILLBOOK_ERR_UNOPEN = 99004
SKILLBOOK_ERR_ZUOQI = 99005
SKILLBOOK_ERR_QIBING = 99006
SKILLBOOK_ERR_ONLY = 99007
SKILLBOOK_ERR_CHIBANG = 99011
SKILLBOOK_ERR_SAME = 99013
# Skillbook slot ranges (SkillbookServiceImpl.moveSkillBook bytecode):
# worn books live at 10001..10056, bag books at 1..150.
SKILLBOOK_EQUIP_LO = 10001
SKILLBOOK_EQUIP_HI = 10056
SKILLBOOK_BAG_LO = 1
SKILLBOOK_BAG_HI = 150
SKILLBOOK_ZUOQI = (10001, 10006)
SKILLBOOK_QIZHAN = (10031, 10036)
SKILLBOOK_GUANGYI = (10051, 10056)
# Player stalls (BoothAction/BoothServiceImpl bytecode): 19 inbound commands.
# Wire order for goods prices is always [sellYb, sellJb]; money-market rows
# live at slots 11 (YB offered) and 12 (YXB offered), goods at 0..10.
CMD_BOOTH_TRADE_LOG = 35013
CMD_BOOTH_ONLINE = 35100
CMD_BOOTH_IN = 35101
CMD_BOOTH_OUT = 35102
CMD_BOOTH_CHANGE_PRICE = 35103
CMD_BOOTH_CHANGE_INDEX = 35104
CMD_BOOTH_SEACH = 35105
CMD_BOOTH_INFO = 35106
CMD_BOOTH_BUY = 35107
CMD_BOOTH_SELL_NOTIFY = 35108
CMD_BOOTH_LOG = 35109
CMD_BOOTH_NAME = 35110
CMD_BOOTH_YB_SELL = 35111
CMD_BOOTH_JB_SELL = 35112
CMD_BOOTH_BUY_YB = 35113
CMD_BOOTH_BUY_JB = 35114
CMD_BOOTH_MONEY = 35115
CMD_BOOTH_MONEY_CLAIM = 35116
CMD_BOOTH_DETAILS = 35120
# Friend lists (FriendAction/FriendServiceImpl bytecode): 11 inbound
# commands, 6 push-only notifies. One-sided directed rows: adding is
# immediate (no request/accept), and only the adder's side is stored.
CMD_FRIEND_INFO = 51000
CMD_FRIEND_ADD = 51001
CMD_FRIEND_DEL = 51002
CMD_FOE_ADD = 51003
CMD_FOE_DEL = 51004
CMD_BLACKLIST_ADD = 51005
CMD_BLACKLIST_DEL = 51006
CMD_CONTACTS_ADD = 51007
CMD_CONTACTS_DEL = 51008
CMD_FRIEND_ONLINE = 51010
CMD_FRIEND_XINQING = 51011
CMD_FRIEND_COUNT = 51012
CMD_FOE_COUNT = 51013
CMD_FRIEND_ROLE_INFO = 51014
CMD_FRIEND_FIGHT = 51015
CMD_FRIEND_BEEN_ADD = 51016
CMD_FOE_BEEN_ADD = 51017
# FriendErrorCode ints (jar constants).
FRIEND_ERR_ROLE_NOT_EXISTS = 450001
FRIEND_ERR_NOT_ADD = 450020
FRIEND_ERR_COUNT_LIMIT = 450021
FRIEND_ERR_EXISTS = 450022
FRIEND_ERR_EXISTS_BLACKLIST = 450023
FRIEND_ERR_ONLINE = 450024
FRIEND_ERR_OFFLINE = 450025
FRIEND_ERR_FIGHT_FAIL = 450026
FRIEND_ERR_FIGHT_WIN = 450027
FRIEND_ERR_XINQING_MAX = 450030
FRIEND_ERR_XINQING_ILLEGAL = 450031
FRIEND_ERR_FOE_NOT_ADD = 450040
FRIEND_ERR_FOE_COUNT_LIMIT = 450041
FRIEND_ERR_FOE_EXISTS = 450042
FRIEND_ERR_FOE_FIGHT_FAIL = 450048
FRIEND_ERR_FOE_FIGHT_WIN = 450049
FRIEND_ERR_BLACKLIST_NOT_ADD = 450060
FRIEND_ERR_BLACKLIST_EXISTS = 450062
FRIEND_ERR_BLACKLIST_EXISTS_FRIEND = 450063
# FriendConstants (jar clinit).
FRIEND_MAX_COUNT = 30
FRIEND_ONLINE_STATE = 1
FRIEND_OFFLINE_STATE = 0
FRIEND_TYPE_FRIEND = 0
FRIEND_TYPE_BLACKLIST = 1
FRIEND_TYPE_FOE = 2
FRIEND_TYPE_CONTACTS = 3
FRIEND_FOE_COUNT_MAX = 999
FRIEND_FOE_COUNT_MIN = -999
FRIEND_XINQING_MAX = 48
# BoothErrorCodeOutput ints (jar clinit) and GeneralErrorCode cells.
BOOTH_ERR_GOODS_EXPIRE = 1007
BOOTH_ERR_YB_NOT_ENOUGH = 1002
BOOTH_ERR_JB_NOT_ENOUGH = 1003
BOOTH_ERR_BAG_SLOT = 1006
BOOTH_ERR_NAME_NO_ALLOW = 424044
BOOTH_ERR_NO_BIND_GOODS = 424046
BOOTH_ERR_GOODS_COUNT_MAX = 424068
BOOTH_ERR_ROLE_BOOTH_COUNT_MAX = 424047
BOOTH_ERR_NO_INPUT_MONEY = 424048
BOOTH_ERR_GOODS_NO_IN_BOOTH = 424049
BOOTH_ERR_SELL_ROLE_OFFLINE = 424050
BOOTH_ERR_SELL_YB_MAX = 424052
BOOTH_ERR_SELL_INDEX_SAME = 424053
BOOTH_ERR_NO_BUY_SELF_GOODS = 424054
BOOTH_ERR_CHANGE_REFRESH = 424067
BOOTH_ERR_YB_SELL_NO_EXIST = 424062
BOOTH_ERR_JB_SELL_NO_EXIST = 424061
BOOTH_ERR_JINGYANYU_NO_SELL = 424070
# Money-market slot numbers (BoothSellMoneyFilter / slot-11-12 call sites).
BOOTH_SLOT_YB = 11
BOOTH_SLOT_JB = 12
# Goods listings visible to shoppers sit below slot 8 (BoothSellGoodsFilter).
BOOTH_GOODS_VISIBLE_MAX = 8
# Listing cap per seller (checkPutBooth: 8 goods rows max).
BOOTH_GOODS_MAX = 8
# YB price floor on new listings (checkPutBooth: sellYb < 2 rejects).
BOOTH_MIN_SELL_YB = 2
# InBooth action price ceiling per currency (900000000).
BOOTH_MAX_PRICE = 900000000
# Trade-exp throttle (isUpdateAddBoothExp): one award per 120000 ms per booth.
BOOTH_TRADE_EXP_MS = 120000
CMD_ATTR_CHANGE = 85010
CMD_LIHE_PREVIEW = 30304
BAG_ERR_BIND_NO_DISCARD = 430218
# PropStageAction.consumeGoods reply id; the 30104/30105 ids below are
# server pushes emitted by splitGoods (no inbound route exists for them).
PROP_SKILL_USE = frozenset([1, 2, 3, 5, 11, 14, 33, 35, 36, 37])
PROP_CONSUME_CATEGORIES = frozenset(
    ['14', '40', '11', '13', '16', '15', '17', '80'])
PROP_HP_CD_MS = 1500
PROP_ERROR_100002 = 100002
PROP_ERROR_100003 = 100003
PROP_ERROR_100004 = 100004
PROP_ERROR_100008 = 100008
PROP_ERROR_ZUOQI = 100014
DAN_ERROR_CAPPED = 851003
GENERAL_LEVEL = 1000
GENERAL_YB = 1002
GENERAL_JB = 1003
GENERAL_BINDYB = 1004
GENERAL_GOODS = 1005
GENERAL_NOSLOT = 1006
GENERAL_INEXISTENCE = 1008
GENERAL_NOT_VIP = 1010
GENERAL_ROLE_EXP = 1014
SKILL_ERROR_STUDY = 420007
SKILL_ERROR_LEVEL = 420008
SKILL_ERROR_JOB = 420009
# GoodsCategoryUtil.GOODS_SORT_TYPE_SIZE: pickup groups slots 0..4.
GOODS_SORT_TYPE_SIZE = 4
# Tidy-up zones: slot range, renumber base, reply command. clearUp and
# clearUpStorage renumber from 1/301; clearUpXunBaoBag from 1001 and,
# unlike the other two, sends no inner 30000 refresh (no stage bus here,
# so none of them do).
BAG_CLEARUP_ZONES = {'bag': (1, 150, 1, '30001'),
                     'storage': (301, 500, 301, '30003'),
                     'xunbao': (1001, 2000, 1001, '30006')}
BAG_ERR_NOT_FOUND_GOODS = 430201
BAG_ERR_SPLIT_COUNT = 430205
BAG_ERR_SPLIT_SLOT_HAVE_GOODS = 430204

# Bag slot zones from BagUtil bytecode: bag 1..150, storage 301..500,
# mount gear -104..-101, treasure-hunt bag 1001..2000.
BAG_SLOT_ZONES = {'bag': (1, 150), 'storage': (301, 500),
                  'zuoqi': (-104, -101), 'xunbao': (1001, 2000)}
# BagErroeCodes from the jar's static initializer.
BAG_ERR_OPERATE_INVALID = 430206
BAG_ERR_NOT_ACTIVATED_SLOT = 430202


def _bag_zone(slot):
    """Zone name for a bag slot number, or None outside every zone."""
    try:
        slot = int(slot)
    except (TypeError, ValueError):
        return None
    for name, (lo, hi) in BAG_SLOT_ZONES.items():
        if lo <= slot <= hi:
            return name
    return None


def _bag_slots_can_move(from_slot, to_slot):
    """BagUtil.checkSlotCanMove: allowed zone pairs for a move."""
    zfrom, zto = _bag_zone(from_slot), _bag_zone(to_slot)
    if zfrom is None or zto is None:
        return False
    return ((zfrom == zto and zfrom in ('bag', 'storage', 'xunbao'))
            or {zfrom, zto} == {'bag', 'storage'}
            or {zfrom, zto} == {'bag', 'zuoqi'}
            or (zfrom == 'xunbao' and zto == 'bag'))
# Meditation (RoleBehaviourAction -> RoleBehaviourServiceImpl). 44004 is the
# 15 s stage timer push, not a client command; errors are StageErrorCode.
CMD_HORN_CHAT = 11005
# Chat (RoleBehaviourAction.normalChat / StageInfoAction.arroundBroadcast, point2point).
CMD_AREA_CHAT = 10050
CMD_WHISPER = 10051
CMD_NORMAL_CHAT = 11000
# 57000 gift-code redeem (GiftAction.useCode): stubbed until the public-code data source exists.
CMD_GIFT_CODE_USE = 57000
CMD_DAZUO_SINGLE = 44001
CMD_DAZUO_BOTH = 44002
CMD_DAZUO_EXIT = 44003
CMD_DAZUO_TIMING = 44004
DAZUO_ERR_FIGHT = 440001
DAZUO_ERR_ROLE = 440002
DAZUO_TICK_SECONDS = 15
CMD_TILE = 40000
CMD_JUMP = 40001
CMD_TELEPORT = 40100
CMD_FACE = 40201
CMD_INNER_FLY = 40101
CMD_TOWN_REVIVE = 43001
CMD_SKILL_MOVE = 42001
CMD_MOVE = 42001
CMD_SKILL_FIRE = 42002
CMD_BUFF = 42100
CMD_FIGHT_STATE = 40501
CMD_SKILL_CD = 42005
CMD_BUFF_VALUE = 42102
CMD_DEAD = 43000
CMD_AOI_LEAVE = 24002
# Observed on the wire but with no captured reply or confirmed semantics yet;
# logged so a live run shows the real post-entry command sequence.
CMD_UNKNOWN_OBSERVED = frozenset({53021})


def frame(payload: bytes) -> bytes:
    return struct.pack('>I', len(payload)) + payload


# Approximation of NameFieldCheck.REGX_CHAR (CJK-only name rule): names must
# be CJK characters and must not start with s/S (checkInputName2 bytecode).
# The sensitive-word list (CheckNameUtil/MinganciUtil) has no portable
# equivalent, so it is an open gap, not a silent pass.
_ROLE_NAME_RE = re.compile(
    '[\u3400-\u4db5\u4e00-\u9fa5\u9fa6-\u9fbb\uf900-\ufa2d'
    '\U00020000-\U0002a6d6\uff00-\uffef\u2e80-\u2eff\u3000-\u303f'
    '\u31c0-\u31ef\u3100-\u312d]+')

# Java caps roles per account+server at 4 (UserRoleServiceImpl.createRole).
MAX_ROLES_PER_ACCOUNT = 4


def check_role_name(name):
    """Port of NameFieldCheck.checkInputName2 minus the word-filter list."""
    if not name or not isinstance(name, str):
        return False
    if name[0] in ('s', 'S'):
        return False
    return _ROLE_NAME_RE.fullmatch(name) is not None


_XINQING_BAD_RE = re.compile(r'[`~@#$%^*+().,?\'":;\[\]{}|<>/\\\s]')


def check_xinqing(text):
    """Port of NameFieldCheck.checkInputName minus the word-filter list.

    checkIntervalChar is the same CJK class as role names (without the
    s/S rule checkInputName2 adds); checkDeleteChar rejects ASCII
    punctuation and whitespace. Empty mood text is allowed by Java.
    """
    if not isinstance(text, str):
        return False
    if text == '':
        return True
    if _XINQING_BAD_RE.search(text):
        return False
    return _ROLE_NAME_RE.fullmatch(text) is not None


def _wire_id(r):
    """Role id on the wire: the migrated legacy id the client knows (capture
    uses 'fu0UR1-0-1-1'), falling back to the local row id for fresh roles."""
    return str(r.get('legacy_id') or r['id'])


def decode_zuoqi_info(text):
    """role_stage.zuoqi_info (fastjson JSON) -> dict, or None when absent.

    Keys are RoleStageUtil.decodeZuoQiInfo's: id (mount rank), hp, deadTime,
    useTime, rideOrNo. Empty text returns immediately in Java, leaving the
    mount business data at its defaults, which is what None means here.
    """
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        log.warning('zuoqi_info is not JSON: %r', text[:80])
        return None
    return data if isinstance(data, dict) else None


def _is_int(value):
    """True for a plain AMF integer (bools excluded)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _find_role(roles, role_id):
    """Resolve the id the client sends: local id or migrated legacy id."""
    return next((r for r in roles if str(r.get('id')) == role_id
                 or str(r.get('legacy_id') or '') == role_id), None)


def _fujia_wire(fujia):
    """HashMap on the wire: an empty map must stay an object, not an array."""
    return None if fujia is None else Obj(fujia)


def _qiandao_ints(text):
    """QiandaoOutput.toInteger: comma-joined ints; null or empty gives []."""
    if text is None or text == '':
        return []
    return [int(part) for part in text.split(',')]


def _qiandao_strings(text):
    """QiandaoOutput.toString: comma-split strings; null or empty gives []."""
    if text is None or text == '':
        return []
    return text.split(',')


# Per-connection frame budget: sustained frames/s and burst size. A client that
# exceeds it is disconnected (the handler closes on ValueError).
FRAME_RATE_PER_S = 50
FRAME_BURST = 300


class Session:
    def __init__(self, conn_id, check_sign, get_roles, server_start_ms,
                 gm_open=False, tz_raw_offset=-18000000,
                 tz_id='America/New_York',
                 get_role_settings=None, save_role_settings=None,
                 create_role=None, save_role_state=None,
                 find_roles_by_name=None,
                 get_role_equip=None, save_role_equip=None,
                 get_role_attr_buffs=None,
                 save_role_attr_buffs=None,
                 get_role_vip=None, get_role_xianjiechenhao=None,
                 get_role_meiren=None, save_role_meiren=None,
                 get_role_baoshi=None, save_role_baoshi=None,
                 get_role_zuoqi=None, save_role_zuoqi=None,
                 get_role_pets=None, save_role_pet=None,
                 get_role_pet_zhenfa=None, save_role_pet_zhenfa=None,
                 get_zuoqi_fanhuan=None, save_zuoqi_fanhuan=None,
                 get_role_skills=None,                  get_role_shenjiang=None, save_role_shenjiang=None, get_role_chengjiu=None, save_role_chengjiu=None, save_role_stage=None,
                 get_role_bag_slots=None, get_role_bag_state=None,
                 get_role_bag_slot=None,                 get_role_bag_slot_by_bag_id=None, save_role_skill=None,
                 get_role_skillbook_slots=None,
                 get_role_skillbook_slot=None,
                 insert_role_skillbook_slot=None,
                 update_role_skillbook_slot=None,
                 delete_role_skillbook_slot=None,
                 get_role_buyback_all=None,
                 get_role_buyback=None,
                 get_role_bag_dummy=None,
                 insert_role_buyback=None,
                 delete_role_buyback=None,
                 get_role_prop=None,
                 save_role_prop=None,
                 get_role_loginlibao=None, save_role_loginlibao=None,
                 get_role_loginlingjiang=None,
                 save_role_loginlingjiang=None,
                 get_role_touxian=None, save_role_touxian=None,
                 get_role_guangyi=None, save_role_guangyi=None,
                 get_role_baixian=None, save_role_baixian=None,
                 get_role_kapai=None, save_role_kapai=None,
                 get_role_zhuihui=None, save_role_zhuihui=None,
                 get_role_dafuwong=None, save_role_dafuwong=None,
                 get_role_xianshibuy=None, save_role_xianshibuy=None,
                 get_xianshi_buy=None, save_xianshi_buy=None,
                 get_role_lvlibao=None, save_role_lvlibao=None,
                 list_role_email=None, get_role_email=None,
                 save_role_email=None, update_role_email=None,
                 delete_role_email=None,
                 get_role_qiandao=None, save_role_qiandao=None,
                 get_role_jiangli_list=None, save_role_jiangli_list=None,
                 get_role_dengluqi=None, save_role_dengluqi=None,
                 get_role_online_reward=None, save_role_online_reward=None,
                 get_role_husong=None, save_role_husong=None,
                 get_role_juqing=None, save_role_juqing=None,
                 get_role_zuwufuben=None, save_role_zuwufuben=None,
                 get_role_zuwu=None, list_role_zuwu=None,
                 save_role_zuwu=None, add_role_bag_dummy=None,
                 get_role_jianding=None, save_role_jianding=None,
                 save_role_vip=None, get_role_vip_kaifu=None,
                 save_role_vip_kaifu=None,
                 get_role_vip_huodong_all=None,
                 get_role_vip_huodong=None,
                 save_role_vip_huodong=None,
                 get_role_qq_list=None, save_role_qq_list=None,
                 get_vip_qq=None, save_vip_qq=None,
                 update_role_bag_slot=None, delete_role_bag_slot=None,
                 move_role_bag_slot=None, insert_role_bag_slot=None,
                 rewrite_role_bag_slots=None, save_role_bag_state=None,
                 get_booth=None, save_booth=None,
                 get_booth_sell=None, get_booth_sell_by_slot=None,
                 list_booth_sells=None, save_booth_sell=None,
                 delete_booth_sell=None, list_public_booths=None,
                 list_booth_trade_logs=None, save_booth_trade_log=None,
                 get_role_brief=None, booth_list_goods_tx=None,
                 booth_delist_goods_tx=None, booth_buy_goods_tx=None,
                 booth_money_position_tx=None, booth_money_buy_tx=None,
                 booth_claim_tx=None,
                 list_friend_links=None, has_friend_link=None,
                 count_friend_links=None, follower_ids=None,
                 friend_add_tx=None, friend_del_tx=None,
                 friend_touch_foe_tx=None, get_friend_info=None,
                 save_friend_info=None, friend_add_count_tx=None,
                 get_task_main=None, save_task_main=None,
                 get_task_taofa=None, get_task_taofas=None,
                 insert_task_taofa=None, update_task_taofa=None,
                 delete_task_taofa=None, get_task_taofa_state=None,
                 save_task_taofa_state=None, get_task_richang=None,
                 save_task_richang=None, delete_task_richang=None,
                 get_task_gonghui=None, save_task_gonghui=None,
                 delete_task_gonghui=None, get_role_huodong=None,
                 save_role_huodong=None, get_role_pozhen=None,
                 save_role_pozhen=None, get_guild_id=None,
                 save_guild_member=None, add_guild_gongxian=None,
                  config=None, stage_registry=None):
        self.conn_id = conn_id
        self.config = config
        self.get_role_equip = get_role_equip or (lambda role_id: [])
        self.save_role_equip = save_role_equip or (lambda *a: False)
        self.get_role_attr_buffs = get_role_attr_buffs or (lambda role_id: [])
        self.save_role_attr_buffs = save_role_attr_buffs or \
            (lambda *a, **k: False)
        self.get_role_vip = get_role_vip or (lambda role_id: None)
        self.get_role_xianjiechenhao = get_role_xianjiechenhao or (lambda role_id: None)
        self.get_role_jianding = get_role_jianding or (lambda role_id: None)
        self.save_role_jianding = save_role_jianding or (lambda *a, **k: False)
        self.save_role_vip = save_role_vip or (lambda *a, **k: False)
        self.get_role_vip_kaifu = get_role_vip_kaifu or \
            (lambda role_id: None)
        self.save_role_vip_kaifu = save_role_vip_kaifu or \
            (lambda *a, **k: False)
        self.get_role_vip_huodong_all = get_role_vip_huodong_all or \
            (lambda role_id: [])
        self.get_role_vip_huodong = get_role_vip_huodong or \
            (lambda role_id, vip: None)
        self.save_role_vip_huodong = save_role_vip_huodong or \
            (lambda *a, **k: False)
        self.get_role_qq_list = get_role_qq_list or (lambda role_id: None)
        self.save_role_qq_list = save_role_qq_list or \
            (lambda *a, **k: False)
        self.get_vip_qq = get_vip_qq or (lambda: None)
        self.save_vip_qq = save_vip_qq or (lambda *a, **k: False)
        self.get_role_meiren = get_role_meiren or (lambda role_id: [])
        self.save_role_meiren = save_role_meiren or (lambda *a: False)
        self.get_role_baoshi = get_role_baoshi or (lambda role_id: [])
        self.save_role_baoshi = save_role_baoshi or (lambda *a: False)
        self.get_zuoqi_fanhuan = get_zuoqi_fanhuan or (lambda: [])
        self.save_zuoqi_fanhuan = save_zuoqi_fanhuan or (lambda *a: False)
        self.save_role_skill = save_role_skill or (lambda *a, **k: False)
        self.get_role_zuoqi = get_role_zuoqi or (lambda role_id: None)
        self.save_role_zuoqi = save_role_zuoqi or (lambda *a, **k: False)
        self.get_role_pets = get_role_pets or (lambda role_id: [])
        self.save_role_pet = save_role_pet or (lambda *a, **k: False)
        self.get_role_pet_zhenfa = \
            get_role_pet_zhenfa or (lambda role_id: None)
        self.save_role_pet_zhenfa = \
            save_role_pet_zhenfa or (lambda *a, **k: False)
        self.get_role_skills = get_role_skills or (lambda role_id: [])
        self.get_role_shenjiang = get_role_shenjiang or (lambda role_id: [])
        self.save_role_shenjiang = save_role_shenjiang or (lambda *a, **k: False)
        self.get_role_chengjiu = get_role_chengjiu or (lambda role_id: [])
        self.save_role_chengjiu = save_role_chengjiu or (lambda *a, **k: False)
        self.save_role_stage = save_role_stage or (lambda *args, **kwargs: False)
        self.get_role_bag_slots = get_role_bag_slots or (lambda role_id: [])
        self.get_role_bag_state = get_role_bag_state or (lambda role_id: None)
        self.get_role_bag_slot = get_role_bag_slot or (lambda r, s: None)
        self.get_role_bag_slot_by_bag_id = (get_role_bag_slot_by_bag_id
                                            or (lambda r, b: None))
        self.get_role_skillbook_slots = (get_role_skillbook_slots
                                         or (lambda r: []))
        self.get_role_skillbook_slot = (get_role_skillbook_slot
                                        or (lambda r, s: None))
        self.insert_role_skillbook_slot = (insert_role_skillbook_slot
                                           or (lambda r, row: None))
        self.update_role_skillbook_slot = (update_role_skillbook_slot
                                           or (lambda *a, **k: False))
        self.delete_role_skillbook_slot = (delete_role_skillbook_slot
                                           or (lambda *a: False))
        self.get_role_buyback_all = (get_role_buyback_all
                                     or (lambda role_id: []))
        self.get_role_buyback = (get_role_buyback
                                 or (lambda r, b: None))
        self.get_role_bag_dummy = (get_role_bag_dummy
                                   or (lambda role_id: []))
        self.insert_role_buyback = (insert_role_buyback
                                    or (lambda r, row: False))
        self.delete_role_buyback = (delete_role_buyback
                                    or (lambda r, b: False))
        self.get_role_prop = get_role_prop or (lambda r, g: None)
        self.save_role_prop = save_role_prop or (lambda *a, **k: False)
        self.get_role_loginlibao = get_role_loginlibao or (lambda r: None)
        self.save_role_loginlibao = save_role_loginlibao or \
            (lambda *a, **k: False)
        self.get_role_loginlingjiang = get_role_loginlingjiang or \
            (lambda r: None)
        self.save_role_loginlingjiang = save_role_loginlingjiang or \
            (lambda *a, **k: False)
        self.get_role_touxian = get_role_touxian or (lambda r: None)
        self.save_role_touxian = save_role_touxian or \
            (lambda *a, **k: False)
        self.get_role_guangyi = get_role_guangyi or (lambda r: None)
        self.save_role_guangyi = save_role_guangyi or \
            (lambda *a, **k: False)
        self.get_role_baixian = get_role_baixian or (lambda r: None)
        self.save_role_baixian = save_role_baixian or \
            (lambda *a, **k: False)
        self.get_role_kapai = get_role_kapai or (lambda r: None)
        self.save_role_kapai = save_role_kapai or \
            (lambda *a, **k: False)
        self.get_role_zhuihui = get_role_zhuihui or (lambda r: None)
        self.get_role_dafuwong = get_role_dafuwong or (lambda r: None)
        self.save_role_dafuwong = save_role_dafuwong or \
            (lambda *a, **k: False)
        self.get_role_xianshibuy = get_role_xianshibuy or (lambda r: None)
        self.save_role_xianshibuy = save_role_xianshibuy or \
            (lambda *a, **k: False)
        self.get_xianshi_buy = get_xianshi_buy or (lambda: None)
        self.save_xianshi_buy = save_xianshi_buy or (lambda *a: False)
        self.save_role_zhuihui = save_role_zhuihui or \
            (lambda *a, **k: False)
        self.get_role_lvlibao = get_role_lvlibao or (lambda r: None)
        self.save_role_lvlibao = save_role_lvlibao or \
            (lambda *a, **k: False)
        self.list_role_email = list_role_email or (lambda r: [])
        self.get_role_email = get_role_email or (lambda r, m: None)
        self.save_role_email = save_role_email or (lambda *a, **k: None)
        self.update_role_email = update_role_email or \
            (lambda *a, **k: False)
        self.delete_role_email = delete_role_email or (lambda *a: False)
        self.get_role_qiandao = get_role_qiandao or (lambda r: None)
        self.save_role_qiandao = save_role_qiandao or (lambda *a, **k: False)
        self.get_role_jiangli_list = \
            get_role_jiangli_list or (lambda r: None)
        self.save_role_jiangli_list = \
            save_role_jiangli_list or (lambda *a, **k: False)
        self.get_role_dengluqi = get_role_dengluqi or (lambda r: None)
        self.save_role_dengluqi = save_role_dengluqi or \
            (lambda *a, **k: False)
        self.get_role_online_reward = get_role_online_reward or \
            (lambda r: None)
        self.save_role_online_reward = save_role_online_reward or \
            (lambda *a, **k: False)
        self.get_role_husong = get_role_husong or (lambda r: None)
        self.save_role_husong = save_role_husong or \
            (lambda *a, **k: False)
        self.get_role_juqing = get_role_juqing or (lambda r: None)
        self.save_role_juqing = save_role_juqing or \
            (lambda *a, **k: False)
        self.get_role_zuwufuben = get_role_zuwufuben or (lambda r: None)
        self.save_role_zuwufuben = save_role_zuwufuben or \
            (lambda *a, **k: False)
        self.get_role_zuwu = get_role_zuwu or (lambda r, z: None)
        self.list_role_zuwu = list_role_zuwu or (lambda r: [])
        self.save_role_zuwu = save_role_zuwu or \
            (lambda *a, **k: False)
        self.add_role_bag_dummy = add_role_bag_dummy or \
            (lambda *a: False)
        self.update_role_bag_slot = update_role_bag_slot or (lambda *a, **k: False)
        self.delete_role_bag_slot = delete_role_bag_slot or (lambda *a: False)
        self.move_role_bag_slot = move_role_bag_slot or (lambda *a: False)
        self.insert_role_bag_slot = insert_role_bag_slot or (lambda *a: None)
        self.rewrite_role_bag_slots = rewrite_role_bag_slots or (lambda *a: False)
        self.save_role_bag_state = save_role_bag_state or (lambda *a, **k: False)
        self.get_booth = get_booth or (lambda r: None)
        self.save_booth = save_booth or (lambda *a, **k: False)
        self.get_booth_sell = get_booth_sell or (lambda s, r: None)
        self.get_booth_sell_by_slot = (get_booth_sell_by_slot
                                       or (lambda r, s: None))
        self.list_booth_sells = list_booth_sells or (lambda r: [])
        self.save_booth_sell = save_booth_sell or (lambda sell: False)
        self.delete_booth_sell = delete_booth_sell or (lambda s, r: False)
        self.list_public_booths = list_public_booths or (lambda: [])
        self.list_booth_trade_logs = (list_booth_trade_logs
                                       or (lambda r: []))
        self.save_booth_trade_log = (save_booth_trade_log
                                      or (lambda *a: False))
        self.get_role_brief = get_role_brief or (lambda r: None)
        self.list_friend_links = list_friend_links or (lambda k, r: [])
        self.has_friend_link = has_friend_link or (lambda k, o, t: False)
        self.count_friend_links = (count_friend_links
                                   or (lambda k, r: 0))
        self.follower_ids = follower_ids or (lambda k, t: [])
        self.friend_add_tx = friend_add_tx or (lambda *a: (False, None))
        self.friend_del_tx = friend_del_tx or (lambda *a: False)
        self.friend_touch_foe_tx = (friend_touch_foe_tx
                                    or (lambda *a: None))
        self.get_friend_info = get_friend_info or (lambda r: None)
        self.save_friend_info = (save_friend_info
                                 or (lambda *a, **k: False))
        self.friend_add_count_tx = (friend_add_count_tx
                                    or (lambda r: 0))
        self.booth_list_goods_tx = (booth_list_goods_tx
                                     or (lambda *a: 'gone'))
        self.booth_delist_goods_tx = (booth_delist_goods_tx
                                       or (lambda *a: 'gone'))
        self.booth_buy_goods_tx = (booth_buy_goods_tx
                                    or (lambda *a: 'gone'))
        self.booth_money_position_tx = (booth_money_position_tx
                                         or (lambda *a: 'gone'))
        self.booth_money_buy_tx = (booth_money_buy_tx
                                    or (lambda *a: 'gone'))
        self.booth_claim_tx = booth_claim_tx or (lambda *a: (0, 0, False))
        self.get_task_main = get_task_main or (lambda r: None)
        self.save_task_main = save_task_main or (lambda *a, **k: False)
        self.get_task_taofa = get_task_taofa or (lambda r, u: None)
        self.get_task_taofas = get_task_taofas or (lambda r: [])
        self.insert_task_taofa = insert_task_taofa or (lambda *a: False)
        self.update_task_taofa = update_task_taofa or (lambda *a, **k: False)
        self.delete_task_taofa = delete_task_taofa or (lambda *a: False)
        self.get_task_taofa_state = get_task_taofa_state or \
            (lambda r: None)
        self.save_task_taofa_state = save_task_taofa_state or \
            (lambda *a, **k: False)
        self.get_task_richang = get_task_richang or (lambda r: None)
        self.save_task_richang = save_task_richang or \
            (lambda *a, **k: False)
        self.delete_task_richang = delete_task_richang or (lambda r: False)
        self.get_task_gonghui = get_task_gonghui or (lambda r: None)
        self.save_task_gonghui = save_task_gonghui or \
            (lambda *a, **k: False)
        self.get_role_huodong = get_role_huodong or (lambda r: None)
        self.save_role_huodong = save_role_huodong or \
            (lambda *a, **k: False)
        self.get_role_pozhen = get_role_pozhen or (lambda r: None)
        self.save_role_pozhen = save_role_pozhen or \
            (lambda *a, **k: False)
        self.delete_task_gonghui = delete_task_gonghui or (lambda r: False)
        self.get_guild_id = get_guild_id or (lambda r: None)
        self.save_guild_member = save_guild_member or \
            (lambda *a, **k: False)
        self.add_guild_gongxian = add_guild_gongxian or (lambda r, d: None)
        self.buf = bytearray()
        self.frame_bucket = TokenBucket(FRAME_RATE_PER_S, FRAME_BURST)
        self.cipher = None
        self.key = None
        self.authed_user = None
        self.server_id = None
        self.check_sign = check_sign
        self.get_roles = get_roles
        self.get_role_settings = get_role_settings or (lambda role_id, user, server: None)
        self.save_role_settings = save_role_settings or (lambda *a, **k: False)
        self.create_role_cb = create_role or (lambda *args: None)
        self.save_role_state = save_role_state or (lambda *args, **kwargs: False)
        self.find_roles_by_name = find_roles_by_name or (lambda name: [])
        self.server_start_ms = server_start_ms
        self.gm_open = gm_open
        self.tz_raw_offset = tz_raw_offset
        self.tz_id = tz_id
        self._scene_seq = 0
        self._pet_ids = set()
        # Stage-instance tag and object sequence for buff ids. Java builds
        # ids as buff_<stageId>_<n> off JVM-global counters (captured
        # buff_64_101..108 then zuoqi_64_109); ours are session-local and
        # restart per stage entry, which keeps them unique where the client
        # matches them (42100 adds vs 42102/removes) without pretending to
        # reproduce the server-global values.
        self._stage_serial = 0
        self._obj_seq = 0
        # Live stage fighters for the combat loop. Roles are re-read from the
        # store on every swing (HP/exp persist there); monsters and pets live
        # here: monster id -> {template, hp} (seeded from GuaiWuBiao on first
        # sight, exactly Java's stage-element state), pet id -> {max_hp, hp,
        # level, owner, name} (registered by zuoqi_pet_frame). Dead ids stay
        # in _dead until the respawn scheduler (Phase 4) revives them.
        # Monster state is bound to the shared world below (not per session).
        self._world = (stage_registry.monsters if stage_registry is not None
                       else MonsterWorld())
        self._monster_hp = self._world.hp
        self._pet_state = {}
        self._dead = self._world.dead
        # Mount death ledger (ZuoQiBussinessData deadTime/useTime): owner
        # wire id -> [deadMs, useMs]. Death stamps [now, 0] (ZuoQiPet
        # syncDeadZuoQiAttribute); revive zeroes it. A dict miss with a
        # persisted deadTime is a previous session, so the first read
        # applies RoleStageUtil.decodeZuoQiInfo's rule (dead re-anchors to
        # now, use keeps the stored elapsed) exactly once per session.
        self._zuoqi_dead = {}
        # Live buff instances for BuffServiceImpl.getBuff (42100): entries
        # [instance_id, buff_id, lasttime_or_None, t0] stashed by
        # entry_buff_frame, so a query replays the same instance ids with
        # ticked-down remaining instead of minting new ones. Permanent
        # buffs carry None (rendered -1.0); expired ones are forgotten and
        # reported once in the removes slot, like BuffStatistics' flush.
        self._buff_live = []
        # Monster AI state (Phase 4: AiFightServiceImpl + MonsterEventManager).
        # _monster_reg: fighter id -> {template, map, born:[x,y], pos:[x,y]}
        # (snapshot monsters seed on first sight; respawns register here).
        # _hatred: monster id -> attacker fighter id (MonsterHatredManager).
        # _leaving: dead id -> ticks until the 24002 AOI leave (asheslast).
        # _spawning: list of [template_id, map, born, ticks] until the 23002
        # re-enter (creattime). _respawn_next: per-map fresh-id counter.
        self._monster_reg = self._world.reg
        self._hatred = self._world.hatred
        self._leaving = self._world.leaving
        self._spawning = self._world.spawning
        self._respawn_next = self._world.respawn_next
        self._ai_seq = 0
        # Stage timers (StageScheduleManager mirror): the server tick loop
        # drains these via tick(); handle() still runs ai_tick after 42002.
        self.stage_scheduler = scheduler_lib.StageScheduleManager()
        # One state lock serializes the connection thread (feed) and the
        # server tick thread (tick); send_lock only orders sendall.
        self.state_lock = threading.RLock()
        self.send_lock = None
        self.bus = eventbus_lib.EventCenter()
        self.inner_handlers = {}
        self._inner_out = None
        # Prop-use HP cooldowns: role id -> last-ms (HpMpPropType 1500ms).
        self._prop_hpcd = {}
        # Cross-session pushes: the shared registry routes a role to its
        # session, whose outbox joins the next tick (outbox_lock is a leaf).
        self.stage_registry = stage_registry
        self.outbox = []
        self.outbox_lock = threading.Lock()
        # Meditation: role id -> {'daZuo': bool, 'target': role id or None}, and
        # state changes queued by other connections, run under this tick.
        self._dazuo = {}
        # Clan-dungeon attempts: role id -> {'dungeon': id, 'kills': {...}}.
        # Java holds this in the stage copy; the shared-world port keeps
        # it on the session and drops it on quit/expiry/disconnect.
        self._zuwu_attempt = {}
        self._ops = []

    def feed(self, data: bytes):
        """Consume TCP bytes under the state lock, return complete out-frames."""
        with self.state_lock:
            return self._feed_unlocked(data)

    def _feed_unlocked(self, data: bytes):
        """Frame parsing and dispatch; feed() holds the state lock."""
        self.buf += data
        out = []
        # Flash socket-policy handshake is answered raw, in-band (NetListener).
        if self.buf.startswith(POLICY_REQ) and b'\x00' in self.buf:
            end = self.buf.index(b'\x00') + 1
            log.info('conn %d: policy request -> answering in-band', self.conn_id)
            out.append(POLICY_XML)
            del self.buf[:end]
        while len(self.buf) >= 4:
            ln = struct.unpack('>I', self.buf[:4])[0]
            if ln > 48 * 1024 * 1024:
                raise ValueError(f'frame too large: {ln}')
            if len(self.buf) < 4 + ln:
                break  # fragment: wait for more (remain_buf)
            payload = bytes(self.buf[4:4 + ln])
            del self.buf[:4 + ln]
            if not self.frame_bucket.allow():
                raise ValueError(f'conn {self.conn_id}: frame rate limit exceeded')
            try:
                reply = self.handle(payload)
            except Exception:
                log.warning('conn %d: handler failed, continuing',
                            self.conn_id, exc_info=True)
                continue
            if isinstance(reply, tuple):
                out.extend(reply)
            elif reply is not None:
                out.append(reply)
        return out

    def handle(self, payload: bytes):
        if self.cipher is None:
            # First frame triggers the key exchange (initEncrypt) and is
            # consumed, exactly like the original decoder.
            try:
                hello = amf3_decode(payload)
            except Exception as e:
                log.warning('conn %d: bad hello: %s', self.conn_id, e)
                return None
            if hello != 'INITKEY':
                log.warning('conn %d: expected INITKEY, got %r', self.conn_id, hello)
                return None
            self.key = new_key()
            self.cipher = SimpleEncrypt(self.key)
            log.info('conn %d: INITKEY -> key exchange (%s...)',
                     self.conn_id, self.key[:8])
            return frame(self.key.encode())
        try:
            msg = amf3_decode(self.cipher.decode(payload))
        except Exception as e:
            log.warning('conn %d: decode failed: %s', self.conn_id, e)
            return None
        if not isinstance(msg, list) or not msg:
            log.warning('conn %d: not a command array: %r', self.conn_id, msg)
            return None
        cmd = msg[0]
        try:
            cmd_num = int(cmd)
        except (TypeError, ValueError):
            cmd_num = None
        log.info('conn %d: command %r', self.conn_id, cmd)
        if cmd_num == CMD_LOGIN:
            return self.login(msg)
        if cmd_num == CMD_ENTER_WORLD:
            return self.enter_world(msg)
        if cmd_num == CMD_CREATE_ROLE:
            return self.create_role(msg)
        if cmd_num == CMD_GETTIME:
            return frame(amf3_encode(['19001', int(time.time() * 1000)]))
        if cmd_num == CMD_HORN_CHAT:
            return self.horn_chat(msg)
        if cmd_num == CMD_NORMAL_CHAT:
            return self.normal_chat(msg)
        if cmd_num == CMD_AREA_CHAT:
            return self.area_chat(msg)
        if cmd_num == CMD_WHISPER:
            return self.whisper(msg)
        if cmd_num == CMD_GIFT_CODE_USE:
            return self.gift_code_use(msg)
        if cmd_num == CMD_DAZUO_SINGLE:
            return self.dazuo_single(msg)
        if cmd_num == CMD_DAZUO_BOTH:
            return self.dazuo_both(msg)
        if cmd_num == CMD_DAZUO_EXIT:
            return self.dazuo_exit(msg)
        if cmd_num == CMD_TILE:
            return self.tile_step(msg)
        if cmd_num == CMD_JUMP:
            return self.jump(msg)
        if cmd_num == CMD_TELEPORT:
            return self.teleport(msg)
        if cmd_num == CMD_FACE:
            return self.change_face(msg)
        if cmd_num == CMD_INNER_FLY:
            return self.inner_fly(msg)
        if cmd_num == CMD_TOWN_REVIVE:
            return self.town_revive(msg)
        if cmd_num == CMD_SKILL_MOVE:
            return self.skill_move(msg)
        if cmd_num == CMD_SKILL_FIRE:
            reply = self.skill_fire(msg)
            extra = self.ai_tick()
            if extra is None:
                return reply
            if reply is None:
                return extra
            first = tuple(reply) if isinstance(reply, tuple) else (reply,)
            return first + tuple(extra)
        if cmd_num in CMD_UNKNOWN_OBSERVED:
            log.info('conn %d: observed command %r (no handler yet)',
                     self.conn_id, cmd)
            return None
        if cmd_num == CMD_APPLY_STAGE:
            # Java answers 20000 with the bare [1, mapId, [x, y]] reply
            # (StageControllOutputWrapper.applyChangeMap). The init burst
            # and the scene arrive only after the client's own requests:
            # pushing 21000 unprompted here is what wedged the client
            # before it ever sent 21000 (session-20261018-040230).
            return self.apply_stage(msg)
        if cmd_num == CMD_CHANGE_STAGE:
            return self.change_stage(msg)
        if cmd_num == CMD_MONEY:
            return self.money_info()
        if cmd_num == CMD_ROLE_EWAI:
            return self.role_extra_info()
        if cmd_num == CMD_FIGHTING:
            return self.fighting_info()
        if cmd_num == CMD_ROLE_SETTINGS:
            return self.role_settings(msg)
        if cmd_num == CMD_SETTING_QUICKBAR:
            return self.setting_quickbar(msg)
        if cmd_num == CMD_SETTING_PANEL:
            return self.setting_panel(msg)
        if cmd_num == CMD_SETTING_UI:
            return self.setting_ui(msg)
        if cmd_num == CMD_SETTING_GUAJI:
            return self.setting_guaji(msg)
        if cmd_num == CMD_ROLE_ATTRS:
            return self.attribute_info()
        if cmd_num == CMD_PING:
            return self.ping()
        if cmd_num == CMD_ZUOQI_INFO:
            return self.zuoqi_info()
        if cmd_num == CMD_RECIVE_YB:
            roles = self.get_roles(self.authed_user or '', self.server_id or '')
            role = roles[0] if roles else {}
            return frame(amf3_encode(['35011', int(role.get('recive_yb') or 0)]))
        if cmd_num == CMD_RECIVE_YB_CLAIM:
            return self.recive_yb_claim()
        if cmd_num == CMD_ROLE_QUERY_NAME:
            return self.role_query_by_name(msg)
        if cmd_num == CMD_EQUIP_INFO:
            return self.equip_info()
        if cmd_num == CMD_EQUIP_DRESS:
            return self.equip_dress(msg)
        if cmd_num == CMD_EQUIP_QIANGHUA:
            return self.equip_qianghua(msg)
        if cmd_num == CMD_EQUIP_JINJIE:
            return self.equip_jinjie(msg)
        if cmd_num == CMD_EQUIP_QIANGHUA_CLEAR:
            return self.equip_qianghua_clear(msg)
        if cmd_num == CMD_EQUIP_JIANDING:
            return self.equip_jianding(msg)
        if cmd_num == CMD_EQUIP_JIANDING_CLEAR:
            return self.equip_jianding_clear(msg)
        if cmd_num == CMD_EQUIP_JIANDING_EXP:
            return self.equip_jianding_exp(msg)
        if cmd_num == CMD_EQUIP_HECHENG:
            return self.equip_hecheng(msg)
        if cmd_num == CMD_EQUIP_HECHENG_COUNT:
            return self.equip_hecheng_count(msg)
        if cmd_num == CMD_VIP_DAY:
            return self.vip_day(msg)
        if cmd_num == CMD_VIP_WEEK:
            return self.vip_week(msg)
        if cmd_num == CMD_VIP_TEJIA:
            return self.vip_tejia(msg)
        if cmd_num == CMD_VIP_KAIFU:
            return self.vip_kaifu(msg)
        if cmd_num == CMD_VIP_LOTTERY:
            return self.vip_lottery(msg)
        if cmd_num == CMD_VIP_LINGJIANG:
            return self.vip_lingjiang(msg)
        if cmd_num == CMD_VIP_HUODONG:
            return self.vip_huodong(msg)
        if cmd_num == CMD_VIP_HUODONG_GUDING:
            return self.vip_huodong_guding(msg)
        if cmd_num == CMD_VIP_HUODONG_CHOUJIANG:
            return self.vip_huodong_choujiang(msg)
        if cmd_num == CMD_VIPQQ_INFO:
            return self.vipqq_info(msg)
        if cmd_num == CMD_VIPQQ_REWARDS:
            return self.vipqq_rewards(msg)
        if cmd_num == CMD_SKILL_INFO:
            return self.skill_info()
        if cmd_num == CMD_SKILL_UPGRADE:
            return self.skill_upgrade(msg)
        if cmd_num == CMD_SKILLBOOK_INFO:
            return self.skillbook_info()
        if cmd_num == CMD_SKILLBOOK_MOVE:
            return self.skillbook_move(msg)
        if cmd_num == CMD_SKILLBOOK_TUNSHI:
            return self.skillbook_tunshi(msg)
        if cmd_num == CMD_EQUIP_QIANGHUA_MAX:
            return self.equip_qianghua_max(msg)
        if cmd_num == CMD_BAG_GOODS:
            return self.bag_goods()
        if cmd_num == CMD_BAG_CLEARUP:
            return self.bag_clearup('bag')
        if cmd_num == CMD_STORAGE_GOODS:
            return self.storage_goods()
        if cmd_num == CMD_STORAGE_CLEARUP:
            return self.bag_clearup('storage')
        if cmd_num == CMD_XUNBAO_CLEARUP:
            return self.bag_clearup('xunbao')
        if cmd_num == CMD_XUNBAO_GOODS:
            return self.xunbao_goods()
        if cmd_num == CMD_BAG_ACTIVATE:
            return self.bag_activate('bag', msg)
        if cmd_num == CMD_STORAGE_ACTIVATE:
            return self.bag_activate('storage', msg)
        if cmd_num == CMD_BAG_GROWUP:
            return self.bag_growup('bag')
        if cmd_num == CMD_STORAGE_GROWUP:
            return self.bag_growup('storage')
        if cmd_num == CMD_BAG_INSPECT:
            return self.bag_inspect(msg)
        if cmd_num == CMD_MAIN_TASK:
            return self.main_task()
        if cmd_num == CMD_CHAPTERS:
            return self.chapters_info()
        if cmd_num == CMD_SUBCHAPTER:
            return self.subchapter_info(msg)
        if cmd_num == CMD_TASK_INFO:
            return self.task_select_info(msg)
        if cmd_num == CMD_SUBMIT_TASK:
            return self.submit_task(msg)
        if cmd_num == CMD_CHAPTER_TIPS:
            return self.chapter_tips(msg)
        if cmd_num == CMD_TAOFA_LIST:
            return self.taofa_list()
        if cmd_num == CMD_TAOFA_TUNSHI:
            return self.taofa_tunshi(msg)
        if cmd_num == CMD_RICHANG_INFO:
            return self.richang_info()
        if cmd_num == CMD_RICHANG_DECREASE:
            return self.richang_decrease()
        if cmd_num == CMD_RICHANG_INCREASE:
            return self.richang_increase()
        if cmd_num == CMD_RICHANG_ZHIJIE:
            return self.richang_zhijie()
        if cmd_num == CMD_RICHANG_COMPLETE_ALL:
            return self.richang_complete_all()
        if cmd_num == CMD_RICHANG_COMPLETE_BEST:
            return self.richang_complete_best()
        if cmd_num == CMD_RICHANG_NOTIFY_LOOP:
            return self.richang_notify_loop()
        if cmd_num == CMD_GONGHUI_INFO:
            return self.gonghui_info()
        if cmd_num == CMD_GONGHUI_DECREASE:
            return self.gonghui_decrease()
        if cmd_num == CMD_GONGHUI_INCREASE:
            return self.gonghui_increase()
        if cmd_num == CMD_GONGHUI_ZHIJIE:
            return self.gonghui_zhijie()
        if cmd_num == CMD_GONGHUI_COMPLETE_ALL:
            return self.gonghui_complete_all()
        if cmd_num == CMD_GONGHUI_COMPLETE_BEST:
            return self.gonghui_complete_best()
        if cmd_num == CMD_GONGHUI_NOTIFY_LOOP:
            return self.gonghui_notify_loop()
        if cmd_num == CMD_HUODONG_ONLINE_INFO:
            return self.huodong_online_info()
        if cmd_num == CMD_HUODONG_ONLINE_REWARD:
            return self.huodong_online_reward()
        if cmd_num == CMD_HUODONG_FIRST_INFO:
            return self.huodong_first_info(msg)
        if cmd_num == CMD_HUODONG_FIRST_REWARD:
            return self.huodong_first_reward(msg)
        if cmd_num == CMD_POZHEN_INFO:
            return self.pozhen_info()
        if cmd_num == CMD_POZHEN_START:
            return self.pozhen_start(msg)
        if cmd_num == CMD_POZHEN_SAODANG:
            return self.pozhen_saodang(msg)
        if cmd_num == CMD_POZHEN_REFRESH:
            return self.pozhen_refresh()
        if cmd_num == CMD_POZHEN_MOVE:
            return self.pozhen_move(msg)
        if cmd_num == CMD_POZHEN_BUY:
            return self.pozhen_buy()
        if cmd_num == CMD_POZHEN_SDOVER:
            return self.pozhen_sdover()
        if cmd_num == CMD_POZHEN_QUICKLY:
            return self.pozhen_quickly()
        if cmd_num == CMD_POZHEN_RECOVERY:
            return self.pozhen_recovery()
        if cmd_num == CMD_POZHEN_STOP:
            return self.pozhen_stop()
        if cmd_num == CMD_POZHEN_GET_GOODS:
            return self.pozhen_get_goods(msg)
        if cmd_num == CMD_ZUOQI_PANEL:
            return self.zuoqi_panel(msg)
        if cmd_num == CMD_ZUOQI_RIDE:
            return self.zuoqi_ride(msg)
        if cmd_num == CMD_ZUOQI_CLAIM:
            return self.zuoqi_claim()
        if cmd_num == CMD_ZUOQI_JINJIE:
            return self.zuoqi_jinjie(msg)
        if cmd_num == CMD_ZUOQI_FANHUAN:
            return self.zuoqi_fanhuan()
        if cmd_num == CMD_ZUOQI_MEIREN:
            return self.zuoqi_jiangli_meiren()
        if cmd_num == CMD_ZUOQI_FANHUAN_LIST:
            return self.zuoqi_fanhuan_list()
        if cmd_num == CMD_ZUOQI_ZHANLI:
            return self.zuoqi_zhanli()
        if cmd_num == CMD_ZUOQI_AWARD:
            return self.zuoqi_award_info()
        if cmd_num == CMD_MEIREN_PANEL:
            return self.meiren_panel()
        if cmd_num == CMD_MEIREN_ADD:
            return self.meiren_obtain(msg)
        if cmd_num == CMD_MEIREN_UPGRADE:
            return self.meiren_upgrade(msg)
        if cmd_num == CMD_MEIREN_CHANMIAN:
            return self.meiren_chanmian(msg)
        if cmd_num == CMD_PET_INFO:
            return self.pet_info()
        if cmd_num == 136005:
            return self.pet_updown(msg)
        if cmd_num == 136006:
            return self.pet_chuzhan(msg)
        if cmd_num == CMD_BAOSHI_INFO:
            return self.baoshi_info()
        if cmd_num == CMD_BAOSHI_JIHUO:
            return self.baoshi_jihuo(msg)
        if cmd_num == CMD_BAOSHI_UPGRADE:
            return self.baoshi_upgrade(msg)
        if cmd_num == CMD_BAG_MOVE:
            return self.bag_move(msg)
        if cmd_num == CMD_BAG_SPLIT:
            return self.bag_split(msg)
        if cmd_num == CMD_BAG_DISCARD:
            return self.bag_discard(msg)
        if cmd_num == CMD_BAG_DELETE:
            return self.bag_delete(msg)
        if cmd_num == CMD_GOODS_PICKUP:
            return self.pickup_goods(msg)
        if cmd_num == CMD_PROP_USE:
            return self.prop_use(msg)
        if cmd_num == CMD_PROP_DUOXUAN:
            return self.prop_duoxuan(msg)
        if cmd_num == CMD_PROP_YOUHUI:
            return self.prop_youhui(msg)
        if cmd_num == CMD_PROP_TESHU:
            return self.prop_teshu_count(self.safe(msg, 1))
        if cmd_num == CMD_DAFUWENG:
            return self.dafuweng_info(msg)
        if cmd_num == CMD_SHENJIANG_INFO:
            return self.shenjiang_slot_info(msg)
        if cmd_num == CMD_QIANDAO_INFO:
            return self.qiandao_info()
        if cmd_num == CMD_QIANDAO_SIGN:
            return self.qiandao_sign()
        if cmd_num == CMD_QIANDAO_BUQIAN:
            return self.qiandao_buqian(msg)
        if cmd_num == CMD_QIANDAO_REWARD:
            return self.qiandao_reward(msg)
        if cmd_num == CMD_QIANDAO_MEIREN:
            return self.qiandao_meiren(msg)
        if cmd_num == CMD_YINGYIN_XIAZAI:
            return self.yingyin_xiazai()
        if cmd_num == CMD_YINGYIN_STATE:
            return self.yingyin_state()
        if cmd_num == CMD_YINGYIN_REWARD:
            return self.yingyin_reward()
        if cmd_num == CMD_WEIDAN_STATE:
            return self.weidan_state(msg)
        if cmd_num == CMD_WEIDAN_REWARD:
            return self.weidan_reward(msg)
        if cmd_num == CMD_ONLINE_INFO:
            return self.online_reward_info(msg)
        if cmd_num == CMD_ONLINE_YAOJIANG:
            return self.online_yaojiang(msg)
        if cmd_num == CMD_ONLINE_LINGQU:
            return self.online_lingqu(msg)
        if cmd_num == CMD_HUSONG_POSITION:
            return self.husong_position(msg)
        if cmd_num == CMD_HUSONG_INFO:
            return self.husong_info(msg)
        if cmd_num == CMD_HUSONG_DAJIE:
            return self.husong_dajie(msg)
        if cmd_num == CMD_MALL:
            return self.mall_info(msg)
        if cmd_num == CMD_MALL_BUY:
            return self.mall_buy(msg)
        if cmd_num == CMD_BUYBACK_SELL:
            return self.buyback_sell(msg)
        if cmd_num == CMD_BUYBACK_HUIGOU:
            return self.buyback_huigou(msg)
        if cmd_num == CMD_BUYBACK_LIST:
            return self.buyback_list()
        if cmd_num == CMD_BAGDUMMY_DUIHUAN:
            return self.bagdummy_info()
        if cmd_num == CMD_GONGHUI_MALL_COUNT:
            return self.gonghui_mall_count()
        if cmd_num == CMD_JUQING_AWARD:
            return self.juqing_award()
        if cmd_num == CMD_JUQING_INFO:
            return self.juqing_info()
        if cmd_num == CMD_JUQING_CHALLENGE:
            return self.juqing_challenge(msg)
        if cmd_num == CMD_JUQING_SAODANG:
            return self.juqing_saodang(msg)
        if cmd_num == CMD_JUQING_FINISH:
            return self.juqing_finish(msg)
        if cmd_num == CMD_JUQING_ACCEL:
            return self.juqing_accelerate(msg)
        if cmd_num == CMD_JUQING_LINGQU:
            return self.juqing_lingqu(msg)
        if cmd_num == CMD_JUQING_ONEKEY:
            return self.juqing_onekey(msg)
        if cmd_num == CMD_VIP:
            return self.vip_info()
        if cmd_num == CMD_ZUWU:
            return self.zuwu_info()
        if cmd_num == CMD_ZUWUFUBEN:
            return self.zuwufuben_info()
        if cmd_num == CMD_ZUWU_ENTER:
            return self.zuwu_enter(msg)
        if cmd_num == CMD_ZUWU_SAODANG:
            return self.zuwu_saodang(msg)
        if cmd_num == CMD_ZUWU_QUIT:
            return self.zuwu_quit()
        if cmd_num == CMD_ZUWU_BUY:
            return self.zuwu_buy(msg)
        if cmd_num == CMD_ZUWU_REFRESH:
            return self.zuwu_refresh(msg)
        if cmd_num == CMD_ZUWU_BUYALL:
            return self.zuwu_buy_all()
        if cmd_num == CMD_BUFF:
            return self.buff_query(msg)
        if cmd_num == CMD_ZUOQI_HP:
            return self.zuoqi_hp(msg)
        if cmd_num == CMD_ZUOQI_FULLHP:
            return self.zuoqi_full_hp(msg)
        if cmd_num == CMD_ZUOQI_REVIVE:
            return self.zuoqi_revive(msg)
        if cmd_num == CMD_ZUOQI_FREEREVIVE:
            return self.zuoqi_free_revive(msg)
        if cmd_num == CMD_ZUOQI_DEADINFO:
            return self.zuoqi_dead_info(msg)
        if cmd_num == 127000:
            return self.loginlibao_info(msg)
        if cmd_num == 127001:
            return self.loginlibao_claim(msg)
        if cmd_num == 58000:
            return self.lvlibao_info(msg)
        if cmd_num == 58001:
            return self.lvlibao_claim(msg)
        if cmd_num == 63001:
            return self.email_list(msg)
        if cmd_num == 63002:
            return self.email_info(msg)
        if cmd_num == 63003:
            return self.email_attachment(msg)
        if cmd_num == 63004:
            return self.email_delete(msg)
        if cmd_num == 63006:
            return self.email_jb(msg)
        if cmd_num == 63007:
            return self.email_yb(msg)
        if cmd_num == 63008:
            return self.email_onekey(msg)
        if cmd_num == 41000:
            return self.shenjiang_info(msg)
        if cmd_num == CMD_SHENJIANG_ACTIVATE:
            return self.shenjiang_activate(msg)
        if cmd_num == CMD_SHENJIANG_SKILLUP:
            return self.shenjiang_skill_up(msg)
        if cmd_num == CMD_SHENJIANG_CANJIHUO:
            return self.shenjiang_can_jihuo(msg)
        if cmd_num == CMD_SHENJIANG_JIHUO:
            return self.shenjiang_jihuo(msg)
        if cmd_num == CMD_SHENJIANG_JINJIE:
            return self.shenjiang_jinjie(msg)
        if cmd_num == CMD_CHENGJIU_PANEL:
            return self.chengjiu_panel()
        if cmd_num == CMD_CHENGJIU_CLAIM:
            return self.chengjiu_claim(msg)
        if cmd_num == 103000:
            return self.loginlingjiang_info(msg)
        if cmd_num == 103001:
            return self.loginlingjiang_claim(msg)
        if cmd_num == 104000:
            return self.touxian_info(msg)
        if cmd_num == 104001:
            return self.touxian_activate(msg)
        if cmd_num == 104002:
            return self.touxian_wear(msg)
        if cmd_num == 102000:
            return self.guangyi_info(msg)
        if cmd_num == 102002:
            return self.guangyi_buy(msg)
        if cmd_num == 102003:
            return self.guangyi_wear(msg)
        if cmd_num == 71000:
            return self.baixian_info(msg)
        if cmd_num == 71001:
            return self.baixian_worship(msg)
        if cmd_num == 107000:
            return self.zhuihui_info(msg)
        if cmd_num == 107001:
            return self.zhuihui_claim(msg)
        if cmd_num == 121000:
            return self.kapai_client(msg)
        if cmd_num == 121001:
            return self.kapai_info(msg)
        if cmd_num == 120000:
            return self.qianfu_client(msg)
        if cmd_num == 122002:
            return self.tuangou_config(msg)
        if cmd_num == 109000:
            return self.guanggao_list(msg)
        if cmd_num == CMD_DAFUWONG_INFO:
            return self.dafuwong_info(msg)
        if cmd_num == CMD_DAFUWONG_ROLL:
            return self.dafuwong_roll(msg)
        if cmd_num == CMD_DAFUWONG_EXCHANGE:
            return self.dafuwong_exchange(msg)
        if cmd_num == CMD_XIANSHIBUY_CLIENT:
            return self.xianshibuy_client(msg)
        if cmd_num == CMD_XIANSHIBUY_INFO:
            return self.xianshibuy_info(msg)
        if cmd_num == CMD_XIANSHIBUY_BUY:
            return self.xianshibuy_buy(msg)
        if cmd_num == CMD_XIANSHIBUY_CLEARCD:
            return self.xianshibuy_clearcd(msg)
        if cmd_num == CMD_BOOTH_ONLINE:
            return self.booth_online_list()
        if cmd_num == CMD_BOOTH_DETAILS:
            return self.booth_detail_infos(msg)
        if cmd_num == CMD_BOOTH_IN:
            return self.booth_in(msg)
        if cmd_num == CMD_BOOTH_OUT:
            return self.booth_out(msg)
        if cmd_num == CMD_BOOTH_CHANGE_PRICE:
            return self.booth_change_price(msg)
        if cmd_num == CMD_BOOTH_CHANGE_INDEX:
            return self.booth_change_index(msg)
        if cmd_num == CMD_BOOTH_SEACH:
            return self.booth_seach(msg)
        if cmd_num == CMD_BOOTH_INFO:
            return self.booth_info(msg)
        if cmd_num == CMD_BOOTH_BUY:
            return self.booth_buy(msg)
        if cmd_num == CMD_BOOTH_LOG:
            return self.booth_log()
        if cmd_num == CMD_BOOTH_TRADE_LOG:
            return self.booth_trade_log()
        if cmd_num == CMD_BOOTH_NAME:
            return self.booth_modify_name(msg)
        if cmd_num == CMD_BOOTH_YB_SELL:
            return self.booth_yb_sell(msg)
        if cmd_num == CMD_BOOTH_JB_SELL:
            return self.booth_jb_sell(msg)
        if cmd_num == CMD_BOOTH_BUY_YB:
            return self.booth_buy_yb(msg)
        if cmd_num == CMD_BOOTH_BUY_JB:
            return self.booth_buy_jb(msg)
        if cmd_num == CMD_BOOTH_MONEY:
            return self.booth_money()
        if cmd_num == CMD_BOOTH_MONEY_CLAIM:
            return self.booth_money_claim()
        if cmd_num == CMD_FRIEND_INFO:
            return self.friend_info()
        if cmd_num == CMD_FRIEND_ADD:
            return self.friend_add(msg)
        if cmd_num == CMD_FRIEND_DEL:
            return self.friend_del(msg)
        if cmd_num == CMD_FOE_ADD:
            return self.foe_add(msg)
        if cmd_num == CMD_FOE_DEL:
            return self.foe_del(msg)
        if cmd_num == CMD_BLACKLIST_ADD:
            return self.blacklist_add(msg)
        if cmd_num == CMD_BLACKLIST_DEL:
            return self.blacklist_del(msg)
        if cmd_num == CMD_CONTACTS_ADD:
            return self.contacts_add(msg)
        if cmd_num == CMD_CONTACTS_DEL:
            return self.contacts_del(msg)
        if cmd_num == CMD_FRIEND_XINQING:
            return self.friend_xinqing(msg)
        if cmd_num == CMD_FRIEND_FIGHT:
            return self.friend_fight(msg)
        if cmd_num in (53006, 51000,
                        82024, 74000,
                        86000, 85000, 87000, 70500, 91002, 90000,
                        92015, 93000, 94002, 94100, 95000, 97001,
                        114000, 113000,
                        120100, 124001):
            return self.loading_stub(msg, cmd_num)
        log.warning('conn %d: unknown command %r payload=%r (ignored)',
                      self.conn_id, cmd, msg)
        return None

    # -- player stalls (BoothAction/BoothServiceImpl bytecode) --
    def _booth_self(self):
        """Requester role and its canonical id, or (None, None)."""
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None, None
        return role, str(role.get('id'))

    def _booth_canonical(self, ref):
        """Canonical numeric id for a wire role reference, or None."""
        try:
            brief = self.get_role_brief(ref)
        except Exception:
            brief = None
        if brief is None:
            return None
        return str(brief.get('id'))

    def _booth_session_of(self, ref):
        """Live session for a role reference; sessions register by wire id."""
        if self.stage_registry is None:
            return None
        for key in (str(ref),):
            try:
                sess = self.stage_registry.session_of(key)
            except Exception:
                sess = None
            if sess is not None:
                return sess
        cid = self._booth_canonical(ref)
        if cid is None:
            return None
        try:
            sess = self.stage_registry.session_of(cid)
        except Exception:
            sess = None
        if sess is not None:
            return sess
        try:
            brief = self.get_role_brief(ref)
        except Exception:
            brief = None
        legacy = (brief or {}).get('legacy_id')
        if not legacy:
            return None
        try:
            return self.stage_registry.session_of(str(legacy))
        except Exception:
            return None

    @staticmethod
    def _booth_long(value):
        """object2Long: ints, integral floats and numeric strings, else None."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value) if value.is_integer() else None
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                try:
                    as_float = float(value)
                except ValueError:
                    return None
                return int(as_float) if as_float.is_integer() else None
        return None

    @staticmethod
    def _booth_ref(value):
        """Role reference on the wire: strings verbatim, numbers by value."""
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, float):
            if not value.is_integer():
                return None
            value = int(value)
        text = str(value)
        return text if text != '' else None

    @staticmethod
    def _booth_money(value):
        """Money cells ride the wire as doubles (32010 convention)."""
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def _booth_err(self, cmd, code):
        """BoothErrorCodeOutput shape: [0, code] under the command id."""
        return frame(amf3_encode([str(cmd), [0, code]]))

    def _booth_ensure(self, cid):
        """A role's stall row, creating the Java defaults (state 1, zeroed)."""
        try:
            booth = self.get_booth(cid)
        except Exception:
            booth = None
        if booth is not None:
            return booth
        created = int(time.time() * 1000)
        try:
            self.save_booth(cid, booth_state=1, booth_jb=0, booth_yb=0,
                            created=created)
        except Exception:
            pass
        return {'role_id': cid, 'booth_name': None, 'booth_state': 1,
                'booth_jb': 0, 'booth_yb': 0, 'booth_buy_time': None,
                'created': created}

    def _booth_balance(self, role, money):
        """Character money balance (YXB -> tongqian, YB -> lingshi)."""
        try:
            return int(role.get(BAG_MONEY_COLUMNS[money]) or 0)
        except (TypeError, ValueError):
            return 0

    def _booth_check(self, role, money, amount):
        """decrCheck: funds sufficient, without mutating."""
        return self._booth_balance(role, money) >= amount

    def _booth_fee(self, amount):
        """getYbShui: 0 without a rate, 1 under 10, else round(amount*rate)."""
        try:
            rate = float(self.config.trade_fee_rate()) \
                if self.config is not None else 0.0
        except (TypeError, ValueError):
            rate = 0.0
        if rate == 0:
            return 0
        if amount <= 10:
            return 1
        return int(math.floor(amount * rate + 0.5))

    @staticmethod
    def _booth_expired(slot):
        """Expired bag rows never list (canShangJia toggle has no source)."""
        try:
            exp = slot.get('expire_time')
        except AttributeError:
            return False
        if not exp:
            return False
        try:
            return int(exp) < int(time.time() * 1000)
        except (TypeError, ValueError):
            return False

    def _booth_bag_fits(self, rid, goods_id, count, bind):
        """checkPutInBag1: reward stacks plus empty bag slots cover it."""
        try:
            left = int(count or 0)
        except (TypeError, ValueError):
            return False
        if left <= 0:
            return True
        try:
            slots = self.get_role_bag_slots(rid, 1, 150) or []
        except Exception:
            slots = []
        try:
            stack = int(self.config.goods_max_stack(goods_id) or 1) \
                if self.config is not None else 1
        except (TypeError, ValueError):
            stack = 1
        for slot in slots:
            if self._bag_same_kind(slot, {'goods_id': goods_id,
                                          'bind': bind}):
                try:
                    room = stack - int(slot.get('count') or 0)
                except (TypeError, ValueError):
                    room = 0
                left -= max(room, 0)
        if left <= 0:
            return True
        try:
            state = self._bag_state_or_init(rid) or {}
            capacity = int(state.get('bag_capacity') or 0)
        except (TypeError, ValueError):
            return False
        used = {s.get('slot_num') for s in slots}
        free = sum(1 for n in range(1, capacity + 1) if n not in used)
        return left <= free * stack

    @staticmethod
    def _booth_log_date():
        """Calendar month/day/12-hour/min/sec cells of the trade log codes."""
        now = time.localtime()
        return now.tm_mon, now.tm_mday, now.tm_hour % 12, now.tm_min, now.tm_sec

    def _booth_goods_name(self, goods_id):
        """GoodsConfig name for the trade log, else the bare goods id."""
        try:
            table = self.config._goods_table() \
                if self.config is not None else None
        except Exception:
            table = None
        try:
            return (table or {}).get(str(goods_id), {}).get('name') \
                or str(goods_id)
        except Exception:
            return str(goods_id)

    def _booth_trade_exp_one(self, cid, role):
        """One party's tradeSuccessAddExp: 120s-gated dealaddexp grant."""
        try:
            booth = self.get_booth(cid)
        except Exception:
            booth = None
        if booth is None:
            return []
        now = int(time.time() * 1000)
        try:
            last = booth.get('booth_buy_time')
            last = int(last) if last else 0
        except (TypeError, ValueError):
            last = 0
        grant = False
        if not last:
            grant = True
        else:
            gap = now - last
            if gap >= 0 and gap >= BOOTH_TRADE_EXP_MS:
                grant = True
        try:
            self.save_booth(cid, booth_buy_time=now)
        except Exception:
            pass
        if not grant:
            return []
        if role is None:
            try:
                brief = self.get_role_brief(cid)
            except Exception:
                brief = None
            if brief is None:
                return []
            role = {'id': brief.get('id'), 'level': brief.get('level'),
                    'exp': brief.get('exp')}
        try:
            level = int(role.get('level') or 0)
            row = self.config.role_attribute_row(level) \
                if self.config is not None else None
            amount = int((row or {}).get('dealaddexp') or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            return []
        try:
            _total, _level, _gained, frames = self._role_gain_exp(
                role, cid, amount)
        except Exception:
            return []
        return list(frames or [])

    def _booth_deliver_seller(self, seller_cid, buyer_cid, frames):
        """PublicMsgQueue flush: live sellers get frames, self-trades merge."""
        if not frames:
            return []
        if seller_cid == buyer_cid:
            return list(frames)
        sess = self._booth_session_of(seller_cid)
        if sess is None:
            return []
        if sess is self:
            return list(frames)
        try:
            sess.push_frames(frames)
        except Exception:
            pass
        return []

    def _booth_formart(self, booth):
        """Booth.fomart: {'0': seller, '1': name, '2': seller}."""
        sid = str(booth.get('role_id'))
        return {'0': sid, '1': booth.get('booth_name'), '2': sid}

    def _booth_item_vo(self, role, sell):
        """BoothVoOutput.getBoothItemVo: [id, goods map, sellYb, sellJb, slot]."""
        slot = {'goods_id': sell.get('goods_id'),
                'bag_id': sell.get('id'),
                'slot_num': sell.get('slot') or 0,
                'count': sell.get('count') or 0,
                'bind': sell.get('bind') or 0,
                'expire_time': sell.get('expire_time'),
                'item_level': sell.get('item_level') or 0,
                'rare_level': sell.get('rare_level') or 0,
                'attributes': sell.get('attributes')}
        return [sell.get('id'), self.bag_goods_map(role, slot),
                self._booth_money(sell.get('sell_yb')),
                self._booth_money(sell.get('sell_jb')),
                sell.get('slot') or 0]

    def _booth_public_sellers(self):
        """Stall rows holding listings whose seller is publicly online."""
        try:
            booths = self.list_public_booths() or []
        except Exception:
            booths = []
        out = []
        for booth in booths:
            sid = str(booth.get('role_id'))
            if self._booth_session_of(sid) is None:
                continue
            out.append((sid, booth))
        return out

    def booth_online_list(self):
        """Command 35100: [ownRoleId, fomart list or null] of open stalls."""
        _role, cid = self._booth_self()
        if cid is None:
            return None
        stalls = [self._booth_formart(booth)
                  for _sid, booth in self._booth_public_sellers()]
        return frame(amf3_encode(['35100', [cid, stalls or None]]))

    def _booth_detail_map(self, seller_cid):
        """getBoothDetailInfo map ('0'..'7'; '7' is the online flag)."""
        try:
            booth = self.get_booth(seller_cid)
        except Exception:
            booth = None
        if booth is None:
            return None
        info = {'0': seller_cid, '1': booth.get('booth_name'),
                '2': seller_cid, '7': 0}
        if self._booth_session_of(seller_cid) is None:
            return info
        try:
            brief = self.get_role_brief(seller_cid)
        except Exception:
            brief = None
        if brief is None:
            return info
        try:
            sells = self.list_booth_sells(seller_cid) or []
        except Exception:
            sells = []
        goods = 0
        flag = 0
        for sell in sells:
            try:
                slot = int(sell.get('slot') or 0)
            except (TypeError, ValueError):
                continue
            if slot < BOOTH_GOODS_VISIBLE_MAX:
                goods += 1
            elif slot == BOOTH_SLOT_YB:
                flag = 3 if flag == 2 else 1
            elif slot == BOOTH_SLOT_JB:
                flag = 3 if flag == 1 else 2
        info.update({'3': brief.get('name'), '4': brief.get('level'),
                     '5': goods, '6': flag, '7': 1})
        return info

    def booth_detail_infos(self, msg):
        """Command 35120: per-seller detail maps (null holes stay null)."""
        _role, _cid = self._booth_self()
        if _cid is None:
            return None
        args = self.safe(msg, 1)
        if not args:
            return frame(amf3_encode(['35120', None]))
        out = []
        for ref in args:
            sid = self._booth_ref(ref)
            if sid is None:
                out.append(None)
                continue
            cid = self._booth_canonical(sid)
            if cid is None:
                out.append(None)
                continue
            out.append(self._booth_detail_map(cid))
        return frame(amf3_encode(['35120', out]))

    def booth_in(self, msg):
        """Command 35101: list bag goods C> [cellGuid, sellYb, sellJb, count]."""
        role, cid = self._booth_self()
        if role is None:
            return None
        args = self.safe(msg, 1, [])
        cell = self.safe(args, 0)
        sell_yb = self._booth_long(self.safe(args, 1))
        sell_jb = self._booth_long(self.safe(args, 2))
        count = self._booth_long(self.safe(args, 3))
        if not cell or not isinstance(cell, str):
            return None
        if sell_yb is None or sell_yb < 0 or sell_yb > BOOTH_MAX_PRICE:
            return None
        if sell_jb is None or sell_jb < 0 or sell_jb > BOOTH_MAX_PRICE:
            return None
        if count is None or count <= 0:
            return None
        try:
            sells = self.list_booth_sells(cid) or []
        except Exception:
            sells = []
        visible = 0
        for sell in sells:
            try:
                if int(sell.get('slot') or 0) < BOOTH_GOODS_VISIBLE_MAX:
                    visible += 1
            except (TypeError, ValueError):
                continue
        if visible >= BOOTH_GOODS_MAX:
            return self._booth_err(CMD_BOOTH_IN,
                                   BOOTH_ERR_ROLE_BOOTH_COUNT_MAX)
        if sell_yb < BOOTH_MIN_SELL_YB:
            return self._booth_err(CMD_BOOTH_IN, BOOTH_ERR_NO_INPUT_MONEY)
        if sell_jb == 0 and sell_yb == 0:
            return self._booth_err(CMD_BOOTH_IN, BOOTH_ERR_NO_INPUT_MONEY)
        try:
            row = self.get_role_bag_slot_by_bag_id(cid, str(cell))
        except Exception:
            row = None
        if row is None:
            return self._booth_err(CMD_BOOTH_IN, BOOTH_ERR_GOODS_EXPIRE)
        try:
            have = int(row.get('count') or 0)
        except (TypeError, ValueError):
            have = 0
        try:
            bind = int(row.get('bind') or 0)
        except (TypeError, ValueError):
            bind = 0
        if bind == 1:
            return self._booth_err(CMD_BOOTH_IN, BOOTH_ERR_NO_BIND_GOODS)
        try:
            category = self.config.goods_category(str(row.get('goods_id'))) \
                if self.config is not None else None
        except Exception:
            category = None
        if category == '108':
            # isChuShou has no ported subsystem; reachable bag jades are
            # never socketed, so every reachable state lists (ledger gap).
            pass
        if count > have:
            return self._booth_err(CMD_BOOTH_IN, BOOTH_ERR_GOODS_COUNT_MAX)
        if self._booth_expired(row):
            return self._booth_err(CMD_BOOTH_IN, BOOTH_ERR_GOODS_EXPIRE)
        self._booth_ensure(cid)
        try:
            slot_num = int(row.get('slot_num') or 0)
        except (TypeError, ValueError):
            return None
        used = set()
        for sell in sells:
            try:
                used.add(int(sell.get('slot') or 0))
            except (TypeError, ValueError):
                continue
        slot = next((n for n in range(10) if n not in used), 0)
        sell = {'id': f'bs{uuid.uuid4().hex[:16]}', 'role_id': cid,
                'goods_id': str(row.get('goods_id')), 'count': count,
                'slot': slot, 'item_level': row.get('item_level') or 0,
                'rare_level': row.get('rare_level') or 0,
                'attributes': row.get('attributes'),
                'expire_time': row.get('expire_time'),
                'sell_jb': sell_jb, 'sell_yb': sell_yb, 'bind': bind,
                'created': int(time.time() * 1000)}
        try:
            placed = self.booth_list_goods_tx(sell, slot_num, have, count)
        except Exception:
            return None
        if placed != 'ok':
            return self._booth_err(CMD_BOOTH_IN, BOOTH_ERR_GOODS_EXPIRE)
        return frame(amf3_encode(
            [str(CMD_BOOTH_IN), [1, self._booth_item_vo(role, sell)]]))

    def booth_out(self, msg):
        """Command 35102: delist C> sellId, goods return to the bag."""
        role, cid = self._booth_self()
        if role is None:
            return None
        sell_id = self.safe(msg, 1)
        if not sell_id or not isinstance(sell_id, str):
            return None
        try:
            sell = self.get_booth_sell(sell_id, cid)
        except Exception:
            sell = None
        if sell is None:
            return self._booth_err(CMD_BOOTH_OUT,
                                   BOOTH_ERR_GOODS_NO_IN_BOOTH)
        item = {'goods_id': str(sell.get('goods_id')),
                'count': sell.get('count') or 0,
                'bind': sell.get('bind') or 0,
                'expire_time': sell.get('expire_time'),
                'rare_level': sell.get('rare_level') or 0,
                'item_level': sell.get('item_level') or 0,
                'attributes': sell.get('attributes')}
        if not self._booth_bag_fits(cid, item['goods_id'], item['count'],
                                    item['bind']):
            return self._booth_err(CMD_BOOTH_OUT, BOOTH_ERR_BAG_SLOT)
        try:
            stack = int(self.config.goods_max_stack(item['goods_id']) or 1) \
                if self.config is not None else 1
        except (TypeError, ValueError):
            stack = 1
        try:
            dropped = self.booth_delist_goods_tx(sell_id, cid, item, stack)
        except Exception:
            return None
        if dropped == 'gone':
            return self._booth_err(CMD_BOOTH_OUT,
                                   BOOTH_ERR_GOODS_NO_IN_BOOTH)
        if dropped != 'ok':
            return self._booth_err(CMD_BOOTH_OUT, BOOTH_ERR_BAG_SLOT)
        return frame(amf3_encode([str(CMD_BOOTH_OUT), [1, sell_id]]))

    def booth_change_price(self, msg):
        """Command 35103: reprice C> [sellId, sellYb, sellJb]."""
        role, cid = self._booth_self()
        if role is None:
            return None
        args = self.safe(msg, 1, [])
        sell_id = self.safe(args, 0)
        sell_yb = self._booth_long(self.safe(args, 1))
        sell_jb = self._booth_long(self.safe(args, 2))
        if not sell_id or not isinstance(sell_id, str):
            return None
        if sell_yb is None or sell_yb < 0:
            return None
        if sell_jb is None or sell_jb < 0:
            return None
        if sell_yb == 0 and sell_jb == 0:
            return self._booth_err(CMD_BOOTH_CHANGE_PRICE,
                                   BOOTH_ERR_NO_INPUT_MONEY)
        try:
            sell = self.get_booth_sell(sell_id, cid)
        except Exception:
            sell = None
        if sell is None:
            return self._booth_err(CMD_BOOTH_CHANGE_PRICE,
                                   BOOTH_ERR_GOODS_NO_IN_BOOTH)
        sell['sell_jb'] = sell_jb
        sell['sell_yb'] = sell_yb
        try:
            self.save_booth_sell(sell)
        except Exception:
            return None
        return frame(amf3_encode(
            [str(CMD_BOOTH_CHANGE_PRICE),
             [1, [sell_id, None, self._booth_money(sell_yb),
                   self._booth_money(sell_jb)]]]))

    def booth_change_index(self, msg):
        """Command 35104: move a listing C> [sellId, slot] (swap on clash)."""
        role, cid = self._booth_self()
        if role is None:
            return None
        args = self.safe(msg, 1, [])
        sell_id = self.safe(args, 0)
        slot = self._booth_long(self.safe(args, 1))
        if not sell_id or not isinstance(sell_id, str):
            return None
        if slot is None or slot < 0 or slot > 10:
            return None
        try:
            sell = self.get_booth_sell(sell_id, cid)
        except Exception:
            sell = None
        if sell is None:
            return self._booth_err(CMD_BOOTH_CHANGE_INDEX,
                                   BOOTH_ERR_GOODS_NO_IN_BOOTH)
        try:
            old = int(sell.get('slot') or 0)
        except (TypeError, ValueError):
            old = 0
        if slot == old:
            return self._booth_err(CMD_BOOTH_CHANGE_INDEX,
                                   BOOTH_ERR_SELL_INDEX_SAME)
        try:
            other = self.get_booth_sell_by_slot(cid, slot)
        except Exception:
            other = None
        try:
            if other is not None:
                other['slot'] = old
                self.save_booth_sell(other)
            sell['slot'] = slot
            self.save_booth_sell(sell)
        except Exception:
            return None
        return frame(amf3_encode(
            [str(CMD_BOOTH_CHANGE_INDEX), [1, sell_id, slot]]))

    def _booth_seach_money(self, slot):
        """seachBoothByYb/Jb: stalls holding that money-market listing."""
        stalls = []
        for sid, booth in self._booth_public_sellers():
            try:
                listing = self.get_booth_sell_by_slot(sid, slot)
            except Exception:
                listing = None
            if listing is not None:
                stalls.append(self._booth_formart(booth))
        return frame(amf3_encode([str(CMD_BOOTH_SEACH), stalls or None]))

    def booth_seach(self, msg):
        """Command 35105: '-1' YB stalls, '-2' YXB stalls, name, goods ids."""
        _role, cid = self._booth_self()
        if cid is None:
            return None
        args = self.safe(msg, 1, [])
        key = self._booth_ref(self.safe(args, 0))
        if key is None:
            return None
        goods = self.safe(args, 1) if len(args) > 1 else None
        if key == '-1':
            return self._booth_seach_money(BOOTH_SLOT_YB)
        if key == '-2':
            return self._booth_seach_money(BOOTH_SLOT_JB)
        if goods is None:
            try:
                roles = self.find_roles_by_name(key) or []
            except Exception:
                roles = []
            wanted = {str(r.get('id')) for r in roles}
            stalls = [self._booth_formart(booth)
                      for sid, booth in self._booth_public_sellers()
                      if sid in wanted]
            return frame(amf3_encode([str(CMD_BOOTH_SEACH), stalls or None]))
        if not isinstance(goods, list):
            return None
        wanted = set()
        for entry in goods:
            ref = self._booth_ref(entry)
            if ref is not None:
                wanted.add(ref)
        stalls = []
        for sid, booth in self._booth_public_sellers():
            try:
                sells = self.list_booth_sells(sid) or []
            except Exception:
                sells = []
            if any(str(s.get('goods_id')) in wanted for s in sells):
                stalls.append(self._booth_formart(booth))
        return frame(amf3_encode([str(CMD_BOOTH_SEACH), stalls or None]))

    def booth_info(self, msg):
        """Command 35106: a seller's [sellerId, goods, ybPair, jbPair]."""
        _role, _cid = self._booth_self()
        if _cid is None:
            return None
        ref = self._booth_ref(self.safe(msg, 1))
        if ref is None:
            return None
        seller_cid = self._booth_canonical(ref)
        if seller_cid is None or \
                self._booth_session_of(seller_cid) is None:
            return frame(amf3_encode([str(CMD_BOOTH_INFO), [ref, None]]))
        try:
            sells = self.list_booth_sells(seller_cid) or []
        except Exception:
            sells = []
        owner = {'id': seller_cid}
        goods = []
        yb_pair, jb_pair = None, None
        for sell in sorted(sells, key=lambda s: s.get('slot') or 0):
            try:
                slot = int(sell.get('slot') or 0)
            except (TypeError, ValueError):
                continue
            if slot < BOOTH_GOODS_VISIBLE_MAX:
                goods.append(self._booth_item_vo(owner, sell))
            elif slot == BOOTH_SLOT_YB and yb_pair is None:
                yb_pair = [self._booth_money(sell.get('sell_yb')),
                           self._booth_money(sell.get('sell_jb'))]
            elif slot == BOOTH_SLOT_JB and jb_pair is None:
                jb_pair = [self._booth_money(sell.get('sell_jb')),
                           self._booth_money(sell.get('sell_yb'))]
        return frame(amf3_encode(
            [str(CMD_BOOTH_INFO),
             [ref, goods or None, yb_pair, jb_pair]]))

    def _booth_goods_codes(self, buyer_name, seller_name, sell, fee):
        """tradeGoodsLog: buyer 424043 view, seller 424042 view (persisted)."""
        mo, day, hour, minute, sec = self._booth_log_date()
        goods = self._booth_goods_name(sell.get('goods_id'))
        try:
            count = int(sell.get('count') or 0)
        except (TypeError, ValueError):
            count = 0
        try:
            sell_jb = int(sell.get('sell_jb') or 0)
        except (TypeError, ValueError):
            sell_jb = 0
        try:
            sell_yb = int(sell.get('sell_yb') or 0)
        except (TypeError, ValueError):
            sell_yb = 0
        buyer = (f'424043,{mo},{day},{hour},{minute},{sec},{seller_name},'
                 f'{goods},{count},{sell_jb},{sell_yb}')
        seller = (f'424042,{mo},{day},{hour},{minute},{sec},{buyer_name},'
                  f'{goods},{count},{sell_jb},{sell_yb},{fee}')
        return buyer, seller

    def _booth_money_codes(self, yb_type, buyer_name, seller_name,
                           first, second, fee):
        """tradeMoneyLog views: YB-type 424064/424063, YXB-type 424066/424065."""
        mo, day, hour, minute, sec = self._booth_log_date()
        if yb_type:
            buyer = (f'424064,{mo},{day},{hour},{minute},{sec},'
                     f'{seller_name},{first},{second}')
            seller = (f'424063,{mo},{day},{hour},{minute},{sec},'
                      f'{buyer_name},{first},{second},0')
        else:
            buyer = (f'424066,{mo},{day},{hour},{minute},{sec},'
                     f'{seller_name},{first},{second}')
            seller = (f'424065,{mo},{day},{hour},{minute},{sec},'
                      f'{buyer_name},{first},{second},{fee}')
        return buyer, seller

    def booth_buy(self, msg):
        """Command 35107: buy goods C> [sellerId, sellId]."""
        role, cid = self._booth_self()
        if role is None:
            return None
        args = self.safe(msg, 1, [])
        ref = self._booth_ref(self.safe(args, 0))
        sell_id = self.safe(args, 1)
        if ref is None:
            return None
        if not sell_id or not isinstance(sell_id, str):
            return None
        seller_cid = self._booth_canonical(ref)
        if seller_cid is None:
            return None
        if self._booth_session_of(seller_cid) is None:
            return self._booth_err(CMD_BOOTH_BUY,
                                   BOOTH_ERR_SELL_ROLE_OFFLINE)
        try:
            seller_booth = self.get_booth(seller_cid)
        except Exception:
            seller_booth = None
        if seller_booth is None:
            return None
        try:
            sell = self.get_booth_sell(sell_id, seller_cid)
        except Exception:
            sell = None
        if sell is None:
            return self._booth_err(CMD_BOOTH_BUY,
                                   BOOTH_ERR_GOODS_NO_IN_BOOTH)
        if self._booth_session_of(seller_cid) is None:
            return self._booth_err(CMD_BOOTH_BUY,
                                   BOOTH_ERR_SELL_ROLE_OFFLINE)
        if cid == sell_id:
            # Java compares the buyer to the listing id (never the seller).
            return self._booth_err(CMD_BOOTH_BUY,
                                   BOOTH_ERR_NO_BUY_SELF_GOODS)
        try:
            sell_jb = int(sell.get('sell_jb') or 0)
        except (TypeError, ValueError):
            sell_jb = 0
        try:
            sell_yb = int(sell.get('sell_yb') or 0)
        except (TypeError, ValueError):
            sell_yb = 0
        if sell_jb > 0 and not self._booth_check(role, 'YXB', sell_jb):
            return self._booth_err(CMD_BOOTH_BUY, BOOTH_ERR_JB_NOT_ENOUGH)
        if sell_yb > 0 and not self._booth_check(role, 'YB', sell_yb):
            return self._booth_err(CMD_BOOTH_BUY, BOOTH_ERR_YB_NOT_ENOUGH)
        item = {'goods_id': str(sell.get('goods_id')),
                'count': sell.get('count') or 0,
                'bind': sell.get('bind') or 0,
                'expire_time': sell.get('expire_time'),
                'rare_level': sell.get('rare_level') or 0,
                'item_level': sell.get('item_level') or 0,
                'attributes': sell.get('attributes')}
        if not self._booth_bag_fits(cid, item['goods_id'], item['count'],
                                    item['bind']):
            return self._booth_err(CMD_BOOTH_BUY, BOOTH_ERR_BAG_SLOT)
        try:
            stack = int(self.config.goods_max_stack(item['goods_id']) or 1) \
                if self.config is not None else 1
        except (TypeError, ValueError):
            stack = 1
        try:
            fee = self._booth_fee(sell_yb) if sell_yb > 0 else 0
        except Exception:
            fee = 0
        try:
            brief = self.get_role_brief(seller_cid)
        except Exception:
            brief = None
        seller_name = (brief or {}).get('name') or seller_cid
        buyer_name = role.get('name') or cid
        _buyer_code, seller_code = self._booth_goods_codes(
            buyer_name, seller_name, sell, fee)
        try:
            buyer_booth = self.get_booth(cid)
        except Exception:
            buyer_booth = None
        if buyer_booth is None:
            buyer_booth = {'exists': False, 'jb': 0, 'yb': 0,
                           'buy_time': int(time.time() * 1000),
                           'created': int(time.time() * 1000)}
        else:
            try:
                buyer_booth = {
                    'exists': True,
                    'jb': int(buyer_booth.get('booth_jb') or 0),
                    'yb': int(buyer_booth.get('booth_yb') or 0)}
            except (TypeError, ValueError):
                buyer_booth = {'exists': True, 'jb': 0, 'yb': 0}
        try:
            settled = self.booth_buy_goods_tx(
                cid, sell_jb, sell_yb, item, stack, seller_cid, sell_id,
                sell_yb, sell_jb, fee, buyer_booth, sell_jb, sell_yb - fee,
                seller_code)
        except Exception:
            return None
        if settled == 'gone':
            return self._booth_err(CMD_BOOTH_BUY,
                                   BOOTH_ERR_GOODS_NO_IN_BOOTH)
        if settled == 'changed':
            return self._booth_err(CMD_BOOTH_BUY, BOOTH_ERR_CHANGE_REFRESH)
        if settled == 'full':
            return self._booth_err(CMD_BOOTH_BUY, BOOTH_ERR_BAG_SLOT)
        if settled != 'ok':
            if sell_jb > 0:
                return self._booth_err(CMD_BOOTH_BUY,
                                       BOOTH_ERR_JB_NOT_ENOUGH)
            return self._booth_err(CMD_BOOTH_BUY, BOOTH_ERR_YB_NOT_ENOUGH)
        try:
            if sell_jb:
                role['tongqian'] = self._booth_balance(role, 'YXB') - sell_jb
            if sell_yb:
                role['lingshi'] = self._booth_balance(role, 'YB') - sell_yb
        except Exception:
            pass
        try:
            new_jb = int(seller_booth.get('booth_jb') or 0) + sell_jb
            new_yb = int(seller_booth.get('booth_yb') or 0) + sell_yb - fee
        except (TypeError, ValueError):
            new_jb, new_yb = sell_jb, sell_yb - fee
        seller_frames = [frame(amf3_encode(
            [str(CMD_BOOTH_MONEY),
             [self._booth_money(new_jb), self._booth_money(new_yb)]]))]
        buyer_frames = self._booth_trade_exp_one(cid, role)
        seller_frames.extend(frame(amf3_encode(f))
                             for f in self._booth_trade_exp_one(seller_cid,
                                                               None))
        seller_frames.append(frame(amf3_encode(
            [str(CMD_BOOTH_SELL_NOTIFY), seller_code])))
        lead = self._booth_deliver_seller(seller_cid, cid, seller_frames)
        reply = [str(CMD_BOOTH_BUY),
                 [1, self.bag_goods_map(
                     role,
                     {'goods_id': item['goods_id'],
                      'bag_id': sell.get('id'),
                      'slot_num': 0,
                      'count': item['count'],
                      'bind': item['bind'],
                      'expire_time': item['expire_time'],
                      'item_level': item['item_level'],
                      'rare_level': item['rare_level'],
                      'attributes': item['attributes']}),
                  self._booth_money(sell_yb), self._booth_money(sell_jb),
                  sell_id, seller_cid]]
        return tuple(lead + buyer_frames +
                     [frame(amf3_encode(reply))])

    def booth_log(self):
        """Command 35109: own seller-view trade codes, newest first."""
        _role, cid = self._booth_self()
        if cid is None:
            return None
        try:
            codes = self.list_booth_trade_logs(cid) or []
        except Exception:
            codes = []
        return frame(amf3_encode([str(CMD_BOOTH_LOG), codes or None]))

    def booth_trade_log(self):
        """Command 35013: same seller log view as 35109."""
        _role, cid = self._booth_self()
        if cid is None:
            return None
        try:
            codes = self.list_booth_trade_logs(cid) or []
        except Exception:
            codes = []
        return frame(amf3_encode([str(CMD_BOOTH_TRADE_LOG), codes or None]))

    def booth_modify_name(self, msg):
        """Command 35110: rename the stall C> name."""
        role, cid = self._booth_self()
        if role is None:
            return None
        name = self.safe(msg, 1)
        if not name or not isinstance(name, str):
            return None
        if not check_role_name(name):
            return self._booth_err(CMD_BOOTH_NAME, BOOTH_ERR_NAME_NO_ALLOW)
        self._booth_ensure(cid)
        try:
            self.save_booth(cid, booth_name=name)
        except Exception:
            return None
        return frame(amf3_encode([str(CMD_BOOTH_NAME), [1, name]]))

    def _booth_money_sell(self, cmd, slot, money, no_exist_code, msg):
        """ybSell/jbSell: offer>0 lists or grows, 0 delists with a refund."""
        role, cid = self._booth_self()
        if role is None:
            return None
        args = self.safe(msg, 1, [])
        offered = self._booth_long(self.safe(args, 0))
        wanted = self._booth_long(self.safe(args, 1))
        if offered is None or offered < 0:
            return None
        if wanted is None or wanted <= 0:
            return None
        column = BAG_MONEY_COLUMNS[money]
        short_code = BOOTH_ERR_YB_NOT_ENOUGH if money == 'YB' \
            else BOOTH_ERR_JB_NOT_ENOUGH
        done = 'gone'
        for _attempt in range(2):
            self._booth_ensure(cid)
            try:
                sell = self.get_booth_sell_by_slot(cid, slot)
            except Exception:
                sell = None
            if offered > 0:
                if sell is not None:
                    try:
                        listed = int(sell.get('sell_yb') or 0) \
                            if slot == BOOTH_SLOT_YB \
                            else int(sell.get('sell_jb') or 0)
                    except (TypeError, ValueError):
                        listed = 0
                    if listed < offered and not self._booth_check(
                            role, money, offered - listed):
                        return self._booth_err(cmd, short_code)
                elif not self._booth_check(role, money, offered):
                    return self._booth_err(cmd, short_code)
            take, give, expect, record = 0, 0, None, None
            if sell is not None:
                try:
                    locked = int(sell.get('sell_yb') or 0) \
                        if slot == BOOTH_SLOT_YB \
                        else int(sell.get('sell_jb') or 0)
                except (TypeError, ValueError):
                    locked = 0
                if offered == 0:
                    give, expect = locked, sell.get('id')
                else:
                    diff = locked - offered
                    if diff > 0:
                        give = diff
                    elif diff < 0:
                        take = -diff
                    expect = sell.get('id')
                    record = dict(sell)
                    if slot == BOOTH_SLOT_YB:
                        record['sell_yb'] = offered
                        record['sell_jb'] = wanted
                    else:
                        record['sell_jb'] = offered
                        record['sell_yb'] = wanted
            else:
                if offered <= 0:
                    return self._booth_err(cmd, no_exist_code)
                take = offered
                record = {'id': f'bs{uuid.uuid4().hex[:16]}',
                          'goods_id': 'YB' if slot == BOOTH_SLOT_YB else 'JB',
                          'slot': slot,
                          'sell_jb': wanted if slot == BOOTH_SLOT_YB
                          else offered,
                          'sell_yb': offered if slot == BOOTH_SLOT_YB
                          else wanted,
                          'created': int(time.time() * 1000)}
            try:
                done = self.booth_money_position_tx(
                    cid, column, expect, take, give, record)
            except Exception:
                return None
            if done != 'gone' and done != 'changed':
                break
        if done == 'funds':
            return self._booth_err(cmd, short_code)
        if done != 'ok':
            return None
        try:
            role[column] = self._booth_balance(role, money) - take + give
        except Exception:
            pass
        if offered == 0:
            return frame(amf3_encode(
                [str(cmd), [1, self._booth_money(0),
                            self._booth_money(wanted)]]))
        return frame(amf3_encode(
            [str(cmd), [1, self._booth_money(offered),
                        self._booth_money(wanted)]]))

    def booth_yb_sell(self, msg):
        """Command 35111: offer YB for YXB C> [sellYb, sellJb]."""
        return self._booth_money_sell(CMD_BOOTH_YB_SELL, BOOTH_SLOT_YB,
                                      'YB', BOOTH_ERR_YB_SELL_NO_EXIST, msg)

    def booth_jb_sell(self, msg):
        """Command 35112: offer YXB for YB C> [sellJb, sellYb]."""
        return self._booth_money_sell(CMD_BOOTH_JB_SELL, BOOTH_SLOT_JB,
                                      'YXB', BOOTH_ERR_JB_SELL_NO_EXIST, msg)

    def _booth_money_buy(self, cmd, slot, yb_type, msg):
        """buySellYb/buySellJb: take the asking currency, credit the booth."""
        role, cid = self._booth_self()
        if role is None:
            return None
        args = self.safe(msg, 1, [])
        ref = self._booth_ref(self.safe(args, 0))
        first = self._booth_long(self.safe(args, 1))
        second = self._booth_long(self.safe(args, 2))
        if ref is None or first is None or second is None:
            return None
        seller_cid = self._booth_canonical(ref)
        if seller_cid is None:
            return None
        if self._booth_session_of(seller_cid) is None:
            return self._booth_err(cmd, BOOTH_ERR_SELL_ROLE_OFFLINE)
        try:
            sell = self.get_booth_sell_by_slot(seller_cid, slot)
        except Exception:
            sell = None
        if sell is None:
            if yb_type:
                return self._booth_err(cmd, BOOTH_ERR_CHANGE_REFRESH)
            return None
        try:
            listed_first = int(sell.get('sell_yb') or 0) if yb_type \
                else int(sell.get('sell_jb') or 0)
            listed_second = int(sell.get('sell_jb') or 0) if yb_type \
                else int(sell.get('sell_yb') or 0)
        except (TypeError, ValueError):
            listed_first, listed_second = 0, 0
        if listed_first != first or listed_second != second:
            # checkBuyJb mismatches answer changeRefresh like Yb; only a
            # missing listing stays silent (the 35114 action skips nulls).
            return self._booth_err(cmd, BOOTH_ERR_CHANGE_REFRESH)
        if cid == str(sell.get('role_id')):
            return self._booth_err(cmd, BOOTH_ERR_NO_BUY_SELF_GOODS)
        if self._booth_session_of(seller_cid) is None:
            return self._booth_err(cmd, BOOTH_ERR_SELL_ROLE_OFFLINE)
        if yb_type:
            pay_money, pay_amount = 'YXB', listed_second
            get_money, get_amount = 'YB', listed_first
        else:
            pay_money, pay_amount = 'YB', listed_second
            get_money, get_amount = 'YXB', listed_first
        if not self._booth_check(role, pay_money, pay_amount):
            if yb_type:
                return self._booth_err(cmd, BOOTH_ERR_JB_NOT_ENOUGH)
            return self._booth_err(cmd, BOOTH_ERR_SELL_YB_MAX)
        try:
            fee = 0 if yb_type else self._booth_fee(listed_second)
        except Exception:
            fee = 0
        try:
            brief = self.get_role_brief(seller_cid)
        except Exception:
            brief = None
        seller_name = (brief or {}).get('name') or seller_cid
        buyer_name = role.get('name') or cid
        buyer_code, seller_code = self._booth_money_codes(
            yb_type, buyer_name, seller_name, listed_first, listed_second,
            fee)
        pay_col = BAG_MONEY_COLUMNS[pay_money]
        get_jb = get_amount if get_money == 'YXB' else 0
        get_yb = get_amount if get_money == 'YB' else 0
        try:
            settled = self.booth_money_buy_tx(
                cid, pay_col, pay_amount, get_jb, get_yb, seller_cid, slot,
                listed_first, listed_second, yb_type, fee, seller_code)
        except Exception:
            return None
        if settled == 'gone':
            if yb_type:
                return self._booth_err(cmd, BOOTH_ERR_CHANGE_REFRESH)
            return None
        if settled == 'changed':
            return self._booth_err(cmd, BOOTH_ERR_CHANGE_REFRESH)
        if settled == 'funds':
            if yb_type:
                return self._booth_err(cmd, BOOTH_ERR_JB_NOT_ENOUGH)
            return self._booth_err(cmd, BOOTH_ERR_SELL_YB_MAX)
        if not isinstance(settled, tuple):
            return None
        _ok, new_buyer, new_seller = settled
        try:
            role[pay_col] = self._booth_balance(role, pay_money) - pay_amount
        except Exception:
            pass
        buyer_frames = [frame(amf3_encode(
            [str(CMD_BOOTH_MONEY),
             [self._booth_money(new_buyer[0]),
              self._booth_money(new_buyer[1])]]))]
        seller_frames = [frame(amf3_encode(
            [str(CMD_BOOTH_MONEY),
             [self._booth_money(new_seller[0]),
              self._booth_money(new_seller[1])]]))]
        seller_frames.append(frame(amf3_encode(
            [str(CMD_BOOTH_SELL_NOTIFY), seller_code])))
        lead = self._booth_deliver_seller(seller_cid, cid, seller_frames)
        reply = [str(cmd),
                 [1, seller_cid, *buyer_code.split(',')]]
        return tuple(buyer_frames + lead + [frame(amf3_encode(reply))])

    def booth_buy_yb(self, msg):
        """Command 35113: buy YB C> [sellerId, sellYb, sellJb]."""
        return self._booth_money_buy(CMD_BOOTH_BUY_YB, BOOTH_SLOT_YB,
                                      True, msg)

    def booth_buy_jb(self, msg):
        """Command 35114: buy YXB C> [sellerId, sellJb, sellYb]."""
        return self._booth_money_buy(CMD_BOOTH_BUY_JB, BOOTH_SLOT_JB,
                                      False, msg)

    def booth_money(self):
        """Command 35115: own collected balances [boothJb, boothYb]."""
        _role, cid = self._booth_self()
        if cid is None:
            return None
        booth = self._booth_ensure(cid)
        return frame(amf3_encode(
            [str(CMD_BOOTH_MONEY),
             [self._booth_money(booth.get('booth_jb')),
              self._booth_money(booth.get('booth_yb'))]]))

    def booth_money_claim(self):
        """Command 35116: collect balances C> nothing, reply [1, jb, yb]."""
        role, cid = self._booth_self()
        if role is None:
            return None
        try:
            take_jb, take_yb, found = self.booth_claim_tx(
                cid, BAG_MONEY_COLUMNS['YXB'], BAG_MONEY_COLUMNS['YB'])
        except Exception:
            return None
        if not found:
            return None
        try:
            if take_jb:
                role[BAG_MONEY_COLUMNS['YXB']] = \
                    self._booth_balance(role, 'YXB') + take_jb
            if take_yb:
                role[BAG_MONEY_COLUMNS['YB']] = \
                    self._booth_balance(role, 'YB') + take_yb
        except Exception:
            pass
        return frame(amf3_encode(
            [str(CMD_BOOTH_MONEY_CLAIM),
             [1, self._booth_money(take_jb),
              self._booth_money(take_yb)]]))

    # -- friends (FriendAction/FriendServiceImpl bytecode) --
    def _friend_self(self):
        """Requester role and canonical id: placed role, else first role."""
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        if self.stage_registry is not None:
            try:
                owned = self.stage_registry.roles_of(self)
            except Exception:
                owned = []
            if owned:
                role = _find_role(roles, owned[0])
                if role is not None:
                    return role, str(owned[0])
        role = roles[0] if roles else None
        if role is None:
            return None, None
        return role, str(role.get('id'))

    def _friend_target(self, ref):
        """Canonical id and brief for a wire role reference, or (None, None)."""
        try:
            brief = self.get_role_brief(ref)
        except Exception:
            brief = None
        if brief is None:
            return None, None
        return str(brief.get('id')), brief

    def _friend_online(self, cid):
        """Public online state: placed session or login presence."""
        if self.stage_registry is None:
            return False
        try:
            if self.stage_registry.session_of(cid) is not None:
                return True
            return self.stage_registry.presence_of(cid) is not None
        except Exception:
            return False

    def _friend_map(self, cid):
        """Stage map a role sits on, or None (getMapId null branch)."""
        if self.stage_registry is None:
            return None
        try:
            return self.stage_registry.map_of(cid)
        except Exception:
            return None

    def _friend_has_booth(self, cid):
        """Whether the role holds any stall listing (hasBooth cell)."""
        try:
            return bool(self.list_booth_sells(cid))
        except Exception:
            return False

    def _friend_xinqing(self, cid):
        """Mood text of a role, or None (missing FriendInfo row)."""
        try:
            info = self.get_friend_info(cid)
        except Exception:
            return None
        return (info or {}).get('xinqing')

    def _friend_vo(self, cid, type_id, count_a, order, brief=None):
        """FriendVoOutput 13-slot card: id/name/sex/face/mood/level/type/\n        online/job/mapId/count/order/stall."""
        if brief is None:
            try:
                brief = self.get_role_brief(cid)
            except Exception:
                brief = None
        brief = brief or {}
        try:
            online = (FRIEND_ONLINE_STATE if self._friend_online(cid)
                      else FRIEND_OFFLINE_STATE)
        except Exception:
            online = FRIEND_OFFLINE_STATE
        return [str(brief.get('id') if brief.get('id') is not None
                    else cid),
                brief.get('name'), brief.get('sex'), brief.get('face'),
                self._friend_xinqing(cid), brief.get('level'),
                type_id, online, brief.get('job'), self._friend_map(cid),
                count_a, order,
                bool(self._friend_has_booth(cid))]

    @staticmethod
    def _friend_err(cmd, payload):
        """FriendErrorCodeOutput shape: [0, code] plus any extra cells."""
        return frame(amf3_encode([str(cmd), [0, *payload]]))

    def _friend_push(self, cid, cmd, payload):
        """PublicMsgQueue flush to one role: live sessions get frames."""
        if self.stage_registry is None:
            return []
        try:
            sess = self.stage_registry.session_of(cid)
        except Exception:
            return []
        if sess is None:
            try:
                sess = self.stage_registry.presence_of(cid)
            except Exception:
                sess = None
        if sess is None:
            return []
        out = frame(amf3_encode([str(cmd), payload]))
        if sess is self:
            return [out]
        try:
            sess.push_frames([out])
        except Exception:
            pass
        return []

    def _friend_followers(self, cid, kinds=('friend', 'foe', 'contacts',
                                            'blacklist')):
        """Attention roles: owners listing cid, in Java's list order."""
        seen = []
        for kind in kinds:
            try:
                owners = self.follower_ids(kind, cid) or []
            except Exception:
                owners = []
            for owner in owners:
                if owner not in seen:
                    seen.append(str(owner))
        return seen

    def _friend_notify_followers(self, cid, cmd, payload,
                                 skip=None, online_only=True):
        """Fan one push out to every attention role; own frames join reply."""
        lead = []
        for owner in self._friend_followers(cid):
            if skip is not None and str(owner) == str(skip):
                continue
            if online_only and not self._friend_online(owner):
                continue
            lead.extend(self._friend_push(owner, cmd, payload))
        return lead

    def friend_info(self):
        """Command 51000: [count, mood, friends, foes, blacklist, contacts]."""
        _role, cid = self._friend_self()
        if cid is None:
            return None
        try:
            info = self.get_friend_info(cid)
        except Exception:
            info = None
        cards = []
        for kind, type_id in (('friend', FRIEND_TYPE_FRIEND),
                              ('foe', FRIEND_TYPE_FOE),
                              ('blacklist', FRIEND_TYPE_BLACKLIST),
                              ('contacts', FRIEND_TYPE_CONTACTS)):
            try:
                links = self.list_friend_links(kind, cid) or []
            except Exception:
                links = []
            group = []
            for link in links:
                target = str(link.get({
                    'friend': 'friend_id', 'foe': 'foe_id',
                    'blacklist': 'blacklist_id',
                    'contacts': 'contacts_id'}[kind]) or '')
                try:
                    count_a = int(link.get('foe_count') or 0) \
                        if kind == 'foe' else 0
                except (TypeError, ValueError):
                    count_a = 0
                try:
                    order = int(link.get('order_id') or 0)
                except (TypeError, ValueError):
                    order = 0
                group.append(self._friend_vo(target, type_id, count_a,
                                             order))
            cards.append(group)
        count = 0
        mood = None
        if info is not None:
            try:
                count = int(info.get('friend_count') or 0)
            except (TypeError, ValueError):
                count = 0
            mood = info.get('xinqing')
        return frame(amf3_encode([str(CMD_FRIEND_INFO),
                                 [count, mood, *cards]]))

    def _friend_add_link(self, kind, cmd, type_id, msg, cap,
                         self_code, missing_code, exists_code,
                         exists_blacklist_code, been_cmd):
        """Shared add flow: guards, directed row, count, notifies, card."""
        _role, cid = self._friend_self()
        if cid is None:
            return None
        ref = self.safe(msg, 1)
        if isinstance(ref, list):
            ref = ref[0] if ref else None
        if not ref or not isinstance(ref, str):
            return None
        target_cid, brief = self._friend_target(ref)
        if target_cid is None:
            return self._friend_err(cmd, [missing_code])
        if target_cid == cid:
            return self._friend_err(cmd, [self_code])
        try:
            links = self.list_friend_links(kind, cid) or []
        except Exception:
            links = []
        if len(links) >= cap:
            return self._friend_err(cmd, [FRIEND_ERR_COUNT_LIMIT
                                          if kind == 'friend' else
                                          FRIEND_ERR_FOE_COUNT_LIMIT,
                                          cap])
        try:
            dup = self.has_friend_link(kind, cid, target_cid)
        except Exception:
            dup = False
        if dup:
            return self._friend_err(cmd, [exists_code,
                                          (brief or {}).get('name')])
        if exists_blacklist_code is not None:
            try:
                blocked = self.has_friend_link('blacklist', cid,
                                               target_cid)
            except Exception:
                blocked = False
            if blocked:
                return self._friend_err(cmd, [exists_blacklist_code,
                                              (brief or {}).get('name')])
        try:
            added, _evicted = self.friend_add_tx(kind, cid, target_cid,
                                                 cap)
        except Exception:
            return None
        if not added:
            return self._friend_err(cmd, [exists_code,
                                          (brief or {}).get('name')])
        count = 0
        if kind == 'friend':
            try:
                count = self.friend_add_count_tx(target_cid)
            except Exception:
                count = 0
        lead = []
        if kind == 'friend':
            lead.extend(self._friend_push(target_cid, CMD_FRIEND_COUNT,
                                          count))
        if self._friend_online(target_cid):
            mine = self._friend_vo(cid, type_id, 0, 0)
            # Java sends the been-add card before computing hasBooth,
            # so its stall cell is always false.
            mine[12] = False
            lead.extend(self._friend_push(target_cid, been_cmd, mine))
        theirs = self._friend_vo(target_cid, type_id, 0, 0, brief)
        reply = [str(cmd), [1, theirs]]
        if lead:
            return (*lead, frame(amf3_encode(reply)))
        return frame(amf3_encode(reply))

    def friend_add(self, msg):
        """Command 51001: add a friend C> targetRoleId."""
        return self._friend_add_link('friend', CMD_FRIEND_ADD,
                                     FRIEND_TYPE_FRIEND, msg,
                                     FRIEND_MAX_COUNT, FRIEND_ERR_NOT_ADD,
                                     FRIEND_ERR_ROLE_NOT_EXISTS,
                                     FRIEND_ERR_EXISTS,
                                     FRIEND_ERR_EXISTS_BLACKLIST,
                                     CMD_FRIEND_BEEN_ADD)

    def foe_add(self, msg):
        """Command 51003: add a foe C> targetRoleId."""
        return self._friend_add_link('foe', CMD_FOE_ADD, FRIEND_TYPE_FOE,
                                     msg, FRIEND_MAX_COUNT,
                                     FRIEND_ERR_FOE_NOT_ADD,
                                     FRIEND_ERR_ROLE_NOT_EXISTS,
                                     FRIEND_ERR_FOE_EXISTS, None,
                                     CMD_FOE_BEEN_ADD)

    def _friend_del_link(self, kind, cmd, msg):
        """Shared removal: drop the directed row, answer [1, targetId]."""
        _role, cid = self._friend_self()
        if cid is None:
            return None
        ref = self.safe(msg, 1)
        if isinstance(ref, list):
            ref = ref[0] if ref else None
        if not ref or not isinstance(ref, str):
            return None
        target_cid, _brief = self._friend_target(ref)
        if target_cid is None:
            return None
        try:
            dropped = self.friend_del_tx(kind, cid, target_cid)
        except Exception:
            return None
        if not dropped:
            return None
        return frame(amf3_encode([str(cmd), [1, target_cid]]))

    def friend_del(self, msg):
        """Command 51002: remove a friend C> targetRoleId."""
        return self._friend_del_link('friend', CMD_FRIEND_DEL, msg)

    def foe_del(self, msg):
        """Command 51004: remove a foe C> targetRoleId."""
        return self._friend_del_link('foe', CMD_FOE_DEL, msg)

    def blacklist_del(self, msg):
        """Command 51006: unblock C> targetRoleId."""
        return self._friend_del_link('blacklist', CMD_BLACKLIST_DEL, msg)

    def contacts_del(self, msg):
        """Command 51008: drop a contact C> targetRoleId."""
        return self._friend_del_link('contacts', CMD_CONTACTS_DEL, msg)

    def _friend_capped_add(self, kind, cmd, type_id, msg, cap,
                           self_silent):
        """Blacklist/contact add: evict oldest past cap, answer card."""
        _role, cid = self._friend_self()
        if cid is None:
            return None
        ref = self.safe(msg, 1)
        if isinstance(ref, list):
            ref = ref[0] if ref else None
        if not ref or not isinstance(ref, str):
            return None
        target_cid, brief = self._friend_target(ref)
        if target_cid is None:
            if self_silent:
                return None
            return self._friend_err(cmd, [FRIEND_ERR_ROLE_NOT_EXISTS])
        if target_cid == cid:
            if self_silent:
                return None
            return self._friend_err(cmd, [FRIEND_ERR_BLACKLIST_NOT_ADD
                                          if kind == 'blacklist' else
                                          FRIEND_ERR_FOE_NOT_ADD])
        try:
            dup = self.has_friend_link(kind, cid, target_cid)
        except Exception:
            dup = False
        if dup:
            if self_silent:
                return None
            return self._friend_err(
                cmd, [FRIEND_ERR_BLACKLIST_EXISTS
                      if kind == 'blacklist' else FRIEND_ERR_FOE_NOT_ADD,
                      (brief or {}).get('name')])
        if kind == 'blacklist':
            try:
                is_friend = self.has_friend_link('friend', cid,
                                                 target_cid)
            except Exception:
                is_friend = False
            if is_friend:
                return self._friend_err(
                    cmd, [FRIEND_ERR_BLACKLIST_EXISTS_FRIEND,
                          (brief or {}).get('name')])
        try:
            added, evicted = self.friend_add_tx(kind, cid, target_cid,
                                                cap)
        except Exception:
            return None
        if not added:
            return None
        vo = self._friend_vo(target_cid, type_id, 0, 0, brief)
        if kind == 'blacklist':
            out = [frame(amf3_encode([str(cmd), [1, vo]]))]
            if evicted is not None:
                out.append(frame(amf3_encode(
                    [str(CMD_BLACKLIST_DEL),
                     [1, evicted.get('blacklist_id')]])))
            return out[0] if len(out) == 1 else tuple(out)
        out = frame(amf3_encode([str(cmd), vo]))
        if evicted is None:
            return out
        return (out, frame(amf3_encode(
            [str(CMD_CONTACTS_DEL), [1, evicted.get('contacts_id')]])))

    def blacklist_add(self, msg):
        """Command 51005: block C> targetRoleId (friend conflict rejects)."""
        return self._friend_capped_add('blacklist', CMD_BLACKLIST_ADD,
                                       FRIEND_TYPE_BLACKLIST, msg,
                                       FRIEND_MAX_COUNT, False)

    def contacts_add(self, msg):
        """Command 51007: add a contact C> targetRoleId."""
        return self._friend_capped_add('contacts', CMD_CONTACTS_ADD,
                                       FRIEND_TYPE_CONTACTS, msg,
                                       FRIEND_MAX_COUNT, True)

    def friend_xinqing(self, msg):
        """Command 51011: set mood C> text ([1, text] or [0, code, old])."""
        _role, cid = self._friend_self()
        if cid is None:
            return None
        text = self.safe(msg, 1)
        if not isinstance(text, str):
            return None
        try:
            info = self.get_friend_info(cid)
        except Exception:
            info = None
        old = (info or {}).get('xinqing') or ''
        if text == old:
            return frame(amf3_encode([str(CMD_FRIEND_XINQING), [1, text]]))
        if len(text) > FRIEND_XINQING_MAX:
            return self._friend_err(CMD_FRIEND_XINQING,
                                    [FRIEND_ERR_XINQING_MAX, old])
        if text != '' and not check_xinqing(text):
            return self._friend_err(CMD_FRIEND_XINQING,
                                    [FRIEND_ERR_XINQING_ILLEGAL, old])
        try:
            self.save_friend_info(cid, xinqing=text)
        except Exception:
            return None
        return frame(amf3_encode([str(CMD_FRIEND_XINQING), [1, text]]))

    def friend_fight(self, msg):
        """Command 51015: spar result C> [loserId, winnerId, mapId]."""
        _role, cid = self._friend_self()
        if cid is None:
            return None
        args = self.safe(msg, 1, [])
        if not isinstance(args, list) or len(args) < 3:
            return None
        loser_ref = args[0] if isinstance(args[0], str) else None
        winner_ref = args[1] if isinstance(args[1], str) else None
        map_id = args[2]
        if loser_ref is None or winner_ref is None:
            return None
        winner_cid, winner_brief = self._friend_target(winner_ref)
        loser_cid, loser_brief = self._friend_target(loser_ref)
        if winner_cid is None or loser_cid is None:
            return None
        lead = []
        try:
            has = self.has_friend_link('foe', winner_cid, loser_cid)
        except Exception:
            has = False
        if has:
            try:
                count = self.friend_touch_foe_tx(
                    winner_cid, loser_cid, 1, FRIEND_FOE_COUNT_MIN,
                    FRIEND_FOE_COUNT_MAX)
            except Exception:
                count = None
            if count is not None:
                lead.extend(self._friend_push(
                    winner_cid, CMD_FOE_COUNT,
                    [loser_cid, count, 1]))
        else:
            count = None
        try:
            back = self.has_friend_link('foe', loser_cid, winner_cid)
        except Exception:
            back = False
        if back:
            try:
                back_count = self.friend_touch_foe_tx(
                    loser_cid, winner_cid, -1, FRIEND_FOE_COUNT_MIN,
                    FRIEND_FOE_COUNT_MAX)
            except Exception:
                back_count = None
            if back_count is not None:
                lead.extend(self._friend_push(
                    loser_cid, CMD_FOE_COUNT,
                    [winner_cid, back_count, -1]))
        else:
            try:
                added, _evicted = self.friend_add_tx(
                    'foe', loser_cid, winner_cid, FRIEND_MAX_COUNT,
                    extra=-1)
            except Exception:
                added = False
            if added:
                card = self._friend_vo(winner_cid, FRIEND_TYPE_FOE, -1, 0,
                                       winner_brief)
                lead.extend(self._friend_push(
                    loser_cid, CMD_FOE_ADD, [1, card]))
        try:
            winner_triple = [winner_cid,
                             (winner_brief or {}).get('name'),
                             (winner_brief or {}).get('sex')]
            loser_triple = [loser_cid, (loser_brief or {}).get('name'),
                            (loser_brief or {}).get('sex')]
        except Exception:
            return tuple(lead) if lead else None
        for owner in self._friend_followers(winner_cid, ('friend',)):
            if owner == loser_cid:
                continue
            if self._friend_online(owner):
                lead.extend(self._friend_push(
                    owner, CMD_FRIEND_FIGHT,
                    [FRIEND_ERR_FIGHT_WIN, winner_triple, map_id,
                     loser_triple]))
        for owner in self._friend_followers(loser_cid, ('friend',)):
            if owner == winner_cid:
                continue
            if self._friend_online(owner):
                lead.extend(self._friend_push(
                    owner, CMD_FRIEND_FIGHT,
                    [FRIEND_ERR_FIGHT_FAIL, loser_triple, map_id,
                     winner_triple]))
        for owner in self._friend_followers(winner_cid, ('foe',)):
            if owner == loser_cid:
                continue
            if self._friend_online(owner):
                lead.extend(self._friend_push(
                    owner, CMD_FRIEND_FIGHT,
                    [FRIEND_ERR_FOE_FIGHT_WIN, winner_triple, map_id,
                     loser_triple]))
        for owner in self._friend_followers(loser_cid, ('foe',)):
            if owner == winner_cid:
                continue
            if self._friend_online(owner):
                lead.extend(self._friend_push(
                    owner, CMD_FRIEND_FIGHT,
                    [FRIEND_ERR_FOE_FIGHT_FAIL, loser_triple, map_id,
                     winner_triple]))
        return tuple(lead) if lead else None

    def _friend_on_enter(self, cid):
        """LoginInit: mark presence, tell online followers I'm online."""
        if self.stage_registry is not None:
            try:
                self.stage_registry.mark_online(cid, self)
            except Exception:
                pass
        return self._friend_notify_followers(
            cid, CMD_FRIEND_ONLINE, [cid, FRIEND_ONLINE_STATE])

    def _friend_on_disconnect(self):
        """RoleOffline: tell online followers I'm offline, drop presence."""
        if self.stage_registry is None:
            return []
        try:
            owned = self.stage_registry.roles_of(self)
        except Exception:
            return []
        lead = []
        for cid in owned:
            lead.extend(self._friend_notify_followers(
                cid, CMD_FRIEND_ONLINE, [cid, FRIEND_OFFLINE_STATE]))
            try:
                self.stage_registry.mark_offline(cid)
            except Exception:
                pass
        return lead

    def _friend_on_level(self, cid, level):
        """LevelUpgrade: [roleId, level, null, null] to every follower."""
        return self._friend_notify_followers(
            cid, CMD_FRIEND_ROLE_INFO, [cid, level, None, None],
            online_only=False)

    def _friend_on_map(self, cid, map_id):
        """ChangeMap: [roleId, -1, mapId, null] to online followers."""
        return self._friend_notify_followers(
            cid, CMD_FRIEND_ROLE_INFO, [cid, -1, map_id, None])

    def loading_stub(self, msg, cmd_num):
        """Post-21000 loading replies: exact fresh-role Java shapes.

        Captured from session-20261020-072313 (fu0 fresh level 8).
        Commands with no S>C reply in either Java capture (81000,
        40600, 53021, 82022, 130000, 101000, 73113, 75004) are
        fire-and-forget notifies: Java sends nothing, so we return
        None like Java instead of inventing a reply.
        """
        arg = self.safe(msg, 1)
        if isinstance(arg, list):
            arg0 = self.safe(arg, 0)
        else:
            arg0 = arg
        if cmd_num == 97001:
            try:
                page = int(arg0)
            except (TypeError, ValueError):
                page = 1
            if page not in (1, 2):
                page = 1
            return frame(amf3_encode(['97001', [page, 1396324799000.0, 0.0, [0, 0, 0, 0, 0], False, 0, 'xunbaonew.ani']]))
        if cmd_num == 114000:
            s = str(arg0)
            if s == '2':
                return frame(amf3_encode(['114000', [1, '2', 0, 0, ['jingyanyu02:1:1', 'jingyanyu03:1:1', 'ys010609:1:1:0:0|0:4', 'ys010610:1:1:0:0|0:4', 'zhenqipill_003:2:1', 'ningshendan01:2:1', 'zhenyuan:30:1', 'wuxing2:3:0', 'wuxing3:3:0', 'wuxing3:3:0', 'wuxing4:3:0', 'jingjie:10:1'], []]]))
            return frame(amf3_encode(['114000', [1, '1', 0, 0, ['xuangui_001:1:0', 'jinjiedan001:1:0', 'jinjiedan001:5:0', 'tongqian004:1:0', 'jinjiedan001:1:0', 'txbawang:1:0', 'xuangui_001:1:0', 'jinjiedan001:1:0', 'jinjiedan001:40:0', 'tongqian004:1:0', 'jinjiedan001:1:0', 'zuoqishuxing3:1:0'], [[1, 2, 20, ''], [10, 2, 190, ''], [50, 2, 900, '']]]]))
        payload = {
            53006: [None],
            51000: [[0, None, [], [], [], []]],
            82024: [None],
            74000: [[1, 0]],
            86000: [[0, 0, [], 0, None]],
            85000: [None],
            87000: [None],
            70500: [[]],
            91002: [['1', 0.0, '1', [], [['35', False, 0], ['36', 1, 0], ['33', 0, 0], ['34', 0, 0], ['39', 0, 0], ['37', 450], ['38', 0.0, 0.0, 0.0], ['43', False, 0], ['42', None], ['41', 0, 0], ['40', 0, 0], ['67', False, 0], ['66', 0, 0], ['69', False], ['68', 0, 0], ['22', 0, 0], ['23', False, 0], ['24', 0.0, 0], ['25', 1, 0], ['26', 34, 30], ['27', 0.0, 0.0], ['28', 0.0, 0.0, 0.0], ['29', 0, 0], ['3', 0.0, 0.0, 0.0], ['2', 34, 30], ['1', 0], ['7', 0, 0], ['30', 0, 0], ['6', 0, 0], ['5', 0.0, 0.0, 0.0], ['32', 0, 0], ['4', 0.0], ['31', 0.0], ['70', 450], ['71', 0, 0], ['9', False, 0], ['72', 0, 0], ['8', 0, 0], ['59', 0, 0], ['58', 0, 0], ['57', 0, 0], ['56', 0, 0], ['19', 0, 0], ['55', 0.0, 0], ['17', 0, 0], ['18', 0, 0], ['15', 0.0, 0.0, 0.0], ['16', 0, 0], ['13', 0.0, 0.0], ['14', 0.0, 0.0], ['11', False, 0], ['12', False], ['21', 0.0, 0.0, 0.0], ['20', 450], ['64', 0, 0], ['65', 0.0, 0.0], ['62', 450], ['63', 0, 0], ['60', 0, 0], ['61', 0, 0], ['49', 0.0, 0.0], ['48', 0, 0], ['45', 0, 0], ['44', 0.0, 0.0, 0.0], ['47', 0, 0], ['46', 0.0, 0], ['10', 1, 0], ['51', 0.0, 0.0], ['52', 450], ['53', 0, 0], ['54', 0.0, 0.0, 0.0], ['50', None]]]],
            90000: [[0, [['1', '0'], ['11', 2130]], []]],
            92015: [[None, [], None]],
            93000: [None],
            94000: [None],
            94002: [None],
            94100: [None],
            95000: [None],
            113000: [None],
            120100: [['db1a1b532903d4a0964771755d4ca6c6902d057451c42eff9d2ae217a1fc9ae2', [[10, None], [[10, ['fanpaika', 1]], [30, ['fanpaika', 3]], [50, ['fanpaika', 5]], [70, ['fanpaika', 7]], [90, ['fanpaika', 9]]], ['chip_baishu:1:1', 'jinglianshi:1:1', 'bsclbig:1:1', 'sj0208:1:1', 'sj0211:1:1', 'sj0217:1:1', 'zuoqishuxing3:1:1', 'zj0615:1:1:0:0|0:4:8|5,8|5,8|5,8|5,8|5,8|5', 'zj0616:1:1:0:0|0:4:9|5,9|5,9|5,9|5,9|5,9|5', 'ys010602:1:1:0:0|0:4', 'ys010604:1:1:0:0|0:4', 'ys010606:1:1:0:0|0:4', 'ys010608:1:1:0:0|0:4', 'ys010610:1:1:0:0|0:4', 'ys010611:1:1:0:0|0:4', 'ys010612:1:1:0:0|0:4', 'ys010613:1:1:0:0|0:4', 'ys010614:1:1:0:0|0:4'], None, 1394254801000.0, 1394510399000.0]]],
            124001: [None],
        }.get(int(cmd_num))
        if payload is None:
            return None
        return frame(amf3_encode([str(cmd_num), payload]))

    def create_role(self, msg):
        """Command 10002: reply ['10002', [1, role]] or ['10002', [0, code]].

        Request is [10002, [account, name, job, sex, face, flag, serverId, pid]]
        (captured live). Role and error shapes follow CreateRoleOutput and
        RoleErrorCode bytecode.
        """
        try:
            acct, name, job, sex, face, _flag, server_id = msg[1][:7]
        except (TypeError, ValueError):
            return frame(amf3_encode(['10002', [0, 2001]]))
        acct = self.authed_user or acct
        # Java has no 2003: bad names (including empty) are 2001 nameIllegal.
        if not check_role_name(name):
            return frame(amf3_encode(['10002', [0, 2001]]))
        if len(self.get_roles(acct, server_id)) >= MAX_ROLES_PER_ACCOUNT:
            return frame(amf3_encode(['10002', [0, 2005]]))
        role_id = self.create_role_cb(acct, server_id, name, job, sex, face)
        if role_id is None:
            return frame(amf3_encode(['10002', [0, 2002]]))
        role = [str(role_id), name, str(job), sex, 1, None, face]
        return frame(amf3_encode(['10002', [1, role]]))

    @staticmethod
    def role_info(r):
        """One role entry, byte-exact to GetRoleOutput.roleInfo(UserRole).

        The jar builds `new Object[8]` positionally; the client does
        `as Array` per entry (it threw AS3 #1034 "cannot convert Object to
        Array" when we sent objects), so this must stay an array:
          [0]=getId()  String   [1]=getName() String
          [2]=getJob() String   [3]=getSex()  Integer
          [4]=getLevel() Integer [5]=null (reserved)
          [6]=getFace() String   [7]=getCreateTime().getTime() Long(ms)
        Note id and job are Strings in the original, not ints.
        """
        return [
            _wire_id(r),
            r['name'],
            str(r['job']),
            r['sex'],
            r['level'],
            None,
            r.get('face') or '',
            int(r.get('created') or 0) * 1000,
        ]

    def safe(self, arr, i, default=None):
        try:
            return arr[i]
        except (IndexError, TypeError):
            return default

    def login(self, msg):
        data = msg[1] if len(msg) > 1 and isinstance(msg[1], list) else []
        user_id = str(self.safe(data, 0, '') or '').strip()
        ts_raw = self.safe(data, 1, 0)
        try:
            timestamp = str(int(float(ts_raw)))
        except (TypeError, ValueError):
            timestamp = ''
        server_id = str(self.safe(data, 2, '') or '')
        verify = str(self.safe(data, 4, '') or '')
        ok = self.check_sign(user_id, timestamp, verify)
        log.info('conn %d: login user=%r server=%r sign_ok=%s',
                 self.conn_id, user_id, server_id, ok)
        if ok:
            self.authed_user = user_id
            self.server_id = server_id
            role_rows = self.get_roles(user_id, server_id)
            roles = [self.role_info(r) for r in role_rows]
            # Slot 3 is a serialized java.util.TimeZone object, not a string:
            # ServerInfoVO.decode() reads `.rawOffset` off it. The capture is
            # a sealed `sun.util.calendar.ZoneInfo` with members rawOffset/ID
            # (session-20261018-195420.log); dynamic objects stall the client.
            tz = SealedObj({'rawOffset': self.tz_raw_offset, 'ID': self.tz_id},
                           cname='sun.util.calendar.ZoneInfo',
                           members=('rawOffset', 'ID'))
            # Slot 2 is the String `serverId + "-" + gsVersion` (IOServiceImpl.in
            # builds it from server-info.properties server_id and
            # version.properties; InOutput.success is static, so its first
            # argument is this string, not an InOutput instance).
            result = [1, [self.server_start_ms, int(time.time() * 1000),
                          GS_SIGNATURE, tz, bool(self.gm_open), None],
                      [0, 0], roles]
        else:
            result = [0, '16002']  # InOutput.signError shape
        env = ['10001', result]
        # Server->client is PLAINTEXT. The protocol is asymmetric:
        # AmfResponseEncoder.encode() only does putInt(len)+put(bytes) and
        # nothing in the jar ever calls SimpleEncrypt.encode() (the cipher is
        # referenced solely by AmfRequestDecoder). Encrypting this reply makes
        # the client try to parse ciphertext as AMF3 and abort the socketData
        # event with "Invalid object". Only client->server is enciphered.
        # The settings/currency bootstrap is NOT sent here: the Java captures
        # (session-20261018-040230, session-20261020-072313) show the 13000
        # and 32010 pushes arriving after the client sends 10003, just before
        # the 10003 reply. Pushing them with the login reply wedges the
        # client at a black screen (it never sends 21000). See enter_world.
        return frame(amf3_encode(env))

    def enter_world(self, msg):
        """Serve the role's persisted stage and basic role values."""
        role_id = str(self.safe(msg, 1, '') or '')
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = _find_role(roles, role_id)
        if role is None:
            try:
                idx = int(role_id)
            except ValueError:
                idx = None
            if idx is not None and 0 <= idx - 1 < len(roles):
                role = roles[idx - 1]
        if role is None:
            if len(roles) == 1:
                role = roles[0]
            else:
                log.warning('conn %d: enter_world unknown role %r (ignored)',
                            self.conn_id, role_id)
                return None
        log.info('conn %d: enter_world role=%r (%s)',
                 self.conn_id, role.get('name'), role_id)
        exp = role.get('exp') if role.get('exp') is not None else 0
        # StageControllOutputWrapper.login: [face, level, exp, sex, job,
        # isChenmi, chenmiAddOnlineTime, vipLevel, recharge[day, all],
        # gmState]. The exp Long serializes as an AMF3 double (1310 ->
        # 1310.0); vip comes from role_vip (0 when unmigrated); the
        # recharge pair reads unmigrated recharge rows, so [0.0, 0.0].
        try:
            vip = self.get_role_vip(role.get('id'))
        except Exception:
            vip = None
        try:
            vip_level = int((vip or {}).get('vip_level') or 0)
        except (TypeError, ValueError):
            vip_level = 0
        state = [role.get('face') or '', role.get('level', 1), float(exp),
                 role.get('sex', 0), str(role.get('job', '')),
                 False, 0, vip_level, [0.0, 0.0], 0]
        stage = [str(role.get('map_id') or '0'),
                 role.get('map_x') if role.get('map_x') is not None else 57,
                 role.get('map_y') if role.get('map_y') is not None else 148]
        result = [1, state, stage]
        # Java pushes the settings (13000) and currency (32010) bootstrap
        # after the client sends 10003, just before the 10003 reply — never
        # with the login reply (see login). Both captures agree on the order
        # [13000, 32010, 10003].
        bootstrap = ()
        if len(roles) == 1:
            role_id = str(role.get('id'))
            settings = self.get_role_settings(
                role_id, self.authed_user or '', self.server_id or '')
            setting_values = ([settings.get('quickbar_info'),
                               settings.get('panel_config'),
                               settings.get('ui_info'),
                               settings.get('guaji_info')]
                              if settings is not None else [None] * 4)
            bootstrap = (
                frame(amf3_encode(['13000', setting_values])),
                self.money_info(role),
            )
            try:
                self._juqing_on_enter(_wire_id(role))
            except Exception:
                pass
            try:
                self._zuwu_on_enter(_wire_id(role))
            except Exception:
                pass
            task_frames = []
            try:
                task_frames = self._task_on_enter(_wire_id(role)) or []
            except Exception:
                pass
            try:
                task_frames.extend(
                    self._friend_on_enter(_wire_id(role)) or [])
            except Exception:
                pass
            try:
                self._huodong_on_enter(_wire_id(role))
            except Exception:
                pass
            return (*bootstrap, *task_frames,
                    frame(amf3_encode(['10003', result])))

    def apply_stage(self, msg):
        role_id = str(self.safe(self.safe(msg, 1, []), 0, '') or '')
        target_map = str(self.safe(self.safe(msg, 1, []), 1, '') or '')
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = _find_role(roles, role_id)
        if role is None:
            return None
        map_id = target_map or str(role.get('map_id') or '0')
        x = role.get('map_x') if role.get('map_x') is not None else 57
        y = role.get('map_y') if role.get('map_y') is not None else 148
        # The client's requested stage is authoritative; persist it so a
        # reconnect/enter-world returns the role where it actually is.
        if target_map:
            self.save_role_state(role_id, map_id=map_id, map_x=x, map_y=y)
        try:
            before = self.stage_registry.map_of(_wire_id(role)) \
                if self.stage_registry is not None else None
        except Exception:
            before = None
        if self.stage_registry is not None:
            self.stage_registry.register(_wire_id(role), map_id, self,
                                         x=x, y=y)
        changed = []
        if before is not None and str(before) != str(map_id):
            try:
                changed = self._friend_on_map(_wire_id(role), map_id) \
                    or []
            except Exception:
                changed = []
        reply = frame(amf3_encode(['20000', [1, map_id, [x, y]]]))
        return (*changed, reply) if changed else reply

    def xianjie_id_for(self, stored):
        """Active xianjie id for a role_xianjiechenhao row, or None.

        Port of XianjiechenhaoServiceImpl.getXianjieId: missing row is
        null (the XIANJIE bag is cleared); an empty id array defaults to
        '1'; otherwise the string-maximum id wins (compareTo order).
        """
        if stored is None:
            return None
        try:
            ids = json.loads(stored.get('xianjie_id')) if stored.get('xianjie_id') else []
        except ValueError:
            log.warning('xianjie_id is not JSON: %r',
                        str(stored.get('xianjie_id'))[:80])
            return None
        if not isinstance(ids, list) or not ids:
            return '1'
        return max(str(i) for i in ids)

    def chenhao_ids_for(self, stored):
        """Chenghao id list for a role_xianjiechenhao row, or None.

        Port of XianjiechenhaoServiceImpl.chenHaoIds: missing row or
        empty array is null (the CHENGHAO bag is cleared); otherwise
        every id contributes its bag.
        """
        if stored is None:
            return None
        try:
            ids = json.loads(stored.get('chenhao_id')) if stored.get('chenhao_id') else []
        except ValueError:
            log.warning('chenhao_id is not JSON: %r',
                        str(stored.get('chenhao_id'))[:80])
            return None
        if not isinstance(ids, list) or not ids:
            return None
        return [str(i) for i in ids]

    def meiren_pairs_for(self, rows):
        """[(type, chanmian)] for role_meiren rows, skipping unlisted ids.

        Port of MeirenServiceImpl.getMeiRenAllObj: the business id is the
        config type (MeiRenConfig.getMeirenTypeId), rows without a config
        are dropped, and chanmianCount is meiren_heti (the level key
        replaceMeirenAttribute selects with).
        """
        pairs = []
        for row in rows or []:
            meiren_type = self.config.meiren_type_for(row.get('meiren_id'))
            if meiren_type is None:
                continue
            pairs.append((meiren_type, row.get('meiren_heti') or 0))
        return pairs

    def role_bags(self, role):
        """No-effect attribute bags for a role: gear, dan, xianjie,
        chenghao, meiren, baoshi and zuoqi.

        Port of RoleFactoryHelper's replace*Attribute sequence over the
        migrated role_equip / role_attribute_buff / role_xianjiechenhao /
        role_meiren / role_zuoqi rows; empty sources yield no bags,
        exactly Java's clear-and-skip behavior. The ZUOQI bag carries
        the replaceZuoqiAttribute goods loop over the role's
        attribute-goods map. The ZUOQI_SPEED bag stays empty: it needs
        rideOrNot, which decodeZuoQiInfo reads false from the stage blob
        at entry, so Java skips replaceZuoqiSudu too.
        """
        bags = []
        if self.config is None or role is None:
            return bags
        try:
            items = self.get_role_equip(role.get('id')) or []
        except Exception:
            items = []
        if items:
            bags.append(self.config.equip_attribute_map(items))
        try:
            buffs = self.get_role_attr_buffs(role.get('id')) or []
        except Exception:
            buffs = []
        ids = [b.get('attribute_id') for b in buffs if b.get('attribute_id')]
        if ids:
            bags.append(self.config.shuxingdan_attribute_map(ids))
        try:
            stored = self.get_role_xianjiechenhao(role.get('id'))
        except Exception:
            stored = None
        xianjie_id = self.xianjie_id_for(stored)
        if xianjie_id is not None:
            bags.append(self.config.xianjie_attribute_map(xianjie_id))
        chenhao_ids = self.chenhao_ids_for(stored)
        if chenhao_ids:
            bags.append(self.config.chenghao_attribute_map(chenhao_ids))
        try:
            owned = self.get_role_meiren(role.get('id')) or []
        except Exception:
            owned = []
        pairs = self.meiren_pairs_for(owned)
        if pairs:
            bags.append(self.config.meiren_attribute_map(pairs))
        try:
            stones = self.get_role_baoshi(role.get('id')) or []
        except Exception:
            stones = []
        if stones:
            bags.append(self.config.baoshi_attribute_map(stones))
        try:
            mount = self.get_role_zuoqi(role.get('id'))
        except Exception:
            mount = None
        if mount is not None:
            bags.append(self.config.zuoqi_effect_attribute_map(
                mount.get('zuoqi_rank'), role.get('level'),
                self._zuoqi_att_map(mount)))
        return [b for b in bags if b]

    def role_effect_slots(self, role):
        """Effect-slot map for a role: the VIP buff's slots.

        Port of replaceVipAttribute's BuffManager.addBuff: the vipbuff's
        XiaoGuoBiao effectpro cells become the numbered slots the
        formulas read. Roles without a VIP buff contribute nothing.
        """
        if role is None or self.config is None:
            return {}
        try:
            vip = self.get_role_vip(role.get('id'))
        except Exception:
            vip = None
        return self.config.vip_effect_slots((vip or {}).get('vip_level'))

    def role_attribute_map(self, role):
        """12000 map for a role: level row + bags + VIP effect slots."""
        if role is None or self.config is None:
            return None
        row = self.config.role_attribute_row(role.get('level'))
        if row is None:
            return None
        return entry_attribute_map(row, role.get('max_mp'),
                                   bags=self.role_bags(role),
                                   effect=self.role_effect_slots(role))

    def _owned_actor(self, actor_id):
        """Return the owned role dict when actor_id is a role or issued pet."""
        if not actor_id:
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = _find_role(roles, str(actor_id))
        if role is not None:
            return role
        if str(actor_id) in getattr(self, '_pet_ids', set()):
            return roles[0] if len(roles) == 1 else None
        return None

    def move(self, msg):
        """Legacy alias for tile_step; 42001 pixel moves never persist."""
        return self.skill_move(msg)

    def tile_step(self, msg):
        """Command 40000 [[x, y, a, b, actor]]: authoritative tile step."""
        args = self.safe(msg, 1, [])
        x, y = self.safe(args, 0), self.safe(args, 1)
        actor = self.safe(args, 4, '')
        if x is None or y is None or not actor:
            log.info('conn %d: tile step without coords/actor (ignored)', self.conn_id)
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = _find_role(roles, str(actor))
        if role is None:
            log.info('conn %d: tile step for unowned %r (ignored)', self.conn_id, actor)
            return None
        log.info('conn %d: tile role=%r -> (%s, %s)', self.conn_id, actor, x, y)
        old = [role.get('map_x'), role.get('map_y')]
        self.save_role_state(_wire_id(role), map_x=int(x), map_y=int(y))
        if self.stage_registry is not None:
            self.stage_registry.set_position(_wire_id(role), x, y)
        self._presence_aggro(role, int(x), int(y))
        frames = list(self._dazuo_cancel_frames(role) or ())
        enter = self._aoi_enter_frames(role, old, [int(x), int(y)])
        if enter is not None:
            frames.extend(enter)
        return tuple(frames) if frames else None

    def jump(self, msg):
        """Command 40001: log only; no Java reply captured."""
        log.info('conn %d: jump %r (logged, no reply)', self.conn_id, msg[1:2])
        return None

    def horn_chat(self, msg):
        """Command 11005: BagEasyAction.hornChat has an empty body, so log only."""
        log.info('conn %d: horn chat %r (logged, no reply)', self.conn_id, msg[1:2])
        return None

    def _chat_sender(self):
        """Role id and level of this connection's own role (first placed role), or (None, 0)."""
        if self.stage_registry is None:
            return None, 0
        owned = self.stage_registry.roles_of(self)
        if not owned:
            return None, 0
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = _find_role(roles, owned[0])
        return owned[0], int((role or {}).get('level') or 0)

    def normal_chat(self, msg):
        """Command 11000: level-gated chat broadcast to the 3x3 surround (chat log skipped)."""
        sender, level = self._chat_sender()
        data = self.safe(msg, 1, None)
        if sender is None or not isinstance(data, list) or self.config is None:
            return None
        if level < self.config.chat_level():
            return None
        out = self._dazuo_broadcast(sender, CMD_NORMAL_CHAT, data)
        return tuple(out) if out else None

    def area_chat(self, msg):
        """Command 10050: area broadcast [senderId, data] to the 3x3 surround."""
        sender, _ = self._chat_sender()
        data = self.safe(msg, 1, None)
        if sender is None:
            return None
        out = self._dazuo_broadcast(sender, CMD_AREA_CHAT, [sender, data])
        return tuple(out) if out else None

    def whisper(self, msg):
        """Command 10051: [targetRoleId, content] delivered to the target as [senderId, content]."""
        sender, _ = self._chat_sender()
        args = self.safe(msg, 1, None)
        if sender is None or not isinstance(args, list) or not args:
            return None
        target = str(args[0])
        content = args[1] if len(args) > 1 else None
        if self.stage_registry is None:
            return None
        target_sess = self.stage_registry.session_of(target)
        if target_sess is None:
            log.info('conn %d: whisper to offline role %r (silent)', self.conn_id, target)
            return None
        target_sess.push_frames([frame(amf3_encode([str(CMD_WHISPER), [sender, content]]))])
        return None

    def gift_code_use(self, msg):
        """Command 57000 stub: gift-code redeem is deferred, so log only and send no reply."""
        log.info('conn %d: gift code %r (stub, logged, no reply)', self.conn_id, msg[1:2])
        return None

    def teleport(self, msg):
        """Command 40100 C> [x, y, _, roleId]: move an owned role and echo to its new surround."""
        args = self.safe(msg, 1, None)
        if not isinstance(args, list) or len(args) < 4:
            log.info('conn %d: teleport without [x, y, _, roleId] (ignored)', self.conn_id)
            return None
        x, y = args[0], args[1]
        if not _is_int(x) or not _is_int(y):
            log.info('conn %d: teleport with non-int coords (ignored)', self.conn_id)
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = _find_role(roles, str(args[3] or ''))
        if role is None:
            log.info('conn %d: teleport for unowned %r (ignored)', self.conn_id, args[3])
            return None
        rid = _wire_id(role)
        self.save_role_state(rid, map_x=x, map_y=y)
        if self.stage_registry is not None:
            self.stage_registry.set_position(rid, x, y)
        frames = list(self._dazuo_cancel_frames(role) or ())
        frames.extend(self._dazuo_broadcast(rid, CMD_TELEPORT, args))
        return tuple(frames) if frames else None

    def change_map(self, rid, map_id, x, y):
        """Move a placed role to another map at (x, y): leave the old map, enter the new one.

        Collapses Java's SC:APPLY_CHANG_MAP and its client-ready commit into one step: the
        own-session frames are 20000 [1, mapId, [x, y]], 21000 and the monster snapshot. The
        old map's peers get no leave notice and the new map's peers no enter record (unported).
        """
        if self.stage_registry is not None:
            self.stage_registry.unregister(rid)
            self.stage_registry.register(rid, map_id, self, x=x, y=y)
        self.save_role_state(rid, map_id=map_id, map_x=x, map_y=y)
        frames = [frame(amf3_encode(['20000', [1, map_id, [x, y]]])),
                  frame(amf3_encode(['21000', [1, 1, self.map_type_for(map_id)]]))]
        if self.config is not None:
            npc_records = self.config.npc_snapshot(map_id, x, y)
            if npc_records:
                frames.append(frame(amf3_encode(['23003', npc_records])))
        snapshot = self.monster_snapshot_frame(map_id, x, y)
        if snapshot is not None:
            frames.append(snapshot)
        for item in self.ground_snapshot_items(map_id, x, y):
            frames.append(frame(amf3_encode(
                ['23004', [self.goods_msg_data(item, first_drop=0)]])))
        return frames

    def town_revive(self, msg):
        """Command 43001 (no args): living role echoes to its surround; a dead role resets HP/MP, then revives at its dead-map birth point (FightServiceImpl.townRevive).

        Cross-map revives move the role through change_map (one-step SC:APPLY_CHANG_MAP).
        """
        sender, _ = self._chat_sender()
        if sender is None or self.stage_registry is None:
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = _find_role(roles, sender)
        if role is None:
            return None
        rid = _wire_id(role)
        if rid not in self._dead:
            out = self._dazuo_broadcast(rid, CMD_TOWN_REVIVE, rid)
            return tuple(out) if out else None
        self._dead.discard(rid)
        max_hp = int(role.get('max_hp') or 0)
        max_mp = int(role.get('max_mp') or 0)
        self.save_role_state(rid, hp=max_hp, mp=max_mp)
        own = [frame(amf3_encode(['12004', [rid, max_hp, max_hp, max_mp, max_mp]]))]
        own += self._dazuo_broadcast(rid, CMD_TOWN_REVIVE, rid)
        birth = self.config.dead_birth(role.get('map_id')) if self.config else None
        if birth is None:
            log.info('conn %d: no revive config for map %r', self.conn_id, role.get('map_id'))
            return tuple(own)
        x, y = random.choice(birth['points'])
        if birth['map'] != str(role.get('map_id')):
            # Java queues SC:APPLY_CHANG_MAP, so the second 43001 still uses the old surround.
            own += self._dazuo_broadcast(rid, CMD_TOWN_REVIVE, rid)
            own += self.change_map(rid, birth['map'], x, y)
            return tuple(own)
        self.stage_registry.set_position(rid, x, y)
        self.save_role_state(rid, map_x=x, map_y=y)
        own += self._dazuo_broadcast(rid, CMD_TELEPORT, [x, y, 0, rid])
        own += self._dazuo_broadcast(rid, CMD_TOWN_REVIVE, rid)
        return tuple(own)

    def inner_fly(self, msg):
        """Command 40101 C> [_, mapId, x, y, stageId]: same-map moves teleport and echo [x, y, 0, roleId]; other maps change map in one step (RoleBehaviourServiceImpl.innerFly).

        stageId is validated but not looked up: the registry keys placed roles by map.
        """
        args = self.safe(msg, 1, None)
        if not isinstance(args, list) or len(args) < 5:
            log.info('conn %d: innerFly without [_, mapId, x, y, stageId] (ignored)', self.conn_id)
            return None
        map_id, x, y, stage_id = args[1], args[2], args[3], args[4]
        if (not isinstance(map_id, str) or not map_id or not _is_int(x) or not _is_int(y)
                or not isinstance(stage_id, str) or not stage_id):
            log.info('conn %d: innerFly with bad fields (ignored)', self.conn_id)
            return None
        sender, _ = self._chat_sender()
        if sender is None or self.stage_registry is None:
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = _find_role(roles, sender)
        if role is None:
            return None
        rid = _wire_id(role)
        if map_id != str(role.get('map_id') or ''):
            return self.change_map(rid, map_id, x, y)
        self.stage_registry.set_position(rid, x, y)
        self.save_role_state(rid, map_x=x, map_y=y)
        out = self._dazuo_broadcast(rid, CMD_INNER_FLY, [x, y, 0, rid])
        return tuple(out) if out else None

    def change_face(self, msg):
        """Command 40201: echo the client's facing payload to the 3x3 surround of the sender's role."""
        sender, _ = self._chat_sender()
        if sender is None or self.stage_registry is None:
            return None
        targets = self.stage_registry.surround(sender)
        if not targets:
            return None
        body = frame(amf3_encode([str(CMD_FACE), self.safe(msg, 1, None)]))
        own = []
        for _, sess in targets:
            if sess is self:
                own.append(body)
            else:
                sess.push_frames([body])
        return tuple(own) if own else None

    def skill_move(self, msg):
        """Command 42001 C> [actor, action, [px, py], [path], 1]."""
        args = self.safe(msg, 1, [])
        actor = str(self.safe(args, 0, '') or '')
        action = self.safe(args, 1, '')
        pos = self.safe(args, 2, None)
        path = self.safe(args, 3, None)
        flag = self.safe(args, 4, 1)
        if not actor or not isinstance(pos, list) or len(pos) < 2:
            log.info('conn %d: 42001 without actor/pos (ignored)', self.conn_id)
            return None
        if self._owned_actor(actor) is None:
            log.info('conn %d: 42001 for unowned %r (ignored)', self.conn_id, actor)
            return None
        log.info('conn %d: 42001 %r %r -> %r', self.conn_id, actor, action, pos)
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = _find_role(roles, str(actor))
        if role is not None and role.get('map_x') is not None:
            self._presence_aggro(role, int(role['map_x']), int(role['map_y']))
        echo = frame(amf3_encode(['42001', [1, actor, action, pos, path, flag, None]]))
        cancel = self._dazuo_cancel_frames(role) if role is not None else None
        if cancel is None:
            return echo
        return tuple(list(cancel) + [echo])

    def _stage_fighter(self, fighter_id):
        """Resolve a combat actor/target to a fighter dict, or None.

        Roles come from the store (fresh HP/exp every swing); monsters parse
        as m_<map>_<n> snapshot ids with template stats; pets come from the
        entry registry. Unknown ids return None instead of invented stats.
        """
        fid = str(fighter_id or '')
        if not fid:
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = _find_role(roles, fid)
        if role is None:
            role = self._registry_role(fid)
        if role is not None:
            return {'kind': 'role', 'id': _wire_id(role), 'role': role}
        pet = self._pet_state.get(fid)
        if pet is not None:
            return {'kind': 'pet', 'id': fid, **pet}
        reg = self._monster_reg.get(fid)
        if reg is not None:
            return {'kind': 'monster', 'id': fid, 'template': reg['template']}
        parts = fid.split('_')
        if len(parts) == 3 and parts[0] == 'm' and self.config is not None:
            # Match by id: the snapshot list is AOI-filtered, so list position is not
            # the spawn index. Unfiltered records give the stable spawn identity.
            rec = next((r for r in self.config.monster_snapshot(parts[1])
                        if r[0] == fid), None)
            if rec is not None:
                tpl = self.config.monster_template(rec[1])
                if tpl is not None:
                    hp = self._monster_hp.setdefault(
                        fid, float(rec[4] if rec[4] is not None else 0))
                    self._monster_reg.setdefault(fid, {
                        'template': tpl, 'map': parts[1],
                        'born': [rec[11], rec[12]], 'pos': [rec[11], rec[12]]})
                    return {'kind': 'monster', 'id': fid, 'template': tpl,
                            'record': rec, 'hp': hp}
        return None

    def _registry_role(self, role_id):
        """Role record owned by another session on the shared registry, or None.

        Monster AI steps in whichever session claims the round, so a target may
        belong to a different connection. The owner re-reads its own roles from
        the store, so HP, position and map are current. None when the role is not
        placed or its owner is this session.
        """
        if self.stage_registry is None:
            return None
        owner = self.stage_registry.session_of(role_id)
        if owner is None or owner is self:
            return None
        return _find_role(
            owner.get_roles(owner.authed_user or '', owner.server_id or ''),
            str(role_id))

    def _fighter_attrs(self, fighter):
        """combat.lib attribute dict for a fighter.

        Roles read the live 12000 map (wuli '2', fangyu '3', baoji '4',
        shanbi '5'); monsters read GuaiWuBiao (physicdamage/physicdefence/
        critical/volt -- volt feeds the T8 dodge odds, the same mapping the
        role formula uses); pets use their entry stats. Effect attributes,
        elementals, shishen, damage/defence, pojia/qiege stay 0: their
        sources (buffs, gear tables) are unmigrated, which is Java's
        empty-source default.
        """
        if fighter['kind'] == 'role':
            role = fighter['role']
            attrs = self.role_attribute_map(role) or {}
            return {'wuli': float(attrs.get('2') or 0.0),
                    'fangyu': float(attrs.get('3') or 0.0),
                    'baoji': float(attrs.get('4') or 0.0),
                    'shanbi': float(attrs.get('5') or 0.0),
                    'level': int(role.get('level') or 0),
                    'max_hp': float(role.get('max_hp') or 0.0),
                    'is_role': True, 'is_monster': False}
        if fighter['kind'] == 'monster':
            tpl = fighter['template']
            hp = float(tpl.get('hitpoints') or 0)
            return {'wuli': float(tpl.get('physicdamage') or 0),
                    'fangyu': float(tpl.get('physicdefence') or 0),
                    'baoji': float(tpl.get('critical') or 0),
                    'shanbi': float(tpl.get('volt') or 0),
                    'level': int(tpl.get('level') or 0),
                    'max_hp': hp,
                    'is_role': False, 'is_monster': True}
        return {'wuli': 0.0, 'fangyu': 0.0, 'baoji': 0.0, 'shanbi': 0.0,
                'level': int(fighter.get('level') or 0),
                'max_hp': float(fighter.get('max_hp') or 0.0),
                'is_role': False, 'is_monster': False}

    def _fighter_hp(self, fighter):
        """Current HP and max HP for a fighter (live values, floats)."""
        if fighter['kind'] == 'role':
            role = fighter['role']
            return (float(role.get('hp') or 0.0), float(role.get('max_hp') or 0.0),
                    float(role.get('mp') or 0.0), float(role.get('max_mp') or 0.0))
        if fighter['kind'] == 'monster':
            tpl = fighter['template']
            max_hp = float(tpl.get('hitpoints') or 0)
            max_mp = float(tpl.get('mana') or 0)
            return self._monster_hp.get(fighter['id'], max_hp), max_hp, max_mp, max_mp
        max_hp = float(fighter.get('max_hp') or 0.0)
        return float(fighter.get('hp', max_hp)), max_hp, 0.0, 0.0

    def _store_fighter_hp(self, fighter, new_hp):
        """Persist HP after acceptHarm (roles) or stage state (pets/monsters)."""
        new_hp = max(0.0, float(new_hp))
        if fighter['kind'] == 'role':
            self.save_role_state(fighter['id'], hp=int(new_hp))
        elif fighter['kind'] == 'monster':
            self._monster_hp[fighter['id']] = new_hp
        else:
            pet = self._pet_state[fighter['id']]
            pet['hp'] = new_hp
            if str(pet.get('template_id', '')).startswith('zuoqi'):
                owner = pet.get('owner')
                if new_hp <= 0:
                    # ZuoQiPet deadHandle + syncDeadZuoQiAttribute: the
                    # death stamps deadTime now and zeroes useTime; the
                    # ledger feeds the 3302x revive family and the persist.
                    now = int(time.time() * 1000)
                    try:
                        self._zuoqi_dead[str(owner)] = [now, 0]
                    except Exception:
                        pass
                    self._persist_mount_hp(owner, new_hp, now, 0)
                else:
                    self._persist_mount_hp(owner, new_hp)
        return new_hp

    def _persist_mount_hp(self, owner_id, hp, dead_ms=None, use_ms=0):
        """Write a mount's HP into its owner's role_stage.zuoqi_info.

        The next scene entry reads it back (23009 record, skipped at 0), so a
        hit survives a reconnect. Owners without a stored mount are skipped.
        dead_ms/use_ms persist raw like ZuoQiBussinessData (the next
        session's first revive read applies decodeZuoQiInfo's rule); None
        leaves a previous death record untouched, since only death stamps
        it and only revive zeroes it.
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = _find_role(roles, owner_id)
        if role is None:
            return
        info = decode_zuoqi_info(role.get('zuoqi_info'))
        if info is None:
            return
        info['hp'] = int(round(hp))
        if dead_ms is not None:
            info['deadTime'] = int(dead_ms)
            info['useTime'] = int(use_ms)
        # role_stage is keyed by the local row id, not the wire id.
        self.save_role_stage(role['id'], zuoqi_info=json.dumps(info))

    def _kill_exp_frames(self, killer, dead_fighter):
        """12001 + 12030 after a role-credited kill (AiServiceImpl.monsterExpDrop).

        Only monster deaths credit exp, and only to roles (pet kills credit
        the owner). Bonuses Java layers on top (exp-fold items, guild, VIP,
        events, ewai odds) live in unmigrated tables and default to 0, so a
        plain kill pays the table base; the captured +51 includes the role's
        exp-fold buffs and is noted, not faked.
        """
        if dead_fighter['kind'] != 'monster':
            return []
        owner = killer
        if killer['kind'] == 'pet':
            roles = self.get_roles(self.authed_user or '', self.server_id or '')
            owner_role = _find_role(roles, killer.get('owner'))
            if owner_role is None:
                return []
            owner = {'kind': 'role', 'id': _wire_id(owner_role), 'role': owner_role}
        if owner['kind'] != 'role':
            return []
        role = owner['role']
        tpl = dead_fighter['template']
        # TaskPublicServiceImpl.changeTaskMonster fan-out: main, taofa,
        # richang (the isOnline gate holds: the killer is online).
        task_frames = self.task_kill_progress(role, tpl.get('id'))
        task_frames = task_frames + self.taofa_kill_progress(
            role, tpl.get('id'))
        task_frames = task_frames + self.richang_kill_progress(
            role, tpl.get('id'))
        task_frames = task_frames + self.gonghui_kill_progress(
            role, tpl.get('id'))
        lv_diff = max(int(role.get('level') or 0) - int(tpl.get('level') or 0), 0)
        revise = (self.config.exp_revise(100, solo=True)
                  if self.config is not None else None)
        decay = (self.config.exp_decay(lv_diff)
                 if self.config is not None else None)
        if revise is None or decay is None:
            log.info('conn %d: no exp tables for %r (no 12001/12030)',
                     self.conn_id, dead_fighter['id'])
            return task_frames
        base = combat_lib.base_kill_exp(tpl.get('basicexp') or 0,
                                        xiuZheng=revise, levelXishu=decay)
        granted = combat_lib.fight_exp_with_bonuses(base)
        _total, _level, _gained, exp_frames = self._role_gain_exp(
            role, owner['id'], granted)
        return exp_frames + [frame(amf3_encode(combat_lib.exp_drop_frame(
            dead_fighter['id'], tpl.get('id'), granted)))] + task_frames

    def _resolve_fire(self, actor, action, index, target_ids, arg4, arg5):
        """SkillProcessHelper.fight + changeOutput burst for one swing.

        Shared by client-relayed 42002, pet auto-fire and monster AI ticks:
        per target resolve_hit, acceptHarm persist, the 12004/42100x2/43000
        burst, then the single 42002 broadcast plus 12001+12030 per kill.
        Role/pet swings also plant MonsterHatredManager hatred; monster
        deaths schedule the asheslast 24002 leave. Returns the frame list
        (empty when nothing was hit)."""
        skill = self.config.skill_row(action) if self.config is not None else None
        if skill is None:
            log.info('conn %d: 42002 unknown skill %r (ignored)',
                     self.conn_id, action)
            return []
        att = self._fighter_attrs(actor)
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = 0
        frames = []
        hits = []
        for target_id in target_ids:
            target = self._stage_fighter(str(target_id))
            if target is None or str(target_id) in self._dead:
                log.info('conn %d: 42002 target %r unknown/dead (skipped)',
                         self.conn_id, target_id)
                continue
            tgt = self._fighter_attrs(target)
            harm_val, harm_type = combat_lib.resolve_hit(att, tgt, skill)
            cur_hp, max_hp, cur_mp, max_mp = self._fighter_hp(target)
            dead = False
            if harm_val > 0:
                # acceptHarm: curHp -= val, clamped at 0; death follows.
                new_hp = self._store_fighter_hp(target, cur_hp - harm_val)
                dead = new_hp <= 0
                frames.append(frame(amf3_encode(combat_lib.hp_changed_frame(
                    target['id'], new_hp, max_hp, cur_mp, max_mp))))
            frames.append(frame(amf3_encode(
                combat_lib.buff_flush_frame(target['id']))))
            frames.append(frame(amf3_encode(
                combat_lib.buff_flush_frame(actor['id']))))
            if target['kind'] == 'role' and harm_val > 0:
                cancel = self._dazuo_cancel_frames(target['role'])
                if cancel is not None:
                    frames.extend(cancel)
            if (actor['kind'] in ('role', 'pet')
                    and target['kind'] == 'monster' and not dead):
                # fireAttackedEvent -> MonsterHatredManager: the monster
                # retaliates on the next AI tick.
                self._hatred[target['id']] = actor['id']
            if dead:
                self._dead.add(target['id'])
                self._hatred.pop(target['id'], None)
                if target['kind'] == 'monster':
                    self._schedule_leave(target)
                    frames.extend(self._record_drop_result(target, actor)
                                  or [])
                    frames.extend(self._juqing_kill_frames(actor, target))
                    frames.extend(self._zuwu_kill_frames(actor, target))
                if target['kind'] == 'role':
                    try:
                        self._juqing_death_progress(target.get('role'))
                    except Exception:
                        pass
                if actor['kind'] == 'pet':
                    frames.append(frame(amf3_encode(combat_lib.dead_notice(
                        target['id'], actor['id'], actor.get('name'), action,
                        owner_id=actor.get('owner'),
                        owner_name=actor.get('owner_name'),
                        attacker_name_full=actor.get('name')))))
                else:
                    frames.append(frame(amf3_encode(combat_lib.dead_notice(
                        target['id'], actor['id'],
                        self._fighter_name(actor), action))))
            hits.append(combat_lib.hit_record(target['id'], harm_type,
                                              harm_val, dead))
        if not hits:
            return []
        frames.append(frame(amf3_encode(combat_lib.skill_fire_frame(
            actor['id'], str(action), index, hits, arg4, arg5))))
        for hit, target_id in zip(hits, [str(t) for t in target_ids]):
            if hit[3]:
                target = self._stage_fighter(target_id)
                if target is not None:
                    frames.extend(self._kill_exp_frames(actor, target))
        return frames

    def skill_fire(self, msg):
        """Command 42002 C> [actor, action, index, [targets], arg4, arg5].

        Ports FightServiceImpl.skillFire over the client-relayed combat the
        capture proves (role, pet and monster actors each echo 1:1): resolve
        the fighter and skill (unknowns are ignored, never invented), run
        SkillProcessHelper.fight via _resolve_fire, then let the owner's pet
        auto-fire at the same monsters (PetFightServiceImpl.skillExecute).
        Monster retaliation is NOT inline here; it fires on ai_tick, which
        handle() runs after every 42002.
        """
        args = self.safe(msg, 1, [])
        actor_id = str(self.safe(args, 0, '') or '')
        action = self.safe(args, 1, '')
        index = self.safe(args, 2, 0) or 0
        targets = self.safe(args, 3, []) or []
        arg4 = self.safe(args, 4, None)
        arg5 = self.safe(args, 5, 1)
        if not actor_id:
            log.info('conn %d: 42002 without actor (ignored)', self.conn_id)
            return None
        actor = self._stage_fighter(actor_id)
        if actor is None:
            log.info('conn %d: 42002 for unknown %r (ignored)',
                     self.conn_id, actor_id)
            return None
        if actor_id in self._dead:
            log.info('conn %d: 42002 from dead %r (ignored)',
                     self.conn_id, actor_id)
            return None
        cancel = None
        if actor['kind'] == 'role':
            cancel = self._dazuo_cancel_frames(actor['role'])
        frames = list(cancel or ()) + self._resolve_fire(actor, action, index, targets, arg4, arg5)
        if not frames:
            return None
        if actor['kind'] == 'role':
            frames.extend(self._pet_auto_fire(actor, targets))
        return tuple(frames)

    def _pet_auto_fire(self, role_fighter, target_ids):
        """Pet mirrors its owner's swing (PetFightServiceImpl.skillExecute).

        Each live pet of the role fires zuoqi11 at the swing's surviving
        monster targets, preceded by its 42001 skillReady. No pet, no valid
        target, or no skill row -> silence, never invention."""
        frames = []
        targets = [str(t) for t in target_ids or []]
        for pet_id, pet in self._pet_state.items():
            if pet.get('owner') != role_fighter['id']:
                continue
            if pet_id in self._dead:
                continue
            prey = [t for t in targets
                    if t not in self._dead
                    and self._stage_fighter(t) is not None
                    and self._stage_fighter(t)['kind'] == 'monster']
            if not prey:
                continue
            pos = pet.get('pos')
            first = self._stage_fighter(prey[0])
            first_pos = self._fighter_pos(first)
            if pos is None or first_pos is None:
                continue
            pixel = ai_lib.tile_to_pixel(pos)
            dest = ai_lib.tile_to_pixel(first_pos)
            import math
            angle = math.atan2(dest[1] - pixel[1], dest[0] - pixel[0])
            self._ai_seq += 1
            path = [[dest[0], dest[1], angle, 0, self._ai_seq]]
            frames.append(frame(amf3_encode(ai_lib.skill_ready_frame(
                pet_id, ai_lib.PET_SKILL, pixel, path, None))))
            fighter = {'kind': 'pet', 'id': pet_id, **pet}
            frames.extend(self._resolve_fire(fighter, ai_lib.PET_SKILL, 0,
                                             prey, None, 1))
        return frames

    def _fighter_name(self, fighter):
        """Display name for 43000 kill notices."""
        if fighter['kind'] == 'role':
            return fighter['role'].get('name')
        if fighter['kind'] == 'monster':
            return fighter['template'].get('name')
        return fighter.get('name')

    def _fighter_pos(self, fighter):
        """Live tile position of a fighter, or None when unknown."""
        if fighter['kind'] == 'role':
            role = fighter['role']
            if role.get('map_x') is None or role.get('map_y') is None:
                return None
            return [int(role['map_x']), int(role['map_y'])]
        if fighter['kind'] == 'monster':
            reg = self._monster_reg.get(fighter['id'])
            return list(reg['pos']) if reg is not None else None
        pos = fighter.get('pos')
        return list(pos) if pos is not None else None

    def _record_drop_result(self, dead_monster, killer):
        """Evaluate a monster's direct-item drops once, at its authoritative death.

        Results are kept on the shared world as structured records. The
        monster id is marked in drop_done, so a repeat hit on the corpse adds nothing.
        Returns this session's own 23004 appearance copies from placement.
        """
        mid = dead_monster['id']
        if mid in self._world.drop_done or self.config is None:
            return
        self._world.drop_done.add(mid)
        if killer.get('kind') != 'role':
            return
        role = killer['role']
        template = dead_monster['template']
        level_diff = self.config.drop_level_difference(template.get('monstertype'))
        if level_diff is None:
            results = [{'outcome': loot_lib.OUTCOME_UNSUPPORTED, 'slot': None,
                        'goods_id': None, 'count': 0,
                        'reason': 'DiaoLuoShuaiJianBiao row missing'}]
        else:
            results = []
            for slot in loot_lib.direct_slots(template):
                results.append(loot_lib.evaluate_direct_drop(
                    template, slot, role_level=role.get('level') or 0,
                    level_difference=level_diff,
                    daily_limit=loot_lib.daily_limit_applies(
                        template.get('countlimit'),
                        self.config.goods_count(slot['goods_id'])),
                    roll=random.randrange(loot_lib.LOTTERY_TENTHOUSAND)))
        self._world.drop_results[mid] = results
        return self._place_ground_items(dead_monster, role, results)

    def _world_now_ms(self):
        """Server clock for ground-item creation and expiry; patchable in tests."""
        return int(time.time() * 1000)

    def _place_ground_items(self, dead_monster, role, results):
        """Create one shared ground item per supported successful drop.

        Placement follows AoiStage.getSurroundValidPoint(point, true, GOODS): the
        monster tile when free, else the first free surround, else nothing when
        the tile has no path node (Java logs and skips the item). The whole
        drop is owner-protected (formatDrop's constant 1): the killer owns it
        and the killer's team shares it; a null team stays null, as in Java.
        Lifetime is the template's dropitemlast in seconds. Each item is
        announced as 23004 [msgData] to its 3x3 AOI (AoiMsgListener enter
        for GOODS, payload Goods.getMsgData); this session's own copies
        are returned so the killer's swing carries them, peers are pushed.
        """
        store = self._world.ground_items
        if store is None or self.config is None:
            return []
        own = []
        template = dead_monster.get('template') or {}
        duration = self.config.drop_goods_duration(template)
        reg = self._monster_reg.get(dead_monster['id']) or {}
        map_id = reg.get('map') or self._mid_map(dead_monster['id'])
        pos = reg.get('pos') or (0, 0)
        now_ms = self._world_now_ms()
        for result in results:
            if result['outcome'] != loot_lib.OUTCOME_DROPPED:
                continue
            occupied = {(i.x, i.y) for i in store.on_map(map_id)}
            point = self.config.surround_valid_point_for_goods(
                map_id, int(pos[0]), int(pos[1]), occupied)
            if point is None:
                result['point'] = None
                continue
            # bind 0: drop2sp carries no bind marker (MonsterConfigExport-
            # ServiceImpl.createRule sets isBind only on the bind marker),
            # and hpadd002's obtainLocked is 0, so ItemCreatorServiceImpl
            # .getBind yields 0 and calGoodsExpireTime yields 0 (duration 0).
            item = store.add(result['goods_id'], result['count'], map_id,
                             int(point[0]), int(point[1]), now_ms,
                             owner_id=str(role.get('id')),
                             owner_team_id=None,  # Python roles carry no team id yet
                             duration_seconds=duration, bind=0)
            result['point'] = (item.x, item.y)
            own.extend(self._point_broadcast(
                map_id, (item.x, item.y), '23004',
                [self.goods_msg_data(item)]))
        return own

    def goods_msg_data(self, item, first_drop=1):
        """Goods.getMsgData 13-field array for one ground item.

        [x, y, goodsId, name, itemId, rareLevel, count, ownerId,
        ownTeamId, dropTimeMs, itemLevel, firstDrop, displayName].
        Fresh drops report firstDrop 1: AOI.add notifies the listener
        before AbsAoiStage.addHandle runs enterStageHandle, which is what
        clears the flag. Snapshots of settled items pass 0.
        """
        return [int(item.x), int(item.y), str(item.goods_id),
                self.config.goods_name(item.goods_id), str(item.id),
                int(self.config.goods_rarelevel(item.goods_id)),
                int(item.count or 0), item.owner_id, item.owner_team_id,
                int(item.drop_time_ms),
                int(self.config.goods_item_level(item.goods_id)),
                int(first_drop),
                int(self.config.goods_display_name(item.goods_id))]

    def pickup_goods(self, msg):
        """Command 30103: RoleBehaviourAction.pickUp -> goodsPickUp -> 30103.

        C> [itemId string]. Replies [0] when the item is gone, expired,
        on another map, owner-protected, or the bag cannot hold it;
        [1, goodsId, count, itemId] on success with the 30105/30104 bag
        pushes (BagExportServiceImpl.notifyClient order: adds, then
        updates). Money ground items have no producer (moneyDropCal is
        unported), so they answer [0] and stay on the ground.
        """
        args = self.safe(msg, 1, []) or []
        if not args or not isinstance(args[0], str):
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        _ok, frames = self.pickup_item(role, args[0])
        return frames

    def pickup_item(self, role, item_id, now_ms=None):
        """RoleBehaviourServiceImpl.goodsPickUp for one ground item.

        Order mirrors Java: element lookup, checkIdentity, money branch,
        checkPutInBag1, stage.leave, putInBag1(true). Here the leave is the
        atomic store.remove claim, so a failed bag write restores the
        item instead of destroying it. Returns (ok, frames); frames[0] is
        the 30103 reply, followed by any 30105/30104 bag pushes.
        No distance, alive or expiry pre-check exists in Java beyond the
        leave itself: a missing/expired element answers [0], and roles
        pick up on their own stage only (here: the item's map must match
        the role's map).
        """
        now = now_ms if now_ms is not None else self._world_now_ms()
        store = self._world.ground_items
        fail = (False, (frame(amf3_encode(['30103', [0]])),))
        if store is None or self.config is None or role is None:
            return fail
        item = store.get(item_id)
        if item is None:
            return fail
        if now >= item.expires_at_ms:
            # The S:GOODS_DIS leave already fired (or would have): gone.
            store.remove(item_id)
            return fail
        if str(role.get('map_id')) != str(item.map_id):
            return fail
        if item.goods_id == 'money':
            log.info('conn %d: money pickup %r (no producer; left)',
                     self.conn_id, item_id)
            return fail
        if not _ground_can_pick_up(item, str(role.get('id')), None, now):
            return fail
        if self.config._goods_table().get(str(item.goods_id)) is None:
            # Java destroys the item here (leave runs before putInBag1
            # reports the unknown config); the item is kept instead so a
            # config gap cannot eat a drop.
            log.info('conn %d: pickup of unconfigured goods %r (left)',
                     self.conn_id, item.goods_id)
            return fail
        if not self._pickup_fits(role.get('id'), item):
            return fail
        claimed = store.remove(item_id)
        if claimed is None:
            return fail
        ok, applied, new_row = self._pickup_write(role, claimed)
        if not ok:
            # Nothing (or only part of the award) reached the bag: roll
            # back any stacked counts, restore the item, drop nothing.
            for row, old_count in applied:
                try:
                    self.update_role_bag_slot(role.get('id'),
                                            row.get('slot_num'),
                                            count=old_count)
                except Exception:
                    pass
            store.restore(claimed)
            if applied:
                log.warning('conn %d: pickup write failed mid-apply '
                            '(rolled back, item %r restored)',
                            self.conn_id, item_id)
            return fail
        frames = [frame(amf3_encode(
            ['30103', [1, claimed.goods_id, claimed.count, claimed.id]]))]
        if new_row is not None:
            frames.append(frame(amf3_encode(
                ['30105', [self.bag_goods_map(role, new_row)]])))
        for row, _old in applied:
            frames.append(frame(amf3_encode(
                ['30104', [[[row.get('bag_id'), row.get('count')]]]])))
        # Stage.leave -> AOI delete -> 24004 [itemId] to the item's 3x3
        # surround (AoiMsgListener leave for GOODS); the picker keeps its
        # own copies inline, peers are pushed.
        frames.extend(self._point_broadcast(
            claimed.map_id, (claimed.x, claimed.y), '24004', [claimed.id]))
        return True, tuple(frames)

    @staticmethod
    def _pickup_expire(value):
        """Bag expire_time normalized the way Java's longValue reads it."""
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _pickup_stackable(self, slot, item, max_stack):
        """BagServiceImpl.canStack: same goods/bind/expire, room left."""
        try:
            if str(slot.get('goods_id')) != str(item.goods_id):
                return False
        except Exception:
            return False
        try:
            same_bind = int(slot.get('bind') or 0) == int(item.bind or 0)
        except (TypeError, ValueError):
            same_bind = False
        if not same_bind:
            return False
        if self._pickup_expire(slot.get('expire_time')) != 0:
            # Drops always carry expire 0 (hpadd002 duration 0), so a
            # nonzero row can never stack with one.
            return False
        try:
            return int(slot.get('count') or 0) < max_stack
        except (TypeError, ValueError):
            return False

    def _pickup_fits(self, rid, item):
        """BagServiceImpl.checkBagSlots1 for one ground item."""
        try:
            slots = self.get_role_bag_slots(rid, 1, 150) or []
        except Exception:
            return False
        try:
            state = self._bag_state_or_init(rid) or {}
            capacity = int(state.get('bag_capacity') or 0)
        except (TypeError, ValueError):
            return False
        if capacity - len(slots) >= 1:
            return True
        max_stack = self.config.goods_max_stack(item.goods_id)
        if not max_stack:
            return False
        try:
            left = int(item.count or 0)
        except (TypeError, ValueError):
            return False
        for slot in slots:
            if not self._pickup_stackable(slot, item, max_stack):
                continue
            try:
                left -= max_stack - int(slot.get('count') or 0)
            except (TypeError, ValueError):
                continue
            if left <= 0:
                return True
        return False

    def _pickup_write(self, role, item):
        """BagServiceImpl.putOneGoodsInBag1 for a claimed ground item.

        Returns (ok, applied_updates, new_row): applied_updates is
        [(row, old_count)] for each stacked row, new_row the inserted bag
        row (or None when the whole count stacked). A write failure
        returns (False, applied_so_far, None) so the caller can roll
        the counts back and restore the item.
        """
        rid = role.get('id')
        max_stack = self.config.goods_max_stack(item.goods_id) or 0
        if max_stack <= 0:
            max_stack = 1
        try:
            slots = self.get_role_bag_slots(rid, 1, 150) or []
        except Exception:
            return False, [], None
        try:
            state = self._bag_state_or_init(rid) or {}
            capacity = int(state.get('bag_capacity') or 0)
        except (TypeError, ValueError):
            return False, [], None
        try:
            left = int(item.count or 0)
        except (TypeError, ValueError):
            return False, [], None
        if left <= 0:
            return False, [], None
        applied = []
        same = sorted((s for s in slots
                       if self._pickup_stackable(s, item, max_stack)),
                      key=lambda s: s.get('slot_num') or 0)
        for slot in same:
            if left <= 0:
                break
            try:
                have = int(slot.get('count') or 0)
            except (TypeError, ValueError):
                continue
            take = min(max_stack - have, left)
            if take <= 0:
                continue
            try:
                self.update_role_bag_slot(rid, slot.get('slot_num'),
                                          count=have + take)
            except Exception:
                return False, applied, None
            slot = dict(slot, count=have + take)
            applied.append((slot, have))
            left -= take
        if left <= 0:
            return True, applied, None
        used = {s.get('slot_num') for s in slots}
        free = next((n for n in range(1, capacity + 1) if n not in used),
                    -1)
        if free < 0:
            return False, applied, None
        # ItemModel fields for a drop: bind from the DropRule lottery (0
        # here), expire 0 (hpadd002 duration 0), rare/item level from the
        # goods row, no attributes outside the equip/skillbook branches.
        row = {'slot_num': free, 'goods_id': item.goods_id, 'count': left,
               'bind': int(item.bind or 0), 'expire_time': 0,
               'rare_level': self.config.goods_rarelevel(item.goods_id),
               'item_level': self.config.goods_item_level(item.goods_id),
               'attributes': None}
        try:
            bag_id = self.insert_role_bag_slot(rid, dict(row))
        except Exception:
            return False, applied, None
        if not bag_id:
            return False, applied, None
        if self.config is not None and self._bag_goods_autouse(
                item.goods_id):
            log.info('conn %d: pickup autouse goods %r (no stage bus; '
                     'skipped)', self.conn_id, item.goods_id)
        return True, applied, dict(row, bag_id=bag_id)

    def _schedule_leave(self, dead_monster):
        """Monster.deadHandle/scheduleDisappearHandle: 24002 after asheslast."""
        tpl = dead_monster.get('template') or {}
        try:
            delay = int(tpl.get('asheslast') or 3)
        except (TypeError, ValueError):
            delay = 3
        self._leaving[dead_monster['id']] = max(delay, 1)

    def _presence_aggro(self, role, x, y):
        """Monsters whose eyeshot covers a moved role gain hatred (no frames)."""
        if self.config is None:
            return
        map_id = str(role.get('map_id'))
        if not any(r['map'] == map_id for r in self._monster_reg.values()):
            for n, rec in enumerate(self.config.monster_snapshot(map_id)):
                self._stage_fighter(rec[0])
        wid = _wire_id(role)
        for mid in list(self._monster_reg):
            if mid in self._dead or mid in self._hatred:
                continue
            reg = self._monster_reg[mid]
            if str(role.get('map_id')) != str(reg['map']):
                continue
            try:
                eyeshot = int(reg['template'].get('eyeshot') or 5)
            except (TypeError, ValueError):
                eyeshot = 5
            if ai_lib.in_aggro(reg['pos'], [x, y], eyeshot):
                self._hatred[mid] = wid

    def _aoi_enter_frames(self, role, old_pos, new_pos):
        """23002 + born-flag tiles for monsters newly inside the role's AOI.

        Mirrors the AoiMsgListener element-enter burst the scene entry sends
        (scene_tail_frames): a role that walks into a monster's AOI sees the
        same 23002 record + 40000 tile it would have gotten entering there,
        except field 15 is True on enter (legacy Java tap: entry snapshots
        carry False, every movement-enter burst carries True). Steps inside
        one AOI box, unknown positions and dead monsters stay silent.
        Returns a frame tuple, or None when nothing new is visible.
        """
        if self.config is None:
            return None
        try:
            old = [int(old_pos[0]), int(old_pos[1])]
            new = [int(new_pos[0]), int(new_pos[1])]
        except (TypeError, ValueError):
            return None
        if old == new:
            return None
        map_id = str(role.get('map_id'))
        before = {r[0] for r in
                  self.world_snapshot_records(map_id, *old)}
        entered = [list(r) for r in
                   self.world_snapshot_records(map_id, *new)
                   if r[0] not in before]
        for r in entered:
            r[15] = True
        if not entered:
            return None
        frames = [frame(amf3_encode(['23002', entered]))]
        for rec in entered:
            try:
                frames.append(frame(amf3_encode(ai_lib.tile_move_frame(
                    rec[0], [rec[11], rec[12]], True))))
            except (IndexError, TypeError, ValueError):
                continue
        return tuple(frames)

    def _dazuo_cancel_frames(self, role):
        """44003 exit when a moving role is meditating, else None.

        The Flash client never sends 44003 for the move itself (live
        capture): the server cancels the _dazuo_state, its tick timer and
        any partner link, exactly like an explicit dazuo_exit.
        """
        wid = _wire_id(role)
        state = self._dazuo.get(wid)
        if state is None or not state.get('daZuo'):
            return None
        return self.dazuo_exit(['44003', [wid]])

    def _walkable(self, map_id):
        """Walkability predicate for AI steps, or None without a grid."""
        grid = self.config.path_grid(map_id) if self.config is not None else None
        if grid is None:
            return None
        return lambda x, y: grid.walkable(int(x), int(y))

    def _monster_step(self, mid, reg, dest, frames):
        """One AiFightServiceImpl.move step toward dest; False when stuck."""
        walkable = self._walkable(reg['map'])
        if walkable is None:
            log.info('conn %d: no path grid for map %r (monster %r holds)',
                     self.conn_id, reg['map'], mid)
            return False
        step = ai_lib.step_toward(list(reg['pos']), list(dest), walkable)
        if step is None:
            return False
        reg['pos'] = step
        frames.append(frame(amf3_encode(ai_lib.tile_move_frame(
            mid, step, step == reg['born'],
            ai_lib.MOVE_KIND_MONSTER))))
        return True

    def ai_tick(self):
        """One AI step for this session (AiFightServiceImpl.defaultHandle).

        The shared monster world steps at most once per server round, whichever
        session claims the round first, and its frames reach the sessions on each
        map. This session's own pets step on every call. Returns this session's
        frames, or None when quiet.
        """
        frames = []
        if self._world.claim_round():
            # The S:GOODS_DIS leave removes each expired item once; its
            # 24004 [itemId] goes to the item's 3x3 surround like a pickup.
            for gone in self._world.ground_items.expire(
                    self._world_now_ms()):
                frames.extend(self._point_broadcast(
                    gone.map_id, (gone.x, gone.y), '24004', [gone.id]))
            frames.extend(self.deliver_world_frames(self.monster_world_step()))
        frames.extend(self.pet_ai_step())
        return tuple(frames) if frames else None

    @staticmethod
    def _mid_map(mid):
        """Map id encoded in a monster id m_<map>_<n>, or None."""
        parts = str(mid).split('_')
        return parts[1] if len(parts) == 3 and parts[0] == 'm' else None

    def monster_world_step(self):
        """Step every shared monster once, grouped by map (under the world lock).

        Monster ids encode their map, so hatred, leave and respawn work for one map
        never touches another map's monsters.
        """
        with self._world.lock:
            maps = {self._mid_map(m) for m in self._monster_reg}
            maps |= {str(sp[1]) for sp in self._spawning}
            maps.discard(None)
            by_map = {}
            for map_id in sorted(maps):
                frames = []
                self._monster_ai_map(map_id, frames)
                by_map[map_id] = frames
            return by_map

    def _target_off_map(self, target, map_id):
        """True when a role target is not alive on the monster's map."""
        if target['kind'] != 'role':
            return False
        role = target['role']
        if str(role.get('map_id')) != str(map_id):
            return True
        return self._fighter_hp(target)[0] <= 0

    def _monster_ai_map(self, map_id, frames):
        """Hatred, leave and respawn for the monsters of one map."""
        for mid in sorted(self._hatred):
            if self._mid_map(mid) != map_id or mid in self._dead:
                continue
            reg = self._monster_reg.get(mid)
            if reg is None:
                self._hatred.pop(mid, None)
                continue
            target = self._stage_fighter(self._hatred[mid])
            if (target is None or target['id'] in self._dead
                    or self._target_off_map(target, map_id)):
                # refreshState FIGHT -> BACK: hatred lost, walk home.
                self._hatred.pop(mid, None)
                if list(reg['pos']) != list(reg['born']):
                    self._monster_step(mid, reg, reg['born'], frames)
                continue
            tpos = self._fighter_pos(target)
            if tpos is None:
                continue
            tpl = reg['template']
            try:
                maxrange = int(tpl.get('maxrange') or 9)
            except (TypeError, ValueError):
                maxrange = 9
            if ai_lib.chebyshev(reg['pos'], reg['born']) > maxrange:
                self._hatred.pop(mid, None)
                self._monster_step(mid, reg, reg['born'], frames)
                continue
            if ai_lib.chebyshev(reg['pos'], tpos) <= 1:
                pixel = ai_lib.tile_to_pixel(tpos)
                rid = target['id'] if target['kind'] == 'role' else None
                frames.append(frame(amf3_encode(ai_lib.skill_ready_frame(
                    mid, ai_lib.MONSTER_SKILL, pixel, None, rid))))
                monster = {'kind': 'monster', 'id': mid,
                           'template': reg['template']}
                frames.extend(self._resolve_fire(
                    monster, ai_lib.MONSTER_SKILL, 0, [target['id']],
                    None, 1))
            else:
                self._monster_step(mid, reg, tpos, frames)
        for mid in sorted(self._leaving):
            if self._mid_map(mid) != map_id:
                continue
            self._leaving[mid] -= 1
            if self._leaving[mid] > 0:
                continue
            reg = self._monster_reg.pop(mid, None)
            self._monster_hp.pop(mid, None)
            if reg is not None:
                tpl = reg['template']
                try:
                    delay = int(tpl.get('creattime') or 5)
                except (TypeError, ValueError):
                    delay = 5
                self._spawning.append([tpl.get('id'), reg['map'],
                                       list(reg['born']), max(delay, 1)])
            frames.append(self.aoi_leave_frame(mid))
        for mid in [m for m in self._leaving
                    if self._mid_map(m) == map_id and self._leaving[m] <= 0]:
            del self._leaving[mid]
        still = []
        for tpl_id, sp_map, born, ticks in list(self._spawning):
            if str(sp_map) != map_id:
                still.append([tpl_id, sp_map, born, ticks])
                continue
            ticks -= 1
            if ticks > 0:
                still.append([tpl_id, sp_map, born, ticks])
                continue
            tpl = (self.config.monster_template(tpl_id)
                   if self.config is not None else None)
            if tpl is None:
                log.info('conn %d: respawn template %r gone (skipped)',
                         self.conn_id, tpl_id)
                continue
            # Snapshot ids occupy 0..spawn_count-1 on this map, so respawns start
            # above them without needing a snapshot to have been sent first.
            base = (self.config.monster_spawn_count(str(map_id))
                    if self.config is not None else 0)
            n = max(self._respawn_next.get(str(map_id), 0), base)
            while ('m_%s_%d' % (map_id, n)) in self._monster_reg:
                n += 1
            self._respawn_next[str(map_id)] = n + 1
            nid = 'm_%s_%d' % (map_id, n)
            self._monster_reg[nid] = {'template': tpl, 'map': str(map_id),
                                      'born': list(born), 'pos': list(born)}
            self._monster_hp[nid] = float(tpl.get('hitpoints') or 0)
            frames.append(frame(amf3_encode(
                ['23002', [ai_lib.respawn_record(nid, tpl, born)]])))
        self._spawning[:] = still

    def pet_ai_step(self):
        """Pets follow their owners: teleport past range, otherwise step toward them."""
        frames = []
        for pet_id in sorted(self._pet_state):
            if pet_id in self._dead:
                continue
            pet = self._pet_state[pet_id]
            roles = self.get_roles(self.authed_user or '', self.server_id or '')
            owner = _find_role(roles, pet.get('owner'))
            if owner is None or pet.get('pos') is None:
                continue
            opos = [int(owner.get('map_x')), int(owner.get('map_y'))]
            if ai_lib.chebyshev(pet['pos'], opos) > ai_lib.PET_TELEPORT_RANGE and \
                    self._pet_teleport(pet_id, pet, owner, frames):
                continue
            if ai_lib.chebyshev(pet['pos'], opos) > 2:
                walkable = self._walkable(str(owner.get('map_id')))
                if walkable is None:
                    continue
                step = ai_lib.step_toward(list(pet['pos']), opos, walkable)
                if step is not None:
                    pet['pos'] = step
                    frames.append(frame(amf3_encode(ai_lib.tile_move_frame(
                        pet_id, step, False, ai_lib.MOVE_KIND_PET))))
        return frames

    def deliver_world_frames(self, by_map):
        """Return this session's share of per-map monster frames; push the rest.

        A session gets the frames of the maps where it has roles (or all frames when
        it has no stage registry). Every other session on a map is pushed that map's
        frames once, however many of its roles are there.
        """
        if not by_map:
            return []
        if self.stage_registry is None:
            mine = []
            for frames in by_map.values():
                mine.extend(frames)
            return mine
        own_maps = {str(r.get('map_id')) for r in
                    self.get_roles(self.authed_user or '', self.server_id or '')}
        mine = []
        for map_id, frames in by_map.items():
            if not frames:
                continue
            seen = set()
            for _role, sess in self.stage_registry.peers(map_id):
                if id(sess) in seen:
                    continue
                seen.add(id(sess))
                if sess is self:
                    mine.extend(frames)
                else:
                    sess.push_frames(frames)
            if map_id in own_maps and id(self) not in seen:
                mine.extend(frames)
        return mine

    def schedule_stage(self, key, command, callback, delay=0,
                       unit='SECONDS', now_ms=None):
        """Queue a stage-timer callback on this session (same key replaces)."""
        return self.stage_scheduler.schedule(key, command,
                                             {'callback': callback},
                                             delay, unit, now_ms)

    def push_op(self, fn):
        """Queue a state change from another connection; it runs on this session's tick."""
        with self.outbox_lock:
            self._ops.append(fn)

    def _dazuo_state(self, role_id):
        """Meditation state of one role on this connection, created on first use."""
        return self._dazuo.setdefault(str(role_id),
                                      {'daZuo': False, 'target': None})

    def _dazuo_actor(self, msg):
        """Role id a meditation request names (msg[1], or its first item), else the sole role."""
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        arg = self.safe(msg, 1, None)
        if isinstance(arg, list):
            arg = self.safe(arg, 0, None)
        role = _find_role(roles, str(arg)) if arg is not None else None
        if role is None and len(roles) == 1:
            role = roles[0]
        return _wire_id(role) if role is not None else None

    def _dazuo_in_fight(self, role_id):
        """Approximate role FIGHT: a monster in this session holds hatred on the role."""
        return any(str(v) == str(role_id) for v in self._hatred.values())

    def _dazuo_key(self, role_id):
        """Stage timer key for one role's meditation tick."""
        return f'timing_dazuo_get:{role_id}'

    def _pet_teleport(self, pet_id, pet, owner, frames):
        """PetFightServiceImpl.telport: jump a distant pet to a free cell beside its owner.

        Returns False when the owner's surround has no valid cell (the pet stays put).
        The 40100 echo [x, y, 0, petId] goes to the 3x3 AOI around the new cell.
        """
        if self.config is None:
            return False
        map_id = str(owner.get('map_id'))
        ox, oy = int(owner.get('map_x')), int(owner.get('map_y'))
        occupied = {(ox, oy)} | self.config.monster_spawn_cells(map_id)
        point = self.config.surround_valid_point(map_id, ox, oy, occupied)
        if point is None:
            return False
        pet['pos'] = [int(point[0]), int(point[1])]
        frames.extend(self._point_broadcast(
            map_id, point, CMD_TELEPORT, [int(point[0]), int(point[1]), 0, pet_id]))
        return True

    def _point_broadcast(self, map_id, point, command, payload):
        """Send a command to the 3x3 AOI around a tile; this session's own copies are returned."""
        body = frame(amf3_encode([str(command), payload]))
        if self.stage_registry is None:
            return [body]
        targets = self.stage_registry.surround_at(map_id, point)
        if not targets:
            return [body]
        own = []
        for _, sess in targets:
            if sess is self:
                own.append(body)
            else:
                sess.push_frames([body])
        return own

    def _dazuo_broadcast(self, role_id, command, payload):
        """Send a command to the role's surround; this session's own copies are returned."""
        body = frame(amf3_encode([str(command), payload]))
        if self.stage_registry is None:
            return [body]
        targets = self.stage_registry.surround(role_id)
        if not targets:
            return [body]
        own = []
        for _, sess in targets:
            if sess is self:
                own.append(body)
            else:
                sess.push_frames([body])
        return own

    def _dazuo_timer(self, role_id):
        """Arm the 15 s meditation tick for a role on this session."""
        self.schedule_stage(self._dazuo_key(role_id), str(CMD_DAZUO_TIMING),
                            lambda: self.dazuo_timing(role_id),
                            delay=DAZUO_TICK_SECONDS, unit='SECONDS')

    def dazuo_single(self, msg):
        """Command 44001: start meditating alone and broadcast to the surround."""
        rid = self._dazuo_actor(msg)
        if rid is None:
            return None
        if self._dazuo_in_fight(rid):
            return frame(amf3_encode(['44001', [0, DAZUO_ERR_FIGHT]]))
        state = self._dazuo_state(rid)
        state['daZuo'] = True
        state['target'] = None
        out = self._dazuo_broadcast(rid, CMD_DAZUO_SINGLE, [1, rid])
        self._dazuo_timer(rid)
        return tuple(out) if out else None

    def dazuo_both(self, msg):
        """Command 44002: ask a solo meditator to pair; the target answers on its tick."""
        rid = self._dazuo_actor(msg)
        arg = self.safe(msg, 1, [])
        target_id = str(arg[1]) if isinstance(arg, list) and len(arg) > 1 else None
        if rid is None or target_id is None:
            return None
        state = self._dazuo_state(rid)
        error = frame(amf3_encode(['44002', [0, DAZUO_ERR_ROLE]]))
        if state['target'] is not None:
            return error
        if not state['daZuo']:
            return None
        target_sess = (self.stage_registry.session_of(target_id)
                       if self.stage_registry is not None else None)
        if target_sess is None:
            return error
        target_sess.push_op(
            lambda: target_sess._dazuo_accept(target_id, rid, self))
        return None

    def _dazuo_accept(self, target_id, rid, requester):
        """Target side of 44002: accept a solo meditator, or refuse a paired one."""
        ts = self._dazuo.get(str(target_id))
        if ts is not None and ts['target'] is not None:
            requester.push_op(lambda: requester._dazuo_refuse(rid))
            return None
        if ts is None or not ts['daZuo']:
            return None
        ts['target'] = str(rid)
        requester.push_op(
            lambda: requester._dazuo_link(rid, target_id, self))
        return None

    def _dazuo_refuse(self, rid):
        """Requester side: the target already has a partner (44002 DA_ZUO_ROLE)."""
        return frame(amf3_encode(['44002', [0, DAZUO_ERR_ROLE]]))

    def _dazuo_link(self, rid, target_id, target_sess):
        """Requester side: link both roles and broadcast 44002, or undo the target's link."""
        state = self._dazuo_state(rid)
        if not state['daZuo'] or state['target'] is not None:
            target_sess.push_op(
                lambda: target_sess._dazuo_unlink(target_id, rid))
            return frame(amf3_encode(['44002', [0, DAZUO_ERR_ROLE]]))
        state['target'] = str(target_id)
        return tuple(self._dazuo_broadcast(
            rid, CMD_DAZUO_BOTH, [1, rid, target_id]))

    def _dazuo_unlink(self, role_id, partner_id):
        """Clear a role's partner link when it still points at the leaving partner."""
        state = self._dazuo.get(str(role_id))
        if state is not None and state['target'] == str(partner_id):
            state['target'] = None
        return None

    def dazuo_exit(self, msg):
        """Command 44003: leave meditation, unlink the partner, broadcast 44003."""
        rid = self._dazuo_actor(msg)
        if rid is None:
            return None
        state = self._dazuo_state(rid)
        partner = state['target']
        state['daZuo'] = False
        state['target'] = None
        self.stage_scheduler.cancel(self._dazuo_key(rid))
        if partner is not None and self.stage_registry is not None:
            partner_sess = self.stage_registry.session_of(partner)
            if partner_sess is not None:
                partner_sess.push_op(
                    lambda: partner_sess._dazuo_unlink(partner, rid))
        # Java daZuoExit addMsg(surround, "44003", roleId): the payload is
        # the exiting role, not null (RoleBehaviourServiceImpl bytecode).
        out = self._dazuo_broadcast(rid, CMD_DAZUO_EXIT, rid)
        return tuple(out) if out else None

    def dazuo_timing(self, role_id):
        """Command 44004 timer: award one tick of meditation exp/zhenqi, then re-arm."""
        state = self._dazuo.get(str(role_id))
        if state is None or not state['daZuo'] or self.config is None:
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = _find_role(roles, str(role_id))
        if role is None:
            return None
        # selfFlag is 1 (no meiren pet is modelled yet); targetFlag is 1 with a partner.
        flag_sum = 1 + (1 if state['target'] is not None else 0)
        gain = self.config.dazuo_gain(role.get('level'), flag_sum)
        if gain is None:
            return None
        exp_gain, zhenqi_gain = gain
        level_frames = []
        if exp_gain > 0:
            _total, _level, _gained, exp_frames = self._role_gain_exp(
                role, role_id, exp_gain)
            level_frames = exp_frames[1:]
        if zhenqi_gain > 0:
            self.save_role_state(role_id,
                                 zhenqi=int(role.get('zhenqi') or 0) + zhenqi_gain)
        self._dazuo_timer(role_id)
        out = [frame(amf3_encode(['44004', [exp_gain, zhenqi_gain]]))]
        out.extend(level_frames)
        return tuple(out) if len(out) > 1 else out[0]

    def tick(self, now_ms=None):
        """One server-loop second under the state lock: timers, then ai_tick."""
        with self.state_lock:
            return self._tick_unlocked(now_ms)

    def subscribe(self, event_type, order, handler):
        """Subscribe a handler to a bus event type (EventCenter.subscribe)."""
        self.bus.subscribe(event_type, order, handler)

    def publish(self, event_type, source=None, data=None):
        """Publish a bus event under the state lock (EventCenter.publish)."""
        with self.state_lock:
            self.bus.publish(eventbus_lib.Event(event_type, source, data))

    def register_inner(self, command, handler):
        """Register the handler a routed inner token for command calls."""
        self.inner_handlers[str(command)] = handler

    def _dispatch_inner(self, role_id, stage_id, command, data, token):
        """StageMsgDispatcher.in: run the command handler, frames join the tick."""
        handler = self.inner_handlers.get(str(command))
        if handler is None:
            log.info('conn %d: inner token %r skipped (no handler)',
                     self.conn_id, command)
            return
        out = handler(role_id, stage_id, data, token)
        if out is None:
            return
        if self._inner_out is None:
            log.info('conn %d: inner token %r ran outside a tick (frames dropped)',
                     self.conn_id, command)
            return
        self._inner_out.extend(tuple(out) if isinstance(out, tuple) else [out])

    def schedule_inner(self, key, module, command, role_id, stage_id, data,
                       delay, unit='SECONDS', now_ms=None):
        """Queue a routed stage inner token (StageTokenRunable) after a delay."""
        job = scheduler_lib.StageTokenRunable.scoped(
            module, role_id, stage_id, command, data,
            on_stage=self._dispatch_inner)
        return self.stage_scheduler.schedule(key, command, {'runnable': job},
                                             delay, unit, now_ms)

    def _tick_unlocked(self, now_ms=None):
        """Tick body; tick() holds the state lock."""
        frames = []
        for entry in self.stage_scheduler.due(now_ms):
            data = entry.get('data')
            if isinstance(data, dict) and data.get('runnable') is not None:
                self._inner_out = []
                try:
                    data['runnable'].run()
                except Exception:
                    log.warning('conn %d: inner token %r failed',
                                self.conn_id, entry.get('command'), exc_info=True)
                frames.extend(self._inner_out)
                self._inner_out = None
                continue
            callback = data.get('callback') if isinstance(data, dict) else None
            if callback is None:
                log.info('conn %d: stage timer %r skipped (no handler)',
                         self.conn_id, entry.get('command'))
                continue
            try:
                out = callback()
            except Exception:
                log.warning('conn %d: stage timer %r failed',
                            self.conn_id, entry.get('command'), exc_info=True)
                continue
            if out is None:
                continue
            frames.extend(tuple(out) if isinstance(out, tuple) else [out])
        extra = self.ai_tick()
        if extra is not None:
            frames.extend(tuple(extra) if isinstance(extra, tuple) else [extra])
        with self.outbox_lock:
            ops, self._ops = self._ops, []
        for op in ops:
            try:
                out = op()
            except Exception:
                log.warning('conn %d: queued op failed', self.conn_id,
                            exc_info=True)
                continue
            if out is not None:
                frames.extend(tuple(out) if isinstance(out, (tuple, list)) else [out])
        with self.outbox_lock:
            pending, self.outbox = self.outbox, []
        frames.extend(pending)
        return tuple(frames) if frames else None

    def push_frames(self, frames):
        """Queue frames from another connection; they go out on this session's next tick."""
        items = list(frames) if isinstance(frames, (list, tuple)) else [frames]
        with self.outbox_lock:
            self.outbox.extend(items)

    def aoi_leave_frame(self, fighter_id):
        """24002 AOI leave [[fighterId]] (builder for the respawn phase)."""
        return frame(amf3_encode(combat_lib.aoi_leave_frame(fighter_id)))

    def next_buff_id(self, kind):
        """IdUtil.nextString('buff'/'propbuff') shape for one stage object."""
        self._obj_seq += 1
        return f'{kind}_{self._stage_serial}_{self._obj_seq}'

    def entry_buff_frame(self, role):
        """42100 stage-entry buff list from the role's known state.

        Ports buffChange's entry flush: the VIP buff when role_vip carries a
        level with a XiaoGuoBiao row (vip010-style, permanent -> -1.0), then
        the unconditional birthprotect (lasttime 10000, fresh -> full
        remaining). Pool and exp-fold buffs live in unmigrated item state, so
        they are absent here -- a role without them looks exactly like the
        captured fresh role (probe-stress: birthprotect alone)."""
        if role is None:
            return None
        wire_id = _wire_id(role)
        adds = []
        live = []
        t0 = time.time()
        try:
            vip = self.get_role_vip(role.get('id'))
        except Exception:
            vip = None
        buff_id = (self.config.vip_buff_id((vip or {}).get('vip_level'))
                   if self.config is not None else None)
        if buff_id is not None:
            iid = self.next_buff_id('buff')
            adds.append(timed_buff(iid, buff_id, None, 1, wire_id))
            live.append([iid, buff_id, None, t0])
        else:
            log.info('conn %d: no VIP buff for role %r (no vip row/mapping)',
                     self.conn_id, wire_id)
        lasttime = (self.config.buff_lasttime('birthprotect')
                    if self.config is not None else None)
        if lasttime is None:
            log.info('conn %d: no birthprotect lasttime (no XiaoGuoBiao)',
                     self.conn_id)
        else:
            iid = self.next_buff_id('buff')
            adds.append(timed_buff(iid, 'birthprotect', lasttime, 1, wire_id))
            live.append([iid, 'birthprotect', float(lasttime), t0])
        self._buff_live = live
        if not adds:
            return None
        return frame(amf3_encode(buff_change(wire_id, adds)))

    def buff_query(self, msg):
        """Command 42100: BuffServiceImpl.getBuff answers the live buffs.

        Replays the instance ids stashed at entry with ticked-down
        remaining (permanent buffs stay -1.0); buffs whose lifetime ran
        out are reported once in the removes slot and forgotten, and a
        quiet session answers [wireId, None, None] — BuffStatistics
        serializes empty lists as null, never [].
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        if not roles:
            return None
        wire_id = _wire_id(roles[0])
        now = time.time()
        adds, removes, keep = [], [], []
        for iid, buff_id, lasttime, t0 in self._buff_live:
            if lasttime is None:
                adds.append(timed_buff(iid, buff_id, None, 1, wire_id))
                keep.append([iid, buff_id, None, t0])
            else:
                try:
                    remaining = float(lasttime) - (now - float(t0)) * 1000.0
                except (TypeError, ValueError):
                    remaining = 0.0
                if remaining > 0:
                    adds.append(timed_buff(iid, buff_id, remaining, 1,
                                           wire_id))
                    keep.append([iid, buff_id, lasttime, t0])
                else:
                    removes.append(iid)
        self._buff_live = keep
        return frame(amf3_encode(buff_change(wire_id, adds, removes)))

    def zuoqi_hp(self, msg):
        """Command 33022: StageMeirenServiceImpl.getZuoqiHp, live pet HP.

        The first live zuoqi pet on this session's stage answers
        [curHp, maxHp] as ints; with no pet staged this is [0, 0],
        exactly the fresh-role capture.
        """
        for pet_id, pet in self._pet_state.items():
            if pet_id in self._dead:
                continue
            if not str(pet.get('template_id', '')).startswith('zuoqi'):
                continue
            try:
                hp = int(pet.get('hp') or 0)
                max_hp = int(pet.get('max_hp') or 0)
            except (TypeError, ValueError):
                continue
            return frame(amf3_encode(['33022', [[hp, max_hp]]]))
        return frame(amf3_encode(['33022', [[0, 0]]]))

    def _zuoqi_revive_state(self, role, rid):
        """Mount revive read for the 33020/33021/33023/33024 family.

        Ports the ZuoQiBussinessData read shared by zuoqiFullHp,
        zuoqiRevive, zuoqiFreeRevive and getZuoqiDeadInfo: rank from the
        live staged pet, else the stage copy (role_stage.zuoqi_info id,
        Java's decodeZuoQiInfo curRank), else the role_zuoqi row; HP from
        the live pet else the persisted copy; max HP from the pet else
        the rank's ZuoJiBiao row; dead/use from the session ledger, with
        RoleStageUtil.decodeZuoQiInfo's reload rule (a persisted deadTime
        re-anchors to now, keeping the stored elapsed) applied once per
        session when no live death record exists. None when the role
        never owned a mount (curRank null) or max HP is unresolvable.
        """
        if role is None or self.config is None:
            return None
        wire = _wire_id(role)
        pet_id, pet = None, None
        for pid, candidate in self._pet_state.items():
            if candidate.get('owner') != wire:
                continue
            if not str(candidate.get('template_id', '')).startswith('zuoqi'):
                continue
            pet_id, pet = pid, candidate
            break
        info = decode_zuoqi_info(role.get('zuoqi_info'))
        rank = 0
        if pet is not None:
            try:
                rank = int(str(pet.get('template_id', ''))[len('zuoqi'):])
            except (TypeError, ValueError):
                rank = 0
        if rank <= 0 and info is not None:
            try:
                rank = int(info.get('id') or 0)
            except (TypeError, ValueError):
                rank = 0
        if rank <= 0:
            row = self._zuoqi_row(rid)
            if row is not None:
                for key in ('zuoqi_cur_rank', 'zuoqi_rank'):
                    try:
                        rank = int(row.get(key) or 0)
                    except (TypeError, ValueError):
                        rank = 0
                    if rank > 0:
                        break
        if rank <= 0:
            return None
        max_hp, cur_hp = 0, 0
        if pet is not None:
            try:
                max_hp = int(pet.get('max_hp') or 0)
                cur_hp = int(pet.get('hp') or 0)
            except (TypeError, ValueError):
                max_hp, cur_hp = 0, 0
        else:
            if info is not None:
                try:
                    cur_hp = int(info.get('hp') or 0)
                except (TypeError, ValueError):
                    cur_hp = 0
            found = self.config.zuoqi_pet(rank, role.get('level'))
            if found is not None:
                try:
                    max_hp = int(found[1].get('meinvhp') or 0)
                except (TypeError, ValueError):
                    max_hp = 0
        if max_hp <= 0:
            return None
        now = int(time.time() * 1000)
        try:
            kept = self._zuoqi_dead.get(wire)
        except Exception:
            kept = None
        if kept is None:
            stored_dead, stored_use = 0, 0
            if info is not None:
                try:
                    stored_dead = int(info.get('deadTime') or 0)
                    stored_use = int(info.get('useTime') or 0)
                except (TypeError, ValueError):
                    stored_dead, stored_use = 0, 0
            if stored_dead > 0:
                kept = [now, stored_use]
                try:
                    self._zuoqi_dead[wire] = kept
                except Exception:
                    pass
            else:
                kept = [0, 0]
        return {'rank': rank, 'cur': cur_hp, 'max': max_hp,
                'dead': kept[0], 'use': kept[1], 'pet_id': pet_id}

    def _zuoqi_revive_handle(self, role, rid, wire, st, out):
        """zuoqiReviveHandle: clear death, top HP, push pet refresh + 33022.

        Java removes the pet DEAD state (unstaged mounts respawn through
        createZuoQiPetEnterStage instead), zeroes deadTime/useTime, tops
        both HP copies to max, re-broadcasts the pet enter to surrounding
        roles (43002) and pushes [maxHp, maxHp] 33022. Ours has no 43002
        builder and the sprite never left the scene, so the enter
        rebroadcast is the 12004 HP refresh Java also sends; an unstaged
        mount restages on the next scene entry, when 23009 reads the
        persisted full HP back.
        """
        max_hp = st['max']
        try:
            self._zuoqi_dead[wire] = [0, 0]
        except Exception:
            pass
        self._persist_mount_hp(wire, max_hp, 0, 0)
        if st['pet_id'] is not None:
            pet = self._pet_state.get(st['pet_id'])
            if pet is not None:
                pet['hp'] = float(max_hp)
                self._dead.discard(st['pet_id'])
                out.append(frame(amf3_encode(combat_lib.hp_changed_frame(
                    st['pet_id'], float(max_hp), float(max_hp), 0.0, 0.0))))
        out.append(frame(amf3_encode(['33022', [[max_hp, max_hp]]])))
        return max_hp

    def zuoqi_full_hp(self, msg):
        """Command 33020: StageMeirenServiceImpl.zuoqiFullHp.

        Heals a hurt mount to full for fullNeedYxb silver: no mount or a
        full bar answers [0, 82144], short silver [0, 82147], else the
        12004 refresh plus [1, cost, maxHp]. A dead mount heals without
        clearing the death (Java leaves DEAD/deadTime alone here).
        """
        if self.config is None:
            return None
        role, rid = self._task_role()
        st = self._zuoqi_revive_state(role, rid)
        if st is None:
            return frame(amf3_encode(
                ['33020', [0, ZUOQI_ERR_FULLHP_STATE]]))
        if st['cur'] >= st['max']:
            return frame(amf3_encode(
                ['33020', [0, ZUOQI_ERR_FULLHP_STATE]]))
        try:
            cost = int((self.config.zuoqi_revive() or {}).get('fullNeedYxb')
                       or 0)
        except (TypeError, ValueError):
            cost = 0
        found = self._bag_money_first(role, cost, ['YXB'])
        if found is None:
            return frame(amf3_encode(
                ['33020', [0, ZUOQI_ERR_FULLHP_MONEY]]))
        self._bag_money_decr(rid, found[0], found[1])
        out = []
        if st['pet_id'] is not None:
            pet = self._pet_state.get(st['pet_id'])
            if pet is not None:
                pet['hp'] = float(st['max'])
                out.append(frame(amf3_encode(combat_lib.hp_changed_frame(
                    st['pet_id'], float(st['max']), float(st['max']),
                    0.0, 0.0))))
        self._persist_mount_hp(_wire_id(role), st['max'])
        out.append(frame(amf3_encode(
            ['33020', [1, cost, st['max']]])))
        return tuple(out)

    def _zuoqi_need_revive(self, st):
        """checkZuoqiNeedRevive: error code, or None when revival may run.

        No mount answers 82140; a staged pet must carry the DEAD state
        (ours: the _dead set, fed by the fight loop's kill), while an
        unstaged mount needs persisted HP at 0, else 82140.
        """
        if st is None:
            return ZUOQI_ERR_NEED_REVIVE
        if st['pet_id'] is not None:
            if st['pet_id'] not in self._dead:
                return ZUOQI_ERR_NEED_REVIVE
            return None
        if st['cur'] > 0:
            return ZUOQI_ERR_NEED_REVIVE
        return None

    def zuoqi_revive(self, msg):
        """Command 33021: StageMeirenServiceImpl.zuoqiRevive (paid, YB).

        A mount needing revival costs reviveNeedYb gold: check failures
        answer [0, check], short gold [0, 82143], else the revive-handle
        pushes plus [1, cost, curHp].
        """
        if self.config is None:
            return None
        role, rid = self._task_role()
        st = self._zuoqi_revive_state(role, rid)
        check = self._zuoqi_need_revive(st)
        if check is not None:
            return frame(amf3_encode(['33021', [0, check]]))
        try:
            cost = int((self.config.zuoqi_revive() or {}).get('reviveNeedYb')
                       or 0)
        except (TypeError, ValueError):
            cost = 0
        found = self._bag_money_first(role, cost, ['YB'])
        if found is None:
            return frame(amf3_encode(
                ['33021', [0, ZUOQI_ERR_REVIVE_YB]]))
        self._bag_money_decr(rid, found[0], found[1])
        out = []
        wire = _wire_id(role)
        cur_hp = self._zuoqi_revive_handle(role, rid, wire, st, out)
        out.append(frame(amf3_encode(['33021', [1, cost, cur_hp]])))
        return tuple(out)

    def zuoqi_free_revive(self, msg):
        """Command 33023: StageMeirenServiceImpl.zuoqiFreeRevive.

        The free revive opens once reviveNeedTime ms elapse past the
        death (accumulated across reconnects): before that the reply is
        [-1, remainingMs]; a mount needing no revival, or one with no
        recorded death, answers [0, 82140]; else the revive-handle pushes
        plus [1, curHp].
        """
        if self.config is None:
            return None
        role, rid = self._task_role()
        st = self._zuoqi_revive_state(role, rid)
        check = self._zuoqi_need_revive(st)
        if check is not None:
            return frame(amf3_encode(['33023', [0, check]]))
        if st['dead'] <= 0:
            return frame(amf3_encode(
                ['33023', [0, ZUOQI_ERR_NEED_REVIVE]]))
        try:
            need = int((self.config.zuoqi_revive() or {}).get(
                'reviveNeedTime') or 0)
        except (TypeError, ValueError):
            need = 0
        remaining = need - int(time.time() * 1000) + st['dead'] - st['use']
        if remaining > 0:
            return frame(amf3_encode(['33023', [-1, remaining]]))
        out = []
        cur_hp = self._zuoqi_revive_handle(
            role, rid, _wire_id(role), st, out)
        out.append(frame(amf3_encode(['33023', [1, cur_hp]])))
        return tuple(out)

    def zuoqi_dead_info(self, msg):
        """Command 33024: StageMeirenServiceImpl.getZuoqiDeadInfo.

        A live mount, a mountless role or one with no recorded death gets
        null (the fresh-role capture shape); a dead mount gets [rank,
        nowMs + reviveNeedTime - useTime], the revive countdown's anchor.
        """
        if self.config is None:
            return frame(amf3_encode(['33024', [None]]))
        role, rid = self._task_role()
        st = self._zuoqi_revive_state(role, rid)
        if st is None or st['cur'] > 0 or st['dead'] <= 0:
            return frame(amf3_encode(['33024', [None]]))
        try:
            need = int((self.config.zuoqi_revive() or {}).get(
                'reviveNeedTime') or 0)
        except (TypeError, ValueError):
            need = 0
        stamp = int(time.time() * 1000) + need - st['use']
        return frame(amf3_encode(['33024', [st['rank'], stamp]]))

    def skill_cd_frame(self, role):
        """42005 entry skill-cooldown [category, dynamicCd].

        Ports FightServiceImpl.skillReadyFire's readyAttackSkill push: the
        category is the role's ready attack skill (role state the 42000
        skill list owns; unmigrated roles carry none and skip the frame
        instead of inventing one), and the cooldown is int(cdtime /
        (1 + gongjisudu/2000)) off CdBiao and the live 12000 attack speed.
        """
        if role is None or self.config is None:
            return None
        category = role.get('attack_skill')
        if not category:
            log.info('conn %d: no attack skill for role %r (no 42005)',
                     self.conn_id, _wire_id(role))
            return None
        cd_id = self.config.skill_cd_id(category)
        cdtime = self.config.cd_time(cd_id) if cd_id else None
        attrs = self.role_attribute_map(role)
        if cdtime is None or attrs is None:
            log.info('conn %d: no cd/attributes for skill %r (no 42005)',
                     self.conn_id, category)
            return None
        return frame(amf3_encode(
            ['42005', [str(category), dynamic_cd(cdtime, attrs['6'])]]))

    def fight_state_frame(self, role):
        """40501 fight-state enter notice: the bare role id (send2One)."""
        return frame(amf3_encode(['40501', _wire_id(role)]))

    def buff_value_frame(self, owner_id, instance_id, value):
        """42102 pool-value tick [ownerId, propBuffId, value].

        Ports FightOutputWrapper.buffValueChange; pool regen has no
        scheduler yet, so entry does not emit it -- the builder is covered
        by tests for the combat-loop phase to call."""
        return frame(amf3_encode(buff_value(owner_id, instance_id, value)))

    def scene_tail_frames(self, role, map_id):
        """Frames Java pushes after 21000 on scene entry.

        Fresh-capture order (session-20261018-040230, map 2): the 23003
        NPC enters, then 12004 vitals, 12050 zhenqi+cap, 12005 shanbi,
        the 12000 attribute map, and the 42100 entry buff flush. The
        23002 monster snapshot only carries spawns inside the role's AOI
        box (a map-2 entry carries none), each followed by its born-flag
        40000 tile; the 23009 mount pet enters only for mounted roles.
        42005/40501 are NOT entry frames: the old tap shows 42005 on
        skill-ready and 40501 on a later fight-state change.
        """
        frames = []
        try:
            x, y = int(role.get('map_x')), int(role.get('map_y'))
        except (TypeError, ValueError):
            x = y = None
        if x is not None and self.config is not None:
            npc_records = self.config.npc_snapshot(map_id, x, y)
            if npc_records:
                frames.append(frame(amf3_encode(['23003', npc_records])))
        snapshot = self.monster_snapshot_frame(map_id, x, y)
        if snapshot is not None:
            frames.append(snapshot)
        # Settled ground items enter with the scene like the AOI role-enter
        # burst (one 23004 [msgData] per item, firstDrop already cleared).
        for item in self.ground_snapshot_items(map_id, x, y):
            frames.append(frame(amf3_encode(
                ['23004', [self.goods_msg_data(item, first_drop=0)]])))
        # The mount pet enters the stage right after the AOI snapshot
        # and before the stats pushes (old tap order).
        pet = self.zuoqi_pet_frame(role, map_id)
        if pet is not None:
            frames.append(pet)
        max_hp = role.get('max_hp')
        max_mp = role.get('max_mp')
        if max_hp is not None and max_mp is not None:
            # Java numerics serialize as AMF3 doubles; a role with no
            # stored vitals enters at full health.
            hp = role.get('hp')
            mp = role.get('mp')
            frames.append(frame(amf3_encode(
                ['12004', [_wire_id(role), float(hp if hp is not None else max_hp),
                           float(max_hp), float(mp if mp is not None else max_mp),
                           float(max_mp)]])))
        frames.append(frame(amf3_encode(
            ['12005', [int(role.get('shanbi_val') or 0)]])))
        row = (self.config.role_attribute_row(role.get('level'))
               if self.config is not None else None)
        if row is not None:
            frames.append(frame(amf3_encode(
                [str(CMD_ROLE_ZHENQI_CAP), [int(role.get('zhenqi') or 0),
                           int(row.get('zhenqi') or 0)]])))
            # Java writes the map as an AMF3 object (marker 0x0A), not an
            # ECMA array; Obj produces the same shape on the wire.
            attrs = self.role_attribute_map(role)
            if attrs is not None:
                frames.append(frame(amf3_encode(['12000', Obj(attrs)])))
        self._stage_serial += 1
        self._obj_seq = 0
        buff_frame = self.entry_buff_frame(role)
        if buff_frame is not None:
            frames.append(buff_frame)
        # The scene populates with one born-flag 40000 per snapshot
        # monster right after the buffs (old tap entry); without tiles
        # the client has records but no positions and renders no actors.
        if self.config is not None and x is not None:
            for rec in self.world_snapshot_records(map_id, x, y) or []:
                try:
                    frames.append(frame(amf3_encode(ai_lib.tile_move_frame(
                        rec[0], [rec[11], rec[12]], True))))
                except (IndexError, TypeError, ValueError):
                    continue
        return frames

    def change_stage(self, msg):
        """Acknowledge scene entry, then push the AOI scene like Java."""
        args = self.safe(msg, 1, [])
        role_id = str(self.safe(args, 0, '') or '')
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = _find_role(roles, role_id)
        if role is None:
            return None
        map_id = str(role.get('map_id') or '')
        if self.stage_registry is not None:
            self.stage_registry.register(_wire_id(role), map_id, self,
                                         x=role.get('map_x'),
                                         y=role.get('map_y'))
        map_type = self.map_type_for(map_id)
        frames = [frame(amf3_encode(['21000', [1, 1, map_type]]))]
        frames.extend(self.scene_tail_frames(role, map_id))
        return tuple(frames) if len(frames) > 1 else frames[0]

    def world_snapshot_records(self, map_id, x=None, y=None):
        """23002 records built from shared monster state, not the static spawn list.

        Spawns whose monster has died are omitted, so a late joiner never sees a dead
        monster alive. Live respawns on the map are added, and each spawn record
        carries the monster's current HP.
        """
        if self.config is None:
            return []
        from .config import _in_surround
        with self._world.lock:
            spawn_records = self.config.monster_snapshot(map_id, x, y)
            spawn_ids = {r[0] for r in self.config.monster_snapshot(map_id)}
            records = []
            for rec in spawn_records:
                if rec[0] in self._dead:
                    continue
                rec = list(rec)
                if rec[0] in self._monster_hp:
                    rec[4] = float(self._monster_hp[rec[0]])
                records.append(rec)
            for mid, reg in sorted(self._monster_reg.items()):
                if (reg['map'] != str(map_id) or mid in spawn_ids
                        or mid in self._dead):
                    continue
                pos = reg['pos']
                if x is not None and y is not None and not _in_surround(
                        x, y, pos[0], pos[1]):
                    continue
                rec = ai_lib.respawn_record(mid, reg['template'], pos)
                if mid in self._monster_hp:
                    rec[4] = float(self._monster_hp[mid])
                records.append(rec)
            return records

    def ground_snapshot_items(self, map_id, x=None, y=None, now_ms=None):
        """Unexpired ground items on a map for scene entry, AOI-box scoped.

        Mirrors the role-enter goods burst (getElementInfos for GOODS): only
        items Java would still hold on the stage, around the entering role.
        """
        store = self._world.ground_items
        if store is None or self.config is None:
            return []
        now = now_ms if now_ms is not None else self._world_now_ms()
        from .config import _in_aoi
        items = []
        for item in store.on_map(map_id):
            if now >= item.expires_at_ms:
                continue
            if x is not None and y is not None and not _in_aoi(
                    x, y, item.x, item.y):
                continue
            items.append(item)
        return items

    def monster_snapshot_frame(self, map_id, x=None, y=None):
        """23002 monster snapshot, or None when no spawn is in range.

        With a role position only the AOI-box spawns are reported, like
        Java's listener; without one (teleports, tests) the whole map is.
        """
        if self.config is None:
            return None
        records = self.world_snapshot_records(map_id, x, y)
        if not records:
            return None
        log.info('conn %d: map %s snapshot with %d monsters',
                 self.conn_id, map_id, len(records))
        return frame(amf3_encode(['23002', records]))

    def zuoqi_pet_frame(self, role, map_id):
        """23009 mount-pet snapshot (ZuoQiPet.enterStageHandle), or None.

        Java builds the pet at scene entry only when rideOrNo is false,
        rank and hp are positive, ZuoJiBiao has the rank's level row, and a
        surround point of the role's position is free
        (RoleEventManager.createZuoQiPetEnterStage); each miss skips the
        frame instead of inventing one.

        Field 12 is the owner's YiDongSuDu (PetFightAttribute delegates to
        the role), i.e. the same value as 12000 key '7', so it carries that
        frame's equipment-data gap. Field 13 is '0' because
        RoleEquipData.getQizhanbinqiId returns '0' when unset.
        """
        info = decode_zuoqi_info(role.get('zuoqi_info'))
        if info is None or info.get('rideOrNo'):
            return None
        rank = int(info.get('id') or 0)
        hp = int(info.get('hp') or 0)
        x, y = role.get('map_x'), role.get('map_y')
        if rank <= 0 or hp <= 0 or x is None or y is None \
                or self.config is None:
            return None
        pet = self.config.zuoqi_pet(rank, role.get('level'))
        level_row = self.config.role_attribute_row(role.get('level'))
        if pet is None or level_row is None:
            log.info('conn %d: no ZuoJiBiao/level row for rank %s at level %s'
                     ' (no 23009)', self.conn_id, rank, role.get('level'))
            return None
        level, row = pet
        # Entities take their cell up on stage add (AbsAoiStage.addHandle),
        # so the pet skips the role's cell and live spawn cells.
        occupied = {(int(x), int(y))} | self.config.monster_spawn_cells(map_id)
        point = self.config.surround_valid_point(map_id, int(x), int(y),
                                                 occupied)
        if point is None:
            log.info('conn %d: pet cannt find valid point, mapId:%s, x:%s, y%s',
                     self.conn_id, map_id, x, y)
            return None
        max_hp = float(row.get('meinvhp') or 0)
        # AbsFightAttribute.setCurHp clamps to [0, maxHp].
        cur_hp = max(0.0, min(float(hp), max_hp))
        self._scene_seq += 1
        pet_id = f'zuoqi_{map_id}_{self._scene_seq}'
        self._pet_ids.add(pet_id)
        self._pet_state[pet_id] = {
            'max_hp': max_hp, 'hp': cur_hp, 'level': level,
            'owner': _wire_id(role), 'owner_name': role.get('name'),
            'name': 'mount', 'template_id': 'zuoqi%d' % rank,
            'pos': list(point)}
        record = [
            pet_id,  # IdUtil.nextString('zuoqi')
            rank,
            cur_hp,
            max_hp,
            _wire_id(role),
            role.get('name'),
            point[0],
            point[1],
            None,                                 # fresh pet has no buffs
            0,                                    # alive (DEAD state absent)
            role.get('sex') if role.get('sex') is not None else 0,
            level,
            float(self.role_attribute_map(role)['7']),
            '0',                                  # getQizhanbinqiId null -> '0'
        ]
        return frame(amf3_encode(['23009', [record]]))

    def zuoqi_info(self):
        """Command 12102: StageInfoAction.zuoqiInfo -> outpuZuoqiInfo's Object[8].

        [mount, level, skills, clothes, longhun, longling, zhanli,
        skillBook]. Mount and level come from zuoqi_info and ZuoJiBiao;
        longhun/longling are PropUtil.getLonglingLonghunCount over the
        role's attribute-goods map (skill-33 total, then skill-35 total).
        The rest lives in tables the migration does not carry
        (role_zuoqi_skill, clothes, zhanli computation), which is exactly
        what Java returns from those sources when they are empty: null/0.
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        mount, level = 0, 0
        info = decode_zuoqi_info(role.get('zuoqi_info')) if role else None
        if info is not None:
            mount = int(info.get('id') or 0)
            if mount > 0:
                pet = (self.config.zuoqi_pet(mount, role.get('level'))
                       if self.config is not None else None)
                if pet is None:
                    log.info('conn %d: 12102 without ZuoJiBiao rank %s',
                             self.conn_id, mount)
                else:
                    level = pet[0]
        hun = ling = 0
        if role is not None and self.config is not None:
            try:
                stored = self.get_role_zuoqi(role.get('id')) or {}
            except Exception:
                stored = {}
            ling, hun = self.config.longling_longhun_counts(
                self._zuoqi_att_map(stored))
        return frame(amf3_encode(
            ['12102', [mount, level, None, None, hun, ling, 0, None]]))

    def map_type_for(self, map_id):
        """MapLine maptype for a map; logs and uses DEFAULT_MAP_TYPE when unknown."""
        map_type = self.config.map_type(map_id) if self.config is not None else None
        if map_type is None:
            map_type = DEFAULT_MAP_TYPE
            log.info('conn %d: map %r has no known MapLine type, using %d',
                     self.conn_id, map_id, map_type)
        return map_type

    def recive_yb_claim(self):
        """Command 35012: AccountServiceImpl.reciveYb moves pending YB into lingshi.

        Success pushes 32010 then replies [1, claimed]; nothing pending replies
        [0, 424016] and a lingshi overflow [0, 424017]. Negative pending resets to 0.
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        if not roles:
            return None
        role = roles[0]
        pending = int(role.get('recive_yb') or 0)
        lingshi = int(role.get('lingshi') or 0)
        if pending <= 0:
            if pending < 0:
                self.save_role_state(role['id'], recive_yb=0)
            return frame(amf3_encode(['35012', [0, RECIVE_YB_ERR_ZERO]]))
        if INT64_MAX - lingshi < pending:
            return frame(amf3_encode(['35012', [0, RECIVE_YB_ERR_OVERFLOW]]))
        self.save_role_state(role['id'], recive_yb=0, lingshi=lingshi + pending)
        claimed = dict(role, recive_yb=0, lingshi=lingshi + pending)
        return (self.money_info(claimed),
                frame(amf3_encode(['35012', [1, pending]])))

    def role_query_by_name(self, msg):
        """Command 12200: RoleAction.queryRoleByName lists roles whose name contains the query.

        C> [12200, name]. A blank or missing name answers an empty list.
        """
        name = self.safe(msg, 1, None)
        rows = []
        if isinstance(name, str) and name:
            rows = [[str(r['id']), r['name'], r['sex'], r['face'], r['level'],
                     r['job']] for r in self.find_roles_by_name(name)]
        return frame(amf3_encode(['12200', rows]))

    def money_info(self, role=None):
        """Command 32010: CreateAccountOutPut.getMoneyChange.

        [RoleAccount.tongqian, UserAccount.lingshi,
        RoleAccount.bindLingshi, AccountConstants.NOTIFYORNOT]. The Java
        Longs serialize as AMF3 doubles and the last slot is the constant
        1, not the recive flag (that lives on the account row behind
        35011).
        """
        if role is None:
            roles = self.get_roles(self.authed_user or '', self.server_id or '')
            role = roles[0] if roles else {}

        def _money(value):
            try:
                return float(value or 0)
            except (TypeError, ValueError):
                return 0.0
        return frame(amf3_encode(['32010', [_money(role.get('tongqian')),
                                             _money(role.get('lingshi')),
                                             _money(role.get('bind_lingshi')),
                                             1]]))

    def role_extra_info(self):
        """Command 12011: RoleAdditionalDataOutput.info.

        [zuoqiRank, pkVal, isShutUp, remainFreeCount, longhun, longhun,
        hasYuxi, guozhanZhiwei, binQiId, isGoldEquip, junGonglv]. Sources
        without migrated rows read as their Java defaults (0/None), which
        is exactly the fresh-role capture [0,0,0,0,0,0,0,None,None,0,1].
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else {}
        info = decode_zuoqi_info(role.get('zuoqi_info'))
        try:
            rank = int((info or {}).get('id') or 0)
        except (TypeError, ValueError):
            rank = 0
        try:
            remain_free = int(role.get('free_fly_count') or 0)
        except (TypeError, ValueError):
            remain_free = 0
        values = [rank, 0, 0, remain_free, 0, 0, 0, None, None, 0, 1]
        return frame(amf3_encode(['12011', values]))

    def fighting_info(self):
        """Command 12010: ZhanDouLiWrapper.getFightObject's Object[25].

        Slot layout from bytecode: [0]=5 equip fights, [1]=roleLevel,
        [2]=[skill,kangxin], [3]=[zuoqi,zuoqiEquip,longhun], [4]=[baoshi,
        baixiao], [5]=vip, [6]=3 shenjiang fights,        [7]=pozhen, [8]=meiren,
        [9]=shuxindan, [10]=[qizhanbingqi,binhun], [11]=xianjie,
        [12]=chenghao, [13]=zuoqiBook, [14]=qiBinBook, [15]=taozhuang,
        [16]=3 guangyi fights, [17]=wuhun, [18]=touxian, [19]=zuwu,
        [20]=guild, [21]=yuanshen, [22]=shenqi, [23]=2 pet fights,
        [24]=hunjie. Computed slots come from migrated gear/dan/vip/level
        rows via ZhanLiXiShu; the rest stay 0 (their source tables are not
        migrated, and Java's int fields default to 0 from empty sources).
        Slot [3] is [zuoqiJichu, zuoqiEquip, longhun]: the base mount
        fight from role_zuoqi.rank, the mount-gear fight over the
        [-105, -100] equip rows (none exist for any legacy role), and
        the longhun fight over the role's attribute-goods map (0 for
        every legacy role, whose attribute_goods_id is NULL).
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        level, base, qianghua, fujia, dan, vip = 0, 0, 0, 0, 0, 0
        pozhen = 0
        zuoqi, zuoqi_equip, longhun, xianjie = 0, 0, 0, 0
        skill_pair = [0, 0]
        shenjiang_slot = [0, 0, 0]
        if role is not None and self.config is not None:
            level = self.config.level_fight(
                self.config.role_attribute_row(role.get('level')))
            try:
                items = self.get_role_equip(role.get('id')) or []
            except Exception:
                items = []
            base, qianghua, fujia = self.config.equip_fight_parts(items)
            zuoqi_equip = self.config.zuoqi_equip_fight(items)
            try:
                mount = self.get_role_zuoqi(role.get('id')) or {}
            except Exception:
                mount = {}
            zuoqi = self.config.zuoqi_fight(mount.get('zuoqi_rank'),
                                            role.get('level'))
            try:
                longhun = self.config.zuoqi_longhun_fight(
                    mount.get('zuoqi_rank'), role.get('level'),
                    self._zuoqi_att_map(mount))
            except Exception:
                longhun = 0
            try:
                skills = self.get_role_skills(role.get('id')) or []
            except Exception:
                skills = []
            skill_pair = self.config.skill_fight(skills)
            try:
                shenjiang = self.get_role_shenjiang(role.get('id')) or []
            except Exception:
                shenjiang = []
            # [0] rank-based shenjiang fight and [1] jiangxingtu fight are not
            # ported yet; both are 0 for the captured role's legacy rows.
            shenjiang_slot = [0, 0, self.config.shenjiang_skill_upgrade_fight(shenjiang)]
            # ZhanDouLiServiceImpl.pozhenfight: getFight over the
            # cleared layer's attribute bag (0 with no progress: Java's
            # null map reads as no contribution from empty sources).
            if role is not None:
                try:
                    pozhen = self.config.fight_value(
                        self.pozhen_attribute_map(role.get('id')))
                except Exception:
                    pozhen = 0
            try:
                buffs = self.get_role_attr_buffs(role.get('id')) or []
            except Exception:
                buffs = []
            dan = self.config.dan_fight(buffs)
            try:
                vip_row = self.get_role_vip(role.get('id'))
            except Exception:
                vip_row = None
            vip = self.config.vip_fight((vip_row or {}).get('vip_level'))
            try:
                stored = self.get_role_xianjiechenhao(role.get('id'))
            except Exception:
                stored = None
            xianjie = self.config.xianjie_fight(self.xianjie_id_for(stored))
        return frame(amf3_encode(['12010', [
            [base, qianghua, fujia, 0, 0], level, skill_pair,
            [zuoqi, zuoqi_equip, longhun],
            [0, 0], vip, shenjiang_slot, pozhen, 0, dan, [0, 0], xianjie,
            0, 0, 0, 0, [0, 0, 0], 0, 0, 0, 0, 0, 0, [0, 0], 0]]))

    def equip_info(self):
        """Command 31000: RoleEquipSlotServiceImpl.getInfoEquip -> formart1(List).

        Sends one 18-field record per equipped slot, or null when there are
        none. Fields the legacy role_equip row lacks are documented in
        equip_record.
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        items = self.get_role_equip(role.get('id')) or []
        records = [self.equip_record(role, item) for item in items]
        return frame(amf3_encode(['31000', records or None]))

    def equip_record(self, role, item):
        """One StoreGoodsOutput.formart1 record (18 slots) for an equipped row.

        Slots 1 (StoreGoods.id), 7 (bind), 8 (expire) and 4-count have no
        legacy column: the id is the goods id, count is 1 (gear does not
        stack), bind 0 and expire null. Slots 15 and 17 are Longs (0 for gear
        outside the exp-book and spirit categories).
        """
        vo = equip_vo(item.get('attributes'))
        fight = self.config.equip_item_fight(item) if self.config else 0
        return [
            str(item.get('goods_id')),                 # 0 goodsId
            str(item.get('goods_id')),                 # 1 StoreGoods.id (approximated)
            item.get('slot_num'),                      # 2 slotNum
            1,                                         # 3 count
            str(role.get('id')),                       # 4 userRoleId
            item.get('item_level') or 0,               # 5 itemLevel
            item.get('rare_level') or 0,               # 6 rareLevel
            0,                                         # 7 bind
            None,                                      # 8 expireTime
            _fujia_wire(fujia_client_map(vo)),         # 9 qhFuJiaAttrClient
            xingxing_lv(vo),                           # 10 xingxingLv
            None,                                      # 11
            fight,                                     # 12 zhanli
            '',                                        # 13
            qh_xingxings_client(vo),                   # 14 qhXingXingsClient
            0.0,                                       # 15 exp (Long)
            0,                                         # 16 luckyValue
            0.0,                                       # 17 jingyanyu exp (Long)
        ]

    @staticmethod
    def _lottery_roll(odds):
        """Lottery.roll(odds, TENTHOUSAND): rand10000 <= int(odds*10000)."""
        try:
            quota = int(float(odds) * 10000)
        except (TypeError, ValueError):
            return False
        if quota <= 0:
            return False
        return random.randrange(10000) <= quota

    @staticmethod
    def _lottery_success(rate):
        """Lottery.isSuccess: a fresh Random's nextFloat() under the rate."""
        try:
            return random.random() < float(rate)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _lottery_map_key(weight_map):
        """Lottery.randomMapKey: uniform pick over the map's keys."""
        keys = list(weight_map or {})
        if not keys:
            return None
        return random.choice(keys)

    @staticmethod
    def _lottery_weighted_key(weight_map):
        """Lottery.getRandomKey2: weighted pick; None when empty.

        Java walks a HashMap whose order is unspecified; ties across
        unequal weights can drift, like the getFight truncation note.
        """
        total, scaled = 0.0, []
        for key, weight in (weight_map or {}).items():
            try:
                total += float(weight)
            except (TypeError, ValueError):
                continue
            scaled.append((key, total))
        if total <= 0:
            return None
        draw = random.random() * total
        for key, edge in scaled:
            if draw < edge:
                return key
        return scaled[-1][0]

    @staticmethod
    def _fj_pairs(vo):
        """fjattrstr {slot: 'id@count'} parsed to {slot: [id, count]}."""
        try:
            raw = json.loads(vo.get('fjattrstr') or '{}')
        except ValueError:
            return {}
        if not isinstance(raw, dict):
            return {}
        out = {}
        for slot, text in raw.items():
            try:
                key = int(slot)
            except (TypeError, ValueError):
                continue
            fid, _, count = str(text or '').partition('@')
            try:
                out[key] = [int(fid), int(count)]
            except (TypeError, ValueError):
                continue
        return out

    def _fj_get(self, vo, slot):
        """GoodsEquipVo.getfujiaId: winner id in a slot, or None."""
        pair = self._fj_pairs(vo).get(slot)
        return pair[0] if pair else None

    def _fj_key(self, vo, slot):
        """GoodsEquipVo.getKeyFuJiaId: winner id, 0 when the slot is empty."""
        pair = self._fj_pairs(vo).get(slot)
        return pair[0] if pair else 0

    def _fj_count(self, vo, slot):
        """GoodsEquipVo.getKeycount: appraised count, 0 when empty."""
        pair = self._fj_pairs(vo).get(slot)
        return pair[1] if pair else 0

    def _fj_exists(self, vo, slot):
        """GoodsEquipVo.isExist: whether a slot already holds an affix."""
        return slot in self._fj_pairs(vo)

    @staticmethod
    def _fj_blob(item, slot, fid, add):
        """GoodsEquipVo.toString after addfuJiaAount(slot[, fid], add).

        The 2-arg form adds onto the stored id; the 3-arg form opens an
        empty slot as fid@add. Goldens parse the JSON, never the string.
        """
        try:
            data = json.loads(item.get('attributes') or '')
            if not isinstance(data, dict):
                data = {}
        except ValueError:
            data = {}
        try:
            raw = json.loads(data.get('fjattrstr') or '{}')
            if not isinstance(raw, dict):
                raw = {}
        except ValueError:
            raw = {}
        key = str(slot)
        if key in raw:
            old, _, count = str(raw[key]).partition('@')
            try:
                add += int(count)
            except (TypeError, ValueError):
                pass
            raw[key] = f'{old}@{add}'
        else:
            raw[key] = f'{fid}@{add}'
        data['fjattrstr'] = json.dumps(raw, separators=(',', ':'))
        return json.dumps(data, separators=(',', ':'))

    @staticmethod
    def _fj_clear_blob(item, slot):
        """GoodsEquipVo.toString after clearFujiaAttribute(slot)."""
        try:
            data = json.loads(item.get('attributes') or '')
            if not isinstance(data, dict):
                data = {}
        except ValueError:
            data = {}
        try:
            raw = json.loads(data.get('fjattrstr') or '{}')
            if not isinstance(raw, dict):
                raw = {}
        except ValueError:
            raw = {}
        raw.pop(str(slot), None)
        data['fjattrstr'] = json.dumps(raw, separators=(',', ':'))
        return json.dumps(data, separators=(',', ':'))

    def _jd_lottery_key(self, vo, pair, maxcount, rare):
        """RoleEquipSlotServiceImpl.lotteryKey: pair arg to fujia slot.

        Pairs are 1 -> (1, 2), 2 -> (3, 4), 3 -> (5, 6). An untouched
        pair opens its first slot; a half-filled pair fills the empty
        half; a full pair below cap lotteries evenly; a capped-out pair
        is -1. maxcount is the fujia max map at the gear's rare level.
        """
        try:
            first, second = {1: (1, 2), 2: (3, 4), 3: (5, 6)}[int(pair)]
        except (TypeError, ValueError, KeyError):
            first, second = 0, 0
        first_on = self._fj_exists(vo, first)
        second_on = self._fj_exists(vo, second)
        if not first_on and not second_on:
            return first
        if first_on and second_on:
            try:
                cap = int(maxcount.get(rare, 0))
            except (TypeError, ValueError, AttributeError):
                cap = 0
            first_full = self._fj_count(vo, first) >= cap
            second_full = self._fj_count(vo, second) >= cap
            if first_full and second_full:
                return -1
            if first_full:
                return second
            if second_full:
                return first
            return self._lottery_weighted_key({first: 1.0, second: 1.0})
        return second if first_on else first

    def _equip_row(self, rid, equip_id):
        """Equipped row addressed by slot number string.

        Java keys RoleEquipSlot by its string id, which has no legacy
        column here, so the port matches str(slot_num) (documented with
        the StoreGoods.id approximation in equip_record).
        """
        try:
            items = self.get_role_equip(rid) or []
        except Exception:
            return None
        for item in items:
            if str(item.get('slot_num')) == str(equip_id):
                return item
        return None

    def _equip_persist(self, rid, row, attributes):
        """Rewrite the role's equip rows with one attributes blob replaced."""
        try:
            items = self.get_role_equip(rid) or []
        except Exception:
            return
        out = []
        for item in items:
            if item is row or (item.get('slot_num') == row.get('slot_num')
                               and item.get('goods_id') == row.get('goods_id')):
                item = dict(item, attributes=attributes)
            out.append(item)
        try:
            self.save_role_equip(rid, out)
        except Exception:
            pass

    @staticmethod
    def _vo_enhanced_blob(item, new_qh, star_bit):
        """GoodsEquipVo.toString after setQhcount + addQhxingxing.

        addQhxingxing appends a [level, 1|0] pair, creating the array when
        the blob has none. Goldens compare the parsed JSON, never the raw
        string, so key order is not pinned.
        """
        try:
            data = json.loads(item.get('attributes') or '')
            if not isinstance(data, dict):
                data = {}
        except ValueError:
            data = {}
        try:
            stars = json.loads(data.get('qhxingxing') or '')
            if not isinstance(stars, list):
                stars = []
        except ValueError:
            stars = []
        stars.append([new_qh, 1 if star_bit else 0])
        data['qhcount'] = new_qh
        data['qhxingxing'] = json.dumps(stars, separators=(',', ':'))
        return json.dumps(data, separators=(',', ':'))

    def _equip_formart(self, role, item):
        """StoreGoodsOutput.formart: the 18 record slots as a string-keyed map."""
        return {str(i): value
                for i, value in enumerate(self.equip_record(role, item))}

    def _equip_role(self):
        """First authed role, re-read so money checks see live balances."""
        try:
            roles = self.get_roles(self.authed_user or '',
                                   self.server_id or '')
        except Exception:
            return None
        return roles[0] if roles else None

    @staticmethod
    def _equip_is_worn(slot):
        """EquipSlotUtils.isEquipSlot: worn band (-105, 0)."""
        try:
            return -105 < int(slot) < 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _equip_is_bag(slot):
        """EquipSlotUtils.isBagSlot: bag band [1, 150]."""
        try:
            return 1 <= int(slot) <= 150
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _equip_move_pair(first, second):
        """StoreGoodsOutput.formatMove [id, slot, count, bind] pair."""
        return [first, second]

    def _equip_worn_row(self, rid, slot):
        """Worn row at a slot, or None (isEquipNull reads occupied)."""
        try:
            items = self.get_role_equip(rid) or []
        except Exception:
            return None
        for item in items:
            try:
                if int(item.get('slot_num')) == int(slot):
                    return item
            except (TypeError, ValueError):
                continue
        return None

    def _equip_persist_worn(self, rid, rows):
        """Replace the worn set (addEquip/cacheDelete/removeEquip write through)."""
        try:
            self.save_role_equip(rid, rows)
        except Exception:
            pass

    @staticmethod
    def _equip_without(items, slot):
        """Worn rows except one slot (int-compared like the lookup)."""
        out = []
        for item in items or []:
            try:
                if int(item.get('slot_num')) == int(slot):
                    continue
            except (TypeError, ValueError):
                pass
            out.append(dict(item))
        return out

    def _equip_wear_gates(self, role, cfg, worn_slot):
        """checkEquip gate chain; an error list or None when wearable.

        Missing numeric cells stay silent (Java unboxes null into an
        NPE). The yuanshen gate cannot fire: goods rows carry no
        yuanshen cell, matching Java's int-default-0 skip.
        """
        if str(cfg.get('category')) != '20':
            return [0, EQUIP_ERROR_DRESS_NOTEQUIP]
        job = cfg.get('job')
        if job is None:
            return None
        if str(job) != '0' and str(role.get('job')) != str(job):
            return [0, EQUIP_ERROR_DRESS_JOB]
        try:
            eqpart = int(cfg.get('eqpart'))
        except (TypeError, ValueError):
            return None
        if -eqpart != worn_slot:
            return [0, EQUIP_ERROR_DRESS_BADSLOT]
        if 101 <= eqpart <= 104:
            try:
                mount = self.get_role_zuoqi(role.get('id')) or {}
                rank = int(mount.get('zuoqi_rank') or 0)
                need = int(cfg.get('levelreq'))
            except (TypeError, ValueError):
                return None
            if rank < need:
                return [0, EQUIP_ERROR_DRESS_ZUOQIRANK]
            return None
        try:
            need = int(cfg.get('levelreq'))
            level = int(role.get('level') or 0)
        except (TypeError, ValueError):
            return None
        if level < need:
            return [0, EQUIP_ERROR_DRESS_LEVEL]
        try:
            sex_need = int(cfg.get('sexreq'))
            sex = int(role.get('sex') or 0)
        except (TypeError, ValueError):
            return None
        if sex_need != 2 and sex != sex_need:
            return [0, EQUIP_ERROR_DRESS_SEX]
        return None

    def equip_dress(self, msg):
        """Command 31001: EquipAction.dressEquip -> dress/peiDai/unLoad.

        C> [equipId, fromSlot, toSlot]. Bag->worn wears, worn->bag
        takes off; any other band pairing stays silent (Java returns
        null). Replies are [1, info, xingxingLv] with a formatMove
        pair; errors are [0, code] (the zuoqi-rank [0, 31036] excepted).
        Worn ids read as goods ids and worn bind as 0, like the 31000
        record; events need a bus.
        """
        data = self.safe(msg, 1)
        try:
            equip_id, from_slot, to_slot = data[0], data[1], data[2]
        except (TypeError, IndexError):
            return None
        if not isinstance(equip_id, str):
            return None
        for slot in (from_slot, to_slot):
            if isinstance(slot, bool) or not isinstance(slot, int):
                return None
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        if self._equip_is_bag(from_slot) and self._equip_is_worn(to_slot):
            return self._equip_wear(role, equip_id, from_slot, to_slot)
        if self._equip_is_worn(from_slot) and self._equip_is_bag(to_slot):
            return self._equip_unwear(role, from_slot, to_slot)
        return None

    def _equip_wear(self, role, equip_id, bag_slot, worn_slot):
        """peiDaiEquip: bag gear moves onto a worn slot (swap when taken)."""
        rid = role.get('id')
        try:
            bag = self.get_role_bag_slot(rid, bag_slot)
        except Exception:
            bag = None
        if bag is None:
            return frame(amf3_encode(
                [str(CMD_EQUIP_DRESS), [0, EQUIP_ERROR_NOSLOT]]))
        if bag.get('bag_id') != equip_id:
            return frame(amf3_encode(
                [str(CMD_EQUIP_DRESS), [0, EQUIP_ERROR_DRESS_MISMATCH]]))
        try:
            cfg = self.config._goods_table().get(str(bag.get('goods_id')))
        except Exception:
            cfg = None
        if cfg is None:
            return frame(amf3_encode(
                [str(CMD_EQUIP_DRESS), [0, EQUIP_ERROR_DRESS_NOCONFIG]]))
        gates = self._equip_wear_gates(role, cfg, worn_slot)
        if gates is not None:
            return frame(amf3_encode([str(CMD_EQUIP_DRESS), gates]))
        try:
            locked = int(cfg.get('equiplocked') or 0)
        except (TypeError, ValueError):
            locked = 0
        try:
            bag_bind = int(bag.get('bind') or 0)
        except (TypeError, ValueError):
            bag_bind = 0
        bind = 1 if locked else bag_bind
        try:
            items = self.get_role_equip(rid) or []
        except Exception:
            items = []
        old = self._equip_worn_row(rid, worn_slot)
        new = {'slot_num': worn_slot, 'goods_id': bag.get('goods_id'),
               'rare_level': bag.get('rare_level') or 0,
               'item_level': bag.get('item_level') or 0,
               'attributes': bag.get('attributes')}
        kept = self._equip_without(items, worn_slot)
        kept.append(new)
        self._equip_persist_worn(rid, kept)
        try:
            self.delete_role_bag_slot(rid, bag_slot)
        except Exception:
            pass
        xing = xingxing_lv(equip_vo(new.get('attributes')))
        if old is None:
            info = self._equip_move_pair(
                None, [new['goods_id'], worn_slot, 1, bind])
        else:
            try:
                self.insert_role_bag_slot(
                    rid, {'slot_num': bag_slot,
                          'goods_id': old.get('goods_id'), 'count': 1,
                          'bind': 0, 'expire_time': None,
                          'rare_level': old.get('rare_level') or 0,
                          'item_level': old.get('item_level') or 0,
                          'attributes': old.get('attributes')})
            except Exception:
                pass
            info = self._equip_move_pair(
                [new['goods_id'], worn_slot, 1, bind],
                [old.get('goods_id'), bag_slot, 1, 0])
        return frame(amf3_encode(
            [str(CMD_EQUIP_DRESS), [1, info, xing]]))

    def _equip_unwear(self, role, worn_slot, bag_slot):
        """unLoadEquip: worn gear moves back to an empty bag slot."""
        rid = role.get('id')
        worn = self._equip_worn_row(rid, worn_slot)
        if worn is None:
            return frame(amf3_encode(
                [str(CMD_EQUIP_DRESS), [0, EQUIP_ERROR_DRESS_MISMATCH]]))
        if not self._prop_fits(rid, {'goods': worn.get('goods_id'),
                                     'count': 1}, 0):
            return frame(amf3_encode(
                [str(CMD_EQUIP_DRESS), [0, EQUIP_ERROR_DRESS_NOROOM]]))
        try:
            target = self.get_role_bag_slot(rid, bag_slot)
        except Exception:
            target = None
        if target is not None:
            return frame(amf3_encode(
                [str(CMD_EQUIP_DRESS), [0, EQUIP_ERROR_DRESS_MISMATCH]]))
        try:
            items = self.get_role_equip(rid) or []
        except Exception:
            items = []
        self._equip_persist_worn(rid, self._equip_without(items, worn_slot))
        try:
            self.insert_role_bag_slot(
                rid, {'slot_num': bag_slot,
                      'goods_id': worn.get('goods_id'), 'count': 1,
                      'bind': 0, 'expire_time': None,
                      'rare_level': worn.get('rare_level') or 0,
                      'item_level': worn.get('item_level') or 0,
                      'attributes': worn.get('attributes')})
        except Exception:
            pass
        try:
            landed = self.get_role_bag_slot(rid, bag_slot)
        except Exception:
            landed = None
        if landed is None:
            landed = {'bag_id': worn.get('goods_id'), 'slot_num': bag_slot,
                      'count': 1, 'bind': 0}
        info = self._equip_move_pair(
            [worn.get('goods_id'), worn_slot, 1, 0],
            [landed.get('bag_id'), bag_slot,
             landed.get('count') or 1, landed.get('bind') or 0])
        return frame(amf3_encode(
            [str(CMD_EQUIP_DRESS), [1, info, 0]]))

    def equip_qianghua(self, msg):
        """Command 34000: EquipAction.equipQianghua -> qiangHuaEquip.

        C> [equipId, flagIntOrNull, slotIntOrNull]. Unknown slots are
        silent (the service returns null); config gaps are silent too
        (Java would NPE on the missing row). At max level [0, 31009],
        non-enhanceable gear [0, 31010], short YXB [0, 31011], missing
        materials [0, 31012], short gold YB [0, 1002]. Costs are consumed
        before the roll, and the fail branch still bumps qhcount (literal
        Java quirk, golden-pinned). Success with qhNotice pushes 11101
        [31015, [roleName, 0, newQh]]; both outcomes push 30106 [formart]
        before the [1|-1, equipId] reply. The flag-true mall auto-buy has
        no ported mall behind it, so materials must be in the bag either
        way (documented gap). Event publishes have no bus, as elsewhere.
        """
        args = self.safe(msg, 1, []) or []
        equip_id = self.safe(args, 0)
        flag_raw = self.safe(args, 1)
        slot_raw = self.safe(args, 2)
        try:
            flag = int(flag_raw or 0) != 0
        except (TypeError, ValueError):
            flag = False
        try:
            slot = int(slot_raw)
        except (TypeError, ValueError):
            slot = None
        role = self._equip_role()
        if role is None or equip_id is None or self.config is None:
            return None
        rid = role.get('id')
        row = self._equip_row(rid, equip_id)
        if row is None:
            return None
        vo = equip_vo(row.get('attributes'))
        try:
            qh = int(vo.get('qhcount') or 0)
        except (TypeError, ValueError):
            qh = 0
        cfg = self.config.qianghua_config(row.get('goods_id'), qh)
        if cfg is None:
            return None
        if qh >= cfg['maxQhLevel']:
            return frame(amf3_encode(
                [str(CMD_EQUIP_QIANGHUA), [0, EQUIP_ERROR_MAXED]]))
        if not cfg['isQianghua']:
            return frame(amf3_encode(
                [str(CMD_EQUIP_QIANGHUA), [0, EQUIP_ERROR_NOQH]]))
        role = self._equip_role()
        if self._bag_money_first(role, cfg['qhJb'], ['YXB']) is None:
            return frame(amf3_encode(
                [str(CMD_EQUIP_QIANGHUA), [0, EQUIP_ERROR_MONEY]]))
        for gid, need in cfg['costGoods'].items():
            if self._task_goods_count(rid, gid) < need:
                return frame(amf3_encode(
                    [str(CMD_EQUIP_QIANGHUA), [0, EQUIP_ERROR_GOODS]]))
        bonus, extra_type, extra = 0.0, None, 0
        if slot is not None and slot > 0:
            pair = cfg['goldOrGaiLv'].get(slot)
            if pair:
                bonus = pair[0]
                try:
                    extra = int(1.0 / pair[1]) if pair[1] else 0
                except (TypeError, ValueError, ZeroDivisionError):
                    extra = 0
                if extra > 0:
                    found = self._bag_money_first(
                        role, extra, ['BIND_YB', 'YB'])
                    if found is None:
                        return frame(amf3_encode(
                            [str(CMD_EQUIP_QIANGHUA),
                             [0, GENERAL_YB_SHORT]]))
                    extra_type = found[0]
        self._bag_money_decr(rid, 'YXB', cfg['qhJb'])
        for gid, need in cfg['costGoods'].items():
            self._prop_take(rid, gid, need)
        if extra_type is not None:
            self._bag_money_decr(rid, extra_type, extra)
        try:
            odds = float(cfg['qhodds']) + bonus
        except (TypeError, ValueError):
            odds = 0.0
        ok = self._lottery_roll(odds)
        new_qh = qh + 1
        self._equip_persist(
            rid, row, self._vo_enhanced_blob(row, new_qh, ok))
        role = self._equip_role()
        frames = []
        if ok and cfg['qhNotice']:
            frames.append(frame(amf3_encode(
                [str(CMD_NOTICE_ALL),
                 [str(CMD_EQUIP_NOTICE),
                  [str(role.get('name')), 0, new_qh]]])))
        frames.append(frame(amf3_encode(
            [str(CMD_EQUIP_CHANGE), [self._equip_formart(role, dict(
                row, attributes=self._vo_enhanced_blob(
                    row, new_qh, ok)))]])))
        frames.append(frame(amf3_encode(
            [str(CMD_EQUIP_QIANGHUA), [1 if ok else -1, str(equip_id)]])))
        log.info('conn %d: qianghua %r %s (events skipped, no bus)',
                 self.conn_id, row.get('goods_id'),
                 'success' if ok else 'fail')
        return tuple(frames)

    def equip_jinjie(self, msg):
        """Command 34001: EquipAction.equipJinjie -> jinJieEquip.

        C> [equipId, flagIntOrNull]. Unknown slots and config gaps are
        silent (null return / missing row). Gates in order: !permitjj or
        missing target goods [0, 31013], role level below the target
        levelreq [0, 1000], short YXB(jjcostcoin) [0, 31011], missing
        materials [0, 31012] (flag-true mall auto-buy shares the enhance
        slice's documented gap). Costs burn before the pity roll: fails
        below min fail outright, fails at/above max always succeed, else
        Lottery.roll(jjodds). Success swaps goodsId/itemLevel/qhcount to
        the target row, pushes 11101 [31016, [roleName, oldName, newName]]
        and 30106 [formart], and replies [1, id]; fail bumps the fail
        count, pushes only 30106, and replies [-1, id]. Events need a bus.
        """
        args = self.safe(msg, 1, []) or []
        equip_id = self.safe(args, 0)
        role = self._equip_role()
        if role is None or equip_id is None or self.config is None:
            return None
        rid = role.get('id')
        row = self._equip_row(rid, equip_id)
        if row is None:
            return None
        vo = equip_vo(row.get('attributes'))
        try:
            qh = int(vo.get('qhcount') or 0)
        except (TypeError, ValueError):
            qh = 0
        try:
            fails = int(vo.get('jjfailcount') or 0)
        except (TypeError, ValueError):
            fails = 0
        cfg = self.config.qianghua_config(row.get('goods_id'), qh)
        target = None
        if cfg is not None and cfg['isPermitjj'] and cfg['jjEquipId']:
            target = self.config._goods_table().get(cfg['jjEquipId'])
        if cfg is None or not cfg['isPermitjj'] or target is None:
            return frame(amf3_encode(
                [str(CMD_EQUIP_JINJIE), [0, EQUIP_ERROR_NOJJ]]))
        try:
            need_lv = int(target.get('levelreq') or 0)
        except (TypeError, ValueError):
            need_lv = 0
        try:
            role_lv = int(role.get('level') or 0)
        except (TypeError, ValueError):
            role_lv = 0
        if role_lv < need_lv:
            return frame(amf3_encode(
                [str(CMD_EQUIP_JINJIE), [0, GENERAL_LEVEL]]))
        role = self._equip_role()
        if self._bag_money_first(role, cfg['jjCostCoin'], ['YXB']) is None:
            return frame(amf3_encode(
                [str(CMD_EQUIP_JINJIE), [0, EQUIP_ERROR_MONEY]]))
        for gid, need in cfg['jjCostGoods'].items():
            if self._task_goods_count(rid, gid) < need:
                return frame(amf3_encode(
                    [str(CMD_EQUIP_JINJIE), [0, EQUIP_ERROR_GOODS]]))
        self._bag_money_decr(rid, 'YXB', cfg['jjCostCoin'])
        for gid, need in cfg['jjCostGoods'].items():
            self._prop_take(rid, gid, need)
        try:
            odds = float(cfg['jjodds'])
        except (TypeError, ValueError):
            odds = 0.0
        if fails < cfg['jjMinTimes']:
            ok = False
        elif fails >= cfg['jjMaxTimes']:
            ok = True
        else:
            ok = self._lottery_roll(odds)
        try:
            data = json.loads(row.get('attributes') or '')
            if not isinstance(data, dict):
                data = {}
        except ValueError:
            data = {}
        if ok:
            try:
                item_lv = int(target.get('itemlevel') or 0)
            except (TypeError, ValueError):
                item_lv = 0
            data['jjfailcount'] = 0
            data['qhcount'] = cfg['jjEquipQhLevel']
            new_row = dict(row, goods_id=cfg['jjEquipId'],
                           item_level=item_lv,
                           attributes=json.dumps(data, separators=(',', ':')))
        else:
            data['jjfailcount'] = fails + 1
            new_row = dict(row, attributes=json.dumps(
                data, separators=(',', ':')))
        try:
            items = self.get_role_equip(rid) or []
        except Exception:
            items = []
        self.save_role_equip(
            rid, [new_row if it is row or
                  (it.get('slot_num') == row.get('slot_num') and
                   it.get('goods_id') == row.get('goods_id')) else it
                  for it in items])
        role = self._equip_role()
        frames = []
        if ok:
            old_name = str((self.config._goods_table().get(
                str(row.get('goods_id'))) or {}).get('name')
                or row.get('goods_id'))
            frames.append(frame(amf3_encode(
                [str(CMD_NOTICE_ALL),
                 [str(CMD_EQUIP_JINJIE_NOTICE),
                  [str(role.get('name')), old_name,
                   str(target.get('name') or cfg['jjEquipId'])]]])))
        frames.append(frame(amf3_encode(
            [str(CMD_EQUIP_CHANGE), [self._equip_formart(role, new_row)]])))
        frames.append(frame(amf3_encode(
            [str(CMD_EQUIP_JINJIE), [1 if ok else -1, str(equip_id)]])))
        log.info('conn %d: jinjie %r -> %s (events skipped, no bus)',
                 self.conn_id, row.get('goods_id'),
                 cfg['jjEquipId'] if ok else 'fail')
        return tuple(frames)

    def _jd_equip_load(self, rid, equip_id):
        """JianDing slot-or-bag gear load: (row, from_bag)."""
        row = self._equip_row(rid, equip_id)
        if row is not None:
            return row, False
        try:
            row = self.get_role_bag_slot_by_bag_id(rid, str(equip_id))
        except Exception:
            row = None
        if row is None:
            return None, False
        return row, True

    def _jd_persist(self, rid, row, from_bag, attributes):
        """Rewrite one gear blob after a fujia change."""
        if from_bag:
            try:
                self.update_role_bag_slot(rid, row.get('slot_num'),
                                          attributes=attributes)
            except Exception:
                pass
        else:
            self._equip_persist(rid, row, attributes)

    def equip_jianding(self, msg):
        """Command 34004: EquipAction.jianDing -> jianDing.

        C> [equipId, materialGuid, pairInt] where pairInt 1..3 selects a
        fujia slot pair. Gates in order: unknown gear or material
        [0, 31001], gear not appraisable [0, 31027], equip material
        without the cailiao flag [0, 31028], material itemLevel mismatch
        [0, 31020], capped-out pair [0, 31021], vip AND role level both
        short [0, 31016], equip material with star level short [0, 31017],
        short YXB [0, 1003]. Costs burn first: YXB, then one material
        (count-decrement for cailiao-category stones, whole-row removal
        otherwise). An empty slot rolls its winner uniformly; a filled
        slot keeps its winner. Stone-category materials force success,
        else Lottery.isSuccess on the (winner, fuJiaLevel) rate at the
        gear's rare level. Success rolls a weighted count (capped at the
        rare max) onto a filled slot or opens an empty one at the rare
        minimum, bumps the jianding count, pushes 30106 [formart], and
        replies [1, guid, slot, keyId, keyCount, rolled, 0]. Failure adds
        capped role-level exp to the jianding pool and the role (12001),
        and replies [1, guid, slot, 0, 0, 0, added]. A bound stone binds
        bag-living gear; equipped rows have no bind column (documented).
        Events need a bus.
        """
        args = self.safe(msg, 1, []) or []
        equip_id = self.safe(args, 0)
        mat_guid = self.safe(args, 1)
        try:
            pair = int(self.safe(args, 2))
        except (TypeError, ValueError):
            pair = 0
        role = self._equip_role()
        if role is None or equip_id is None or mat_guid is None \
                or self.config is None:
            return None
        rid = role.get('id')
        row, from_bag = self._jd_equip_load(rid, equip_id)
        if row is None:
            return frame(amf3_encode(
                [str(CMD_EQUIP_JIANDING), [0, EQUIP_ERROR_NOSLOT]]))
        try:
            mat_row = self.get_role_bag_slot_by_bag_id(rid, str(mat_guid))
        except Exception:
            mat_row = None
        if mat_row is None:
            return frame(amf3_encode(
                [str(CMD_EQUIP_JIANDING), [0, EQUIP_ERROR_NOSLOT]]))
        goods = self.config._goods_table()
        grow = goods.get(str(row.get('goods_id'))) or {}
        mat_grow = goods.get(str(mat_row.get('goods_id'))) or {}
        try:
            appraisable = int(grow.get('jianding') or 0) != 0
        except (TypeError, ValueError):
            appraisable = False
        if not appraisable:
            return frame(amf3_encode(
                [str(CMD_EQUIP_JIANDING), [0, EQUIP_ERROR_JD_NOTJD]]))
        mat_cat = str(mat_grow.get('category') or '')
        try:
            mat_cailiao = int(mat_grow.get('jdcailiao') or 0) != 0
        except (TypeError, ValueError):
            mat_cailiao = False
        if mat_cat == GOODS_CATEGORY_EQUIP and not mat_cailiao:
            return frame(amf3_encode(
                [str(CMD_EQUIP_JIANDING), [0, EQUIP_ERROR_JD_MAT]]))
        try:
            same_lv = int(grow.get('itemlevel') or 0) == int(
                mat_grow.get('itemlevel') or 0)
        except (TypeError, ValueError):
            same_lv = False
        if not same_lv:
            return frame(amf3_encode(
                [str(CMD_EQUIP_JIANDING), [0, EQUIP_ERROR_JD_LVLMATCH]]))
        fcfg = self.config.fujia_config(str(row.get('goods_id')))
        if fcfg is None:
            return None
        try:
            rare = int(row.get('rare_level') or 0)
        except (TypeError, ValueError):
            rare = 0
        max_map = fcfg.get('rareMax') or {}
        vo = equip_vo(row.get('attributes'))
        slot = self._jd_lottery_key(vo, pair, max_map, rare)
        try:
            slot = int(slot)
        except (TypeError, ValueError):
            slot = -1
        if slot is None or slot < 0:
            return frame(amf3_encode(
                [str(CMD_EQUIP_JIANDING), [0, EQUIP_ERROR_JD_SLOT]]))
        cfg_slot = fcfg['slots'].get(slot)
        if cfg_slot is None:
            return None
        try:
            vip_row = self.get_role_vip(rid) or {}
        except Exception:
            vip_row = {}
        try:
            vip_lv = int(vip_row.get('vip_level') or 0)
        except (TypeError, ValueError):
            vip_lv = 0
        try:
            role_lv = int(role.get('level') or 0)
        except (TypeError, ValueError):
            role_lv = 0
        if cfg_slot['needVip'] > vip_lv and cfg_slot['needLv'] > role_lv:
            return frame(amf3_encode(
                [str(CMD_EQUIP_JIANDING), [0, EQUIP_ERROR_JD_VIPLV]]))
        if mat_cat == GOODS_CATEGORY_EQUIP and \
                xingxing_lv(vo) < cfg_slot['needEquipLv']:
            return frame(amf3_encode(
                [str(CMD_EQUIP_JIANDING), [0, EQUIP_ERROR_JD_EQLV]]))
        role = self._equip_role()
        if self._bag_money_first(role, cfg_slot['money'], ['YXB']) is None:
            return frame(amf3_encode(
                [str(CMD_EQUIP_JIANDING), [0, GENERAL_JB]]))
        self._bag_money_decr(rid, 'YXB', cfg_slot['money'])
        if mat_cat == GOODS_CATEGORY_JDCAILIAO:
            self._prop_decr(rid, mat_row)
        else:
            try:
                self.delete_role_bag_slot(rid, mat_row.get('slot_num'))
            except Exception:
                pass
        winner = self._fj_get(vo, slot)
        if winner is None:
            winner = self._lottery_map_key(
                {fid: 1.0 for fid in cfg_slot['ids']})
            if winner is None:
                return None
        rcfg = self.config.fujia_random(winner, fcfg['fuJiaLevel'])
        if rcfg is None:
            return None
        ok = self._lottery_success(rcfg['rates'].get(rare, 0))
        if mat_cat == GOODS_CATEGORY_JDCAILIAO:
            ok = True
        try:
            mat_bind = int(mat_row.get('bind') or 0)
        except (TypeError, ValueError):
            mat_bind = 0
        if mat_bind == 1 and from_bag:
            try:
                self.update_role_bag_slot(rid, row.get('slot_num'), bind=1)
                row = dict(row, bind=1)
            except Exception:
                pass
        now = int(time.time() * 1000)
        try:
            jd_row = self.get_role_jianding(rid) or {}
        except Exception:
            jd_row = {}
        try:
            jd_count = int(jd_row.get('jianding_count') or 0)
        except (TypeError, ValueError):
            jd_count = 0
        if ok:
            if self._fj_exists(vo, slot):
                rolled = self._lottery_weighted_key(
                    rcfg['counts'].get(rare) or {})
                if rolled is None:
                    return None
                try:
                    cap = int(max_map.get(rare, 0))
                except (TypeError, ValueError, AttributeError):
                    cap = 0
                cur = self._fj_count(vo, slot)
                if cur + rolled > cap:
                    rolled = cap - cur
                blob = self._fj_blob(row, slot, winner, rolled)
            else:
                rolled = 0
                try:
                    floor = int((fcfg.get('rareMin') or {}).get(rare, 0))
                except (TypeError, ValueError, AttributeError):
                    floor = 0
                blob = self._fj_blob(row, slot, winner, floor)
            self._jd_persist(rid, row, from_bag, blob)
            try:
                self.save_role_jianding(rid, jianding_count=jd_count + 1,
                                        jianding_time=now)
            except Exception:
                pass
            new_vo = equip_vo(blob)
            role = self._equip_role()
            new_row = dict(row, attributes=blob)
            return (frame(amf3_encode(
                [str(CMD_EQUIP_CHANGE),
                 [self._equip_formart(role, new_row)]])),
                frame(amf3_encode(
                    [str(CMD_EQUIP_JIANDING),
                     [1, str(equip_id), slot, self._fj_key(new_vo, slot),
                      self._fj_count(new_vo, slot), rolled, 0]])))
        try:
            add = int(fcfg['addexp'][0]) * role_lv + int(fcfg['addexp'][1])
        except (TypeError, ValueError, IndexError):
            add = 0
        cap_exp = self.config.zhujue_jdexp(role_lv)
        try:
            stored = int(jd_row.get('jianding_exp') or 0)
        except (TypeError, ValueError):
            stored = 0
        if stored + add > cap_exp:
            add = cap_exp - stored
        try:
            self.save_role_jianding(rid, jianding_count=jd_count + 1,
                                    jianding_time=now,
                                    jianding_exp=stored + add)
        except Exception:
            pass
        _total, _level, _gained, exp_frames = self._role_gain_exp(
            role, rid, add)
        return (*exp_frames,
                frame(amf3_encode(
                    [str(CMD_EQUIP_JIANDING),
                     [1, str(equip_id), slot, 0, 0, 0, add]])))

    def equip_jianding_clear(self, msg):
        """Command 34005: EquipAction.jianDingClear -> jianDingClear.

        C> [equipId, slotInt]. Unknown gear answers [0, 31001]. The
        slot's charm map is consumed when the bag covers it, else the
        slot's gold falls back to BIND_YB/YB ([0, 31015] when short).
        The affix is removed, 30106 [formart] precedes [1, equipId,
        slot]. Events need a bus.
        """
        args = self.safe(msg, 1, []) or []
        equip_id = self.safe(args, 0)
        try:
            slot = int(self.safe(args, 1))
        except (TypeError, ValueError):
            slot = None
        role = self._equip_role()
        if role is None or equip_id is None or slot is None \
                or self.config is None:
            return None
        rid = role.get('id')
        row, from_bag = self._jd_equip_load(rid, equip_id)
        if row is None:
            return frame(amf3_encode(
                [str(CMD_EQUIP_JIANDING_CLEAR), [0, EQUIP_ERROR_NOSLOT]]))
        fcfg = self.config.fujia_config(str(row.get('goods_id')))
        if fcfg is None:
            return None
        cfg_slot = fcfg['slots'].get(slot)
        if cfg_slot is None:
            return None
        charms = cfg_slot.get('clearGoods') or {}
        gold = cfg_slot.get('clearYb') or 0
        if charms and all(self._task_goods_count(rid, gid) >= need
                          for gid, need in charms.items()):
            for gid, need in charms.items():
                self._prop_take(rid, gid, need)
        else:
            role = self._equip_role()
            found = self._bag_money_first(role, gold, ['BIND_YB', 'YB'])
            if found is None:
                return frame(amf3_encode(
                    [str(CMD_EQUIP_JIANDING_CLEAR),
                     [0, EQUIP_ERROR_JD_NOGOLD]]))
            self._bag_money_decr(rid, found[0], found[1])
        blob = self._fj_clear_blob(row, slot)
        self._jd_persist(rid, row, from_bag, blob)
        role = self._equip_role()
        return (frame(amf3_encode(
            [str(CMD_EQUIP_CHANGE),
             [self._equip_formart(role, dict(row, attributes=blob))]])),
            frame(amf3_encode(
                [str(CMD_EQUIP_JIANDING_CLEAR),
                 [1, str(equip_id), slot]])))

    def equip_jianding_exp(self, msg):
        """Command 34006: EquipAction.getJianDingExp -> getJianDingExp.

        No arguments. A missing pool answers [0]; a pool from another
        day is reset before the [exp, hechengCount] reply.
        """
        role = self._equip_role()
        if role is None:
            return None
        rid = role.get('id')
        try:
            jd_row = self.get_role_jianding(rid)
        except Exception:
            jd_row = None
        if not jd_row:
            return frame(amf3_encode([str(CMD_EQUIP_JIANDING_EXP), [0]]))
        try:
            stamp = int(jd_row.get('jianding_time') or 0)
        except (TypeError, ValueError):
            stamp = 0
        now = int(time.time() * 1000)
        if time.localtime(stamp / 1000)[:3] != time.localtime(now / 1000)[:3]:
            try:
                self.save_role_jianding(rid, jianding_exp=0,
                                        jianding_time=now, jianding_count=0)
            except Exception:
                pass
            jd_row = dict(jd_row, jianding_exp=0, jianding_count=0)
        try:
            exp = int(jd_row.get('jianding_exp') or 0)
        except (TypeError, ValueError):
            exp = 0
        try:
            hecheng = int(jd_row.get('hecheng_count') or 0)
        except (TypeError, ValueError):
            hecheng = 0
        return frame(amf3_encode(
            [str(CMD_EQUIP_JIANDING_EXP), [exp, hecheng]]))

    def equip_hecheng(self, msg):
        """Command 34007: EquipAction.cailiaohechen -> heCheng.

        C> is 4 material guids, fused into the next-tier scroll.
        Gates in order: vip hecheng cap reached [0, 31026], arg count
        != 4 [0, 31022], unknown material [0, 31001], equip material
        without the cailiao flag [0, 31029, name], stone material under
        a non-juanzhou row [0, 31025], non-cailiao material [0, 31024],
        itemLevel mismatch [0, 31023], short synthesis stones [0, 1005],
        no bag room for the reward [0, 1006]. The 4 materials burn
        (count-decrement for cailiao-category stones, whole-row removal
        otherwise), the pool hecheng count bumps with fresh time, every
        reward lands with the any-bound flag, and the reply is [1]. The
        synthesis is deterministic (no lottery); events need a bus.
        """
        args = self.safe(msg, 1, []) or []
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        rid = role.get('id')
        try:
            jd_row = self.get_role_jianding(rid)
        except Exception:
            jd_row = None
        if jd_row is None:
            try:
                self.save_role_jianding(
                    rid, jianding_count=0, jianding_time=int(
                        time.time() * 1000), jianding_exp=0)
            except Exception:
                pass
            jd_row = {}
        try:
            vip_row = self.get_role_vip(rid) or {}
        except Exception:
            vip_row = {}
        try:
            vip_lv = int(vip_row.get('vip_level') or 0)
        except (TypeError, ValueError):
            vip_lv = 0
        try:
            made = jd_row.get('hecheng_count')
            made = int(made) if made is not None else None
        except (TypeError, ValueError):
            made = None
        if made is not None and \
                self.config.vip_hecheng(vip_lv) <= made:
            return frame(amf3_encode(
                [str(CMD_EQUIP_HECHENG), [0, EQUIP_ERROR_HC_LIMIT]]))
        if len(args) != 4:
            return frame(amf3_encode(
                [str(CMD_EQUIP_HECHENG), [0, EQUIP_ERROR_HC_ARGS]]))
        goods = self.config._goods_table()
        mats = []
        for guid in args:
            try:
                mat = self.get_role_bag_slot_by_bag_id(rid, str(guid))
            except Exception:
                mat = None
            if mat is None:
                return frame(amf3_encode(
                    [str(CMD_EQUIP_HECHENG), [0, EQUIP_ERROR_NOSLOT]]))
            mats.append(mat)
        try:
            first_lv = int((goods.get(str(mats[0].get('goods_id'))) or {})
                           .get('itemlevel') or 0)
        except (TypeError, ValueError):
            first_lv = 0
        jcfg = self.config.jianding_config(first_lv)
        if jcfg is None:
            return None
        bound = 0
        for mat in mats:
            grow = goods.get(str(mat.get('goods_id'))) or {}
            mat_cat = str(grow.get('category') or '')
            try:
                cailiao = int(grow.get('jdcailiao') or 0) != 0
            except (TypeError, ValueError):
                cailiao = False
            if mat_cat == GOODS_CATEGORY_EQUIP and not cailiao:
                return frame(amf3_encode(
                    [str(CMD_EQUIP_HECHENG),
                     [0, EQUIP_ERROR_HC_MAT,
                      str(grow.get('name') or mat.get('goods_id'))]]))
            if mat_cat != GOODS_CATEGORY_EQUIP:
                if mat_cat == GOODS_CATEGORY_JDCAILIAO:
                    if not jcfg['juanzhou']:
                        return frame(amf3_encode(
                            [str(CMD_EQUIP_HECHENG),
                             [0, EQUIP_ERROR_HC_JUAN]]))
                else:
                    return frame(amf3_encode(
                        [str(CMD_EQUIP_HECHENG),
                         [0, EQUIP_ERROR_HC_KIND]]))
            try:
                same = int(grow.get('itemlevel') or 0) == first_lv
            except (TypeError, ValueError):
                same = False
            if not same:
                return frame(amf3_encode(
                    [str(CMD_EQUIP_HECHENG), [0, EQUIP_ERROR_HC_LEVEL]]))
            try:
                if int(mat.get('bind') or 0) == 1:
                    bound = 1
            except (TypeError, ValueError):
                pass
        stones = jcfg['stones']
        if stones and any(self._task_goods_count(rid, gid) < need
                          for gid, need in stones.items()):
            return frame(amf3_encode(
                [str(CMD_EQUIP_HECHENG), [0, GENERAL_GOODS]]))
        for gid, need in stones.items():
            self._prop_take(rid, gid, need)
        for reward_gid, reward_count in jcfg['rewards']:
            if not self._prop_fits(
                    rid, {'goods': reward_gid, 'count': reward_count},
                    bound):
                return frame(amf3_encode(
                    [str(CMD_EQUIP_HECHENG), [0, GENERAL_NOSLOT]]))
        for mat in mats:
            grow = goods.get(str(mat.get('goods_id'))) or {}
            if str(grow.get('category') or '') == \
                    GOODS_CATEGORY_JDCAILIAO:
                self._prop_decr(rid, mat)
            else:
                try:
                    self.delete_role_bag_slot(rid, mat.get('slot_num'))
                except Exception:
                    pass
        try:
            self.save_role_jianding(
                rid, hecheng_count=(made or 0) + 1,
                hecheng_time=int(time.time() * 1000))
        except Exception:
            pass
        self._task_grant(
            rid, [{'goods_id': gid, 'count': count, 'bind': bound}
                  for gid, count in jcfg['rewards']])
        return frame(amf3_encode([str(CMD_EQUIP_HECHENG), [1]]))

    def equip_hecheng_count(self, msg):
        """Command 34008: EquipAction.gethehengCount -> gethehengCount.

        No arguments. A missing pool answers [0], else [hechengCount]
        (null passes through when the pool never synthesized, as Java
        boxes the column directly).
        """
        role = self._equip_role()
        if role is None:
            return None
        try:
            jd_row = self.get_role_jianding(role.get('id'))
        except Exception:
            jd_row = None
        if not jd_row:
            return frame(amf3_encode([str(CMD_EQUIP_HECHENG_COUNT), [0]]))
        made = jd_row.get('hecheng_count')
        try:
            made = int(made) if made is not None else None
        except (TypeError, ValueError):
            made = None
        return frame(amf3_encode([str(CMD_EQUIP_HECHENG_COUNT), [made]]))

    def _vip_parcel_items(self, parcels):
        """Gift tuples to _task_grant dicts (expire hours have no slot)."""
        return [{'goods_id': gid, 'count': count, 'bind': bind}
                for gid, count, bind in parcels or []]

    def _vip_fits_list(self, rid, parcels):
        """checkPutInBag over a gift list (single-parcel helper per item)."""
        for gid, count, bind in parcels or []:
            if not self._prop_fits(rid, {'goods': gid, 'count': count},
                                   bind):
                return False
        return True

    def _vip_clear_times(self, rid, row):
        """VipServiceImpl.clearTimes day/week arm (login-time rule).

        vip>0 only: a stale dayTime re-arms state_day to 1; past the
        weekTime week's Sunday 23:59:59 re-arms state_week to 1. The
        prop-value arm stays a login concern (62006 territory). Missing
        times read as stale, matching a fresh row's first login.
        """
        try:
            level = int(row.get('vip_level') or 0)
        except (TypeError, ValueError):
            return row
        if level <= 0:
            return row
        now = int(time.time() * 1000)
        try:
            day_ms = int(row.get('day_time') or 0)
        except (TypeError, ValueError):
            day_ms = 0
        if time.localtime(day_ms / 1000)[:3] != \
                time.localtime(now / 1000)[:3]:
            try:
                self.save_role_vip(rid, state_day=1)
            except Exception:
                pass
            row = dict(row, state_day=1)
        try:
            week_ms = int(row.get('week_time') or 0)
        except (TypeError, ValueError):
            week_ms = 0
        end = time.localtime(week_ms / 1000)[:3]
        try:
            base = time.mktime(time.struct_time(
                (end[0], end[1], end[2], 23, 59, 59, 0, 0, -1)))
            sunday = base + (6 - time.localtime(week_ms / 1000).tm_wday) \
                * 86400
        except (TypeError, ValueError, OverflowError):
            sunday = 0
        if now / 1000 > sunday:
            try:
                self.save_role_vip(rid, state_week=1)
            except Exception:
                pass
            row = dict(row, state_week=1)
        return row

    @staticmethod
    def _vip_day_num(ms):
        """Calendar-day serial for ms (DatatimeUtil day math)."""
        try:
            parts = time.localtime(int(ms) / 1000)
        except (TypeError, ValueError, OverflowError):
            return None
        try:
            return int(time.mktime((parts[0], parts[1], parts[2], 0, 0, 0,
                                    0, 0, -1))) // 86400
        except (TypeError, ValueError, OverflowError):
            return None

    def _vip_kaifu_days(self):
        """ServerInfoExportService.getKaifuDays: days since server start."""
        now = self._vip_day_num(int(time.time() * 1000))
        try:
            start = self._vip_day_num(self.server_start_ms or 0)
        except (TypeError, ValueError):
            start = None
        if now is None or start is None:
            return 0
        return max(now - start, 0)

    def _vip_kaifu_ensure(self, rid):
        """RoleVipKaifu row, created empty like roleLogin does."""
        try:
            row = self.get_role_vip_kaifu(rid)
        except Exception:
            row = None
        if row is None:
            try:
                self.save_role_vip_kaifu(rid, lingqu_reward='{}',
                                         lotter_reward=0)
            except Exception:
                pass
            return {'lingqu_reward': '{}', 'lotter_reward': 0}
        return row

    @staticmethod
    def _vip_claimed(text):
        """lingqu/state maps from JSON text; corrupt reads as unclaimed."""
        try:
            data = json.loads(text or '{}')
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def vip_day(self, msg):
        """Command 62001: VipAction.getVipDay -> vipService.getVipDay.

        No arguments. No vip row is silent; vip 0 answers [0, 621002];
        an armed-claimed state answers [0, 621001]. The level daybag
        grants (short room answers [0, 1006]), the state arms to
        claimed with fresh time, and the reply is [1]. Events need a
        bus.
        """
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        rid = role.get('id')
        try:
            row = self.get_role_vip(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = self._vip_clear_times(rid, row)
        try:
            level = int(row.get('vip_level') or 0)
        except (TypeError, ValueError):
            level = 0
        if level == 0:
            return frame(amf3_encode([str(CMD_VIP_DAY), [0, VIP_ERR_NOVIP]]))
        try:
            claimed = int(row.get('state_day') or 0) == 2
        except (TypeError, ValueError):
            claimed = False
        if claimed:
            return frame(amf3_encode(
                [str(CMD_VIP_DAY), [0, VIP_ERR_CLAIMED_DAY]]))
        gifts = self.config.vip_gifts(level)
        if gifts is None:
            return None
        if gifts['daybag']:
            if not self._vip_fits_list(rid, gifts['daybag']):
                return frame(amf3_encode(
                    [str(CMD_VIP_DAY), [0, GENERAL_NOSLOT]]))
            self._task_grant(rid, self._vip_parcel_items(gifts['daybag']))
        try:
            self.save_role_vip(rid, state_day=2,
                               day_time=int(time.time() * 1000))
        except Exception:
            pass
        return frame(amf3_encode([str(CMD_VIP_DAY), [1]]))

    def vip_week(self, msg):
        """Command 62002: VipAction.getVipWeek -> vipService.getVipWeek.

        The week twin of the day gift: [0, 621003] when claimed, the
        level weekbag, [1] on success.
        """
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        rid = role.get('id')
        try:
            row = self.get_role_vip(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = self._vip_clear_times(rid, row)
        try:
            level = int(row.get('vip_level') or 0)
        except (TypeError, ValueError):
            level = 0
        if level == 0:
            return frame(amf3_encode([str(CMD_VIP_WEEK), [0, VIP_ERR_NOVIP]]))
        try:
            claimed = int(row.get('state_week') or 0) == 2
        except (TypeError, ValueError):
            claimed = False
        if claimed:
            return frame(amf3_encode(
                [str(CMD_VIP_WEEK), [0, VIP_ERR_CLAIMED_WEEK]]))
        gifts = self.config.vip_gifts(level)
        if gifts is None:
            return None
        if gifts['weekbag']:
            if not self._vip_fits_list(rid, gifts['weekbag']):
                return frame(amf3_encode(
                    [str(CMD_VIP_WEEK), [0, GENERAL_NOSLOT]]))
            self._task_grant(rid, self._vip_parcel_items(gifts['weekbag']))
        try:
            self.save_role_vip(rid, state_week=2,
                               week_time=int(time.time() * 1000))
        except Exception:
            pass
        return frame(amf3_encode([str(CMD_VIP_WEEK), [1]]))

    def vip_tejia(self, msg):
        """Command 62004: VipAction.getVipTeJia -> vipService.getVipTeJia.

        C> is the bare target vip level as an Integer. No row is
        silent; vip 0 answers [0, 621002], a level above the role's
        [0, 621004], a claimed one [0, 621005]. The level libaoid
        grants (short room [0, 1006]); a positive specialprice burns YB
        first ([0, 1002] when short). The claim marks, and the reply is
        [1, level]. The job filter is vacuous in data (no libaoid rows
        exist anywhere), as is the price (always 0); both ride along as
        structure. Events need a bus.
        """
        data = self.safe(msg, 1)
        try:
            target = int(data)
        except (TypeError, ValueError):
            return None
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        rid = role.get('id')
        try:
            row = self.get_role_vip(rid)
        except Exception:
            row = None
        if row is None:
            return None
        try:
            level = int(row.get('vip_level') or 0)
        except (TypeError, ValueError):
            level = 0
        if level == 0:
            return frame(amf3_encode(
                [str(CMD_VIP_TEJIA), [0, VIP_ERR_NOVIP]]))
        if level < target:
            return frame(amf3_encode(
                [str(CMD_VIP_TEJIA), [0, VIP_ERR_ABOVE_LEVEL]]))
        claimed = self._vip_claimed(row.get('state_tejia'))
        try:
            if int(claimed.get(str(target)) or 0) == 2:
                return frame(amf3_encode(
                    [str(CMD_VIP_TEJIA), [0, VIP_ERR_CLAIMED_TEJIA]]))
        except (TypeError, ValueError):
            pass
        gifts = self.config.vip_gifts(target)
        if gifts is None:
            return None
        if gifts['libaoid'] and not self._vip_fits_list(
                rid, gifts['libaoid']):
            return frame(amf3_encode(
                [str(CMD_VIP_TEJIA), [0, GENERAL_NOSLOT]]))
        price = gifts['specialprice']
        if price > 0:
            role = self._equip_role()
            found = self._bag_money_first(role, price, ['YB'])
            if found is None:
                return frame(amf3_encode(
                    [str(CMD_VIP_TEJIA), [0, GENERAL_YB_SHORT]]))
            self._bag_money_decr(rid, found[0], found[1])
        claimed[str(target)] = 2
        try:
            self.save_role_vip(
                rid, state_tejia=json.dumps(claimed,
                                            separators=(',', ':')))
        except Exception:
            pass
        if gifts['libaoid']:
            self._task_grant(rid, self._vip_parcel_items(gifts['libaoid']))
        return frame(amf3_encode([str(CMD_VIP_TEJIA), [1, target]]))

    def vip_kaifu(self, msg):
        """Command 62020: VipAction.getkaifu -> vipService.getKaiFuInfo.

        No arguments. The kaifu row is ensured empty (roleLogin
        equivalent), and the reply is [1, lotterReward, [[id, mark],
        ...]] over the claimed map. Events need a bus.
        """
        role = self._equip_role()
        if role is None:
            return None
        row = self._vip_kaifu_ensure(role.get('id'))
        claimed = self._vip_claimed(row.get('lingqu_reward'))
        try:
            used = int(row.get('lotter_reward') or 0)
        except (TypeError, ValueError):
            used = 0
        pairs = []
        for key, value in claimed.items():
            try:
                pairs.append([int(key), int(value)])
            except (TypeError, ValueError):
                continue
        return frame(amf3_encode(
            [str(CMD_VIP_KAIFU), [1, used, pairs]]))

    def _vip_push(self, role, frames):
        """Queue VIP pushes on the role's session; no-op when unwired."""
        if frames and self.stage_registry is not None:
            self.stage_registry.push(_wire_id(role), frames)
        return frames

    def _vip_upgrade(self, rid, charge_total):
        """VipServiceImpl.upgradeVipLevel: map charge + prop value to a level.

        Prop value above the level's needGold is moved back into the
        charge side. Returns the 62003 frame when the level changed.
        """
        total = int(charge_total or 0)
        row = self.get_role_vip(rid)
        if row is None:
            now = int(time.time() * 1000)
            self.save_role_vip(
                rid, vip_level=0, state_day=0, state_week=0,
                state_tejia=json.dumps({'0': 0}), prop_value=0,
                tody_prop_value=0, day_time=now - DAY_MS,
                week_time=now - 8 * DAY_MS)
            row = self.get_role_vip(rid) or {}
        prop = int(row.get('prop_value') or 0)
        tody = int(row.get('tody_prop_value') or 0)
        level = self.config.vip_level_for_gold(total + prop + tody)
        if level == int(row.get('vip_level') or 0):
            return []
        fields = {'vip_level': level}
        need = self.config.vip_need_gold(level)
        if need > total:
            moved = need - total - prop
            fields['tody_prop_value'] = tody - moved
            fields['prop_value'] = prop + moved
        self.save_role_vip(rid, **fields)
        return [frame(amf3_encode([str(CMD_VIP_LEVEL_UP), level]))]

    def vip_upgrade_level(self, role, charge_total):
        """VipServiceImpl.upgradeVipLevel (extra 0): push 62003 on a level change.

        Needs the recharge total, which the recharge slice supplies. Returns
        the pushed frames.
        """
        if self.config is None:
            return []
        return self._vip_push(role, self._vip_upgrade(role['id'], charge_total))

    def vip_add_prop_value(self, role, value, charge_total):
        """VipServiceImpl.addPropValue: add to today's prop value, push 62006, re-level.

        Without a vip row the Java raises, so nothing is pushed. Returns the
        pushed frames.
        """
        if self.config is None:
            return []
        rid = role['id']
        row = self.get_role_vip(rid)
        if row is None:
            return []
        try:
            add = int(value or 0)
        except (TypeError, ValueError):
            add = 0
        tody = int(row.get('tody_prop_value') or 0)
        self.save_role_vip(rid, tody_prop_value=tody + add,
                           prop_use_time=int(time.time() * 1000))
        frames = [frame(amf3_encode([str(CMD_VIP_PROP_VALUE), None]))]
        frames += self._vip_upgrade(rid, charge_total)
        return self._vip_push(role, frames)

    def vip_lottery(self, msg):
        """Command 62021: VipAction.kaiFuLotter -> vipService.lotterReward.

        No arguments. Below the choujiang vip floor answers [0, 1011],
        outside kaifu days 4-6 [0, 621012], no remaining count [0,
        621013]. The prize rolls weighted over every choujiang row,
        grants (short room [0, 1006]), bumps the used count, and replies
        [1, prizeId, [[goodsId, count]], [], []]. The bag-delta tails
        have no grant counterpart here, and putInBag1 lands in the bag
        zone; both documented. Events need a bus.
        """
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        rid = role.get('id')
        row = self._vip_kaifu_ensure(rid)
        try:
            vip_row = self.get_role_vip(rid) or {}
        except Exception:
            vip_row = {}
        try:
            level = int(vip_row.get('vip_level') or 0)
        except (TypeError, ValueError):
            level = 0
        table = self.config.vip_choujiang()
        if level < table['needvip']:
            return frame(amf3_encode(
                [str(CMD_VIP_LOTTERY), [0, GENERAL_VIP_LEVEL]]))
        days = self._vip_kaifu_days()
        lo, hi = table['kaifuday']
        if not (lo <= days <= hi):
            return frame(amf3_encode(
                [str(CMD_VIP_LOTTERY), [0, VIP_ERR_NO_LOTTERY]]))
        try:
            used = int(row.get('lotter_reward') or 0)
        except (TypeError, ValueError):
            used = 0
        span = hi - lo + 1
        count = 0 if span == used else days - lo + 1 - used
        if count == 0:
            return frame(amf3_encode(
                [str(CMD_VIP_LOTTERY), [0, VIP_ERR_NO_COUNT]]))
        weights = {pid: prize['rate']
                   for pid, prize in table['prizes'].items()}
        prize_id = self._lottery_weighted_key(weights)
        if prize_id is None or prize_id not in table['prizes']:
            return None
        try:
            gid, count, bind = table['prizes'][prize_id]['item'][0]
        except (TypeError, ValueError, IndexError):
            return None
        if gid is None:
            return None
        if not self._prop_fits(rid, {'goods': gid, 'count': count}, bind):
            return frame(amf3_encode(
                [str(CMD_VIP_LOTTERY), [0, GENERAL_NOSLOT]]))
        self._task_grant(rid, [{'goods_id': gid, 'count': count,
                                'bind': bind}])
        try:
            self.save_role_vip_kaifu(rid, lotter_reward=used + 1)
        except Exception:
            pass
        return frame(amf3_encode(
            [str(CMD_VIP_LOTTERY),
             [1, prize_id, [[gid, count]], [], []]]))

    def vip_lingjiang(self, msg):
        """Command 62022: VipAction.lingQuReward -> vipService.lingQuReward.

        C> is the reward id. An already-claimed id answers [0, 621010],
        below the vip floor [0, 1011], outside kaifu days [0, 621012], a
        day mismatch [0, 621011], short room [0, 1006]. The parcel
        grants, the id marks claimed, and the reply is [1, id, 1].
        Events need a bus.
        """
        data = self.safe(msg, 1)
        try:
            reward_id = int(data if isinstance(data, str) else
                            self.safe(data or [], 0))
        except (TypeError, ValueError):
            return None
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        rid = role.get('id')
        row = self._vip_kaifu_ensure(rid)
        claimed = self._vip_claimed(row.get('lingqu_reward'))
        try:
            if int(claimed.get(str(reward_id)) or 0) == 1:
                return frame(amf3_encode(
                    [str(CMD_VIP_LINGJIANG), [0, VIP_ERR_CLAIMED_KAIFU]]))
        except (TypeError, ValueError):
            pass
        try:
            vip_row = self.get_role_vip(rid) or {}
        except Exception:
            vip_row = {}
        try:
            level = int(vip_row.get('vip_level') or 0)
        except (TypeError, ValueError):
            level = 0
        table = self.config.vip_choujiang()
        if level < table['needvip']:
            return frame(amf3_encode(
                [str(CMD_VIP_LINGJIANG), [0, GENERAL_VIP_LEVEL]]))
        days = self._vip_kaifu_days()
        lo, hi = table['kaifuday']
        if not (lo <= days <= hi):
            return frame(amf3_encode(
                [str(CMD_VIP_LINGJIANG), [0, VIP_ERR_NO_LOTTERY]]))
        cfg = self.config.vip_lingjiang(reward_id)
        if cfg is None:
            return None
        if cfg['date'] != days:
            return frame(amf3_encode(
                [str(CMD_VIP_LINGJIANG), [0, VIP_ERR_DAY_MISMATCH]]))
        gid, count, bind = cfg['item']
        if not self._prop_fits(rid, {'goods': gid, 'count': count}, bind):
            return frame(amf3_encode(
                [str(CMD_VIP_LINGJIANG), [0, GENERAL_NOSLOT]]))
        self._task_grant(rid, [{'goods_id': gid, 'count': count,
                                'bind': bind}])
        claimed[str(reward_id)] = 1
        try:
            self.save_role_vip_kaifu(
                rid, lingqu_reward=json.dumps(claimed,
                                              separators=(',', ':')))
        except Exception:
            pass
        return frame(amf3_encode(
            [str(CMD_VIP_LINGJIANG), [1, reward_id, 1]]))

    def vip_huodong(self, msg):
        """Command 88000: VipAction.getVipHuoDongData -> getVipHuoDongState.

        No arguments. Every role_vip_huodong row splits into the
        claimed fixed-reward tiers plus the drawn lottery tiers, and
        the reply is [lingqu..., choujiang...]. Events need a bus.
        """
        role = self._equip_role()
        if role is None:
            return None
        try:
            rows = self.get_role_vip_huodong_all(role.get('id')) or []
        except Exception:
            rows = []
        claimed, drawn = [], []
        for row in rows:
            try:
                tier = int(row.get('vip'))
            except (TypeError, ValueError):
                continue
            try:
                if int(row.get('lingqu_state') or 0) == 1:
                    claimed.append(tier)
            except (TypeError, ValueError):
                pass
            try:
                if int(row.get('choujiang_state') or 0) == 1:
                    drawn.append(tier)
            except (TypeError, ValueError):
                pass
        return frame(amf3_encode(
            [str(CMD_VIP_HUODONG), [claimed, drawn]]))

    def _vip_huodong_tier(self, msg):
        """C> vip tier for 88001/88002; unparseable stays silent.

        Java parses data[0].toString, so a bare int works like the
        usual string cell (unlike the older vip arg convention).
        """
        data = self.safe(msg, 1)
        if isinstance(data, (list, tuple)):
            data = self.safe(data, 0)
        try:
            return int(str(data))
        except (TypeError, ValueError):
            return None

    def _vip_huodong_grant(self, rid, parcels):
        """checkPutInBag then putInBag for a huodong parcel list."""
        for gid, count, bind in parcels:
            if not self._prop_fits(rid, {'goods': gid, 'count': count},
                                   bind):
                return False
        self._task_grant(rid, [{'goods_id': gid, 'count': count,
                                'bind': bind}
                               for gid, count, bind in parcels])
        return True

    def vip_huodong_guding(self, msg):
        """Command 88001: VipAction.getVipHuoDongGuDing -> getVipHuoDongJiangLi.

        C> is the vip tier. An already-claimed tier answers [0,
        621008], below the tier floor [0, 1011], outside its kaifu
        window [0, 621007], short room [0, 1006]. The bisong parcels
        grant, the tier marks claimed, and the reply is [1, tier]. A
        missing row or empty bisong stays silent like Java's null.
        Events need a bus.
        """
        tier = self._vip_huodong_tier(msg)
        role = self._equip_role()
        if tier is None or role is None or self.config is None:
            return None
        rid = role.get('id')
        try:
            row = self.get_role_vip_huodong(rid, tier)
        except Exception:
            row = None
        try:
            claimed = row is not None and \
                int(row.get('lingqu_state') or 0) == 1
        except (TypeError, ValueError):
            claimed = False
        if claimed:
            return frame(amf3_encode(
                [str(CMD_VIP_HUODONG_GUDING),
                 [0, VIP_ERR_HUODONG_CLAIMED]]))
        try:
            vip_row = self.get_role_vip(rid) or {}
        except Exception:
            vip_row = {}
        try:
            level = int(vip_row.get('vip_level') or 0)
        except (TypeError, ValueError):
            level = 0
        if tier > level:
            return frame(amf3_encode(
                [str(CMD_VIP_HUODONG_GUDING), [0, GENERAL_VIP_LEVEL]]))
        cfg = self.config.vip_huodong(tier)
        if cfg is None:
            return None
        days = self._vip_kaifu_days()
        lo, hi = cfg['window']
        if not (lo <= days <= hi):
            return frame(amf3_encode(
                [str(CMD_VIP_HUODONG_GUDING),
                 [0, VIP_ERR_HUODONG_TIME]]))
        if not cfg['bisong']:
            return None
        if not self._vip_huodong_grant(rid, cfg['bisong']):
            return frame(amf3_encode(
                [str(CMD_VIP_HUODONG_GUDING), [0, GENERAL_NOSLOT]]))
        if row is None:
            try:
                self.save_role_vip_huodong(rid, tier, choujiang_state=0,
                                           lingqu_state=0)
            except Exception:
                pass
        try:
            self.save_role_vip_huodong(rid, tier, lingqu_state=1)
        except Exception:
            pass
        return frame(amf3_encode(
            [str(CMD_VIP_HUODONG_GUDING), [1, tier]]))

    def vip_huodong_choujiang(self, msg):
        """Command 88002: VipAction.getVipHuoDongChouJiang -> getVipHuoDongChouJiang.

        C> is the vip tier. An already-drawn tier answers [0, 621009],
        below the tier floor [0, 1011], outside its kaifu window [0,
        621007], short room [0, 1006]. The prize rolls weighted over
        the tier's odds map, grants, marks drawn, and the reply is
        [1, tier, prizeIndex]. A missing row or empty odds stays
        silent like Java's null. Events need a bus.
        """
        tier = self._vip_huodong_tier(msg)
        role = self._equip_role()
        if tier is None or role is None or self.config is None:
            return None
        rid = role.get('id')
        try:
            row = self.get_role_vip_huodong(rid, tier)
        except Exception:
            row = None
        try:
            drawn = row is not None and \
                int(row.get('choujiang_state') or 0) == 1
        except (TypeError, ValueError):
            drawn = False
        if drawn:
            return frame(amf3_encode(
                [str(CMD_VIP_HUODONG_CHOUJIANG),
                 [0, VIP_ERR_HUODONG_DRAWN]]))
        try:
            vip_row = self.get_role_vip(rid) or {}
        except Exception:
            vip_row = {}
        try:
            level = int(vip_row.get('vip_level') or 0)
        except (TypeError, ValueError):
            level = 0
        if tier > level:
            return frame(amf3_encode(
                [str(CMD_VIP_HUODONG_CHOUJIANG),
                 [0, GENERAL_VIP_LEVEL]]))
        cfg = self.config.vip_huodong(tier)
        if cfg is None:
            return None
        days = self._vip_kaifu_days()
        lo, hi = cfg['window']
        if not (lo <= days <= hi):
            return frame(amf3_encode(
                [str(CMD_VIP_HUODONG_CHOUJIANG),
                 [0, VIP_ERR_HUODONG_TIME]]))
        if not cfg['odds']:
            return None
        key = self._lottery_weighted_key(dict(cfg['odds']))
        if key is None or key not in cfg['prizes']:
            return None
        if not self._vip_huodong_grant(rid, cfg['prizes'][key]):
            return frame(amf3_encode(
                [str(CMD_VIP_HUODONG_CHOUJIANG), [0, GENERAL_NOSLOT]]))
        if row is None:
            try:
                self.save_role_vip_huodong(rid, tier, choujiang_state=0,
                                           lingqu_state=0)
            except Exception:
                pass
        try:
            self.save_role_vip_huodong(rid, tier, choujiang_state=1)
        except Exception:
            pass
        return frame(amf3_encode(
            [str(CMD_VIP_HUODONG_CHOUJIANG), [1, tier, key]]))

    def _vipqq_config(self):
        """Active vip_qq row, or None when the table is unseeded."""
        try:
            return self.get_vip_qq()
        except Exception:
            return None

    def _vipqq_flag(self, cfg, charge_total, claimed):
        """getVipQQInfo state: 2 claimed, 1 recharge reached, else 0."""
        if claimed:
            return 2
        try:
            total = int(charge_total or 0)
        except (TypeError, ValueError):
            total = 0
        try:
            need = int(cfg.get('min_recharge') or 0)
        except (TypeError, ValueError):
            need = 0
        return 1 if total // 10 >= need else 0

    def _vipqq_payload(self, cfg, flag):
        """[1, minRecharge, flag, pic, qq] like getVipQQInfo/recharge."""
        try:
            need = int(cfg.get('min_recharge') or 0)
        except (TypeError, ValueError):
            need = 0
        return [1, need, flag, cfg.get('pic'), cfg.get('qq')]

    def vipqq_info(self, msg, charge_total=0):
        """Command 88003: VipQqAction.vipqqInfo -> getVipQQInfo.

        No arguments. Without a vip_qq row answers [0, 794002]. The
        lifetime-recharge source has no local table, so the caller
        supplies the total like vip_upgrade_level takes charge_total.
        """
        role = self._equip_role()
        if role is None:
            return None
        cfg = self._vipqq_config()
        if cfg is None:
            return frame(amf3_encode(
                [str(CMD_VIPQQ_INFO), [0, VIPQQ_ERR_NOCONFIG]]))
        try:
            row = self.get_role_qq_list(role.get('id'))
        except Exception:
            row = None
        try:
            claimed = int((row or {}).get('is_get_rewards') or 0) == 1
        except (TypeError, ValueError):
            claimed = False
        return frame(amf3_encode(
            [str(CMD_VIPQQ_INFO),
             self._vipqq_payload(
                 cfg, self._vipqq_flag(cfg, charge_total, claimed))]))

    def vipqq_rewards(self, msg):
        """Command 88004: VipQqAction.vipqqRewards -> getRewards.

        No arguments. Unbound answers [0, 794000], claimed [0, 794001],
        full bag [0, 430212]; success grants chaojihuiyuan parcels and
        marks the row claimed. The reward event has no bus (logged).
        """
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        rid = role.get('id')
        try:
            row = self.get_role_qq_list(rid)
        except Exception:
            row = None
        if row is None:
            return frame(amf3_encode(
                [str(CMD_VIPQQ_REWARDS), [0, VIPQQ_ERR_NOBIND]]))
        try:
            claimed = int(row.get('is_get_rewards') or 0) == 1
        except (TypeError, ValueError):
            claimed = False
        if claimed:
            return frame(amf3_encode(
                [str(CMD_VIPQQ_REWARDS), [0, VIPQQ_ERR_CLAIMED]]))
        parcels = self.config.vipqq_rewards()
        if not self._vip_fits_list(rid, parcels):
            return frame(amf3_encode(
                [str(CMD_VIPQQ_REWARDS), [0, BAG_ERR_SLOT_LESS]]))
        self._task_grant(rid, self._vip_parcel_items(parcels))
        try:
            self.save_role_qq_list(rid, is_get_rewards=1)
        except Exception:
            pass
        return frame(amf3_encode([str(CMD_VIPQQ_REWARDS), [1]]))

    def vipqq_bind(self, role, qq, user_name):
        """VipQqServiceImpl.vipQqOK: store the QQ binding, push 88005.

        The QQ platform callback has no local equivalent, so callers
        invoke this directly. Returns the pushed frames.
        """
        if role is None:
            return []
        try:
            self.save_role_qq_list(role.get('id'), qq=qq,
                                   user_name=user_name, is_get_rewards=0)
        except Exception:
            pass
        return self._vip_push(
            role, [frame(amf3_encode([str(CMD_VIPQQ_BIND_PUSH), None]))])

    def vipqq_recharge(self, role, yb):
        """VipQqServiceImpl.recharge: refresh the 88003 push on recharge.

        Claimed rows and non-positive amounts stay silent. Returns the
        pushed frames.
        """
        if role is None:
            return []
        try:
            row = self.get_role_qq_list(role.get('id'))
        except Exception:
            row = None
        try:
            claimed = int((row or {}).get('is_get_rewards') or 0) == 1
        except (TypeError, ValueError):
            claimed = False
        if claimed:
            return []
        try:
            amount = int(yb or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            return []
        cfg = self._vipqq_config()
        if cfg is None:
            return []
        return self._vip_push(
            role, [frame(amf3_encode(
                [str(CMD_VIPQQ_INFO),
                 self._vipqq_payload(
                     cfg, self._vipqq_flag(cfg, amount, False))]))])

    def equip_qianghua_clear(self, msg):
        """Command 34003: EquipAction.qiangHuaClear -> qiangHuaClear.

        C> is the bare equipId string. Unknown slots answer [0, 31001].
        Missing charm with short YB answers [0, 31012]; otherwise the
        charm is consumed when present, qingxiyb YB is deducted, qhcount
        and stars reset to 0, and 30106 [formart] precedes [1, equipId].
        """
        data = self.safe(msg, 1)
        equip_id = data if isinstance(data, str) else self.safe(data or [],
                                                                0)
        role = self._equip_role()
        if role is None or equip_id is None or self.config is None:
            return None
        rid = role.get('id')
        row = self._equip_row(rid, equip_id)
        if row is None:
            return frame(amf3_encode(
                [str(CMD_EQUIP_QIANGHUA_CLEAR), [0, EQUIP_ERROR_NOSLOT]]))
        vo = equip_vo(row.get('attributes'))
        try:
            qh = int(vo.get('qhcount') or 0)
        except (TypeError, ValueError):
            qh = 0
        cfg = self.config.qianghua_config(row.get('goods_id'), qh)
        if cfg is None:
            return None
        short = any(self._task_goods_count(rid, gid) < need
                    for gid, need in cfg['qingxiGoods'].items())
        if short and self._bag_money_first(role, cfg['qingxiyb'],
                                            ['YB']) is None:
            return frame(amf3_encode(
                [str(CMD_EQUIP_QIANGHUA_CLEAR), [0, EQUIP_ERROR_GOODS]]))
        for gid, need in cfg['qingxiGoods'].items():
            self._prop_take(rid, gid, need)
        if cfg['qingxiyb'] > 0:
            self._bag_money_decr(rid, 'YB', cfg['qingxiyb'])
        try:
            data = json.loads(row.get('attributes') or '')
            if not isinstance(data, dict):
                data = {}
        except ValueError:
            data = {}
        data['qhcount'] = 0
        data['qhxingxing'] = '[]'
        blob = json.dumps(data, separators=(',', ':'))
        self._equip_persist(rid, row, blob)
        role = self._equip_role()
        return (frame(amf3_encode(
                    [str(CMD_EQUIP_CHANGE),
                     [self._equip_formart(role, dict(row,
                                                     attributes=blob))]])),
                frame(amf3_encode(
                    [str(CMD_EQUIP_QIANGHUA_CLEAR), [1, str(equip_id)]])))

    def equip_qianghua_max(self, msg):
        """Command 34009: EquipAction.qiangHuaMax -> qiangHuaMax.

        C> [equipGuid]. At qhcount 11 [0, 31034]; short 300000 YXB
        [0, 31011]; missing jinglianshi [0, 1005]. The attempt steps
        qhcount +1 with a lit star, pushes 11101 [31035, [roleName,
        goodsName, '+MAX' at 11 else '+n']] and 30106 [formart], and
        replies [1]. The bag-mirror updateGoods has no guid linkage here
        and is skipped (documented). Event publishes have no bus.
        """
        args = self.safe(msg, 1, []) or []
        guid = self.safe(args, 0)
        if guid is not None:
            guid = str(guid)
        role = self._equip_role()
        if role is None or guid is None or self.config is None:
            return None
        rid = role.get('id')
        row = self._equip_row(rid, guid)
        if row is None:
            return None
        vo = equip_vo(row.get('attributes'))
        try:
            qh = int(vo.get('qhcount') or 0)
        except (TypeError, ValueError):
            qh = 0
        if qh == 11:
            return frame(amf3_encode(
                [str(CMD_EQUIP_QIANGHUA_MAX), [0, EQUIP_ERROR_MAXED11]]))
        role = self._equip_role()
        if self._bag_money_first(role, 300000, ['YXB']) is None:
            return frame(amf3_encode(
                [str(CMD_EQUIP_QIANGHUA_MAX), [0, EQUIP_ERROR_MONEY]]))
        if self._task_goods_count(rid, 'jinglianshi') < 1:
            return frame(amf3_encode(
                [str(CMD_EQUIP_QIANGHUA_MAX), [0, GENERAL_GOODS]]))
        self._bag_money_decr(rid, 'YXB', 300000)
        self._prop_take(rid, 'jinglianshi', 1)
        new_qh = qh + 1
        blob = self._vo_enhanced_blob(row, new_qh, True)
        self._equip_persist(rid, row, blob)
        role = self._equip_role()
        grow = self.config._goods_table().get(str(row.get('goods_id')))
        goods_name = (grow or {}).get('name') or str(row.get('goods_id'))
        tag = '+MAX' if new_qh == 11 else f'+{new_qh}'
        return (frame(amf3_encode(
                    [str(CMD_NOTICE_ALL),
                     [str(CMD_EQUIP_MAX_NOTICE),
                      [str(role.get('name')), str(goods_name), tag]]])),
                frame(amf3_encode(
                    [str(CMD_EQUIP_CHANGE),
                     [self._equip_formart(role, dict(row,
                                                     attributes=blob))]])),
                frame(amf3_encode([str(CMD_EQUIP_QIANGHUA_MAX), [1]])))

    def _skill_role(self):
        """First role of the authed account plus its local id."""
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None, None
        return role, role.get('id')

    def skill_info(self):
        """Command 42000: SkillServiceImpl.getSkill -> [[category, level]].

        One pair per role_skill row; an empty skill set answers [].
        """
        role, rid = self._skill_role()
        if role is None:
            return None
        try:
            skills = self.get_role_skills(rid) or []
        except Exception:
            return None
        pairs = [[s.get('category'), s.get('level')] for s in skills]
        return frame(amf3_encode([str(CMD_SKILL_INFO), pairs]))

    def skill_upgrade(self, msg):
        """Command 42003: SkillServiceImpl.upgradeSkill.

        C> skillCategoryId. Gates in order: unknown skill [0, 420005],
        level 100 cap [0, 420010], skill at/above role level [0, 420006],
        shenjiang rank short [0, 420012], config levelneed [0, 1000],
        zhenqi short [0, 1001], YXB short [0, 1003]. Costs (zhenqi +
        YXB) burn before the learnodds roll: success learns level+1 and
        replies [1, category, level], failure replies [-1]. A missing
        JiNengBiao row stays silent (Java throws, answering nothing).
        """
        category = str(self.safe(msg, 1, '') or '')
        role, rid = self._skill_role()
        if role is None or not category:
            return None
        try:
            rows = self.get_role_skills(rid) or []
        except Exception:
            rows = []
        row = next((s for s in rows
                    if str(s.get('category')) == category), None)
        if row is None:
            return frame(amf3_encode(
                [str(CMD_SKILL_UPGRADE), [0, SKILL_UPGRADE_NOT]]))
        try:
            level = int(row.get('level') or 0)
        except (TypeError, ValueError):
            level = 0
        if level >= 100:
            return frame(amf3_encode(
                [str(CMD_SKILL_UPGRADE), [0, SKILL_ERROR_MAX_LEVEL]]))
        try:
            role_level = int(role.get('level') or 0)
        except (TypeError, ValueError):
            role_level = 0
        if level >= role_level:
            return frame(amf3_encode(
                [str(CMD_SKILL_UPGRADE), [0, SKILL_UPGRADE_LEVEL]]))
        info = self.config.skill_info(category, level) \
            if self.config is not None else None
        if info is None:
            log.info('conn %d: upgrade %r has no JiNengBiao row (silent)',
                     self.conn_id, category)
            return None
        err = self._skill_shengjiang_gate(rid, info)
        if err is not None:
            return frame(amf3_encode([str(CMD_SKILL_UPGRADE), err]))
        try:
            need_level = int(info.get('levelneed') or 0)
        except (TypeError, ValueError):
            need_level = 0
        if need_level > role_level:
            return frame(amf3_encode(
                [str(CMD_SKILL_UPGRADE), [0, GENERAL_LEVEL]]))
        try:
            need_zhenqi = int(info.get('zhenqineed') or 0)
        except (TypeError, ValueError):
            need_zhenqi = 0
        try:
            zhenqi = int(role.get('zhenqi') or 0)
        except (TypeError, ValueError):
            zhenqi = 0
        if zhenqi < need_zhenqi:
            return frame(amf3_encode(
                [str(CMD_SKILL_UPGRADE), [0, GENERAL_ZHENQI]]))
        try:
            money = int(info.get('goldneed') or 0)
        except (TypeError, ValueError):
            money = 0
        try:
            tongqian = int(role.get('tongqian') or 0)
        except (TypeError, ValueError):
            tongqian = 0
        if tongqian < money:
            return frame(amf3_encode(
                [str(CMD_SKILL_UPGRADE), [0, GENERAL_JB]]))
        try:
            self.save_role_state(rid, tongqian=tongqian - money,
                                 zhenqi=zhenqi - need_zhenqi)
        except Exception:
            pass
        try:
            odds = float(info.get('learnodds') or 0)
        except (TypeError, ValueError):
            odds = 0.0
        log.info('conn %d: upgrade %r event skipped (no bus)',
                 self.conn_id, category)
        if not self._lottery_roll(odds):
            return frame(amf3_encode([str(CMD_SKILL_UPGRADE), [-1]]))
        try:
            self.save_role_skill(rid, category, level + 1)
        except Exception:
            pass
        return frame(amf3_encode(
            [str(CMD_SKILL_UPGRADE), [1, category, level + 1]]))

    def _skill_shengjiang_gate(self, rid, info):
        """upgradeSkill's bianshenneed gate: [0, 420012] or None.

        'shenjiangId|rank' against the role_shenjiang rows; a missing
        row or a short rank fails (unmigrated shenjiang data fails too).
        """
        raw = info.get('bianshenneed')
        if raw is None or str(raw) == '':
            return None
        try:
            parts = str(raw).split('|')
            sj_id, need_rank = parts[0], int(parts[1])
        except (TypeError, ValueError, IndexError):
            log.info('conn %d: bad bianshenneed %r (silent)',
                     self.conn_id, raw)
            return None
        try:
            owned = self.get_role_shenjiang(rid) or []
        except Exception:
            owned = []
        for sj in owned:
            if str(sj.get('shenjiang_id')) != sj_id:
                continue
            try:
                have = int(sj.get('jiangxing_rank') or 0)
            except (TypeError, ValueError):
                have = 0
            if have >= need_rank:
                return None
            break
        return [0, SKILL_ERROR_SHENGJI]

    @staticmethod
    def _exp_get(attributes):
        """GoodsExpVo.analysis: exp cell of an attributes blob, else 0."""
        try:
            data = json.loads(attributes or '')
        except (TypeError, ValueError):
            return 0
        if not isinstance(data, dict):
            return 0
        try:
            return int(data.get('exp') or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _exp_set(attributes, exp):
        """GoodsExpVo.toString: attributes blob with the exp cell set."""
        try:
            data = json.loads(attributes or '')
        except (TypeError, ValueError):
            data = None
        if not isinstance(data, dict):
            data = {}
        data['exp'] = int(exp)
        return json.dumps(data)

    @staticmethod
    def _skillbook_slot_type(slot):
        """getType: 1 zuoqi, 2 qizhan, 3 guangyi, else 0."""
        try:
            num = int(slot)
        except (TypeError, ValueError):
            return 0
        if SKILLBOOK_ZUOQI[0] <= num <= SKILLBOOK_ZUOQI[1]:
            return 1
        if SKILLBOOK_QIZHAN[0] <= num <= SKILLBOOK_QIZHAN[1]:
            return 2
        if SKILLBOOK_GUANGYI[0] <= num <= SKILLBOOK_GUANGYI[1]:
            return 3
        return 0

    @staticmethod
    def _skillbook_can_wear(teshutype, slot):
        """isPeiDai: type 0 fits 10001..10056, else its own mount band."""
        try:
            special = int(teshutype)
            num = int(slot)
        except (TypeError, ValueError):
            return False
        if special == 0:
            return SKILLBOOK_EQUIP_LO <= num <= SKILLBOOK_EQUIP_HI
        bands = {1: SKILLBOOK_ZUOQI, 2: SKILLBOOK_QIZHAN,
                 3: SKILLBOOK_GUANGYI}
        band = bands.get(special)
        return band is not None and band[0] <= num <= band[1]

    @staticmethod
    def _skillbook_can_shift(from_slot, to_slot):
        """isMove: both slots in the same mount band."""
        try:
            a, b = int(from_slot), int(to_slot)
        except (TypeError, ValueError):
            return False
        bands = (SKILLBOOK_ZUOQI, SKILLBOOK_QIZHAN, SKILLBOOK_GUANGYI)
        return any(lo <= a <= hi and lo <= b <= hi for lo, hi in bands)

    def _skillbook_slot_open(self, rid, role, slot):
        """isOpenSlot: zuoqi mutex cells; qizhan/guanyi stay locked.

        The qizhan and guanyi tables are not migrated, so their bands
        answer closed exactly like Java's empty sources would.
        """
        try:
            num = int(slot)
        except (TypeError, ValueError):
            return False
        if SKILLBOOK_ZUOQI[0] <= num <= SKILLBOOK_ZUOQI[1]:
            try:
                zuoqi = self.get_role_zuoqi(rid) or {}
            except Exception:
                zuoqi = {}
            if self.config is None:
                return False
            return bool(self.config.zuoqi_skill_open(
                zuoqi.get('zuoqi_rank'), role.get('level'), num - 10000))
        return False

    def _skillbook_wear_gate(self, rid, role, book, existing, slot):
        """checkPeiDai: [0, code] or None when the book may be worn."""
        try:
            zuoqi = self.get_role_zuoqi(rid) or {}
        except Exception:
            zuoqi = {}
        try:
            rank = int(zuoqi.get('zuoqi_rank') or 0)
        except (TypeError, ValueError):
            rank = 0
        try:
            if rank < int(book.get('zuoqilv') or 0):
                return [0, SKILLBOOK_ERR_ZUOQI]
        except (TypeError, ValueError):
            pass
        # getQizhanBinLevel/getGuangYiLevel read unmigrated tables, so
        # both count as 0 here; books above 0 stay gated (99006/99011).
        for column, code in (('qibinglv', SKILLBOOK_ERR_QIBING),
                             ('chibanglv', SKILLBOOK_ERR_CHIBANG)):
            try:
                if 0 < int(book.get(column) or 0):
                    return [0, code]
            except (TypeError, ValueError):
                pass
        if self.config is None:
            return None
        try:
            slots = self.get_role_skillbook_slots(
                rid, *{1: SKILLBOOK_ZUOQI, 2: SKILLBOOK_QIZHAN,
                       3: SKILLBOOK_GUANGYI}[self._skillbook_slot_type(slot)])
        except Exception:
            slots = []
        if not slots:
            return None
        try:
            only = bool(int(book.get('only') or 0))
        except (TypeError, ValueError):
            only = bool(book.get('only'))
        if not only:
            return None
        for worn in slots:
            if existing is not None and str(worn.get('bag_id')) == \
                    str(existing.get('bag_id')):
                continue
            worn_book = self.config.skillbook_book(worn.get('goods_id'))
            if worn_book is None:
                continue
            if str(book.get('ridetype')) == str(worn_book.get('ridetype')):
                return [0, SKILLBOOK_ERR_ONLY]
        return None

    def _skillbook_promote(self, book, exp):
        """checkUpgradeLevel: tier row the exp reaches, else the book row.

        The recursion walks (ridetype, rare, level+1) tiers while the exp
        passes maxexp, stopping at level 10; a missing next tier keeps
        the current row (Java would throw on absent data).
        """
        if self.config is None:
            return book
        seen = str(book.get('id'))
        while True:
            try:
                level = int(book.get('skillbooklevel') or 0)
            except (TypeError, ValueError):
                return book
            nxt = self.config.skillbook_type(book.get('ridetype'),
                                             book.get('rarelevel'), level + 1)
            if nxt is None:
                return book
            try:
                cap = int(book.get('maxexp') or 0)
                cap_next = int(nxt.get('maxexp') or 0)
            except (TypeError, ValueError):
                return book
            if cap > exp and exp < cap_next:
                return book
            try:
                if int(nxt.get('skillbooklevel') or 0) == 10:
                    return nxt
            except (TypeError, ValueError):
                return nxt
            if str(nxt.get('id')) == seen:
                return nxt
            book = nxt

    def _skillbook_bag_slot(self, rid, slot):
        """loadGoodsBySlot: one bag row, or None."""
        try:
            return self.get_role_bag_slot(rid, slot)
        except Exception:
            return None

    def _skillbook_worn_slot(self, rid, slot):
        """getRoleSkillbookSlot: one worn row, or None."""
        try:
            return self.get_role_skillbook_slot(rid, slot)
        except Exception:
            return None

    def _skillbook_decr(self, rid, slot, take):
        """decrGoodsesById for devoured books: shrink or clear the row."""
        row = self._skillbook_bag_slot(rid, slot)
        if row is None:
            return False
        try:
            have = int(row.get('count') or 0)
        except (TypeError, ValueError):
            have = 0
        try:
            if have - take > 0:
                self.update_role_bag_slot(rid, slot, count=have - take)
            else:
                self.delete_role_bag_slot(rid, slot)
        except Exception:
            return False
        return True

    def skillbook_info(self):
        """Command 99000: getSkillBookInfo -> formart1 worn-book list.

        An empty slot set answers [] (Java's empty Object[0]).
        """
        role, rid = self._skill_role()
        if role is None:
            return None
        try:
            slots = self.get_role_skillbook_slots(rid) or []
        except Exception:
            slots = []
        maps = [self.bag_goods_map(role, dict(slot)) for slot in slots]
        return frame(amf3_encode([str(CMD_SKILLBOOK_INFO), maps]))

    def skillbook_move(self, msg):
        """Command 99001: moveSkillBook routing by slot bands.

        C> [fromSlot, toSlot]: bag->worn is peidai, worn->bag is xieZai,
        worn->worn is move, bag->bag is tunshi (devour); anything else
        answers [0, 99000].
        """
        args = self.safe(msg, 1, []) or []
        try:
            a, b = int(args[0]), int(args[1])
        except (TypeError, ValueError, IndexError):
            return None
        role, rid = self._skill_role()
        if role is None:
            return None
        lo, hi = SKILLBOOK_BAG_LO, SKILLBOOK_BAG_HI
        elo, ehi = SKILLBOOK_EQUIP_LO, SKILLBOOK_EQUIP_HI
        if lo <= a <= hi and elo <= b <= ehi:
            return self._skillbook_wear(rid, role, a, b)
        if elo <= a <= ehi and lo <= b <= hi:
            return self._skillbook_strip(rid, role, a, b)
        if elo <= a <= ehi and elo <= b <= ehi:
            return self._skillbook_shift(rid, role, a, b)
        if lo <= a <= hi and lo <= b <= hi:
            return self._skillbook_feed(rid, role, a, b)
        return frame(amf3_encode(
            [str(CMD_SKILLBOOK_MOVE), [0, SKILLBOOK_ERR]]))

    def _skillbook_wear(self, rid, role, bag_slot, equip_slot):
        """peidai: wear a bag book; swap when the slot is taken."""
        item = self._skillbook_bag_slot(rid, bag_slot)
        book = self.config.skillbook_book(item.get('goods_id')) \
            if self.config is not None and item is not None else None
        if book is None:
            log.info('conn %d: wear of unknown book at %r stays silent',
                     self.conn_id, bag_slot)
            return frame(amf3_encode([str(CMD_SKILLBOOK_MOVE), None]))
        try:
            special = int(book.get('gongnengtype') or 0)
        except (TypeError, ValueError):
            special = 0
        if not self._skillbook_can_wear(special, equip_slot):
            return frame(amf3_encode(
                [str(CMD_SKILLBOOK_MOVE), [0, SKILLBOOK_ERR_TYPE]]))
        if not self._skillbook_slot_open(rid, role, equip_slot):
            return frame(amf3_encode(
                [str(CMD_SKILLBOOK_MOVE), [0, SKILLBOOK_ERR_UNOPEN]]))
        target = self._skillbook_worn_slot(rid, equip_slot)
        err = self._skillbook_wear_gate(rid, role, book, target, equip_slot)
        if err is not None:
            return frame(amf3_encode([str(CMD_SKILLBOOK_MOVE), err]))
        try:
            self.delete_role_bag_slot(rid, bag_slot)
        except Exception:
            pass
        if target is None:
            try:
                self.insert_role_skillbook_slot(
                    rid, dict(item, slot_num=equip_slot))
            except Exception:
                pass
            log.info('conn %d: wear change event skipped (no bus)',
                     self.conn_id)
            return frame(amf3_encode(
                [str(CMD_SKILLBOOK_MOVE),
                 [1, [equip_slot,
                      self.bag_goods_map(role, dict(item,
                                                   slot_num=equip_slot))],
                  None]]))
        try:
            self.insert_role_bag_slot(rid, dict(target, slot_num=bag_slot))
        except Exception:
            pass
        try:
            self.delete_role_skillbook_slot(rid, equip_slot)
        except Exception:
            pass
        try:
            self.insert_role_skillbook_slot(
                rid, dict(item, slot_num=equip_slot))
        except Exception:
            pass
        log.info('conn %d: wear swap events skipped (no bus)', self.conn_id)
        return frame(amf3_encode(
            [str(CMD_SKILLBOOK_MOVE),
             [1, [equip_slot,
                  self.bag_goods_map(role, dict(item, slot_num=equip_slot))],
              None]]))

    def _skillbook_strip(self, rid, role, equip_slot, bag_slot):
        """xieZai: unwear a book into an empty bag slot."""
        slot = self._skillbook_worn_slot(rid, equip_slot)
        if slot is None:
            return frame(amf3_encode(
                [str(CMD_SKILLBOOK_MOVE), [0, SKILLBOOK_ERR]]))
        if self._skillbook_bag_slot(rid, bag_slot) is not None:
            return frame(amf3_encode(
                [str(CMD_SKILLBOOK_MOVE), [0, SKILLBOOK_ERR]]))
        if bag_slot < SKILLBOOK_BAG_LO or bag_slot > SKILLBOOK_BAG_HI:
            return frame(amf3_encode(
                [str(CMD_SKILLBOOK_MOVE), [0, SKILLBOOK_ERR]]))
        try:
            self.delete_role_skillbook_slot(rid, equip_slot)
        except Exception:
            pass
        try:
            self.insert_role_bag_slot(rid, dict(slot, slot_num=bag_slot))
        except Exception:
            pass
        log.info('conn %d: strip change event skipped (no bus)',
                 self.conn_id)
        return frame(amf3_encode(
            [str(CMD_SKILLBOOK_MOVE), [1, [equip_slot, None], None]]))

    def _skillbook_shift(self, rid, role, from_slot, to_slot):
        """move: slide a worn book within its mount band (swap)."""
        if not self._skillbook_slot_open(rid, role, to_slot):
            return frame(amf3_encode(
                [str(CMD_SKILLBOOK_MOVE), [0, SKILLBOOK_ERR_UNOPEN]]))
        if not self._skillbook_can_shift(from_slot, to_slot):
            return frame(amf3_encode(
                [str(CMD_SKILLBOOK_MOVE), [0, SKILLBOOK_ERR]]))
        try:
            first = self.get_role_skillbook_slot(rid, from_slot)
        except Exception:
            first = None
        if first is None:
            log.info('conn %d: shift of empty slot %r stays silent',
                     self.conn_id, from_slot)
            return None
        try:
            other = self.get_role_skillbook_slot(rid, to_slot)
        except Exception:
            other = None
        try:
            self.update_role_skillbook_slot(rid, from_slot,
                                            slot_num=to_slot)
        except Exception:
            pass
        if other is not None:
            try:
                self.update_role_skillbook_slot(rid, to_slot,
                                                slot_num=from_slot)
            except Exception:
                pass
        first_map = self.bag_goods_map(role, dict(first, slot_num=to_slot))
        if other is None:
            second = [from_slot, None]
        else:
            second = [from_slot,
                      self.bag_goods_map(role, dict(other,
                                                   slot_num=from_slot))]
        return frame(amf3_encode(
            [str(CMD_SKILLBOOK_MOVE), [1, [to_slot, first_map], second]]))

    def _skillbook_feed(self, rid, role, eater_slot, food_slot):
        """tunshi: one bag book devours another for exp."""
        if eater_slot == food_slot:
            return frame(amf3_encode(
                [str(CMD_SKILLBOOK_MOVE), [0, SKILLBOOK_ERR_SAME]]))
        eater = self._skillbook_bag_slot(rid, eater_slot)
        food = self._skillbook_bag_slot(rid, food_slot)
        if eater is None or food is None:
            return frame(amf3_encode(
                [str(CMD_SKILLBOOK_MOVE), [0, SKILLBOOK_ERR]]))
        if self.config is None:
            return None
        eater_cat = self.config.goods_category(eater.get('goods_id'))
        food_cat = self.config.goods_category(food.get('goods_id'))
        if eater_cat != '100' or food_cat != '100':
            return frame(amf3_encode(
                [str(CMD_SKILLBOOK_MOVE), [0, SKILLBOOK_ERR]]))
        eater_book = self.config.skillbook_book(eater.get('goods_id'))
        food_book = self.config.skillbook_book(food.get('goods_id'))
        if eater_book is None or food_book is None:
            log.info('conn %d: devour of unlisted book stays silent',
                     self.conn_id)
            return None
        err = self._skillbook_feed_gate(food_book, eater_book, food_book)
        if err is not None:
            return frame(amf3_encode([str(CMD_SKILLBOOK_MOVE), err]))
        try:
            extra = int(eater_book.get('jcexp') or 0)
        except (TypeError, ValueError):
            extra = 0
        exp = self._exp_get(food.get('attributes')) + \
            self._exp_get(eater.get('attributes')) + extra
        grown = self._skillbook_promote(food_book, exp)
        if grown is not food_book and str(grown.get('skillbooklevel')) \
                == '10':
            try:
                exp = int(food_book.get('maxexp') or 0)
            except (TypeError, ValueError):
                pass
        if grown is not food_book:
            # Raw cell is 'id' (SkillBookConfig.skillbookid).
            food = dict(food, goods_id=str(grown.get('id')))
        food = dict(food, attributes=self._exp_set(food.get('attributes'),
                                                   exp))
        try:
            self.delete_role_bag_slot(rid, eater_slot)
        except Exception:
            pass
        try:
            self.update_role_bag_slot(
                rid, food_slot, goods_id=food.get('goods_id'),
                attributes=food.get('attributes'))
        except Exception:
            pass
        return tuple(self._skillbook_fed_frames(
            rid, role, food, eater, eater_slot, CMD_SKILLBOOK_MOVE))

    @staticmethod
    def _skillbook_feed_gate(capped_book, eater_book, food_book):
        """tunshi/yjTunshi gates: [0, code] or None.

        tunshi reads the cap book from the food, yjTunshi from the eater
        (bytecode order); the type check always uses the eater's kind.
        """
        try:
            # Raw cell is 'specialtype' (SkillBookConfig.zhuangbei).
            if int(capped_book.get('specialtype') or 0):
                return [0, SKILLBOOK_ERR_ZHUANG_BEI]
        except (TypeError, ValueError):
            pass
        try:
            kind = int(eater_book.get('jinengtype') or 0)
        except (TypeError, ValueError):
            kind = 0
        if kind != 0 and str(eater_book.get('gongnengtype')) != \
                str(food_book.get('gongnengtype')):
            return [0, SKILLBOOK_ERR_TYPE]
        try:
            level = int(capped_book.get('skillbooklevel') or 0)
        except (TypeError, ValueError):
            level = 0
        if level == 10:
            return [0, SKILLBOOK_ERR_MAX_LEVEL]
        return None

    def _skillbook_fed_frames(self, rid, role, food, eater, eater_slot,
                              cmd):
        """30106 push plus the devour reply for one fed book."""
        food_map = self.bag_goods_map(role, food)
        frames = [frame(amf3_encode([str(CMD_EQUIP_CHANGE), [food_map]]))]
        log.info('conn %d: devour event skipped (no bus)', self.conn_id)
        frames.append(frame(amf3_encode(
            [str(cmd), [1, [food.get('slot_num'), food_map],
                        [eater_slot, None]]])))
        return frames

    def skillbook_tunshi(self, msg):
        """Command 99002: yjTunshi one-key devour of bag books.

        C> [eaterSlot, [foodSlots]]: every food is validated first
        (eater slot or unknown food [0, 99000], equipped [0, 99001],
        type mismatch [0, 99003], eater at cap [0, 99002]); then each
        food feeds the eater in order, pushing 30106 once at the end and
        replying [1, [eaterSlot, formart]]. An eater that hits level 10
        mid-list stops early with the same push+reply. Bound books pass
        their bind to the eater.
        """
        args = self.safe(msg, 1, []) or []
        try:
            eater_slot = int(args[0])
            foods = [int(s) for s in (args[1] or [])]
        except (TypeError, ValueError, IndexError):
            return None
        role, rid = self._skill_role()
        if role is None or not foods:
            return None
        if self.config is None:
            return None
        eater = self._skillbook_bag_slot(rid, eater_slot)
        if eater is None:
            return frame(amf3_encode(
                [str(CMD_SKILLBOOK_TUNSHI), [0, SKILLBOOK_ERR]]))
        batch = []
        for slot in foods:
            if slot == eater_slot:
                return frame(amf3_encode(
                    [str(CMD_SKILLBOOK_TUNSHI), [0, SKILLBOOK_ERR]]))
            item = self._skillbook_bag_slot(rid, slot)
            if item is None:
                return frame(amf3_encode(
                    [str(CMD_SKILLBOOK_TUNSHI), [0, SKILLBOOK_ERR]]))
            eater_book = self.config.skillbook_book(eater.get('goods_id'))
            food_book = self.config.skillbook_book(item.get('goods_id'))
            if eater_book is None or food_book is None:
                log.info('conn %d: bulk devour of unlisted book stays silent',
                         self.conn_id)
                return None
            err = self._skillbook_feed_gate(eater_book, eater_book,
                                              food_book)
            if err is not None:
                return frame(amf3_encode([str(CMD_SKILLBOOK_TUNSHI), err]))
            batch.append((slot, item, food_book))
        for slot, item, food_book in batch:
            eater_book = self.config.skillbook_book(eater.get('goods_id'))
            if eater_book is None:
                return None
            try:
                capped = int(eater_book.get('skillbooklevel') or 0) == 10
            except (TypeError, ValueError):
                capped = False
            if capped:
                food_map = self.bag_goods_map(role, eater)
                return tuple([
                    frame(amf3_encode(
                        [str(CMD_EQUIP_CHANGE), [food_map]])),
                    frame(amf3_encode(
                        [str(CMD_SKILLBOOK_TUNSHI),
                         [1, [eater_slot, food_map]]]))])
            try:
                extra = int(food_book.get('jcexp') or 0)
            except (TypeError, ValueError):
                extra = 0
            exp = self._exp_get(eater.get('attributes')) + \
                self._exp_get(item.get('attributes')) + extra
            grown = self._skillbook_promote(eater_book, exp)
            if grown is not eater_book and str(grown.get('skillbooklevel')) \
                    == '10':
                try:
                    exp = int(eater_book.get('maxexp') or 0)
                except (TypeError, ValueError):
                    pass
            if grown is not eater_book:
                eater = dict(eater, goods_id=str(grown.get('id')))
            eater = dict(eater,
                         attributes=self._exp_set(eater.get('attributes'), exp))
            try:
                bound = int(item.get('bind') or 0) == 1
            except (TypeError, ValueError):
                bound = False
            if bound:
                eater = dict(eater, bind=1)
            try:
                self.update_role_bag_slot(
                    rid, eater_slot, goods_id=eater.get('goods_id'),
                    attributes=eater.get('attributes'), bind=eater.get('bind'))
            except Exception:
                pass
            try:
                take = int(item.get('count') or 0)
            except (TypeError, ValueError):
                take = 0
            self._skillbook_decr(rid, slot, take if take > 0 else 1)
            log.info('conn %d: bulk devour event skipped (no bus)',
                     self.conn_id)
        food_map = self.bag_goods_map(role, eater)
        return tuple([
            frame(amf3_encode([str(CMD_EQUIP_CHANGE), [food_map]])),
            frame(amf3_encode([str(CMD_SKILLBOOK_TUNSHI),
                               [1, [eater_slot, food_map]]]))])

    def bag_goods(self):
        """Command 30000: BagServiceImpl.getBagGoods -> Object[5].

        [goodsMapsOrNull (slots 1..150, StoreGoodsOutput.formart), bagLockVo
        or null, bagMaxSlot, storageLockVo or null, storageMaxSlot]. Lock VOs
        are [slotNum, unlockAtMs] or null once capacity reaches the max.
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        try:
            slots = self.get_role_bag_slots(role.get('id')) or []
        except Exception:
            slots = []
        try:
            state = self.get_role_bag_state(role.get('id')) or {}
        except Exception:
            state = {}
        goods = [self.bag_goods_map(role, slot) for slot in slots] or None
        bag_max = self.config.kaige_max_slot_num('B') if self.config else 0
        storage_max = self.config.kaige_max_slot_num('C') if self.config else 0
        return frame(amf3_encode(['30000', [
            goods,
            self.bag_lock_vo(state, 'bag', bag_max),
            bag_max,
            self.bag_lock_vo(state, 'storage', storage_max),
            storage_max]]))

    def storage_goods(self):
        """Command 30002: BagServiceImpl.getStorageGoods -> Object[3].

        [goodsMapsOrNull (slots 301..500, StoreGoodsOutput.formart),
        storageLockVo or null, storageMaxSlot]. Same row maps as 30000.
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        try:
            slots = self.get_role_bag_slots(role.get('id'), 301, 500) or []
        except Exception:
            slots = []
        try:
            state = self.get_role_bag_state(role.get('id')) or {}
        except Exception:
            state = {}
        goods = [self.bag_goods_map(role, slot) for slot in slots] or None
        storage_max = self.config.kaige_max_slot_num('C') if self.config else 0
        return frame(amf3_encode(['30002', [
            goods,
            self.bag_lock_vo(state, 'storage', storage_max),
            storage_max]]))

    def bag_move(self, msg):
        """Command 30004: BagEasyAction.move -> moveGoodses -> 30004 reply.

        C> [bagRowId, fromSlot, toSlot]. Same-slot moves are silent
        (the action returns before the service). Errors send [0, code]
        (430206 invalid, 430202 locked slot); success sends [1, moveVo,
        moveVo] where each VO is [bagId, slot, count, bind] (StoreGoods-
        Output.formatMove) or null. Stackable goods merge counts up to the
        goods maxstack, deleting a fully merged source row; anything else
        swaps slots. Mount-gear slots (-104..-101) answer 430206: that
        subsystem's tables are unmigrated, so the move cannot be honored.
        """
        args = self.safe(msg, 1, []) or []
        if len(args) < 3:
            return None
        bag_id, from_slot, to_slot = str(args[0]), args[1], args[2]
        try:
            from_slot, to_slot = int(from_slot), int(to_slot)
        except (TypeError, ValueError):
            return None
        if from_slot == to_slot:
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        if not _bag_slots_can_move(from_slot, to_slot):
            return frame(amf3_encode(['30004', [0, BAG_ERR_OPERATE_INVALID]]))
        if 'zuoqi' in (_bag_zone(from_slot), _bag_zone(to_slot)):
            log.info('conn %d: 30004 into mount-gear slots (unported)',
                     self.conn_id)
            return frame(amf3_encode(['30004', [0, BAG_ERR_OPERATE_INVALID]]))
        rid = role.get('id')
        try:
            src = self.get_role_bag_slot_by_bag_id(rid, bag_id)
        except Exception:
            src = None
        if src is None or src.get('slot_num') != from_slot:
            return frame(amf3_encode(['30004', [0, BAG_ERR_OPERATE_INVALID]]))
        try:
            dst = self.get_role_bag_slot(rid, to_slot)
        except Exception:
            dst = None
        # checkCanMove: a treasure-hunt row only moves into an empty slot.
        if dst is not None and _bag_zone(from_slot) == 'xunbao':
            return frame(amf3_encode(['30004', [0, BAG_ERR_OPERATE_INVALID]]))
        if not self._bag_slot_actived(rid, to_slot, from_slot):
            return frame(amf3_encode(
                ['30004', [0, BAG_ERR_NOT_ACTIVATED_SLOT]]))
        if dst is not None and self._bag_can_stack(src, dst):
            return frame(amf3_encode(['30004', self._bag_stack(rid, src, dst)]))
        self.move_role_bag_slot(rid, from_slot, to_slot)
        moved = dict(src, slot_num=to_slot)
        vo1 = [moved.get('bag_id'), to_slot, moved.get('count') or 0,
               moved.get('bind') or 0]
        vo2 = None
        if dst is not None:
            other = dict(dst, slot_num=from_slot)
            vo2 = [other.get('bag_id'), from_slot, other.get('count') or 0,
                   other.get('bind') or 0]
        return frame(amf3_encode(['30004', [1, vo1, vo2]]))

    def _bag_slot_actived(self, role_id, to_slot, from_slot):
        """BagServiceImpl.checkBagSlotIsActived: storageCap + 300 >= slot."""
        if to_slot < 0:
            return False
        if _bag_zone(from_slot) == 'xunbao' and _bag_zone(to_slot) == 'xunbao':
            return True
        try:
            state = self.get_role_bag_state(role_id) or {}
        except Exception:
            state = {}
        try:
            capacity = int(state.get('storage_capacity') or 0)
        except (TypeError, ValueError):
            capacity = 0
        return capacity + 300 >= to_slot

    def _bag_can_stack(self, src, dst):
        """StoreGoodsUtil.checkCanStack: same goods/bind/expire, room left."""
        if self.config is None:
            return False
        if src.get('goods_id') != dst.get('goods_id'):
            return False
        if (src.get('bind') or 0) != (dst.get('bind') or 0):
            return False
        if (src.get('expire_time') or 0) != (dst.get('expire_time') or 0):
            return False
        max_stack = self.config.goods_max_stack(src.get('goods_id'))
        if not max_stack:
            return False
        try:
            return ((int(src.get('count') or 0) < max_stack)
                    and (int(dst.get('count') or 0) < max_stack))
        except (TypeError, ValueError):
            return False

    def _bag_stack(self, role_id, src, dst):
        """Merge stackable rows up to maxstack; returns the [1, vo1, vo2] body."""
        max_stack = self.config.goods_max_stack(src.get('goods_id')) or 0
        space = max_stack - int(dst.get('count') or 0)
        if space >= int(src.get('count') or 0):
            # Full merge: the target absorbs the source, which is deleted.
            # Java still reports the emptied source row (count 0).
            total = int(dst.get('count') or 0) + int(src.get('count') or 0)
            self.update_role_bag_slot(role_id, dst.get('slot_num'),
                                      count=total)
            self.delete_role_bag_slot(role_id, src.get('slot_num'))
            vo1 = [src.get('bag_id'), src.get('slot_num'), 0,
                   src.get('bind') or 0]
            vo2 = [dst.get('bag_id'), dst.get('slot_num'), total,
                   dst.get('bind') or 0]
        else:
            # Partial fill: the target tops up, the source keeps the rest.
            rest = int(src.get('count') or 0) - space
            self.update_role_bag_slot(role_id, src.get('slot_num'),
                                      count=rest)
            self.update_role_bag_slot(role_id, dst.get('slot_num'),
                                      count=max_stack)
            vo1 = [src.get('bag_id'), src.get('slot_num'), rest,
                   src.get('bind') or 0]
            vo2 = [dst.get('bag_id'), dst.get('slot_num'), max_stack,
                   dst.get('bind') or 0]
        return [1, vo1, vo2]

    def bag_split(self, msg):
        """Command 30100: splitGoods; pushes 30104 + 30105, replies 30100 null.

        C> [bagRowId, slotArg, toSlot, count]: the service requires the two
        slot args to be equal (checkSplitGoods, traced literally) and uses
        their value as the target slot; the source slot is the row's own.
        Guards (action): non-empty id, toSlot > 0, slotArg/count >= 0, else
        silence. Errors send [0, code] (430201 unknown row, 430206 slot-arg
        mismatch, 430205 count >= row count, 430204 target occupied, 430202
        locked slot). Success decrements the source, inserts the new row,
        pushes 30104 [[[rowId, newCount]]] then 30105 [formartMap], and the
        30100 reply itself is null (splitGoods returns null). Auto-use
        goods only queue an internal stage message in Java; without a stage
        bus that trigger is logged and skipped.
        """
        args = self.safe(msg, 1, []) or []
        if len(args) < 4:
            return None
        bag_id = args[0]
        try:
            slot_arg, to_slot, count = int(args[1]), int(args[2]), int(args[3])
        except (TypeError, ValueError):
            return None
        if not bag_id or to_slot <= 0 or slot_arg < 0 or count < 0:
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        rid = role.get('id')
        try:
            src = self.get_role_bag_slot_by_bag_id(rid, str(bag_id))
        except Exception:
            src = None
        if src is None:
            return frame(amf3_encode(
                ['30100', [0, BAG_ERR_NOT_FOUND_GOODS]]))
        if slot_arg != to_slot:
            return frame(amf3_encode(
                ['30100', [0, BAG_ERR_OPERATE_INVALID]]))
        if count >= int(src.get('count') or 0):
            return frame(amf3_encode(
                ['30100', [0, BAG_ERR_SPLIT_COUNT]]))
        try:
            dst = self.get_role_bag_slot(rid, to_slot)
        except Exception:
            dst = None
        if dst is not None:
            return frame(amf3_encode(
                ['30100', [0, BAG_ERR_SPLIT_SLOT_HAVE_GOODS]]))
        if not self._bag_slot_actived(rid, to_slot, src.get('slot_num')):
            return frame(amf3_encode(
                ['30100', [0, BAG_ERR_NOT_ACTIVATED_SLOT]]))
        rest = int(src.get('count') or 0) - count
        self.update_role_bag_slot(rid, src.get('slot_num'), count=rest)
        frames = [frame(amf3_encode(
            [str(CMD_BAG_SPLIT_COUNT), [[[src.get('bag_id'), rest]]]]))]
        new_id = self.insert_role_bag_slot(rid, {**src, 'slot_num': to_slot,
                                                 'count': count,
                                                 'bag_id': None})
        new_row = dict(src, slot_num=to_slot, count=count, bag_id=new_id)
        frames.append(frame(amf3_encode(
            [str(CMD_BAG_SPLIT_NEW), [self.bag_goods_map(role, new_row)]])))
        if self.config is not None and self._bag_goods_autouse(
                src.get('goods_id')):
            log.info('conn %d: split autouse goods %r (no stage bus; skipped)',
                     self.conn_id, src.get('goods_id'))
        frames.append(frame(amf3_encode(['30100', None])))
        return tuple(frames)

    def _bag_goods_autouse(self, goods_id):
        """Whether goods.jat marks a goods id auto-used on gain."""
        row = self.config._goods_table().get(str(goods_id))
        if row is None:
            return False
        return str(row.get('autouse') or '') == '1'

    def bag_delete(self, msg):
        """Command 30102: deleteBagGoods -> 30102 [1, [bagRowId]].

        C> [bagRowId, slotArg]: the slot arg is validated (>= 0) but only
        the row id selects the row (removeGoodsById). A missing row still
        replies success with an empty id list (BagResponse.getRemoveIds on
        the error path). Unlike discardGoods, the delete action has no bind
        check, so bound rows are deletable here exactly as in Java.
        """
        args = self.safe(msg, 1, []) or []
        if len(args) < 2:
            return None
        bag_id = args[0]
        try:
            slot_arg = int(args[1])
        except (TypeError, ValueError):
            return None
        if slot_arg < 0 or not bag_id:
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        rid = role.get('id')
        try:
            src = self.get_role_bag_slot_by_bag_id(rid, str(bag_id))
        except Exception:
            src = None
        if src is None:
            return frame(amf3_encode(['30102', [1, []]]))
        self.delete_role_bag_slot(rid, src.get('slot_num'))
        return frame(amf3_encode(['30102', [1, [src.get('bag_id')]]]))

    def bag_discard(self, msg):
        """Command 30101: discardBagGoods -> discardGoods -> queue flush.

        C> [bagRowId, slotArg]: the slot arg is validated (>= 0) but only
        the row id selects the row. A missing row is silent (the service
        returns before queuing anything). A bound row queues 30101 [0,
        430218] (null bind proceeds, matching Java's ifnull branch).
        Success removes the row and queues 30102 [1, [bagRowId]]; the
        stage message (S:DISCARD_GOODS) and BagDropGoodsEvent have no bus
        here, so that tail is logged and skipped.
        """
        args = self.safe(msg, 1, []) or []
        if len(args) < 2:
            return None
        bag_id = args[0]
        try:
            slot_arg = int(args[1])
        except (TypeError, ValueError):
            return None
        if slot_arg < 0 or not bag_id:
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        rid = role.get('id')
        try:
            src = self.get_role_bag_slot_by_bag_id(rid, str(bag_id))
        except Exception:
            src = None
        if src is None:
            return None
        bind = src.get('bind')
        try:
            bound = bind is not None and int(bind) == 1
        except (TypeError, ValueError):
            bound = False
        if bound:
            return frame(amf3_encode(
                ['30101', [0, BAG_ERR_BIND_NO_DISCARD]]))
        if not self.delete_role_bag_slot(rid, src.get('slot_num')):
            return frame(amf3_encode(
                ['30101', [0, BAG_ERR_NOT_FOUND_GOODS]]))
        log.info('conn %d: discarded %r (stage/event tail skipped)',
                 self.conn_id, src.get('goods_id'))
        return frame(amf3_encode(['30102', [1, [src.get('bag_id')]]]))

    def prop_use(self, msg):
        """Command 30301: PropStageAction.consumeGoods -> useProp pipeline.

        C> is the bag-row guid string (empty is silent). Unknown rows,
        goods, or skills are silent like Java's null paths; dead roles
        are silent (isDead gate); check failures reply [0, code]. Only
        skills 1/2/3/5/11/14/33/35/36/37 have portable effects so far
        (3 is the taofa scroll hook, 33/35 the longhun/longling mount
        pills); other known skills stay open and silent pending their
        systems (documented).
        """
        guid = msg if isinstance(msg, str) else self.safe(msg, 1, None)
        if not guid or self.config is None:
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        try:
            dead = int(role.get('hp') or 1) <= 0
        except (TypeError, ValueError):
            dead = False
        if dead:
            return None
        rid = role.get('id')
        try:
            row = self.get_role_bag_slot_by_bag_id(rid, str(guid))
        except Exception:
            row = None
        if row is None:
            return None
        grow = self.config._goods_table().get(str(row.get('goods_id')))
        if grow is None:
            return None
        try:
            skill = int(grow.get('skill') or 0)
        except (TypeError, ValueError):
            return None
        if skill not in PROP_SKILL_USE:
            return None
        err = self._prop_use_check(role, grow, skill)
        if err is not None:
            return frame(amf3_encode([str(CMD_PROP_USE), [0, err]]))
        # consumePrior default true, false for HpMp/skillBook/LiHe/TaoFa
        # (their services consume internally, so the pipeline post-decrs),
        # and null for LongHun/LongLing (useLongHun/useLongLing decr
        # inside, so the pipeline never does).
        prior = None if skill in (33, 35) else skill not in (1, 37, 11, 3)
        if prior and not self._prop_decr(rid, row):
            return None
        frames = self._prop_effect(role, rid, row, grow, skill)
        if frames is None:
            return None
        frames, terminal = frames
        if frames is None:
            return None
        if terminal:
            if prior is False:
                self._prop_decr(rid, row)
            log.info('conn %d: used %r (events skipped, no bus)',
                     self.conn_id, row.get('goods_id'))
            frames.append(frame(amf3_encode(
                [str(CMD_PROP_USE), [1, row.get('bag_id')]])))
        return tuple(frames) if len(frames) > 1 else frames[0]

    def _prop_use_check(self, role, grow, skill=0):
        """PropType.useCheck gates: consume category, level, job, vip."""
        category = str(grow.get('category') or '')
        if category not in PROP_CONSUME_CATEGORIES:
            return PROP_ERROR_100002
        # LiHe owns its level gate (canUseLiHe levelneed -> 1000), so the
        # generic levelreq check does not pre-empt it.
        if skill != 11:
            try:
                need = int(grow.get('levelreq') or 0)
            except (TypeError, ValueError):
                need = 0
            try:
                level = int(role.get('level') or 0)
            except (TypeError, ValueError):
                level = 0
            if level < need:
                return PROP_ERROR_100003
        gate = str(grow.get('job') or '')
        if gate not in ('', '0') and gate != str(role.get('job') or ''):
            return PROP_ERROR_100004
        return None

    def _prop_decr(self, rid, row, take=1):
        """decrGoodsesById for one use; False when the row is gone."""
        try:
            have = int(row.get('count') or 0)
        except (TypeError, ValueError):
            have = 0
        if have <= 0:
            return False
        rest = have - take
        if rest > 0:
            self.update_role_bag_slot(rid, row.get('slot_num'), count=rest)
        else:
            self.delete_role_bag_slot(rid, row.get('slot_num'))
        row['count'] = max(rest, 0)
        return True

    def _prop_effect(self, role, rid, row, grow, skill):
        """useDaoJu for portable skills; None stays silent like Java."""
        if skill == 37:
            return self._prop_skillbook(role, rid, row, grow), False
        if skill == 11:
            return self._prop_lihe(role, rid, row, grow), False
        if skill == 3:
            return self._prop_taofa(role, rid, row, grow)
        if skill == 36:
            return self._prop_dan(role, rid, row, grow)
        if skill == 33:
            return self._prop_longhun(role, rid, row, grow)
        if skill == 35:
            return self._prop_longling(role, rid, row, grow)
        if skill == 2:
            frames = self._prop_exp(role, rid, grow)
        elif skill == 5:
            frames = self._prop_zhenqi(role, rid, grow)
        elif skill == 14:
            frames = self._prop_yxb(role, rid, grow)
        else:
            frames = self._prop_hpmp(role, rid, row, grow)
        if frames is None:
            return None
        return frames, True

    def _prop_exp(self, role, rid, grow):
        """ExpType: incrExp(addExp) persists and pushes 12001 like kills."""
        try:
            amount = int(grow.get('addexp') or 0)
        except (TypeError, ValueError):
            amount = 0
        _total, _level, _gained, exp_frames = self._role_gain_exp(
            role, rid, amount)
        return exp_frames

    def _prop_zhenqi(self, role, rid, grow):
        """ZhenQiType: incrZhenqi(addZhenqi) persists; no direct push."""
        try:
            amount = int(grow.get('addzhenqi') or 0)
        except (TypeError, ValueError):
            amount = 0
        total = int(role.get('zhenqi') or 0) + amount
        self.save_role_state(rid, zhenqi=total)
        return []

    def _prop_yxb(self, role, rid, grow):
        """YxbType: account incr(addGold, YXB) persists, pushes 32010."""
        try:
            amount = int(grow.get('addgold') or 0)
        except (TypeError, ValueError):
            amount = 0
        total = int(role.get('tongqian') or 0) + amount
        self.save_role_state(rid, tongqian=total)
        role = dict(role, tongqian=total)
        return [self.money_info(role)]

    def _prop_hpmp(self, role, rid, row, grow):
        """HpMpPropType: 1500ms hpcd gate; the heal buff is stage-side."""
        now = int(time.time() * 1000)
        last = self._prop_hpcd.get(rid) or 0
        if now - last < PROP_HP_CD_MS:
            return None
        self._prop_hpcd[rid] = now
        log.info('conn %d: prop buff %r queued stage-side (skipped)',
                 self.conn_id, grow.get('buffid'))
        return []

    def _prop_skillbook(self, role, rid, row, grow):
        """skillBook: autoStudySkill2 learn gates; consume lives inside."""
        skill_id = grow.get('jhzqjn') or None
        info = self.config.skill_info(skill_id, 1) if skill_id else None
        if info is None:
            return [frame(amf3_encode(
                [str(CMD_PROP_USE), [0, PROP_ERROR_100008]]))]
        try:
            learned = [s for s in self.get_role_skills(rid)
                       if s.get('category') == skill_id]
        except Exception:
            learned = []
        if learned:
            return self._prop_study_error(SKILL_ERROR_STUDY)
        try:
            need = int(info.get('levelneed') or 0)
        except (TypeError, ValueError):
            need = 0
        try:
            level = int(role.get('level') or 0)
        except (TypeError, ValueError):
            level = 0
        if level < need:
            return self._prop_study_error(SKILL_ERROR_LEVEL)
        gate = str(info.get('needjob') or '')
        if gate != '0' and gate != str(role.get('job') or ''):
            return self._prop_study_error(SKILL_ERROR_JOB)
        try:
            info_level = int(info.get('level') or 0)
        except (TypeError, ValueError):
            info_level = 0
        frames = []
        if info_level <= level:
            self.save_role_skill(rid, skill_id, 1)
        self._prop_decr(rid, row)
        frames.append(frame(amf3_encode(
            [str(CMD_STUDY_SKILL), [info.get('skilltype'), 1]])))
        frames.append(frame(amf3_encode(
            [str(CMD_PROP_USE), [1, row.get('bag_id')]])))
        return frames

    def _prop_dan(self, role, rid, row, grow):
        """AttributeDan: eatShuxinDan cap math; consume runs twice like Java."""
        goods_id = str(row.get('goods_id'))
        dan = self.config.dan_buff(goods_id)
        if dan is None:
            return [], True
        try:
            level = int(role.get('level') or 0)
        except (TypeError, ValueError):
            return None
        zhujue = self.config.role_attribute_row(level)
        if zhujue is None:
            return None
        try:
            cap = int(zhujue.get(goods_id) or 0)
        except (TypeError, ValueError):
            return None
        try:
            buffs = self.get_role_attr_buffs(rid) or []
        except Exception:
            buffs = []
        cur = 0
        for buff in buffs:
            if buff.get('attribute_id') == goods_id:
                try:
                    cur = int(buff.get('count') or 0)
                except (TypeError, ValueError):
                    cur = 0
        if cur >= cap:
            return ([frame(amf3_encode(
                [str(CMD_PROP_USE), [0, DAN_ERROR_CAPPED]]))], False)
        total = cur + 1
        take = 1
        if total > cap:
            take = 1 - (total - cap)
            total = cap
        self._prop_decr(rid, row, take)
        merged = [dict(b) for b in buffs
                  if b.get('attribute_id') != goods_id]
        merged.append({'attribute_id': goods_id, 'count': total})
        self.save_role_attr_buffs(rid, merged)
        log.info('conn %d: dan %r change event skipped (no bus)',
                 self.conn_id, goods_id)
        return ([frame(amf3_encode(
            [str(CMD_ATTR_CHANGE), [goods_id, total]]))], True)

    @staticmethod
    def _zuoqi_att_map(mount):
        """attribute_goods_id {goods: n} map; bad blobs read as empty."""
        try:
            text = mount.get('attribute_goods_id')
        except AttributeError:
            return {}
        if not text:
            return {}
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        out = {}
        for key, value in data.items():
            try:
                out[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        return out

    def _prop_longhun(self, role, rid, row, grow):
        """Skill 33 LongHun pill: bump the goods count, push 33010."""
        outcome = self._prop_longdan(role, rid, row, grow, 'xlimit')
        if outcome is None:
            return None
        if outcome[0] == 'err':
            return ([frame(amf3_encode(
                [str(CMD_PROP_USE), [0, outcome[1]]]))], False)
        return ([frame(amf3_encode(
            [str(CMD_ZUOQI_LONGHUN), outcome[1]]))], True)

    def _prop_longling(self, role, rid, row, grow):
        """Skill 35 LongLing pill: bump the goods count, push 33012."""
        outcome = self._prop_longdan(role, rid, row, grow, 'perxlimit')
        if outcome is None:
            return None
        if outcome[0] == 'err':
            return ([frame(amf3_encode(
                [str(CMD_PROP_USE), [0, outcome[1]]]))], False)
        return ([frame(amf3_encode(
            [str(CMD_ZUOQI_LONGLING), outcome[1]]))], True)

    def _prop_longdan(self, role, rid, row, grow, cap_column):
        """useLongHun/useLongLing shared body; ('ok', total)/('err', code).

        The two ServiceImpl bodies differ only in the cap column and
        the push id: GoodsConfig.zuoqiLv above the mount rank answers
        520004, a missing (rank, clamped level) row answers 520004, and
        checkAttDan/checkAttLuckyDan answers 520011 once this goods id
        already fills the row's xlimit/perxlimit cap (an absent id
        always passes, even when the cap is 0). The decr runs inside
        (consumePrior is null, so the pipeline never decrs); the map is
        bumped, persisted, and its new count returned. Events ride no
        bus, matching the other pill effects.
        """
        goods_id = str(row.get('goods_id') or '')
        if not goods_id:
            return ('err', GENERAL_INEXISTENCE)
        mount = self._zuoqi_row(rid)
        if mount is None:
            return None
        try:
            rank = int(mount.get('zuoqi_rank') or 0)
        except (TypeError, ValueError):
            rank = 0
        try:
            need = int(grow.get('zuoqilv') or 0)
        except (TypeError, ValueError):
            need = 0
        if need > rank:
            return ('err', ZUOQI_RANK_CODE)
        pet = self.config.zuoqi_pet(rank, role.get('level'))
        if pet is None:
            return ('err', ZUOQI_RANK_CODE)
        try:
            cap = int(pet[1].get(cap_column) or 0)
        except (TypeError, ValueError):
            cap = 0
        counts = self._zuoqi_att_map(mount)
        if goods_id in counts and counts[goods_id] >= cap:
            return ('err', ZUOQI_ATT_CAP_CODE)
        self._prop_decr(rid, row)
        total = counts.get(goods_id, 0) + 1
        counts[goods_id] = total
        mount['attribute_goods_id'] = json.dumps(counts)
        self._zuoqi_save(rid, mount)
        return ('ok', total)

    def _prop_lihe(self, role, rid, row, grow):
        """LiHe: deterministic gift boxes; lottery/vip boxes stay open."""
        goods_id = str(row.get('goods_id'))
        box = self.config.lihe_box(goods_id)
        if box is None:
            return [frame(amf3_encode(
                [str(CMD_PROP_USE), [0, PROP_ERROR_100008]]))]
        if (grow.get('kaiqifenlei') or '') != '':
            return None
        if box['zubao']:
            return None
        err = self._prop_lihe_gate(role, rid, box)
        if err is not None:
            return [frame(amf3_encode([str(CMD_PROP_USE), [0, err]]))]
        fixed = box['fixed']
        if fixed is None:
            return None
        if not self._prop_fits(rid, fixed, box['bind']):
            return [frame(amf3_encode(
                [str(CMD_PROP_USE), [0, GENERAL_NOSLOT]]))]
        self._prop_decr(rid, row)
        for gid, need in box['itemneed'].items():
            self._prop_take(rid, gid, need)
        self._prop_pay(rid, role, box)
        self._prop_grant(rid, fixed, box['bind'])
        log.info('conn %d: opened %r (events skipped, no bus)',
                 self.conn_id, goods_id)
        return [frame(amf3_encode(
                  [str(CMD_LIHE_PREVIEW),
                   [goods_id, [[fixed['goods'], fixed['count']]]]])),
                frame(amf3_encode(
                    [str(CMD_PROP_USE), [0, [[goods_id, 1]]]]))]

    def _prop_lihe_gate(self, role, rid, box):
        """canUseLiHe: level, mount rank, copper/yb/bind, item costs."""
        try:
            level = int(role.get('level') or 0)
        except (TypeError, ValueError):
            level = 0
        if level < box['levelneed']:
            return GENERAL_LEVEL
        try:
            rank = int((self.get_role_zuoqi(rid) or {}).get('zuoqi_rank')
                         or 0)
        except (TypeError, ValueError, AttributeError):
            rank = 0
        if rank < box['zuoqi']:
            return PROP_ERROR_ZUOQI
        for need, column, code in (
                (box['jb'], 'tongqian', GENERAL_JB),
                (box['yb'], 'lingshi', GENERAL_YB),
                (box['bindyb'], 'bind_lingshi', GENERAL_BINDYB)):
            try:
                have = int(role.get(column) or 0)
            except (TypeError, ValueError):
                have = 0
            if have < need:
                return code
        # Item costs are not presence-gated here; the take step consumes
        # what is there (white-box golden: unmet itemneed still gates None).
        return None

    def _prop_take(self, rid, goods_id, need):
        """Decrement a cost goods across slots, slot order ascending."""
        try:
            slots = self.get_role_bag_slots(rid, -1000000, 1000000) or []
        except Exception:
            return
        left = need
        for slot in sorted(slots, key=lambda s: s.get('slot_num') or 0):
            if left <= 0:
                break
            if str(slot.get('goods_id')) != str(goods_id):
                continue
            try:
                have = int(slot.get('count') or 0)
            except (TypeError, ValueError):
                have = 0
            take = min(have, left)
            if take <= 0:
                continue
            left -= take
            rest = have - take
            try:
                if rest > 0:
                    self.update_role_bag_slot(rid, slot.get('slot_num'),
                                            count=rest)
                else:
                    self.delete_role_bag_slot(rid, slot.get('slot_num'))
            except Exception:
                break

    def _prop_pay(self, rid, role, box):
        """openLiHe currency decr (persist only; pushes ride the bus)."""
        updates = {}
        for need, column in ((box['jb'], 'tongqian'),
                             (box['yb'], 'lingshi'),
                             (box['bindyb'], 'bind_lingshi')):
            if need <= 0:
                continue
            try:
                updates[column] = int(role.get(column) or 0) - need
            except (TypeError, ValueError):
                pass
        if updates:
            try:
                self.save_role_state(rid, **updates)
            except Exception:
                pass

    def prop_duoxuan(self, msg):
        """Command 30305: PropStageAction.duoxuanlibao -> duoXuanLiBao.

        C> is [bagSlot, choiceKey] (choiceKey is a libao1..4 key). Bad
        shapes or types are silent like Java's casts; a missing slot
        replies [0, 1005], short YB [0, 1002], a full bag [0, 1006],
        and a failed take [0, 100009]. Unknown boxes or choices stay
        silent (Java NPEs on the missing config). Success consumes one
        box, decrs the YB cost, grants the choice, pushes 30304
        [configId, [[goodsId, count]]] ahead of the [1, bagId] reply.
        """
        args = msg if isinstance(msg, (list, tuple)) else None
        if args is None or len(args) != 2:
            return None
        slot, choice = args[0], args[1]
        if isinstance(slot, bool) or not isinstance(slot, int):
            return None
        if not isinstance(choice, str) or not choice:
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None or self.config is None:
            return None
        rid = role.get('id')
        try:
            box_row = self.get_role_bag_slot(rid, slot)
        except Exception:
            box_row = None
        if box_row is None:
            return frame(amf3_encode(
                [str(CMD_PROP_DUOXUAN), [0, GENERAL_GOODS]]))
        cfg = self.config.duoxuan_box(str(box_row.get('goods_id')))
        if cfg is None:
            return None
        opt = cfg['options'].get(choice)
        if opt is None:
            return None
        gold = opt['gold']
        if gold:
            try:
                have = int(role.get('lingshi') or 0)
            except (TypeError, ValueError):
                have = 0
            if have < gold:
                return frame(amf3_encode(
                    [str(CMD_PROP_DUOXUAN), [0, GENERAL_YB]]))
        for gid, count, bind in opt['goods']:
            if not self._prop_fits(rid, {'goods': gid, 'count': count},
                                   bind):
                return frame(amf3_encode(
                    [str(CMD_PROP_DUOXUAN), [0, GENERAL_NOSLOT]]))
        if not self._prop_decr(rid, box_row):
            return frame(amf3_encode(
                [str(CMD_PROP_DUOXUAN), [0, PROP_ERROR_100009]]))
        if gold:
            self._bag_money_decr(rid, 'YB', gold)
        self._task_grant(rid, [{'goods_id': gid, 'count': count,
                                'bind': bind}
                               for gid, count, bind in opt['goods']])
        pairs = [[gid, count] for gid, count, _ in opt['goods']]
        log.info('conn %d: duoxuan %r -> %r (events skipped, no bus)',
                 self.conn_id, box_row.get('goods_id'), choice)
        return (frame(amf3_encode(
                    [str(CMD_LIHE_PREVIEW), [cfg['id'], pairs]])),
                frame(amf3_encode(
                    [str(CMD_PROP_DUOXUAN), [1, box_row.get('bag_id')]])))

    def prop_youhui(self, msg):
        """Command 30306: PropStageAction.yougHuiQuanLiBao.

        C> is [bagSlot]. Guards, error codes, and the 30304 push ahead
        of the [1, bagId] reply mirror duoXuanLiBao, except a failed
        take replies [0, 100008] and the reward/cost come from
        youhuiquan.jat (single fixed parcel plus the YB libaocost).
        """
        args = msg if isinstance(msg, (list, tuple)) else None
        if args is None or len(args) != 1:
            return None
        slot = args[0]
        if isinstance(slot, bool) or not isinstance(slot, int):
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None or self.config is None:
            return None
        rid = role.get('id')
        try:
            box_row = self.get_role_bag_slot(rid, slot)
        except Exception:
            box_row = None
        if box_row is None:
            return frame(amf3_encode(
                [str(CMD_PROP_YOUHUI), [0, GENERAL_GOODS]]))
        cfg = self.config.youhui_box(str(box_row.get('goods_id')))
        if cfg is None:
            return None
        cost = cfg['cost']
        if cost:
            try:
                have = int(role.get('lingshi') or 0)
            except (TypeError, ValueError):
                have = 0
            if have < cost:
                return frame(amf3_encode(
                    [str(CMD_PROP_YOUHUI), [0, GENERAL_YB]]))
        for gid, count, bind in cfg['goods']:
            if not self._prop_fits(rid, {'goods': gid, 'count': count},
                                   bind):
                return frame(amf3_encode(
                    [str(CMD_PROP_YOUHUI), [0, GENERAL_NOSLOT]]))
        if not self._prop_decr(rid, box_row):
            return frame(amf3_encode(
                [str(CMD_PROP_YOUHUI), [0, PROP_ERROR_100008]]))
        if cost:
            self._bag_money_decr(rid, 'YB', cost)
        self._task_grant(rid, [{'goods_id': gid, 'count': count,
                                'bind': bind}
                               for gid, count, bind in cfg['goods']])
        pairs = [[gid, count] for gid, count, _ in cfg['goods']]
        log.info('conn %d: youhui %r opened (events skipped, no bus)',
                 self.conn_id, box_row.get('goods_id'))
        return (frame(amf3_encode(
                    [str(CMD_LIHE_PREVIEW), [cfg['id'], pairs]])),
                frame(amf3_encode(
                    [str(CMD_PROP_YOUHUI), [1, box_row.get('bag_id')]])))

    def prop_teshu_count(self, msg):
        """Command 30307: getTeShuTypeCount answers the daily use count.

        C> is the bare special-type string (non-strings are silent
        like Java's cast). Stale day rows reset to 0 first
        (clearTeShuTypeCount: a useStartTime off today re-arms
        useCount 0 with a fresh stamp); missing rows answer 0.
        """
        if not isinstance(msg, str):
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        rid = role.get('id')
        try:
            row = self.get_role_prop(rid, msg)
        except Exception:
            row = None
        if row is not None and not self._prop_count_today(row):
            try:
                self.save_role_prop(rid, msg, use_count=0,
                                    use_start_time=int(time.time() * 1000))
            except Exception:
                pass
            count = 0
        elif row is None:
            count = 0
        else:
            try:
                count = int(row.get('use_count') or 0)
            except (TypeError, ValueError):
                count = 0
        return frame(amf3_encode([str(CMD_PROP_TESHU), count]))

    @staticmethod
    def _prop_count_today(row):
        """dayIsToday over a role_prop use_start_time (server-local day)."""
        try:
            stamp = int(row.get('use_start_time') or 0)
        except (TypeError, ValueError):
            return False
        if stamp <= 0:
            return False
        now = int(time.time() * 1000)
        return (time.localtime(stamp / 1000)[:3] ==
                time.localtime(now / 1000)[:3])

    def _prop_fits(self, rid, fixed, bind):
        """checkBagSlots: reward stacks plus empty slots cover it."""
        try:
            left = int(fixed['count'] or 0)
        except (TypeError, ValueError):
            left = 0
        if left <= 0:
            return True
        try:
            slots = self.get_role_bag_slots(rid, 1, 150) or []
        except Exception:
            slots = []
        try:
            stack = int(self.config.goods_max_stack(fixed['goods']) or 1)
        except (TypeError, ValueError):
            stack = 1
        for slot in slots:
            if self._bag_same_kind(slot, {'goods_id': fixed['goods'],
                                          'bind': bind}):
                try:
                    room = stack - int(slot.get('count') or 0)
                except (TypeError, ValueError):
                    room = 0
                left -= max(room, 0)
        try:
            state = self._bag_state_or_init(rid) or {}
            capacity = int(state.get('bag_capacity') or 0)
        except (TypeError, ValueError):
            capacity = 0
        used = {s.get('slot_num') for s in slots}
        free = sum(1 for n in range(1, capacity + 1) if n not in used)
        return left <= free * stack

    def _prop_grant(self, rid, fixed, bind):
        """putInBag for one fixed reward (no mail fallback here)."""
        self._task_grant(rid, [{'goods_id': fixed['goods'],
                               'count': fixed['count'],
                               'bind': bind}])

    def _prop_study_error(self, code):
        """autoStudySkill2 failure: 42004 error now, 30301 [0,100008] after."""
        return [frame(amf3_encode([str(CMD_STUDY_SKILL), [0, code]])),
                frame(amf3_encode(
                    [str(CMD_PROP_USE), [0, PROP_ERROR_100008]]))]

    def bag_clearup(self, zone):
        """Commands 30001/30003/30006: clearUp/clearUpStorage/clearUpXunBaoBag.

        The request body is ignored (the actions pass only the role id).
        An empty zone replies null; a single row is just moved to the
        zone base. Otherwise BagClearUpUtil.pickup groups, sorts, merges
        and filters the rows, the survivors are renumbered from the base
        and rewritten, and the reply lists one formart map per row.
        """
        lo, hi, base, cmd = BAG_CLEARUP_ZONES[zone]
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        rid = role.get('id')
        try:
            slots = self.get_role_bag_slots(rid, lo, hi) or []
        except Exception:
            slots = []
        if not slots:
            return frame(amf3_encode([cmd, None]))
        if len(slots) == 1:
            final = [dict(slots[0], slot_num=base)]
            self.rewrite_role_bag_slots(rid, final, lo, hi)
            return frame(amf3_encode(
                [cmd, [self.bag_goods_map(role, final[0])]]))
        if self.config is None:
            return None
        rows = [dict(slot) for slot in slots]
        try:
            result = self._bag_pickup(rows)
        except KeyError:
            log.info('conn %d: %s with unconfigured goods (ignored)',
                     self.conn_id, cmd)
            return None
        final = [dict(row, slot_num=slot)
                 for slot, row in enumerate(result, start=base)]
        self.rewrite_role_bag_slots(rid, final, lo, hi)
        return frame(amf3_encode(
            [cmd, [self.bag_goods_map(role, row) for row in final]]))

    def _bag_pickup(self, rows):
        """BagClearUpUtil.pickup: group by sort group, sort, merge, collect.

        Unknown goods raise KeyError (Java's getGoodsSortConfig throws, so
        the whole op dies with no reply). Groups outside 0..4 are dropped
        by the tail loop exactly as in Java; every known goods has sort
        group 0 (the jar never sets sortNum), so only group 0 holds rows.
        """
        groups = {}
        for row in rows:
            key = self.config.goods_sort_num(row.get('goods_id'))
            if key is None:
                raise KeyError(row.get('goods_id'))
            groups.setdefault(key, []).append(row)
        for group in groups.values():
            # SortBagComparator.compare: String.compareTo on the goods id.
            # Config ids are ASCII, where that matches Python's ordering.
            group.sort(key=lambda row: str(row.get('goods_id')))
            self._bag_merge(group)
        result = []
        for index in range(GOODS_SORT_TYPE_SIZE + 1):
            group = groups.get(index)
            if not group:
                continue
            for row in group:
                try:
                    count = int(row.get('count') or 0)
                except (TypeError, ValueError):
                    count = 0
                if count > 0:
                    result.append(row)
        self._bag_bind_sort(result)
        self._bag_expire_sort(result)
        self._bag_count_sort(result)
        return result

    def _bag_merge(self, group):
        """BagClearUpUtil.merge: fold each target's later stackable rows in.

        move = min(source count, maxstack - target count), taken literally:
        with a zero maxstack the target empties into the source. Emptied
        rows stay in the group at count 0 and the pickup tail drops them
        (Java deletes them via ClearBagGoodsCheck). Null bind/expire read
        as 0 (Java would throw on those instead).
        """
        for i in range(len(group) - 1):
            target = group[i]
            max_stack = self.config.goods_max_stack(target.get('goods_id'))
            if max_stack is None:
                raise KeyError(target.get('goods_id'))
            for j in range(i + 1, len(group)):
                src = group[j]
                try:
                    t_count = int(target.get('count') or 0)
                    s_count = int(src.get('count') or 0)
                except (TypeError, ValueError):
                    continue
                if t_count == max_stack:
                    break
                if str(target.get('goods_id')) != str(src.get('goods_id')):
                    continue
                if (target.get('bind') or 0) != (src.get('bind') or 0):
                    continue
                if not self._bag_expire_equal(target.get('expire_time'),
                                             src.get('expire_time')):
                    continue
                move = (s_count if t_count + s_count < max_stack
                        else max_stack - t_count)
                target['count'], src['count'] = t_count + move, s_count - move

    @staticmethod
    def _bag_expire_equal(first, second):
        """BagUtil.compareExpireTime: equal, both expired, or same second.

        A zero expire means permanent and never merges with a timed one.
        Null reads as 0 (Java would throw on a null instead).
        """
        first = first if first is not None else 0
        second = second if second is not None else 0
        if first == second:
            return True
        if first == 0 or second == 0:
            return False
        now = int(time.time() * 1000)
        if first < now and second < now:
            return True
        return first // 1000 == second // 1000

    @staticmethod
    def _bag_same_kind(first, second):
        """Same goods (case-insensitive) and same bind for the order passes."""
        return (str(first.get('goods_id')).lower()
                == str(second.get('goods_id')).lower()
                and (first.get('bind') or 0) == (second.get('bind') or 0))

    def _bag_bind_sort(self, rows):
        """BagClearUpUtil.bindSort: bound before unbound, then count desc.

        A literal bubble pass over same-goods rows (unlike the expire and
        count passes, this one also swaps across binds: unbound yields to
        bound). Integer 0/1 are cached in Java, so its reference compare
        behaves as == here; null binds read as 0 (Java would throw).
        """
        for i in range(len(rows) - 1):
            for j in range(i + 1, len(rows)):
                if (str(rows[i].get('goods_id')).lower()
                        != str(rows[j].get('goods_id')).lower()):
                    continue
                m_count = int(rows[i].get('count') or 0)
                n_count = int(rows[j].get('count') or 0)
                m_bind = rows[i].get('bind') or 0
                n_bind = rows[j].get('bind') or 0
                if ((m_bind == n_bind and m_count < n_count)
                        or (m_bind == 0 and n_bind == 1)):
                    rows[i], rows[j] = rows[j], rows[i]

    def _bag_expire_sort(self, rows):
        """BagClearUpUtil.expireTimeSort: expire ascending, same kind only."""
        for i in range(len(rows) - 1):
            for j in range(i + 1, len(rows)):
                if not self._bag_same_kind(rows[i], rows[j]):
                    continue
                m_exp = rows[i].get('expire_time')
                m_exp = m_exp if m_exp is not None else 0
                n_exp = rows[j].get('expire_time')
                n_exp = n_exp if n_exp is not None else 0
                if m_exp > n_exp:
                    rows[i], rows[j] = rows[j], rows[i]

    def _bag_count_sort(self, rows):
        """BagClearUpUtil.goodsCountSort: count desc, same kind only."""
        for i in range(len(rows) - 1):
            for j in range(i + 1, len(rows)):
                if not self._bag_same_kind(rows[i], rows[j]):
                    continue
                if int(rows[i].get('count') or 0) < int(rows[j].get('count') or 0):
                    rows[i], rows[j] = rows[j], rows[i]

    def xunbao_goods(self):
        """Command 30005: BagServiceImpl.getXunBao -> formart maps or null.

        Slots 1001..2000 with no lock VOs (the service returns the bare
        formatted array, null when the zone is empty).
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        try:
            slots = self.get_role_bag_slots(role.get('id'), 1001, 2000) or []
        except Exception:
            slots = []
        goods = [self.bag_goods_map(role, slot) for slot in slots] or None
        return frame(amf3_encode(['30005', goods]))

    def bag_inspect(self, msg):
        """Command 30302: selGoods -> [1, formartMap] or [0, 430251].

        C> [bagRowId, targetRoleId]: inspects a row in another role's bag
        (booth preview when the row is missing, via BagOutput). The booth
        subsystem is unmigrated, so a missing row always reports GOODS_NOT;
        an unresolvable target is silent (Java's not-online branch). Only
        own roles resolve without the public-state subsystem.
        """
        args = self.safe(msg, 1, []) or []
        if len(args) < 2:
            return None
        if not isinstance(args[0], str) or not isinstance(args[1], str):
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        target = _find_role(roles, args[1])
        if target is None:
            return None
        try:
            src = self.get_role_bag_slot_by_bag_id(target.get('id'), args[0])
        except Exception:
            src = None
        if src is None:
            return frame(amf3_encode(['30302', [0, BAG_ERR_GOODS_NOT]]))
        return frame(amf3_encode(
            ['30302', [1, self.bag_goods_map(target, src)]]))

    @staticmethod
    def _bag_f32(value):
        """Java float<Product> arithmetic rounds every op to float32."""
        return struct.unpack('>f', struct.pack('>f', value))[0]

    @staticmethod
    def _bag_account_tran(money, amount):
        """MoneyType.accountTran: YB x5, BIND_YB ceil(/5), else -1."""
        if money == 'YB':
            return amount * 5
        if money == 'BIND_YB':
            return -(-amount // 5)
        return -1

    def _bag_money_first(self, role, amount, types):
        """First MoneyType covering amount (with conversion carry), or None.

        Ports the AccountServiceImpl decr/decrCheck type loop: each type is
        tried against the running amount, else accountTran converts it for
        the next type. A negative amount never succeeds, as in Java.
        """
        if amount < 0:
            return None
        try:
            balances = {money: int(role.get(col) or 0)
                        for money, col in BAG_MONEY_COLUMNS.items()}
        except (TypeError, ValueError):
            return None
        rest = amount
        for money in types:
            if balances.get(money, 0) >= rest:
                return money, rest
            rest = self._bag_account_tran(money, rest)
            if rest < 0:
                return None
        return None

    def _bag_money_decr(self, rid, money, amount):
        """Deduct amount of one MoneyType's column (decrMoney single-type)."""
        column = BAG_MONEY_COLUMNS[money]
        try:
            roles = self.get_roles(self.authed_user or '', self.server_id or '')
            role = roles[0] if roles else None
            balance = int((role or {}).get(column) or 0)
        except (TypeError, ValueError):
            return False
        self.save_role_state(rid, **{column: balance - amount})
        return True

    def _bag_state_or_init(self, rid):
        """Bag state row, materializing createBagState init defaults.

        Java always has the row (role-creation event); fresh local roles do
        not, so the init counts (live-proven 34/30) are written first. None
        without config (kaige supplies the init counts).
        """
        try:
            state = self.get_role_bag_state(rid) or None
        except Exception:
            state = None
        if state:
            return dict(state)
        if self.config is None:
            return None
        now = int(time.time() * 1000)
        init = {'bag_capacity': self.config.kaige_init_slot_num('B'),
                'bag_slot_time': 0, 'bag_update_slot_time': now,
                'storage_capacity': self.config.kaige_init_slot_num('C'),
                'storage_slot_time': 0, 'storage_update_slot_time': now}
        self.save_role_bag_state(rid, **init)
        return init

    @staticmethod
    def _bag_grown_ms(update_ms):
        """getBagGrowUpTime without online time (Java's null branch)."""
        try:
            return max(int(time.time() * 1000) - int(update_ms or 0), 0)
        except (TypeError, ValueError):
            return 0

    def _bag_activation_params(self, capacity, count, stype, grow_ms):
        """getActivationSlotParam -> [tongqian, yb, openMs, addExp, addAttr].

        The first slot is prorated by grown time (float32 ratio, minimum
        charge 1, free once fully grown); later slots pay full costNum.
        addAttr is computed but unused downstream, as in Java. None when a
        slot has no kaige row (Java throws instead).
        """
        tongqian, yb, open_ms, add_exp, add_attr = 0, 0, 0, 0, 0
        for i in range(1, count + 1):
            cfg = self.config.kaige_slot(stype, capacity + i)
            if cfg is None:
                return None
            if i == 1:
                grow_sec = grow_ms // 1000
                if cfg['open_time'] <= 0:
                    discount = None if grow_sec > 0 else 1
                else:
                    ratio = self._bag_f32(grow_sec / cfg['open_time'])
                    if ratio >= 1:
                        discount = None
                    else:
                        cost = self._bag_f32(
                            self._bag_f32(1.0 - ratio) * cfg['cost_num'])
                        discount = max(1, int(cost + 0.5))
                if discount is not None:
                    if cfg['money'] == 'YXB':
                        tongqian = discount
                    else:
                        yb = discount
            elif cfg['money'] == 'YXB':
                tongqian += cfg['cost_num']
            else:
                yb += cfg['cost_num']
            open_ms += cfg['open_time']
            add_exp += cfg['add_exp']
            if cfg['add_attr_value'] != 0:
                add_attr = int(self._bag_f32(add_attr + cfg['add_attr_value']))
        return tongqian, yb, open_ms, add_exp, add_attr

    def _bag_activate_reply(self, kind, capacity, max_slot):
        """[1, next lock VO or null] after an unlock (both call sites)."""
        nxt = capacity + 1
        if nxt > max_slot:
            return [1, None]
        rid = (self.get_roles(self.authed_user or '', self.server_id or '')
               or [{}])[0].get('id')
        try:
            state = self.get_role_bag_state(rid) or {}
        except Exception:
            state = {}
        return [1, self.bag_lock_vo(state, kind, max_slot)]

    def bag_activate(self, kind, msg):
        """Commands 30201/30202: activationSlot/activationSlotStorage.

        C> slot count (an Integer; anything else is silent). Over max
        answers [0, 430207]; short tongqian [0, 430208], short lingshi /
        bind [0, 430209] (no YXB-cost slot exists in the config, so 430208
        is ported but unreachable). Each deduct pushes a 32010 money frame,
        slot exp pushes 12001 (same no-level-curve approximation as kill
        exp), and the unlock reply [1, nextLockVoOrNull] comes last, after
        Java's in-service pushes. The BagOpenChangeEvent has no bus here.
        """
        count = self.safe(msg, 1)
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            return None
        if self.config is None:
            return None
        stype = 'B' if kind == 'bag' else 'C'
        cap_key = 'bag_capacity' if kind == 'bag' else 'storage_capacity'
        cmd = '30201' if kind == 'bag' else '30202'
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        rid = role.get('id')
        state = self._bag_state_or_init(rid)
        if state is None:
            return None
        max_slot = self.config.kaige_max_slot_num(stype)
        try:
            capacity = int(state.get(cap_key) or 0)
        except (TypeError, ValueError):
            capacity = 0
        if capacity + count > max_slot:
            return frame(amf3_encode([cmd, [0, BAG_ERR_EXCEED_MAX]]))
        slot_key = 'bag_slot_time' if kind == 'bag' else 'storage_slot_time'
        update_key = ('bag_update_slot_time' if kind == 'bag'
                      else 'storage_update_slot_time')
        try:
            slot_time = int(state.get(slot_key) or 0)
        except (TypeError, ValueError):
            slot_time = 0
        grow = self._bag_grown_ms(state.get(update_key)) + slot_time
        params = self._bag_activation_params(capacity, count, stype, grow)
        if params is None:
            log.info('conn %d: %s beyond kaige rows (ignored)',
                     self.conn_id, cmd)
            return None
        tongqian, yb, _open, add_exp, _attr = params
        if tongqian > 0 and self._bag_money_first(
                role, tongqian, ['YXB']) is None:
            return frame(amf3_encode([cmd, [0, BAG_ERR_TONGQIAN]]))
        if yb > 0 and self._bag_money_first(
                role, yb, ['BIND_YB', 'YB']) is None:
            return frame(amf3_encode([cmd, [0, BAG_ERR_LINGSHI_BIND]]))
        frames = []
        if yb > 0:
            money, rest = self._bag_money_first(role, yb, ['BIND_YB', 'YB'])
            self._bag_money_decr(rid, money, rest)
            frames.append(self.money_info())
        if tongqian > 0:
            self._bag_money_decr(rid, 'YXB', tongqian)
            frames.append(self.money_info())
        now = int(time.time() * 1000)
        self.save_role_bag_state(rid, **{cap_key: capacity + count,
                                         slot_key: 0, update_key: now})
        log.info('conn %d: %s unlock (open-change event skipped)',
                 self.conn_id, cmd)
        if add_exp > 0:
            _total, _level, _gained, exp_frames = self._role_gain_exp(
                role, rid, add_exp)
            frames.extend(exp_frames)
        frames.append(frame(amf3_encode(
            [cmd, self._bag_activate_reply(kind, capacity + count,
                                           max_slot)])))
        return tuple(frames)

    def bag_growup(self, kind):
        """Commands 30203/30204: bagSlotGrowUp/storageSlotChengZhang.

        No request args. Past max answers [0, 0, -1]; still growing answers
        [-1, nowMs]; a grown slot unlocks free (state reset, slot exp via
        12001 as in activation) and replies [1, nextLockVoOrNull].
        """
        if self.config is None:
            return None
        stype = 'B' if kind == 'bag' else 'C'
        cap_key = 'bag_capacity' if kind == 'bag' else 'storage_capacity'
        slot_key = 'bag_slot_time' if kind == 'bag' else 'storage_slot_time'
        update_key = ('bag_update_slot_time' if kind == 'bag'
                      else 'storage_update_slot_time')
        cmd = '30203' if kind == 'bag' else '30204'
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        rid = role.get('id')
        state = self._bag_state_or_init(rid)
        if state is None:
            return None
        max_slot = self.config.kaige_max_slot_num(stype)
        try:
            capacity = int(state.get(cap_key) or 0)
            slot_time = int(state.get(slot_key) or 0)
        except (TypeError, ValueError):
            capacity, slot_time = 0, 0
        if capacity + 1 > max_slot:
            return frame(amf3_encode([cmd, [0, 0, -1]]))
        cfg = self.config.kaige_slot(stype, capacity + 1)
        if cfg is None:
            log.info('conn %d: %s beyond kaige rows (ignored)',
                     self.conn_id, cmd)
            return None
        now = int(time.time() * 1000)
        if self._bag_grown_ms(state.get(update_key)) + slot_time < cfg['open_time']:
            return frame(amf3_encode([cmd, [-1, now]]))
        self.save_role_bag_state(rid, **{cap_key: capacity + 1,
                                         slot_key: 0, update_key: now})
        log.info('conn %d: %s free unlock (open-change event skipped)',
                 self.conn_id, cmd)
        frames = []
        if cfg['add_exp'] > 0:
            _total, _level, _gained, exp_frames = self._role_gain_exp(
                role, rid, cfg['add_exp'])
            frames.extend(exp_frames)
        frames.append(frame(amf3_encode(
            [cmd, self._bag_activate_reply(kind, capacity + 1, max_slot)])))
        return tuple(frames)

    def main_task(self):
        """Command 50000: getRunTaskMainInfo -> [taskId, recevieMs, cond, state].

        Missing rows init the first quest (recevie stored as state, like
        initFirstTaskMain); state 2 previews the next quest. Done quests only
        report here; paying goes through 50005 (getRunTaskMainInfo never pays).
        """
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        try:
            row = self.get_task_main(rid)
        except Exception:
            row = None
        frames = []
        if row is None:
            level = self._task_role_level(role)
            row, cfg = self._task_init_first(role, rid, level)
            if row is None:
                return None
            pushed = self._task_50004(row, cfg, row['state'], rid)
            if pushed is not None:
                frames.append(pushed)
        else:
            row = dict(row)
        cfg = self.config.task_main(row.get('task_id'))
        if cfg is None:
            log.info('conn %d: unknown quest %r (ignored)',
                     self.conn_id, row.get('task_id'))
            return None
        try:
            state = int(row.get('state') or 0)
        except (TypeError, ValueError):
            state = 0
        if state == 2:
            nxt = cfg['next_task_id']
            if not nxt or nxt == '0':
                return frame(amf3_encode(
                    ['50000', self._task_wrapper(None, cfg, state, rid)]))
            nxt_cfg = self.config.task_main(nxt)
            if nxt_cfg is None:
                return None
            try:
                level = int(role.get('level') or 0)
            except (TypeError, ValueError):
                level = 0
            preview = 3 if nxt_cfg['recevie_level'] <= level else 4
            return frame(amf3_encode(
                ['50000', self._task_wrapper(None, nxt_cfg, preview, rid)]))
        reply = self._task_wrapper(row, cfg, state, rid)
        if reply is None:
            return None
        frames.insert(0, frame(amf3_encode(['50000', reply])))
        if len(frames) == 1:
            return frames[0]
        return tuple(frames)

    def _task_wrapper(self, row, cfg, state, rid):
        """getTaskMainWrapper: [taskId, recevieMsOrNull, condData, state]."""
        if row is None:
            return [cfg['id'], None, None, state]
        try:
            recevie = float(row.get('recevie_time') or 0)
        except (TypeError, ValueError):
            recevie = 0.0
        cond = self._task_condition(row, cfg, rid)
        if cond is None:
            return None
        return [row.get('task_id'), recevie, cond, state]

    def _task_condition(self, row, cfg, rid):
        """[itemPartOrNull, monsterArrayOrNull]; last map entry wins like Java."""
        items = cfg.get('complete_items')
        if items:
            goods_id = next(reversed(items))
            item_part = [goods_id, items[goods_id],
                         self._task_goods_count(rid, goods_id)]
        else:
            item_part = None
        monsters = cfg.get('complete_monsters')
        if not monsters:
            return [item_part, None]
        try:
            state = int(row.get('state') or 0)
        except (TypeError, ValueError):
            state = 0
        kills = self._task_kills(row.get('condition'))
        if kills is None:
            return None
        part = None
        for monster_id, vo in monsters.items():
            if state in (1, 2):
                done = vo['count']
            else:
                done = kills.get(monster_id, 0)
            part = [monster_id, vo['count'], done, vo['auto_attack'],
                    vo['show_name']]
        return [item_part, part]

    @staticmethod
    def _task_kills(condition):
        """TaskDataUtil.getKillMonster: 'mid;n,...' -> {mid: n}; None when corrupt."""
        if not condition:
            return {}
        kills = {}
        try:
            for segment in str(condition).split(','):
                monster_id, _, count = segment.partition(';')
                kills[monster_id] = int(count)
        except (TypeError, ValueError):
            return None
        return kills

    def _task_goods_count(self, rid, goods_id):
        """BagExportService getGoodsCount: total count across all slots."""
        try:
            slots = self.get_role_bag_slots(rid, -1000000, 1000000) or []
        except Exception:
            return 0
        total = 0
        for slot in slots:
            if str(slot.get('goods_id')) != str(goods_id):
                continue
            try:
                total += int(slot.get('count') or 0)
            except (TypeError, ValueError):
                continue
        return total

    def _task_role(self):
        """First role of the authed account plus its local id."""
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None, None
        return role, role.get('id')

    @staticmethod
    def _task_role_level(role):
        """Role level as int, tolerant of bad cells."""
        try:
            return int((role or {}).get('level') or 0)
        except (TypeError, ValueError):
            return 0

    def _task_init_first(self, role, rid, level):
        """initFirstTaskMain: create the first quest, queue nothing.

        Only an empty task list creates (Java's cacheLoadAll gate); state
        is the recevie state with nonzero bumped to 1, persisted twice
        like the DAO insert+update. Returns (row, cfg) or (None, None).
        """
        first = self.config.task_main_first_id()
        cfg = self.config.task_main(first) if first is not None else None
        if cfg is None:
            return None, None
        now = int(time.time() * 1000)
        row = {'task_uid': f'task{uuid.uuid4().hex[:16]}',
               'task_id': cfg['id'], 'state': 0, 'condition': '',
               'recevie_time': now, 'create_time': now}
        recv = self._task_recevie_state(cfg, row, rid, level)
        row['state'] = 1 if recv != 0 else 0
        self.save_task_main(rid, **row)
        return row, cfg

    def _task_50004(self, row, cfg, state, rid):
        """One 50004 wrapper frame, or None when the condition is corrupt."""
        wrapper = self._task_wrapper(row, cfg, state, rid)
        if wrapper is None:
            return None
        return frame(amf3_encode(['50004', wrapper]))

    def _task_is_finished(self, row, cfg, rid):
        """taskMainIsFinished: kills cover each monster, bag covers items."""
        monsters = cfg.get('complete_monsters')
        if monsters:
            kills = self._task_kills((row or {}).get('condition'))
            if kills is None:
                return False
            for monster_id, vo in monsters.items():
                try:
                    need = int(vo.get('count') or 0)
                except (TypeError, ValueError):
                    need = 0
                if need <= 0:
                    continue
                if kills.get(monster_id, 0) < need:
                    return False
        items = cfg.get('complete_items')
        if items:
            for goods_id, need in items.items():
                try:
                    need = int(need or 0)
                except (TypeError, ValueError):
                    need = 0
                if need > 0 and self._task_goods_count(rid, goods_id) < need:
                    return False
        return True

    def _task_recevie_state(self, cfg, row, rid, level):
        """getTaskRecevieState: 4 past the level gate, 1 when done, else 0."""
        try:
            gate = int(cfg.get('recevie_level') or 0)
        except (TypeError, ValueError):
            gate = 0
        if gate > level:
            return 4
        if self._task_is_finished(row, cfg, rid):
            return 1
        return 0

    def _task_bag_has(self, rid, items):
        """BagExportService.checkDecrGoods: every need covered by the bag."""
        for goods_id, need in (items or {}).items():
            try:
                need = int(need or 0)
            except (TypeError, ValueError):
                need = 0
            if need > 0 and self._task_goods_count(rid, goods_id) < need:
                return False
        return True

    def _task_consume(self, rid, cfg):
        """taskConsumeGoods: decr the complete items (bag order: slot asc)."""
        items = cfg.get('complete_items')
        if not items:
            return
        try:
            slots = self.get_role_bag_slots(rid, -1000000, 1000000) or []
        except Exception:
            return
        for goods_id, need in items.items():
            try:
                left = int(need or 0)
            except (TypeError, ValueError):
                left = 0
            if left <= 0:
                continue
            for slot in sorted(slots, key=lambda s: s.get('slot_num') or 0):
                if left <= 0:
                    break
                if str(slot.get('goods_id')) != str(goods_id):
                    continue
                try:
                    have = int(slot.get('count') or 0)
                except (TypeError, ValueError):
                    have = 0
                take = min(have, left)
                if take <= 0:
                    continue
                left -= take
                rest = have - take
                try:
                    if rest > 0:
                        self.update_role_bag_slot(rid, slot.get('slot_num'),
                                                count=rest)
                    else:
                        self.delete_role_bag_slot(rid, slot.get('slot_num'))
                except Exception:
                    break
                slot['count'] = rest

    def _task_grant(self, rid, items):
        """Bag half of putInBagOrEmail: stack, then empty slots; overflow drops (no mail yet)."""
        if not items:
            return
        try:
            slots = self.get_role_bag_slots(rid, -1000000, 1000000) or []
        except Exception:
            slots = []
        by_slot = {s.get('slot_num'): dict(s) for s in slots}
        try:
            state = self._bag_state_or_init(rid) or {}
            capacity = int(state.get('bag_capacity') or 0)
        except (TypeError, ValueError):
            capacity = 0
        for item in items:
            left = item.get('count') or 0
            if left <= 0:
                continue
            try:
                stack = int(self.config.goods_max_stack(item['goods_id'])
                            or 0) if self.config is not None else 0
            except (TypeError, ValueError):
                stack = 0
            if stack <= 0:
                stack = 1
            for slot in sorted(by_slot.values(),
                               key=lambda s: s.get('slot_num') or 0):
                if left <= 0:
                    break
                if not self._bag_same_kind(slot, item):
                    continue
                try:
                    have = int(slot.get('count') or 0)
                except (TypeError, ValueError):
                    have = 0
                room = stack - have
                if room <= 0:
                    continue
                take = min(room, left)
                left -= take
                new_count = have + take
                try:
                    self.update_role_bag_slot(rid, slot.get('slot_num'),
                                            count=new_count)
                except Exception:
                    left += take
                    break
                slot['count'] = new_count
            num = 1
            while left > 0 and num <= capacity:
                if num not in by_slot:
                    take = min(stack, left)
                    try:
                        self.insert_role_bag_slot(
                            rid, {'slot_num': num,
                                  'goods_id': item['goods_id'],
                                  'count': take,
                                  'bind': item.get('bind') or 0,
                                  'expire_time': item.get('expire') or None,
                                  'rare_level': 0, 'item_level': 0,
                                  'attributes': None})
                    except Exception:
                        break
                    by_slot[num] = {'slot_num': num,
                                    'goods_id': item['goods_id'],
                                    'count': take,
                                    'bind': item.get('bind') or 0}
                    left -= take
                num += 1
            if left > 0:
                log.warning('conn %d: quest reward %r x%d overflows '
                            '(no mail yet, dropped)',
                            self.conn_id, item.get('goods_id'), left)

    def _task_reward(self, role, rid, cfg):
        """reward(): currencies, exp, zhenqi, goods, shenjiang, event.

        Returns the level-up extra frames (12001 rides no extra push on
        this path today, so only the 12000/12004/12002/learn/unlock tail
        is returned for the submit chain to flush).
        """
        extra = []
        try:
            exp = int(cfg.get('exp') or 0)
        except (TypeError, ValueError):
            exp = 0
        if exp > 0:
            try:
                _total, _level, _gained, exp_frames = \
                    self._role_gain_exp(role, rid, exp)
                extra.extend(exp_frames[1:])
            except Exception:
                pass
        for key, column in (('bound_ob', 'bind_lingshi'), ('jb', 'tongqian'),
                            ('zhiqi', 'zhenqi')):
            try:
                amount = int(cfg.get(key) or 0)
            except (TypeError, ValueError):
                amount = 0
            if amount <= 0:
                continue
            try:
                total = int(role.get(column) or 0) + amount
            except (TypeError, ValueError):
                total = amount
            try:
                self.save_role_state(rid, **{column: total})
            except Exception:
                pass
        job = str(role.get('job') or '')
        grant = []
        for item in cfg.get('reward_grant') or []:
            category = self.config.goods_category(item['goods_id']) \
                if self.config is not None else None
            if category is None:
                continue
            if category in ('20', ''):
                gate = self.config.goods_job(item['goods_id']) \
                    if self.config is not None else None
                if gate != '0' and gate != job:
                    continue
            grant.append(item)
        self._task_grant(rid, grant)
        if cfg.get('shenjiang'):
            # activateShenjiang needs the shenjiang module (read-only here).
            log.info('conn %d: quest %r shenjiang reward %r (not ported)',
                     self.conn_id, cfg.get('id'), cfg.get('shenjiang'))
        # TaskMainFinishEvent has no bus here; the state changes above are
        # the portable half.
        return extra

    def _task_reward_result(self, cfg):
        """CreateTaskOutputWrapper.getRewardResultOutPut for the 50005 push."""
        items = cfg.get('reward_items')
        pairs = [[i['goods_id'], i['count']] for i in items] \
            if items else []
        return [1, [cfg['id'], pairs, cfg.get('exp') or 0,
                    cfg.get('jb') or 0, cfg.get('bound_ob') or 0,
                    cfg.get('prestige') or 0, cfg.get('zhiqi') or 0]]

    def chapters_info(self):
        """Command 50001: getChapterList 3-arg overload, always null.

        The chapters panel is client-config driven; Java returns null
        unconditionally, so this takes no role or table input.
        """
        return frame(amf3_encode(['50001', None]))

    def _task_notify_chapter(self, row, rid):
        """notifyChapterComplete: 50012 when a subchapter's last quest pays."""
        if row is None or self.config is None:
            return None
        try:
            paid = int(row.get('state') or 0) == 2
        except (TypeError, ValueError):
            paid = False
        if not paid:
            return None
        cfg = self.config.task_main(row.get('task_id'))
        if cfg is None:
            return None
        sub = self.config.task_subchapter(cfg.get('chapter_sub_id'))
        if sub is None:
            return None
        if sub.get('last_task_id') != row.get('task_id'):
            return None
        # TaskChapterFinishEvent has no bus here; the push is the wire half.
        return frame(amf3_encode(['50012', sub['id']]))

    def _task_pay(self, rid, task_id, cfg):
        """payMainTask -> (ok, pushes, next); failures stay silent like Java's unflushed queues."""
        try:
            row = self.get_task_main(rid)
        except Exception:
            row = None
        if row is None or task_id != row.get('task_id'):
            return False, [], None
        row = dict(row)
        try:
            state = int(row.get('state') or 0)
        except (TypeError, ValueError):
            state = 0
        if cfg.get('complete_items') and state != 1:
            if not self._task_bag_has(rid, cfg['complete_items']):
                return False, [], None
            row['state'] = 1
            state = 1
        if state != 1:
            return False, [], None
        nxt = cfg.get('next_task_id') or ''
        self._task_consume(rid, cfg)
        row['state'] = 2
        self.save_task_main(rid, **row)
        pushes = [frame(amf3_encode(['50005', self._task_reward_result(cfg)]))]
        chapter = self._task_notify_chapter(row, rid)
        if chapter is not None:
            pushes.append(chapter)
        return True, pushes, nxt

    def _task_receive(self, role, rid, task_id):
        """recevieMainTask -> (ok, pushes, tailId); gated quests queue a 50000 refresh, NPC-less accepts resubmit inline."""
        pushes = []
        if not task_id or self.config is None:
            return False, pushes, None
        cfg = self.config.task_main(task_id)
        if cfg is None:
            return False, pushes, None
        try:
            row = self.get_task_main(rid)
        except Exception:
            row = None
        if row is None:
            return False, pushes, None
        row = dict(row)
        if row.get('task_id') == cfg['id']:
            return False, pushes, None
        level = self._task_role_level(role)
        if cfg.get('recevie_level', 0) > level:
            info = self._task_wrapper(None, cfg, 4, rid)
            if info is not None:
                pushes.append(frame(amf3_encode(['50000', info])))
            return False, pushes, None
        try:
            cur = self.config.task_main(row.get('task_id'))
            line = cur.get('chapter_sub_id') if cur else None
        except Exception:
            line, cur = None, None
        recv = self._task_recevie_state(cfg, row, rid, level)
        row['task_id'] = cfg['id']
        row['condition'] = ''
        row['recevie_time'] = int(time.time() * 1000)
        row['state'] = recv
        self.save_task_main(rid, **row)
        pushed = self._task_50004(row, cfg, recv, rid)
        if pushed is not None:
            pushes.append(pushed)
        if line != cfg.get('chapter_sub_id'):
            sub = self.subchapter_info(cfg['chapter_sub_id'])
            if sub is not None:
                pushes.append(sub)
        nxt = cfg['id'] if not cfg.get('complete_npc') else None
        return True, pushes, nxt

    def _task_submit_chain(self, role, rid, cfg):
        """Pay/reward/receive cascade with NPC-less resubmits inline (Java's inner bus laid flat, capped at 64)."""
        frames = []
        task_id, current = cfg['id'], cfg
        depth = 0
        while depth < 64:
            ok, pushes, nxt = self._task_pay(rid, task_id, current)
            if not ok:
                break
            frames.extend(pushes)
            frames.extend(self._task_reward(role, rid, current) or [])
            if not nxt:
                break
            ok, received, tail = self._task_receive(role, rid, nxt)
            frames.extend(received)
            if not ok or not tail:
                break
            task_id = tail
            current = self.config.task_main(task_id)
            if current is None:
                break
            depth += 1
        return frames

    def _task_chapter_state(self, sub_id, row):
        """getChapterState: 2 done, 0 running arc, 4 locked, by sequence."""
        if row is None or self.config is None:
            return 4
        cur = self.config.task_main(row.get('task_id'))
        sub = self.config.task_subchapter(sub_id)
        if cur is None or sub is None:
            return 4
        line = self.config.task_subchapter(cur.get('chapter_sub_id'))
        if line is None:
            return 4
        diff = sub['sequence'] - line['sequence']
        if diff == 0:
            try:
                paid = int(row.get('state') or 0) == 2
            except (TypeError, ValueError):
                paid = False
            if row.get('task_id') == sub.get('last_task_id') and paid:
                return 2
            return 0
        return 2 if diff < 0 else 4

    def _task_state(self, row, task_id):
        """getTaskState: running quest reads live, others by sequence."""
        if row is None or self.config is None:
            return 3
        if task_id == row.get('task_id'):
            try:
                return int(row.get('state') or 0)
            except (TypeError, ValueError):
                return 0
        cfg = self.config.task_main(task_id)
        cur = self.config.task_main(row.get('task_id'))
        if cfg is None or cur is None:
            return 3
        if cfg['sequence'] < cur['sequence']:
            return 2
        try:
            paid = int(row.get('state') or 0) == 2
        except (TypeError, ValueError):
            paid = False
        if task_id == cur.get('next_task_id') and paid:
            return 4
        return 3

    def subchapter_info(self, msg):
        """Command 50002: [subchapter detail, per-quest simple VOs]."""
        if self.config is None:
            return None
        sub_id = msg if isinstance(msg, str) else None
        if sub_id is None and isinstance(msg, (list, tuple)) and msg:
            sub_id = msg[0]
        sub = self.config.task_subchapter(sub_id) if sub_id else None
        if sub is None:
            return frame(amf3_encode(['50002', None]))
        role, rid = self._task_role()
        try:
            row = self.get_task_main(rid) if rid is not None else None
        except Exception:
            row = None
        row = dict(row) if row else None
        state = self._task_chapter_state(sub_id, row)
        detail = [sub['id'], sub['name'],
                  self.config.task_attr_index_convert(sub.get('reward')),
                  state, sub['ico'], sub['shuoming'], len(sub['task_ids'])]
        vos = []
        for task_id in sub['task_ids']:
            cfg = self.config.task_main(task_id)
            if cfg is None:
                continue
            each = state if state != 0 else self._task_state(row, task_id)
            vos.append([cfg['id'], cfg['name'], each])
        return frame(amf3_encode(['50002', [detail, vos]]))

    def task_select_info(self, msg):
        """Command 50003: getSelectTaskInfo wrapper for one quest."""
        if self.config is None:
            return None
        task_id = msg if isinstance(msg, str) else None
        if task_id is None and isinstance(msg, (list, tuple)) and msg:
            task_id = msg[0]
        cfg = self.config.task_main(task_id) if task_id else None
        if cfg is None:
            return frame(amf3_encode(['50003', None]))
        _role, rid = self._task_role()
        try:
            row = self.get_task_main(rid) if rid is not None else None
        except Exception:
            row = None
        row = dict(row) if row else None
        state = self._task_state(row, task_id)
        return frame(amf3_encode(
            ['50003', self._task_wrapper(row, cfg, state, rid)]))

    def submit_task(self, msg):
        """Command 50005 completeMainTask: silent failures, pay pushes then receive cascade on success."""
        if self.config is None:
            return None
        task_id = msg[0] if isinstance(msg, (list, tuple)) and msg else msg
        if not task_id:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        cfg = self.config.task_main(task_id)
        if cfg is None:
            return None
        try:
            row = self.get_task_main(rid)
        except Exception:
            row = None
        if row is None:
            return None
        frames = self._task_submit_chain(role, rid, cfg)
        if not frames:
            return None
        return tuple(frames) if len(frames) > 1 else frames[0]

    def chapter_tips(self, msg):
        """Command 50008: [type, subId, reward-or-null] chapter tips."""
        if self.config is None:
            return None
        kind, sub_id = 0, ''
        if isinstance(msg, (list, tuple)) and len(msg) >= 2:
            kind, sub_id = msg[0], msg[1]
        try:
            kind = int(kind)
        except (TypeError, ValueError):
            kind = 0
        reward = None
        if kind == 2:
            sub = self.config.task_subchapter(sub_id)
            reward = sub.get('reward') if sub else None
        converted = self.config.task_attr_index_convert(reward)
        return frame(amf3_encode(['50008', [kind, sub_id, converted]]))

    def _role_gain_exp(self, role, rid, amount):
        """RoleExportService.incrExp + calUpgradeAndExp + per-level fan-out.

        Persists level/exp/max_hp/max_mp and refreshes the role dict in
        place; returns (total, level, gained, frames) where frames holds
        the 12001 notice plus, per level gained, the 12000/12004/12002
        refreshes, skill auto-learns and quest level-unlocks. The 12001
        frame always leads, like the bus push after every incrExp.
        """
        try:
            old_level = int(role.get('level') or 0)
        except (TypeError, ValueError):
            old_level = 0
        try:
            old_exp = int(role.get('exp') or 0)
        except (TypeError, ValueError):
            old_exp = 0
        try:
            amount = int(amount or 0)
        except (TypeError, ValueError):
            amount = 0
        if self.config is not None:
            need = self.config.role_need_exp
            cap = self.config.role_max_level()
        else:
            need, cap = (lambda lv: None), 0
        level, total, gained = combat_lib.apply_exp_gain(
            old_level, old_exp, amount, need, cap)
        fields = {'exp': total}
        if gained:
            row = self.config.role_attribute_row(level) \
                if self.config is not None else None
            if row is not None:
                fields['level'] = level
                try:
                    fields['max_hp'] = int(row.get('hitpoints') or 0)
                except (TypeError, ValueError):
                    pass
                try:
                    fields['max_mp'] = int(row.get('mana') or 0)
                except (TypeError, ValueError):
                    pass
        self.save_role_state(rid, **fields)
        try:
            role.update(exp=total)
            if gained and 'level' in fields:
                role.update(level=level, max_hp=fields.get('max_hp'),
                            max_mp=fields.get('max_mp'))
        except Exception:
            pass
        frames = [frame(amf3_encode(
            combat_lib.exp_notice(total, fields.get('level', old_level))))]
        if gained:
            frames.extend(self._role_level_frames(role, rid, old_level))
        return total, fields.get('level', old_level), gained, frames

    def _role_level_frames(self, role, rid, old_level=0):
        """Per-gain fan-out: 12004/12005/12000, 12002, learns, unlock.

        Mirrors roleUpgrade + outputAttributeChange routing: 12004 and
        12002 ride the 3x3 surround while 12000/12005 go to self only,
        and 12005 fires only when the shanbi value actually changed.
        """
        frames = []
        try:
            level = int(role.get('level') or 0)
        except (TypeError, ValueError):
            level = 0
        try:
            old_level = int(old_level or 0)
        except (TypeError, ValueError):
            old_level = level
        try:
            attrs = self.role_attribute_map(role)
        except Exception:
            attrs = None
        try:
            wire = _wire_id(role)
        except Exception:
            wire = None
        # Vitals to the surround (own copy returned; Java's isHpMpChanged
        # is always true here because maxHp moved with the level row).
        try:
            hp = role.get('hp')
            max_hp = role.get('max_hp')
            mp = role.get('mp')
            max_mp = role.get('max_mp')
            if wire is not None and max_hp is not None \
                    and max_mp is not None:
                frames.extend(self._dazuo_broadcast(
                    rid, 12004, [wire, hp, max_hp, mp, max_mp]))
        except Exception:
            pass
        # Shanbi to self, only on change (dunshandian is flat across the
        # shipped rows, so this rarely fires, like Java's conditional).
        try:
            new_val = int(float((attrs or {}).get('10') or 0))
            old_val = self._role_shanbi_at(role, old_level)
            if old_val is not None and old_val != new_val:
                frames.append(frame(amf3_encode(['12005', [new_val]])))
        except Exception:
            pass
        if attrs is not None:
            frames.append(frame(amf3_encode(['12000', Obj(attrs)])))
        # Level notice to the surround, like roleUpgrade's 12002.
        try:
            if wire is not None:
                frames.extend(self._dazuo_broadcast(
                    rid, 12002, [wire, role.get('name'), level]))
        except Exception:
            pass
        # One RoleLevelUpgradeEvent per gained level in Java, so each
        # intermediate level's learnskill tokens get their turn.
        for lv in range(old_level + 1, level + 1):
            frames.extend(self._skill_level_learn(rid, lv))
        frames.extend(self._task_on_level(role, rid))
        if level != old_level:
            try:
                frames.extend(self._friend_on_level(rid, level) or [])
            except Exception:
                pass
        return frames

    def _role_shanbi_at(self, role, level):
        """MaxShanbiVal for a role at a past level, or None when unknown."""
        if self.config is None:
            return None
        row = self.config.role_attribute_row(level)
        if row is None:
            return None
        try:
            old_role = dict(role, level=int(level or 0))
        except (TypeError, ValueError):
            old_role = role
        try:
            bags = self.role_bags(old_role)
        except Exception:
            return None
        try:
            effect = self.role_effect_slots(role)
        except Exception:
            effect = {}
        try:
            return int(float(entry_attribute_map(
                row, None, bags=bags, effect=effect).get('10') or 0))
        except (TypeError, ValueError):
            return None

    def _skill_level_learn(self, rid, level):
        """roleLevelUpgradeSkill: learnskill tokens at the new level.

        Each unknown category saves level 1 and pushes the 42004 study
        notice, like the prop-study success shape (AddSkillEvent has no
        ported subscribers and is skipped like every other publish).
        """
        if self.config is None:
            return []
        row = self.config.role_attribute_row(level)
        tokens = str((row or {}).get('learnskill') or '')
        try:
            owned = {str(s.get('category'))
                     for s in (self.get_role_skills(rid) or [])}
        except Exception:
            owned = set()
        frames = []
        for token in tokens.split(';'):
            token = token.strip()
            if not token or token in owned:
                continue
            info = self.config.skill_info(token, 1)
            if info is None:
                log.info('conn %d: level %d skill %r has no row (skipped)',
                         self.conn_id, level, token)
                continue
            try:
                self.save_role_skill(rid, token, 1)
            except Exception:
                continue
            owned.add(token)
            frames.append(frame(amf3_encode(
                [str(CMD_STUDY_SKILL), [info.get('skilltype'), 1]])))
        return frames

    def _task_on_level(self, role, rid):
        """ShengJiEventHandler.handle: paid quest with a satisfied next.

        shengJiRecevieMainTask: when the running quest is paid (state 2)
        and its next quest exists with recevie_level at or below the new
        level, receive it (the inner-bus cascade, NPC-less tails paying
        inline). Returns the queued push frames.
        """
        if self.config is None or role is None:
            return []
        try:
            row = self.get_task_main(rid)
        except Exception:
            return []
        if row is None:
            return []
        row = dict(row)
        try:
            paid = int(row.get('state') or 0) == 2
        except (TypeError, ValueError):
            paid = False
        if not paid:
            return []
        cfg = self.config.task_main(row.get('task_id'))
        if cfg is None:
            return []
        try:
            level = int(role.get('level') or 0)
        except (TypeError, ValueError):
            return []
        nxt = cfg.get('next_task_id') or ''
        nxt_cfg = self.config.task_main(nxt) if nxt else None
        if nxt_cfg is None:
            return []
        try:
            gate = int(nxt_cfg.get('recevie_level') or 0)
        except (TypeError, ValueError):
            gate = 0
        if gate > level:
            return []
        return self._task_receive_next(role, rid, row, cfg)

    def _task_receive_next(self, role, rid, row, cfg):
        """Paid tail shared by dataCheck and shengJi: receive + cascade."""
        nxt = cfg.get('next_task_id') or ''
        ok, pushes, tail = self._task_receive(role, rid, nxt)
        frames = list(pushes)
        if ok and tail:
            tail_cfg = self.config.task_main(tail)
            if tail_cfg is not None:
                frames.extend(self._task_submit_chain(role, rid, tail_cfg))
        return frames

    def task_kill_progress(self, role, monster_id):
        """Kill hook: 50006 progress, 50007 on completion, auto-finish for pay-1 quests."""
        if self.config is None or role is None:
            return []
        rid = role.get('id')
        try:
            row = self.get_task_main(rid)
        except Exception:
            return []
        if row is None:
            return []
        row = dict(row)
        try:
            if int(row.get('state') or 0) != 0:
                return []
        except (TypeError, ValueError):
            return []
        cfg = self.config.task_main(row.get('task_id'))
        if cfg is None:
            return []
        monsters = cfg.get('complete_monsters')
        if not monsters or monster_id not in monsters:
            return []
        try:
            need = int(monsters[monster_id].get('count') or 0)
        except (TypeError, ValueError):
            need = 0
        kills = self._task_kills(row.get('condition'))
        if kills is None:
            return []
        if not row.get('condition'):
            done = 1
            kills[monster_id] = 1
        else:
            done = kills.get(monster_id, 0)
            if need > done:
                done = (kills.get(monster_id) or 0) + 1
                kills[monster_id] = done
        row['condition'] = self._task_kills_str(kills)
        frames = [frame(amf3_encode(
            ['50006', [row['task_id'], monster_id, done]]))]
        if done >= need:
            row['state'] = 1
            frames.append(frame(amf3_encode(
                ['50007', row['task_id']])))
            if cfg.get('pay_type') == '1':
                frames.extend(self._task_submit_chain(role, rid, cfg))
        self.save_task_main(rid, **row)
        return frames

    def _task_on_enter(self, rid):
        """role_login dataCheck: repair, advance paid chains, flip finished states.

        TaskRoleOnlineHandler.handle runs dataCheck: a quest whose config
        vanished resets to the first quest; a paid (state 2) quest receives
        its next quest (the inner-bus cascade, NPC-less tails paying
        inline); a running quest whose kills/bag now cover its objectives
        flips to state 1. Returns the queued push frames.
        """
        if self.config is None:
            return []
        try:
            roles = self.get_roles(self.authed_user or '',
                                   self.server_id or '')
        except Exception:
            return []
        role = _find_role(roles or [], rid)
        if role is None:
            return []
        try:
            row = self.get_task_main(rid)
        except Exception:
            return []
        if row is None:
            return []
        row = dict(row)
        cfg = self.config.task_main(row.get('task_id'))
        if cfg is None:
            first = self.config.task_main_first_id()
            cfg = self.config.task_main(first) if first else None
            if cfg is None:
                return []
            now = int(time.time() * 1000)
            row.update(task_id=cfg['id'], condition='',
                       recevie_time=now, state=0)
            try:
                self.save_task_main(rid, **row)
            except Exception:
                pass
        try:
            state = int(row.get('state') or 0)
        except (TypeError, ValueError):
            state = 0
        if state == 2:
            return self._task_receive_next(role, rid, row, cfg)
        if state == 0 and self._task_is_finished(row, cfg, rid):
            row['state'] = 1
            try:
                self.save_task_main(rid, **row)
            except Exception:
                pass
        return []

    @staticmethod
    def _same_day_ms(first_ms, second_ms):
        """DateUtils.isSameDay over two ms stamps (server-local day)."""
        try:
            first = time.localtime(int(first_ms or 0) / 1000)[:3]
            second = time.localtime(int(second_ms or 0) / 1000)[:3]
        except (TypeError, ValueError):
            return False
        return first == second

    def _taofa_vip_level(self, rid):
        """Role vip level int for the taofa/richang bonus lookups."""
        try:
            vip = self.get_role_vip(rid) or {}
        except Exception:
            return 0
        try:
            return int(vip.get('vip_level') or 0)
        except (TypeError, ValueError):
            return 0

    def _taofa_state_or_init(self, rid):
        """resetOrCheckTaofaUpdateTime: materialize then re-arm a stale day."""
        try:
            state = self.get_task_taofa_state(rid)
        except Exception:
            state = None
        now = int(time.time() * 1000)
        if state is None:
            state = {'tunshi_count': 0, 'hebing_count': 0,
                     'finish_count': 0, 'total_count': 0,
                     'create_time': now}
            try:
                self.save_task_taofa_state(rid, **state)
            except Exception:
                pass
            return dict(state)
        state = dict(state)
        if not self._same_day_ms(now, state.get('create_time')):
            state.update(tunshi_count=0, hebing_count=0, finish_count=0,
                         create_time=now)
            try:
                self.save_task_taofa_state(rid, **state)
            except Exception:
                pass
        return state

    def _taofa_max_value(self, vip_level):
        """getTaofaMaxValue: [5, 10, 10] plus the vip bonuses."""
        tunshi = self.config.vip_tunshi_times(vip_level) \
            if self.config is not None else 0
        taofa = self.config.vip_taofa_times(vip_level) \
            if self.config is not None else 0
        return [5 + tunshi, 10 + taofa, 10 + taofa]

    def taofa_list(self):
        """Command 50101: [quest infos or null, [tunshi, finish, use], max]."""
        if self.config is None:
            return None
        _role, rid = self._task_role()
        if rid is None:
            return None
        state = self._taofa_state_or_init(rid)
        try:
            rows = self.get_task_taofas(rid) or []
        except Exception:
            rows = []
        counts = [state.get('tunshi_count') or 0,
                  state.get('finish_count') or 0,
                  state.get('hebing_count') or 0]
        infos = [self._taofa_out_info(dict(row)) for row in rows] or None
        reply = [infos, counts,
                 self._taofa_max_value(self._taofa_vip_level(rid))]
        return frame(amf3_encode(['50101', reply]))

    def _taofa_out_info(self, row):
        """CreateTaskOutputWrapper.getTaofaOutPutInfo: the 18-field quest VO."""
        cfg = self.config.taofa_config(row.get('task_id'))
        if cfg is None:
            return None
        try:
            created = float(row.get('create_time') or 0)
        except (TypeError, ValueError):
            created = 0.0
        vo = cfg.get('kill_monster')
        if vo is None:
            monster = [None, None]
        else:
            try:
                master = int(row.get('master_count') or 0)
            except (TypeError, ValueError):
                master = 0
            monster = [None, [vo['monster_id'], vo['count'], master,
                              vo['auto_attack'], vo['show_name']]]
        try:
            exp_base = int(cfg.get('exp') or 0)
        except (TypeError, ValueError):
            exp_base = 0
        try:
            exp_ts = int(row.get('ts_reward_exp') or 0)
        except (TypeError, ValueError):
            exp_ts = 0
        try:
            ratio = 1.0 + exp_ts / exp_base if exp_base else \
                (float('inf') if exp_ts else float('nan'))
        except (TypeError, ValueError):
            ratio = 1.0
        call_goods = cfg.get('call_goods')
        return [row.get('id'), cfg['id'], created,
                row.get('task_state') or 0, monster,
                self._taofa_reward_part(row, cfg), 2, cfg.get('target'),
                cfg.get('monster_type') or 0,
                cfg.get('monster_name') or '',
                cfg.get('monster_level') or 0, ratio,
                cfg.get('color') or 0, bool(cfg.get('swallow')),
                float(cfg.get('merge') or 0.0), cfg.get('res') or '',
                cfg.get('desc'),
                [call_goods, 1] if call_goods else None]

    def _taofa_reward_part(self, row, cfg):
        """The 8-field reward array (config plus merged swallow rewards)."""
        def total(base, key):
            try:
                return int(cfg.get(base) or 0) + int(row.get(key) or 0)
            except (TypeError, ValueError):
                return 0
        return [total('jb', 'ts_reward_jb'), total('exp', 'ts_reward_exp'),
                total('bind_yb', 'ts_reward_bing_yb'),
                total('zhenqi', 'ts_reward_zhenqi'),
                total('prestige', 'ts_reward_prestige'),
                None, 0, self._taofa_show_pairs(cfg.get('show_items'))]

    @staticmethod
    def _taofa_show_pairs(items):
        """CreateTaskOutputWrapper.getRewardOutPut: pairs or null."""
        if not items:
            return None
        return [[item['goods_id'], item['count']] for item in items]

    def _prop_taofa(self, role, rid, row, grow):
        """TaoFaPropType.useDaoJu: xtf scrolls receive a quest (skill 3).

        consumePrior is false, so errors never burn the scroll; success
        burns it like the published UsePropEvent and replies terminal.
        """
        err, info = self._taofa_receive(role, rid, row)
        if err is not None:
            return ([frame(amf3_encode(
                [str(CMD_PROP_USE), [0, err]]))], False)
        self._prop_decr(rid, row)
        return ([frame(amf3_encode([str(CMD_TAOFA_RECEIVE), [1, info]]))],
                True)

    def _taofa_receive(self, role, rid, row):
        """recevieTaskTaofa -> (error or None, quest info or None)."""
        goods_id = str(row.get('goods_id') or '')
        if self.config is None or \
                self.config._goods_table().get(goods_id) is None:
            return TASK_ERR_TAOFA_NO_GOODS, None
        level = self._task_role_level(role)
        vip_level = self._taofa_vip_level(rid)
        state = self._taofa_state_or_init(rid)
        try:
            used = int(state.get('hebing_count') or 0)
        except (TypeError, ValueError):
            used = 0
        bonus = self.config.vip_taofa_times(vip_level)
        if used + 1 > TAOFA_MAX_USE + bonus:
            return TASK_ERR_TAOFA_USE_MAX, None
        try:
            rows = self.get_task_taofas(rid) or []
        except Exception:
            rows = []
        if len(rows) >= TAOFA_RECEIVE_MAX:
            return TASK_ERR_TAOFA_RECEIVE_MAX, None
        interval = self.config.taofa_interval(
            level, self.config.goods_rarelevel(goods_id))
        if not interval:
            return TASK_ERR_TAOFA_CONFIG, None
        # Lottery.roll(size): uniform pick like Random.nextInt.
        cfg = interval[random.randrange(len(interval))]
        try:
            self.save_task_taofa_state(
                rid, tunshi_count=state.get('tunshi_count') or 0,
                hebing_count=used + 1,
                finish_count=state.get('finish_count') or 0,
                total_count=state.get('total_count') or 0,
                create_time=int(time.time() * 1000))
        except Exception:
            pass
        now = int(time.time() * 1000)
        quest = {'id': f'task{uuid.uuid4().hex[:16]}',
                 'task_id': cfg['id'], 'master_count': 0, 'task_state': 0,
                 'ts_state': 0, 'ts_reward_jb': 0, 'ts_reward_exp': 0,
                 'ts_reward_zhenqi': 0, 'ts_reward_bing_yb': 0,
                 'ts_reward_prestige': 0, 'update_time': now,
                 'create_time': now}
        try:
            self.insert_task_taofa(rid, quest)
        except Exception:
            return TASK_ERR_TAOFA_CONFIG, None
        return None, self._taofa_out_info(quest)

    def taofa_tunshi(self, msg):
        """Command 50103: devour one quest into another, replying the survivor."""
        if self.config is None:
            return None
        keeper_guid, eaten_guid = None, None
        if isinstance(msg, (list, tuple)) and len(msg) >= 2:
            keeper_guid, eaten_guid = msg[0], msg[1]
        if not keeper_guid or not eaten_guid:
            return None
        _role, rid = self._task_role()
        if rid is None:
            return None
        try:
            keeper = self.get_task_taofa(rid, str(keeper_guid))
        except Exception:
            keeper = None
        try:
            eaten = self.get_task_taofa(rid, str(eaten_guid))
        except Exception:
            eaten = None
        if keeper is None or eaten is None:
            return frame(amf3_encode(
                ['50103', [0, TASK_ERR_TAOFA_NO_EXIST]]))
        state = self._taofa_state_or_init(rid)
        try:
            tunshi = int(state.get('tunshi_count') or 0)
        except (TypeError, ValueError):
            tunshi = 0
        bonus = self.config.vip_tunshi_times(self._taofa_vip_level(rid))
        if tunshi >= TAOFA_MAX_TUNSHI + bonus:
            return frame(amf3_encode(
                ['50103', [0, TASK_ERR_TAOFA_TUNSHI_MAX]]))
        keeper = dict(keeper)
        eaten = dict(eaten)
        cfg = self.config.taofa_config(keeper.get('task_id'))
        if cfg is None or not cfg.get('swallow'):
            return frame(amf3_encode(
                ['50103', [0, TASK_ERR_TAOFA_NO_TUNSHI]]))
        try:
            self.save_task_taofa_state(
                rid, tunshi_count=tunshi + 1,
                hebing_count=state.get('hebing_count') or 0,
                finish_count=state.get('finish_count') or 0,
                total_count=state.get('total_count') or 0,
                create_time=int(time.time() * 1000))
        except Exception:
            pass
        try:
            self.delete_task_taofa(rid, str(eaten_guid))
        except Exception:
            pass
        merge = cfg.get('merge') or 0.0
        updates = {'ts_state': 1}
        for base, key in (('jb', 'ts_reward_jb'), ('exp', 'ts_reward_exp'),
                          ('prestige', 'ts_reward_prestige'),
                          ('zhenqi', 'ts_reward_zhenqi'),
                          ('bind_yb', 'ts_reward_bing_yb')):
            try:
                have = int(eaten.get(key) or 0) + int(cfg.get(base) or 0)
            except (TypeError, ValueError):
                have = 0
            try:
                updates[key] = int(keeper.get(key) or 0) + int(have * merge)
            except (TypeError, ValueError):
                updates[key] = int(keeper.get(key) or 0)
        try:
            self.update_task_taofa(rid, str(keeper_guid), **updates)
        except Exception:
            pass
        keeper.update(updates)
        info = self._taofa_out_info(keeper)
        return frame(amf3_encode(['50103', [1, [info, str(eaten_guid)]]]))

    def taofa_kill_progress(self, role, monster_id):
        """Kill hook: 50104 progress, 50105 pay push on completion."""
        if self.config is None or role is None:
            return []
        rid = role.get('id')
        try:
            rows = self.get_task_taofas(rid) or []
        except Exception:
            return []
        matching = []
        for row in rows:
            cfg = self.config.taofa_config(row.get('task_id'))
            vo = (cfg or {}).get('kill_monster')
            if vo is not None and vo['monster_id'] == monster_id:
                matching.append((dict(row), cfg))
        if not matching:
            return []
        if len(matching) > 1:
            # TaofaTaskComparator: task ids sort descending, first wins.
            matching.sort(key=lambda pair: str(pair[0].get('task_id') or ''),
                          reverse=True)
        row, cfg = matching[0]
        try:
            need = int(cfg['kill_monster']['count'] or 0)
        except (TypeError, ValueError):
            need = 0
        try:
            done = int(row.get('master_count') or 0) + 1
        except (TypeError, ValueError):
            done = 1
        try:
            self.update_task_taofa(rid, row['id'], master_count=done)
        except Exception:
            pass
        row['master_count'] = done
        frames = [frame(amf3_encode(
            [str(CMD_TAOFA_CHANGE), [row['id'], monster_id, done]]))]
        if done >= need:
            try:
                self.update_task_taofa(rid, row['id'], master_count=need,
                                       task_state=1)
            except Exception:
                pass
            row.update(master_count=need, task_state=1)
            paid = self._taofa_pay(role, rid, row)
            if paid is not None:
                result, extra = paid
                frames.append(frame(amf3_encode(
                    [str(CMD_TAOFA_PAY), result])))
                frames.extend(extra)
        return frames

    def _taofa_pay(self, role, rid, row):
        """payTaskTaofa: finish count, delete, grant; None unless payable."""
        try:
            saved = self.get_task_taofa(rid, row['id'])
        except Exception:
            saved = None
        if saved is None:
            return None
        try:
            if int(saved.get('task_state') or 0) != 1:
                return None
        except (TypeError, ValueError):
            return None
        cfg = self.config.taofa_config(saved.get('task_id'))
        if cfg is None:
            return None
        state = self._taofa_state_or_init(rid)
        try:
            finish = int(state.get('finish_count') or 0)
        except (TypeError, ValueError):
            finish = 0
        try:
            self.save_task_taofa_state(
                rid, tunshi_count=state.get('tunshi_count') or 0,
                hebing_count=state.get('hebing_count') or 0,
                finish_count=finish + 1,
                total_count=state.get('total_count') or 0,
                create_time=int(time.time() * 1000))
        except Exception:
            pass
        try:
            self.delete_task_taofa(rid, row['id'])
        except Exception:
            pass
        return self._taofa_grant(role, rid, dict(saved), cfg)

    def _taofa_grant(self, role, rid, row, cfg):
        """reward(): currencies, exp, zhenqi, goods; the 50105 result array."""
        tunshi = int(row.get('ts_state') or 0) == 1
        totals = {}
        for base, key in (('jb', 'ts_reward_jb'), ('exp', 'ts_reward_exp'),
                          ('zhenqi', 'ts_reward_zhenqi'),
                          ('bind_yb', 'ts_reward_bing_yb')):
            try:
                amount = int(cfg.get(base) or 0)
            except (TypeError, ValueError):
                amount = 0
            if tunshi:
                try:
                    amount += int(row.get(key) or 0)
                except (TypeError, ValueError):
                    pass
            totals[base] = amount
        extra = []
        if totals['exp'] > 0:
            try:
                _total, _level, _gained, exp_frames = \
                    self._role_gain_exp(role, rid, totals['exp'])
                extra.extend(exp_frames[1:])
            except Exception:
                pass
        for key, column in (('bind_yb', 'bind_lingshi'),
                            ('jb', 'tongqian')):
            if totals[key] <= 0:
                continue
            try:
                total = int(role.get(column) or 0) + totals[key]
            except (TypeError, ValueError):
                total = totals[key]
            try:
                self.save_role_state(rid, **{column: total})
            except Exception:
                pass
        if totals['zhenqi'] > 0:
            try:
                total = int(role.get('zhenqi') or 0) + totals['zhenqi']
            except (TypeError, ValueError):
                total = totals['zhenqi']
            try:
                self.save_role_state(rid, zhenqi=total)
            except Exception:
                pass
        if cfg.get('goods'):
            self._task_grant(rid, cfg['goods'])
        if cfg.get('zubao'):
            # rollZubaoId needs the zubao module (read-only here).
            log.info('conn %d: taofa %r zubao rewards %r (not ported)',
                     self.conn_id, cfg.get('id'), cfg.get('zubao'))
        try:
            prestige = int(cfg.get('prestige') or 0)
        except (TypeError, ValueError):
            prestige = 0
        return ([cfg['id'],
                 self._taofa_show_pairs(cfg.get('show_items')),
                 int(cfg.get('exp') or 0), int(cfg.get('jb') or 0),
                 int(cfg.get('bind_yb') or 0), prestige,
                 int(cfg.get('zhenqi') or 0)], extra)

    @staticmethod
    def _task_kills_str(kills):
        """TaskDataUtil.killMap2String: 'mid;n,..' with the trailing comma cut."""
        text = ''.join(f'{mid};{count},' for mid, count in kills.items())
        return text[:-1] if text.endswith(',') else text

    def richang_info(self):
        """Command 50201: [quest VO, cost data, loop reward VO]."""
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        if self._task_role_level(role) < RICHANG_MIN_LEVEL:
            return None
        try:
            row = self.get_task_richang(rid)
        except Exception:
            row = None
        frames = []
        if row is None:
            row = self._richang_init(role, rid)
            if row is None:
                return None
            # initRiChang queues its own 50201 before the reply is built.
            frames.append(frame(amf3_encode(
                [str(CMD_RICHANG_INFO),
                 self._richang_output_data(dict(row))])))
        else:
            row = dict(row)
        row = self._richang_reset(rid, self._task_role_level(role), row)
        reply = self._richang_output_data(row)
        frames.append(frame(amf3_encode([str(CMD_RICHANG_INFO), reply])))
        return tuple(frames) if len(frames) > 1 else frames[0]

    def _richang_init(self, role, rid):
        """initRiChang: roll all three configs, insert, or None."""
        level = self._task_role_level(role)
        cond = self._richang_random_condition(level, None)
        reward = self._richang_random_reward(level, None)
        loop = self._richang_random_loop(level)
        if cond is None or reward is None or loop is None:
            return None
        now = int(time.time() * 1000)
        row = {'id': f'task{uuid.uuid4().hex[:16]}',
               'condition_config_id': cond['id'],
               'reward_config_id': reward['id'],
               'reward_loop_config_id': loop['id'],
               'task_condition': '', 'current_loop': 1, 'task_state': 0,
               'fufei_state': 0, 'recevie_time': now, 'create_time': now}
        try:
            self.save_task_richang(rid, **row)
        except Exception:
            return None
        return row

    def _richang_reset(self, rid, level, row):
        """resetTaskRichang: a stale recevie day re-rolls the quest."""
        now = int(time.time() * 1000)
        if self._same_day_ms(now, row.get('recevie_time')):
            return row
        cond = self._richang_random_condition(level, None)
        reward = self._richang_random_reward(level, None)
        loop = self._richang_random_loop(level)
        if cond is None or reward is None or loop is None:
            return row
        row.update(condition_config_id=cond['id'],
                   reward_config_id=reward['id'],
                   reward_loop_config_id=loop['id'], task_state=0,
                   fufei_state=0, task_condition='', current_loop=1,
                   recevie_time=now)
        self._richang_save(rid, row)
        return row

    def _richang_save(self, rid, row):
        """Persist a richang row dict under its role id."""
        fields = {key: row.get(key) for key in (
            'id', 'condition_config_id', 'reward_config_id',
            'reward_loop_config_id', 'task_condition', 'current_loop',
            'task_state', 'fufei_state', 'recevie_time', 'create_time')}
        try:
            self.save_task_richang(rid, **fields)
        except Exception:
            pass

    def _richang_out(self, row):
        """getTaskRichangOutPut: the 11-field quest VO, or None."""
        if row is None:
            return None
        cond = self.config.richang_condition(row.get('condition_config_id'))
        reward = self.config.richang_reward(row.get('reward_config_id'))
        if cond is None or reward is None:
            return None
        try:
            recevied = float(row.get('recevie_time') or 0)
        except (TypeError, ValueError):
            recevied = 0.0
        return [row.get('id'), recevied, row.get('task_state') or 0,
                [self._richang_monster_part(row, cond.get('complete_items')),
                 self._richang_monster_part(row, cond.get('kill_monsters'))],
                self._richang_reward_part(
                    reward.get('reward_items'), reward.get('jb') or 0,
                    reward.get('exp') or 0, reward.get('bind_yb') or 0,
                    reward.get('zhenqi') or 0, reward.get('prestige') or 0),
                reward.get('thick') or 0, cond.get('difficulty') or 0,
                row.get('current_loop') or 0, row.get('fufei_state') or 0,
                3, RICHANG_MAX_LOOP]

    def _richang_monster_part(self, row, mmap):
        """getMonsterOutPut: [id, need, done, auto, name]; last entry wins."""
        if not mmap:
            return None
        try:
            state = int(row.get('task_state') or 0)
        except (TypeError, ValueError):
            state = 0
        kills = self._task_kills(row.get('task_condition')) or {}
        part = None
        for monster_id, vo in mmap.items():
            if state in (1, 2):
                done = vo['count']
            else:
                done = kills.get(monster_id, 0)
            part = [monster_id, vo['count'], done, vo['auto_attack'],
                    vo['show_name']]
        return part

    def _richang_reward_part(self, items, jb, exp, bind_yb, zhenqi,
                             prestige):
        """getRewardOutPut(items, jb, exp, bindYb, zhenqi, prestige)."""
        pairs = self._taofa_show_pairs(items)
        return [jb, exp, bind_yb, zhenqi, prestige, None, 0, pairs]

    @staticmethod
    def _richang_state_data():
        """getTaskRiChangStateData: [jiangDi, tiSheng, direct, 1key, best]."""
        return [RICHANG_COST_JIANGDI, RICHANG_COST_TISHENG,
                RICHANG_COST_DIRECT, RICHANG_COST_ONEKEY,
                RICHANG_COST_ONEKEY_BEST]

    def _richang_output_data(self, row):
        """getTaskRiChangeOutputData: [quest VO, costs, loop reward VO]."""
        loop = self.config.richang_loop_reward(
            row.get('reward_loop_config_id'))
        if loop is None:
            loop = {'reward_items': None, 'jb': 0, 'exp': 0, 'bind_yb': 0,
                    'zhenqi': 0, 'prestige': 0}
        return [self._richang_out(row), self._richang_state_data(),
                self._richang_reward_part(
                    loop.get('reward_items'), loop.get('jb') or 0,
                    loop.get('exp') or 0, loop.get('bind_yb') or 0,
                    loop.get('zhenqi') or 0, loop.get('prestige') or 0)]

    def _richang_random_condition(self, level, difficulty):
        """randomCondition: Lottery.roll over the interval (or subinterval)."""
        sub = richang_condition_interval(
            self.config.richang_condition_buckets(), level)
        if not sub:
            return None
        if difficulty is None:
            pool = self.config.richang_condition_subinterval(sub)
        else:
            pool = self.config.richang_condition_interval(sub, difficulty)
        if not pool:
            return None
        return pool[random.randrange(len(pool))]

    def _richang_random_reward(self, level, thick):
        """randomReward: Lottery.roll over the interval (or subinterval)."""
        sub = richang_reward_interval(
            self.config.richang_reward_buckets(),
            self.config.richang_condition_buckets(), level)
        if not sub:
            return None
        if thick is None:
            pool = self.config.richang_reward_subinterval(sub)
        else:
            pool = self.config.richang_reward_interval(sub, thick)
        if not pool:
            return None
        return pool[random.randrange(len(pool))]

    def _richang_random_loop(self, level):
        """randomRewardLoop: Lottery.roll over the loop interval."""
        sub = richang_loop_interval(
            self.config.richang_loop_buckets(),
            self.config.richang_condition_buckets(), level)
        if not sub:
            return None
        pool = self.config.richang_loop_interval(sub)
        if not pool:
            return None
        return pool[random.randrange(len(pool))]

    def richang_decrease(self):
        """Command 50202: re-roll an easier condition for 50000 YXB."""
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        try:
            row = self.get_task_richang(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = dict(row)
        cond = self.config.richang_condition(row.get('condition_config_id'))
        if cond is None:
            return None
        if row.get('current_loop') == RICHANG_MAX_LOOP and \
                row.get('task_state') == 2:
            return frame(amf3_encode(
                ['50202', [0, TASK_ERR_RICHANG_MAX_LOOP]]))
        if cond.get('difficulty') == 1:
            return frame(amf3_encode(
                ['50202', [0, TASK_ERR_RICHANG_DIFF_MIN]]))
        if not self._bag_money_check(role, 'YXB', RICHANG_COST_JIANGDI):
            return frame(amf3_encode(['50202', [0, MALL_ERR_YB_NO_ENOUGHT]]))
        easier = self._richang_random_condition(
            self._task_role_level(role), 1)
        if easier is None:
            return None
        self._bag_money_decr(rid, 'YXB', RICHANG_COST_JIANGDI)
        row.update(condition_config_id=easier['id'], task_condition='',
                   task_state=0,
                   recevie_time=int(time.time() * 1000))
        self._richang_save(rid, row)
        part = [self._richang_monster_part(row, easier.get('complete_items')),
                self._richang_monster_part(row, easier.get('kill_monsters'))]
        return frame(amf3_encode(['50202', [1, 1, part]]))

    def richang_increase(self):
        """Command 50203: re-roll a best reward for 50000 YXB."""
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        try:
            row = self.get_task_richang(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = dict(row)
        reward = self.config.richang_reward(row.get('reward_config_id'))
        if reward is None:
            return None
        if row.get('current_loop') == RICHANG_MAX_LOOP and \
                row.get('task_state') == 2:
            return frame(amf3_encode(
                ['50203', self._richang_done_reply()]))
        if reward.get('thick') == RICHANG_THICK_MAX:
            return frame(amf3_encode(
                ['50203', [0, TASK_ERR_RICHANG_THICK_MAX]]))
        if not self._bag_money_check(role, 'YXB', RICHANG_COST_TISHENG):
            return frame(amf3_encode(
                ['50203', self._richang_yb_short()]))
        best = self._richang_random_reward(self._task_role_level(role),
                                           RICHANG_THICK_MAX)
        if best is None:
            return None
        self._bag_money_decr(rid, 'YXB', RICHANG_COST_TISHENG)
        row.update(reward_config_id=best['id'], task_state=0,
                   recevie_time=int(time.time() * 1000))
        self._richang_save(rid, row)
        return frame(amf3_encode(
            ['50203', [1, RICHANG_THICK_MAX,
                       self._richang_reward_part(
                           best.get('reward_items'), best.get('jb') or 0,
                           best.get('exp') or 0, best.get('bind_yb') or 0,
                           best.get('zhenqi') or 0,
                           best.get('prestige') or 0)]]))

    @staticmethod
    def _richang_done_reply():
        """GetTaskOutPut.riChaungTsak: [0, 480060]."""
        return [0, TASK_ERR_RICHANG_MAX_LOOP]

    @staticmethod
    def _richang_yb_short():
        """GetTaskOutPut.isYbNotEnough: [0, 430403]."""
        return [0, MALL_ERR_YB_NO_ENOUGHT]

    def richang_zhijie(self):
        """Command 50204: finish the loop now for 10 YB, then advance."""
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        try:
            row = self.get_task_richang(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = dict(row)
        if row.get('current_loop') == RICHANG_MAX_LOOP and \
                row.get('task_state') == 2:
            return frame(amf3_encode(
                ['50204', self._richang_done_reply()]))
        if not self._bag_money_check(role, 'YB', RICHANG_COST_DIRECT):
            return frame(amf3_encode(
                ['50204', self._richang_yb_short()]))
        self._bag_money_decr(rid, 'YB', RICHANG_COST_DIRECT)
        frames = []
        paid = self._richang_pay(role, rid, False)
        if paid is not None:
            result, extra = paid
            frames.append(frame(amf3_encode(
                [str(CMD_RICHANG_PAY), result])))
            frames.extend(extra)
            if self._richang_stop(rid, frames) is False:
                nxt = self._richang_receive(role, rid, False)
                if nxt is not None:
                    frames.append(nxt)
        # The finish event has no bus here; the reply is the wire half.
        frames.append(frame(amf3_encode(['50204', [1]])))
        return tuple(frames) if len(frames) > 1 else frames[0]

    def richang_complete_all(self):
        """Command 50205: one-key the rest for 50 YB (vip-gated)."""
        if self.config is None:
            return None
        _role, rid = self._task_role()
        if rid is None:
            return None
        try:
            row = self.get_task_richang(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = dict(row)
        if not self.config.vip_onekeytask(self._taofa_vip_level(rid)):
            return frame(amf3_encode(
                ['50205', [0, TASK_ERR_NOT_RICHANG]]))
        if row.get('current_loop') == RICHANG_MAX_LOOP and \
                row.get('task_state') == 2:
            return frame(amf3_encode(
                ['50205', self._richang_done_reply()]))
        role = (_role or {})
        if not self._bag_money_check(role, 'YB', RICHANG_COST_ONEKEY):
            return frame(amf3_encode(
                ['50205', self._richang_yb_short()]))
        self._bag_money_decr(rid, 'YB', RICHANG_COST_ONEKEY)
        row['fufei_state'] = 1
        self._richang_save(rid, row)
        # TaskRiChangCompleteEvent has no bus here.
        return frame(amf3_encode(['50205', [1, row['fufei_state']]]))

    def richang_complete_best(self):
        """Command 50206: best one-key for 100 YB (vip-gated)."""
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        try:
            row = self.get_task_richang(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = dict(row)
        if not self.config.vip_onekeytask(self._taofa_vip_level(rid)):
            return frame(amf3_encode(
                ['50206', [0, TASK_ERR_NOT_RICHANG]]))
        if row.get('current_loop') == RICHANG_MAX_LOOP and \
                row.get('task_state') == 2:
            return frame(amf3_encode(
                ['50206', [0, TASK_ERR_RICHANG_MAX_LOOP]]))
        if not self._bag_money_check(role, 'YB', RICHANG_COST_ONEKEY_BEST):
            return frame(amf3_encode(
                ['50206', [0, MALL_ERR_YB_NO_ENOUGHT]]))
        self._bag_money_decr(rid, 'YB', RICHANG_COST_ONEKEY_BEST)
        row['fufei_state'] = 2
        self._richang_save(rid, row)
        frames = []
        reward = self.config.richang_reward(row.get('reward_config_id'))
        if reward is not None and reward.get('thick') != RICHANG_THICK_MAX:
            best = self._richang_best_receive(rid, row)
            if best is not None:
                frames.append(best)
            try:
                row = dict(self.get_task_richang(rid) or row)
            except Exception:
                row = dict(row)
        reward = self.config.richang_reward(row.get('reward_config_id'))
        cond = self.config.richang_condition(
            row.get('condition_config_id'))
        part = self._richang_reward_part(
            (reward or {}).get('reward_items'),
            (reward or {}).get('jb') or 0, (reward or {}).get('exp') or 0,
            (reward or {}).get('bind_yb') or 0,
            (reward or {}).get('zhenqi') or 0,
            (reward or {}).get('prestige') or 0)
        # TaskRiChangCompleteBestEvent has no bus here.
        frames.append(frame(amf3_encode(
            ['50206', [1, row.get('fufei_state') or 0, part,
                       (reward or {}).get('thick') or 0,
                       (cond or {}).get('difficulty') or 0]])))
        return tuple(frames) if len(frames) > 1 else frames[0]

    def richang_notify_loop(self):
        """Command 50209: pay out a fufei loop, then advance or stop."""
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        try:
            row = self.get_task_richang(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = dict(row)
        if (row.get('fufei_state') or 0) == 0:
            return None
        if row.get('current_loop') == RICHANG_MAX_LOOP and \
                row.get('task_state') == 2:
            return None
        reward = self.config.richang_reward(row.get('reward_config_id'))
        if reward is None:
            return None
        frames = []
        best = (row.get('fufei_state') or 0) == 2
        paid = self._richang_pay(role, rid, False)
        if paid is not None:
            result, extra = paid
            frames.append(frame(amf3_encode(
                [str(CMD_RICHANG_PAY), result])))
            frames.extend(extra)
            if self._richang_stop(rid, frames) is False:
                nxt = self._richang_receive(role, rid, best)
                if nxt is not None:
                    frames.append(nxt)
        if not frames:
            return None
        return tuple(frames) if len(frames) > 1 else frames[0]

    def _richang_receive(self, role, rid, is_best):
        """receiveTaskRiChange: create or advance the quest, pushing 50210."""
        if self._task_role_level(role) < RICHANG_MIN_LEVEL:
            return None
        try:
            row = self.get_task_richang(rid)
        except Exception:
            row = None
        if row is not None and \
                (row.get('current_loop') or 0) >= RICHANG_MAX_LOOP:
            return None
        level = self._task_role_level(role)
        thick = RICHANG_THICK_MAX if is_best else None
        cond = self._richang_random_condition(level, thick)
        reward = self._richang_random_reward(level, thick)
        if cond is None or reward is None:
            return None
        if row is None:
            loop = self._richang_random_loop(level)
            if loop is None:
                return None
            now = int(time.time() * 1000)
            row = {'id': f'task{uuid.uuid4().hex[:16]}',
                   'condition_config_id': cond['id'],
                   'reward_config_id': reward['id'],
                   'reward_loop_config_id': loop['id'],
                   'task_condition': '', 'current_loop': 1, 'task_state': 0,
                   'fufei_state': 0, 'recevie_time': now, 'create_time': now}
        else:
            row = dict(row)
            row.update(condition_config_id=cond['id'],
                       reward_config_id=reward['id'], task_state=0,
                       task_condition='',
                       current_loop=(row.get('current_loop') or 0) + 1,
                       recevie_time=int(time.time() * 1000))
        self._richang_save(rid, row)
        return frame(amf3_encode(
            [str(CMD_RICHANG_RECEIVE), self._richang_out(dict(row))]))

    def _richang_best_receive(self, rid, row):
        """bestReceiveTaskRichange: best re-roll in place, pushing 50210."""
        if row is None:
            # Java would NPE on the missing quest; staying silent instead.
            return None
        try:
            roles = self.get_roles(self.authed_user or '',
                                   self.server_id or '')
            role = roles[0] if roles else None
        except Exception:
            role = None
        if role is None:
            return None
        level = self._task_role_level(role)
        cond = self._richang_random_condition(level, RICHANG_THICK_MAX)
        reward = self._richang_random_reward(level, RICHANG_THICK_MAX)
        if cond is None or reward is None:
            return None
        row = dict(row)
        row.update(condition_config_id=cond['id'],
                   reward_config_id=reward['id'], task_state=0,
                   task_condition='',
                   recevie_time=int(time.time() * 1000))
        self._richang_save(rid, row)
        return frame(amf3_encode(
            [str(CMD_RICHANG_RECEIVE), self._richang_out(dict(row))]))

    def _richang_pay(self, role, rid, is_best):
        """payTaskRichange: settle a finished loop; None unless payable."""
        try:
            row = self.get_task_richang(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = dict(row)
        if is_best and row.get('task_state') != 1:
            return None
        # payTaskRichange: a finished final loop pays once (state 1 ->
        # loop reward, fufei cleared); an already-settled row pays nothing.
        if row.get('current_loop') == RICHANG_MAX_LOOP and \
                row.get('task_state') == 2:
            return None
        reward = self.config.richang_reward(row.get('reward_config_id'))
        if reward is None:
            return None
        loop = None
        if row.get('current_loop') == RICHANG_MAX_LOOP:
            loop = self.config.richang_loop_reward(
                row.get('reward_loop_config_id'))
            row['fufei_state'] = 0
        row['task_state'] = 2
        self._richang_save(rid, row)
        return self._richang_grant(role, rid, row.get('id'), reward, loop)

    def _richang_grant(self, role, rid, task_uid, reward, loop):
        """reward(): currencies, exp, zhenqi, goods; the 50207 result array."""
        try:
            bind_yb = int(reward.get('bind_yb') or 0)
        except (TypeError, ValueError):
            bind_yb = 0
        try:
            jb = int(reward.get('jb') or 0)
        except (TypeError, ValueError):
            jb = 0
        try:
            exp = int(reward.get('exp') or 0)
        except (TypeError, ValueError):
            exp = 0
        try:
            zhenqi = int(reward.get('zhenqi') or 0)
        except (TypeError, ValueError):
            zhenqi = 0
        loop_items = None
        extra = []
        if loop is not None:
            try:
                bind_yb += int(loop.get('bind_yb') or 0)
                jb += int(loop.get('jb') or 0)
                exp += int(loop.get('exp') or 0)
                zhenqi += int(loop.get('zhenqi') or 0)
            except (TypeError, ValueError):
                pass
            loop_items = loop.get('reward_items')
        if exp > 0:
            try:
                _total, _level, _gained, exp_frames = \
                    self._role_gain_exp(role, rid, exp)
                extra.extend(exp_frames[1:])
            except Exception:
                pass
        if bind_yb > 0:
            try:
                total = int(role.get('bind_lingshi') or 0) + bind_yb
            except (TypeError, ValueError):
                total = bind_yb
            try:
                self.save_role_state(rid, bind_lingshi=total)
            except Exception:
                pass
        if jb > 0:
            try:
                total = int(role.get('tongqian') or 0) + jb
            except (TypeError, ValueError):
                total = jb
            try:
                self.save_role_state(rid, tongqian=total)
            except Exception:
                pass
        if zhenqi > 0:
            try:
                total = int(role.get('zhenqi') or 0) + zhenqi
            except (TypeError, ValueError):
                total = zhenqi
            try:
                self.save_role_state(rid, zhenqi=total)
            except Exception:
                pass
        merged = list(reward.get('reward_items') or [])
        if loop_items:
            merged.extend(loop_items)
        if merged:
            self._task_grant(rid, merged)
        if reward.get('reward_items'):
            pairs = [[item['goods_id'], item['count']] for item in merged]
        else:
            # Loop-only drops grant but never show, like the jar.
            pairs = []
        return ([task_uid, pairs, int(reward.get('exp') or 0),
                 int(reward.get('jb') or 0), int(reward.get('bind_yb') or 0),
                 0, int(reward.get('zhenqi') or 0)], extra)

    def _richang_stop(self, rid, frames):
        """stopRefreshRichang: 50211 + True on the finished final loop."""
        try:
            row = self.get_task_richang(rid)
        except Exception:
            row = None
        if row is None:
            return False
        row = dict(row)
        if row.get('current_loop') != RICHANG_MAX_LOOP or \
                row.get('task_state') != 2:
            return False
        loop = self.config.richang_loop_reward(
            row.get('reward_loop_config_id'))
        if loop is None:
            loop = {'reward_items': None, 'jb': 0, 'exp': 0, 'bind_yb': 0,
                    'zhenqi': 0, 'prestige': 0}
        frames.append(frame(amf3_encode(
            [str(CMD_RICHANG_STOP),
             [self._richang_out(row),
              self._richang_reward_part(
                  loop.get('reward_items'), loop.get('jb') or 0,
                  loop.get('exp') or 0, loop.get('bind_yb') or 0,
                  loop.get('zhenqi') or 0,
                  loop.get('prestige') or 0)]])))
        return True

    def richang_kill_progress(self, role, monster_id):
        """Kill hook: 50208 progress, 50207 pay, 50210/50211 advance."""
        if self.config is None or role is None:
            return []
        rid = role.get('id')
        try:
            row = self.get_task_richang(rid)
        except Exception:
            return []
        if row is None:
            return []
        row = dict(row)
        if row.get('task_state') in (1, 2):
            return []
        if (row.get('fufei_state') or 0) != 0:
            return []
        cond = self.config.richang_condition(row.get('condition_config_id'))
        if cond is None:
            return []
        killmap = cond.get('kill_monsters')
        if not killmap or monster_id not in killmap:
            return []
        try:
            need = int(killmap[monster_id]['count'] or 0)
        except (TypeError, ValueError):
            need = 0
        kills = self._task_kills(row.get('task_condition'))
        if kills is None:
            return []
        if not row.get('task_condition'):
            done = 1
            kills[monster_id] = 1
        else:
            current = kills.get(monster_id, 0)
            done = 0
            if need > current:
                done = (kills.get(monster_id) or 0) + 1
                kills[monster_id] = done
        row['task_condition'] = self._task_kills_str(kills)
        frames = [frame(amf3_encode(
            [str(CMD_RICHANG_CHANGE), [row['id'], monster_id, done]]))]
        complete = True
        for entry_id in killmap:
            progress = kills.get(entry_id)
            # The jar compares every entry against the killed monster's
            # need, which matches single-monster conditions exactly.
            if progress is None or need > progress:
                complete = False
                break
        if complete:
            row['task_state'] = 1
            paid = self._richang_pay(role, rid, True)
            if paid is not None:
                result, extra = paid
                frames.append(frame(amf3_encode(
                    [str(CMD_RICHANG_PAY), result])))
                frames.extend(extra)
                if self._richang_stop(rid, frames) is False:
                    nxt = self._richang_receive(role, rid, False)
                    if nxt is not None:
                        frames.append(nxt)
        self._richang_save(rid, row)
        return frames

    # Guild-task quests (GonghuitaskAction/GonghuitaskServiceImpl). Evidence:
    # action javap (7 inbound: 81000-81005 + 81008; pushes 81006/81007/81009/
    # 81010), IGonghuitaskService + impl bytecode, GongHuiTaskConstants and
    # GonghuitaskErrorCode clinit ints, RoleGonghuiTask fields, and the
    # GongHuiRenWu(.JiangLi/EWaiJiangLi).jat tables (120 conditions with
    # difficulties 1-12, 290 rewards, 72 loop rewards).
    #
    # The lifecycle mirrors richang exactly, with two deltas: every handler
    # first requires guild membership (null GuildWrapper answers silence,
    # like Java), and rewards credit banggong via addRoleGongxian. YB-short
    # failures answer GeneralErrorCode.YB_NOT_ENOUGH (1003), not 430403.
    def _gonghui_guild(self, rid):
        """Guild id of a role, or None (the Java null-GuildWrapper branch)."""
        try:
            return self.get_guild_id(rid)
        except Exception:
            return None

    def _gonghui_role(self):
        """(role, rid, guild_id); guild_id None means silent like Java."""
        role, rid = self._task_role()
        if role is None or rid is None:
            return None, None, None
        guild = self._gonghui_guild(rid)
        if guild is None:
            return None, None, None
        return role, rid, guild

    def gonghui_info(self):
        """Command 81000: [quest VO, cost data, loop reward VO]."""
        if self.config is None:
            return None
        role, rid, _guild = self._gonghui_role()
        if role is None:
            return None
        if self._task_role_level(role) < GONGHUI_MIN_LEVEL:
            return None
        try:
            row = self.get_task_gonghui(rid)
        except Exception:
            row = None
        frames = []
        if row is None:
            row = self._gonghui_init(role, rid)
            if row is None:
                return None
            # initRiChang queues its own 81000 before the reply is built.
            frames.append(frame(amf3_encode(
                [str(CMD_GONGHUI_INFO),
                 self._gonghui_output_data(dict(row))])))
        else:
            row = dict(row)
        row = self._gonghui_reset(rid, self._task_role_level(role), row)
        reply = self._gonghui_output_data(row)
        frames.append(frame(amf3_encode([str(CMD_GONGHUI_INFO), reply])))
        return tuple(frames) if len(frames) > 1 else frames[0]

    def _gonghui_init(self, role, rid):
        """initRiChang: roll all three configs, insert, or None."""
        level = self._task_role_level(role)
        cond = self._gonghui_random_condition(level, None)
        reward = self._gonghui_random_reward(level, None)
        loop = self._gonghui_random_loop(level)
        if cond is None or reward is None or loop is None:
            return None
        now = int(time.time() * 1000)
        row = {'id': f'task{uuid.uuid4().hex[:16]}',
               'condition_config_id': cond['id'],
               'reward_config_id': reward['id'],
               'reward_loop_config_id': loop['id'],
               'task_condition': '', 'current_loop': 1, 'task_state': 0,
               'fufei_state': 0, 'recevie_time': now, 'create_time': now}
        try:
            self.save_task_gonghui(rid, **row)
        except Exception:
            return None
        return row

    def _gonghui_reset(self, rid, level, row):
        """resetTaskRichang: a stale recevie day re-rolls the quest."""
        now = int(time.time() * 1000)
        if self._same_day_ms(now, row.get('recevie_time')):
            return row
        cond = self._gonghui_random_condition(level, None)
        reward = self._gonghui_random_reward(level, None)
        loop = self._gonghui_random_loop(level)
        if cond is None or reward is None or loop is None:
            return row
        row.update(condition_config_id=cond['id'],
                   reward_config_id=reward['id'],
                   reward_loop_config_id=loop['id'], task_state=0,
                   fufei_state=0, task_condition='', current_loop=1,
                   recevie_time=now)
        self._gonghui_save(rid, row)
        return row

    def _gonghui_save(self, rid, row):
        """Persist a guild-task row dict under its role id."""
        fields = {key: row.get(key) for key in (
            'id', 'condition_config_id', 'reward_config_id',
            'reward_loop_config_id', 'task_condition', 'current_loop',
            'task_state', 'fufei_state', 'recevie_time', 'create_time')}
        try:
            self.save_task_gonghui(rid, **fields)
        except Exception:
            pass

    def _gonghui_out(self, row):
        """getTaskRichangOutPut: the 11-field quest VO, or None."""
        if row is None:
            return None
        cond = self.config.gonghui_condition(row.get('condition_config_id'))
        reward = self.config.gonghui_reward(row.get('reward_config_id'))
        if cond is None or reward is None:
            return None
        try:
            recevied = float(row.get('recevie_time') or 0)
        except (TypeError, ValueError):
            recevied = 0.0
        return [row.get('id'), recevied, row.get('task_state') or 0,
                [self._gonghui_monster_part(row, cond.get('complete_items')),
                 self._gonghui_monster_part(row, cond.get('kill_monsters'))],
                self._gonghui_reward_part(
                    reward.get('reward_items'), reward.get('jb') or 0,
                    reward.get('exp') or 0, reward.get('bind_yb') or 0,
                    reward.get('zhenqi') or 0,
                    reward.get('prestige') or 0),
                reward.get('thick') or 0, cond.get('difficulty') or 0,
                row.get('current_loop') or 0, row.get('fufei_state') or 0,
                3, GONGHUI_MAX_LOOP]

    def _gonghui_monster_part(self, row, mmap):
        """getMonsterOutPut: [id, need, done, auto, name]; last entry wins."""
        if not mmap:
            return None
        try:
            state = int(row.get('task_state') or 0)
        except (TypeError, ValueError):
            state = 0
        kills = self._task_kills(row.get('task_condition')) or {}
        part = None
        for monster_id, vo in mmap.items():
            if state in (1, 2):
                done = vo['count']
            else:
                done = kills.get(monster_id, 0)
            part = [monster_id, vo['count'], done, vo['auto_attack'],
                    vo['show_name']]
        return part

    def _gonghui_reward_part(self, items, jb, exp, bind_yb, zhenqi,
                             prestige):
        """getRewardOutPut(items, jb, exp, bindYb, zhenqi, prestige)."""
        pairs = self._taofa_show_pairs(items)
        return [jb, exp, bind_yb, zhenqi, prestige, None, 0, pairs]

    @staticmethod
    def _gonghui_state_data():
        """getTaskRiChangStateData: [jiangDi, tiSheng, direct, 1key, best]."""
        return [GONGHUI_COST_JIANGDI, GONGHUI_COST_TISHENG,
                GONGHUI_COST_DIRECT, GONGHUI_COST_ONEKEY,
                GONGHUI_COST_ONEKEY_BEST]

    def _gonghui_output_data(self, row):
        """getTaskRiChangeOutputData: [quest VO, costs, loop reward VO]."""
        loop = self.config.gonghui_loop_reward(
            row.get('reward_loop_config_id'))
        if loop is None:
            loop = {'reward_items': None, 'jb': 0, 'exp': 0, 'bind_yb': 0,
                    'zhenqi': 0, 'prestige': 0}
        return [self._gonghui_out(row), self._gonghui_state_data(),
                self._gonghui_reward_part(
                    loop.get('reward_items'), loop.get('jb') or 0,
                    loop.get('exp') or 0, loop.get('bind_yb') or 0,
                    loop.get('zhenqi') or 0, loop.get('prestige') or 0)]

    def _gonghui_random_condition(self, level, difficulty):
        """randomCondition: Lottery.roll over the interval (or subinterval)."""
        sub = richang_condition_interval(
            self.config.gonghui_condition_buckets(), level)
        if not sub:
            return None
        if difficulty is None:
            pool = self.config.gonghui_condition_subinterval(sub)
        else:
            pool = self.config.gonghui_condition_interval(sub, difficulty)
        if not pool:
            return None
        return pool[random.randrange(len(pool))]

    def _gonghui_random_reward(self, level, thick):
        """randomReward: Lottery.roll over the interval (or subinterval)."""
        sub = richang_reward_interval(
            self.config.gonghui_reward_buckets(),
            self.config.gonghui_condition_buckets(), level)
        if not sub:
            return None
        if thick is None:
            pool = self.config.gonghui_reward_subinterval(sub)
        else:
            pool = self.config.gonghui_reward_interval(sub, thick)
        if not pool:
            return None
        return pool[random.randrange(len(pool))]

    def _gonghui_random_loop(self, level):
        """randomRewardLoop: Lottery.roll over the loop interval."""
        sub = richang_loop_interval(
            self.config.gonghui_loop_buckets(),
            self.config.gonghui_condition_buckets(), level)
        if not sub:
            return None
        pool = self.config.gonghui_loop_interval(sub)
        if not pool:
            return None
        return pool[random.randrange(len(pool))]

    @staticmethod
    def _gonghui_done_reply():
        """GetGongHuiOutPut.getError(81101): the finished-loop guard."""
        return [0, TASK_ERR_GONGHUI_DONE]

    @staticmethod
    def _gonghui_yb_short():
        """GeneralErrorCode.YB_NOT_ENOUGH (1003), not the mall 430403."""
        return [0, TASK_ERR_GONGHUI_YB_SHORT]

    def gonghui_decrease(self):
        """Command 81001: re-roll an easier condition for 50000 YXB."""
        if self.config is None:
            return None
        role, rid, _guild = self._gonghui_role()
        if role is None:
            return None
        try:
            row = self.get_task_gonghui(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = dict(row)
        cond = self.config.gonghui_condition(
            row.get('condition_config_id'))
        if cond is None:
            return None
        if row.get('current_loop') == GONGHUI_MAX_LOOP and \
                row.get('task_state') == 2:
            return frame(amf3_encode(
                ['81001', self._gonghui_done_reply()]))
        if cond.get('difficulty') == 1:
            return frame(amf3_encode(
                ['81001', [0, TASK_ERR_GONGHUI_DIFF_MIN]]))
        if not self._bag_money_check(role, 'YXB', GONGHUI_COST_JIANGDI):
            return frame(amf3_encode(['81001', self._gonghui_yb_short()]))
        easier = self._gonghui_random_condition(
            self._task_role_level(role), 1)
        if easier is None:
            return None
        self._bag_money_decr(rid, 'YXB', GONGHUI_COST_JIANGDI)
        row.update(condition_config_id=easier['id'], task_condition='',
                   task_state=0,
                   recevie_time=int(time.time() * 1000))
        self._gonghui_save(rid, row)
        part = [self._gonghui_monster_part(row, easier.get('complete_items')),
                self._gonghui_monster_part(row, easier.get('kill_monsters'))]
        return frame(amf3_encode(['81001', [1, 1, part]]))

    def gonghui_increase(self):
        """Command 81002: re-roll a best reward for 50000 YXB."""
        if self.config is None:
            return None
        role, rid, _guild = self._gonghui_role()
        if role is None:
            return None
        try:
            row = self.get_task_gonghui(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = dict(row)
        reward = self.config.gonghui_reward(row.get('reward_config_id'))
        if reward is None:
            return None
        if row.get('current_loop') == GONGHUI_MAX_LOOP and \
                row.get('task_state') == 2:
            return frame(amf3_encode(
                ['81002', self._gonghui_done_reply()]))
        if reward.get('thick') == GONGHUI_THICK_MAX:
            return frame(amf3_encode(
                ['81002', [0, TASK_ERR_GONGHUI_THICK_MAX]]))
        if not self._bag_money_check(role, 'YXB', GONGHUI_COST_TISHENG):
            return frame(amf3_encode(['81002', self._gonghui_yb_short()]))
        best = self._gonghui_random_reward(self._task_role_level(role),
                                            GONGHUI_THICK_MAX)
        if best is None:
            return None
        self._bag_money_decr(rid, 'YXB', GONGHUI_COST_TISHENG)
        row.update(reward_config_id=best['id'], task_state=0,
                   recevie_time=int(time.time() * 1000))
        self._gonghui_save(rid, row)
        return frame(amf3_encode(
            ['81002', [1, GONGHUI_THICK_MAX,
                       self._gonghui_reward_part(
                           best.get('reward_items'),
                           best.get('jb') or 0, best.get('exp') or 0,
                           best.get('bind_yb') or 0,
                           best.get('zhenqi') or 0,
                           best.get('prestige') or 0)]]))

    def gonghui_zhijie(self):
        """Command 81003: finish the loop now for 10 YB, then advance."""
        if self.config is None:
            return None
        role, rid, _guild = self._gonghui_role()
        if role is None:
            return None
        try:
            row = self.get_task_gonghui(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = dict(row)
        if row.get('current_loop') == GONGHUI_MAX_LOOP and \
                row.get('task_state') == 2:
            return frame(amf3_encode(
                ['81003', self._gonghui_done_reply()]))
        if not self._bag_money_check(role, 'YB', GONGHUI_COST_DIRECT):
            return frame(amf3_encode(['81003', self._gonghui_yb_short()]))
        self._bag_money_decr(rid, 'YB', GONGHUI_COST_DIRECT)
        frames = []
        paid = self._gonghui_pay(role, rid, False)
        if paid is not None:
            result, extra = paid
            frames.append(frame(amf3_encode(
                [str(CMD_GONGHUI_PAY), result])))
            frames.extend(extra)
            if self._gonghui_stop(rid, frames) is False:
                nxt = self._gonghui_receive(role, rid, False)
                if nxt is not None:
                    frames.append(nxt)
        # The finish event has no bus here; the reply is the wire half.
        frames.append(frame(amf3_encode(['81003', [1]])))
        return tuple(frames) if len(frames) > 1 else frames[0]

    def gonghui_complete_all(self):
        """Command 81004: one-key the rest for 50 YB (vip-gated)."""
        if self.config is None:
            return None
        _role, rid, _guild = self._gonghui_role()
        if rid is None:
            return None
        try:
            row = self.get_task_gonghui(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = dict(row)
        if not self.config.vip_onekeytask(self._taofa_vip_level(rid)):
            return frame(amf3_encode(
                ['81004', [0, TASK_ERR_NOT_RICHANG]]))
        if row.get('current_loop') == GONGHUI_MAX_LOOP and \
                row.get('task_state') == 2:
            return frame(amf3_encode(
                ['81004', self._gonghui_done_reply()]))
        role = (_role or {})
        if not self._bag_money_check(role, 'YB', GONGHUI_COST_ONEKEY):
            return frame(amf3_encode(['81004', self._gonghui_yb_short()]))
        self._bag_money_decr(rid, 'YB', GONGHUI_COST_ONEKEY)
        row['fufei_state'] = 1
        self._gonghui_save(rid, row)
        # TaskRiChangCompleteEvent has no bus here.
        return frame(amf3_encode(['81004', [1, row['fufei_state']]]))

    def gonghui_complete_best(self):
        """Command 81005: best one-key for 100 YB (vip-gated)."""
        if self.config is None:
            return None
        role, rid, _guild = self._gonghui_role()
        if role is None:
            return None
        try:
            row = self.get_task_gonghui(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = dict(row)
        if not self.config.vip_onekeytask(self._taofa_vip_level(rid)):
            return frame(amf3_encode(
                ['81005', [0, TASK_ERR_NOT_RICHANG]]))
        if row.get('current_loop') == GONGHUI_MAX_LOOP and \
                row.get('task_state') == 2:
            return frame(amf3_encode(
                ['81005', [0, TASK_ERR_GONGHUI_DONE]]))
        if not self._bag_money_check(role, 'YB', GONGHUI_COST_ONEKEY_BEST):
            return frame(amf3_encode(['81005', self._gonghui_yb_short()]))
        self._bag_money_decr(rid, 'YB', GONGHUI_COST_ONEKEY_BEST)
        row['fufei_state'] = 2
        self._gonghui_save(rid, row)
        frames = []
        reward = self.config.gonghui_reward(row.get('reward_config_id'))
        if reward is not None and reward.get('thick') != GONGHUI_THICK_MAX:
            best = self._gonghui_best_receive(rid, row)
            if best is not None:
                frames.append(best)
            try:
                row = dict(self.get_task_gonghui(rid) or row)
            except Exception:
                row = dict(row)
        reward = self.config.gonghui_reward(row.get('reward_config_id'))
        cond = self.config.gonghui_condition(
            row.get('condition_config_id'))
        part = self._gonghui_reward_part(
            (reward or {}).get('reward_items'),
            (reward or {}).get('jb') or 0, (reward or {}).get('exp') or 0,
            (reward or {}).get('bind_yb') or 0,
            (reward or {}).get('zhenqi') or 0,
            (reward or {}).get('prestige') or 0)
        # TaskRiChangCompleteBestEvent has no bus here.
        frames.append(frame(amf3_encode(
            ['81005', [1, row.get('fufei_state') or 0, part,
                       (reward or {}).get('thick') or 0,
                       (cond or {}).get('difficulty') or 0]])))
        return tuple(frames) if len(frames) > 1 else frames[0]

    def gonghui_notify_loop(self):
        """Command 81008: pay out a fufei loop, then advance or stop."""
        if self.config is None:
            return None
        role, rid, _guild = self._gonghui_role()
        if role is None:
            return None
        try:
            row = self.get_task_gonghui(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = dict(row)
        if (row.get('fufei_state') or 0) == 0:
            return None
        if row.get('current_loop') == GONGHUI_MAX_LOOP and \
                row.get('task_state') == 2:
            return None
        reward = self.config.gonghui_reward(row.get('reward_config_id'))
        if reward is None:
            return None
        frames = []
        best = (row.get('fufei_state') or 0) == 2
        paid = self._gonghui_pay(role, rid, False)
        if paid is not None:
            result, extra = paid
            frames.append(frame(amf3_encode(
                [str(CMD_GONGHUI_PAY), result])))
            frames.extend(extra)
            if self._gonghui_stop(rid, frames) is False:
                nxt = self._gonghui_receive(role, rid, best)
                if nxt is not None:
                    frames.append(nxt)
        if not frames:
            return None
        return tuple(frames) if len(frames) > 1 else frames[0]

    def _gonghui_receive(self, role, rid, is_best):
        """receiveTaskRiChange: create or advance the quest, pushing 81009."""
        if self._task_role_level(role) < GONGHUI_MIN_LEVEL:
            return None
        try:
            row = self.get_task_gonghui(rid)
        except Exception:
            row = None
        if row is not None and \
                (row.get('current_loop') or 0) >= GONGHUI_MAX_LOOP:
            return None
        level = self._task_role_level(role)
        # Special loops re-roll at fixed thick: the finished final loop
        # (state 2 at loop 19) and loop 14 draw difficulty 11/12 configs.
        thick = None
        if row is not None:
            if (row.get('current_loop') or 0) == GONGHUI_MAX_LOOP - 1 and \
                    row.get('task_state') == 2:
                thick = 11
            elif (row.get('current_loop') or 0) == 14 and \
                    row.get('task_state') == 2:
                thick = 12
        if is_best:
            thick = GONGHUI_THICK_MAX
        cond = self._gonghui_random_condition(level, thick)
        reward = self._gonghui_random_reward(level, thick)
        if cond is None or reward is None:
            return None
        if row is None:
            loop = self._gonghui_random_loop(level)
            if loop is None:
                return None
            now = int(time.time() * 1000)
            row = {'id': f'task{uuid.uuid4().hex[:16]}',
                   'condition_config_id': cond['id'],
                   'reward_config_id': reward['id'],
                   'reward_loop_config_id': loop['id'],
                   'task_condition': '', 'current_loop': 1, 'task_state': 0,
                   'fufei_state': 0, 'recevie_time': now, 'create_time': now}
        else:
            row = dict(row)
            row.update(condition_config_id=cond['id'],
                       reward_config_id=reward['id'], task_state=0,
                       task_condition='',
                       current_loop=(row.get('current_loop') or 0) + 1,
                       recevie_time=int(time.time() * 1000))
        self._gonghui_save(rid, row)
        return frame(amf3_encode(
            [str(CMD_GONGHUI_RECEIVE), self._gonghui_out(dict(row))]))

    def _gonghui_best_receive(self, rid, row):
        """bestReceiveTaskRichange: best re-roll in place, pushing 81009."""
        if row is None:
            # Java would NPE on the missing quest; staying silent instead.
            return None
        try:
            roles = self.get_roles(self.authed_user or '',
                                   self.server_id or '')
            role = roles[0] if roles else None
        except Exception:
            role = None
        if role is None:
            return None
        level = self._task_role_level(role)
        cond = self._gonghui_random_condition(level, GONGHUI_THICK_MAX)
        reward = self._gonghui_random_reward(level, GONGHUI_THICK_MAX)
        if cond is None or reward is None:
            return None
        row = dict(row)
        row.update(condition_config_id=cond['id'],
                   reward_config_id=reward['id'], task_state=0,
                   task_condition='',
                   recevie_time=int(time.time() * 1000))
        self._gonghui_save(rid, row)
        return frame(amf3_encode(
            [str(CMD_GONGHUI_RECEIVE), self._gonghui_out(dict(row))]))

    def _gonghui_pay(self, role, rid, is_best):
        """payTaskRichange: settle a finished loop; None unless payable."""
        try:
            row = self.get_task_gonghui(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = dict(row)
        if is_best and row.get('task_state') != 1:
            return None
        # payTaskRichange: a finished final loop pays once (state 1 ->
        # loop reward, fufei cleared); an already-settled row pays nothing.
        if row.get('current_loop') == GONGHUI_MAX_LOOP and \
                row.get('task_state') == 2:
            return None
        reward = self.config.gonghui_reward(row.get('reward_config_id'))
        if reward is None:
            return None
        loop = None
        if row.get('current_loop') == GONGHUI_MAX_LOOP:
            loop = self.config.gonghui_loop_reward(
                row.get('reward_loop_config_id'))
            row['fufei_state'] = 0
        row['task_state'] = 2
        self._gonghui_save(rid, row)
        return self._gonghui_grant(role, rid, row.get('id'), reward, loop)

    def _gonghui_grant(self, role, rid, task_uid, reward, loop):
        """reward(): currencies, exp, zhenqi, banggong, goods; the 81006 array."""
        try:
            bind_yb = int(reward.get('bind_yb') or 0)
        except (TypeError, ValueError):
            bind_yb = 0
        try:
            jb = int(reward.get('jb') or 0)
        except (TypeError, ValueError):
            jb = 0
        try:
            exp = int(reward.get('exp') or 0)
        except (TypeError, ValueError):
            exp = 0
        try:
            zhenqi = int(reward.get('zhenqi') or 0)
        except (TypeError, ValueError):
            zhenqi = 0
        try:
            banggong = int(reward.get('banggong') or 0)
        except (TypeError, ValueError):
            banggong = 0
        loop_items = None
        if loop is not None:
            try:
                bind_yb += int(loop.get('bind_yb') or 0)
                jb += int(loop.get('jb') or 0)
                exp += int(loop.get('exp') or 0)
                zhenqi += int(loop.get('zhenqi') or 0)
                banggong += int(loop.get('banggong') or 0)
            except (TypeError, ValueError):
                pass
            loop_items = loop.get('reward_items')
        if exp > 0:
            try:
                _total, _level, _gained, exp_frames = \
                    self._role_gain_exp(role, rid, exp)
                extra_frames = list(exp_frames[1:])
            except Exception:
                extra_frames = []
        else:
            extra_frames = []
        if bind_yb > 0:
            try:
                total = int(role.get('bind_lingshi') or 0) + bind_yb
            except (TypeError, ValueError):
                total = bind_yb
            try:
                self.save_role_state(rid, bind_lingshi=total)
            except Exception:
                pass
        if jb > 0:
            try:
                total = int(role.get('tongqian') or 0) + jb
            except (TypeError, ValueError):
                total = jb
            try:
                self.save_role_state(rid, tongqian=total)
            except Exception:
                pass
        if zhenqi > 0:
            try:
                total = int(role.get('zhenqi') or 0) + zhenqi
            except (TypeError, ValueError):
                total = zhenqi
            try:
                self.save_role_state(rid, zhenqi=total)
            except Exception:
                pass
        if banggong > 0:
            # addRoleGongxian: contribution lands on the member row.
            try:
                self.add_guild_gongxian(rid, banggong)
            except Exception:
                pass
        merged = list(reward.get('reward_items') or [])
        if loop_items:
            merged.extend(loop_items)
        if merged:
            self._task_grant(rid, merged)
        if reward.get('reward_items'):
            pairs = [[item['goods_id'], item['count']] for item in merged]
        else:
            # Loop-only drops grant but never show, like the jar.
            pairs = []
        return ([task_uid, pairs, int(reward.get('exp') or 0),
                 int(reward.get('jb') or 0), int(reward.get('bind_yb') or 0),
                 0, int(reward.get('zhenqi') or 0)], extra_frames)

    def _gonghui_stop(self, rid, frames):
        """stopRefreshRichang: 81010 + True on the finished final loop."""
        try:
            row = self.get_task_gonghui(rid)
        except Exception:
            row = None
        if row is None:
            return False
        row = dict(row)
        if row.get('current_loop') != GONGHUI_MAX_LOOP or \
                row.get('task_state') != 2:
            return False
        loop = self.config.gonghui_loop_reward(
            row.get('reward_loop_config_id'))
        if loop is None:
            loop = {'reward_items': None, 'jb': 0, 'exp': 0, 'bind_yb': 0,
                    'zhenqi': 0, 'prestige': 0}
        frames.append(frame(amf3_encode(
            [str(CMD_GONGHUI_STOP),
             [self._gonghui_out(row),
              self._gonghui_reward_part(
                  loop.get('reward_items'), loop.get('jb') or 0,
                  loop.get('exp') or 0, loop.get('bind_yb') or 0,
                  loop.get('zhenqi') or 0,
                  loop.get('prestige') or 0)]])))
        return True

    def gonghui_kill_progress(self, role, monster_id):
        """Kill hook: 81007 progress, 81006 pay, 81009/81010 advance."""
        if self.config is None or role is None:
            return []
        rid = role.get('id')
        if self._gonghui_guild(rid) is None:
            # The monster-dead handler only fires for guild members in
            # Java (the quest row cannot exist without membership).
            return []
        try:
            row = self.get_task_gonghui(rid)
        except Exception:
            return []
        if row is None:
            return []
        row = dict(row)
        if row.get('task_state') in (1, 2):
            return []
        if (row.get('fufei_state') or 0) != 0:
            return []
        cond = self.config.gonghui_condition(
            row.get('condition_config_id'))
        if cond is None:
            return []
        killmap = cond.get('kill_monsters')
        if not killmap or monster_id not in killmap:
            return []
        try:
            need = int(killmap[monster_id]['count'] or 0)
        except (TypeError, ValueError):
            need = 0
        kills = self._task_kills(row.get('task_condition'))
        if kills is None:
            return []
        if not row.get('task_condition'):
            done = 1
            kills[monster_id] = 1
        else:
            current = kills.get(monster_id, 0)
            done = 0
            if need > current:
                done = (kills.get(monster_id) or 0) + 1
                kills[monster_id] = done
        row['task_condition'] = self._task_kills_str(kills)
        frames = [frame(amf3_encode(
            [str(CMD_GONGHUI_CHANGE), [row['id'], monster_id, done]]))]
        complete = True
        for entry_id in killmap:
            progress = kills.get(entry_id)
            # The jar compares every entry against the killed monster's
            # need, which matches single-monster conditions exactly.
            if progress is None or need > progress:
                complete = False
                break
        if complete:
            row['task_state'] = 1
            # The jar mutates the shared cached entity, so payTaskRichange
            # observes state 1; persisting first reproduces that visibility.
            self._gonghui_save(rid, row)
            paid = self._gonghui_pay(role, rid, True)
            if paid is not None:
                result, extra = paid
                frames.append(frame(amf3_encode(
                    [str(CMD_GONGHUI_PAY), result])))
                frames.extend(extra)
                if self._gonghui_stop(rid, frames) is False:
                    nxt = self._gonghui_receive(role, rid, False)
                    if nxt is not None:
                        frames.append(nxt)
            try:
                row = dict(self.get_task_gonghui(rid) or row)
            except Exception:
                pass
        self._gonghui_save(rid, row)
        return frames

    # Battle-formation (pozhen 48001-48011). Evidence: PoZhenAction (11
    # inbound; 48011 getGoods is a void grant), RolePozhenServiceImpl plus
    # the MopupInner sweep math, PoZhenUtil splitPZ/zuzhiMax/megre, the
    # PoZhenBiao.dat/PoZhenXinXi/PoZhenShuaXin loaders, and the shipped
    # PoZhenBiao (150 rows, 10 layers), PoZhenShuaXin, PoZhenXinXi,
    # vipbiao (pozhen/pozhentime) and ZuBaoDiaoLuoBiao (@pozhen001-110).
    @staticmethod
    def _pozhen_split(text):
        """PoZhenUtil.splitPZ: 'main-idx' ints, [1, 0] when absent."""
        if not text:
            return [1, 0]
        try:
            parts = str(text).split('-')
            return [int(parts[0]), int(parts[1])]
        except (TypeError, ValueError, IndexError):
            return [1, 0]

    @staticmethod
    def _pozhen_loc_map(text):
        """PoZhenUtil.megre(String): 'main-idx;...' to {main: idx}."""
        loc = {}
        if not text:
            return loc
        for cell in str(text).split(';'):
            if not cell:
                continue
            try:
                key, val = cell.split('-')
                loc[int(key)] = int(val)
            except (TypeError, ValueError):
                continue
        return loc

    @staticmethod
    def _pozhen_loc_str(loc):
        """PoZhenUtil.megre(Map): {main: idx} to 'main-idx;...' ('' empty)."""
        if not loc:
            return ''
        return ';'.join(f'{key}-{loc[key]}' for key in loc)

    def _pozhen_role(self):
        """(role, rid) for the authed account's first role."""
        role, rid = self._task_role()
        if role is None or rid is None:
            return None, None
        return role, rid

    def _pozhen_vip_max(self, rid):
        """VipConfig.getPozhen: daily point cap for the role's tier."""
        if self.config is None:
            return 0
        return self.config.vip_pozhen_count(self._role_vip_level(rid))

    def _pozhen_sweep_ms(self, rid):
        """VipConfig.getPoZhenSaoDangTime: millis per sweep point."""
        if self.config is None:
            return 0
        return self.config.vip_pozhen_saodang_ms(
            self._role_vip_level(rid))

    def _pozhen_save(self, rid, row):
        """Persist a formation row dict under its role id."""
        fields = {key: row.get(key) for key in (
            'max_location', 'locations', 'can_use_count', 'buy_count',
            'refresh_count', 'in_mopup', 'sd_main_id', 'mopup_time',
            'recovery_time', 'refresh_time', 'award_rate', 'expire_time')}
        try:
            self.save_role_pozhen(rid, **fields)
        except Exception:
            pass

    def _pozhen_create(self, rid, vip_max):
        """createRolePoZhen: zeroed row with a full point bar, saved."""
        now = int(time.time() * 1000)
        row = {'max_location': None, 'locations': None,
               'can_use_count': vip_max, 'buy_count': 0,
               'refresh_count': 0, 'in_mopup': 0, 'sd_main_id': 0,
               'mopup_time': 0, 'recovery_time': 0, 'refresh_time': now,
               'award_rate': None, 'expire_time': None}
        self._pozhen_save(rid, row)
        return row

    def _pozhen_online(self, row, rid, vip_max):
        """pozhenOnline: a stale refresh day refills the bar, saved."""
        now = int(time.time() * 1000)
        if not self._same_day_ms(row.get('refresh_time'), now):
            row['buy_count'] = 0
            row['can_use_count'] = vip_max
            row['refresh_count'] = 0
            row['recovery_time'] = 0
            row['refresh_time'] = now
            self._pozhen_save(rid, row)
        return row

    def _pozhen_cal_cur(self, row):
        """calCurCeng: [max layer, idx], rolling over a cleared layer."""
        cur = self._pozhen_split((row or {}).get('max_location'))
        if self.config is None:
            return cur
        cfg = self.config.pozhen_layer(cur[0])
        if cfg is None:
            return cur
        if cur[1] < cfg['max']:
            return cur
        nxt = self.config.pozhen_layer(cur[0] + 1)
        if nxt is None:
            return cur
        return [cur[0] + 1, nxt['min'] - 1]

    @staticmethod
    def _pozhen_compute_next(cfg, idx):
        """computeNext: [main, idx + 1], or [main + 1, min] past max."""
        if idx < cfg['max']:
            return [cfg['main_id'], idx + 1]
        return [cfg['main_id'] + 1, cfg['min']]

    def _pozhen_check_can(self, row, main_id, idx):
        """checkCanPozhen: error code or None when the cell may start."""
        if row is None:
            return POZHEN_ERR_LEVEL_LESS
        try:
            if int(row.get('can_use_count') or 0) <= 0:
                return POZHEN_ERR_DIANSHU_LESS
        except (TypeError, ValueError):
            return POZHEN_ERR_DIANSHU_LESS
        cfg = self.config.pozhen_layer(main_id)
        if cfg is None:
            return POZHEN_ERR_NOT_EXIST
        if idx not in cfg['subs']:
            return POZHEN_ERR_NOT_EXIST
        cur = self._pozhen_split(row.get('max_location'))
        cur_cfg = self.config.pozhen_layer(cur[0])
        nxt = self._pozhen_compute_next(cur_cfg, cur[1]) \
            if cur_cfg is not None else None
        if nxt is None:
            if main_id > cur[0]:
                return POZHEN_ERR_NOT_EXIST
            if main_id == cur[0] and idx > cur[1]:
                return POZHEN_ERR_NOT_EXIST
        else:
            if main_id > nxt[0] or \
                    (main_id == nxt[0] and idx > nxt[1]):
                return POZHEN_ERR_YUEJI
            if main_id == nxt[0] and idx == nxt[1]:
                return None
        loc = self._pozhen_loc_map(row.get('locations'))
        if main_id not in loc:
            return POZHEN_ERR_YUEJI
        if idx <= loc[main_id]:
            return POZHEN_ERR_NO_REFRESH
        return None

    def _pozhen_decr(self, row, rid, count):
        """decrPoZhenDianShu: spend points, stamping recovery at full."""
        try:
            have = int(row.get('can_use_count') or 0)
        except (TypeError, ValueError):
            return False
        if have < count:
            return False
        if have == self._pozhen_vip_max(rid):
            row['recovery_time'] = int(time.time() * 1000)
        row['can_use_count'] = have - count
        return True

    def _pozhen_win_and_add(self, role, rid, sub, row):
        """computeWinAndAdd: level-scaled jb/exp/zhenqi + zubao bag drop.

        Grants YXB/exp/zhenqi/bag immediately like the jar; the buff
        multiplies jb and exp only (zhenqi rides unscaled). Returns
        ([jb, exp, zhenqi, itemVo], level-up frames), or None when the
        zubao group misses (the jar returns null and the caller faults;
        unreachable: every shipped sub rolls a configured @pozhen group).
        """
        level = self._task_role_level(role)
        jb = level * sub['jb'] + sub['jb1']
        exp = level * sub['exp'] + sub['exp1']
        zhenqi = level * sub['zhenqi'] + sub['zhenqi1']
        try:
            buff_live = row.get('expire_time') is not None and \
                int(row.get('expire_time') or 0) > int(time.time() * 1000)
        except (TypeError, ValueError):
            buff_live = False
        if buff_live:
            try:
                rate = float(row.get('award_rate')
                             if row.get('award_rate') is not None else 1.0)
            except (TypeError, ValueError):
                rate = 1.0
            jb = int(jb * rate)
            exp = int(exp * rate)
        odds = self._pozhen_roll(sub.get('zubao_id'))
        if odds is None:
            return None
        goods_id, count = odds
        item_vo = [goods_id, count]
        extra = []
        if jb > 0:
            try:
                total = int(role.get('tongqian') or 0) + jb
            except (TypeError, ValueError):
                total = jb
            try:
                self.save_role_state(rid, tongqian=total)
            except Exception:
                pass
        if exp > 0:
            try:
                _total, _level, _gained, exp_frames = \
                    self._role_gain_exp(role, rid, exp)
                extra.extend(exp_frames)
            except Exception:
                pass
        if zhenqi > 0:
            try:
                total = int(role.get('zhenqi') or 0) + zhenqi
            except (TypeError, ValueError):
                total = zhenqi
            try:
                self.save_role_state(rid, zhenqi=total)
            except Exception:
                pass
        try:
            self._task_grant(rid, [{'goods_id': goods_id,
                                    'count': count}])
        except Exception:
            pass
        return [jb, exp, zhenqi, item_vo], extra

    def _pozhen_roll(self, zubao_id):
        """rollZubaoId: one componentRoll draw, or None when unconfigured."""
        if self.config is None or not zubao_id:
            return None
        try:
            from game import juqing as juqing_lib
        except Exception:
            return None
        try:
            table = self.config.zubao_table()
        except Exception:
            return None
        try:
            entry = juqing_lib.component_roll(table, str(zubao_id))
        except Exception:
            return None
        if entry is None:
            return None
        return [entry[0], entry[1]]

    def _pozhen_compute_n_awards(self, role, rid, row, times, loc):
        """computeNTimesAward: grant `times` cells past the cursor.

        The jar feeds the cumulative elapsed count with an advancing
        cursor, so a second mid-sweep poll grants from the moved cursor
        again; reproduced verbatim (pinned by tests). Returns
        ([entries], level-up frames) or None when times is 0.
        """
        if not times:
            return None
        sd = row.get('sd_main_id') or 0
        try:
            start = int(loc.get(sd) or 0)
        except (TypeError, ValueError):
            start = 0
        out, extra = [], []
        idx = start + 1
        while idx <= start + times:
            sub = self.config.pozhen_sub(sd, idx)
            if sub is None:
                break
            award = self._pozhen_win_and_add(role, rid, sub, row)
            if award is None:
                break
            result, frames = award
            extra.extend(frames)
            self._pozhen_decr(row, rid, 1)
            out.append([result[3], result[1], result[0], result[2], idx])
            loc[sd] = idx
            idx += 1
        row['locations'] = self._pozhen_loc_str(loc)
        if not out:
            return None
        return out, extra

    def _pozhen_sao_dang_online(self, role, rid, row):
        """saoDangOnline: advance an active sweep by elapsed time.

        Returns {'times', 'awards', 'single', 'total'} or None. An
        elapsed sweep settles offline (in_mopup cleared) but its awards
        still grant here, exactly like the jar.
        """
        if not row.get('max_location'):
            return None
        try:
            if int(row.get('in_mopup') or 0) != 1:
                return None
        except (TypeError, ValueError):
            return None
        try:
            if int(row.get('can_use_count') or 0) <= 0:
                row['in_mopup'] = 0
                return None
        except (TypeError, ValueError):
            row['in_mopup'] = 0
            return None
        sd = row.get('sd_main_id') or 0
        try:
            sd = int(sd)
        except (TypeError, ValueError):
            sd = 0
        loc = self._pozhen_loc_map(row.get('locations'))
        cur = self._pozhen_split(row.get('max_location'))
        cfg = self.config.pozhen_layer(sd)
        if sd == cur[0]:
            remaining = cur[1] - (loc.get(sd) or 0)
        elif cfg is None:
            remaining = 0
        else:
            remaining = cfg['max'] - (loc.get(sd) or 0)
        try:
            have = int(row.get('can_use_count') or 0)
        except (TypeError, ValueError):
            have = 0
        if remaining > have:
            remaining = have
        if remaining <= 0:
            row['in_mopup'] = 0
            return None
        single = self._pozhen_sweep_ms(rid)
        inner = {'times': remaining, 'awards': None, 'single': single,
                 'total': 0}
        if single > 0:
            now = int(time.time() * 1000)
            try:
                mop = int(row.get('mopup_time') or 0)
            except (TypeError, ValueError):
                mop = 0
            elapsed = now - mop
            full = single * remaining
            if elapsed > full:
                row['in_mopup'] = 0
            else:
                done = elapsed // single
                rest = elapsed % single
                if rest > 0:
                    total = (remaining - done - 1) * single + \
                        (single - rest)
                else:
                    total = (remaining - done) * single
                if single > total:
                    inner['single'] = total
                inner['total'] = total
                remaining = done
        computed = self._pozhen_compute_n_awards(
            role, rid, row, remaining, loc)
        if computed is not None:
            awards, extra = computed
            inner['awards'] = awards
            inner['extra'] = extra
        return inner

    def _pozhen_two_times(self, row, rid):
        """computeTwoTimes: [single, remaining total, sweepable count]."""
        sd = row.get('sd_main_id') or 0
        try:
            sd = int(sd)
        except (TypeError, ValueError):
            sd = 0
        loc = self._pozhen_loc_map(row.get('locations'))
        single = self._pozhen_sweep_ms(rid)
        cur = self._pozhen_split(row.get('max_location'))
        cfg = self.config.pozhen_layer(sd)
        stored = loc.get(sd)
        count = 0
        if stored is not None:
            if sd == cur[0]:
                if stored < cur[1]:
                    count = cur[1] - stored
            elif cfg is not None and stored < cfg['max']:
                count = cfg['max'] - stored
        try:
            have = int(row.get('can_use_count') or 0)
        except (TypeError, ValueError):
            have = 0
        if count > have:
            count = have
        return [single, single * count, count]

    @staticmethod
    def _pozhen_remain_minutes(row, total):
        """computeRemainMinutes: ceil down to whole minutes, plus one."""
        now = int(time.time() * 1000)
        try:
            mop = int(row.get('mopup_time') or 0)
        except (TypeError, ValueError):
            mop = 0
        elapsed = now - mop
        minutes = 0
        if elapsed < total:
            minutes = (total - elapsed) // 60000
            if minutes > 0:
                minutes += 1
        return int(minutes)

    def _pozhen_check_can_saodang(self, row, main_id):
        """checkCanSaoDang: error code or None when a sweep may start."""
        if row is None:
            return POZHEN_ERR_LEVEL_LESS
        try:
            if int(row.get('can_use_count') or 0) <= 0:
                return POZHEN_ERR_DIANSHU_LESS
        except (TypeError, ValueError):
            return POZHEN_ERR_DIANSHU_LESS
        cur = self._pozhen_split(row.get('max_location'))
        if main_id > cur[0]:
            return POZHEN_ERR_YUEJI
        cfg = self.config.pozhen_layer(main_id)
        if cfg is None:
            return POZHEN_ERR_NOT_EXIST
        loc = self._pozhen_loc_map(row.get('locations'))
        if main_id not in loc:
            return POZHEN_ERR_CANNT_SD
        if main_id == cur[0]:
            limit = cur[1]
        else:
            limit = cfg['max']
        if loc[main_id] >= limit:
            return POZHEN_ERR_TOP
        try:
            if int(row.get('in_mopup') or 0) == 1:
                return POZHEN_ERR_SAODANGING
        except (TypeError, ValueError):
            pass
        return None

    def pozhen_info(self):
        """Command 48001: formation panel (progress, bar, sweep state)."""
        if self.config is None:
            return None
        role, rid = self._pozhen_role()
        if role is None:
            return None
        try:
            row = self.get_role_pozhen(rid)
        except Exception:
            row = None
        if row is None:
            if self._task_role_level(role) < \
                    self.config.pozhen_open_level():
                return frame(amf3_encode(
                    ['48001', [0, POZHEN_ERR_LEVEL_LESS]]))
            row = self._pozhen_create(
                rid, self._pozhen_vip_max(rid))
        else:
            row = dict(row)
        inner = self._pozhen_sao_dang_online(role, rid, row)
        self._pozhen_save(rid, row)
        self._pozhen_online(row, rid, self._pozhen_vip_max(rid))
        try:
            can_use = int(row.get('can_use_count') or 0)
        except (TypeError, ValueError):
            can_use = 0
        vip_max = self._pozhen_vip_max(rid)
        countdown = 0
        if can_use < vip_max:
            try:
                rec = int(row.get('recovery_time') or 0)
            except (TypeError, ValueError):
                rec = 0
            countdown = self.config.pozhen_recovery_ms() - \
                (int(time.time() * 1000) - rec)
        cur = self._pozhen_cal_cur(row)
        awards = inner.get('awards') if inner else None
        times = None
        if inner:
            times = [inner['single'], inner['total']]
        extra = (inner.get('extra') or []) if inner else []
        reply = [1, [cur[0], cur[1],
                      self._pozhen_loc_map(row.get('locations')), 0,
                      can_use, row.get('buy_count'),
                      row.get('refresh_count'), awards, times, vip_max,
                      countdown]]
        main = frame(amf3_encode(['48001', reply]))
        if extra:
            return (main, *extra)
        return main

    def pozhen_start(self, msg):
        """Command 48002: challenge one formation cell for a point."""
        if self.config is None:
            return None
        try:
            data = msg[1] if isinstance(msg, list) and len(msg) > 1 \
                else None
            main_id, idx = int(data[0]), int(data[1])
        except (TypeError, ValueError, IndexError):
            return None
        if main_id < 0 or idx < 0:
            return None
        role, rid = self._pozhen_role()
        if role is None:
            return None
        try:
            row = self.get_role_pozhen(rid)
        except Exception:
            row = None
        row = dict(row) if row else None
        err = self._pozhen_check_can(row, main_id, idx)
        if err is not None:
            return frame(amf3_encode(['48002', [0, err]]))
        cfg = self.config.pozhen_layer(main_id)
        sub = self.config.pozhen_sub(main_id, idx)
        self._pozhen_decr(row, rid, 1)
        cur = self._pozhen_split(row.get('max_location'))
        if main_id > cur[0] or (main_id == cur[0] and idx > cur[1]):
            row['max_location'] = f'{main_id}-{idx}'
        if main_id == cur[0] and idx == cfg['max'] and \
                sub['num'] >= cfg['max']:
            # S:PZATT: the stage side recalculates fight power from the
            # cleared layer. Python recomputes 12010 live (see
            # fighting_info), so no extra frame is emitted here.
            pass
        loc = self._pozhen_loc_map(row.get('locations'))
        loc[main_id] = idx
        row['locations'] = self._pozhen_loc_str(loc)
        self._pozhen_save(rid, row)
        return None

    def pozhen_saodang(self, msg):
        """Command 48003: open a timed sweep over a cleared layer."""
        if self.config is None:
            return None
        try:
            data = msg[1] if isinstance(msg, list) and len(msg) > 1 \
                else None
            main_id = int(data)
        except (TypeError, ValueError):
            return None
        if data is None:
            return None
        role, rid = self._pozhen_role()
        if role is None:
            return None
        try:
            row = self.get_role_pozhen(rid)
        except Exception:
            row = None
        row = dict(row) if row else None
        err = self._pozhen_check_can_saodang(row, main_id)
        if err is not None:
            return frame(amf3_encode(['48003', [0, err]]))
        now = int(time.time() * 1000)
        row['in_mopup'] = 1
        row['sd_main_id'] = main_id
        row['mopup_time'] = now
        self._pozhen_save(rid, row)
        single, total, _count = self._pozhen_two_times(row, rid)
        return frame(amf3_encode(['48003', [1, single, total]]))

    def pozhen_move(self, msg):
        """Command 48005: formation cursor view for one layer."""
        if self.config is None:
            return None
        try:
            data = msg[1] if isinstance(msg, list) and len(msg) > 1 \
                else None
            loc_arg = int(data)
        except (TypeError, ValueError):
            return None
        if data is None or loc_arg <= 0:
            return None
        role, rid = self._pozhen_role()
        if role is None:
            return None
        try:
            row = self.get_role_pozhen(rid)
        except Exception:
            row = None
        if row is None:
            return frame(amf3_encode(
                ['48005', [0, POZHEN_ERR_LEVEL_LESS]]))
        row = dict(row)
        cur = self._pozhen_split(row.get('max_location'))
        loc = self._pozhen_loc_map(row.get('locations'))
        if loc_arg in loc:
            idx = loc[loc_arg]
        elif loc_arg == cur[0]:
            idx = cur[1]
        elif loc_arg < cur[0]:
            cfg = self.config.pozhen_layer(loc_arg)
            idx = cfg['max'] if cfg is not None else 0
        else:
            idx = 0
        return frame(amf3_encode(
            ['48005', [1, loc_arg, idx,
                        self._pozhen_sweep_ms(rid)]]))

    def pozhen_refresh(self):
        """Command 48004: reset cleared cells for YB (charged twice)."""
        if self.config is None:
            return None
        role, rid = self._pozhen_role()
        if role is None:
            return None
        try:
            row = self.get_role_pozhen(rid)
        except Exception:
            row = None
        row = dict(row) if row else None
        try:
            made = int((row or {}).get('refresh_count') or 0)
        except (TypeError, ValueError):
            made = 0
        cfg = self.config.pozhen_shuaxin(made + 1)
        err = self._pozhen_check_can_refresh(row, cfg, role)
        if err is not None:
            return frame(amf3_encode(['48004', [0, err]]))
        made += 1
        row['refresh_count'] = made
        cur = self._pozhen_split(row.get('max_location'))
        row['locations'] = self._pozhen_loc_str(
            {layer: 0 for layer in range(1, cur[0] + 1)})
        # The jar decr()s the refresh gold twice (once for the event
        # payload, once for the charge); the double spend is reproduced
        # here and pinned by tests.
        self._bag_money_decr(rid, 'YB', cfg['refresh_gold'])
        self._pozhen_save(rid, row)
        self._bag_money_decr(rid, 'YB', cfg['refresh_gold'])
        return frame(amf3_encode(['48004', [1, made]]))

    def _pozhen_check_can_refresh(self, row, cfg, role):
        """checkCanRefresh: error code or None for a refresh attempt."""
        if row is None:
            return POZHEN_ERR_LEVEL_LESS
        if cfg is None:
            return POZHEN_ERR_FULL_BUY
        if not self._bag_money_check(role, 'YB', cfg['refresh_gold']):
            return POZHEN_ERR_YB_SHORT
        if self._task_role_level(role) < cfg['refresh_level']:
            return POZHEN_ERR_LEVEL_GATE
        return None

    def pozhen_buy(self):
        """Command 48006: buy one formation point for YB."""
        if self.config is None:
            return None
        role, rid = self._pozhen_role()
        if role is None:
            return None
        try:
            row = self.get_role_pozhen(rid)
        except Exception:
            row = None
        if row is None:
            return frame(amf3_encode(
                ['48006', [0, POZHEN_ERR_LEVEL_LESS]]))
        row = dict(row)
        try:
            can_use = int(row.get('can_use_count') or 0)
        except (TypeError, ValueError):
            can_use = 0
        vip_max = self._pozhen_vip_max(rid)
        if can_use >= vip_max:
            return frame(amf3_encode(
                ['48006', [0, POZHEN_ERR_FULL_COUNT]]))
        try:
            bought = int(row.get('buy_count') or 0) + 1
        except (TypeError, ValueError):
            bought = 1
        cfg = self.config.pozhen_shuaxin(bought)
        if cfg is None:
            return frame(amf3_encode(
                ['48006', [0, POZHEN_ERR_FULL_BUY]]))
        if self._task_role_level(role) < cfg['buy_level']:
            return frame(amf3_encode(
                ['48006', [0, POZHEN_ERR_LEVEL_GATE]]))
        if not self._bag_money_check(role, 'YB', cfg['buy_gold']):
            return frame(amf3_encode(['48006', [0, POZHEN_ERR_YB_SHORT]]))
        self._bag_money_decr(rid, 'YB', cfg['buy_gold'])
        can_use += 1
        row['can_use_count'] = can_use
        row['buy_count'] = bought
        self._pozhen_save(rid, row)
        return frame(amf3_encode(['48006', [1, can_use, bought, 0]]))

    def pozhen_quickly(self):
        """Command 48008: instantly finish a sweep for YB per minute."""
        if self.config is None:
            return None
        role, rid = self._pozhen_role()
        if role is None:
            return None
        try:
            row = self.get_role_pozhen(rid)
        except Exception:
            row = None
        row = dict(row) if row else None
        try:
            sweeping = row is not None and \
                int(row.get('in_mopup') or 0) == 1
        except (TypeError, ValueError):
            sweeping = False
        if not sweeping:
            err = POZHEN_ERR_LEVEL_LESS if row is None \
                else POZHEN_ERR_NO_SAODANG
            return frame(amf3_encode(['48008', [0, err]]))
        single, total, count = self._pozhen_two_times(row, rid)
        cost = 0
        if total > 0:
            minutes = self._pozhen_remain_minutes(row, total)
            cost = minutes * self.config.pozhen_kill_cd_gold()
            if not self._bag_money_check(role, 'YB', cost):
                return frame(amf3_encode(
                    ['48008', [0, POZHEN_ERR_JIASU_YB_LESS, cost]]))
        if cost > 0:
            self._bag_money_decr(rid, 'YB', cost)
        cur = self._pozhen_split(row.get('max_location'))
        loc = self._pozhen_loc_map(row.get('locations'))
        computed = self._pozhen_compute_n_awards(
            role, rid, row, count, loc)
        awards = computed[0] if computed is not None else None
        extra = computed[1] if computed is not None else []
        row['in_mopup'] = 0
        self._pozhen_save(rid, row)
        reply = [1, awards, row.get('can_use_count'), 0]
        main = frame(amf3_encode(['48008', reply]))
        if extra:
            return (main, *extra)
        return main

    def _pozhen_next_saodang(self, main_id, loc, cur):
        """computeNextSaoDang: [main, stored + 1], or None at the top."""
        if main_id == cur[0]:
            limit = cur[1]
        else:
            cfg = self.config.pozhen_layer(main_id)
            if cfg is None:
                return None
            limit = cfg['max']
        stored = loc.get(main_id) or 0
        if stored >= limit:
            return None
        return [main_id, stored + 1]

    def pozhen_sdover(self):
        """Command 48007: claim one sweep cell after its timer lapses."""
        if self.config is None:
            return None
        role, rid = self._pozhen_role()
        if role is None:
            return None
        try:
            row = self.get_role_pozhen(rid)
        except Exception:
            row = None
        row = dict(row) if row else None
        if row is None:
            return frame(amf3_encode(
                ['48007', [0, POZHEN_ERR_NO_SAODANG]]))
        try:
            sweeping = int(row.get('in_mopup') or 0) == 1
        except (TypeError, ValueError):
            sweeping = False
        if not sweeping:
            return frame(amf3_encode(
                ['48007', [0, POZHEN_ERR_NO_SAODANG]]))
        try:
            if int(row.get('can_use_count') or 0) <= 0:
                return frame(amf3_encode(
                    ['48007', [0, POZHEN_ERR_DIANSHU_LESS]]))
        except (TypeError, ValueError):
            return frame(amf3_encode(
                ['48007', [0, POZHEN_ERR_DIANSHU_LESS]]))
        single = self._pozhen_sweep_ms(rid)
        now = int(time.time() * 1000)
        try:
            mop = int(row.get('mopup_time') or 0)
        except (TypeError, ValueError):
            mop = 0
        if now - mop < single:
            row['in_mopup'] = 0
            row['mopup_time'] = 0
            self._pozhen_save(rid, row)
            return frame(amf3_encode(
                ['48007', [0, POZHEN_ERR_TIME_LESS]]))
        sd = row.get('sd_main_id') or 0
        try:
            sd = int(sd)
        except (TypeError, ValueError):
            sd = 0
        loc = self._pozhen_loc_map(row.get('locations'))
        cur = self._pozhen_split(row.get('max_location'))
        nxt = self._pozhen_next_saodang(sd, loc, cur)
        if nxt is None:
            return frame(amf3_encode(['48007', [0, POZHEN_ERR_TOP]]))
        row['in_mopup'] = 0
        self._pozhen_decr(row, rid, 1)
        loc[nxt[0]] = nxt[1]
        row['locations'] = self._pozhen_loc_str(loc)
        self._pozhen_save(rid, row)
        sub = self.config.pozhen_sub(nxt[0], nxt[1])
        award = self._pozhen_win_and_add(role, rid, sub, row) \
            if sub is not None else None
        if award is None:
            return None
        result, extra = award
        inner = [[result[3], result[1], result[0], result[2]],
                 result[1], result[0], result[2],
                 row.get('can_use_count'), 0, nxt]
        main = frame(amf3_encode(['48007', [1, inner]]))
        if extra:
            return (main, *extra)
        return main

    def pozhen_recovery(self):
        """Command 48009: reclaim one point once its timer lapses."""
        if self.config is None:
            return None
        role, rid = self._pozhen_role()
        if role is None:
            return None
        try:
            row = self.get_role_pozhen(rid)
        except Exception:
            row = None
        if row is None:
            return frame(amf3_encode(
                ['48009', [0, POZHEN_ERR_LEVEL_LESS]]))
        row = dict(row)
        vip_max = self._pozhen_vip_max(rid)
        try:
            can_use = int(row.get('can_use_count') or 0)
        except (TypeError, ValueError):
            can_use = 0
        if can_use < vip_max:
            now = int(time.time() * 1000)
            try:
                rec = int(row.get('recovery_time') or 0)
            except (TypeError, ValueError):
                rec = 0
            if now - rec < self.config.pozhen_recovery_ms():
                return frame(amf3_encode(
                    ['48009', [0, POZHEN_ERR_TIME_LESS]]))
            can_use += 1
            row['can_use_count'] = can_use
            if can_use >= vip_max:
                row['recovery_time'] = 0
            else:
                row['recovery_time'] = now
            self._pozhen_save(rid, row)
        return frame(amf3_encode(['48009', [1, [can_use, 0]]]))

    def pozhen_stop(self):
        """Command 48010: abandon an active sweep, kept progress stays."""
        if self.config is None:
            return None
        role, rid = self._pozhen_role()
        if role is None:
            return None
        try:
            row = self.get_role_pozhen(rid)
        except Exception:
            row = None
        if row is None:
            return frame(amf3_encode(
                ['48010', [0, POZHEN_ERR_LEVEL_LESS]]))
        row = dict(row)
        row['in_mopup'] = 0
        row['mopup_time'] = 0
        self._pozhen_save(rid, row)
        return frame(amf3_encode(['48010', [1]]))

    def pozhen_get_goods(self, msg):
        """Command 48011: void grant of one cell award (both ids read

        from data[0], like the jar action). The service result is
        discarded, so success is silent; the grants still land.
        """
        if self.config is None:
            return None
        try:
            data = msg[1] if isinstance(msg, list) and len(msg) > 1 \
                else None
            main_id = int(data[0])
        except (TypeError, ValueError, IndexError):
            return None
        if data is None:
            return None
        role, rid = self._pozhen_role()
        if role is None:
            return None
        try:
            row = self.get_role_pozhen(rid)
        except Exception:
            row = None
        if row is None:
            return None
        row = dict(row)
        sub = self.config.pozhen_sub(main_id, main_id)
        if sub is None:
            return None
        self._pozhen_win_and_add(role, rid, sub, row)
        return None

    def pozhen_use_award_prop(self, rid, minutes, rate):
        """useAwardProp: extend the reward buff window (no inbound ID)."""
        try:
            row = self.get_role_pozhen(rid)
        except Exception:
            row = None
        if row is None:
            row = self._pozhen_create(rid, self._pozhen_vip_max(rid))
        else:
            row = dict(row)
        now = int(time.time() * 1000)
        try:
            span = int(minutes or 0) * 60000
        except (TypeError, ValueError):
            span = 0
        try:
            live = row.get('expire_time') is not None and \
                int(row.get('expire_time') or 0) > now
        except (TypeError, ValueError):
            live = False
        if live:
            row['expire_time'] = int(row.get('expire_time') or 0) + span
        else:
            row['expire_time'] = now + span
        try:
            row['award_rate'] = float(rate)
        except (TypeError, ValueError):
            row['award_rate'] = 1.0
        self._pozhen_save(rid, row)
        return None

    def pozhen_prop_expire_time(self, rid):
        """getPropExpireTime: live buff expiry millis, else 0."""
        try:
            row = self.get_role_pozhen(rid)
        except Exception:
            return 0
        if row is None:
            return 0
        try:
            exp = int(row.get('expire_time') or 0)
        except (TypeError, ValueError):
            return 0
        if exp <= int(time.time() * 1000):
            return 0
        return exp

    def pozhen_attribute_map(self, rid):
        """calPozhenAttribute: the cleared layer's attribute bag."""
        if self.config is None:
            return None
        try:
            row = self.get_role_pozhen(rid)
        except Exception:
            row = None
        cur = self._pozhen_cal_cur(dict(row) if row else {})
        return self.config.pozhen_attribute_map(cur[0], cur[1])

    # -- online gifts (HuodongAction getTimeHuodongInfo/getTimeHuodongReward
    # via OnlineGiftServiceImpl, backed by shipped kaifuzaixian.jat) --
    # Evidence: HuodongAction (94000/94001, null 94001 reply stays silent),
    # OnlineGiftServiceImpl (getHuodongInfo/getReward/online/logout +
    # isNotEmptyAndNoEnd/isToday/initToday/getremainderTime/getRewardArray/
    # resetToNext/reSetLoginTime/resetRemainderTime), OnlineGiftConfig
    # (id/minute=online seconds/time=kaifu day/nextId/jiangli) grouped into
    # OnlineGiftDayConfigs by kaifu day with file-order nextId chains,
    # RoleOnlineHuodongOutput ([[goodsId, count]] pairs) and the
    # HuodongRoleLoginEventHandler/HuodongRoleLogoutEventHandler wiring.
    HUODONG_GIFT_KEY = 'online_gift'

    @staticmethod
    def _huodong_json(text):
        """Fastjson object map of a counter JSON string; {} when absent."""
        if not text:
            return {}
        try:
            val = json.loads(text)
        except (TypeError, ValueError):
            return {}
        return val if isinstance(val, dict) else {}

    def _huodong_row(self, rid):
        """Role's activity row, created empty like initRoleHuodong."""
        try:
            row = self.get_role_huodong(rid)
        except Exception:
            row = None
        if row is not None:
            return dict(row)
        try:
            self.save_role_huodong(rid, max_count='')
        except Exception:
            return None
        try:
            row = self.get_role_huodong(rid)
        except Exception:
            row = None
        return dict(row) if row is not None else None

    def _huodong_gift_get(self, row):
        """The online_gift state object, or None (getValue str overload)."""
        state = self._huodong_json((row or {}).get('max_count')).get(
            self.HUODONG_GIFT_KEY)
        return dict(state) if isinstance(state, dict) else None

    def _huodong_gift_save(self, rid, row, state):
        """Persist the online_gift state object (setValue str overload)."""
        try:
            counters = self._huodong_json((row or {}).get('max_count'))
            counters[self.HUODONG_GIFT_KEY] = dict(state)
            self.save_role_huodong(rid, max_count=json.dumps(counters))
            row['max_count'] = json.dumps(counters)
        except Exception:
            pass

    @staticmethod
    def _huodong_kaifu_day(created):
        """twoDaysDiffence(role.createTime)+1, date-based like Java."""
        try:
            born = datetime.date.fromtimestamp(int(created or 0))
        except (TypeError, ValueError, OverflowError, OSError):
            born = datetime.date.today()
        try:
            return (datetime.date.today() - born).days + 1
        except Exception:
            return 1

    def _huodong_gift_config(self, cid):
        """Day bucket + config entry for a gift id, or (None, None)."""
        if self.config is None or cid is None:
            return None, None
        try:
            days = self.config.online_gift_days()
        except Exception:
            return None, None
        for bucket in (days or {}).values():
            cfg = bucket.get('configs', {}).get(str(cid))
            if cfg is not None:
                return bucket, cfg
        return None, None

    @staticmethod
    def _huodong_live(state):
        """isNotEmptyAndNoEnd: state present and no end marker."""
        return state is not None and 'end' not in state

    @staticmethod
    def _huodong_today(state, kaifu_day):
        """isToday: state's kaifu day matches."""
        if state is None:
            return False
        try:
            return int(state.get('day')) == int(kaifu_day)
        except (TypeError, ValueError):
            return False

    def _huodong_init_today(self, rid, row, kaifu_day):
        """initToday: fresh {day, id, logintime, minute} or {day, end}."""
        now = int(time.time() * 1000)
        try:
            bucket = (self.config.online_gift_days()
                      if self.config is not None else None).get(
                          int(kaifu_day))
        except (TypeError, ValueError, AttributeError):
            bucket = None
        if bucket is None:
            state = {'day': kaifu_day, 'end': 'end'}
        else:
            cfg = bucket['configs'].get(str(bucket.get('start_id')))
            if cfg is None:
                state = {'day': kaifu_day, 'end': 'end'}
            else:
                state = {'day': kaifu_day, 'id': str(cfg['id']),
                         'logintime': now,
                         'minute': int(cfg.get('minute') or 0) * 1000}
        self._huodong_gift_save(rid, row, state)
        return state

    @staticmethod
    def _huodong_remainder_ms(state, now_ms):
        """getremainderTime: banked ms minus elapsed session, floor 0."""
        try:
            banked = int(state.get('minute') or 0)
        except (TypeError, ValueError):
            banked = 0
        try:
            elapsed = int(now_ms) - int(state.get('logintime') or 0)
        except (TypeError, ValueError):
            elapsed = 0
        return max(0, banked - max(0, elapsed))

    def _huodong_reward_array(self, state):
        """getRewardArray: current gift's [[goodsId, count]] or None."""
        _, cfg = self._huodong_gift_config((state or {}).get('id'))
        if cfg is None:
            return None
        return [[gid, count] for gid, count, _bind in cfg.get('jiangli') or []]

    def _huodong_reset_next(self, rid, row, state):
        """resetToNext: advanced state, or None when the ladder ends."""
        now = int(time.time() * 1000)
        _, cur = self._huodong_gift_config((state or {}).get('id'))
        nxt = (cur or {}).get('next_id')
        if nxt is not None:
            _, cfg = self._huodong_gift_config(nxt)
            if cfg is not None:
                advanced = {
                    'day': cfg.get('day'), 'id': str(cfg['id']),
                    'logintime': now,
                    'minute': int(cfg.get('minute') or 0) * 1000}
                self._huodong_gift_save(rid, row, advanced)
                return advanced
        ended = dict(state or {})
        ended['end'] = 'end'
        self._huodong_gift_save(rid, row, ended)
        return None

    def _huodong_role_day(self, rid):
        """(role, kaifu_day) for online-gift progress, or (None, None)."""
        try:
            roles = self.get_roles(self.authed_user or '',
                                   self.server_id or '')
        except Exception:
            return None, None
        role = _find_role(roles or [], rid)
        if role is None:
            if len(roles or []) == 1:
                role = roles[0]
            else:
                return None, None
        return role, self._huodong_kaifu_day(role.get('created'))

    def _huodong_on_enter(self, rid):
        """HuodongRoleLoginEventHandler: refresh logintime or re-init day."""
        role, kaifu_day = self._huodong_role_day(rid)
        if role is None:
            return
        row = self._huodong_row(_wire_id(role))
        if row is None:
            return
        state = self._huodong_gift_get(row)
        now = int(time.time() * 1000)
        if state is not None and self._huodong_today(state, kaifu_day):
            state['logintime'] = now
            self._huodong_gift_save(_wire_id(role), row, state)
        else:
            self._huodong_init_today(_wire_id(role), row, kaifu_day)

    def _huodong_logout_role(self, role, now_ms):
        """Logout half of HuodongRoleLogoutEventHandler for one role."""
        try:
            rid = _wire_id(role)
            row = self._huodong_row(rid)
        except Exception:
            return
        if row is None:
            return
        kaifu_day = self._huodong_kaifu_day(role.get('created'))
        state = self._huodong_gift_get(row)
        if not self._huodong_live(state):
            return
        if self._huodong_today(state, kaifu_day):
            state['minute'] = self._huodong_remainder_ms(state, now_ms)
            self._huodong_gift_save(rid, row, state)
        else:
            self._huodong_init_today(rid, row, kaifu_day)

    def _huodong_on_disconnect(self):
        """HuodongRoleLogoutEventHandler: bank the session remainder."""
        try:
            roles = self.get_roles(self.authed_user or '',
                                   self.server_id or '')
        except Exception:
            return
        now = int(time.time() * 1000)
        for role in roles or []:
            self._huodong_logout_role(role, now)

    def _huodong_active(self):
        """Live online-gift state for the requester's role, or None."""
        role, kaifu_day = self._huodong_role_day(None)
        if role is None:
            return None, None, None, None
        rid = _wire_id(role)
        row = self._huodong_row(rid)
        if row is None:
            return None, None, None, None
        state = self._huodong_gift_get(row)
        if not self._huodong_live(state):
            return role, rid, row, None
        if not self._huodong_today(state, kaifu_day):
            state = self._huodong_init_today(rid, row, kaifu_day)
        return role, rid, row, state

    def huodong_online_info(self):
        """Command 94000: [1, remainderMs, [[goodsId, count]...]]."""
        role, rid, row, state = self._huodong_active()
        if state is None:
            return None
        now = int(time.time() * 1000)
        arr = self._huodong_reward_array(state)
        if arr is None:
            return None
        return frame(amf3_encode(
            [str(CMD_HUODONG_ONLINE_INFO),
             [1, self._huodong_remainder_ms(state, now), arr]]))

    def huodong_online_reward(self):
        """Command 94001: claim the matured online gift, then advance."""
        role, rid, row, state = self._huodong_active()
        if state is None:
            return frame(amf3_encode(
                [str(CMD_HUODONG_ONLINE_REWARD), [0, HUODONG_ERR_NO_GIFT]]))
        now = int(time.time() * 1000)
        if self._huodong_remainder_ms(state, now) > 0:
            return frame(amf3_encode(
                [str(CMD_HUODONG_ONLINE_REWARD),
                 [2, self._huodong_remainder_ms(state, now),
                  HUODONG_ERR_NOT_YET]]))
        arr = self._huodong_reward_array(state)
        if arr is None:
            arr = []
        _, cfg = self._huodong_gift_config(state.get('id'))
        parcels = (cfg or {}).get('jiangli') or []
        if not self._vip_fits_list(rid, parcels):
            return frame(amf3_encode(
                [str(CMD_HUODONG_ONLINE_REWARD), [0, BAG_ERR_SLOT_LESS]]))
        self._task_grant(rid, self._vip_parcel_items(parcels))
        advanced = self._huodong_reset_next(rid, row, state)
        if advanced is None:
            return frame(amf3_encode(
                [str(CMD_HUODONG_ONLINE_REWARD), [1, -1, arr]]))
        return frame(amf3_encode(
            [str(CMD_HUODONG_ONLINE_REWARD),
             [1, self._huodong_remainder_ms(advanced, now), arr]]))

    # First-recharge lifecycle (zonghe clienttype 21: HuodongAction
    # getRechargeInfo/lingquRechargeReward -> HuodongServiceImpl
    # getFirstRechargeInfo/lingquFirstRechargeReward ->
    # RoleHuodongOutputWrapper.firstrecharge for the 70000 display
    # array). State rides the role_huodong max_count JSON map under
    # 'zonghe_first' as {'charged': 0/1, 'claimed': [activity ids]},
    # mirroring the jar's getValue/setValue helpers and the
    # online_gift precedent.
    HUODONG_FIRST_KEY = 'zonghe_first'

    def _zonghe_first_get(self, row):
        """The zonghe_first state object, or None."""
        state = self._huodong_json((row or {}).get('max_count')).get(
            self.HUODONG_FIRST_KEY)
        return dict(state) if isinstance(state, dict) else None

    def _zonghe_first_save(self, rid, row, state):
        """Persist the zonghe_first state object."""
        try:
            counters = self._huodong_json((row or {}).get('max_count'))
            counters[self.HUODONG_FIRST_KEY] = dict(state)
            self.save_role_huodong(rid, max_count=json.dumps(counters))
            row['max_count'] = json.dumps(counters)
        except Exception:
            pass

    def _zonghe_first_live(self, now_ms):
        """(category, activity) for the live first-recharge row, or None.

        Earliest-ending live category wins, file order breaking ties;
        the snapshot windows for one server do not overlap in practice.
        """
        if self.config is None:
            return None
        try:
            kaifu = int(self.server_start_ms or 0)
        except (TypeError, ValueError):
            kaifu = 0
        try:
            live = self.config.zonghe_live(
                self.config.ZONGHE_FIRST_RECHARGE, kaifu_ms=kaifu,
                now_ms=now_ms)
        except Exception:
            return None
        if not live:
            return None
        live.sort(key=lambda pair: (pair[0].get('end_ms') or 0,
                                    pair[0].get('id') or ''))
        return live[0]

    def zonghe_recharge(self, role, yb, now_ms=None):
        """Recharge hook: latch 'charged', push 71002 [activityId, yb, 1]
        when a first-recharge category is live. Non-positive amounts
        stay silent."""
        if role is None:
            return []
        try:
            amount = int(yb or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            return []
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        try:
            rid = _wire_id(role)
            row = self._huodong_row(rid)
        except Exception:
            return []
        if row is None:
            return []
        state = self._zonghe_first_get(row) or {}
        state['charged'] = 1
        state.setdefault('claimed', [])
        self._zonghe_first_save(rid, row, state)
        found = self._zonghe_first_live(now_ms)
        if found is None:
            return []
        _cat, act = found
        return self._vip_push(
            role, [frame(amf3_encode(
                ['71002', [act.get('id'), amount, 1]]))])

    def _zonghe_first_grantable(self, role, parcels):
        """Award parcels passing GoodsJobFilter (job '0' or the role's job;
        unknown/job-mismatched goods drop, like the jar)."""
        job = str(role.get('job') or '')
        grant = []
        for gid, count, bind in parcels or []:
            try:
                gate = self.config.goods_job(gid)
            except Exception:
                continue
            if gate != '0' and gate != job:
                continue
            grant.append((gid, count, bind))
        return grant

    def _zonghe_first_mount(self, role, rid, now_ms):
        """changeZuoqiRank(roleId, 3): ranks below 3 rise to 3 and push
        the 33004 [1, 3, level] frame; rank 3+ pushes nothing."""
        try:
            row = self._zuoqi_row(rid)
        except Exception:
            row = None
        if row is None:
            return None
        try:
            rank = int(row.get('zuoqi_rank') or 0)
        except (TypeError, ValueError):
            rank = 0
        if rank >= 3:
            return None
        try:
            row.update(zuoqi_rank=3, zuoqi_cur_rank=3,
                       update_time=int(now_ms))
            self._zuoqi_save(rid, row)
            cfg = self.config.zuoqi_rank_config(self.ZUOQI_MIN_RANK)
        except Exception:
            return None
        level = self._zuoqi_level(self._task_role_level(role), cfg) \
            if cfg is not None else 0
        return frame(amf3_encode([str(CMD_ZUOQI_CLAIM), [1, 3, level]]))

    def _zonghe_first_claim_full(self, role, now_ms=None):
        """Claim core (lingquFirstRechargeReward): (True, {'pairs',
        'act_id', 'mount'}) on success, else (False, reason) with
        'no_live'/'claimed'/'uncharged'/'bag_full'. Currency/meiren
        grants only run for non-zero configs (none in fu0)."""
        if role is None or self.config is None:
            return (False, 'no_live')
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        try:
            rid = _wire_id(role)
            row = self._huodong_row(rid)
        except Exception:
            return (False, 'no_live')
        if row is None:
            return (False, 'no_live')
        found = self._zonghe_first_live(now_ms)
        if found is None:
            return (False, 'no_live')
        _cat, act = found
        state = self._zonghe_first_get(row) or {}
        claimed = state.get('claimed') or []
        if act.get('id') in claimed:
            return (False, 'claimed')
        if not state.get('charged'):
            return (False, 'uncharged')
        parcels = act.get('parcels') or []
        if not self._vip_fits_list(rid, parcels):
            return (False, 'bag_full')
        grant = self._zonghe_first_grantable(role, parcels)
        self._task_grant(rid, self._vip_parcel_items(grant))
        mount = self._zonghe_first_mount(role, rid, now_ms)
        state['claimed'] = list(claimed) + [act.get('id')]
        self._zonghe_first_save(rid, row, state)
        return (True, {'pairs': [[gid, count]
                                 for gid, count, _bind in grant],
                       'act_id': act.get('id'), 'mount': mount})

    def _zonghe_first_info(self, role, now_ms=None):
        """70000 payload: None when no category is live, [0, 792005]
        when gated, else the 13-slot firstrecharge array
        ([configId, title, state, [mm, mmEffect], startMs, endMs,
        needPayYb, claimedCount, [jb, lijin, zhenqi, shengwang, exp,
        items], jiemian, anniu, chufa, categoryTitle]; items are
        [goodsId, count, bind, hours, [qinghua, qianghua], rare,
        fjid], state 2/1/0 claimed/charged/otherwise)."""
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        found = self._zonghe_first_live(now_ms)
        if found is None:
            return None
        cat, act = found
        try:
            rid = _wire_id(role)
            row = self._huodong_row(rid)
        except Exception:
            row = None
        state = (self._zonghe_first_get(row)
                 if row is not None else None) or {}
        try:
            level = int((role or {}).get('level') or 0)
        except (TypeError, ValueError):
            level = 0
        try:
            need_level = int(act.get('need_level') or 0)
        except (TypeError, ValueError):
            need_level = 0
        try:
            need_pay = int(act.get('need_pay_yb') or 0)
        except (TypeError, ValueError):
            need_pay = 0
        if level < need_level or \
                (need_pay > 0 and not state.get('charged')):
            return [0, HUODONG_ERR_FIRST_NO_CONFIG]
        claimed = act.get('id') in (state.get('claimed') or [])
        if claimed:
            status, claimed_count = 2, 1
        elif state.get('charged'):
            status, claimed_count = 1, 0
        else:
            status, claimed_count = 0, 0
        currencies = act.get('currencies') or {}
        items = [[it['goods_id'], it['count'], it['bind'],
                  it['hours'], [it['qinghua'], it['qianghua']],
                  it['rare'], it['fjid']]
                 for it in act.get('award_items') or []]
        return [act.get('id'), act.get('cfg_title') or '', status,
                [act.get('cfg_mm') or '', act.get('cfg_mmeffect') or ''],
                cat.get('start_ms') or 0, cat.get('end_ms') or 0,
                need_pay, claimed_count,
                [currencies.get('jb') or 0,
                 currencies.get('lijin') or 0,
                 currencies.get('zhenqi') or 0,
                 currencies.get('shengwang') or 0,
                 currencies.get('exp') or 0, items],
                act.get('cfg_jiemian') or '',
                act.get('cfg_anniu') or '',
                act.get('cfg_chufa') or '',
                cat.get('title') or '']

    def huodong_first_info(self, msg=None, now_ms=None):
        """Command 70000: the first-recharge panel for the live row."""
        roles = self.get_roles(self.authed_user or '',
                               self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        return frame(amf3_encode(
            [str(CMD_HUODONG_FIRST_INFO),
             self._zonghe_first_info(role, now_ms=now_ms)]))

    def huodong_first_reward(self, msg=None, now_ms=None):
        """Command 70001: [1, configId] on success (33004 mount frame
        first when the mount rank rose), else [0, code]."""
        roles = self.get_roles(self.authed_user or '',
                               self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        ok, res = self._zonghe_first_claim_full(role, now_ms=now_ms)
        if not ok:
            code = {'no_live': HUODONG_ERR_FIRST_NO_CONFIG,
                    'claimed': HUODONG_ERR_FIRST_CLAIMED,
                    'uncharged': HUODONG_ERR_FIRST_UNCHARGED,
                    'bag_full': BAG_ERR_SLOT_LESS}.get(res, 0)
            return frame(amf3_encode(
                [str(CMD_HUODONG_FIRST_REWARD), [0, code]]))
        out = []
        if res.get('mount') is not None:
            out.append(res['mount'])
        out.append(frame(amf3_encode(
            [str(CMD_HUODONG_FIRST_REWARD), [1, res['act_id']]])))
        return out if len(out) > 1 else out[0]

    # Mount panel/ride/claim (zuoqi 33001/33000/33004). Evidence:
    # ZuoQiAction (ZuoqiMianban/rideZuoQi/lingquZuoqi) and
    # RoleZuoQiServiceImpl (getZuoQiPannel/rideZuoqi/changeZuoqiRank).
    ZUOQI_MIN_RANK = 1
    ZUOQI_EMPTY_CODE = 520005
    ZUOQI_NOCONFIG_CODE = 520006
    ZUOQI_MAX_CODE = 520001
    ZUOQI_LEVEL_CODE = 520002
    ZUOQI_MONEY_CODE = 520003
    ZUOQI_MALL_FAIL = 430249
    ZUOQI_TRY_FAIL = 430250
    ZUOQI_NOTICE_CODE = 520013
    ZUOQI_FANHUAN_STATE = 520020
    ZUOQI_MEIREN_STATE = 520021
    ZUOQI_FANHUAN_CLAIMED = 520022
    ZUOQI_MEIREN_CLAIMED = 520023
    ZUOQI_KAIFU_OVER = 520024

    def _zuoqi_row(self, rid):
        """Role's mount row, created zeroed like createRoleZuoqi, or None."""
        try:
            row = self.get_role_zuoqi(rid)
        except Exception:
            row = None
        if row is not None:
            return dict(row)
        row = {'zuoqi_rank': 0, 'zuoqi_cur_rank': 0, 'lucky_value': 0,
               'update_time': 0, 'fail_count': 0, 'total_exp': 0,
               'free_jb': 0, 'lucky_goods_id': None,
               'lucky_goods_expire_time': 0, 'add_lucky_value': 0,
               'kaifu_data': None, 'attribute_goods_id': None}
        try:
            self.save_role_zuoqi(rid, 0, 0, 0, 0, 0, 0, 0, None, 0, 0, None)
        except Exception:
            return None
        return row

    def _zuoqi_save(self, rid, row):
        """Persist a mount row dict under its role id."""
        try:
            self.save_role_zuoqi(
                rid, row.get('zuoqi_rank'), row.get('zuoqi_cur_rank'),
                row.get('lucky_value'), row.get('update_time'),
                row.get('fail_count'), row.get('total_exp'),
                row.get('free_jb'), row.get('lucky_goods_id'),
                row.get('lucky_goods_expire_time'),
                row.get('add_lucky_value'), row.get('kaifu_data'),
                row.get('attribute_goods_id'))
        except Exception:
            pass

    def _zuoqi_timer(self, rid, row):
        """timerTask: same-day rows pass; else the blessing resets.

        historyLucky/historyCount/failCount/totalExp and the zhufu-ka
        prop clear live in unmigrated columns/services, so only the
        observable part ports: a stale update day zeroes the blessing
        when the rank's luckyClear is set, and stamps update_time.
        """
        now = int(time.time() * 1000)
        try:
            updated = int(row.get('update_time') or 0)
        except (TypeError, ValueError):
            updated = 0
        if self._same_day_ms(now, updated):
            return row
        if self.config is not None:
            cfg = self.config.zuoqi_rank_config(row.get('zuoqi_rank'))
            if cfg is not None and cfg.get('lucky_clear'):
                row['lucky_value'] = 0
        row['update_time'] = now
        self._zuoqi_save(rid, row)
        return row

    @staticmethod
    def _zuoqi_level(role_level, cfg):
        """getZuoqiLevel: role level clamped to [0, maxLevel]."""
        try:
            level = int(role_level or 0)
        except (TypeError, ValueError):
            return 0
        return max(0, min(level, int(cfg.get('max_level') or 0)))

    def _zuoqi_in_kaifu(self, rank):
        """isInKaifu: the rank has a kaifu row and kaifu days < lastDays."""
        if self.config is None:
            return False
        cfg = self.config.kaifu_zuoqi_config(rank)
        if cfg is None:
            return False
        return self._vip_kaifu_days() < cfg['last_days']

    def zuoqi_panel(self, msg):
        """Command 33001: [1, [rank, level, lucky, fight], [], kaifu, cost]."""
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        args = self.safe(msg, 1, []) or []
        try:
            req = int(args[1] if len(args) > 1 else 0)
        except (TypeError, ValueError):
            req = 0
        row = self._zuoqi_row(rid)
        if row is None:
            return None
        row = self._zuoqi_timer(rid, row)
        try:
            rank = int(row.get('zuoqi_rank') or 0)
        except (TypeError, ValueError):
            rank = 0
        if req <= 0 or req > rank:
            req = rank
        if req <= 0:
            return frame(amf3_encode(
                [str(CMD_ZUOQI_PANEL), [0, [self.ZUOQI_EMPTY_CODE]]]))
        cfg = self.config.zuoqi_rank_config(req)
        if cfg is None:
            return frame(amf3_encode(
                [str(CMD_ZUOQI_PANEL), [0, [self.ZUOQI_NOCONFIG_CODE]]]))
        try:
            lucky = int(row.get('lucky_value') or 0)
        except (TypeError, ValueError):
            lucky = 0
        level = self._task_role_level(role)
        # Cost is getUpgradeCostCount over the kaifuData 'cost-count'
        # map for the fanhuan rank (0 when no fanhuan row or no spend).
        cost = 0
        fanhuan = self.config.kaifu_zuoqi_fanhuan() \
            if self.config is not None else None
        if fanhuan is not None:
            cost = self._zuoqi_cost_count(row, fanhuan['rank'])
        reply = [1, [rank, self._zuoqi_level(level, cfg), lucky,
                     self.config.zuoqi_fight(req, level)],
                 [], self._zuoqi_in_kaifu(rank), cost]
        return frame(amf3_encode([str(CMD_ZUOQI_PANEL), reply]))

    def zuoqi_ride(self, msg):
        """Command 33000: clamp the ridden rank, persist, stage [id, rank]."""
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        args = self.safe(msg, 1, []) or []
        try:
            req = int(args[1] if len(args) > 1 else None)
        except (TypeError, ValueError):
            return None
        row = self._zuoqi_row(rid)
        if row is None:
            return None
        try:
            rank = int(row.get('zuoqi_rank') or 0)
        except (TypeError, ValueError):
            rank = 0
        cur = req if 0 <= req <= rank else rank
        row['zuoqi_cur_rank'] = cur
        self._zuoqi_save(rid, row)
        return frame(amf3_encode(
            [str(CMD_ZUOQI_RIDE), [_wire_id(role), cur]]))

    def zuoqi_claim(self):
        """Command 33004: free rank-1 mount; silent past the rank gate."""
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        row = self._zuoqi_row(rid)
        if row is None:
            return None
        try:
            rank = int(row.get('zuoqi_rank') or 0)
        except (TypeError, ValueError):
            rank = 0
        if rank >= self.ZUOQI_MIN_RANK:
            return None
        now = int(time.time() * 1000)
        row.update(zuoqi_rank=self.ZUOQI_MIN_RANK,
                   zuoqi_cur_rank=self.ZUOQI_MIN_RANK, update_time=now)
        self._zuoqi_save(rid, row)
        cfg = self.config.zuoqi_rank_config(self.ZUOQI_MIN_RANK)
        level = self._zuoqi_level(self._task_role_level(role), cfg) \
            if cfg is not None else 0
        return frame(amf3_encode(
            [str(CMD_ZUOQI_CLAIM), [1, self.ZUOQI_MIN_RANK, level]]))

    # Mount kaifu refund/meiren (zuoqi 33005/33006/33007/33011). Evidence:
    # RoleZuoQiServiceImpl.zuoqiFanhuan/zuoqiJiangliMeiren/
    # getZuoqiFanhuanList/getZuoqiAwardInfo with ZuoQiUtil's kaifuData
    # helpers: 'cost-count' maps rank->jinjie pill spend, 'fanhuan' and
    # 'meiren' flags mark claimed (null/False means claimable, fastjson).
    @staticmethod
    def _zuoqi_kaifu_data(row):
        """kaifuData blob as a dict, tolerant like JsonUtils.getJSONObj."""
        try:
            text = row.get('kaifu_data')
        except AttributeError:
            return {}
        if not text:
            return {}
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _zuoqi_cost_count(self, row, rank):
        """ZuoQiUtil.getUpgradeCostCount: tracked spend at a rank."""
        try:
            key = str(int(rank))
        except (TypeError, ValueError):
            return 0
        inner = self._zuoqi_kaifu_data(row).get('cost-count')
        if isinstance(inner, str):
            try:
                inner = json.loads(inner)
            except (TypeError, ValueError):
                return 0
        if not isinstance(inner, dict):
            return 0
        try:
            return int(inner.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    def _zuoqi_add_cost(self, row, rank, count):
        """ZuoQiUtil.addCostCount: bank one attempt's cailiao count."""
        try:
            key = str(int(rank))
        except (TypeError, ValueError):
            return 0
        try:
            add = int(count or 0)
        except (TypeError, ValueError):
            add = 0
        data = self._zuoqi_kaifu_data(row)
        inner = data.get('cost-count')
        if isinstance(inner, str):
            try:
                inner = json.loads(inner)
            except (TypeError, ValueError):
                inner = None
        if not isinstance(inner, dict):
            inner = {}
        try:
            total = int(inner.get(key) or 0) + add
        except (TypeError, ValueError):
            total = add
        inner[key] = total
        data['cost-count'] = inner
        try:
            row['kaifu_data'] = json.dumps(data)
        except (TypeError, ValueError):
            pass
        return total

    def _zuoqi_can_claim(self, row, key):
        """ZuoQiUtil.checkCanLingqu*: an unset flag means claimable."""
        try:
            return not self._zuoqi_kaifu_data(row).get(key)
        except Exception:
            return True

    def _zuoqi_set_claimed(self, row, key):
        """ZuoQiUtil.change*State: set the claim flag on the blob."""
        data = self._zuoqi_kaifu_data(row)
        data[key] = True
        try:
            row['kaifu_data'] = json.dumps(data)
        except (TypeError, ValueError):
            pass

    def _zuoqi_fanhuan_cfg(self, rank):
        """Fanhuan gate config: the rank's own row when it refunds."""
        if self.config is None:
            return None
        own = self.config.kaifu_zuoqi_config(rank)
        if own is not None and own.get('return_goods'):
            return own
        return self.config.kaifu_zuoqi_fanhuan()

    def _zuoqi_meiren_cfg(self, rank):
        """Meiren gate config: the rank's own row when it names one."""
        if self.config is None:
            return None
        own = self.config.kaifu_zuoqi_config(rank)
        if own is not None and own.get('meiren'):
            return own
        return self.config.kaifu_zuoqi_meiren()

    def _zuoqi_raw_row(self, rid):
        """Mount row without auto-create (None is Java's cacheLoad miss)."""
        try:
            row = self.get_role_zuoqi(rid)
        except Exception:
            return None
        return dict(row) if row is not None else None

    @staticmethod
    def _zuoqi_name_str(role, wire_id):
        """ClientStrUtil.getNameStr: '{user|id,name,sex,0}' for the feed."""
        try:
            sex = int((role or {}).get('sex') or 0)
        except (TypeError, ValueError):
            sex = 0
        return '{user|%s,%s,%s,0}' % (
            wire_id, (role or {}).get('name'), sex)

    def zuoqi_fanhuan(self):
        """Command 33005: refund the fanhuan rank's tracked pill spend.

        Gates answer [0, code] (520020 state, 520024 past kaifu, 520022
        claimed, 1006 full bag); the grant is the rank's cailiao goods
        times the tracked count, bind 1, expiring per guoqi hours, and the
        reply is [1, [[goodsId, count]]] with a feed row appended.
        """
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        row = self._zuoqi_raw_row(rid)
        if row is None:
            return frame(amf3_encode(
                [str(CMD_ZUOQI_FANHUAN), [0, self.ZUOQI_FANHUAN_STATE]]))
        try:
            rank = int(row.get('zuoqi_rank') or 0)
        except (TypeError, ValueError):
            rank = 0
        cfg = self._zuoqi_fanhuan_cfg(rank)
        if cfg is None or rank <= cfg['rank']:
            return frame(amf3_encode(
                [str(CMD_ZUOQI_FANHUAN), [0, self.ZUOQI_FANHUAN_STATE]]))
        if self._vip_kaifu_days() > cfg['last_days']:
            return frame(amf3_encode(
                [str(CMD_ZUOQI_FANHUAN), [0, self.ZUOQI_KAIFU_OVER]]))
        if not self._zuoqi_can_claim(row, 'fanhuan'):
            return frame(amf3_encode(
                [str(CMD_ZUOQI_FANHUAN), [0, self.ZUOQI_FANHUAN_CLAIMED]]))
        goods_cfg = self.config.zuoqi_rank_config(cfg['rank'])
        if goods_cfg is None or not goods_cfg.get('cailiao_id'):
            return None
        count = self._zuoqi_cost_count(row, cfg['rank'])
        try:
            expire_hours = int(cfg.get('expire_hours') or 0)
        except (TypeError, ValueError):
            expire_hours = 0
        expire = int(time.time() * 1000) + expire_hours * 3600 * 1000 \
            if expire_hours > 0 else None
        if not self._prop_fits(rid, {'goods': goods_cfg['cailiao_id'],
                                     'count': count}, 1):
            return frame(amf3_encode(
                [str(CMD_ZUOQI_FANHUAN), [0, GENERAL_NOSLOT]]))
        self._zuoqi_set_claimed(row, 'fanhuan')
        self._zuoqi_save(rid, row)
        self._task_grant(rid, [{'goods_id': goods_cfg['cailiao_id'],
                                'count': count, 'bind': 1, 'expire': expire}])
        try:
            self.save_zuoqi_fanhuan(
                self._zuoqi_name_str(role, _wire_id(role)), count)
        except Exception:
            pass
        return frame(amf3_encode(
            [str(CMD_ZUOQI_FANHUAN),
             [1, [[goods_cfg['cailiao_id'], count]]]]))

    def zuoqi_fanhuan_list(self):
        """Command 33007: [costCount, [[name, count]...] or null]."""
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        row = self._zuoqi_raw_row(rid)
        if row is None:
            return frame(amf3_encode([str(CMD_ZUOQI_FANHUAN_LIST), None]))
        cfg = self.config.kaifu_zuoqi_fanhuan()
        if cfg is None:
            return None
        try:
            feed = self.get_zuoqi_fanhuan() or []
        except Exception:
            feed = []
        return frame(amf3_encode(
            [str(CMD_ZUOQI_FANHUAN_LIST),
             [self._zuoqi_cost_count(row, cfg['rank']), feed or None]]))

    def zuoqi_zhanli(self):
        """Command 33008: mount fight total (jichu + mount gear).

        Port of sendZhanli over getZuoQiFight: the cached fight-map
        total is jichu + mount-equip + longhun, computed live here.
        Longhun runs getlongLingOrLongHun over the role's
        attribute-goods map (0 for legacy roles, whose map is empty).
        """
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        try:
            items = self.get_role_equip(rid) or []
        except Exception:
            items = []
        try:
            mount = self.get_role_zuoqi(rid) or {}
        except Exception:
            mount = {}
        try:
            total = self.config.zuoqi_fight(
                mount.get('zuoqi_rank'), role.get('level')) or 0
        except Exception:
            total = 0
        try:
            total += self.config.zuoqi_equip_fight(items) or 0
        except Exception:
            pass
        try:
            total += self.config.zuoqi_longhun_fight(
                mount.get('zuoqi_rank'), role.get('level'),
                self._zuoqi_att_map(mount)) or 0
        except Exception:
            pass
        return frame(amf3_encode([str(CMD_ZUOQI_ZHANLI), total]))

    def _zuoqi_grant_meiren(self, rid, meiren_id):
        """addMeiRen: insert the type's level-1 row; True means push 82001.

        An owned row of the same type ([0, 82100] in Java) or a missing
        level-1 config (empty array) grants nothing; the caller still
        answers the claim either way.
        """
        if self.config is None:
            return False
        _, types = self.config.meiren_table()
        if not types.get(str(meiren_id), {}).get(1):
            return False
        try:
            owned = self.get_role_meiren(rid) or []
        except Exception:
            owned = []
        for entry in owned:
            try:
                same = self.config.meiren_type_for(
                    entry.get('meiren_id')) == str(meiren_id)
            except Exception:
                same = False
            if same:
                return False
        by_id, _ = self.config.meiren_table()
        meinvid = None
        for vid, pair in by_id.items():
            try:
                mtype, level = pair
            except (TypeError, ValueError):
                continue
            if mtype == str(meiren_id) and level == 1:
                meinvid = vid
                break
        if meinvid is None:
            return False
        rows = [dict(r) for r in owned]
        rows.append({'meiren_id': meinvid, 'meiren_level': 1,
                     'meiren_heti': 0})
        try:
            self.save_role_meiren(rid, rows)
        except Exception:
            return False
        return True

    @staticmethod
    def _meiren_int(cell):
        """object2int over a config cell ('' and junk read as 0)."""
        try:
            return int(cell or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _meiren_item_map(raw):
        """ConfigAnalyzeUtil.convert2Map over 'goods|count' pairs."""
        out = {}
        for chunk in str(raw or '').split(','):
            parts = chunk.split('|')
            if len(parts) != 2 or not parts[0]:
                continue
            try:
                out[parts[0]] = int(parts[1])
            except (TypeError, ValueError):
                continue
        return out

    def _meiren_owned(self, rid, meiren_type):
        """RoleMeiren row of one type (getRoleMeiRen: match by config type)."""
        try:
            owned = self.get_role_meiren(rid) or []
        except Exception:
            return None
        for entry in owned:
            try:
                same = self.config.meiren_type_for(
                    entry.get('meiren_id')) == str(meiren_type)
            except Exception:
                same = False
            if same:
                return entry
        return None

    def _meiren_decr_goods(self, rid, goods_id, need):
        """decrGoodses across slots; False leaves stock untouched."""
        try:
            slots = [s for s in
                     self.get_role_bag_slots(rid, -1000000, 1000000) or []
                     if str(s.get('goods_id')) == str(goods_id)]
        except Exception:
            return False
        have = 0
        for slot in slots:
            try:
                have += int(slot.get('count') or 0)
            except (TypeError, ValueError):
                continue
        if have < need:
            return False
        left = need
        for slot in slots:
            if left <= 0:
                break
            try:
                count = int(slot.get('count') or 0)
            except (TypeError, ValueError):
                continue
            take = min(count, left)
            rest = count - take
            try:
                if rest > 0:
                    self.update_role_bag_slot(rid, slot.get('slot_num'),
                                              count=rest)
                else:
                    self.delete_role_bag_slot(rid, slot.get('slot_num'))
            except Exception:
                return False
            left -= take
        return True

    def _meiren_request_type(self, msg):
        """MeirenAction data: the request carries a bare String type id."""
        data = msg[1] if len(msg) > 1 else None
        if not isinstance(data, str) or not data:
            return None
        return data

    @staticmethod
    def _pet_zhenfa_entries(zhenfa_pet):
        """zhenfa_pet fastjson {pos: petId} as [[pos, petId]] or null.

        Mirrors getPetInfo's JSONObject walk: a missing, unparseable or
        empty map yields null.
        """
        if not zhenfa_pet:
            return None
        try:
            data = json.loads(zhenfa_pet)
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict) or not data:
            return None
        return [[str(pos), data[pos]] for pos in data]

    def pet_info(self):
        """Command 136000: [pets, [zhenfaId, upgradeExp, entries],
        chuzhanId, upgradeCount].

        Port of PetServiceImpl.getPetInfo: one [petId, lv, rank, lvExp,
        rankExp] per owned RolePet (null when the role owns none), then
        the RolePetZhenfa row; no formation row is silent like Java's
        cacheLoad miss (live rows always exist, created at role birth).
        """
        role, rid = self._task_role()
        if role is None:
            return None
        try:
            pets = self.get_role_pets(rid) or []
        except Exception:
            pets = []
        arr = [[str(p.get('pet_id')), int(p.get('pet_lv') or 0),
                int(p.get('pet_rank') or 0),
                int(p.get('pet_lv_exp') or 0),
                int(p.get('pet_rank_exp') or 0)] for p in pets] or None
        try:
            zhenfa = self.get_role_pet_zhenfa(rid)
        except Exception:
            zhenfa = None
        if zhenfa is None:
            return None
        entries = self._pet_zhenfa_entries(zhenfa.get('zhenfa_pet'))
        try:
            upgrade_exp = int(zhenfa.get('upgrade_exp') or 0)
        except (TypeError, ValueError):
            upgrade_exp = 0
        try:
            upgrade_count = int(zhenfa.get('pet_upgrade_count') or 0)
        except (TypeError, ValueError):
            upgrade_count = 0
        return frame(amf3_encode(
            [str(CMD_PET_INFO),
             [arr, [zhenfa.get('zhenfa_id'), upgrade_exp, entries],
              zhenfa.get('pet_chuzhan_id'), upgrade_count]]))

    @staticmethod
    def _pet_zhenfa_map(zhenfa_pet):
        """zhenfa_pet fastjson {pos: petId} as a str-keyed dict or None."""
        if not zhenfa_pet:
            return None
        try:
            data = json.loads(zhenfa_pet)
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        return {str(k): v for k, v in data.items()}

    def _pet_zhenfa_push(self, entries):
        """136010 push: [[pos, petId]...] in document order (or [])."""
        return frame(amf3_encode(
            [str(CMD_PET_ZHENFA_PUSH),
             [[pos, entries[pos]] for pos in entries]]))

    _PET_KEEP = object()

    def _pet_save_zhenfa(self, rid, row, zhenfa_pet=None,
                         pet_chuzhan_id=_PET_KEEP):
        """Read-modify-write the formation row (save overwrites all)."""
        try:
            self.save_role_pet_zhenfa(
                rid, zhenfa_id=row.get('zhenfa_id'),
                pet_chuzhan_id=(row.get('pet_chuzhan_id')
                                if pet_chuzhan_id is self._PET_KEEP
                                else pet_chuzhan_id),
                upgrade_exp=row.get('upgrade_exp'),
                jinjie_fail_count=row.get('jinjie_fail_count'),
                jinjie_time=row.get('jinjie_time'),
                jinjie_data=row.get('jinjie_data'),
                zhenfa_pet=(zhenfa_pet if zhenfa_pet is not None
                            else row.get('zhenfa_pet')),
                pet_upgrade_count=row.get('pet_upgrade_count'),
                pet_upgrade_time=row.get('pet_upgrade_time'))
            return True
        except Exception:
            return False

    def _pet_owned(self, rid, pet_id):
        """True when the role owns petId (PetServiceImpl.getRolePet)."""
        try:
            pets = self.get_role_pets(rid) or []
        except Exception:
            return False
        return any(str(p.get('pet_id')) == str(pet_id) for p in pets)

    def pet_updown(self, msg):
        """Command 136005: upDownZhen [petId, slot, 1] deploys, flag
        other removes the slot (downZhen ignores the pet id).

        Port of upZhen/_downZhen: unknown pet answers [0, 136005], an
        already-deployed pet answers [0, 136006]; success stores the
        slot, emits the 136010 formation push, and answers
        [1, petId, slot, flag] (down answers [1, remainingMap, slot,
        flag]). The upZhen containsKey(Integer) pre-clear is dead in
        Java (String keys never equal an Integer), so put wins
        directly. No formation row stays silent like cacheLoad miss."""
        role, rid = self._task_role()
        if role is None:
            return None
        try:
            data = self.safe(msg, 1, [])
            pet_id, slot, flag = (str(self.safe(data, 0)),
                                  int(self.safe(data, 1)),
                                  int(self.safe(data, 2)))
        except (TypeError, ValueError):
            return None
        if not pet_id:
            return None
        try:
            row = self.get_role_pet_zhenfa(rid)
        except Exception:
            row = None
        if row is None:
            return None
        entries = self._pet_zhenfa_map(row.get('zhenfa_pet'))
        if entries is None:
            return None
        if flag == 1:
            if not self._pet_owned(rid, pet_id):
                return frame(amf3_encode(['136005', [0, PET_ERR_NO_PET]]))
            if pet_id in entries.values():
                return frame(amf3_encode(['136005', [0, PET_ERR_DEPLOYED]]))
            entries[str(slot)] = pet_id
            self._pet_save_zhenfa(
                rid, row, zhenfa_pet=json.dumps(entries))
            return [self._pet_zhenfa_push(entries),
                    frame(amf3_encode(['136005', [1, pet_id, slot, flag]]))]
        entries.pop(str(slot), None)
        self._pet_save_zhenfa(rid, row, zhenfa_pet=json.dumps(entries))
        return [self._pet_zhenfa_push(entries),
                frame(amf3_encode(['136005', [1, entries, slot, flag]]))]

    def pet_chuzhan(self, msg):
        """Command 136006: chuZhan deploys a pet to expedition (or
        recalls with a null id).

        Port of PetServiceImpl.chuZhan: an unknown pet answers
        [0, 136005]; the pet is stripped from every formation slot
        first (one 136010 push per removed slot); re-calling with the
        current expedition pet answers [0, 136010]. Otherwise the
        136011 push reports [[old, 2]] on recall, [[new, 1]] on
        deploy, [[old, 2], [new, 1]] on switch, and the reply is [1]."""
        role, rid = self._task_role()
        if role is None:
            return None
        try:
            raw = self.safe(msg, 1, None)
            pet_id = None if raw is None else str(raw)
        except Exception:
            return None
        if pet_id is not None and not pet_id:
            return None
        try:
            row = self.get_role_pet_zhenfa(rid)
        except Exception:
            row = None
        if row is None:
            return None
        entries = self._pet_zhenfa_map(row.get('zhenfa_pet'))
        if entries is None:
            return None
        out = []
        if pet_id is not None:
            if not self._pet_owned(rid, pet_id):
                return frame(amf3_encode(['136006', [0, PET_ERR_NO_PET]]))
            for pos in [p for p, v in entries.items() if v == pet_id]:
                del entries[pos]
                self._pet_save_zhenfa(
                    rid, row, zhenfa_pet=json.dumps(entries))
                row = dict(row, zhenfa_pet=json.dumps(entries))
                out.append(self._pet_zhenfa_push(entries))
        old = row.get('pet_chuzhan_id')
        if old is not None and old == pet_id:
            return frame(amf3_encode(['136006', [0, PET_ERR_CHUZHAN_DUP]]))
        if old is None:
            push = [[pet_id, 1]]
        elif pet_id is None:
            push = [[old, 2]]
        else:
            push = [[old, 2], [pet_id, 1]]
        out.append(frame(amf3_encode([str(CMD_PET_CHUZHAN_PUSH), push])))
        self._pet_save_zhenfa(rid, row, pet_chuzhan_id=pet_id)
        out.append(frame(amf3_encode(['136006', [1]])))
        return out

    def meiren_panel(self):
        """Command 82000: owned [[type, level, heti]] or null when empty."""
        if self.config is None:
            return None
        _, rid = self._task_role()
        if rid is None:
            return None
        try:
            owned = self.get_role_meiren(rid) or []
        except Exception:
            owned = []
        entries = []
        for entry in owned:
            try:
                mtype = self.config.meiren_type_for(entry.get('meiren_id'))
                level = int(entry.get('meiren_level') or 0)
                heti = int(entry.get('meiren_heti') or 0)
            except (TypeError, ValueError):
                continue
            if mtype is None:
                continue
            entries.append([mtype, level, heti])
        return frame(amf3_encode(['82000', entries or None]))

    def meiren_obtain(self, msg):
        """Command 82001: recruit a meiren, gating level/qiandao/items/zhenqi."""
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        meiren_type = self._meiren_request_type(msg)
        if meiren_type is None:
            return None
        gates = self.config.meiren_gates()
        entry = gates.get(meiren_type)
        if entry is None or entry.get('l1') is None:
            return None
        if self._meiren_owned(rid, meiren_type) is not None:
            return frame(amf3_encode(['82001', [0, 82100]]))
        l1 = entry['l1']
        need_level = self._meiren_int(l1.get('zhaomulv'))
        if self._task_role_level(role) < need_level:
            return frame(amf3_encode(['82001', [0, 82101, [need_level]]]))
        need_qian = self._meiren_int(l1.get('zhaomuqiandao'))
        if 0 < need_qian:
            return frame(amf3_encode(['82001', [0, 82102, [need_qian]]]))
        try:
            zuoqi_rank = int((self.get_role_zuoqi(rid) or {}).get(
                'zuoqi_rank') or 0)
        except (TypeError, ValueError):
            zuoqi_rank = 0
        if self._meiren_int(l1.get('zhaomutiaojian')) > zuoqi_rank:
            return frame(amf3_encode(['82001', [0, GENERAL_ZUOQI_RANK]]))
        needs = self._meiren_item_map(l1.get('zhaomuitem'))
        if any(self._task_goods_count(rid, gid) < need
               for gid, need in needs.items()):
            return frame(amf3_encode(['82001', [0, 82103]]))
        try:
            zhenqi = int(role.get('zhenqi') or 0)
        except (TypeError, ValueError):
            zhenqi = 0
        need_zhenqi = self._meiren_int(l1.get('zhaomuzhenqi'))
        if zhenqi < need_zhenqi:
            return frame(amf3_encode(['82001', [0, 82104]]))
        for gid, need in needs.items():
            if not self._meiren_decr_goods(rid, gid, need):
                return frame(amf3_encode(['82001', [0, 82103]]))
        try:
            owned = self.get_role_meiren(rid) or []
        except Exception:
            owned = []
        rows = [dict(r) for r in owned]
        rows.append({'meiren_id': str(l1.get('meinvid')), 'meiren_level': 1,
                     'meiren_heti': 0})
        try:
            self.save_role_meiren(rid, rows)
            self.save_role_state(rid, zhenqi=zhenqi - need_zhenqi)
        except Exception:
            return None
        return frame(amf3_encode(['82001', [1, meiren_type, 1]]))

    def meiren_upgrade(self, msg):
        """Command 82002: level up for zhenqi, pushing [1, type, level]."""
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        meiren_type = self._meiren_request_type(msg)
        if meiren_type is None:
            return None
        row = self._meiren_owned(rid, meiren_type)
        if row is None:
            return None
        try:
            level = int(row.get('meiren_level') or 0)
            heti = int(row.get('meiren_heti') or 0)
        except (TypeError, ValueError):
            return None
        if heti < level:
            return frame(amf3_encode(['82002', [0, 82105]]))
        if level + 1 > self._task_role_level(role):
            return frame(amf3_encode(['82002', [0, 82106]]))
        nxt = self.config.meiren_gates().get(meiren_type, {}).get(
            'levels', {}).get(level + 1)
        if nxt is None:
            return frame(amf3_encode(['82002', [0, 82106]]))
        try:
            zhenqi = int(role.get('zhenqi') or 0)
        except (TypeError, ValueError):
            zhenqi = 0
        need = self._meiren_int(nxt.get('lvupzhenqi'))
        if zhenqi < need:
            return frame(amf3_encode(['82002', [0, 82108]]))
        try:
            owned = self.get_role_meiren(rid) or []
        except Exception:
            return None
        rows = []
        for entry in owned:
            entry = dict(entry)
            if entry.get('meiren_id') == row.get('meiren_id'):
                entry['meiren_id'] = str(nxt.get('meinvid'))
                entry['meiren_level'] = level + 1
            rows.append(entry)
        try:
            self.save_role_meiren(rid, rows)
            self.save_role_state(rid, zhenqi=zhenqi - need)
        except Exception:
            return None
        return frame(amf3_encode(['82002', [1, meiren_type, level + 1]]))

    def meiren_chanmian(self, msg):
        """Command 82003: chanmian for zhenqi + YXB, pushing [1, type, lv, heti]."""
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        meiren_type = self._meiren_request_type(msg)
        if meiren_type is None:
            return None
        row = self._meiren_owned(rid, meiren_type)
        if row is None:
            return None
        try:
            level = int(row.get('meiren_level') or 0)
            heti = int(row.get('meiren_heti') or 0)
        except (TypeError, ValueError):
            return None
        if level <= heti:
            return frame(amf3_encode(['82003', [0, 82109]]))
        cfg = self.config.meiren_gates().get(meiren_type, {}).get(
            'levels', {}).get(level)
        if cfg is None:
            return None
        try:
            zhenqi = int(role.get('zhenqi') or 0)
        except (TypeError, ValueError):
            zhenqi = 0
        if zhenqi < self._meiren_int(cfg.get('chanmianzhenqi')):
            return frame(amf3_encode(['82003', [0, 82110]]))
        try:
            roles = self.get_roles(self.authed_user or '',
                                   self.server_id or '')
            yxb = int((roles[0] if roles else {}).get('tongqian') or 0)
        except (TypeError, ValueError):
            yxb = 0
        coin = self._meiren_int(cfg.get('chanmiancoin'))
        if yxb < coin:
            return frame(amf3_encode(['82003', [0, 82112]]))
        try:
            owned = self.get_role_meiren(rid) or []
        except Exception:
            return None
        rows = []
        for entry in owned:
            entry = dict(entry)
            if entry.get('meiren_id') == row.get('meiren_id'):
                entry['meiren_heti'] = heti + 1
            rows.append(entry)
        try:
            self.save_role_meiren(rid, rows)
            self.save_role_state(
                rid, zhenqi=zhenqi - self._meiren_int(
                    cfg.get('chanmianzhenqi')))
            self._bag_money_decr(rid, 'YXB', coin)
        except Exception:
            return None
        return frame(amf3_encode(['82003', [1, meiren_type, level, heti + 1]]))

    def _baoshi_rows(self, rid):
        """Role_baoshi rows for a role as fresh dicts (getRoleBaoShi list)."""
        try:
            return [dict(r) for r in self.get_role_baoshi(rid) or []]
        except Exception:
            return []

    def _baoshi_save(self, rid, rows):
        """Persist role_baoshi rows; False keeps the reply silent."""
        try:
            return bool(self.save_role_baoshi(rid, rows))
        except Exception:
            return False

    def _baoshi_request(self, msg):
        """BaoShiAction data: [part, grid] or [part, grid, isAuto]."""
        data = msg[1] if len(msg) > 1 else None
        if not isinstance(data, (list, tuple)) or len(data) not in (2, 3):
            return None
        part, grid = data[0], data[1]
        for value in (part, grid):
            if isinstance(value, bool) or not isinstance(value, int):
                return None
        auto = False
        if len(data) == 3:
            flag = data[2]
            if isinstance(flag, bool) or not isinstance(flag, int):
                return None
            auto = flag == 1
        return part, grid, auto

    @staticmethod
    def _baoshi_part_level(rows, part):
        """Sum of levels on one part (getPartLevelSum)."""
        total = 0
        for row in rows or []:
            try:
                if int(row.get('part')) != part:
                    continue
                total += int(row.get('level') or 0)
            except (TypeError, ValueError):
                continue
        return total

    def _baoshi_find(self, rows, part, grid):
        """Row for one (part, grid) (getRoleBaoShi), or None."""
        for row in rows or []:
            try:
                if int(row.get('part')) == part and \
                        int(row.get('grid')) == grid:
                    return row
            except (TypeError, ValueError):
                continue
        return None

    def _baoshi_min_row(self, rows, part):
        """Lowest (level, grid) row on a part (getMinLevelBaoshi)."""
        best, best_key = None, None
        for row in rows or []:
            try:
                if int(row.get('part')) != part:
                    continue
                key = (int(row.get('level') or 0), int(row.get('grid')))
            except (TypeError, ValueError):
                continue
            if best_key is None or key < best_key:
                best, best_key = row, key
        return best

    def _baoshi_material_plan(self, rid, role, needs, rank, auto_buy,
                              short_code):
        """Bag-plus-mall material check over a {goods: count} map.

        Port of checkGoodsJinJieDanMoneyEnough (upgrade) and
        checkGoodsMoneyEnough (jihuo): each need fills from its
        specialtype substitutes in config order (both baoshi materials
        substitute only themselves), then the remainder is mall-priced
        (npc 2000, first affordable non-guild type) when auto_buy holds.
        Returns (decr, mall_money) or (None, code): 430250 with no
        substitutes, short_code when the bag falls short without
        auto-buy, 430249 with no mall offer, else the short money's
        code (1002/1004/1003, defaulting to 1002 like Java).
        """
        decr, mall_money = {}, {}
        for gid, need in (needs or {}).items():
            try:
                left = int(need)
            except (TypeError, ValueError):
                continue
            if left <= 0:
                continue
            if rank is None:
                subs = [str(gid)]
            else:
                try:
                    subs = self.config.goods_specialtype_substitutes(
                        gid, rank)
                except Exception:
                    subs = None
            if not subs:
                return None, BAG_ERR_TRY
            for sub in subs:
                if left <= 0:
                    break
                stock = self._task_goods_count(rid, sub)
                if stock <= 0:
                    continue
                take = min(left, stock)
                decr[sub] = decr.get(sub, 0) + take
                left -= take
            if left <= 0:
                continue
            if not auto_buy:
                return None, short_code
            offer = self.config.mall_offer(str(gid), '2000')
            if offer is None:
                return None, BAG_ERR_MALL
            priced = False
            for money_type in sorted(offer['costs']):
                if money_type == 5:
                    continue
                name = MALL_MONEY_NAMES.get(money_type)
                column = BAG_MONEY_COLUMNS.get(name) if name else None
                if column is None:
                    continue
                try:
                    total = int(offer['costs'][money_type]) * left
                    balance = int((role or {}).get(column) or 0)
                except (TypeError, ValueError):
                    continue
                if balance >= total:
                    mall_money[money_type] = \
                        mall_money.get(money_type, 0) + total
                    priced = True
                    break
            if priced:
                continue
            first = next((t for t in sorted(offer['costs']) if t != 5), 2)
            return None, {2: GENERAL_YB, 3: GENERAL_BINDYB,
                           1: GENERAL_JB}.get(first, GENERAL_YB)
        return decr, mall_money

    def _baoshi_consume(self, rid, role, decr, mall_money):
        """Take planned goods and mall money (decrConsumeGoodMoney)."""
        for gid, take in (decr or {}).items():
            self._prop_take(rid, gid, take)
        for money_type, total in (mall_money or {}).items():
            name = MALL_MONEY_NAMES.get(money_type)
            if name is not None and total:
                self._bag_money_decr(rid, name, total)

    def _baoshi_can_jihuo(self, role, rows, part, grid):
        """canJiHuo gate code for a (part, grid), or None when open."""
        detail = self.config.baoshi_detail(part, grid)
        if detail is None:
            return BAOSHI_ERR_CANNOT
        if detail['needlv'] > self._task_role_level(role):
            return BAOSHI_ERR_LEVEL
        if detail['gjneedpj'] > self._baoshi_part_level(rows, part):
            return BAOSHI_ERR_GRADE
        buwei = self.config.baoshi_buwei().get(part)
        if buwei is None:
            return BAOSHI_ERR_CANNOT
        if grid < buwei['min_grid'] or grid > buwei['max_grid']:
            return BAOSHI_ERR_CANNOT
        mine = [r for r in rows
                if self._baoshi_find([r], part, r.get('grid')) is not None]
        top = None
        for row in mine:
            try:
                level = int(row.get('level') or 0)
                cell = int(row.get('grid'))
            except (TypeError, ValueError):
                continue
            if top is None or cell > top[0]:
                top = (cell, level)
        if top is not None:
            if top[0] > grid:
                return BAOSHI_ERR_JIHUOED
            if top[0] == grid:
                if top[1] > 0:
                    return BAOSHI_ERR_JIHUOED
            elif top[0] + 1 != grid:
                return BAOSHI_ERR_CANNOT
        elif grid != buwei['min_grid']:
            return BAOSHI_ERR_CANNOT
        try:
            zhenqi = int((role or {}).get('zhenqi') or 0)
        except (TypeError, ValueError):
            zhenqi = 0
        if zhenqi < detail['cost_zhenqi']:
            return BAOSHI_ERR_ZHENQI_J
        return None

    @staticmethod
    def _baoshi_is_success(odds):
        """Lottery.isSuccess: a uniform roll under the rate."""
        try:
            return random.random() < float(odds)
        except (TypeError, ValueError):
            return False

    def _baoshi_roll_rates(self, rates):
        """RateScope.randomZuoqiRate: [type, exp] or None past the total."""
        roll = random.random()
        total = 0.0
        for kind, rate, exp in rates or []:
            try:
                total += float(rate)
            except (TypeError, ValueError):
                continue
            if roll < total:
                return [kind, exp]
        return None

    def _baoshi_add_exp(self, rid, rows, add, row, upgraded, chained):
        """addBaoShiExp: feed exp, leveling with overflow chaining.

        Rows mutate in place; upgraded collects leveled rows, chained the
        overflow targets (yiChu). A null roll or a capped gem ends the
        feed like Java's early return; the chained row is recorded on
        entry when a chain is already open.
        """
        if add <= 0 or row is None:
            return
        try:
            part = int(row.get('part'))
            level = int(row.get('level') or 0)
        except (TypeError, ValueError):
            return
        detail = self.config.baoshi_detail(part, row.get('grid'))
        if detail is None:
            return
        cfg = self.config.baoshi_shengji().get(str(detail.get('gemid')))
        if cfg is None or level >= cfg['max']:
            return
        if chained and chained[0]:
            chained[0] = row
        lvl = self.config.baoshi_level(detail.get('gemid'), level)
        if lvl is None:
            return
        try:
            exp = int(row.get('exp') or 0)
        except (TypeError, ValueError):
            exp = 0
        overflow = exp + add - lvl['max_exp']
        if overflow < 0:
            row['exp'] = exp + add
            return
        upgraded.append(row)
        row['level'] = level + 1
        row['exp'] = 0
        if overflow <= 0:
            return
        chained[0] = True
        nxt = self._baoshi_min_row(rows, part)
        self._baoshi_add_exp(rid, rows, overflow, nxt, upgraded, chained)

    def baoshi_info(self):
        """Command 37000: formatAll panel, null when nothing is socketed."""
        if self.config is None:
            return None
        _, rid = self._task_role()
        if rid is None:
            return None
        groups = {}
        for row in self._baoshi_rows(rid):
            try:
                part = int(row.get('part'))
                cell = [int(row.get('grid')), int(row.get('exp') or 0),
                        int(row.get('level') or 0)]
            except (TypeError, ValueError):
                continue
            groups.setdefault(part, []).append(cell)
        if not groups:
            return frame(amf3_encode([str(CMD_BAOSHI_INFO), None]))
        flat = []
        for part in sorted(groups):
            flat.extend([part, sorted(groups[part])])
        return frame(amf3_encode([str(CMD_BAOSHI_INFO), flat]))

    def baoshi_jihuo(self, msg):
        """Command 37001: socket a gem through the pity lottery.

        Gates answer [0, code]; the cost goods (mall-priced when auto)
        and zhenqi are consumed, then a fresh row (or the failed row's
        retry) rolls: failCount under minTimes fails, past maxTimes
        lands, else the odds decide. Success pushes [1, part, grid] at
        the detail's chushi level, failure pushes [-1] with failCount+1.
        Goods-check failures answer [0, code] on the wire: Java returns
        those arrays to an action that drops them, so queuing them here
        is the observable fix. Events ride no bus.
        """
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        req = self._baoshi_request(msg)
        if req is None:
            return None
        part, grid, auto = req
        rows = self._baoshi_rows(rid)
        gate = self._baoshi_can_jihuo(role, rows, part, grid)
        if gate is not None:
            return frame(amf3_encode(
                [str(CMD_BAOSHI_JIHUO), [0, gate]]))
        detail = self.config.baoshi_detail(part, grid)
        if detail is None:
            return None
        needs = detail['cost_goods'] or {}
        decr, mall_money = self._baoshi_material_plan(
            rid, role, needs, None, auto, BAOSHI_ERR_GOODS_J) \
            if needs else ({}, {})
        if decr is None:
            return frame(amf3_encode(
                [str(CMD_BAOSHI_JIHUO), [0, BAOSHI_ERR_GOODS_J]]))
        try:
            zhenqi = int(role.get('zhenqi') or 0)
        except (TypeError, ValueError):
            zhenqi = 0
        self._baoshi_consume(rid, role, decr, mall_money)
        if detail['cost_zhenqi'] > 0:
            try:
                self.save_role_state(
                    rid, zhenqi=zhenqi - detail['cost_zhenqi'])
            except Exception:
                return None
        row = self._baoshi_find(rows, part, grid)
        if row is None:
            row = {'id': f'baoshi{uuid.uuid4().hex[:16]}',
                   'part': part, 'grid': grid, 'level': 0,
                   'fail_count': 0, 'exp': 0,
                   'update_time': int(time.time() * 1000)}
            rows.append(row)
        try:
            fails = int(row.get('fail_count') or 0)
        except (TypeError, ValueError):
            fails = 0
        if fails < detail['mintimes']:
            success = False
        elif fails >= detail['maxtimes']:
            success = True
        else:
            success = self._baoshi_is_success(detail['odds'])
        now = int(time.time() * 1000)
        if success:
            row['level'] = int(detail['chushilv'])
            row['fail_count'] = 0
            row['update_time'] = now
            reply = [1, part, grid]
        else:
            row['fail_count'] = fails + 1
            reply = [-1]
        if not self._baoshi_save(rid, rows):
            return None
        return frame(amf3_encode([str(CMD_BAOSHI_JIHUO), reply]))

    def baoshi_upgrade(self, msg):
        """Command 37002: feed a gem exp, chaining overflow along the part.

        Gates answer [0, code]; consumed materials answer [0, code] and
        the RateScope roll pays exp with level-ups (overflow recurses
        into the part's lowest gem, whose formatOne rides slot 7).
        Success pushes [1, part, grid, level, exp, roll0, roll1]; a stone
        that canUpgrade no more with a notice detail also emits the
        11101 [530011, ...] broadcast. Events ride no bus.
        """
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        req = self._baoshi_request(msg)
        if req is None:
            return None
        part, grid, auto = req
        rows = self._baoshi_rows(rid)
        row = self._baoshi_find(rows, part, grid)
        if row is None:
            return frame(amf3_encode(
                [str(CMD_BAOSHI_UPGRADE), [0, BAOSHI_ERR_CANNOT]]))
        try:
            level = int(row.get('level') or 0)
        except (TypeError, ValueError):
            return frame(amf3_encode(
                [str(CMD_BAOSHI_UPGRADE), [0, BAOSHI_ERR_CANNOT]]))
        if level <= 0:
            return frame(amf3_encode(
                [str(CMD_BAOSHI_UPGRADE), [0, BAOSHI_ERR_CANNOT]]))
        detail = self.config.baoshi_detail(part, grid)
        if detail is None:
            return frame(amf3_encode(
                [str(CMD_BAOSHI_UPGRADE), [0, BAOSHI_ERR_CANNOT]]))
        cfg = self.config.baoshi_shengji().get(str(detail.get('gemid')))
        if cfg is None or level >= cfg['max']:
            return frame(amf3_encode(
                [str(CMD_BAOSHI_UPGRADE), [0, BAOSHI_ERR_TOP]]))
        low = self._baoshi_min_row(rows, part)
        try:
            low_grid = int(low.get('grid')) if low is not None else None
        except (TypeError, ValueError):
            low_grid = None
        if low_grid != grid:
            return frame(amf3_encode(
                [str(CMD_BAOSHI_UPGRADE), [0, BAOSHI_ERR_CANNOT]]))
        lvl = self.config.baoshi_level(detail.get('gemid'), level)
        if lvl is None or not lvl['can_upgrade']:
            return frame(amf3_encode(
                [str(CMD_BAOSHI_UPGRADE), [0, BAOSHI_ERR_CANNOT]]))
        if lvl['cost_zhenqi'] > 0:
            try:
                zhenqi = int((role or {}).get('zhenqi') or 0)
            except (TypeError, ValueError):
                zhenqi = 0
            if zhenqi < lvl['cost_zhenqi']:
                return frame(amf3_encode(
                    [str(CMD_BAOSHI_UPGRADE), [0, BAOSHI_ERR_ZHENQI_U]]))
        decr, mall_money = self._baoshi_material_plan(
            rid, role, lvl['cost_goods'] or {}, level, auto, GENERAL_GOODS)
        if decr is None:
            return frame(amf3_encode(
                [str(CMD_BAOSHI_UPGRADE), [0, mall_money]]))
        try:
            zhenqi = int(role.get('zhenqi') or 0)
        except (TypeError, ValueError):
            zhenqi = 0
        self._baoshi_consume(rid, role, decr, mall_money)
        if detail['cost_zhenqi'] > 0:
            try:
                self.save_role_state(
                    rid, zhenqi=zhenqi - detail['cost_zhenqi'])
            except Exception:
                return None
        roll = self._baoshi_roll_rates(lvl['rates'])
        if roll is None:
            return frame(amf3_encode(
                [str(CMD_BAOSHI_UPGRADE), [0, BAG_ERR_TRY]]))
        upgraded, chained = [], [False]
        self._baoshi_add_exp(rid, rows, roll[1], row, upgraded, chained)
        if not self._baoshi_save(rid, rows):
            return None
        try:
            exp = int(row.get('exp') or 0)
            level = int(row.get('level') or 0)
        except (TypeError, ValueError):
            exp, level = 0, 0
        reply = [1, part, grid, level, exp, roll[0], roll[1]]
        if chained[0] and isinstance(chained[0], dict):
            try:
                chained_cell = [int(chained[0].get('grid')),
                                int(chained[0].get('exp') or 0),
                                int(chained[0].get('level') or 0)]
            except (TypeError, ValueError):
                chained_cell = None
            if chained_cell is not None:
                reply.append(chained_cell)
        frames = []
        if upgraded and detail['notice']:
            top_lvl = self.config.baoshi_level(detail.get('gemid'), level)
            if top_lvl is not None and not top_lvl['can_upgrade']:
                frames.append(frame(amf3_encode(
                    [str(CMD_NOTICE_ALL),
                     [BAOSHI_ERR_NOTIFY,
                      [str(role.get('name')), '{bodyPart|%d}' % part,
                       top_lvl['name']]]]))) 
        frames.append(frame(amf3_encode([str(CMD_BAOSHI_UPGRADE), reply])))
        return tuple(frames) if len(frames) > 1 else frames[0]

    def zuoqi_jiangli_meiren(self):
        """Command 33006: grant the kaifu meiren, pushing 82001 first.

        Gates answer [0, code] (520021 state, 520024 past kaifu, 520023
        claimed); success pushes [1, meirenId, 1] ahead of [1, meirenId].
        """
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        row = self._zuoqi_raw_row(rid)
        if row is None:
            return frame(amf3_encode(
                [str(CMD_ZUOQI_MEIREN), [0, self.ZUOQI_MEIREN_STATE]]))
        try:
            rank = int(row.get('zuoqi_rank') or 0)
        except (TypeError, ValueError):
            rank = 0
        cfg = self._zuoqi_meiren_cfg(rank)
        if cfg is None or rank <= cfg['rank']:
            return frame(amf3_encode(
                [str(CMD_ZUOQI_MEIREN), [0, self.ZUOQI_MEIREN_STATE]]))
        if self._vip_kaifu_days() > cfg['last_days']:
            return frame(amf3_encode(
                [str(CMD_ZUOQI_MEIREN), [0, self.ZUOQI_KAIFU_OVER]]))
        if not self._zuoqi_can_claim(row, 'meiren'):
            return frame(amf3_encode(
                [str(CMD_ZUOQI_MEIREN), [0, self.ZUOQI_MEIREN_CLAIMED]]))
        grant = self.config.kaifu_zuoqi_meiren()
        if grant is None or not grant.get('meiren'):
            return None
        meiren_id = grant['meiren']
        self._zuoqi_set_claimed(row, 'meiren')
        self._zuoqi_save(rid, row)
        frames = []
        if self._zuoqi_grant_meiren(rid, meiren_id):
            frames.append(frame(amf3_encode(
                [str(CMD_MEIREN_ADD), [1, meiren_id, 1]])))
        frames.append(frame(amf3_encode(
            [str(CMD_ZUOQI_MEIREN), [1, meiren_id]])))
        return tuple(frames) if len(frames) > 1 else frames[0]

    def zuoqi_award_info(self):
        """Command 33011: [fanhuanRank?, meirenRank?] claimable-now slots.

        Each slot carries the kaifu rank when the role could claim it
        now (in-kaifu, past the rank, unclaimed), else null; no mount
        row answers the empty array.
        """
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        row = self._zuoqi_raw_row(rid)
        if row is None:
            return frame(amf3_encode([str(CMD_ZUOQI_AWARD), []]))
        try:
            rank = int(row.get('zuoqi_rank') or 0)
        except (TypeError, ValueError):
            rank = 0
        days = self._vip_kaifu_days()
        fanhuan = self.config.kaifu_zuoqi_fanhuan()
        meiren = self.config.kaifu_zuoqi_meiren()
        first = fanhuan['rank'] if (
            fanhuan is not None and days <= fanhuan['last_days']
            and rank > fanhuan['rank']
            and self._zuoqi_can_claim(row, 'fanhuan')) else None
        second = meiren['rank'] if (
            meiren is not None and days <= meiren['last_days']
            and rank > meiren['rank']
            and self._zuoqi_can_claim(row, 'meiren')) else None
        return frame(amf3_encode(
            [str(CMD_ZUOQI_AWARD), [first, second]]))

    @staticmethod
    def _zuoqi_java_round(value):
        """Math.round for non-negative floats (floor(x + 0.5))."""
        try:
            return int(math.floor(float(value) + 0.5))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _zuoqi_random_int(low, high):
        """Lottery.randomInt: low when equal, else low + nextInt(high-low)."""
        try:
            low, high = int(low), int(high)
        except (TypeError, ValueError):
            return 0
        if low == high:
            return low
        if high < low:
            return low
        return low + random.randrange(high - low)

    @staticmethod
    def _zuoqi_is_success(odds):
        """Lottery.isSuccess: nextFloat() below the odds."""
        try:
            return random.random() < float(odds)
        except (TypeError, ValueError):
            return False

    def _zuoqi_can_upgrade(self, role, row, cfg):
        """canUpgradeRank gates, or None when the attempt may proceed."""
        try:
            rank = int(row.get('zuoqi_rank') or 0)
        except (TypeError, ValueError):
            rank = 0
        if rank >= self.config.zuoqi_max_rank():
            return [self.ZUOQI_MAX_CODE]
        if self._task_role_level(role) < cfg['need_level']:
            return [self.ZUOQI_LEVEL_CODE, cfg['need_level']]
        try:
            free = int(row.get('free_jb') or 0)
        except (TypeError, ValueError):
            free = 0
        if free != 1 and not self._bag_money_check(
                role, 'YXB', cfg['upgrade_jb']):
            return [self.ZUOQI_MONEY_CODE, cfg['upgrade_jb']]
        return None

    def _zuoqi_bag_stock(self, rid, goods_id):
        """Total count of a goods across the role's bag slots."""
        try:
            slots = self.get_role_bag_slots(rid, -1000000, 1000000) or []
        except Exception:
            return 0
        total = 0
        for slot in slots:
            if str(slot.get('goods_id')) != str(goods_id):
                continue
            try:
                total += int(slot.get('count') or 0)
            except (TypeError, ValueError):
                continue
        return total

    def _zuoqi_material_plan(self, rid, role, cfg, rank, auto_buy):
        """Jinjie material check: bag pills, mall money for the rest.

        Port of checkGoodsJinJieDanMoneyEnough over the specialtype
        substitutes: each deficit is mall-priced (npc 2000, first affordable
        non-guild type in int order; HashMap order matches it for the
        shipped small-int keys) when auto_buy holds, else GOODS_NOT_ENOUGH.
        Returns (decr_map, mall_money) or (None, code).
        """
        subs = self.config.goods_specialtype_substitutes(
            cfg['cailiao_id'], rank)
        if not subs:
            return None, self.ZUOQI_TRY_FAIL
        need = cfg['cailiao_count']
        decr = {}
        for sub in subs:
            if need <= 0:
                break
            stock = self._zuoqi_bag_stock(rid, sub)
            if stock <= 0:
                continue
            take = min(need, stock)
            decr[sub] = take
            need -= take
        if need <= 0:
            return decr, {}
        if not auto_buy:
            return None, GENERAL_GOODS
        offer = self.config.mall_offer(cfg['cailiao_id'], '2000')
        if offer is None:
            return None, self.ZUOQI_MALL_FAIL
        for money_type in sorted(offer['costs']):
            if money_type == 5:
                continue
            name = MALL_MONEY_NAMES.get(money_type)
            column = BAG_MONEY_COLUMNS.get(name) if name else None
            if column is None:
                continue
            try:
                total = int(offer['costs'][money_type]) * need
                balance = int((role or {}).get(column) or 0)
            except (TypeError, ValueError):
                continue
            if balance >= total:
                return decr, {money_type: total}
        first = next((t for t in sorted(offer['costs']) if t != 5), 2)
        return None, {2: GENERAL_YB, 3: GENERAL_BINDYB,
                       1: GENERAL_JB}.get(first, GENERAL_YB)

    def _zuoqi_upgrade_success(self, row, lvl, role_level):
        """upgradeSuccess lottery over the pity window plus base odds.

        Lucky-pill time shaves (minTimes-scaled luckyChance) and the
        addLucky shave (round(add/90)) apply; no local row can carry lucky
        pills (their writers are unported), so only the addLucky term can
        fire. The zhufu-card rate prop is unported, hence 0.
        """
        max_times, min_times = lvl['max_times'], lvl['min_times']
        try:
            add = int(row.get('add_lucky_value') or 0)
        except (TypeError, ValueError):
            add = 0
        if add:
            shave = max(self._zuoqi_java_round(add / 90.0), 1)
            max_times -= shave
            min_times -= shave
        try:
            lucky = int(row.get('lucky_value') or 0)
            fails = int(row.get('fail_count') or 0)
        except (TypeError, ValueError):
            return False
        if lucky >= lvl['upgrade_zhufu']:
            return True
        if fails < min_times:
            return False
        if fails >= max_times:
            return True
        return self._zuoqi_is_success(lvl['odds'])

    def _zuoqi_upgrade_fail(self, role, rid, row, lvl, role_level):
        """upgradeFailOperate: pity up, fail exp, or [0, -1] at the cap.

        Returns ([type, exp], granted, extra): the baoji roll pays role
        exp through the shared level-up path (12001 notice plus any
        level-up refreshes in extra), and lucky caps at upgradeZhufu.
        """
        try:
            fails = int(row.get('fail_count') or 0)
            lucky = int(row.get('lucky_value') or 0)
            total = int(row.get('total_exp') or 0)
        except (TypeError, ValueError):
            fails, lucky, total = 0, 0, 0
        row['fail_count'] = fails + 1
        add = self._zuoqi_random_int(lvl['min_zhufu'], lvl['max_zhufu'])
        row['lucky_value'] = min(lucky + add, lvl['upgrade_zhufu'])
        if total >= self.config.zhujue_zq_fail_max_exp(role_level):
            return [0, -1], False, []
        rates = self.config.zuoqi_fail_rates(
            row.get('zuoqi_rank'), lvl['level'])
        roll = random.random() * sum(r for _, r, _ in rates) \
            if rates else 0
        pick, exp = 0, 0
        for kind, rate, value in rates:
            roll -= rate
            if roll < 0:
                pick, exp = kind, value
                break
        row['total_exp'] = total + exp
        try:
            _total, _level, _gained, exp_frames = \
                self._role_gain_exp(role, rid, exp)
        except Exception:
            return [pick, exp], True, []
        return [pick, exp], True, exp_frames

    def zuoqi_jinjie(self, msg):
        """Command 33003: bless/advance the mount (upgradeRank).

        C> is an Integer auto-buy flag (other shapes stay silent like the
        action's early return). Gates answer [0, error], consumed materials
        [0, code], success the panel shape plus the 11101 [520013, ...]
        notice when the new level row wants one, failure
        [-1, lucky, type, exp, 0] with the 12001 exp notice ahead of it.
        Events ride no bus, like the other ported upgrade flows.
        """
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        data = self.safe(msg, 1, None)
        if isinstance(data, bool) or not isinstance(data, int) or \
                data not in (0, 1):
            return None
        auto_buy = data == 1
        row = self._zuoqi_row(rid)
        if row is None:
            return None
        row = self._zuoqi_timer(rid, row)
        try:
            rank = int(row.get('zuoqi_rank') or 0)
        except (TypeError, ValueError):
            rank = 0
        cfg = self.config.zuoqi_rank_config(rank)
        if cfg is None:
            return None
        level = self._task_role_level(role)
        gate = self._zuoqi_can_upgrade(role, row, cfg)
        if gate is not None:
            return frame(amf3_encode(
                [str(CMD_ZUOQI_JINJIE), [0, gate]]))
        decr, mall_money = self._zuoqi_material_plan(
            rid, role, cfg, rank, auto_buy) if cfg['cailiao_id'] \
            else ({}, {})
        if decr is None:
            return frame(amf3_encode(
                [str(CMD_ZUOQI_JINJIE), [0, mall_money]]))
        try:
            free = int(row.get('free_jb') or 0)
        except (TypeError, ValueError):
            free = 0
        if free != 1 and not self._bag_money_check(
                role, 'YXB', cfg['upgrade_jb']):
            return frame(amf3_encode(
                [str(CMD_ZUOQI_JINJIE), [0, GENERAL_JB]]))
        for gid, take in decr.items():
            self._prop_take(rid, gid, take)
        if free != 1 and cfg['upgrade_jb']:
            self._bag_money_decr(rid, 'YXB', cfg['upgrade_jb'])
        # ZuoQiUtil.addCostCount: every attempt banks the rank's full
        # cailiao count under the current rank, win or lose.
        self._zuoqi_add_cost(row, rank, cfg['cailiao_count'])
        for money_type, total in mall_money.items():
            name = MALL_MONEY_NAMES.get(money_type)
            if name is not None and total:
                self._bag_money_decr(rid, name, total)
        lvl = self.config.zuoqi_level_config(
            rank, self._zuoqi_level(level, cfg))
        if lvl is None:
            return None
        now = int(time.time() * 1000)
        if self._zuoqi_upgrade_success(row, lvl, level):
            success = True
            ret = None
        else:
            ret, granted, exp_frames = self._zuoqi_upgrade_fail(
                role, rid, row, lvl, level)
            try:
                lucky_now = int(row.get('lucky_value') or 0)
            except (TypeError, ValueError):
                lucky_now = 0
            success = lucky_now >= lvl['upgrade_zhufu']
        if success:
            row.update(fail_count=0, lucky_value=0, add_lucky_value=0,
                       lucky_goods_id=None, lucky_goods_expire_time=0,
                       zuoqi_rank=rank + 1, zuoqi_cur_rank=rank + 1,
                       update_time=now)
            self._zuoqi_save(rid, row)
            new_cfg = self.config.zuoqi_rank_config(rank + 1)
            new_level = self._zuoqi_level(
                level, new_cfg) if new_cfg is not None else 0
            new_lvl = self.config.zuoqi_level_config(rank + 1, new_level)
            reply = [1, [rank + 1, new_level, 0,
                         self.config.zuoqi_fight(rank + 1, level)],
                     [], self._zuoqi_in_kaifu(rank + 1), 0]
            frames = []
            if new_lvl is not None and new_lvl['notice'] and \
                    new_cfg is not None:
                frames.append(frame(amf3_encode(
                    [str(CMD_NOTICE_ALL),
                     [self.ZUOQI_NOTICE_CODE,
                      [str(role.get('name')), rank + 1,
                       new_cfg['name']]]])))
            frames.append(frame(amf3_encode(
                [str(CMD_ZUOQI_JINJIE), reply])))
            return tuple(frames) if len(frames) > 1 else frames[0]
        row['update_time'] = now
        self._zuoqi_save(rid, row)
        try:
            lucky_now = int(row.get('lucky_value') or 0)
        except (TypeError, ValueError):
            lucky_now = 0
        # Slot 4 is getUpgradeCostCount for the fanhuan rank, not 0.
        cost = 0
        fanhuan = self.config.kaifu_zuoqi_fanhuan()
        if fanhuan is not None:
            cost = self._zuoqi_cost_count(row, fanhuan['rank'])
        reply = frame(amf3_encode(
            [str(CMD_ZUOQI_JINJIE),
             [-1, lucky_now, ret[0], ret[1], cost]]))
        if granted:
            return (*exp_frames, reply)
        return reply

    def _bag_money_check(self, role, money, amount):
        """AccountServiceImpl decrCheck for one MoneyType: balance covers it."""
        column = BAG_MONEY_COLUMNS[money]
        try:
            return int((role or {}).get(column) or 0) >= amount
        except (TypeError, ValueError):
            return False

    def bag_lock_vo(self, state, kind, max_slot):
        """Next-slot unlock VO for 30000, or None at max capacity.

        Port of BagServiceImpl.getBagLockIndexVos/getStorageLockIndexVos:
        [configNum, nowMs + remainingMs] where remainingMs is the slot's
        openTime (seconds) minus the time already grown, clamped at 0. The
        grown time is now - updateSlotTime: Java takes max(onlineTime,
        updateSlotTime) but online time is not tracked here, which is exactly
        Java's null-onlineTime branch. A missing state row uses the init
        slot count (live rows prove 34/30 for fresh roles).
        """
        stype = 'B' if kind == 'bag' else 'C'
        cap_key = 'bag_capacity' if kind == 'bag' else 'storage_capacity'
        slot_key = 'bag_slot_time' if kind == 'bag' else 'storage_slot_time'
        update_key = ('bag_update_slot_time' if kind == 'bag'
                      else 'storage_update_slot_time')
        try:
            capacity = int(state.get(cap_key) or 0)
        except (TypeError, ValueError):
            capacity = 0
        if self.config is None:
            return None
        if not state:
            capacity = self.config.kaige_init_slot_num(stype)
        if capacity >= max_slot:
            return None
        row = self.config.kaige_row(stype, capacity + 1)
        if row is None:
            return None
        try:
            open_ms = int(float(row.get('needtime') or 0) * 1000)
            slot_time = int(state.get(slot_key) or 0)
            update_time = int(state.get(update_key) or 0)
        except (TypeError, ValueError):
            return None
        now_ms = int(time.time() * 1000)
        grown_ms = max(now_ms - update_time, 0)
        remaining_ms = max(open_ms - (grown_ms + slot_time), 0)
        return [capacity + 1, now_ms + remaining_ms]

    def bag_goods_map(self, role, slot):
        """One StoreGoodsOutput.formart map (keys '0'..'17') for a bag row.

        Keys mirror the 18 formart1 slots (see equip_record). Only the
        row's own category branch parses attributes: equip ('20') reads the
        GoodsEquipVo, skillbook ('100') and jingyanyu ('108') read the exp
        cell, shenqi ('107') the lucky cell. The exp/lucky attribute keys
        are unverified (no legacy row exercises them), so they default to 0.
        """
        category = (self.config.goods_category(slot.get('goods_id'))
                    if self.config else None)
        vo = None
        if category == '20' and slot.get('attributes'):
            try:
                vo = equip_vo(slot.get('attributes'))
            except Exception:
                vo = None
        fight = (self.config.equip_item_fight(slot)
                 if self.config is not None and vo is not None else 0)
        exp_val = self._bag_exp_cell(slot) if category in ('100', '108') else 0
        return {
            '0': str(slot.get('goods_id')),                 # goodsId
            '1': str(slot.get('bag_id') or slot.get('goods_id')),  # id
            '2': slot.get('slot_num'),                      # slotNum
            '3': slot.get('count') or 0,                    # count
            '4': str(role.get('id')),                       # userRoleId
            '5': slot.get('item_level') or 0,               # itemLevel
            '6': slot.get('rare_level') or 0,               # rareLevel
            '7': slot.get('bind') or 0,                     # bind
            '8': slot.get('expire_time'),                   # expireTime
            '9': _fujia_wire(fujia_client_map(vo)) if vo is not None else None,
            '10': xingxing_lv(vo) if vo is not None else 0,  # xingxingLv
            '11': None,
            '12': fight,                                    # zhanli
            '13': '',
            '14': qh_xingxings_client(vo) if vo is not None else None,
            '15': exp_val if category == '100' else 0,      # exp (Long)
            '16': 0,                                        # luckyValue
            '17': exp_val if category == '108' else 0,      # jingyan exp
        }

    @staticmethod
    def _bag_exp_cell(slot):
        """Exp cell from a skillbook/jingyanyu attributes blob, else 0."""
        try:
            data = json.loads(slot.get('attributes') or '')
        except (TypeError, ValueError):
            return 0
        if not isinstance(data, dict):
            return 0
        try:
            return int(data.get('exp') or 0)
        except (TypeError, ValueError):
            return 0

    def ping(self):
        """Command 19000: IoCommands.PING -> PingVo.genInterval().

        A random heartbeat interval, 5000 + Random.nextInt(5000) ms; the
        capture's values (6830, 8265, 9018) all fall in [5000, 9999].
        """
        return frame(amf3_encode(['19000', 5000 + random.randrange(5000)]))

    def vip_info(self):
        """Command 62000: GetVipOutPut.getVipInfo's Object[5].

        [stateDay, stateWeek, [[tejiaKey, value]...], propValue,
        todyPropValue]; day/week are zeroed when vipLevel is 0, and the
        pairs list the role_vip.state_tejia JSON keys (empty when none).
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        vip = self.get_role_vip(role.get('id')) if role is not None else None
        if vip is None:
            return frame(amf3_encode(['62000', [0, 0, [], 0, 0]]))
        if int(vip.get('vip_level') or 0) == 0:
            day, week = 0, 0
        else:
            day, week = int(vip.get('state_day') or 0), int(vip.get('state_week') or 0)
        try:
            tejia = json.loads(vip.get('state_tejia')) if vip.get('state_tejia') else {}
        except ValueError:
            tejia = {}
        pairs = [[k, v] for k, v in tejia.items()] if isinstance(tejia, dict) else []
        return frame(amf3_encode(['62000', [
            day, week, pairs, int(vip.get('prop_value') or 0),
            int(vip.get('tody_prop_value') or 0)]]))

    def mall_info(self, msg):
        """Command 32000: MallServiceImpl.shopList [1, sign, items].

        The request is [sign, category]; Java answers nothing when the
        category is empty, [-1, category] when the client's sign matches
        (the client then uses its cache), else the sign plus the raw
        WuPinChuShouBiao rows of the category.
        """
        args = self.safe(msg, 1, [])
        sign = self.safe(args, 0)
        category = self.safe(args, 1)
        if not category:
            return None
        mall_sign = self.config.mall_sign() if self.config is not None else None
        if sign is not None and sign == mall_sign:
            return frame(amf3_encode(['32000', [-1, category]]))
        items = (self.config.mall_shop_list(category)
                 if self.config is not None else [])
        return frame(amf3_encode(['32000', [1, mall_sign, items]]))

    def dafuweng_info(self, msg):
        """105003: the dafuweng sign and its three config tables (no role state)."""
        reply = self.config.dafuweng_reply() if self.config is not None else None
        if reply is None:
            return None
        return frame(amf3_encode(['105003', reply]))

    def _dafuwong_row(self, rid):
        """RoleDafuwong row: online() creates, clear() resets daily/weekly.

        A missing row starts at zeros with today's stamp. Otherwise a new
        day zeroes slot and both roll counters, a new ISO week zeroes the
        zanshi stamps, and tongqianCount always resets for the new day,
        mirroring clear(). The stamp always advances to now.
        """
        now = int(time.time() * 1000)
        try:
            row = self.get_role_dafuwong(rid)
        except Exception:
            row = None
        if not row:
            row = {'slot': 0, 'grade': 0, 'zanshi': 0, 'roll_count': 0,
                   'tongqian_count': 0, 'last_roll_ms': now}
            try:
                self.save_role_dafuwong(rid, **row)
            except Exception:
                pass
            return dict(row)
        row = dict(row)
        try:
            last = int(row.get('last_roll_ms') or 0)
        except (TypeError, ValueError):
            last = 0
        if self._same_day_ms(now, last):
            for key in ('slot', 'grade', 'zanshi', 'roll_count',
                        'tongqian_count'):
                try:
                    row[key] = int(row.get(key) or 0)
                except (TypeError, ValueError):
                    row[key] = 0
            return row
        row['slot'] = 0
        row['roll_count'] = 0
        row['tongqian_count'] = 0
        if self._dafuwong_week_changed(last, now):
            row['zanshi'] = 0
        else:
            try:
                row['zanshi'] = int(row.get('zanshi') or 0)
            except (TypeError, ValueError):
                row['zanshi'] = 0
        try:
            row['grade'] = int(row.get('grade') or 0)
        except (TypeError, ValueError):
            row['grade'] = 0
        row['last_roll_ms'] = now
        try:
            self.save_role_dafuwong(rid, **row)
        except Exception:
            pass
        return row

    @staticmethod
    def _dafuwong_week_changed(last_ms, now_ms):
        """Approximate DatatimeUtil.dayIsToWeek with the ISO week
        (server-local); Java's Calendar week may differ at year edges."""
        try:
            old = time.localtime(int(last_ms or 0) / 1000)
            new = time.localtime(int(now_ms or 0) / 1000)
        except (TypeError, ValueError, OverflowError):
            return True
        if old.tm_year != new.tm_year:
            return True
        try:
            return time.strftime('%V', old) != time.strftime('%V', new)
        except (TypeError, ValueError):
            return True

    def dafuwong_info(self, msg):
        """105000: getDaFuWongInfo [slot, grade, zanshi, count,
        tongqianCount, isChongZhi].

        The recharge flag has no local ledger (like vipqq's charge_total),
        so it answers False.
        """
        role = self._equip_role()
        if role is None:
            return None
        row = self._dafuwong_row(role.get('id'))
        return frame(amf3_encode([str(CMD_DAFUWONG_INFO), [
            row['slot'], row['grade'], row['zanshi'], row['roll_count'],
            row['tongqian_count'], False]]))

    def _dafuwong_lottery(self, rid, row, roll_type, zhubiao):
        """One lottery() draw: [dice, slot, zanshiBull, [[id, count]]].

        A d7 moves the piece, capped at the last board slot (lapping
        resets to 0). Type 1 banks grade points, type 2 grants the slot's
        item list, type 3 banks zanshi stamps and converts full sets into
        the zanshi gift. Returns None when the landing slot has no row.
        """
        try:
            slot = int(row.get('slot') or 0)
        except (TypeError, ValueError):
            slot = 0
        try:
            top = max(zhubiao)
        except (TypeError, ValueError):
            return None
        dice = random.randint(1, 7)
        if slot + dice > top:
            dice = top - slot
            slot = top
        else:
            slot += dice
        cfg = zhubiao.get(slot)
        if cfg is None:
            return None
        try:
            kind = int(cfg.get('itemtype') or 0)
        except (TypeError, ValueError):
            kind = 0
        items, bull = [], False
        if kind == 1:
            try:
                row['grade'] = int(row.get('grade') or 0) + \
                    int(cfg.get('item') or 0)
            except (TypeError, ValueError):
                pass
        elif kind == 2:
            for gid, count, _bind in self.config.parse_goods_string(
                    cfg.get('item')):
                items.append([gid, count])
            self._task_grant(rid, [{
                'goods_id': gid, 'count': count, 'bind': bind}
                for gid, count, bind in self.config.parse_goods_string(
                    cfg.get('item'))])
        elif kind == 3:
            try:
                row['zanshi'] = int(row.get('zanshi') or 0) + \
                    int(cfg.get('item') or 0)
            except (TypeError, ValueError):
                pass
            bull = self._dafuwong_zuanshi(rid, row)
        if roll_type == 1:
            row['tongqian_count'] = int(row.get('tongqian_count') or 0) + 1
        row['roll_count'] = int(row.get('roll_count') or 0) + 1
        row['slot'] = 0 if slot >= top else slot
        shown = top if (roll_type == 3 and row['slot'] == 0) else slot
        return [dice, shown, bull, items]

    def _dafuwong_zuanshi(self, rid, row):
        """Trade full zanshi sets for the zanshi gift; True if any traded."""
        if self.config is None:
            return False
        need, goods = self.config.dafuweng_zuanshi()
        if need <= 0 or not goods:
            return False
        parcels = self.config.parse_pipe_goods_string(goods)
        if not parcels:
            return False
        traded = False
        try:
            have = int(row.get('zanshi') or 0)
        except (TypeError, ValueError):
            have = 0
        while have >= need:
            have -= need
            traded = True
        if not traded:
            return False
        row['zanshi'] = have
        self._task_grant(rid, [{
            'goods_id': gid, 'count': count, 'bind': bind}
            for gid, count, bind in parcels])
        return True

    def dafuwong_roll(self, msg):
        """105001: yaoJiang(type) dice roll (1 coin, 2 gold, 3 ten-gold).

        Prices come from the jiage drop (coin rolls also need enough free
        rolls left for the vip level); short funds answer the General
        errors, an empty board 792005. Single rolls reply [1, dice, slot,
        zanshi, grade, zanshiBull, count, tongqianCount, null]; the
        ten-roll replies the same shape with the last draw plus the ten
        landing slots. A bad type is silent like Java's null.
        """
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        try:
            roll_type = int(str(self.safe(self.safe(msg, 1, []), 0)))
        except (TypeError, ValueError):
            return None
        if roll_type not in (1, 2, 3):
            return None
        rid = role.get('id')
        zhubiao = self.config.dafuweng_zhubiao()
        if not zhubiao:
            return frame(amf3_encode(
                [str(CMD_DAFUWONG_ROLL), [0, DAFUWONG_ERR_NOBOARD]]))
        row = self._dafuwong_row(rid)
        if roll_type == 1:
            try:
                level = int((self.get_role_vip(rid) or {}).get('vip_level')
                            or 0)
            except Exception:
                level = 0
            if int(row.get('tongqian_count') or 0) >= \
                    self.config.vip_dafuwong_rolls(level):
                return frame(amf3_encode(
                    [str(CMD_DAFUWONG_ROLL),
                     [0, DAFUWONG_ERR_VIPROLLS]]))
            money = 'YXB'
            price = self.config.dafuweng_roll_price(
                1, int(row.get('tongqian_count') or 0) + 1)
        elif roll_type == 2:
            money = 'YB'
            price = self.config.dafuweng_roll_price(
                2, int(row.get('roll_count') or 0) + 1)
        else:
            money, price = 'YB', 100
        if price is None:
            return None
        if not self._bag_money_check(role, money, price):
            return frame(amf3_encode(
                [str(CMD_DAFUWONG_ROLL),
                 [0, GENERAL_JB if money == 'YXB' else GENERAL_YB]]))
        self._bag_money_decr(rid, money, price)
        if roll_type in (1, 2):
            draw = self._dafuwong_lottery(rid, row, roll_type, zhubiao)
            if draw is None:
                return None
            dice, slot, bull, items = draw
            extra = None
        else:
            slots, bull, dice = [], False, 0
            for _ in range(10):
                draw = self._dafuwong_lottery(rid, row, roll_type, zhubiao)
                if draw is None:
                    return None
                dice, slot, bull, _items = draw
                slots.append(slot)
            extra = slots
        row['last_roll_ms'] = int(time.time() * 1000)
        try:
            self.save_role_dafuwong(
                rid, slot=row['slot'], grade=row['grade'],
                zanshi=row['zanshi'], roll_count=row['roll_count'],
                tongqian_count=row['tongqian_count'],
                last_roll_ms=row['last_roll_ms'])
        except Exception:
            pass
        return frame(amf3_encode([str(CMD_DAFUWONG_ROLL), [
            1, dice, row['slot'], row['zanshi'], row['grade'], bull,
            row['roll_count'], row['tongqian_count'], extra]]))

    def _bag_goods_count(self, rid, goods_id):
        """Total count of one goods id across bag slots."""
        try:
            slots = self.get_role_bag_slots(rid, -1000000, 1000000) or []
        except Exception:
            return 0
        have = 0
        for s in slots:
            try:
                if str(s.get('goods_id')) == str(goods_id):
                    have += int(s.get('count') or 0)
            except (TypeError, ValueError):
                continue
        return have

    def dafuwong_exchange(self, msg):
        """105002: duiHuan(id) swaps grade points (page 1) or yushi goods
        (page 2) for the exchange-list item.

        Short points answer 105000, short goods 1005, a full bag 1006, and
        success [1, id]. An unknown id is silent like Java's loadById
        null. Events need a bus.
        """
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        try:
            did = str(self.safe(self.safe(msg, 1, []), 0))
        except (TypeError, ValueError):
            return None
        entry = self.config.dafuweng_duihuan(did)
        if entry is None:
            return None
        jifen, decr_map, grants = entry
        rid = role.get('id')
        row = self._dafuwong_row(rid)
        if int(row.get('grade') or 0) < jifen:
            return frame(amf3_encode(
                [str(CMD_DAFUWONG_EXCHANGE), [0, DAFUWONG_ERR_JIFEN]]))
        for gid, count in decr_map.items():
            if self._bag_goods_count(rid, gid) < count:
                return frame(amf3_encode(
                    [str(CMD_DAFUWONG_EXCHANGE), [0, GENERAL_GOODS]]))
        for gid, count, bind in grants:
            if not self._prop_fits(rid, {'goods': gid, 'count': count},
                                   bind):
                return frame(amf3_encode(
                    [str(CMD_DAFUWONG_EXCHANGE), [0, GENERAL_NOSLOT]]))
        try:
            self.save_role_dafuwong(
                rid, grade=int(row.get('grade') or 0) - jifen)
        except Exception:
            return frame(amf3_encode(
                [str(CMD_DAFUWONG_EXCHANGE), [0, GENERAL_GOODS]]))
        for gid, count in decr_map.items():
            self._bag_decr(rid, gid, count)
        self._task_grant(rid, [{'goods_id': gid, 'count': count,
                                'bind': bind}
                               for gid, count, bind in grants])
        return frame(amf3_encode([str(CMD_DAFUWONG_EXCHANGE), [1, did]]))

    @staticmethod
    def _xsbuy_today():
        """Server-local day stamp for the xianshibuy daily reset."""
        return time.strftime('%Y-%m-%d', time.localtime())

    def _xianshibuy_data(self, rid):
        """Role buy map {id: [count, lastMs, cdMs]}: online() + clear().

        A missing row starts empty; a stale day resets the map. Like
        Java's online(), every surviving entry's last-buy stamp refreshes
        to now on read.
        """
        now = int(time.time() * 1000)
        try:
            row = self.get_role_xianshibuy(rid)
        except Exception:
            row = None
        data = {}
        if row:
            if (row.get('buy_day') or '') != self._xsbuy_today():
                try:
                    self.save_role_xianshibuy(
                        rid, buy_data='{}', buy_day=self._xsbuy_today())
                except Exception:
                    pass
                return {}
            try:
                parsed = json.loads(row.get('buy_data') or '{}')
            except (TypeError, ValueError):
                parsed = {}
            if isinstance(parsed, dict):
                for key, val in parsed.items():
                    if isinstance(val, list) and len(val) >= 3:
                        try:
                            data[str(key)] = [int(val[0]), now,
                                             int(val[2])]
                        except (TypeError, ValueError):
                            continue
        else:
            try:
                self.save_role_xianshibuy(rid, buy_data='{}',
                                         buy_day=self._xsbuy_today())
            except Exception:
                pass
        return data

    def _xianshibuy_save(self, rid, data):
        """Persist the role buy map."""
        try:
            self.save_role_xianshibuy(
                rid, buy_data=json.dumps(data),
                buy_day=self._xsbuy_today())
        except Exception:
            pass

    def _xsbuy_sold(self):
        """Server-wide {id: sold} map (the XianshiBuy singleton row)."""
        try:
            row = self.get_xianshi_buy()
        except Exception:
            row = None
        try:
            parsed = json.loads((row or {}).get('buy_data') or '{}')
        except (TypeError, ValueError):
            parsed = {}
        sold = {}
        if isinstance(parsed, dict):
            for key, val in parsed.items():
                try:
                    sold[str(key)] = int(val)
                except (TypeError, ValueError):
                    continue
        return sold

    def _xsbuy_add_sold(self, sid):
        """Bump the server-wide sold count for one shop id."""
        sold = self._xsbuy_sold()
        try:
            sold[str(sid)] = int(sold.get(str(sid)) or 0) + 1
        except (TypeError, ValueError):
            sold[str(sid)] = 1
        try:
            self.save_xianshi_buy(json.dumps(sold))
        except Exception:
            pass
        return sold

    @staticmethod
    def _xsbuy_day_end_ms(base_ms, days):
        """Local midnight after base-day plus days (Calendar +24:00)."""
        try:
            local = time.localtime(int(base_ms or 0) / 1000)
        except (TypeError, ValueError, OverflowError):
            return 0
        try:
            midnight = time.mktime((local.tm_year, local.tm_mon,
                                    local.tm_mday, 0, 0, 0, 0, 0, -1))
        except (TypeError, ValueError, OverflowError):
            return 0
        return int((midnight + (int(days) + 1) * 86400) * 1000)

    def _xsbuy_check_time(self, cfg, ts_ms, days, start):
        """XianShiBuyConfig.checkTime against a server/hefu start stamp."""
        try:
            ts = int(ts_ms or 0)
        except (TypeError, ValueError):
            ts = 0
        if cfg['hefudays'] == 0 and cfg['kaifudays'] == 0 and \
                cfg['start_ms'] == 0 and cfg['end_ms'] == 0 and \
                cfg['hefustart'] == 0 and cfg['startday'] == 0:
            return True
        now = int(time.time() * 1000)
        if days > 0 and \
                now <= self._xsbuy_day_end_ms(ts, days):
            return True
        if start > 0:
            low = self._xsbuy_day_end_ms(ts, start)
            return now <= cfg['end_ms'] and now >= cfg['start_ms'] \
                and now >= low
        if start != 0:
            return False
        if cfg['start_ms'] > 0 and cfg['end_ms'] > 0:
            return cfg['start_ms'] <= now <= cfg['end_ms']
        return False

    @staticmethod
    def _xsbuy_hm_ge(first, second):
        """XianShiBuyConfig.compare: HH:mm first at or after second."""
        try:
            h1, m1 = [int(x) for x in str(first).split(':')[:2]]
            h2, m2 = [int(x) for x in str(second).split(':')[:2]]
        except (TypeError, ValueError):
            return False
        return h1 > h2 or (h1 == h2 and m1 >= m2)

    def _xsbuy_is_buy(self, cfg):
        """XianShiBuyConfig.isBuy: open window and inside the HH:mm slot."""
        try:
            server_ms = int(self.server_start_ms or 0) or None
        except (TypeError, ValueError):
            server_ms = None
        window_ok = (server_ms is not None and self._xsbuy_check_time(
            cfg, server_ms, cfg['kaifudays'], cfg['startday']))
        if not window_ok:
            return False
        window = cfg.get('window') or []
        if len(window) != 2:
            return False
        now_hm = time.strftime('%H:%M', time.localtime())
        return self._xsbuy_hm_ge(now_hm, window[0]) and \
            self._xsbuy_hm_ge(window[1], now_hm)

    def _xsbuy_role_cd(self, data, sid):
        """Remaining personal cooldown ms for one shop id."""
        try:
            entry = data.get(str(sid))
        except (TypeError, ValueError):
            return 0
        if not isinstance(entry, list) or len(entry) < 3:
            return 0
        try:
            return max(0, int(entry[2]) -
                       (int(time.time() * 1000) - int(entry[1])))
        except (TypeError, ValueError):
            return 0

    def _xsbuy_type_cd(self, data, shop_type):
        """Remaining cooldown of the first same-type entry with a cd."""
        for key in data:
            cfg = self.config.xianshishop_row(key) \
                if self.config is not None else None
            if cfg is None or int(cfg.get('type') or 0) != shop_type:
                continue
            try:
                cd = int((data.get(key) or [0, 0, 0])[2])
            except (TypeError, ValueError):
                continue
            if cd > 0 and self._xsbuy_role_cd(data, key) > 0:
                return self._xsbuy_role_cd(data, key)
        return 0

    def xianshibuy_client(self, msg):
        """119000: XianshibuyServiceImpl.getClientData (raw shop rows).

        Silent when no xianshishop drop is published, like the other
        published-table families.
        """
        if self.config is None:
            return None
        rows = self.config.xianshishop_table()
        if not rows:
            return None
        return frame(amf3_encode(
            [str(CMD_XIANSHIBUY_CLIENT),
             [r.get('client') for r in rows]]))

    def _xianshibuy_entry(self, sid, sold, data):
        """One 119001 row: [id, serverSold, roleCount, cdExpiryMs]."""
        try:
            count = int((data.get(str(sid)) or [0])[0])
        except (TypeError, ValueError):
            count = 0
        return [str(sid), int(sold.get(str(sid)) or 0), count,
                int(time.time() * 1000) + self._xsbuy_role_cd(data, sid)]

    def xianshibuy_info(self, msg):
        """119001: getInfo [1, [[id, serverSold, roleCount, cdMs]...]].

        Ids union the role's bought ids with the server-sold ids, like
        getIds().
        """
        role = self._equip_role()
        if role is None:
            return None
        data = self._xianshibuy_data(role.get('id'))
        sold = self._xsbuy_sold()
        ids = list(data)
        for key in sold:
            if key not in data:
                ids.append(key)
        return frame(amf3_encode([str(CMD_XIANSHIBUY_INFO),
                                  [1, [self._xianshibuy_entry(sid, sold,
                                                             data)
                                       for sid in ids]]]))

    def xianshibuy_buy(self, msg):
        """119002: buy(id) for the timed shop.

        Closed window answers 119000, server cap 119001, personal cap
        119002, shared-type cooldown 119003, a full bag 1006 and short
        gold 1002. Success grants the first itmeid parcel, bumps both
        counters and replies [1, id] plus the buyer's own 119001 push;
        the server-wide 119001 broadcast needs a bus.
        """
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        try:
            sid = str(self.safe(self.safe(msg, 1, []), 0))
        except (TypeError, ValueError):
            return None
        cfg = self.config.xianshishop_row(sid)
        if cfg is None:
            return None
        if not self._xsbuy_is_buy(cfg):
            return frame(amf3_encode(
                [str(CMD_XIANSHIBUY_BUY), [0, XSBUY_ERR_CLOSED]]))
        sold = self._xsbuy_sold()
        if int(sold.get(sid) or 0) >= cfg['smax']:
            return frame(amf3_encode(
                [str(CMD_XIANSHIBUY_BUY), [0, XSBUY_ERR_SOLDOUT]]))
        rid = role.get('id')
        data = self._xianshibuy_data(rid)
        try:
            bought = int((data.get(sid) or [0])[0])
        except (TypeError, ValueError):
            bought = 0
        if bought >= cfg['pmax']:
            return frame(amf3_encode(
                [str(CMD_XIANSHIBUY_BUY), [0, XSBUY_ERR_PMAX]]))
        if self._xsbuy_type_cd(data, int(cfg.get('type') or 0)) != 0:
            return frame(amf3_encode(
                [str(CMD_XIANSHIBUY_BUY), [0, XSBUY_ERR_CD]]))
        if not cfg.get('grants'):
            return None
        gid, count, bind = cfg['grants'][0]
        if not self._prop_fits(rid, {'goods': gid, 'count': count}, bind):
            return frame(amf3_encode(
                [str(CMD_XIANSHIBUY_BUY), [0, GENERAL_NOSLOT]]))
        if not self._bag_money_check(role, 'YB', cfg['price']):
            return frame(amf3_encode(
                [str(CMD_XIANSHIBUY_BUY), [0, GENERAL_YB]]))
        self._bag_money_decr(rid, 'YB', cfg['price'])
        now = int(time.time() * 1000)
        data[sid] = [bought + 1, now, cfg['cd']]
        self._xianshibuy_save(rid, data)
        self._task_grant(rid, [{'goods_id': gid, 'count': count,
                               'bind': bind}])
        sold = self._xsbuy_add_sold(sid)
        push = frame(amf3_encode([str(CMD_XIANSHIBUY_INFO),
                                  [1, [self._xianshibuy_entry(
                                      sid, sold, data)]]]))
        return (frame(amf3_encode([str(CMD_XIANSHIBUY_BUY), [1, sid]])),
                push)

    def xianshibuy_clearcd(self, msg):
        """119003: clearCd(id) wipes the personal cooldown for gold.

        Unknown or cooldown-free ids answer 119004, short gold 1002.
        Success replies [1, id] plus the buyer's own 119001 push.
        """
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        try:
            sid = str(self.safe(self.safe(msg, 1, []), 0))
        except (TypeError, ValueError):
            return None
        rid = role.get('id')
        data = self._xianshibuy_data(rid)
        if sid not in data or self._xsbuy_role_cd(data, sid) == 0:
            return frame(amf3_encode(
                [str(CMD_XIANSHIBUY_CLEARCD), [0, XSBUY_ERR_NOCD]]))
        cfg = self.config.xianshishop_row(sid)
        if cfg is None:
            return None
        if not self._bag_money_check(role, 'YB', cfg['consume']):
            return frame(amf3_encode(
                [str(CMD_XIANSHIBUY_CLEARCD), [0, GENERAL_YB]]))
        self._bag_money_decr(rid, 'YB', cfg['consume'])
        try:
            count = int((data.get(sid) or [0])[0])
        except (TypeError, ValueError):
            count = 0
        data[sid] = [count, int(time.time() * 1000), 0]
        self._xianshibuy_save(rid, data)
        sold = self._xsbuy_sold()
        push = frame(amf3_encode([str(CMD_XIANSHIBUY_INFO),
                                  [1, [self._xianshibuy_entry(
                                      sid, sold, data)]]]))
        return (frame(amf3_encode([str(CMD_XIANSHIBUY_CLEARCD),
                                   [1, sid]])),
                push)

    def shenjiang_slot_info(self, msg):
        """Command 41023: ShenJiangSlotServiceImpl.getInfo answers [1, id, slots].

        Slots come from role_shenjiang_slot, which the legacy data leaves
        empty (its MYD is 0 bytes) and Python never writes, so the slot list
        is always null, as Java answers for a role without slot rows. A
        non-string id is silent, like Java's String cast.
        """
        data = self.safe(msg, 1)
        if data is not None and not isinstance(data, str):
            return None
        return frame(amf3_encode([str(CMD_SHENJIANG_INFO), [1, data, None]]))

    def qiandao_info(self):
        """Command 58011: JiangliServiceImpl.getQiandaoInfo answers the sign-in row.

        A missing RoleQiandao answers Java's fixed [1, null, 0, null, null];
        a row returns its month days and both reward strings, comma-split by
        QiandaoOutput.toInteger/toString.
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        row = None
        if role is not None:
            try:
                row = self.get_role_qiandao(role.get('id'))
            except Exception:
                row = None
        if row is None:
            return frame(amf3_encode([str(CMD_QIANDAO_INFO),
                                      [1, None, 0, None, None]]))
        return frame(amf3_encode([
            str(CMD_QIANDAO_INFO),
            [1, _qiandao_ints(row.get('month_qiandao')),
             row.get('total_qiandao_count'),
             _qiandao_strings(row.get('month_qiandao_reward')),
             _qiandao_strings(row.get('total_qiandao_reward'))]]))

    @staticmethod
    def _qiandao_today():
        """Calendar.DAY_OF_MONTH for the sign-in day clocks."""
        return time.localtime().tm_mday

    @staticmethod
    def _qiandao_weekday(day=None):
        """Calendar.DAY_OF_WEEK - 1 (Sunday 0) for today or a month day."""
        now = time.localtime()
        if day is None:
            return (now.tm_wday + 1) % 7
        try:
            stamp = time.mktime((now.tm_year, now.tm_mon, int(day),
                                 0, 0, 0, 0, 0, -1))
        except (TypeError, ValueError, OverflowError):
            return -1
        return (time.localtime(stamp).tm_wday + 1) % 7

    @staticmethod
    def _qiandao_has(ids_text, token):
        """checkIds: comma membership; a null/empty list never matches."""
        if not ids_text:
            return False
        return str(token) in [s for s in str(ids_text).split(',')
                              if s != '']

    @staticmethod
    def _qiandao_mark(ids_text, token):
        """setIds: append the token to the comma list."""
        if not ids_text:
            return str(token)
        return str(ids_text) + ',' + str(token)

    @staticmethod
    def _qiandao_same_day(stamp_ms):
        """DateUtils.isSameDay over the stored qiandao_time."""
        try:
            when = time.localtime(int(stamp_ms or 0) // 1000)
        except (TypeError, ValueError, OverflowError):
            return False
        now = time.localtime()
        return (when.tm_year, when.tm_mon, when.tm_mday) == \
            (now.tm_year, now.tm_mon, now.tm_mday)

    def _qiandao_vip_config(self, vip_level):
        """First category-3 qiandao config with the role's vip level."""
        if self.config is None:
            return None
        try:
            configs = self.config.qiandao_tables().get(3, {})
        except Exception:
            return None
        for cfg in configs.values():
            if cfg.get('vip_level') == vip_level:
                return cfg
        return None

    def _qiandao_grant_weekend(self, rid, cfg, weekday):
        """Weekend vip sign-in goods via putInBagOrEmail's bag half.

        The mail fallback has no bus here, so overflow only logs like the
        quest-grant path; the weekend event tail is logged, not published.
        """
        if cfg is None or weekday not in (cfg.get('week1'),
                                          cfg.get('week2')):
            return
        rewards = cfg.get('rewards') or []
        if not rewards:
            return
        self._task_grant(rid, [{'goods_id': gid, 'count': count,
                                'bind': bind}
                               for gid, count, bind in rewards])
        log.info('conn %d: qiandao weekend vip goods %r (mail skipped)',
                 self.conn_id, cfg.get('id'))

    def qiandao_sign(self):
        """Command 58012: JiangliServiceImpl.qiandao signs today in.

        A missing row is created at total 1; a same-day row answers
        [0, '592000']. Otherwise the total bumps, today marks, vip
        weekend goods grant, and the reply is QiandaoOutput.qiandao [1].
        Both Jiangli events have no bus here, so that tail is logged.
        """
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        try:
            row = self.get_role_qiandao(rid)
        except Exception:
            row = None
        today = self._qiandao_today()
        now_ms = self._online_now_ms()
        if row is None:
            fields = {'total_qiandao_count': 1,
                      'month': time.localtime().tm_mon,
                      'month_qiandao': str(today),
                      'total_qiandao_reward': '',
                      'month_qiandao_reward': '', 'week': today,
                      'qiandao_time': now_ms}
            try:
                self.save_role_qiandao(rid, **fields)
            except Exception:
                return None
            row = dict(fields)
        else:
            if self._qiandao_same_day((row or {}).get('qiandao_time')):
                return frame(amf3_encode(
                    [str(CMD_QIANDAO_SIGN),
                     [0, QIANDAO_ERR_NOT_REPEAT]]))
            row = dict(row or {})
            try:
                total = int(row.get('total_qiandao_count') or 0) + 1
            except (TypeError, ValueError):
                total = 1
            fields = {'total_qiandao_count': total,
                      'qiandao_time': now_ms,
                      'month_qiandao': self._qiandao_mark(
                          row.get('month_qiandao'), today)}
            try:
                self.save_role_qiandao(rid, **fields)
            except Exception:
                return None
            row.update(fields)
        vip_level = self._role_vip_level(rid)
        if vip_level:
            self._qiandao_grant_weekend(
                rid, self._qiandao_vip_config(vip_level),
                self._qiandao_weekday())
        log.info('conn %d: qiandao sign total %r (events skipped, no bus)',
                 self.conn_id, row.get('total_qiandao_count'))
        return frame(amf3_encode([str(CMD_QIANDAO_SIGN), [1]]))

    def qiandao_buqian(self, msg):
        """Command 58013: JiangliServiceImpl.buQian retro-signs a past day.

        A non-int day stays silent like Java's cast; a future day answers
        nothing (the null result is never sent). Vip 0 answers [0, 1010],
        a missing vip config [0, '592007'], an already-signed day
        [0, '592010']; success marks, bumps, grants weekend vip goods for
        that day's weekday, and replies [1, day].
        """
        day = self.safe(msg, 1)
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None or isinstance(day, bool) or \
                not isinstance(day, int):
            return None
        if day > self._qiandao_today():
            return None
        try:
            row = self.get_role_qiandao(rid)
        except Exception:
            row = None
        if row is None:
            try:
                self.save_role_qiandao(
                    rid, total_qiandao_count=0,
                    month=time.localtime().tm_mon, month_qiandao='',
                    total_qiandao_reward='', month_qiandao_reward='',
                    week=self._qiandao_today(), qiandao_time=0)
                row = self.get_role_qiandao(rid)
            except Exception:
                row = None
            if row is None:
                return None
        if not self._role_vip_level(rid):
            return frame(amf3_encode(
                [str(CMD_QIANDAO_BUQIAN), [0, GENERAL_NOT_VIP]]))
        cfg = self._qiandao_vip_config(self._role_vip_level(rid))
        if cfg is None:
            return frame(amf3_encode(
                [str(CMD_QIANDAO_BUQIAN),
                 [0, QIANDAO_ERR_VIP_CFG_NULL]]))
        if self._qiandao_has((row or {}).get('month_qiandao'), day):
            return frame(amf3_encode(
                [str(CMD_QIANDAO_BUQIAN),
                 [0, QIANDAO_ERR_CANNOT_BUQIAN]]))
        row = dict(row or {})
        try:
            total = int(row.get('total_qiandao_count') or 0) + 1
        except (TypeError, ValueError):
            total = 1
        try:
            self.save_role_qiandao(
                rid, total_qiandao_count=total,
                month_qiandao=self._qiandao_mark(row.get('month_qiandao'),
                                                day))
        except Exception:
            return None
        self._qiandao_grant_weekend(rid, cfg, self._qiandao_weekday(day))
        log.info('conn %d: qiandao buqian day %r (events skipped, no bus)',
                 self.conn_id, day)
        return frame(amf3_encode([str(CMD_QIANDAO_BUQIAN), [1, day]]))

    def qiandao_reward(self, msg):
        """Command 58014: lingquQiandaoReward claims a total-count reward.

        A bad id type stays silent; a missing row answers null. An unknown
        reward id answers [0, '592002'], a repeat [0, '592001'], a full bag
        [0, 1006]; success marks the month list, grants, and replies
        [1, id]. The GetQiandaoGoodsEvent has no bus here, so it is logged.
        """
        reward_id = self.safe(msg, 1)
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None or not isinstance(reward_id, str):
            return None
        cfg = self.config.qiandao_config(1, reward_id)
        try:
            row = self.get_role_qiandao(rid)
        except Exception:
            row = None
        if row is None:
            return frame(amf3_encode([str(CMD_QIANDAO_REWARD), None]))
        if cfg is None:
            return frame(amf3_encode(
                [str(CMD_QIANDAO_REWARD),
                 [0, QIANDAO_ERR_COUNT_SHORT]]))
        if self._qiandao_has(row.get('month_qiandao_reward'), reward_id):
            return frame(amf3_encode(
                [str(CMD_QIANDAO_REWARD),
                 [0, QIANDAO_ERR_REWARD_REPEAT]]))
        for gid, count, bind in cfg.get('rewards') or []:
            if not self._prop_fits(rid, {'goods': gid, 'count': count},
                                   bind):
                return frame(amf3_encode(
                    [str(CMD_QIANDAO_REWARD), [0, GENERAL_NOSLOT]]))
        try:
            self.save_role_qiandao(
                rid, month_qiandao_reward=self._qiandao_mark(
                    row.get('month_qiandao_reward'), reward_id))
        except Exception:
            return None
        self._task_grant(rid, [{'goods_id': gid, 'count': count,
                                'bind': bind}
                               for gid, count, bind in cfg.get('rewards')
                               or []])
        log.info('conn %d: qiandao reward %r (event skipped, no bus)',
                 self.conn_id, reward_id)
        return frame(amf3_encode([str(CMD_QIANDAO_REWARD), [1, reward_id]]))

    def qiandao_meiren(self, msg):
        """Command 58015: lingquQiandaoMeiren grants a count-tier meiren.

        A bad id type, a missing row, or an unknown reward id stays silent
        (the action only sends non-null results). A short lifetime total
        answers [0, '592002'], a repeat [0, '592001']; success grants via
        addMeiRen (pushing 82001 like 33006 when it inserts) and replies
        [1, id] either way, since the service discards addMeiRen's result.
        """
        reward_id = self.safe(msg, 1)
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None or not isinstance(reward_id, str):
            return None
        cfg = self.config.qiandao_config(2, reward_id)
        if cfg is None:
            return None
        try:
            row = self.get_role_qiandao(rid)
        except Exception:
            row = None
        if row is None:
            return None
        try:
            total = int(row.get('total_qiandao_count') or 0)
        except (TypeError, ValueError):
            total = 0
        if cfg.get('count') > total:
            return frame(amf3_encode(
                [str(CMD_QIANDAO_MEIREN),
                 [0, QIANDAO_ERR_COUNT_SHORT]]))
        if self._qiandao_has(row.get('total_qiandao_reward'), reward_id):
            return frame(amf3_encode(
                [str(CMD_QIANDAO_MEIREN),
                 [0, QIANDAO_ERR_REWARD_REPEAT]]))
        frames = []
        if self._zuoqi_grant_meiren(rid, cfg.get('meiren_id')):
            frames.append(frame(amf3_encode(
                [str(CMD_MEIREN_ADD),
                 [1, cfg.get('meiren_id'), 1]])))
        frames.append(frame(amf3_encode(
            [str(CMD_QIANDAO_MEIREN), [1, reward_id]])))
        return tuple(frames) if len(frames) > 1 else frames[0]

    def _yingyin_row(self, rid):
        """loginYingYin: create the flags row, or reset a stale day flag.

        The download flag is one-time (only the daily flag resets), so a
        same-day row passes through untouched.
        """
        try:
            row = self.get_role_jiangli_list(rid)
        except Exception:
            row = None
        now_ms = self._online_now_ms()
        if row is None:
            fields = {'baidu_yingyin': 0, 'baidu_yingyin_xiazai': 0,
                      'baidu_yingyin_time': now_ms}
            try:
                self.save_role_jiangli_list(rid, **fields)
            except Exception:
                return None
            return dict(fields)
        row = dict(row)
        if not self._qiandao_same_day(row.get('baidu_yingyin_time')):
            try:
                self.save_role_jiangli_list(rid, baidu_yingyin=0,
                                            baidu_yingyin_time=now_ms)
            except Exception:
                return None
            row.update(baidu_yingyin=0, baidu_yingyin_time=now_ms)
        return row

    def _yingyin_claim(self, rid, cmd, row, cfg, goods, flag):
        """Shared xiazai/dayReward claim: [0, code] gates, or granted."""
        try:
            if int(row.get(flag) or 0) == 1:
                return frame(amf3_encode(
                    [str(cmd), [0, YINGYIN_ERR_CLAIMED]]))
        except (TypeError, ValueError):
            pass
        if self._vip_kaifu_days() > cfg.get('time'):
            return frame(amf3_encode(
                [str(cmd), [0, YINGYIN_ERR_PAST_WINDOW]]))
        for gid, count, bind in goods:
            if not self._prop_fits(rid, {'goods': gid, 'count': count},
                                   bind):
                return frame(amf3_encode(
                    [str(cmd), [0, GENERAL_NOSLOT]]))
        return None

    def _yingyin_pay(self, rid, goods, flag, cmd, pairs):
        """Grant the goods, stamp the flag, and build the success reply."""
        self._task_grant(rid, [{'goods_id': gid, 'count': count,
                                'bind': bind}
                               for gid, count, bind in goods])
        fields = {flag: 1}
        if pairs:
            fields['baidu_yingyin_time'] = self._online_now_ms()
        try:
            self.save_role_jiangli_list(rid, **fields)
        except Exception:
            return None
        log.info('conn %d: yingyin %s claimed (event skipped, no bus)',
                 self.conn_id, cmd)
        if pairs:
            return frame(amf3_encode(
                [str(cmd), [1, [[gid, count]
                                for gid, count, _ in goods]]]))
        return frame(amf3_encode([str(cmd), [1]]))

    def yingyin_xiazai(self):
        """Command 58017: yingyinXiaZaiReward claims the download goods.

        A repeat answers [0, '592013'], a server past the day window
        [0, '592014'], a full bag [0, 1006]; success stamps the one-time
        flag, grants, and replies [1]. The reward event has no bus here.
        """
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        row = self._yingyin_row(rid)
        cfg = self.config.yingyin_config() if row is not None else None
        if row is None or cfg is None:
            return None
        gate = self._yingyin_claim(rid, CMD_YINGYIN_XIAZAI, row, cfg,
                                   cfg.get('first_goods') or [],
                                   'baidu_yingyin_xiazai')
        if gate is not None:
            return gate
        return self._yingyin_pay(rid, cfg.get('first_goods') or [],
                                 'baidu_yingyin_xiazai',
                                 CMD_YINGYIN_XIAZAI, False)

    def yingyin_state(self):
        """Command 58018: getYingYinState answers [download, daily] flags."""
        role, rid = self._task_role()
        if role is None:
            return None
        row = self._yingyin_row(rid)
        if row is None:
            return None
        return frame(amf3_encode(
            [str(CMD_YINGYIN_STATE),
             [row.get('baidu_yingyin_xiazai') or 0,
              row.get('baidu_yingyin') or 0]]))

    def yingyin_reward(self):
        """Command 58019: yingyinreward claims the daily voice goods.

        Same gates as the download claim; success stamps the daily flag
        with now and replies [1, [[goodsId, count]]] like itemParamVo2GoodsArray.
        """
        if self.config is None:
            return None
        role, rid = self._task_role()
        if role is None:
            return None
        row = self._yingyin_row(rid)
        cfg = self.config.yingyin_config() if row is not None else None
        if row is None or cfg is None:
            return None
        gate = self._yingyin_claim(rid, CMD_YINGYIN_REWARD, row, cfg,
                                   cfg.get('day_goods') or [],
                                   'baidu_yingyin')
        if gate is not None:
            return gate
        return self._yingyin_pay(rid, cfg.get('day_goods') or [],
                                 'baidu_yingyin', CMD_YINGYIN_REWARD, True)

    def _online_now_ms(self):
        """System.currentTimeMillis for the jiangli online clocks."""
        return int(time.time() * 1000)

    def _online_kaifu_months(self):
        """ServerInfoExportService.getKaifuMonths, capped like JiangliServiceImpl."""
        try:
            start = time.localtime(int(self.server_start_ms or 0) / 1000)
            now = time.localtime()
            months = (now.tm_year - start.tm_year) * 12 + \
                (now.tm_mon - start.tm_mon)
        except (TypeError, ValueError, OverflowError):
            months = 0
        if months > 3:
            months = 3
        if months == 0:
            months = 1
        return months

    @staticmethod
    def _online_has_id(text, day):
        """checkIds(int, String): the comma list already holds the tier id."""
        for part in str(text or '').split(','):
            part = part.strip()
            if not part:
                continue
            try:
                if int(part) == day:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    @staticmethod
    def _online_add_id(text, day):
        """setIds(int, String): append the tier id to the comma list."""
        if text is None or text == '':
            return str(day)
        return '%s,%s' % (text, day)

    @staticmethod
    def _micro_end_login(rid):
        """MicroEndExportService.isMicroEndLogin: no micro-end login channel

        exists here, so the stored login type is never 1 and this is always
        False — getWeiDanReward answers 592011 exactly like Java does for
        every non-micro-end session.
        """
        return False

    def _dengluqi_row(self, rid):
        """initDengLuQi: create the missing row, reset it past its day."""
        now = self._online_now_ms()
        try:
            row = self.get_role_dengluqi(rid)
        except Exception:
            row = None
        if row is None:
            try:
                self.save_role_dengluqi(rid, lingqu_state=0,
                                        lingqu_time=now)
            except Exception:
                pass
            return {'lingqu_state': 0, 'lingqu_time': now}
        if not self._same_day_ms(row.get('lingqu_time'), now):
            try:
                self.save_role_dengluqi(rid, lingqu_state=0,
                                        lingqu_time=now)
            except Exception:
                pass
            row = dict(row, lingqu_state=0, lingqu_time=now)
        return row

    def _online_bind_yb(self, ms, configs, kaifu):
        """getOnlineRewardBindYb: whole hours times the month's bindGold."""
        hours = int(ms) // 1000 // 60 // 60
        for cfg in configs:
            if cfg.get('month') == kaifu:
                try:
                    return int(hours * float(cfg.get('bindGold') or 0))
                except (TypeError, ValueError):
                    return 0
        return 0

    def _online_row(self, rid):
        """createRoleOnlineReward plus the loginOnlineReward rollovers.

        Java runs these at login; without a login hook here the handlers
        run them lazily instead, which settles to the same stored state.
        """
        now = self._online_now_ms()
        try:
            row = self.get_role_online_reward(rid)
        except Exception:
            row = None
        if row is None:
            row = {'month': time.localtime().tm_mon, 'online_time': 0,
                   'month_online_time': 0, 'refresh_time': now,
                   'online_reward': '', 'is_lingqu_reward': 0,
                   'month_bind_yb': 0, 'role_online_time': now}
            try:
                self.save_role_online_reward(rid, **row)
            except Exception:
                pass
            return dict(row)
        row = dict(row)
        changed = {}
        if self.config is not None:
            try:
                cats = self.config.online_reward_tables()
            except Exception:
                cats = {1: [], 2: []}
            kaifu = self._online_kaifu_months()
            monthly = cats.get(2, [])
            if any(c.get('month') == kaifu for c in monthly):
                try:
                    cur = time.localtime().tm_mon
                except (TypeError, ValueError, OverflowError):
                    cur = None
                if cur is not None and cur != (row.get('month') or 0):
                    carry = int(row.get('month_online_time') or 0)
                    if carry > 0:
                        changed['month_bind_yb'] = \
                            int(row.get('month_bind_yb') or 0) + \
                            self._online_bind_yb(carry, monthly, kaifu)
                    changed['month_online_time'] = 0
                    changed['month'] = cur
                    changed['is_lingqu_reward'] = 0
        if not self._same_day_ms(row.get('refresh_time'), now):
            changed['refresh_time'] = now
            changed['online_time'] = 0
            changed['online_reward'] = ''
        if changed:
            try:
                self.save_role_online_reward(rid, **changed)
            except Exception:
                pass
            row.update(changed)
        return row

    @staticmethod
    def _online_totals(row, now):
        """Read-time totals: stored ms plus the open session's delta."""
        try:
            anchor = int(row.get('role_online_time') or 0)
        except (TypeError, ValueError):
            anchor = 0
        delta = now - anchor if anchor > 0 else 0
        try:
            total = int(row.get('online_time') or 0) + delta
        except (TypeError, ValueError):
            total = delta
        try:
            month_total = int(row.get('month_online_time') or 0) + delta
        except (TypeError, ValueError):
            month_total = delta
        return total, month_total

    def weidan_state(self, msg):
        """Command 10060: getWeiDanState answers the claim state.

        The tunnel wraps Java's bare Integer, so the wire shape is [state]
        as captured — state 0 fresh or past its day, 1 once claimed.
        """
        role = self._equip_role()
        if role is None:
            return None
        row = self._dengluqi_row(role.get('id'))
        try:
            state = int(row.get('lingqu_state') or 0)
        except (TypeError, ValueError):
            state = 0
        return frame(amf3_encode([str(CMD_WEIDAN_STATE), [state]]))

    def weidan_reward(self, msg):
        """Command 10061: getWeiDanReward claims the micro-client parcel.

        Non-micro-end sessions answer [0, 592011] and claimed ones [0,
        592012]; a fresh grant replies [1] after the dengluqijiangli pool
        lands (short bag [0, 1006]). A missing pool stays silent like Java's
        null-WeiDuan branch.
        """
        role = self._equip_role()
        if role is None:
            return None
        rid = role.get('id')
        row = self._dengluqi_row(rid)
        try:
            claimed = int(row.get('lingqu_state') or 0) == 1
        except (TypeError, ValueError):
            claimed = False
        if not self._micro_end_login(rid):
            return frame(amf3_encode([str(CMD_WEIDAN_REWARD),
                                      [0, WEIDAN_ERR_NOT_MICRO]]))
        if claimed:
            return frame(amf3_encode([str(CMD_WEIDAN_REWARD),
                                      [0, WEIDAN_ERR_CLAIMED]]))
        items = self.config.weiduan_items() \
            if self.config is not None else []
        if not items:
            return None
        if not self._vip_fits_list(rid, items):
            return frame(amf3_encode([str(CMD_WEIDAN_REWARD),
                                      [0, GENERAL_NOSLOT]]))
        self._task_grant(rid, [{'goods_id': gid, 'count': count,
                                'bind': bind}
                               for gid, count, bind in items])
        try:
            self.save_role_dengluqi(rid, lingqu_state=1,
                                    lingqu_time=self._online_now_ms())
        except Exception:
            pass
        return frame(amf3_encode([str(CMD_WEIDAN_REWARD), [1]]))

    def online_reward_info(self, msg):
        """Command 58003: getOnlineRewardInfo totals plus the claim state.

        Java Longs ride the wire as doubles, so the two ms totals go out
        as floats; the claimed tiers split like QiandaoOutput.toInteger.
        State 1 means the month's bind-yb is claimable today, else 2.
        """
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        rid = role.get('id')
        now = self._online_now_ms()
        row = self._online_row(rid)
        total, month_total = self._online_totals(row, now)
        try:
            bind_yb = int(row.get('month_bind_yb') or 0)
        except (TypeError, ValueError):
            bind_yb = 0
        claimed = _qiandao_ints(row.get('online_reward'))
        kaifu = self._online_kaifu_months()
        try:
            monthly = self.config.online_reward_tables().get(2, [])
        except Exception:
            monthly = []
        cfg = next((c for c in monthly if c.get('month') == kaifu), None)
        state = 2
        if cfg is not None:
            try:
                open_day = time.localtime().tm_mday in \
                    (cfg.get('dayLimit') or [])
            except (TypeError, ValueError, OverflowError):
                open_day = False
            if open_day:
                state = 1 if bind_yb > 0 else 2
        return frame(amf3_encode([
            str(CMD_ONLINE_INFO),
            [[float(total), float(month_total), bind_yb, claimed,
              state]]]))

    def _online_check_yaojiang(self, row, claimed, configs, total):
        """checkYaojiang: repeat and eligible-tier guards for 58004."""
        if claimed:
            if len(str(claimed).split(',')) == len(configs):
                return [0, ONLINE_ERR_NOT_REPEAT]
        eligible = []
        for cfg in configs:
            try:
                threshold = int(cfg.get('monthTime') or 0)
            except (TypeError, ValueError):
                threshold = 0
            if total < threshold:
                continue
            if self._online_has_id(claimed, cfg.get('count')):
                continue
            eligible.append(cfg.get('count'))
        if not eligible:
            return [0, ONLINE_ERR_TIME_SHORT]
        if claimed:
            parts = [p for p in str(claimed).split(',') if p.strip()]
            if len(parts) > 1:
                try:
                    ids = [int(p) for p in parts]
                except (TypeError, ValueError):
                    return None
                if all(v in eligible for v in ids):
                    return [0, ONLINE_ERR_TIME_SHORT]
        return None

    def online_yaojiang(self, msg):
        """Command 58004: yaoJiang rolls the open daily tiers.

        Each unclaimed tier whose raw threshold the ms total reaches draws
        one weighted prize (Java compares the ms total against the seconds
        config directly); the reply pairs [tier, prizeIndex] per draw and
        [1, pairs] overall. A full bag answers [0, 592001]; with nothing
        to draw the guard above answers instead. Null stays silent.
        """
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        rid = role.get('id')
        now = self._online_now_ms()
        row = self._online_row(rid)
        claimed = row.get('online_reward') or ''
        try:
            configs = self.config.online_reward_tables().get(1, [])
        except Exception:
            configs = []
        total, _ = self._online_totals(row, now)
        err = self._online_check_yaojiang(row, claimed, configs, total)
        if err is not None:
            return frame(amf3_encode([str(CMD_ONLINE_YAOJIANG), err]))
        pairs, grant, mark = [], [], []
        for cfg in configs:
            try:
                threshold = int(cfg.get('time') or 0)
            except (TypeError, ValueError):
                continue
            if total < threshold:
                continue
            if self._online_has_id(claimed, cfg.get('count')):
                continue
            weights = {}
            for pos, reward in enumerate(cfg.get('rewards') or []):
                try:
                    weights[pos] = float(reward[3])
                except (TypeError, ValueError, IndexError):
                    continue
            pick = self._lottery_weighted_key(weights)
            if pick is None:
                continue
            try:
                gid, count, bind, _, index = \
                    (cfg.get('rewards') or [])[pick]
            except (TypeError, ValueError, IndexError):
                continue
            pairs.append([cfg.get('count'), index])
            grant.append((gid, count, bind))
            mark.append(cfg.get('count'))
        if grant:
            if not self._vip_fits_list(rid, grant):
                return frame(amf3_encode([str(CMD_ONLINE_YAOJIANG),
                                          [0, ONLINE_ERR_BAG_FULL]]))
            self._task_grant(rid, [{'goods_id': gid, 'count': count,
                                    'bind': bind}
                                   for gid, count, bind in grant])
        for tier in mark:
            claimed = self._online_add_id(claimed, tier)
        try:
            self.save_role_online_reward(rid, online_reward=claimed)
        except Exception:
            pass
        return frame(amf3_encode([str(CMD_ONLINE_YAOJIANG),
                                  [1, pairs]]))

    def online_lingqu(self, msg):
        """Command 58005: lingquOnlineRewardBindYb claims the month's bind-yb.

        The kaifu-month tier must be open today with an unclaimed accrual;
        success zeroes it, credits bind_lingshi and replies [1, granted].
        A null result stays silent like Java.
        """
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        rid = role.get('id')
        row = self._online_row(rid)
        kaifu = self._online_kaifu_months()
        try:
            monthly = self.config.online_reward_tables().get(2, [])
        except Exception:
            monthly = []
        cfg = next((c for c in monthly if c.get('month') == kaifu), None)
        if cfg is None:
            return frame(amf3_encode([str(CMD_ONLINE_LINGQU),
                                      [0, ONLINE_ERR_MONTH_LIMIT]]))
        try:
            bind_yb = int(row.get('month_bind_yb') or 0)
        except (TypeError, ValueError):
            bind_yb = 0
        if bind_yb == 0:
            return frame(amf3_encode([str(CMD_ONLINE_LINGQU),
                                      [0, ONLINE_ERR_NO_BINDYB]]))
        try:
            open_day = time.localtime().tm_mday in \
                (cfg.get('dayLimit') or [])
        except (TypeError, ValueError, OverflowError):
            open_day = False
        if not open_day:
            return frame(amf3_encode([str(CMD_ONLINE_LINGQU),
                                      [0, ONLINE_ERR_MONTH_LIMIT]]))
        try:
            done = int(row.get('is_lingqu_reward') or 0) == 1
        except (TypeError, ValueError):
            done = False
        if done:
            return frame(amf3_encode([str(CMD_ONLINE_LINGQU),
                                      [0, ONLINE_ERR_NOT_REPEAT]]))
        try:
            self.save_role_online_reward(rid, is_lingqu_reward=1,
                                         month_bind_yb=0)
        except Exception:
            pass
        try:
            total = int(role.get('bind_lingshi') or 0) + bind_yb
        except (TypeError, ValueError):
            total = bind_yb
        try:
            self.save_role_state(rid, bind_lingshi=total)
        except Exception:
            pass
        return frame(amf3_encode([str(CMD_ONLINE_LINGQU),
                                  [1, bind_yb]]))

    def _role_vip_level(self, rid):
        """VipService.getRoleVipLevel: the RoleVip tier, 0 when absent."""
        try:
            vip = self.get_role_vip(rid) or {}
        except Exception:
            return 0
        try:
            return int(vip.get('vip_level') or 0)
        except (TypeError, ValueError):
            return 0

    def _husong_row(self, rid):
        """checkRefreshData plus createRoleHusong: reset a stale day, else

        create the row (first MeiQi id, zero counts, now stamps) like Java.
        """
        now = self._online_now_ms()
        try:
            row = self.get_role_husong(rid)
        except Exception:
            row = None
        if row is not None:
            if not self._same_day_ms(row.get('refresh_time'), now):
                try:
                    self.save_role_husong(rid, husong_times=0,
                                         refresh_time=now)
                except Exception:
                    pass
                row = dict(row, husong_times=0, refresh_time=now)
            return row
        first = self.config.husong_first_id() \
            if self.config is not None else None
        row = {'mei_qi_id': first, 'husong_times': 0,
               'refresh_time': now, 'dajie_cishu': 0, 'dajie_time': now}
        try:
            self.save_role_husong(rid, **row)
        except Exception:
            pass
        return dict(row)

    def husong_position(self, msg):
        """Command 83000: meiQiPosition pushes the escort beauty's spot.

        With no escort running Java pushes null (no HuSongManager, or a
        manager with no MeiQi); this server never runs escorts, so the
        reply is always [None] as captured.
        """
        role = self._equip_role()
        if role is None:
            return None
        return frame(amf3_encode([str(CMD_HUSONG_POSITION), [None]]))

    def husong_info(self, msg):
        """Command 83001: huSongInfo answers [meiQiId, remaining escorts].

        The remainder is the vip husongsishu quota minus today's count,
        [['1', 3]] for a fresh role as captured.
        """
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        rid = role.get('id')
        row = self._husong_row(rid)
        try:
            used = int(row.get('husong_times') or 0)
        except (TypeError, ValueError):
            used = 0
        remaining = self.config.vip_husong_count(
            self._role_vip_level(rid)) - used
        return frame(amf3_encode([str(CMD_HUSONG_INFO),
                                  [[row.get('mei_qi_id'), remaining]]]))

    def husong_dajie(self, msg):
        """Command 83008: getDaJieCount answers [remaining rob chances].

        The vip jiebiao quota minus robbed count ([[10]] fresh); a missing
        row answers [[0]] like Java's null branch.
        """
        role = self._equip_role()
        if role is None or self.config is None:
            return None
        rid = role.get('id')
        try:
            row = self.get_role_husong(rid)
        except Exception:
            row = None
        if row is None:
            return frame(amf3_encode([str(CMD_HUSONG_DAJIE), [[0]]]))
        try:
            used = int(row.get('dajie_cishu') or 0)
        except (TypeError, ValueError):
            used = 0
        remaining = self.config.vip_dajie(
            self._role_vip_level(rid)) - used
        return frame(amf3_encode([str(CMD_HUSONG_DAJIE), [[remaining]]]))

    def loginlibao_info(self, msg):
        """127000: LoginlibaoServiceImpl.getConfig [sign, configs?, unclaimed]."""
        if self.config is None:
            return None
        client_sign = None
        try:
            client_sign = str(self.safe(self.safe(msg, 1, []), 0) or '')
        except Exception:
            client_sign = None
        sign, rows = self.config.denglulibao_table()
        role = self._equip_role()
        claimed = {}
        if role is not None:
            try:
                row = self.get_role_loginlibao(role.get('id'))
            except Exception:
                row = None
            if row and row.get('lingqujson'):
                try:
                    import json as _json
                    claimed = _json.loads(row.get('lingqujson')) or {}
                except Exception:
                    claimed = {}
        unclaimed = 0
        for r in rows:
            if str(r.get('id')) not in claimed:
                unclaimed = 1
                break
        configs = None if (client_sign and client_sign == sign) else \
            [dict(r) for r in rows]
        return frame(amf3_encode(['127000', [sign, configs, unclaimed]]))

    def loginlibao_claim(self, msg):
        """127001: lingqu(id) grants prizegoods, marks claimed."""
        if self.config is None:
            return None
        role = self._equip_role()
        if role is None:
            return None
        rid = role.get('id')
        try:
            gid = str(self.safe(self.safe(msg, 1, []), 0))
        except Exception:
            return frame(amf3_encode(['127001', [0]]))
        _, rows = self.config.denglulibao_table()
        cfg = next((r for r in rows if str(r.get('id')) == gid), None)
        if cfg is None:
            return frame(amf3_encode(['127001', [0]]))
        try:
            row = self.get_role_loginlibao(rid)
        except Exception:
            row = None
        claimed = {}
        if row and row.get('lingqujson'):
            try:
                import json as _json
                claimed = _json.loads(row.get('lingqujson')) or {}
            except Exception:
                claimed = {}
        if str(gid) in claimed:
            return frame(amf3_encode(['127001', [0]]))
        items = self.config.parse_goods_string(cfg.get('prizegoods'))
        if not self._vip_fits_list(
                rid, [(g, c, b) for g, c, b in items]):
            return frame(amf3_encode(['127001', [0]]))
        self._task_grant(rid, [{'goods_id': g, 'count': c, 'bind': b}
                               for g, c, b in items])
        claimed[str(gid)] = 1
        try:
            import json as _json, time as _time
            self.save_role_loginlibao(
                rid, lingqujson=_json.dumps(claimed),
                lingqu_time=int(_time.time() * 1000))
        except Exception:
            pass
        return frame(amf3_encode(['127001', [1, gid]]))

    def lvlibao_info(self, msg):
        """58000: LvlibaoServiceImpl.laQuLvLiBao [[id, state]...]."""
        role = self._equip_role()
        if role is None:
            return None
        try:
            row = self.get_role_lvlibao(role.get('id'))
        except Exception:
            row = None
        pairs = []
        if row and row.get('state'):
            try:
                import json as _json
                state = _json.loads(row.get('state')) or {}
            except Exception:
                state = {}
            for k, v in state.items():
                try:
                    pairs.append([str(k), int(v)])
                except (TypeError, ValueError):
                    continue
        return frame(amf3_encode(['58000', pairs]))

    def lvlibao_claim(self, msg):
        """58001: lingQuLvLiBao(number) level-gated grant."""
        if self.config is None:
            return None
        role = self._equip_role()
        if role is None:
            return None
        rid = role.get('id')
        try:
            number = str(self.safe(self.safe(msg, 1, []), 0))
        except Exception:
            return frame(amf3_encode(['58001', [0]]))
        _, rows = self.config.dengjilibao_table()
        cfg = next((r for r in rows if str(r.get('number')) == number),
                   None)
        if cfg is None:
            return frame(amf3_encode(['58001', [0]]))
        try:
            need = int(cfg.get('levelneed') or 0)
        except (TypeError, ValueError):
            need = 0
        try:
            lv = int(role.get('level') or 0)
        except (TypeError, ValueError):
            lv = 0
        if lv < need:
            return frame(amf3_encode(['58001', [0]]))
        try:
            row = self.get_role_lvlibao(rid)
        except Exception:
            row = None
        state = {}
        if row and row.get('state'):
            try:
                import json as _json
                state = _json.loads(row.get('state')) or {}
            except Exception:
                state = {}
        if int(state.get(number) or 0) == 1:
            return frame(amf3_encode(['58001', [0]]))
        items = self.config.parse_goods_string(cfg.get('goods'))
        if not self._vip_fits_list(
                rid, [(g, c, b) for g, c, b in items]):
            return frame(amf3_encode(['58001', [0]]))
        self._task_grant(rid, [{'goods_id': g, 'count': c, 'bind': b}
                               for g, c, b in items])
        state[str(number)] = 1
        try:
            import json as _json
            self.save_role_lvlibao(rid, state=_json.dumps(state))
        except Exception:
            pass
        return frame(amf3_encode(['58001', [1, number]]))

    def loginlingjiang_info(self, msg):
        """103000: LoginlingjaingServiceImpl.getInfo [dayNumber, claimed]."""
        role = self._equip_role()
        if role is None:
            return None
        rid = role.get('id')
        try:
            row = self.get_role_loginlingjiang(rid)
        except Exception:
            row = None
        if row is None:
            try:
                self.save_role_loginlingjiang(rid, day_number=1,
                                              lingqujson='{}')
            except Exception:
                pass
            return frame(amf3_encode(['103000', [1, []]]))
        try:
            days = int(row.get('day_number') or 1)
        except (TypeError, ValueError):
            days = 1
        claimed = self._json_ids(row.get('lingqujson'))
        return frame(amf3_encode(['103000', [days, claimed]]))

    def loginlingjiang_claim(self, msg):
        """103001: lingQu(day) grants the dengluqijiangli pool."""
        if self.config is None:
            return None
        role = self._equip_role()
        if role is None:
            return None
        rid = role.get('id')
        try:
            day = str(self.safe(self.safe(msg, 1, []), 0))
        except Exception:
            return frame(amf3_encode(['103001', [0]]))
        try:
            row = self.get_role_loginlingjiang(rid)
        except Exception:
            row = None
        try:
            days = int((row or {}).get('day_number') or 1)
        except (TypeError, ValueError):
            days = 1
        try:
            day_no = int(day)
        except (TypeError, ValueError):
            return frame(amf3_encode(['103001', [0]]))
        if day_no < 1 or day_no > days:
            return frame(amf3_encode(['103001', [0]]))
        claimed = self._json_ids((row or {}).get('lingqujson'))
        if day in claimed or str(day_no) in claimed:
            return frame(amf3_encode(['103001', [0]]))
        items = self.config.parse_goods_string(
            self.config.loginlingjiang_items())
        if not items:
            return frame(amf3_encode(['103001', [0]]))
        if not self._vip_fits_list(
                rid, [(g, c, b) for g, c, b in items]):
            return frame(amf3_encode(['103001', [0]]))
        self._task_grant(rid, [{'goods_id': g, 'count': c, 'bind': b}
                               for g, c, b in items])
        claimed.append(str(day_no))
        try:
            import json as _json
            self.save_role_loginlingjiang(
                rid, lingqujson=_json.dumps(claimed))
        except Exception:
            pass
        return frame(amf3_encode(['103001', [1, str(day_no)]]))

    @staticmethod
    def _json_ids(text):
        """Fastjson claim mark (list or {id:1} map) to string ids."""
        if not text:
            return []
        try:
            import json as _json
            data = _json.loads(text)
        except Exception:
            return []
        if isinstance(data, dict):
            return [str(k) for k in data]
        if isinstance(data, list):
            return [str(x) for x in data]
        return []

    def touxian_info(self, msg):
        """104000: TouxianServiceImpl.getTouXianInfo [worn, owned]."""
        role = self._equip_role()
        if role is None:
            return None
        try:
            row = self.get_role_touxian(role.get('id'))
        except Exception:
            row = None
        if row is None:
            return frame(amf3_encode(['104000', [None, []]]))
        owned = self._json_ids(row.get('jihuoids'))
        return frame(amf3_encode(
            ['104000', [row.get('peidai_id'), owned]]))

    def touxian_activate(self, msg):
        """104001: jiHuoTouXian(id) owns the title.

        The shipped touxianbiao.jat rows carry no decr-goods column, so
        activation is own-and-persist (like Java when decrGoods is
        empty); titles with a cost table would fail closed here.
        """
        if self.config is None:
            return None
        role = self._equip_role()
        if role is None:
            return None
        rid = role.get('id')
        try:
            tid = str(self.safe(self.safe(msg, 1, []), 0))
        except Exception:
            return frame(amf3_encode(['104001', [0]]))
        if tid not in self.config.touxian_table():
            return frame(amf3_encode(['104001', [0]]))
        try:
            row = self.get_role_touxian(rid)
        except Exception:
            row = None
        owned = self._json_ids((row or {}).get('jihuoids'))
        if tid in owned:
            return frame(amf3_encode(['104001', [0]]))
        owned.append(tid)
        try:
            import json as _json
            self.save_role_touxian(
                rid, jihuoids=_json.dumps(owned),
                peidai_id=(row or {}).get('peidai_id'))
        except Exception:
            pass
        return frame(amf3_encode(['104001', [1, tid]]))

    def touxian_wear(self, msg):
        """104002: changeTouXian(id) wears an owned title."""
        role = self._equip_role()
        if role is None:
            return None
        rid = role.get('id')
        try:
            tid = str(self.safe(self.safe(msg, 1, []), 0))
        except Exception:
            return frame(amf3_encode(['104002', [0]]))
        try:
            row = self.get_role_touxian(rid)
        except Exception:
            row = None
        if tid not in self._json_ids((row or {}).get('jihuoids')):
            return frame(amf3_encode(['104002', [0]]))
        try:
            self.save_role_touxian(rid, peidai_id=tid)
        except Exception:
            pass
        return frame(amf3_encode(['104002', [1, tid]]))

    def guangyi_info(self, msg):
        """102000: GuangyiServiceImpl.guangyiInfo; null with no row."""
        role = self._equip_role()
        if role is None:
            return None
        try:
            row = self.get_role_guangyi(role.get('id'))
        except Exception:
            row = None
        if row is None:
            return frame(amf3_encode(['102000', None]))
        return frame(amf3_encode(['102000', [
            row.get('peidai_id') or 0, row.get('level') or 1,
            row.get('lucky') or 0, row.get('ispeidai') or 0,
            self._json_pairs(row.get('attr_dan'))]]))

    @staticmethod
    def _json_pairs(text):
        """Fastjson {k: v} map to [[k, v]...] pairs."""
        if not text:
            return []
        try:
            import json as _json
            data = _json.loads(text) or {}
        except Exception:
            return []
        if not isinstance(data, dict):
            return []
        return [[str(k), v] for k, v in data.items()]

    def guangyi_buy(self, msg):
        """102002: buyGuangYi creates the level-1 row.

        Cost is needthingsid x needthingsvalue from guangyi.jat (the
        first row's pair), paid from the bag; missing goods fail [0].
        """
        if self.config is None:
            return None
        role = self._equip_role()
        if role is None:
            return None
        rid = role.get('id')
        try:
            if self.get_role_guangyi(rid) is not None:
                return frame(amf3_encode(['102002', [0]]))
        except Exception:
            pass
        rows = self.config.guangyi_table()
        if not rows:
            return frame(amf3_encode(['102002', [0]]))
        first = rows[0]
        need_id = str(first.get('needthingsid') or '')
        try:
            need_n = int(first.get('needthingsvalue') or 0)
        except (TypeError, ValueError):
            need_n = 0
        if need_id and need_n > 0 and not self._bag_decr(rid, need_id,
                                                         need_n):
            return frame(amf3_encode(['102002', [0]]))
        try:
            self.save_role_guangyi(rid, peidai_id=1, level=1, lucky=0,
                                   ispeidai=1, attr_dan='{}')
        except Exception:
            return frame(amf3_encode(['102002', [0]]))
        return frame(amf3_encode(['102002', [1, 1]]))

    def _bag_decr(self, rid, goods_id, count):
        """Decr count of goods_id across bag slots; False if short."""
        try:
            slots = self.get_role_bag_slots(rid, -1000000, 1000000) or []
        except Exception:
            return False
        have = 0
        for s in slots:
            try:
                if str(s.get('goods_id')) == str(goods_id):
                    have += int(s.get('count') or 0)
            except (TypeError, ValueError):
                continue
        if have < count:
            return False
        left = count
        for s in sorted(slots, key=lambda x: x.get('slot_num') or 0):
            if left <= 0:
                break
            try:
                if str(s.get('goods_id')) != str(goods_id):
                    continue
                n = int(s.get('count') or 0)
            except (TypeError, ValueError):
                continue
            if n <= 0:
                continue
            take = min(n, left)
            left -= take
            try:
                if n - take <= 0:
                    self.delete_role_bag_slot(rid, s.get('slot_num'))
                else:
                    self.update_role_bag_slot(rid, s.get('slot_num'),
                                              count=n - take)
            except Exception:
                return False
        return left <= 0

    def guangyi_wear(self, msg):
        """102003: qiehuan(id) wears the wing (no cost, like change)."""
        role = self._equip_role()
        if role is None:
            return None
        rid = role.get('id')
        try:
            gid = int(self.safe(self.safe(msg, 1, []), 0))
        except (TypeError, ValueError):
            return frame(amf3_encode(['102003', [0]]))
        try:
            row = self.get_role_guangyi(rid)
        except Exception:
            row = None
        if row is None:
            return frame(amf3_encode(['102003', [0]]))
        try:
            self.save_role_guangyi(rid, peidai_id=gid, ispeidai=1)
        except Exception:
            pass
        return frame(amf3_encode(['102003', [1, gid]]))

    def baixian_info(self, msg):
        """71000: RoleBaixianServiceImpl.getInfo [[id,count]..., cost]."""
        if self.config is None:
            return None
        role = self._equip_role()
        if role is None:
            return None
        counts = self._baixian_counts(role.get('id'))
        flat = []
        for r in self.config.baixian_table():
            flat.extend([str(r.get('id')), int(counts.get(str(r.get('id')), 0))])
        return frame(amf3_encode(['71000', [[flat, 0.0]]]))

    def _baixian_counts(self, rid):
        """Today's worship counts; a stale day resets like todayChuli."""
        import time as _time
        today = _time.strftime('%Y-%m-%d')
        try:
            row = self.get_role_baixian(rid)
        except Exception:
            row = None
        if row is None or row.get('last_day') != today:
            return {}
        try:
            import json as _json
            data = _json.loads(row.get('counts')) or {}
        except Exception:
            return {}
        return {str(k): int(v) for k, v in data.items()}

    def baixian_worship(self, msg):
        """71001: baixian(god) spends lingshi past the free worship.

        Cost/reward mapping is best-effort from BaiXianHuaFei.jat column
        semantics (xNgold = YB cost for god N at this count; god1 gets
        coinxs11 tongqian, god2 zhenqi22 zhenqi, god3 exp23 exp; the
        first worship of each god per day is free). The oracle diff
        adjudicates the exact Java mapping.
        """
        if self.config is None:
            return None
        role = self._equip_role()
        if role is None:
            return None
        rid = role.get('id')
        try:
            god = str(self.safe(self.safe(msg, 1, []), 0))
        except Exception:
            return frame(amf3_encode(['71001', [0]]))
        gods = [str(r.get('id')) for r in self.config.baixian_table()]
        if god not in gods:
            return frame(amf3_encode(['71001', [0]]))
        import time as _time
        today = _time.strftime('%Y-%m-%d')
        counts = self._baixian_counts(rid)
        n = int(counts.get(god, 0)) + 1
        cost = 0
        reward_tongqian, reward_zhenqi, reward_exp = 0, 0, 0
        fee = self.config.baixian_huafei(n) or {}
        if n > 1:
            try:
                cost = int(fee.get(f'x{god}gold') or 0)
            except (TypeError, ValueError):
                cost = 0
        try:
            reward_tongqian = int(fee.get('coinxs11') or 0) if god == gods[0] \
                else 0
            reward_zhenqi = int(fee.get('zhenqi22') or 0) if god == gods[1] \
                else 0
            reward_exp = int(fee.get('exp23') or 0) if god == gods[2] else 0
        except (TypeError, ValueError):
            pass
        try:
            lingshi = int(role.get('lingshi') or 0)
        except (TypeError, ValueError):
            lingshi = 0
        if cost > lingshi:
            return frame(amf3_encode(['71001', [0]]))
        if cost:
            try:
                self.save_role_state(rid, lingshi=lingshi - cost)
            except Exception:
                return frame(amf3_encode(['71001', [0]]))
        if reward_tongqian or reward_zhenqi or reward_exp:
            try:
                fresh = self.get_roles(self.authed_user or '',
                                       self.server_id or '')
                cur = fresh[0] if fresh else role
                self.save_role_state(
                    rid,
                    tongqian=int(cur.get('tongqian') or 0) + reward_tongqian,
                    zhenqi=int(cur.get('zhenqi') or 0) + reward_zhenqi,
                    exp=int(cur.get('exp') or 0) + reward_exp)
            except Exception:
                pass
        counts[god] = n
        try:
            import json as _json
            self.save_role_baixian(rid, counts=_json.dumps(counts),
                                   last_day=today)
        except Exception:
            pass
        return frame(amf3_encode(['71001', [1, god, n]]))

    def zhuihui_info(self, msg):
        """107000: ZyzhuihuiServiceImpl.getinfo 8 recovery rows."""
        if self.config is None:
            return None
        role = self._equip_role()
        if role is None:
            return None
        claimed = self._zhuihui_claimed(role.get('id'))
        out = []
        for rid_key in sorted(self.config.zhuihui_table(),
                              key=lambda x: int(x)):
            out.append([rid_key, 0, 1 if rid_key in claimed else 0])
        return frame(amf3_encode(['107000', [out]]))

    def _zhuihui_claimed(self, rid):
        try:
            row = self.get_role_zhuihui(rid)
        except Exception:
            return set()
        return set(self._json_ids((row or {}).get('state')))

    def zhuihui_claim(self, msg):
        """107001: zhuiHui(id) spends lingshi, grants exp/tongqian.

        Best-effort flat mapping (money1 lingshi cost; exp1 exp and
        tongqian1 tongqian grants; lingqi/banggong have no character
        columns and are skipped). Java scales by level via
        ZiYuanZhuiHuiConfig math; that scaling is a follow-up once
        the Config class is decompiled.
        """
        if self.config is None:
            return None
        role = self._equip_role()
        if role is None:
            return None
        rid = role.get('id')
        try:
            zid = str(self.safe(self.safe(msg, 1, []), 0))
        except Exception:
            return frame(amf3_encode(['107001', [0]]))
        cfg = self.config.zhuihui_table().get(zid)
        if cfg is None:
            return frame(amf3_encode(['107001', [0]]))
        if zid in self._zhuihui_claimed(rid):
            return frame(amf3_encode(['107001', [0]]))
        try:
            cost = int(cfg.get('money1') or 0)
            grant_exp = int(cfg.get('exp1') or 0)
            grant_coin = int(cfg.get('tongqian1') or 0)
        except (TypeError, ValueError):
            return frame(amf3_encode(['107001', [0]]))
        try:
            lingshi = int(role.get('lingshi') or 0)
        except (TypeError, ValueError):
            lingshi = 0
        if cost > lingshi:
            return frame(amf3_encode(['107001', [0]]))
        try:
            fresh = self.get_roles(self.authed_user or '',
                                   self.server_id or '')
            cur = fresh[0] if fresh else role
            self.save_role_state(
                rid, lingshi=lingshi - cost,
                exp=int(cur.get('exp') or 0) + grant_exp,
                tongqian=int(cur.get('tongqian') or 0) + grant_coin)
        except Exception:
            return frame(amf3_encode(['107001', [0]]))
        claimed = self._zhuihui_claimed(rid) | {zid}
        try:
            import json as _json
            self.save_role_zhuihui(rid,
                                   state=_json.dumps(sorted(claimed)))
        except Exception:
            pass
        return frame(amf3_encode(['107001', [1, zid]]))

    def kapai_client(self, msg):
        """121000: KapaiServiceImpl.getClientConfig [sign, entries, recycle].

        Sign is the newest kapaibiao drop's md5; recycle rows come from
        the newest kapaiduihuanbiao drop. Silent when no drop is
        published, like the other published-table families.
        """
        if self.config is None:
            return None
        sign, entries, recycle = self.config.kapai_tables()
        if sign is None or not entries:
            return None
        return frame(amf3_encode(['121000', [sign, entries, recycle]]))

    def kapai_info(self, msg):
        """121001: KapaiServiceImpl.getInfo [flag, cardCounts, rewards].

        Card counts read the role_bag_dummy counts per kapai id (like
        Java's bagdummy getCount); reward states read role_kapai and
        default to [0, 0], which is byte-exact for a fresh role.
        """
        if self.config is None:
            return None
        role = self._equip_role()
        if role is None:
            return None
        _, entries, recycle = self.config.kapai_tables()
        if not entries:
            return None
        try:
            dummy = self.get_role_bag_dummy(role.get('id')) or []
        except Exception:
            dummy = []
        counts = {}
        for row in dummy:
            try:
                counts[str(row.get('goods_id'))] = counts.get(
                    str(row.get('goods_id')), 0) + int(row.get('goods_count')
                                                     or 0)
            except (TypeError, ValueError):
                continue
        card_ids = [str(r.get('kapai1', '').split(':')[0])
                    for r in entries]
        _seen, ordered = set(), []
        for cid in card_ids:
            if cid and cid not in _seen:
                _seen.add(cid)
                ordered.append(cid)
        if not ordered:
            ordered = [str(r.get('id')) for r in recycle
                       if r.get('id')]
        states = {}
        try:
            krow = self.get_role_kapai(role.get('id'))
        except Exception:
            krow = None
        if krow and krow.get('state'):
            try:
                import json as _json
                states = _json.loads(krow.get('state')) or {}
            except Exception:
                states = {}
        entry_ids = [str(r.get('ID') if r.get('ID') is not None
                         else r.get('id'))
                     for r in entries]
        rewards = []
        for eid in entry_ids:
            got, can = 0, 0
            try:
                got, can = (states.get(eid) or [0, 0])[:2]
            except (TypeError, ValueError):
                pass
            rewards.append([eid, int(got), int(can)])
        return frame(amf3_encode(
            ['121001', [0, [[c, int(counts.get(c, 0))] for c in ordered],
                         rewards]]))

    def qianfu_client(self, msg):
        """120000: QianfuhuodongServiceImpl.getClientConfig.

        [sign, rows, startMs]; startMs is the earliest row kaiqitime
        parsed server-local (see drop_millis). Silent with no drop.
        """
        if self.config is None:
            return None
        sign, rows = self.config.qianfu_table()
        if sign is None or not rows:
            return None
        starts = [self.config.drop_millis(r.get('kaiqitime')) for r in rows]
        starts = [s for s in starts if s > 0]
        start = min(starts) if starts else 0
        return frame(amf3_encode(['120000', [sign, rows, float(start)]]))

    def tuangou_config(self, msg):
        """122002: XianshituangouServiceImpl.getConfig.

        [sign, rows, [startMs, endMs]]; a matching client sign is
        silent (Java returns null), like the loginlibao sign rule.
        """
        if self.config is None:
            return None
        client_sign = None
        try:
            client_sign = str(self.safe(self.safe(msg, 1, []), 0) or '')
        except Exception:
            client_sign = None
        sign, rows, start, end = self.config.tuangou_table()
        if sign is None:
            return None
        if client_sign and client_sign == sign:
            return None
        return frame(amf3_encode(
            ['122002', [sign, rows, [float(start), float(end)]]]))

    def guanggao_list(self, msg):
        """109000: newest dengluguanggao rows (login ads)."""
        if self.config is None:
            return None
        try:
            rows = self.config.guanggao_table()
        except Exception:
            rows = []
        return frame(amf3_encode(['109000', [rows]]))

    def email_list(self, msg):
        """63001: RoleEmailServiceImpl.list; null when no mail."""
        role = self._equip_role()
        if role is None:
            return None
        try:
            rows = self.list_role_email(role.get('id')) or []
        except Exception:
            rows = []
        if not rows:
            return frame(amf3_encode(['63001', None]))
        out = [[str(r.get('id')), r.get('title') or '',
                r.get('content') or '', r.get('attachment') or '',
                int(r.get('is_read') or 0), int(r.get('is_claimed') or 0)]
               for r in rows]
        return frame(amf3_encode(['63001', out]))

    def email_info(self, msg):
        """63002: open(id) marks read, answers the mail row."""
        role = self._equip_role()
        if role is None:
            return None
        try:
            mid = str(self.safe(self.safe(msg, 1, []), 0))
        except Exception:
            return None
        try:
            row = self.get_role_email(role.get('id'), mid)
        except Exception:
            row = None
        if row is None:
            return None
        try:
            self.update_role_email(role.get('id'), mid, is_read=1)
        except Exception:
            pass
        return frame(amf3_encode(
            ['63002', [str(row.get('id')), row.get('title') or '',
                       row.get('content') or '',
                       row.get('attachment') or '']]))

    def _email_items(self, text):
        """Parse an email attachment JSON array to ItemModel dicts.

        GoodsConvertUtil.json2ItemModel reads goodsId/goodsCount (+bind /
        attributes); anything unparsable yields []."""
        try:
            import json as _json
            raw = _json.loads(text or '[]')
        except (TypeError, ValueError):
            return []
        if not isinstance(raw, list):
            return []
        items = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            gid = str(entry.get('goodsId') or '')
            try:
                count = int(entry.get('goodsCount') or 0)
            except (TypeError, ValueError):
                count = 0
            if not gid or count <= 0:
                continue
            try:
                bind = int(entry.get('bind') or 0)
            except (TypeError, ValueError):
                bind = 0
            items.append({'goods_id': gid, 'count': count, 'bind': bind,
                          'expire': entry.get('expireTime') or None})
        return items

    @staticmethod
    def _email_fail(cmd, code):
        """lingqu*/onekey gate reply: [0, EmailErrorCode].

        cmd is the literal reply id string ('63003', ...) so the
        command ledger can see the route's emission."""
        return frame(amf3_encode([cmd, [0, code]]))

    def email_attachment(self, msg):
        """63003: lingquAttachment(emailId, index) grants one item.

        Gates mirror RoleEmailServiceImpl: missing row -> 60001, no
        attachments -> 60002, bad index -> 60002, bag full -> 60007.
        Success removes that index from the JSON array and replies
        [1, emailId, index]."""
        role = self._equip_role()
        if role is None:
            return None
        try:
            data = self.safe(msg, 1, [])
            mid, index = str(self.safe(data, 0)), str(self.safe(data, 1))
        except Exception:
            return None
        if not mid:
            return None
        try:
            row = self.get_role_email(role.get('id'), mid)
        except Exception:
            row = None
        if row is None:
            return self._email_fail('63003', EMAIL_ERR_NOT_FOUND)
        items = self._email_items(row.get('attachment'))
        if not items:
            return self._email_fail('63003', EMAIL_ERR_NO_ATTACHMENT)
        try:
            pos = int(index)
        except (TypeError, ValueError):
            return self._email_fail('63003', EMAIL_ERR_NO_ATTACHMENT)
        if pos < 0 or pos >= len(items):
            return self._email_fail('63003', EMAIL_ERR_NO_ATTACHMENT)
        item = items[pos]
        try:
            fits = self._prop_fits(role.get('id'),
                                   {'goods': item['goods_id'],
                                    'count': item['count']}, item['bind'])
        except Exception:
            fits = False
        if not fits:
            return self._email_fail('63003', EMAIL_ERR_BAG_LESS)
        try:
            self._task_grant(role.get('id'), [item])
        except Exception:
            return self._email_fail('63003', EMAIL_ERR_BAG_LESS)
        import json as _json
        rest = [e for n, e in enumerate(items) if n != pos]
        kept = []
        try:
            raw = _json.loads(row.get('attachment') or '[]')
            kept = [e for n, e in enumerate(raw) if n != pos]
        except (TypeError, ValueError):
            kept = [{'goodsId': e['goods_id'], 'goodsCount': e['count']}
                    for e in rest]
        try:
            self.update_role_email(role.get('id'), mid,
                                   attachment=_json.dumps(kept))
        except Exception:
            pass
        return frame(amf3_encode(['63003', [1, mid, index]]))

    def _email_money(self, cmd, msg, kind, column, empty_code):
        """63006/63007: lingquJb/lingquYb move the mail purse on-role."""
        role = self._equip_role()
        if role is None:
            return None
        try:
            mid = str(self.safe(self.safe(msg, 1, []), 0))
        except Exception:
            return None
        if not mid:
            return None
        try:
            row = self.get_role_email(role.get('id'), mid)
        except Exception:
            row = None
        if row is None:
            return self._email_fail(cmd, EMAIL_ERR_NOT_FOUND)
        try:
            amount = int(row.get(kind) or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            return self._email_fail(cmd, empty_code)
        rid = role.get('id')
        try:
            balance = int((role or {}).get(column) or 0)
        except (TypeError, ValueError):
            balance = 0
        try:
            self.save_role_state(rid, **{column: balance + amount})
        except Exception:
            pass
        try:
            self.update_role_email(rid, mid, **{kind: 0})
        except Exception:
            pass
        # Literal reply heads so the command ledger sees each route's
        # emission (shared helper, one frame per route).
        if cmd == '63006':
            return frame(amf3_encode(['63006', [1, amount]]))
        return frame(amf3_encode(['63007', [1, amount]]))

    def email_jb(self, msg):
        """63006: lingquJb moves mail JB into tongqian."""
        return self._email_money('63006', msg, 'jb', 'tongqian',
                                 EMAIL_ERR_NO_JB)

    def email_yb(self, msg):
        """63007: lingquYb moves mail YB into lingshi."""
        return self._email_money('63007', msg, 'yb', 'lingshi',
                                 EMAIL_ERR_NO_YB)

    def email_onekey(self, msg):
        """63008: onekey(emailId) sweeps one mail's items, JB and YB.

        Bag-full aborts with [0, 60007] before anything moves; success
        zeroes all three stores and replies [1, jb, yb, [[id, count]]]."""
        role = self._equip_role()
        if role is None:
            return None
        try:
            mid = str(self.safe(self.safe(msg, 1, []), 0))
        except Exception:
            return None
        if not mid:
            return None
        try:
            row = self.get_role_email(role.get('id'), mid)
        except Exception:
            row = None
        if row is None:
            return self._email_fail('63008', EMAIL_ERR_NOT_FOUND)
        items = self._email_items(row.get('attachment'))
        try:
            for item in items:
                if not self._prop_fits(
                        role.get('id'), {'goods': item['goods_id'],
                                       'count': item['count']}, item['bind']):
                    return self._email_fail('63008', EMAIL_ERR_BAG_LESS)
        except Exception:
            return self._email_fail('63008', EMAIL_ERR_BAG_LESS)
        if items:
            try:
                self._task_grant(role.get('id'), items)
            except Exception:
                return self._email_fail('63008', EMAIL_ERR_BAG_LESS)
        rid = role.get('id')
        try:
            jb = int(row.get('jb') or 0)
        except (TypeError, ValueError):
            jb = 0
        try:
            yb = int(row.get('yb') or 0)
        except (TypeError, ValueError):
            yb = 0
        if jb > 0:
            try:
                tongqian = int((role or {}).get('tongqian') or 0)
            except (TypeError, ValueError):
                tongqian = 0
            try:
                self.save_role_state(rid, tongqian=tongqian + jb)
            except Exception:
                pass
        if yb > 0:
            try:
                lingshi = int((role or {}).get('lingshi') or 0)
            except (TypeError, ValueError):
                lingshi = 0
            try:
                self.save_role_state(rid, lingshi=lingshi + yb)
            except Exception:
                pass
        try:
            import json as _json
            self.update_role_email(rid, mid, attachment=_json.dumps([]),
                                   jb=0, yb=0)
        except Exception:
            pass
        return frame(amf3_encode(
            ['63008', [1, jb, yb,
                       [[i['goods_id'], i['count']] for i in items]]]))

    def email_delete(self, msg):
        """63004: delete(id) removes the row."""
        role = self._equip_role()
        if role is None:
            return None
        try:
            mid = str(self.safe(self.safe(msg, 1, []), 0))
        except Exception:
            return None
        try:
            self.delete_role_email(role.get('id'), mid)
        except Exception:
            pass
        return frame(amf3_encode(['63004', [1, mid]]))

    @staticmethod
    def _shenjiang_pairs(text):
        """'id:count[;...]' goods map (partquatity/needthingsid cells)."""
        pairs = []
        for cell in str(text or '').split(';'):
            if ':' not in cell:
                continue
            gid, _, count = cell.partition(':')
            gid = gid.strip()
            if not gid:
                continue
            try:
                pairs.append((gid, int(count)))
            except (TypeError, ValueError):
                continue
        return pairs

    def _shenjiang_owned(self, rid, sj_id):
        """First owned shenjiang row for an id, like ShenjiangIdFilter."""
        try:
            rows = self.get_role_shenjiang(rid) or []
        except Exception:
            return None
        return next((dict(r) for r in rows
                     if str(r.get('shenjiang_id')) == str(sj_id)), None)

    def _shenjiang_money(self, role, rid, money, amount):
        """Check-then-decr one MoneyType column (account decr port)."""
        if amount <= 0:
            return True
        if not self._bag_money_check(role, money, amount):
            return False
        try:
            balance = int((role or {}).get(
                BAG_MONEY_COLUMNS[money]) or 0)
        except (TypeError, ValueError):
            return False
        try:
            self.save_role_state(rid, **{BAG_MONEY_COLUMNS[money]:
                                          balance - amount})
        except Exception:
            pass
        return True

    def shenjiang_activate(self, msg):
        """Command 41001: fragment-synthesis activation (suiPianHeCheng).

        C> shenjiang id. Gates in order: unknown id or owned id stays
        silent, fragment short answers [0, 420011], zhenqi short [0, 1001].
        Costs burn, a zeroed row is inserted, and the reply is [1, id].
        """
        sj_id = str(self.safe(msg, 1) or '')
        role = self._equip_role()
        if role is None or not sj_id or self.config is None:
            return None
        rid = role.get('id')
        tier = self.config.shenjiang_tier(sj_id, 0)
        if tier is None:
            return None
        if self._shenjiang_owned(rid, sj_id) is not None:
            return None
        pairs = self._shenjiang_pairs(tier.get('partquatity'))
        for gid, count in pairs:
            if self._bag_goods_count(rid, gid) < count:
                return frame(amf3_encode(
                    [str(CMD_SHENJIANG_ACTIVATE), [0, SHENJIANG_ERR_FRAG]]))
        try:
            need_zhenqi = int(tier.get('zhenqi') or 0)
        except (TypeError, ValueError):
            need_zhenqi = 0
        try:
            zhenqi = int(role.get('zhenqi') or 0)
        except (TypeError, ValueError):
            zhenqi = 0
        if zhenqi < need_zhenqi:
            return frame(amf3_encode(
                [str(CMD_SHENJIANG_ACTIVATE), [0, GENERAL_ZHENQI]]))
        for gid, count in pairs:
            try:
                self._bag_decr(rid, gid, count)
            except Exception:
                pass
        try:
            self.save_role_state(rid, zhenqi=zhenqi - need_zhenqi)
        except Exception:
            pass
        import json as _json
        skills = {}
        for name in str(tier.get('skill') or '').split(';'):
            name = name.strip()
            if name:
                skills[name] = 0
        try:
            self.save_role_shenjiang(rid, sj_id, jiangxing_id='',
                                     jiangxing_rank=0,
                                     skills=_json.dumps(skills))
        except Exception:
            pass
        return frame(amf3_encode([str(CMD_SHENJIANG_ACTIVATE), [1, sj_id]]))

    def shenjiang_skill_up(self, msg):
        """Command 41002: shenjiang skill upgrade (skillUpgrade).

        C> [shenjiang id, skill id]. Gates in order: no owned row or no
        (id, rank) tier stays silent, skill at maxLv answers [0, 420010],
        skill at/over level 100 the same, a skill missing from the owned
        JSON stays silent.        checkSkillUpgrade then gates: no skill row [0, 420001], role
        level short [0, 1000], zhenqi short [0, 1001], exp short [0, 1014],
        YXB short [0, 1003], fragment short [0, 1005]. (The shenjiang
        id/rank lookups have no local source, so the 420012 arm stays
        silent like a null getShengjiangId.)
        Costs burn, the learn roll decides, and the reply is [1, id, skill,
        newLevel] or [0, id, skill, level]. The additionSjid chain has no
        local source, so it is logged, not followed.
        """
        data = self.safe(msg, 1, [])
        sj_id = str(self.safe(data, 0) or '')
        skill_id = str(self.safe(data, 1) or '')
        role = self._equip_role()
        if role is None or not sj_id or not skill_id or \
                self.config is None:
            return None
        rid = role.get('id')
        row = self._shenjiang_owned(rid, sj_id)
        if row is None:
            return None
        import json as _json
        try:
            skills = _json.loads(row.get('skills') or '{}') or {}
        except Exception:
            skills = {}
        if skill_id not in skills:
            return None
        try:
            rank = int(row.get('jiangxing_rank') or 0)
        except (TypeError, ValueError):
            rank = 0
        tier = self.config.shenjiang_tier(sj_id, rank)
        if tier is None:
            return None
        try:
            level = int(skills.get(skill_id) or 0)
        except (TypeError, ValueError):
            level = 0
        try:
            max_lv = int(tier.get('maxlv') or 0)
        except (TypeError, ValueError):
            max_lv = 0
        if level + 1 > max_lv or level >= 100:
            return frame(amf3_encode(
                [str(CMD_SHENJIANG_SKILLUP),
                 [0, SHENJIANG_ERR_MAXSKILL]]))
        info = self.config.skill_info(skill_id, level)
        if info is None:
            return frame(amf3_encode(
                [str(CMD_SHENJIANG_SKILLUP),
                 [0, SHENJIANG_ERR_NOSKILLCFG]]))
        err = self._shenjiang_skill_gates(role, info)
        if err is not None:
            return frame(amf3_encode([str(CMD_SHENJIANG_SKILLUP), err]))
        self._shenjiang_skill_pay(role, rid, info)
        if not self._lottery_roll(info.get('learnodds')):
            return frame(amf3_encode(
                [str(CMD_SHENJIANG_SKILLUP), [0, sj_id, skill_id, level]]))
        skills[skill_id] = level + 1
        try:
            self.save_role_shenjiang(rid, sj_id,
                                     skills=_json.dumps(skills))
        except Exception:
            pass
        try:
            self.save_role_skill(rid, skill_id, level + 1)
        except Exception:
            pass
        log.info('conn %d: shenjiang %r addition chain skipped (no source)',
                 self.conn_id, sj_id)
        return frame(amf3_encode(
            [str(CMD_SHENJIANG_SKILLUP), [1, sj_id, skill_id, level + 1]]))

    def _shenjiang_skill_gates(self, role, info):
        """checkSkillUpgrade gates, or None when the upgrade may proceed.

        The shenjiangId/shengjiangRank columns are absent from the local
        JiNengBiao rows, so those two gates are skipped like a null
        getShengjiangId; everything else follows the bytecode order.
        """
        try:
            role_level = int(role.get('level') or 0)
        except (TypeError, ValueError):
            role_level = 0
        try:
            need_level = int(info.get('levelneed') or 0)
        except (TypeError, ValueError):
            need_level = 0
        if need_level > role_level:
            return [0, GENERAL_LEVEL]
        try:
            need_zhenqi = int(info.get('zhenqineed') or 0)
        except (TypeError, ValueError):
            need_zhenqi = 0
        try:
            zhenqi = int(role.get('zhenqi') or 0)
        except (TypeError, ValueError):
            zhenqi = 0
        if need_zhenqi > zhenqi:
            return [0, GENERAL_ZHENQI]
        try:
            need_exp = int(info.get('expneed') or 0)
        except (TypeError, ValueError):
            need_exp = 0
        try:
            exp = int(role.get('exp') or 0)
        except (TypeError, ValueError):
            exp = 0
        if need_exp > 0 and exp < need_exp:
            return [0, GENERAL_ROLE_EXP]
        try:
            need_yxb = int(info.get('goldneed') or 0)
        except (TypeError, ValueError):
            need_yxb = 0
        if need_yxb > 0 and not self._bag_money_check(role, 'YXB', need_yxb):
            return [0, GENERAL_JB]
        item = str(info.get('itemneed') or '')
        if item:
            gid, _, count = item.partition('|')
            try:
                need = int(count)
            except (TypeError, ValueError):
                need = 0
            if gid and need > 0 and \
                    self._bag_goods_count(role.get('id'), gid) < need:
                return [0, GENERAL_GOODS]
        return None

    def _shenjiang_skill_pay(self, role, rid, info):
        """Burn the skillUpgrade costs (zhenqi/exp/YXB/goods), best effort."""
        try:
            zhenqi = int(role.get('zhenqi') or 0)
            exp = int(role.get('exp') or 0)
        except (TypeError, ValueError):
            zhenqi, exp = 0, 0
        try:
            self.save_role_state(
                rid, zhenqi=zhenqi - int(info.get('zhenqineed') or 0),
                exp=exp - int(info.get('expneed') or 0))
        except Exception:
            pass
        try:
            need_yxb = int(info.get('goldneed') or 0)
        except (TypeError, ValueError):
            need_yxb = 0
        if need_yxb > 0:
            try:
                balance = int(role.get('tongqian') or 0)
            except (TypeError, ValueError):
                balance = 0
            try:
                self.save_role_state(rid, tongqian=balance - need_yxb)
            except Exception:
                pass
        item = str(info.get('itemneed') or '')
        if item:
            gid, _, count = item.partition('|')
            try:
                self._bag_decr(rid, gid, int(count))
            except Exception:
                pass

    def shenjiang_can_jihuo(self, msg):
        """Command 41003: star-chart pre-check (canJihuoJiangxingtu).

        C> [shenjiang id, chart id]. Gates mirror checkCanJihuoJiangxingtu:
        unknown chart, no owned row, unmet skill, already-lit chart,
        short role level [0, 1000], short zhenqi [0, 1001], broken chain
        [0, '423001'], short rank [0, '423006'], short money [0, '423002'].
        Passing burns zhenqi + money, arms the chart, and answers
        [1, maxTimes, moneyType, costValue, chart id].
        """
        data = self.safe(msg, 1, [])
        sj_id = str(self.safe(data, 0) or '')
        dwid = str(self.safe(data, 1) or '')
        role = self._equip_role()
        if role is None or not sj_id or not dwid or self.config is None:
            return None
        rid = role.get('id')
        cfg = self.config.jiangxingtu_config(dwid)
        if cfg is None:
            return None
        row = self._shenjiang_owned(rid, sj_id)
        if row is None:
            return None
        err = self._shenjiang_jihuo_gates(role, row, cfg, dwid)
        if err is not None:
            return frame(amf3_encode([str(CMD_SHENJIANG_CANJIHUO), err]))
        try:
            cost_zhenqi = int(cfg.get('costzhenqi') or 0)
            zhenqi = int(role.get('zhenqi') or 0)
        except (TypeError, ValueError):
            cost_zhenqi, zhenqi = 0, 0
        try:
            self.save_role_state(rid, zhenqi=zhenqi - cost_zhenqi)
        except Exception:
            pass
        money = SHENJIANG_MONEY_NAMES.get(int(cfg.get('costtype') or 0))
        try:
            cost_value = int(cfg.get('costvalue') or 0)
        except (TypeError, ValueError):
            cost_value = 0
        if money is not None and cost_value > 0:
            self._shenjiang_money(role, rid, money, cost_value)
        try:
            self.save_role_shenjiang(rid, sj_id, cur_jiangxing_id=dwid,
                                     jiangxing_state=1)
        except Exception:
            pass
        log.info('conn %d: CanJihuoJiangxingtuEvent skipped (no bus)',
                 self.conn_id)
        try:
            max_times = int(cfg.get('needmaxtime') or 0)
        except (TypeError, ValueError):
            max_times = 0
        return frame(amf3_encode(
            [str(CMD_SHENJIANG_CANJIHUO),
             [1, max_times, int(cfg.get('costtype') or 0), cost_value,
              dwid]]))

    def _shenjiang_jihuo_gates(self, role, row, cfg, dwid):
        """checkCanJihuoJiangxingtu gates, or None when lighting may start."""
        import json as _json
        need = str(cfg.get('jinengneed') or '')
        if need:
            sk, _, lv = need.partition(':')
            try:
                skills = _json.loads(row.get('skills') or '{}') or {}
            except Exception:
                skills = {}
            try:
                have = int(skills.get(sk.strip()) or 0)
                want = int(lv)
            except (TypeError, ValueError):
                have, want = 0, 1
            if have < want:
                return [0, SHENJIANG_ERR_SKILLLV]
        cur = str(row.get('cur_jiangxing_id') or '')
        if not cur:
            cur = str(row.get('jiangxing_id') or '')
        if cur and (cur == dwid or self._shenjiang_before(dwid, cur)):
            return [0, SHENJIANG_ERR_ACTIVED]
        try:
            role_level = int(role.get('level') or 0)
            need_level = int(cfg.get('needlv') or 0)
        except (TypeError, ValueError):
            role_level, need_level = 0, 0
        if need_level > role_level:
            return [0, GENERAL_LEVEL]
        try:
            cost_zhenqi = int(cfg.get('costzhenqi') or 0)
            zhenqi = int(role.get('zhenqi') or 0)
        except (TypeError, ValueError):
            cost_zhenqi, zhenqi = 0, 0
        if cost_zhenqi > zhenqi:
            return [0, GENERAL_ZHENQI]
        before = str(cfg.get('abovedw') or '')
        if before and cur and cur != before and \
                not self._shenjiang_before(before, cur):
            return [0, SHENJIANG_ERR_BEFORE]
        try:
            rank = int(row.get('jiangxing_rank') or 0)
            dw_level = int(cfg.get('dwlv') or 0)
        except (TypeError, ValueError):
            rank, dw_level = 0, 0
        if rank < dw_level:
            return [0, SHENJIANG_ERR_LVTOP]
        money = SHENJIANG_MONEY_NAMES.get(int(cfg.get('costtype') or 0))
        try:
            cost_value = int(cfg.get('costvalue') or 0)
        except (TypeError, ValueError):
            cost_value = 0
        if money is None:
            return None if cost_value <= 0 else [0, SHENJIANG_ERR_MONEY]
        if cost_value > 0 and \
                not self._bag_money_check(role, money, cost_value):
            return [0, SHENJIANG_ERR_MONEY]
        return None

    def _shenjiang_before(self, first, second):
        """dwId1BeforedwId2: chart `first` precedes `second` in one chain."""
        if not first or not second or first == second:
            return first == second
        try:
            a = self.config.jiangxingtu_config(first)
            b = self.config.jiangxingtu_config(second)
        except Exception:
            return False
        if a is None or b is None:
            return False
        if str(a.get('dalei') or '') != str(b.get('dalei') or ''):
            return False
        try:
            return (int(a.get('dwstratum') or 0),
                    int(a.get('dwlv') or 0)) < \
                   (int(b.get('dwstratum') or 0), int(b.get('dwlv') or 0))
        except (TypeError, ValueError):
            return False

    def shenjiang_jihuo(self, msg):
        """Command 41004: light the armed star chart (jihuoJiangxingtu).

        C> shenjiang id; the chart is the row's armed curJiangxingId and the
        boolean is hardcoded false, exactly like the Action call. Gates:
        no owned row, no armed chart, or an unmet skill requirement stay
        silent. Failure grants failAddExp and answers [0, exp]; success
        grants successAddExp, auto-learns the chart skill, and answers
        [1, chart id, attr map, skill ids, exp]. Notices have no bus here.
        """
        sj_id = str(self.safe(msg, 1) or '')
        role = self._equip_role()
        if role is None or not sj_id or self.config is None:
            return None
        rid = role.get('id')
        row = self._shenjiang_owned(rid, sj_id)
        if row is None:
            return None
        dwid = str(row.get('cur_jiangxing_id') or '')
        if not dwid:
            return None
        cfg = self.config.jiangxingtu_config(dwid)
        if cfg is None:
            return None
        if not self._shenjiang_skill_need(row, cfg):
            return None
        try:
            fail_count = int(row.get('fail_count') or 0)
        except (TypeError, ValueError):
            fail_count = 0
        if self._shenjiang_jihuo_roll(fail_count, cfg):
            return self._shenjiang_jihuo_success(role, rid, sj_id, row,
                                                 cfg, dwid)
        return self._shenjiang_jihuo_fail(rid, sj_id, row, cfg, dwid,
                                          fail_count)

    def _shenjiang_skill_need(self, row, cfg):
        """Jihuo's jinengneed gate (skill id at a level), best effort."""
        import json as _json
        need = str(cfg.get('jinengneed') or '')
        if not need:
            return True
        sk, _, lv = need.partition(':')
        try:
            skills = _json.loads(row.get('skills') or '{}') or {}
            have = int(skills.get(sk.strip()) or 0)
            return have >= int(lv)
        except (TypeError, ValueError):
            return False

    def _shenjiang_jihuo_roll(self, fail_count, cfg):
        """computeIsSuccess: pity window shrinks with kaifu days.

        need = max(0, minTimes - kaifuDays/kaifuJianmian); below need the
        roll always fails, at maxTimes it always succeeds, otherwise a
        float roll against successOdds decides. kaifuJianmian has no column
        in JiangXingTu.jat, so the row's jolt is used (mostly 1).
        """
        try:
            min_times = int(cfg.get('needmintime') or 0)
            max_times = int(cfg.get('needmaxtime') or 0)
            odds = float(cfg.get('successodds') or 0)
            jianmian = float(cfg.get('jolt') or 1) or 1
        except (TypeError, ValueError):
            return False
        try:
            days = self._vip_kaifu_days()
        except Exception:
            days = 0
        need = max(0, min_times - int(days / jianmian))
        if fail_count < need:
            return False
        if fail_count >= max_times:
            return True
        return self._lottery_success(odds)

    def _shenjiang_grant_exp(self, rid, amount):
        """incrExp, returning (granted amount, level-up extras)."""
        try:
            amount = int(amount or 0)
        except (TypeError, ValueError):
            return 0, []
        if amount <= 0:
            return 0, []
        role = self._equip_role()
        if role is None:
            return 0, []
        try:
            _total, _level, _gained, exp_frames = self._role_gain_exp(
                role, rid, amount)
        except Exception:
            return amount, []
        return amount, exp_frames[1:]

    def _shenjiang_jihuo_fail(self, rid, sj_id, row, cfg, dwid, fail_count):
        """Failed lighting: fail count +1, failAddExp, [0, exp] reply."""
        try:
            granted, extra = self._shenjiang_grant_exp(
                rid, int(cfg.get('failaddexp') or 0))
        except (TypeError, ValueError):
            granted, extra = 0, []
        try:
            self.save_role_shenjiang(rid, sj_id,
                                     cur_jiangxing_id='',
                                     fail_count=fail_count + 1)
        except Exception:
            pass
        log.info('conn %d: JihuoJiangxingtuFailEvent skipped (no bus)',
                 self.conn_id)
        out = [frame(amf3_encode(
            [str(CMD_SHENJIANG_JIHUO), [0, granted]]))]
        out.extend(extra)
        return tuple(out) if len(out) > 1 else out[0]

    def _shenjiang_jihuo_success(self, role, rid, sj_id, row, cfg, dwid):
        """Successful lighting: chart id set, skill learned, full reply."""
        try:
            granted, extra = self._shenjiang_grant_exp(
                rid, int(cfg.get('successaddexp') or 0))
        except (TypeError, ValueError):
            granted, extra = 0, []
        skill_ids = [s for s in (str(cfg.get('successskillid') or ''),
                                 str(cfg.get('prizeskillid') or ''))
                     if s]
        for sk in skill_ids:
            try:
                self.save_role_skill(rid, sk, 1)
            except Exception:
                pass
        try:
            self.save_role_shenjiang(rid, sj_id, jiangxing_id=dwid,
                                     cur_jiangxing_id='', fail_count=0)
        except Exception:
            pass
        log.info('conn %d: JihuoJiangxingtuEvent+notice skipped (no bus)',
                 self.conn_id)
        import json as _json
        attrs = {}
        for name in ('hitpoints', 'physicdamage', 'physicdefence', 'mana',
                     'volt', 'attackrate', 'velocity', 'critical'):
            if cfg.get(name) not in ('', None):
                attrs[name] = cfg.get(name)
        out = [frame(amf3_encode(
            [str(CMD_SHENJIANG_JIHUO),
             [1, dwid, convert_index_attribute(attrs, TASK_ATTRIBUTE_INDEX),
              skill_ids, granted]]))]
        out.extend(extra)
        return tuple(out) if len(out) > 1 else out[0]

    def shenjiang_jinjie(self, msg):
        """Command 41021: breakthrough the star-chart rank (jiangxingtuJinjie).

        C> [shenjiang id, auto-mall boolean]. Gates: no owned row stays
        silent, a tier that forbids breakthrough answers [0, '423005'], an
        unlit chart [0, '423004'], short YXB coin [0, 1003], and (without
        auto-mall) short goods [0, 1005]. Auto-mall YB cover has no local
        price source, so it fails closed with the same goods error. Costs
        burn; a full blessing bar or a won odds roll ranks up ([1, id,
        newRank]), otherwise blessing grows and the reply is [-1, id, lucky].
        """
        data = self.safe(msg, 1, [])
        sj_id = str(self.safe(data, 0) or '')
        auto = bool(self.safe(data, 1))
        role = self._equip_role()
        if role is None or not sj_id or self.config is None:
            return None
        rid = role.get('id')
        row = self._shenjiang_owned(rid, sj_id)
        if row is None:
            return None
        try:
            rank = int(row.get('jiangxing_rank') or 0)
        except (TypeError, ValueError):
            rank = 0
        tier = self.config.shenjiang_tier(sj_id, rank)
        if tier is None or not tier.get('jinjie'):
            return frame(amf3_encode(
                [str(CMD_SHENJIANG_JINJIE), [0, SHENJIANG_ERR_RANKTOP]]))
        if not str(row.get('jiangxing_id') or ''):
            return frame(amf3_encode(
                [str(CMD_SHENJIANG_JINJIE), [0, SHENJIANG_ERR_LVNOTTOP]]))
        try:
            need_coin = int(tier.get('jinjieneedcoin') or 0)
        except (TypeError, ValueError):
            need_coin = 0
        if need_coin > 0 and \
                not self._bag_money_check(role, 'YXB', need_coin):
            return frame(amf3_encode(
                [str(CMD_SHENJIANG_JINJIE), [0, GENERAL_JB]]))
        pairs = self._shenjiang_pairs(tier.get('needthingsid'))
        short = any(self._bag_goods_count(rid, gid) < n
                    for gid, n in pairs)
        if short:
            if auto:
                log.info('conn %d: jinjie auto-mall cover skipped '
                         '(no price source)', self.conn_id)
            return frame(amf3_encode(
                [str(CMD_SHENJIANG_JINJIE), [0, GENERAL_GOODS]]))
        self._shenjiang_money(role, rid, 'YXB', need_coin)
        for gid, count in pairs:
            try:
                self._bag_decr(rid, gid, count)
            except Exception:
                pass
        log.info('conn %d: JiangxingtuJinjieDecrEvent skipped (no bus)',
                 self.conn_id)
        try:
            lucky = int(row.get('rank_lucky') or 0)
            fail_count = int(row.get('rank_fail_count') or 0)
            shangxian = int(tier.get('maxblessing') or 0)
            odds = float(tier.get('odds') or 0)
        except (TypeError, ValueError):
            lucky, fail_count, shangxian, odds = 0, 0, 0, 0
        if lucky >= shangxian and shangxian > 0:
            return self._shenjiang_jinjie_success(rid, sj_id, rank)
        if self._lottery_success(odds):
            return self._shenjiang_jinjie_success(rid, sj_id, rank)
        return self._shenjiang_jinjie_fail(rid, sj_id, tier, rank,
                                           fail_count, lucky)

    def _shenjiang_jinjie_success(self, rid, sj_id, rank):
        """Rank up: fail count and blessing cleared, [1, id, newRank]."""
        try:
            self.save_role_shenjiang(rid, sj_id, jiangxing_rank=rank + 1,
                                     rank_fail_count=0, rank_lucky=0)
        except Exception:
            pass
        log.info('conn %d: jinjie 423011 notice skipped (no bus)',
                 self.conn_id)
        return frame(amf3_encode(
            [str(CMD_SHENJIANG_JINJIE), [1, sj_id, rank + 1]]))

    def _shenjiang_jinjie_fail(self, rid, sj_id, tier, rank, fail_count,
                               lucky):
        """Rank fail: fail count +1, blessing grows, [-1, id, lucky].

        A blessing bar at/over the cap flips to success, like Java's
        jinjieFail tail (pity overflow also ranks up).
        """
        import random as _random
        try:
            lo = int(tier.get('addminblessing') or 0)
            hi = int(tier.get('addmaxblessing') or 0)
        except (TypeError, ValueError):
            lo, hi = 0, 0
        lucky = lucky + (_random.randint(lo, hi) if hi >= lo and hi > 0
                         else 0)
        try:
            shangxian = int(tier.get('maxblessing') or 0)
        except (TypeError, ValueError):
            shangxian = 0
        try:
            self.save_role_shenjiang(rid, sj_id,
                                     rank_fail_count=fail_count + 1,
                                     rank_lucky=lucky)
        except Exception:
            pass
        if shangxian > 0 and lucky >= shangxian:
            return self._shenjiang_jinjie_success(rid, sj_id, rank)
        return frame(amf3_encode(
            [str(CMD_SHENJIANG_JINJIE), [-1, sj_id, lucky]]))

    def shenjiang_info(self, msg):
        """41000: ShenjiangServiceImpl.getShenjiangInfo live rows."""
        role = self._equip_role()
        if role is None:
            return None
        try:
            rows = self.get_role_shenjiang(role.get('id')) or []
        except Exception:
            rows = []
        out = [[str(r.get('shenjiang_id') or r.get('shenjiang_key') or ''),
                r.get('jiangxing_rank') or 0]
               for r in rows]
        return frame(amf3_encode(['41000', out]))

    def chengjiu_panel(self):
        """Command 89000: getChengJiu lists claimed achievements.

        RoleChengjiuServiceImpl.getChengJiu maps each persisted row to
        [taskId, taskStatus] (an empty cache answers an empty array); only
        ever STATUS_1 rows exist, since rows are created at claim time.
        """
        role, rid = self._task_role()
        if role is None:
            return None
        try:
            rows = self.get_role_chengjiu(rid) or []
        except Exception:
            rows = []
        out = [[str(r.get('task_id') or ''), r.get('task_status') or 0]
               for r in rows]
        return frame(amf3_encode([str(CMD_CHENGJIU_PANEL), out]))

    def chengjiu_claim(self, msg):
        """Command 89005: getLingQu claims an achievement reward.

        Gates in order: unknown achievement id answers null; an already
        claimed id answers [0, id]; a failed kaiqi/tiaojian gate answers
        [False, [0, id]] ([False, 0] for an unknown gate type); a full bag
        answers [0, 1006] (GeneralErrorCode.BAG_SLOT_NOT_ENOUGH); an empty
        reward list answers null. Success persists STATUS_1, grants the
        job-filtered rewards, and replies [1, id, [0, 0, formart2 maps]].
        The ChengJiuFinishEvent has no bus here, so that tail is logged.
        """
        cid = self.safe(msg, 1)
        role, rid = self._task_role()
        if role is None or not isinstance(cid, str) or not cid \
                or self.config is None:
            return None
        cfg = self.config.chengjiu_config(cid)
        if cfg is None:
            return frame(amf3_encode([str(CMD_CHENGJIU_CLAIM), None]))
        try:
            rows = self.get_role_chengjiu(rid) or []
        except Exception:
            rows = []
        if self._chengjiu_claimed(rows, cid):
            return frame(amf3_encode([str(CMD_CHENGJIU_CLAIM), [0, cid]]))
        gate = self._chengjiu_gates(role, rid, cfg)
        if gate is None:
            return None
        ok, fail_body = gate
        if not ok:
            return frame(amf3_encode(
                [str(CMD_CHENGJIU_CLAIM), [False, fail_body]]))
        grant = self._chengjiu_rewards(role, cfg)
        if not grant:
            return frame(amf3_encode([str(CMD_CHENGJIU_CLAIM), None]))
        for item in grant:
            if not self._prop_fits(rid, {'goods': item['goods_id'],
                                         'count': item['count']},
                                   item.get('bind') or 0):
                return frame(amf3_encode(
                    [str(CMD_CHENGJIU_CLAIM), [0, GENERAL_NOSLOT]]))
        try:
            self.save_role_chengjiu(rid, cid, task_status=1)
        except Exception:
            return None
        self._task_grant(rid, [{'goods_id': item['goods_id'],
                                'count': item['count'],
                                'bind': item.get('bind') or 0}
                               for item in grant])
        records = [self.chengjiu_grant_record(rid, row)
                   for row in self._chengjiu_granted(rid, grant)]
        log.info('conn %d: chengjiu %r claimed (event skipped, no bus)',
                 self.conn_id, cid)
        return frame(amf3_encode(
            [str(CMD_CHENGJIU_CLAIM), [1, cid, [0, 0, records]]]))

    @staticmethod
    def _chengjiu_claimed(rows, cid):
        """Already-claimed check: a STATUS_1 row for the achievement."""
        for row in rows or []:
            if str(row.get('task_id') or '') != cid:
                continue
            try:
                if int(row.get('task_status') or 0) == 1:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def _chengjiu_gates(self, role, rid, cfg):
        """isTaskKaiqi/isTaskTiaoJian over kaiqi then tiaojian.

        Type 1 names a main quest (TaskMainServiceImpl.isTaskfinsh), type 2
        a role level; anything else fails with a bare 0, like the Java
        fallthrough. Returns (ok, fail_body) or None on a bad role state.
        """
        for gates in (cfg.get('kaiqi') or [], cfg.get('tiaojian') or []):
            for kind, value in gates:
                if kind == 2:
                    try:
                        need = int(str(value))
                    except (TypeError, ValueError):
                        return False, 0
                    if self._task_role_level(role) < need:
                        return False, [0, cfg['id']]
                elif kind == 1:
                    if not self._chengjiu_task_finished(rid, str(value)):
                        return False, [0, cfg['id']]
                else:
                    return False, 0
        return True, 0

    def _chengjiu_task_finished(self, rid, task_id):
        """TaskMainServiceImpl.isTaskfinsh: on the quest in state 1, or past it."""
        try:
            row = self.get_task_main(rid)
        except Exception:
            return False
        if not row:
            return False
        cur = str(row.get('task_id') or '')
        if cur == task_id:
            try:
                return int(row.get('state') or 0) == 1
            except (TypeError, ValueError):
                return False
        return task_id < cur

    def _chengjiu_rewards(self, role, cfg):
        """GoodsJobFilter over the achievement rewards: unknown goods and job-gated equips drop."""
        job = str(role.get('job') or '')
        grant = []
        for item in cfg.get('rewards') or []:
            category = self.config.goods_category(item['goods_id']) \
                if self.config is not None else None
            if category is None:
                continue
            if category in ('20', ''):
                gate = self.config.goods_job(item['goods_id']) \
                    if self.config is not None else None
                if gate != '0' and gate != job:
                    continue
            grant.append(item)
        return grant

    def _chengjiu_granted(self, rid, grant):
        """Granted bag rows for the formart2 reply half, by (goods, bind)."""
        try:
            slots = self.get_role_bag_slots(rid, -1000000, 1000000) or []
        except Exception:
            return []
        wanted = {(item['goods_id'], item.get('bind') or 0)
                  for item in grant}
        return sorted(
            (s for s in slots
             if (str(s.get('goods_id') or ''), s.get('bind') or 0) in wanted),
            key=lambda s: s.get('slot_num') or 0)

    def chengjiu_grant_record(self, rid, row):
        """One StoreGoodsOutput.formart2 record for a granted bag row."""
        shared = self.buyback_map({'id': rid}, row)
        shared['1'] = str(row.get('bag_id') or row.get('goods_id') or '')
        return [shared[str(i)] for i in range(18)]

    def _mall_expired(self, row):
        """checkExpireTime: losttime past (60s grace) or duration under 60s."""
        now = int(time.time() * 1000)
        lost = str(row.get('losttime') or '').strip()
        if lost:
            deadline = None
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
                try:
                    deadline = int(time.mktime(
                        time.strptime(lost, fmt)) * 1000)
                    break
                except (ValueError, OverflowError):
                    continue
            if deadline is None or deadline <= now + 60000:
                return True
        try:
            duration = int(row.get('duration') or 0)
        except (TypeError, ValueError):
            duration = 0
        return duration > 0 and now + duration * 1000 <= now + 60000

    def mall_buy(self, msg):
        """Command 32001: MallServiceImpl.buyGoods without guild or coupons.

        C> is [goodsId, count, npcId, _, moneyType, bindFlag, couponGuid?].
        The entry guards are silent like MallAction (bad ids, count, money
        type, or a non--1 bindFlag with count > 1 answer nothing); failures
        reply [0, code], success [1, [goodsId, count, decr, moneyType]].
        BANGGONG (guild) buys fail closed with 430412: no guild system is
        ported. Coupon discounts fail closed with 430418: the discount
        table yuanbaoxiaofeiyouhuika.jat is not shipped (missing or expired
        coupon rows still reply 430416/430417 exactly like Java).
        """
        args = self.safe(msg, 1, [])
        goods_id = self.safe(args, 0)
        npc_id = self.safe(args, 2)
        count = self.safe(args, 1)
        money_type = self.safe(args, 4)
        bind_flag = self.safe(args, 5)
        coupon = self.safe(args, 6) if len(args) > 6 else None
        if not goods_id or not npc_id or self.config is None:
            return None
        if isinstance(count, bool) or not isinstance(count, int) or \
                count <= 0:
            return None
        if isinstance(money_type, bool) or \
                not isinstance(money_type, int) or money_type < 0:
            return None
        if bind_flag is not None:
            if isinstance(bind_flag, bool) or \
                    not isinstance(bind_flag, int):
                return None
            if bind_flag != -1 and count > 1:
                return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        rid = role.get('id')
        if self.config._goods_table().get(str(goods_id)) is None:
            return frame(amf3_encode(
                [str(CMD_MALL_BUY), [0, MALL_ERR_NO_GOODS]]))
        offer = self.config.mall_offer(str(goods_id), str(npc_id))
        if offer is None:
            return frame(amf3_encode(
                [str(CMD_MALL_BUY), [0, MALL_ERR_NO_IN_BUY_LIST]]))
        if self._mall_expired(offer):
            return frame(amf3_encode(
                [str(CMD_MALL_BUY), [0, MALL_ERR_GOODS_NOW_EXPIRE]]))
        money_name = MALL_MONEY_NAMES.get(money_type)
        if money_name is None:
            return None
        if coupon:
            if money_type != 2:
                return frame(amf3_encode(
                    [str(CMD_MALL_BUY), [0, MALL_ERR_YOUHUI_CAN_NOT_USE]]))
            try:
                admitted = self.get_role_bag_slot_by_bag_id(
                    rid, str(coupon))
            except Exception:
                admitted = None
            if admitted is None:
                return frame(amf3_encode(
                    [str(CMD_MALL_BUY), [0, MALL_ERR_YOUHUI_EXPIRE]]))
            return frame(amf3_encode(
                [str(CMD_MALL_BUY),
                 [0, MALL_ERR_YOUHUI_CAN_NOT_USE_MONEY]]))
        if money_name == 'BANGGONG':
            return frame(amf3_encode(
                [str(CMD_MALL_BUY), [0, MALL_ERR_BANGGONG_NO_ENOUGHT]]))
        if money_type not in offer['costs']:
            return frame(amf3_encode(
                [str(CMD_MALL_BUY), [0, MALL_ERR_ACCOUNT_TYPE_ERROR]]))
        total = offer['costs'][money_type] * count
        try:
            balance = int(role.get(BAG_MONEY_COLUMNS[money_name]) or 0)
        except (TypeError, ValueError):
            return frame(amf3_encode(
                [str(CMD_MALL_BUY),
                 [0, MALL_NO_ENOUGH[money_type]]]))
        if balance < total:
            return frame(amf3_encode(
                [str(CMD_MALL_BUY), [0, MALL_NO_ENOUGH[money_type]]]))
        bind = 1 if money_type == 3 else 0
        if not self._prop_fits(rid, {'goods': str(goods_id),
                                     'count': count}, bind):
            return frame(amf3_encode(
                [str(CMD_MALL_BUY), [0, MALL_ERR_BAG_NO_SLOT]]))
        self._bag_money_decr(rid, money_name, total)
        self._task_grant(rid, [{'goods_id': str(goods_id), 'count': count,
                                'bind': bind}])
        return frame(amf3_encode(
            [str(CMD_MALL_BUY),
             [1, [str(goods_id), count, total, money_type]]]))

    def buyback_map(self, role, row):
        """One StoreGoodsOutput.formart map for a buyback row (32002/32005)."""
        category = (self.config.goods_category(row.get('goods_id'))
                    if self.config else None)
        vo = None
        if category == '20' and row.get('attributes'):
            try:
                vo = equip_vo(row.get('attributes'))
            except Exception:
                vo = None
        fight = (self.config.equip_item_fight(row)
                 if self.config is not None and vo is not None else 0)
        exp_val = self._bag_exp_cell(row) if category in ('100', '108') else 0
        return {
            '0': str(row.get('goods_id')),
            '1': str(row.get('buyback_id') or row.get('goods_id')),
            '2': row.get('slot_num'),
            '3': row.get('count') or 0,
            '4': str(role.get('id')),
            '5': row.get('item_level') or 0,
            '6': row.get('rare_level') or 0,
            '7': row.get('bind') or 0,
            '8': row.get('expire_time'),
            '9': _fujia_wire(fujia_client_map(vo)) if vo is not None else None,
            '10': xingxing_lv(vo) if vo is not None else 0,
            '11': None,
            '12': fight,
            '13': '',
            '14': qh_xingxings_client(vo) if vo is not None else None,
            '15': exp_val if category == '100' else 0,
            '16': 0,
            '17': exp_val if category == '108' else 0,
        }

    def buyback_record(self, role, row):
        """One StoreGoodsOutput.formart1 record (18 slots) for a buyback row."""
        shared = self.buyback_map(role, row)
        return [shared['0'], shared['1'], shared['2'], shared['3'],
                shared['4'], shared['5'], shared['6'], shared['7'],
                shared['8'], shared['9'], shared['10'], shared['11'],
                shared['12'], shared['13'], shared['14'], shared['15'],
                shared['16'], shared['17']]

    @staticmethod
    def _buyback_created(row):
        """Createtime as int for the eviction sort (missing reads as 0)."""
        try:
            return int(row.get('createtime') or 0)
        except (TypeError, ValueError):
            return 0

    def buyback_sell(self, msg):
        """Command 32002: GoodsBuyBackServiceImpl.addGoodsBuyBack.

        C> [bagGuid, countArg]: the count arg is parsed but never read by
        the service (the whole stack sells), so any int is accepted. A
        missing bag row answers nothing (Java returns null); a missing
        goods config replies [0, '430405']. At 27 stored rows the oldest
        (createtime ascending, the GoodsBackComppator order) is evicted
        with a 32005 [evictedId, formart] push before the 32002 reply.
        The sell price (recycle x count) is paid in YXB; the sell/buyback
        events have no bus here, so that tail is logged and skipped.
        """
        args = self.safe(msg, 1, []) or []
        if len(args) < 2:
            return None
        guid = args[0]
        if not guid or not isinstance(guid, str):
            return None
        if isinstance(args[1], bool) or not isinstance(args[1], int):
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None or self.config is None:
            return None
        rid = role.get('id')
        try:
            src = self.get_role_bag_slot_by_bag_id(rid, guid)
        except Exception:
            src = None
        if src is None:
            return None
        recycle = self.config.goods_recycle(src.get('goods_id'))
        if recycle is None:
            return frame(amf3_encode(
                [str(CMD_BUYBACK_SELL), [0, BUYBACK_ERR_NO_CONFIG]]))
        self.delete_role_bag_slot(rid, src.get('slot_num'))
        entity = {'buyback_id': str(guid),
                  'slot_num': src.get('slot_num'),
                  'goods_id': src.get('goods_id'),
                  'count': src.get('count') or 0,
                  'bind': src.get('bind') or 0,
                  'expire_time': src.get('expire_time'),
                  'rare_level': src.get('rare_level') or 0,
                  'item_level': src.get('item_level') or 0,
                  'attributes': src.get('attributes'),
                  'createtime': int(time.time() * 1000)}
        frames = []
        try:
            stored = self.get_role_buyback_all(rid) or []
        except Exception:
            stored = []
        if len(stored) >= BUYBACK_MAX_ROWS:
            oldest = sorted(stored, key=self._buyback_created)[0]
            frames.append(frame(amf3_encode(
                [str(CMD_BUYBACK_EVICT),
                 [oldest.get('buyback_id'),
                  self.buyback_map(role, entity)]])))
            self.delete_role_buyback(rid, oldest.get('buyback_id'))
        self.insert_role_buyback(rid, entity)
        try:
            total = int(role.get('tongqian') or 0) + \
                recycle * int(src.get('count') or 0)
        except (TypeError, ValueError):
            total = int(role.get('tongqian') or 0)
        self.save_role_state(rid, tongqian=total)
        log.info('conn %d: sold %r (no event bus; skipped)',
                 self.conn_id, src.get('goods_id'))
        frames.append(frame(amf3_encode(
            [str(CMD_BUYBACK_SELL), [1, self.buyback_map(role, entity)]])))
        return tuple(frames) if len(frames) > 1 else frames[0]

    def buyback_huigou(self, msg):
        """Command 32003: GoodsBuyBackServiceImpl.removeGoodsBuyBack.

        C> is the buyback id (the sold bag guid); anything else is silent.
        A missing row answers nothing (Java returns null). The price
        (recycle x count) is checked then paid in YXB: short money replies
        [0, '1003'], no bag room [0, '1006']. Success deletes the row,
        restores the stack with its bind flag, and replies the
        GetGoodsBuyBackOutPut.getData triple [1, id, [record], price].
        """
        args = self.safe(msg, 1, []) or []
        if not args:
            return None
        guid = args[0]
        if not guid or not isinstance(guid, str):
            return None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None or self.config is None:
            return None
        rid = role.get('id')
        try:
            row = self.get_role_buyback(rid, guid)
        except Exception:
            row = None
        if row is None:
            return None
        recycle = self.config.goods_recycle(row.get('goods_id'))
        if recycle is None:
            return frame(amf3_encode(
                [str(CMD_BUYBACK_HUIGOU), [0, BUYBACK_ERR_NO_CONFIG]]))
        try:
            price = recycle * int(row.get('count') or 0)
            balance = int(role.get('tongqian') or 0)
        except (TypeError, ValueError):
            return frame(amf3_encode(
                [str(CMD_BUYBACK_HUIGOU), [0, BUYBACK_ERR_JB_SHORT]]))
        if balance < price:
            return frame(amf3_encode(
                [str(CMD_BUYBACK_HUIGOU), [0, BUYBACK_ERR_JB_SHORT]]))
        if not self._prop_fits(rid, {'goods': row.get('goods_id'),
                                     'count': row.get('count') or 0},
                               row.get('bind') or 0):
            return frame(amf3_encode(
                [str(CMD_BUYBACK_HUIGOU), [0, BUYBACK_ERR_NO_SLOT]]))
        self.delete_role_buyback(rid, guid)
        self._task_grant(rid, [{'goods_id': row.get('goods_id'),
                                'count': row.get('count') or 0,
                                'bind': row.get('bind') or 0,
                                'expire': row.get('expire_time')}])
        self.save_role_state(rid, tongqian=balance - price)
        log.info('conn %d: bought back %r (no event bus; skipped)',
                 self.conn_id, row.get('goods_id'))
        return frame(amf3_encode(
            [str(CMD_BUYBACK_HUIGOU),
             [1, str(guid), [self.buyback_record(role, row)], price]]))

    def buyback_list(self):
        """Command 32004: getGoodsBuyBackAll -> formart1 list or null."""
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        try:
            rows = self.get_role_buyback_all(role.get('id')) or []
        except Exception:
            rows = []
        records = [self.buyback_record(role, row) for row in rows]
        return frame(amf3_encode([str(CMD_BUYBACK_LIST), records or None]))

    def bagdummy_info(self):
        """Command 93002: bagdummyService.getInfo -> [[goodsId, count], ...] or [].

        Java answers an empty Object[] when the role has no dummy rows, never null.
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        try:
            rows = self.get_role_bag_dummy(role.get('id')) or []
        except Exception:
            rows = []
        pairs = [[r['goods_id'], int(r['goods_count'] or 0)] for r in rows]
        return frame(amf3_encode([str(CMD_BAGDUMMY_DUIHUAN), pairs]))

    def gonghui_mall_count(self):
        """Command 32006: getGongHuiMallBuyCount, always null here.

        Java answers null without a RoleMallBangpai row (or with an empty
        mallDate map); the guild mall that writes that row is unmigrated,
        so the row can never exist and the reply stays null.
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        return frame(amf3_encode([str(CMD_GONGHUI_MALL_COUNT), None]))

    def zuwu_info(self):
        """Command 111000: [entries[], wuhunsuipianCount].

        Port of ZuwuServiceImpl.getInfo: owned guardians render their
        rows, the rest mock [id,0,0,0,type] per ZuWuShuxing type, then
        the wuhunsuipian bagdummy count.
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return frame(amf3_encode(['111000', [[], 0]]))
        return self._zuwu_111000_frame(role)

    def _juqing_actor(self, msg):
        """Role for a story-dungeon request, else None."""
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        arg = self.safe(msg, 1, None)
        if isinstance(arg, list):
            arg = self.safe(arg, 0, None)
        role = _find_role(roles, str(arg)) if arg is not None else None
        if role is None and len(roles) == 1:
            role = roles[0]
        return role

    def _juqing_row(self, rid):
        """Story-dungeon entity, defaulted when the role never challenged."""
        row = self.get_role_juqing(rid)
        if row is None:
            return {'passed_highest_id': None, 'passed_ids_daily': None,
                    'auto_pass_info': None, 'best_passed_info': None,
                    'refresh_time': None, 'award_info': None,
                    'tiaozhan_jindu': None, 'pending_award': None}
        row = dict(row)
        row.setdefault('pending_award', None)
        return row

    def _juqing_save(self, rid, row):
        """Persist the story-dungeon entity (skips None columns)."""
        fields = {k: v for k, v in row.items() if v is not None}
        if fields:
            self.save_role_juqing(rid, **fields)

    def _juqing_ensure(self, rid):
        """Load-or-create the entity (checkRoleJuQingFuBenInfo).

        Java inserts a row with only userRoleId + refreshTime on first
        access; every access then runs the daily refresh.
        """
        row = self._juqing_row(rid)
        if self.get_role_juqing(rid) is None:
            row['refresh_time'] = int(self._world_now_ms())
            self._juqing_save(rid, row)
        self._juqing_refresh_daily(rid, row)
        return row

    @staticmethod
    def _day_is_today(stamp_ms, now_ms=None):
        """ObjectUtil.dayIsToday: the stamp falls on the local day."""
        import datetime as _dt
        try:
            stamp = _dt.datetime.fromtimestamp(int(stamp_ms) / 1000).date()
        except (TypeError, ValueError, OverflowError, OSError):
            return False
        base = now_ms / 1000 if now_ms is not None else None
        try:
            today = _dt.datetime.fromtimestamp(
                base if base is not None else _dt.datetime.now().timestamp()
            ).date()
        except (TypeError, ValueError, OverflowError, OSError):
            return False
        return stamp == today

    def _juqing_refresh_daily(self, rid, row):
        """checkPassedIdDailyRefresh: new day clears daily counts."""
        now = int(self._world_now_ms())
        if not self._day_is_today(row.get('refresh_time'), now):
            row['passed_ids_daily'] = ''
            row['refresh_time'] = now
            self._juqing_save(rid, row)

    def _juqing_pending_load(self, row):
        """Staged victory PassAwards, or None (DataContainer replacement).

        Java stages the victory awards in the in-memory DataContainer
        keyed by role; the Python port persists them in role_juqing so a
        claim survives reconnects, which the wire protocol allows.
        """
        import json as _json
        try:
            pending = _json.loads(row.get('pending_award') or '')
        except (TypeError, ValueError):
            return None
        return pending if isinstance(pending, dict) else None

    def _juqing_pending_save(self, rid, row, pending):
        """Stage (or, with None, clear) the victory award."""
        import json as _json
        row['pending_award'] = _json.dumps(pending) if pending else ''
        self._juqing_save(rid, row)

    def _juqing_cfg(self, chapter_id):
        """Chapter config row, or None when unconfigured."""
        if self.config is None:
            return None
        return self.config.juqing_row(chapter_id)

    def _juqing_active(self, row):
        """Active attempt (chapter, startMs, kills, deaths) or None.

        JSON {chapter, start, kills:{}, deaths} written at challenge
        entry; the one pre-JSON 'cid:start|mid=n,...' draft is still
        accepted so half-written rows keep working.
        """
        import json as _json
        raw = row.get('tiaozhan_jindu')
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None
        if isinstance(raw, dict):
            data = raw
        else:
            try:
                data = _json.loads(str(raw))
            except (TypeError, ValueError):
                data = None
            if not isinstance(data, dict) or 'chapter' not in data:
                return self._juqing_active_legacy(str(raw))
        try:
            kills = {str(k): int(v)
                     for k, v in dict(data.get('kills') or {}).items()}
            return {'chapter': str(data['chapter']),
                    'start': int(data.get('start') or 0),
                    'kills': kills,
                    'deaths': int(data.get('deaths') or 0)}
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _juqing_active_legacy(raw):
        """Pre-JSON 'cid:start|mid=n,...' attempt marker, or None."""
        if '|' not in raw:
            return None
        head, _, tail = raw.partition('|')
        try:
            cid, _, start = head.partition(':')
            kills = {}
            for part in tail.split(','):
                if '=' in part:
                    mid, _, num = part.partition('=')
                    kills[mid.strip()] = int(num.strip())
            return {'chapter': str(cid), 'start': int(start),
                    'kills': kills, 'deaths': 0}
        except (TypeError, ValueError):
            return None

    def _juqing_attempt_save(self, rid, row, chapter, start_ms,
                             kills=None, deaths=0):
        """Write the attempt marker and persist."""
        import json as _json
        row['tiaozhan_jindu'] = _json.dumps(
            {'chapter': str(chapter), 'start': int(start_ms),
             'kills': {str(k): int(v) for k, v in (kills or {}).items()},
             'deaths': int(deaths)})
        self._juqing_save(rid, row)

    def _juqing_idle(self, rid, row):
        """Clear the active attempt marker and persist."""
        row['tiaozhan_jindu'] = ''
        self._juqing_save(rid, row)

    def _juqing_offline_sweep(self, rid, row, now_ms=None):
        """offlineAutoFightHandle: negative-useTime guard + settle.

        Returns the [oneKey, curId, remainMs] offline entry when the sweep
        is still running, else None (settled sweeps append one award,
        stamp the daily count and clear the sweep, like finishAutoPass).
        """
        from . import juqing as juqing_lib
        now = int(now_ms if now_ms is not None else self._world_now_ms())
        auto = juqing_lib.decode_auto(row.get('auto_pass_info'))
        if auto is None:
            return None
        if int(auto.get('usetime') or 0) < 0:
            auto['usetime'] = 0
            row['auto_pass_info'] = juqing_lib.encode_auto(
                auto['onekey'], auto['curid'], auto['start'], 0)
            self._juqing_save(rid, row)
        best = juqing_lib.decode_best(row.get('best_passed_info'),
                                      auto['curid'])
        if best is None or best.get('fast') is None:
            # Unreachable with honest data (a sweep needs a best time to
            # start); Java would NPE here, so report no time left without
            # settling the un-settleable sweep.
            return [1 if auto['onekey'] else 0, auto['curid'], 0]
        remain = juqing_lib.sweep_remain_ms(auto, best['fast'], now)
        if remain > 0:
            return [1 if auto['onekey'] else 0, auto['curid'], remain]
        self._juqing_commit_sweep(rid, row, auto, best, now)
        return None

    def _juqing_commit_sweep(self, rid, row, auto, best, now):
        """Shared sweep-settle write (finishAutoPass + offline handle)."""
        from . import juqing as juqing_lib
        row['auto_pass_info'] = ''
        row['award_info'] = juqing_lib.award_incr(
            row.get('award_info'), auto['curid'], best['pingjia'], now)
        row['passed_ids_daily'] = juqing_lib.set_count(
            row.get('passed_ids_daily'), auto['curid'], 2)
        self._juqing_save(rid, row)

    def _juqing_sweep_remaining(self, row, auto, now_ms=None):
        """Millis left on a running sweep, or None without a best time."""
        from . import juqing as juqing_lib
        now = int(now_ms if now_ms is not None else self._world_now_ms())
        best = juqing_lib.decode_best(row.get('best_passed_info'),
                                      auto['curid'])
        if best is None or best.get('fast') is None:
            return None
        return juqing_lib.sweep_remain_ms(auto, best['fast'], now)

    def juqing_info(self):
        """Command 64001: [1, [highest, daily, best, offline]].

        getInfo: entity auto-created, daily refreshed, then
        offlineAutoFightHandle settles an elapsed sweep (or reports the
        running [oneKey, curId, useTime]). Null cells stay null.
        """
        from . import juqing as juqing_lib
        role = self._juqing_actor(['64001', None])
        if role is None:
            return None
        rid = _wire_id(role)
        row = self._juqing_ensure(rid)
        offline = self._juqing_offline_sweep(rid, row)
        if offline is None:
            row = self._juqing_row(rid)
        highest = row.get('passed_highest_id')
        return frame(amf3_encode(['64001', [1, [
            int(highest) if highest is not None else 0,
            juqing_lib.daily_info_rows(row.get('passed_ids_daily')) or None,
            juqing_lib.best_time_rows(row.get('best_passed_info')) or None,
            offline]]]))

    def juqing_award(self):
        """Command 64010: null or [[chapterId, pingjia]] pending awards."""
        from . import juqing as juqing_lib
        role = self._juqing_actor(['64010', None])
        if role is None:
            return None
        row = self._juqing_ensure(_wire_id(role))
        rows = juqing_lib.award_info_shapes(row.get('award_info'))
        if not rows:
            return frame(amf3_encode(['64010', None]))
        return frame(amf3_encode(['64010', rows]))

    def juqing_challenge(self, msg):
        """Command 64002 [chapterId]: gates, dungeon entry, [1, id]/[0, code]."""
        from . import juqing as juqing_lib
        args = self.safe(msg, 1, [])
        try:
            cid = int(self.safe(args, 0, 0) if isinstance(args, list)
                      else args)
        except (TypeError, ValueError):
            cid = 0
        role = self._juqing_actor(msg)
        if role is None:
            return None
        rid = _wire_id(role)
        # Java refreshes (creating) the entity before loading config.
        row = self._juqing_ensure(rid)
        cfg = self._juqing_cfg(cid)
        if cfg is None:
            return frame(amf3_encode(
                ['64002', [0, juqing_lib.ERR_NOT_EXIST]]))
        active = self._juqing_active(row)
        err = juqing_lib.check_can_challenge(
            cfg, role.get('level'), row.get('passed_highest_id'),
            row.get('passed_ids_daily'), active is not None)
        if err is not None:
            return frame(amf3_encode(['64002', [0, err]]))
        pos = cfg.get('pos') or []
        frames = list(self.change_map(
            rid, str(cfg.get('map') or role.get('map_id')),
            int(pos[0]) if len(pos) > 0 else int(role.get('map_x') or 0),
            int(pos[1]) if len(pos) > 1 else int(role.get('map_y') or 0)))
        now = int(self._world_now_ms())
        row['passed_ids_daily'] = juqing_lib.set_count(
            row.get('passed_ids_daily'), cid, 1)
        row['refresh_time'] = now
        self._juqing_attempt_save(rid, row, cid, now)
        try:
            self.stage_scheduler.cancel(f'juqing_expire:{rid}')
        except (AttributeError, KeyError, ValueError):
            pass
        self.schedule_stage(f'juqing_expire:{rid}', '64008',
                            lambda: self._juqing_expire(rid),
                            delay=max(int(cfg.get('expire_min') or 0) * 60,
                                      1),
                            unit='SECONDS')
        # getRestTime: raw expireDelay minus elapsed (may go negative).
        rest = int(cfg.get('expire_ms') or 0) - \
            (int(self._world_now_ms()) - now)
        frames.append(frame(amf3_encode(
            ['64009', [rest, str(cfg.get('map') or ''), int(cid), []]])))
        frames.append(frame(amf3_encode(['64002', [1, cid]])))
        return tuple(frames)

    def _juqing_expire(self, rid):
        """Forced-leave timer: an unfinished attempt expires (COPY_EXPIRE3).

        Ports StageJuQingCopyServiceImpl.expireCheck: the copy ends with
        COPY_EXPIRE3, challengeResult answers [1, chapter, 3] for the
        64003 push, and the role is sent home with 64008 [1]. Home-map
        routing lives in stagecontroll (unported), so the role keeps its
        current map while the attempt state clears.
        """
        from . import juqing as juqing_lib
        try:
            roles = self.get_roles(self.authed_user or '',
                                   self.server_id or '')
        except Exception:
            return None
        role = roles[0] if roles else None
        if role is None or str(_wire_id(role)) != str(rid):
            return None
        row = self._juqing_row(rid)
        active = self._juqing_active(row)
        if active is None:
            return None
        self._juqing_idle(rid, row)
        try:
            self.stage_scheduler.cancel(f'juqing_expire:{rid}')
        except (AttributeError, KeyError, ValueError):
            pass
        return (frame(amf3_encode(
            ['64003', [1, int(active['chapter']),
                       juqing_lib.COPY_EXPIRE3]])),
            frame(amf3_encode(['64008', [1]])))

    def juqing_saodang(self, msg):
        """Command 64004 [chapterId, oneKey]: start a sweep, [1, id, key, ms]."""
        from . import juqing as juqing_lib
        args = self.safe(msg, 1, [])
        cid, onekey = 0, False
        if isinstance(args, list) and args:
            try:
                cid = int(args[0])
            except (TypeError, ValueError):
                cid = 0
            onekey = bool(args[1]) if len(args) > 1 else False
        role = self._juqing_actor(msg)
        if role is None:
            return None
        rid = _wire_id(role)
        cfg = self._juqing_cfg(cid)
        row = self._juqing_ensure(rid)
        auto = juqing_lib.decode_auto(row.get('auto_pass_info'))
        best = juqing_lib.decode_best(row.get('best_passed_info'), cid)
        try:
            vip = self.get_role_vip(role.get('id')) or {}
        except Exception:
            vip = {}
        err = juqing_lib.check_can_saodang(
            cfg, auto, best, row.get('passed_ids_daily'), onekey,
            vip.get('vip_level'))
        if err is not None:
            return frame(amf3_encode(['64004', [0, err]]))
        now = int(self._world_now_ms())
        row['auto_pass_info'] = juqing_lib.encode_auto(onekey, cid, now)
        self._juqing_save(rid, row)
        return frame(amf3_encode(
            ['64004', [1, cid, bool(onekey), best['fast']]]))

    def juqing_finish(self, msg):
        """Command 64006: collect a finished sweep, else [-1, id, remain]."""
        from . import juqing as juqing_lib
        role = self._juqing_actor(msg)
        if role is None:
            return None
        rid = _wire_id(role)
        row = self._juqing_ensure(rid)
        auto = juqing_lib.decode_auto(row.get('auto_pass_info'))
        if auto is None or auto.get('curid') is None:
            return frame(amf3_encode(
                ['64006', [0, juqing_lib.ERR_NO_AUTOPASS]]))
        best = juqing_lib.decode_best(row.get('best_passed_info'),
                                      auto['curid'])
        if best is None or best.get('fast') is None:
            return frame(amf3_encode(
                ['64006', [0, juqing_lib.ERR_NO_AUTOPASS]]))
        remain = juqing_lib.sweep_remain_ms(
            auto, best['fast'], int(self._world_now_ms()))
        if remain > 0:
            return frame(amf3_encode(
                ['64006', [-1, auto['curid'], remain]]))
        now = int(self._world_now_ms())
        self._juqing_commit_sweep(rid, row, auto, best, now)
        return frame(amf3_encode(
            ['64006', [1, auto['curid'], bool(auto['onekey'])]], ))

    def juqing_accelerate(self, msg):
        """Command 64007: spend YB to finish a sweep now, [1, id]."""
        from . import juqing as juqing_lib
        role = self._juqing_actor(msg)
        if role is None:
            return None
        rid = _wire_id(role)
        row = self._juqing_ensure(rid)
        auto = juqing_lib.decode_auto(row.get('auto_pass_info'))
        if auto is None or auto.get('curid') is None:
            return frame(amf3_encode(
                ['64007', [0, juqing_lib.ERR_NO_AUTOPASS]]))
        cfg = self._juqing_cfg(auto['curid'])
        if cfg is None:
            return frame(amf3_encode(
                ['64007', [0, juqing_lib.ERR_NOT_EXIST]]))
        cost = int(cfg.get('accel_yb') or 0)
        if not self._juqing_spend_yb(role, cost):
            return frame(amf3_encode(
                ['64007', [0, juqing_lib.ERR_YB_LESS]]))
        now = int(self._world_now_ms())
        best = juqing_lib.decode_best(row.get('best_passed_info'),
                                      auto['curid']) or {}
        self._juqing_commit_sweep(
            rid, row, auto,
            {'pingjia': int(best.get('pingjia') or 4)},
            now)
        return frame(amf3_encode(['64007', [1, auto['curid'], cost]]))

    def _juqing_spend_yb(self, role, cost):
        """accelerateAutoChallenge decrCheck/decr on YB (lingqu path).

        Ports the account decrCheck(YB) gate: short balance answers
        YB_LESS(1002) without touching the sweep; success deducts.
        """
        try:
            balance = int(role.get('lingshi') or 0)
        except (TypeError, ValueError):
            return False
        if balance < int(cost or 0):
            return False
        self.save_role_state(role.get('id'), lingshi=balance - int(cost or 0))
        return True

    def _juqing_goods_table(self):
        """Goods rows for ItemModel conversion, or {} when unavailable."""
        try:
            table = self.config._goods_table() \
                if self.config is not None else {}
        except Exception:
            return {}
        return dict(table or {})

    def _juqing_zubao_table(self):
        """ZuBao drop-group rows, or {} when unavailable."""
        try:
            table = self.config.zubao_table() \
                if self.config is not None else {}
        except Exception:
            return {}
        return dict(table or {})

    def _juqing_pass_awards(self, role, chapter_id, pingjia):
        """passAwards: currency math + fixed params + roll candidates.

        Returns {'exp','yxb','zhenqi','fixed':[[gid,count,bind]],
        'candidates':[(ItemModel, rate)]}. Fixed entries keep their cell
        bind; every roll candidate carries the chapter rollBind with
        ItemModel.setId following group order, like rollItems.
        """
        from . import juqing as juqing_lib
        cfg = self._juqing_cfg(chapter_id) or {}
        factor = float((cfg.get('award_odds') or {}).get(int(pingjia), 1.0))
        awards = juqing_lib.pass_awards(cfg, role.get('level'), factor)
        fixed = [[g[0], int(g[1]), int(g[2]) if len(g) > 2 else 0]
                 for g in cfg.get('fixed_goods') or []]
        candidates = juqing_lib.roll_candidates(
            self._juqing_goods_table(), self._juqing_zubao_table(),
            cfg.get('drop_id'), cfg.get('equip_fujia') or {},
            int(cfg.get('roll_bind') or 0))
        return {'exp': awards['exp'], 'yxb': awards['yxb'],
                'zhenqi': awards['zhenqi'], 'fixed': fixed,
                'candidates': candidates}

    def _juqing_grant_currencies(self, role, exp, yxb, zhenqi):
        """incrExp/incr(YXB)/incrZhenqi; answers (exp, yxb, zq, extra).

        Exp flows through the shared level-up path (12001 notice plus
        any level-up refreshes in extra). The Java incr calls report the
        real (cap-clipped) increments; no cap table is ported, so the
        full computed amounts persist, like every other Python grant.
        """
        rid = role.get('id')
        try:
            exp_i = int(exp or 0)
        except (TypeError, ValueError):
            exp_i = 0
        extra = []
        if exp_i:
            _total, _level, _gained, exp_frames = \
                self._role_gain_exp(role, rid, exp_i)
            extra.extend(exp_frames[1:])
        else:
            try:
                role.update(exp=int(role.get('exp') or 0))
            except (TypeError, ValueError):
                pass
        total_zq = int(role.get('zhenqi') or 0) + int(zhenqi or 0)
        total_yxb = int(role.get('tongqian') or 0) + int(yxb or 0)
        self.save_role_state(rid, zhenqi=total_zq, tongqian=total_yxb)
        try:
            role.update(zhenqi=total_zq, tongqian=total_yxb)
        except Exception:
            pass
        return int(exp or 0), int(yxb or 0), int(zhenqi or 0), extra

    def _juqing_grant_goods(self, role, rid, fixed, models):
        """putInBagOrEmail1: stack into the bag, mail the overflow.

        Fixed params convert through the goods table (unknown goods are
        skipped like Java's null convert2ItemModel). Overflow goes to
        mail with the juqing subject instead of dropping. Returns the
        formart maps in grant order.
        """
        from . import juqing as juqing_lib
        goods_table = self._juqing_goods_table()
        items = []
        for entry in fixed:
            gid, count = entry[0], entry[1]
            bind = int(entry[2]) if len(entry) > 2 else 0
            items.extend(juqing_lib.convert_item(
                goods_table.get(str(gid)), gid, count, bind=bind))
        items.extend(models or [])
        try:
            slots = self.get_role_bag_slots(rid, -1000000, 1000000) or []
        except Exception:
            slots = []
        by_slot = {s.get('slot_num'): dict(s) for s in slots}
        try:
            state = self._bag_state_or_init(rid) or {}
            capacity = int(state.get('bag_capacity') or 0)
        except (TypeError, ValueError):
            capacity = 0
        formarts = []
        for item in items:
            left = int(item.get('count') or 0)
            if left <= 0 or not item.get('goods_id'):
                continue
            try:
                stack = int(self.config.goods_max_stack(
                    item['goods_id']) or 0) if self.config is not None else 0
            except (TypeError, ValueError):
                stack = 0
            if stack <= 0:
                stack = 1
            placed_rows = []
            for slot in sorted(by_slot.values(),
                               key=lambda s: s.get('slot_num') or 0):
                if left <= 0:
                    break
                if not self._bag_same_kind(slot, item):
                    continue
                try:
                    have = int(slot.get('count') or 0)
                except (TypeError, ValueError):
                    have = 0
                room = stack - have
                if room <= 0:
                    continue
                take = min(room, left)
                try:
                    self.update_role_bag_slot(rid, slot.get('slot_num'),
                                            count=have + take)
                except Exception:
                    continue
                slot['count'] = have + take
                left -= take
                placed_rows.append(slot)
            num = 1
            while left > 0 and num <= capacity:
                if num not in by_slot:
                    take = min(stack, left)
                    row = {'slot_num': num,
                           'goods_id': str(item['goods_id']),
                           'count': take,
                           'bind': int(item.get('bind') or 0),
                           'expire_time': int(item.get('expire_time') or 0)
                           or None,
                           'rare_level': int(item.get('rare_level') or 0),
                           'item_level': int(item.get('item_level') or 0),
                           'attributes': None}
                    try:
                        bag_id = self.insert_role_bag_slot(rid, dict(row))
                    except Exception:
                        break
                    if not bag_id:
                        break
                    row = dict(row, bag_id=bag_id)
                    by_slot[num] = row
                    left -= take
                    placed_rows.append(row)
                num += 1
            for prow in placed_rows:
                try:
                    formarts.append(self.bag_goods_map(role, prow))
                except Exception:
                    pass
            if left > 0:
                try:
                    self.save_role_email(
                        str(rid), title=juqing_lib.JUQING_SUBJECT,
                        content=juqing_lib.JUQING_SUBJECT,
                        attachment=f"{item.get('goods_id')}:{left}:"
                                   f"{int(item.get('bind') or 0)}")
                except Exception:
                    log.warning('conn %d: juqing reward %r x%d '
                                'overflows (unmailable)',
                                self.conn_id, item.get('goods_id'), left)
        return formarts

    def _juqing_claim_models(self, pending, cfg):
        """Rebuild the staged roll candidates and draw the granted one.

        Mirrors the claim-time Lottery.getRandomKey2 over the staged
        modelMap: candidates persist as [goodsId, count, rate] so the
        draw repeats Java's weights without new table rolls.
        """
        from . import juqing as juqing_lib
        goods_table = self._juqing_goods_table()
        roll_bind = int(cfg.get('roll_bind') or 0)
        candidates = []
        for idx, entry in enumerate(pending.get('candidates') or []):
            try:
                gid, count, rate = entry[0], int(entry[1]), float(entry[2])
            except (TypeError, ValueError, IndexError):
                continue
            models = juqing_lib.convert_item(
                goods_table.get(str(gid)), gid, count, bind=roll_bind,
                first_only=True)
            if not models:
                continue
            models[0]['id'] = str(idx)
            candidates.append((models[0], rate))
        picked = juqing_lib.roll_pick(candidates)
        return [picked] if picked is not None else []

    def juqing_lingqu(self, msg):
        """Command 64012: claim the staged manual-victory award.

        lingquAward: the DataContainer-staged PassAwards (persisted here
        in role_juqing) grant currencies plus fixed goods and one fresh
        Zubao roll; the reply is lingJiangSuccessResult [1, exp, yxb,
        zhenqi, fixedPairs, rollFormart].
        """
        from . import juqing as juqing_lib
        role = self._juqing_actor(msg)
        if role is None:
            return None
        rid = _wire_id(role)
        row = self._juqing_ensure(rid)
        pending = self._juqing_pending_load(row)
        if pending is None:
            return frame(amf3_encode(
                ['64012', [0, juqing_lib.ERR_NO_AWARD]]))
        try:
            chapter = int(pending['chapter'])
            pingjia = int(pending.get('pingjia') or 4)
        except (TypeError, ValueError):
            return frame(amf3_encode(
                ['64012', [0, juqing_lib.ERR_NO_AWARD]]))
        staged = pending.get('awards') or {}
        fixed = [[g[0], int(g[1]), int(g[2]) if len(g) > 2 else 0]
                 for g in pending.get('fixed') or []]
        # Java removeData runs before any grant: a crash loses the
        # award instead of duplicating it, and a second claim finds
        # nothing (NO_AWARD).
        self._juqing_pending_save(rid, row, None)
        got_exp, got_yxb, got_zq, extra = \
            self._juqing_grant_currencies(
                role, staged.get('exp'), staged.get('yxb'),
                staged.get('zhenqi'))
        self._juqing_grant_goods(role, rid, fixed, [])
        cfg = self._juqing_cfg(chapter) or {}
        models = self._juqing_claim_models(pending, cfg)
        roll_formarts = self._juqing_grant_goods(role, rid, [], models)
        pairs = [[g[0], int(g[1])] for g in fixed]
        reply = frame(amf3_encode(['64012', [
            1, got_exp, got_yxb, got_zq, pairs,
            roll_formarts[0] if roll_formarts else None]]))
        return (reply, *extra) if extra else reply

    def juqing_onekey(self, msg):
        """Command 64013: claim every pending sweep award.

        oneKeyLingquAward: per award-entry passAwards grants currencies
        immediately while fixed goods and one fresh roll per entry join a
        single putInBagOrEmail1; the reply is [exp, yxb, zhenqi,
        [formart...]] with no leading 1.
        """
        from . import juqing as juqing_lib
        role = self._juqing_actor(msg)
        if role is None:
            return None
        rid = _wire_id(role)
        row = self._juqing_ensure(rid)
        entries = juqing_lib.award_entries(row.get('award_info'))
        if not entries:
            return frame(amf3_encode(
                ['64013', [0, juqing_lib.ERR_NO_AWARD]]))
        total_exp = total_yxb = total_zq = 0
        fixed_all = []
        models_all = []
        level_extra = []
        for _idx, cid, pingjia, _ms in entries:
            # Java skips award rows whose chapter config is gone.
            if self._juqing_cfg(cid) is None:
                continue
            computed = self._juqing_pass_awards(role, cid, pingjia)
            got_exp, got_yxb, got_zq, extra = \
                self._juqing_grant_currencies(
                    role, computed['exp'], computed['yxb'],
                    computed['zhenqi'])
            total_exp += got_exp
            total_yxb += got_yxb
            total_zq += got_zq
            level_extra.extend(extra)
            fixed_all.extend(computed['fixed'])
            # One fresh Lottery draw per award entry, like oneKey's
            # per-entry passAwards + getRandomKey2 (not all candidates).
            picked = juqing_lib.roll_pick(computed['candidates'])
            if picked is not None:
                models_all.append(picked)
        formarts = self._juqing_grant_goods(role, rid, fixed_all,
                                            models_all)
        row['award_info'] = ''
        self._juqing_save(rid, row)
        reply = frame(amf3_encode(
            ['64013', [total_exp, total_yxb, total_zq, formarts]]))
        return (reply, *level_extra) if level_extra else reply

    def _juqing_on_enter(self, rid):
        """handleLogin: a running sweep restarts its clock at login."""
        from . import juqing as juqing_lib
        row = self._juqing_row(rid)
        if row is None:
            return
        auto = juqing_lib.decode_auto(row.get('auto_pass_info'))
        if auto is None or auto.get('curid') is None:
            return
        row['auto_pass_info'] = juqing_lib.encode_auto(
            auto['onekey'], auto['curid'], int(self._world_now_ms()),
            auto.get('usetime') or 0)
        self._juqing_save(rid, row)

    def _juqing_on_disconnect(self):
        """handleLogout: freeze a running sweep clock at logout.

        useTime accumulates the session's elapsed millis so offline
        time never counts toward the sweep.
        """
        from . import juqing as juqing_lib
        try:
            roles = self.get_roles(self.authed_user or '',
                                   self.server_id or '')
        except Exception:
            return
        now = int(self._world_now_ms())
        for role in roles or []:
            try:
                rid = _wire_id(role)
            except Exception:
                continue
            row = self._juqing_row(rid)
            if row is None:
                continue
            auto = juqing_lib.decode_auto(row.get('auto_pass_info'))
            if auto is None or auto.get('curid') is None:
                continue
            try:
                use = int(auto.get('usetime') or 0) + \
                    max(now - int(auto.get('start') or 0), 0)
            except (TypeError, ValueError):
                continue
            row['auto_pass_info'] = juqing_lib.encode_auto(
                auto['onekey'], auto['curid'], now, use)
            self._juqing_save(rid, row)

    def _juqing_kill_frames(self, actor, dead_monster):
        """Juqing kill fan-out for one dead monster (role/pet killers)."""
        killer_role = None
        try:
            if actor.get('kind') == 'role':
                killer_role = actor.get('role')
            elif actor.get('kind') == 'pet':
                roles = self.get_roles(self.authed_user or '',
                                       self.server_id or '')
                killer_role = _find_role(roles, actor.get('owner'))
        except Exception:
            killer_role = None
        if killer_role is None:
            return []
        tpl = dead_monster.get('template') or {}
        try:
            return self._juqing_kill_progress(killer_role, tpl.get('id'))
        except Exception:
            return []

    def _juqing_kill_progress(self, owner_role, monster_tpl_id):
        """JuqingStageCopy.killMonster for shared-world dungeon kills.

        When the killer's role has an active attempt and the template is
        wanted, the kill count bumps (no wire push, like Java); reaching
        the wanted total ends the copy: challengeResult(ROLE_WIN)
        persists highest/daily/best, stages the PassAwards for 64012
        and pushes the 64003 challengeSuccessResult.
        """
        from . import juqing as juqing_lib
        try:
            rid = _wire_id(owner_role)
        except Exception:
            return []
        row = self._juqing_row(rid)
        if row is None:
            return []
        active = self._juqing_active(row)
        if active is None:
            return []
        cfg = self._juqing_cfg(active['chapter'])
        if cfg is None:
            return []
        wanted = {str(mid): int(n) for mid, n in cfg.get('complete') or []}
        mid = str(monster_tpl_id)
        if mid not in wanted:
            return []
        kills = dict(active['kills'])
        kills[mid] = int(kills.get(mid, 0)) + 1
        self._juqing_attempt_save(rid, row, active['chapter'],
                                  active['start'], kills, active['deaths'])
        # Java sends no per-kill push (killMap only rides the 64009
        # enter state); victory is total kills >= total wanted, like
        # getWantedListComplete (killCount >= monsterCount).
        if sum(kills.values()) < sum(wanted.values()):
            return []
        return self._juqing_victory(owner_role, rid, row, active, cfg)

    def _juqing_victory(self, role, rid, row, active, cfg):
        """challengeResult(roleId, chapter, ROLE_WIN, costMs, deadTimes).

        Highest/daily/best persist, the PassAwards stage into pending
        for 64012, and the client gets the 64003 challengeSuccessResult
        [1, chapter, roleId, exp, yxb, zhenqi, fixedPairs, rollFormarts,
        useTimeMs, deadTimes]. JuQingFuBenFinishEvent/huoYuedu have no
        ported subscribers and are skipped like other event publishes.
        """
        from . import juqing as juqing_lib
        now = int(self._world_now_ms())
        use_ms = max(now - active['start'], 0)
        pingjia = juqing_lib.victory_pingjia(
            use_ms, cfg.get('pingjia') or [], active['deaths'])
        highest = row.get('passed_highest_id')
        if highest is None or int(highest) < int(active['chapter']):
            row['passed_highest_id'] = int(active['chapter'])
        row['passed_ids_daily'] = juqing_lib.set_count(
            row.get('passed_ids_daily'), active['chapter'], 2)
        row['best_passed_info'] = juqing_lib.merge_best(
            row.get('best_passed_info'), active['chapter'], use_ms,
            pingjia)
        computed = self._juqing_pass_awards(
            role, active['chapter'], pingjia)
        staged = [[m['goods_id'], m['count'], rate]
                  for m, rate in computed['candidates']]
        self._juqing_pending_save(rid, row, {
            'chapter': int(active['chapter']), 'pingjia': pingjia,
            'use_time': use_ms, 'dead': active['deaths'],
            'awards': {'exp': computed['exp'], 'yxb': computed['yxb'],
                       'zhenqi': computed['zhenqi']},
            'fixed': computed['fixed'], 'candidates': staged})
        self._juqing_idle(rid, row)
        try:
            self.stage_scheduler.cancel(f'juqing_expire:{rid}')
        except (AttributeError, KeyError, ValueError):
            pass
        # rollGoods: formart of every candidate, not just the granted
        # one (Java challengeSuccessResult element 7).
        pairs = [[g[0], int(g[1])] for g in computed['fixed']]
        if computed['candidates']:
            roll_formarts = []
            try:
                for model, _rate in computed['candidates']:
                    roll_formarts.append(self.bag_goods_map(
                        role, dict(model, slot_num=0,
                                  bag_id=model.get('id'))))
            except Exception:
                roll_formarts = []
        else:
            roll_formarts = None
        return [frame(amf3_encode(
            ['64003', [1, int(active['chapter']), str(rid),
                       computed['exp'], computed['yxb'],
                       computed['zhenqi'], pairs,
                       roll_formarts, use_ms, active['deaths']]]))]

    def _juqing_death_progress(self, owner_role):
        """JuqingStageCopy.incrDeadTimes: a death during an attempt counts."""
        try:
            rid = _wire_id(owner_role)
        except Exception:
            return
        row = self._juqing_row(rid)
        if row is None:
            return
        active = self._juqing_active(row)
        if active is None:
            return
        self._juqing_attempt_save(rid, row, active['chapter'],
                                  active['start'], active['kills'],
                                  active['deaths'] + 1)

    def zuwufuben_info(self):
        """Command 108001: [1, [passMax, everyday[], saodangOrNull]].

        ZuwufubenServiceImpl.getInfo: load-or-create the row, run the
        daily refresh, settle an elapsed sweep (the schedule's
        saoDangFinish work, so an offline sweep never blocks the list),
        then answer passMax, the [[idStr, used, total]] rows in stored
        order, and [sdId, endMs, autoPass] or null.
        """
        from . import zuwu as zuwu_lib
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        rid = _wire_id(role)
        row = self._zuwu_ensure(rid)
        self._zuwu_settle(rid, row)
        row = self._zuwu_row(rid)
        everyday = zuwu_lib.parse_counts(row.get('everyday_pass_data'))
        buy = zuwu_lib.parse_counts(row.get('buy_count_data'))
        vo = zuwu_lib.decode_sao(row.get('saodang_data'))
        sao = None
        if zuwu_lib.is_sweeping(vo):
            sao = [vo['sdid'], zuwu_lib.sweep_end_ms(vo),
                   bool(vo['autopass'])]
        try:
            pass_max = int(row.get('pass_max_id') or 0)
        except (TypeError, ValueError):
            pass_max = 0
        return frame(amf3_encode(
            ['108001', [1, [pass_max, zuwu_lib.info_rows(everyday, buy),
                           sao]]]))

    def _zuwu_cfg(self, dungeon_id):
        """Normalized clan-dungeon row, or None when unconfigured."""
        try:
            return self.config.zuwu_fuben_row(int(dungeon_id)) \
                if self.config is not None else None
        except (TypeError, ValueError):
            return None

    def _zuwu_row(self, rid):
        """Clan-dungeon entity, defaulted when the role never entered."""
        row = self.get_role_zuwufuben(rid)
        if row is None:
            return {'pass_max_id': None, 'everyday_pass_data': None,
                    'everyday_time': None, 'buy_count_data': None,
                    'saodang_data': None}
        return dict(row)

    def _zuwu_save(self, rid, row):
        """Persist the clan-dungeon entity (skips None columns)."""
        fields = {k: v for k, v in row.items() if v is not None}
        if fields:
            self.save_role_zuwufuben(rid, **fields)

    def _zuwu_ensure(self, rid):
        """Load-or-create the entity (online() for a missing row).

        A fresh row clears dungeon 1 (everyday {"1": 1}, bought
        {"1": 0}), like the Java insert; every access then runs the
        daily refresh.
        """
        from . import zuwu as zuwu_lib
        row = self._zuwu_row(rid)
        if self.get_role_zuwufuben(rid) is None:
            now = int(self._world_now_ms())
            row['pass_max_id'] = 0
            row['everyday_pass_data'] = zuwu_lib.format_counts({1: 1})
            row['everyday_time'] = now
            row['buy_count_data'] = zuwu_lib.format_counts({1: 0})
            row['saodang_data'] = zuwu_lib.encode_sao(None, 0, 0)
            self._zuwu_save(rid, row)
        self._zuwu_refresh_daily(rid, row)
        return row

    def _zuwu_refresh_daily(self, rid, row):
        """refresh(): new day re-arms 1..passMax+1 and clears the sweep."""
        from . import zuwu as zuwu_lib
        if self._day_is_today(row.get('everyday_time'),
                              int(self._world_now_ms())):
            return row
        try:
            top = int(row.get('pass_max_id') or 0) + 1
        except (TypeError, ValueError):
            top = 1
        row['everyday_pass_data'] = zuwu_lib.format_counts(
            {i: 1 for i in range(1, max(top, 1) + 1)})
        row['buy_count_data'] = zuwu_lib.format_counts(
            {i: 0 for i in range(1, max(top, 1) + 1)})
        row['saodang_data'] = zuwu_lib.encode_sao(None, 0, 0)
        row['everyday_time'] = int(self._world_now_ms())
        self._zuwu_save(rid, row)
        return row

    def _zuwu_vip_level(self, role):
        """RoleVipExportService.getRoleVipLevel (0 when unmigrated)."""
        try:
            vip = self.get_role_vip(role.get('id')) or {}
        except Exception:
            return 0
        try:
            return int(vip.get('vip_level') or 0)
        except (TypeError, ValueError):
            return 0

    def _zuwu_spend_yb(self, role, cost):
        """account decrCheck/decr on YB (role lingshi); False when short."""
        try:
            balance = int(role.get('lingshi') or 0)
        except (TypeError, ValueError):
            return False
        if balance < int(cost or 0):
            return False
        self.save_role_state(role.get('id'),
                             lingshi=balance - int(cost or 0))
        return True

    def _zuwu_formart_model(self, role_id, model):
        """One StoreGoodsOutput.formart2 record for a granted ItemModel.

        Same 18 slots as bag_goods_map, sourced from the model (no bag
        slot): id is the model id, slotNum 0, userRoleId the role.
        """
        try:
            count = int(model.get('count') or 0)
        except (TypeError, ValueError):
            count = 0
        try:
            ilevel = int(model.get('item_level') or 0)
        except (TypeError, ValueError):
            ilevel = 0
        try:
            rare = int(model.get('rare_level') or 0)
        except (TypeError, ValueError):
            rare = 0
        return {
            '0': str(model.get('goods_id')), '1': model.get('id'),
            '2': 0, '3': count, '4': str(role_id), '5': ilevel,
            '6': rare, '7': int(model.get('bind') or 0),
            '8': int(model.get('expire_time') or 0), '9': None,
            '10': 0, '11': None, '12': 0, '13': '', '14': None,
            '15': 0, '16': 0, '17': 0}

    def _zuwu_grant_models(self, role, models):
        """finishReward item routing + formart2 records.

        xuni goods go to the bag dummy (addGoods), real goods stack into
        the bag with mail overflow; every converted model is formatted,
        like StoreGoodsOutput.formart2(models, roleId).
        """
        from . import juqing as juqing_lib
        goods_table = self._juqing_goods_table()
        items = []
        for entry in models:
            gid = entry[0]
            try:
                count = int(entry[1])
            except (TypeError, ValueError):
                continue
            items.extend(juqing_lib.convert_item(
                goods_table.get(str(gid)), gid, count, bind=0))
        rid = _wire_id(role)
        formarts = []
        for item in items:
            gid = str(item.get('goods_id') or '')
            if not gid:
                continue
            if self.config is not None and self.config.goods_is_xuni(gid):
                try:
                    self.add_role_bag_dummy(rid, gid,
                                          int(item.get('count') or 0))
                except Exception:
                    log.warning('conn %d: zuwu dummy grant %r failed',
                                self.conn_id, gid, exc_info=True)
            else:
                try:
                    self._juqing_grant_goods(role, rid, [], [item])
                except Exception:
                    log.warning('conn %d: zuwu bag grant %r failed',
                                self.conn_id, gid, exc_info=True)
            formarts.append(self._zuwu_formart_model(rid, item))
        return formarts

    def _zuwu_roll_models(self, cfg):
        """finishReward drop list: fixed gditem + one zubao1 lottery win."""
        from . import juqing as juqing_lib
        from . import zuwu as zuwu_lib
        fixed = [list(g) for g in cfg.get('fixed_goods') or []]
        if cfg.get('zubao1') and \
                zuwu_lib.lottery_open(cfg.get('jilv1')):
            goods_table = self._juqing_goods_table()
            zubao = self.config.zubao_table() \
                if self.config is not None else {}
            cands = juqing_lib.roll_candidates(
                goods_table, zubao, cfg['zubao1'], 0)
            pick = juqing_lib.roll_pick(cands)
            if pick is not None:
                fixed.append([pick['goods_id'], pick.get('count', 1), 0])
        return fixed

    def _zuwu_jihuo(self, role, wuhunid):
        """roleZuwuExportService.jihuoZuwu: activate the guardian once.

        Creates the level-1 RoleZuwu row (jieshu from ZuWuShuxing) and
        pushes the refreshed 111000 list; already-owned guardians stay
        untouched. Returns the push frames, or [] without a wuhun id.
        """
        if not wuhunid:
            return []
        rid = _wire_id(role)
        try:
            if self.get_role_zuwu(rid, wuhunid) is not None:
                return []
        except Exception:
            return []
        jieshu = 0
        try:
            shu = self.config.zuwu_shuxing_table().get(str(wuhunid)) \
                if self.config is not None else None
            jieshu = int((shu or {}).get('jieshu') or 0)
        except (TypeError, ValueError):
            jieshu = 0
        try:
            self.save_role_zuwu(rid, wuhunid, level=1, exp=0,
                               jieshu=jieshu, fail_count=0)
        except Exception:
            log.warning('conn %d: zuwu jihuo %r failed', self.conn_id,
                        wuhunid, exc_info=True)
            return []
        return [self._zuwu_111000_frame(role)]

    def _zuwu_111000_frame(self, role):
        """Current 111000 body: owned entries plus the fragment count."""
        entries = []
        kinds = {}
        try:
            kinds = dict(self.config.zuwu_table()) \
                if self.config is not None else {}
        except Exception:
            kinds = {}
        owned = {}
        try:
            for row in self.list_role_zuwu(_wire_id(role)) or []:
                owned[str(row.get('zuwu_id'))] = row
        except Exception:
            owned = {}
        try:
            dummy = self.get_role_bag_dummy(_wire_id(role)) or []
        except Exception:
            dummy = []
        frag = 0
        for entry in dummy:
            try:
                if str(entry.get('goods_id')) == 'wuhunsuipian':
                    frag += int(entry.get('goods_count') or 0)
            except (TypeError, ValueError):
                continue
        seen = set()
        for zid, data in owned.items():
            try:
                level = int(data.get('level') or 0)
            except (TypeError, ValueError):
                level = 0
            entries.append([zid, level, 0, 0, 0])
            seen.add(zid)
        for kind, zid in sorted(kinds.items()):
            if zid not in seen:
                entries.append([zid, 0, 0, 0, kind])
        return frame(amf3_encode(['111000', [entries, frag]]))

    def zuwu_enter(self, msg):
        """Command 108002 [dungeonId]: gates, dungeon entry, [1, id].

        enterFuBen: unknown config answers nothing; the checked() gates
        come first (in-copy 114008, sweeping 114003, level 1000,
        locked 114001, no attempts 114002). Entry queues the
        SC:APPLY_COPY equivalent (shared-world change_map + the 108007
        [id, restMs] enter push), marks center, and replies [1, id].
        """
        from . import zuwu as zuwu_lib
        args = self.safe(msg, 1, [])
        try:
            did = int(args[0]) if isinstance(args, list) else int(args)
        except (TypeError, ValueError):
            did = 0
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        rid = _wire_id(role)
        row = self._zuwu_ensure(rid)
        cfg = self._zuwu_cfg(did)
        if cfg is None:
            return None
        everyday = zuwu_lib.parse_counts(row.get('everyday_pass_data'))
        vo = zuwu_lib.decode_sao(row.get('saodang_data'))
        try:
            pass_max = int(row.get('pass_max_id') or 0)
        except (TypeError, ValueError):
            pass_max = 0
        err = zuwu_lib.check_enter(
            vo.get('center') if vo else False,
            zuwu_lib.is_sweeping(vo), role.get('level'), cfg['level'],
            did, pass_max, everyday)
        if err is not None:
            return frame(amf3_encode(['108002', [0, err]]))
        pos = cfg.get('pos') or []
        frames = list(self.change_map(
            rid, str(cfg.get('map') or role.get('map_id')),
            int(pos[0]) if len(pos) > 0 else int(role.get('map_x') or 0),
            int(pos[1]) if len(pos) > 1 else int(role.get('map_y') or 0)))
        now = int(self._world_now_ms())
        rest_ms = max(int(cfg.get('expire_min') or 0) * 60000, 1)
        self._zuwu_attempt[rid] = {'dungeon': int(did), 'kills': {}}
        row['saodang_data'] = zuwu_lib.encode_sao(
            vo.get('sdid') if vo else None,
            vo.get('start') if vo else 0, vo.get('chixu') if vo else 0,
            vo.get('autopass') if vo else False, True)
        row['everyday_time'] = now
        self._zuwu_save(rid, row)
        try:
            self.stage_scheduler.cancel(f'zuwu_expire:{rid}')
        except (AttributeError, KeyError, ValueError):
            pass
        self.schedule_stage(f'zuwu_expire:{rid}', '108002',
                            lambda: self._zuwu_expire(rid),
                            delay=max(int(cfg.get('expire_min') or 0) * 60,
                                      1),
                            unit='SECONDS')
        frames.append(frame(amf3_encode(['108007', [int(did), rest_ms]])))
        frames.append(frame(amf3_encode(['108002', [1, int(did)]])))
        return tuple(frames)

    def _zuwu_expire(self, rid):
        """Forced-leave timer: an unfinished attempt ends (S:EXPIRE_ZW).

        The stage copy expires on its own clock; the bus side drops the
        attempt marker and the center flag so the role can enter again.
        The role keeps its map (no stagecontroll home routing is ported).
        """
        from . import zuwu as zuwu_lib
        attempt = self._zuwu_attempt.pop(str(rid), None)
        if attempt is None:
            return None
        try:
            roles = self.get_roles(self.authed_user or '',
                                   self.server_id or '')
        except Exception:
            return None
        role = roles[0] if roles else None
        if role is None or str(_wire_id(role)) != str(rid):
            return None
        row = self._zuwu_row(rid)
        vo = zuwu_lib.decode_sao(row.get('saodang_data'))
        if vo is None:
            return None
        row['saodang_data'] = zuwu_lib.encode_sao(
            vo.get('sdid'), vo.get('start'), vo.get('chixu'),
            vo.get('autopass'), False)
        self._zuwu_save(rid, row)
        return None

    def zuwu_quit(self):
        """Command 108006: leave the dungeon, [1].

        quitFuben clears center, persists, drops the attempt and expiry,
        and answers [1] (the SC:APPLY_CHANG_MAP home routing needs the
        unported stagecontroll history, so the role keeps its map).
        """
        from . import zuwu as zuwu_lib
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        rid = _wire_id(role)
        row = self._zuwu_row(rid)
        vo = zuwu_lib.decode_sao(row.get('saodang_data'))
        if vo is not None:
            row['saodang_data'] = zuwu_lib.encode_sao(
                vo.get('sdid'), vo.get('start'), vo.get('chixu'),
                vo.get('autopass'), False)
            self._zuwu_save(rid, row)
        self._zuwu_attempt.pop(str(rid), None)
        try:
            self.stage_scheduler.cancel(f'zuwu_expire:{rid}')
        except (AttributeError, KeyError, ValueError):
            pass
        return frame(amf3_encode(['108006', [1]]))

    def zuwu_saodang(self, msg):
        """Command 108004 [dungeonId|null]: start a sweep.

        saoDangFuben: a running sweep answers 114003; a null id sweeps
        the lowest cleared dungeon with attempts left (114005 when
        none); an explicit id needs unlock (114009) and attempts
        (114002). The start burns one attempt, stages the vip-length
        timer, and answers [1, id, endMs, autoPass].
        """
        from . import zuwu as zuwu_lib
        args = self.safe(msg, 1, [])
        raw = args[0] if isinstance(args, list) and args else args
        if isinstance(args, list) and not args:
            raw = None
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        rid = _wire_id(role)
        row = self._zuwu_ensure(rid)
        vo = zuwu_lib.decode_sao(row.get('saodang_data'))
        if zuwu_lib.is_sweeping(vo):
            return frame(amf3_encode(['108004', [0, zuwu_lib.ERR_SAODANGING]]))
        everyday = zuwu_lib.parse_counts(row.get('everyday_pass_data'))
        buy = zuwu_lib.parse_counts(row.get('buy_count_data'))
        try:
            pass_max = int(row.get('pass_max_id') or 0)
        except (TypeError, ValueError):
            pass_max = 0
        if raw is None:
            sid = zuwu_lib.first_sweep_id(everyday, pass_max)
            if sid is None:
                return frame(amf3_encode(
                    ['108004', [0, zuwu_lib.ERR_NO_SAODANG_ID]]))
            autopass = True
        else:
            try:
                sid = int(raw)
            except (TypeError, ValueError):
                return frame(amf3_encode(
                    ['108004', [0, zuwu_lib.ERR_SWEEP_LOCKED]]))
            err = zuwu_lib.check_sweep_param(sid, pass_max, everyday)
            if err is not None:
                return frame(amf3_encode(['108004', [0, err]]))
            autopass = False
        duration = self.config.vip_zuwu_time_ms(
            self._zuwu_vip_level(role)) if self.config is not None else 0
        now = int(self._world_now_ms())
        end = now + int(duration)
        row['saodang_data'] = zuwu_lib.encode_sao(sid, now, int(duration),
                                                  autopass)
        row['everyday_time'] = now
        everyday[int(sid)] = int(everyday.get(int(sid), 0)) - 1
        row['everyday_pass_data'] = zuwu_lib.format_counts(everyday)
        self._zuwu_save(rid, row)
        try:
            self.stage_scheduler.cancel(f'zuwu_sweep:{rid}')
        except (AttributeError, KeyError, ValueError):
            pass
        self.schedule_stage(f'zuwu_sweep:{rid}', '108004',
                            lambda: self._zuwu_sweep_timer(rid),
                            delay=int(duration), unit='MILLISECONDS')
        return frame(amf3_encode(
            ['108004', [1, int(sid), end, bool(autopass)]]))

    def _zuwu_sweep_timer(self, rid):
        """Sweep clock (ZW:FUBENSAODANGFINISH): settle and push rewards."""
        row = self._zuwu_row(rid)
        frames = self._zuwu_settle(rid, row)
        if not frames:
            return None
        return tuple(frames)

    def _zuwu_settle(self, rid, row, force=False):
        """saoDangFinish: grant an elapsed sweep, chain auto-pass links.

        Stale-day and idle calls are no-ops. A manual sweep grants and
        clears; an auto sweep grants, then advances to the next dungeon
        with attempts left (burning one attempt and re-arming the timer)
        until the chain ends. Returns the 108003/108005 push frames.
        Each link is persisted before its push, so a repeated settle
        can never grant twice. force grants a running manual sweep
        early (108010 refresh path).
        """
        from . import zuwu as zuwu_lib
        try:
            roles = self.get_roles(self.authed_user or '',
                                   self.server_id or '')
        except Exception:
            return []
        role = roles[0] if roles else None
        if role is None or str(_wire_id(role)) != str(rid):
            return []
        if not self._day_is_today(row.get('everyday_time'),
                                  int(self._world_now_ms())):
            return []
        vo = zuwu_lib.decode_sao(row.get('saodang_data'))
        if not zuwu_lib.is_sweeping(vo):
            return []
        if not force and \
                zuwu_lib.sweep_end_ms(vo) > int(self._world_now_ms()):
            return []
        cfg = self._zuwu_cfg(vo['sdid'])
        if cfg is None:
            row['saodang_data'] = zuwu_lib.encode_sao(None, 0, 0)
            self._zuwu_save(rid, row)
            return []
        everyday = zuwu_lib.parse_counts(row.get('everyday_pass_data'))
        buy = zuwu_lib.parse_counts(row.get('buy_count_data'))
        used, _total = zuwu_lib.used_total(everyday, buy, vo['sdid'])
        models = self._zuwu_roll_models(cfg)
        formarts = self._zuwu_grant_models(role, models)
        if not vo['autopass']:
            row['saodang_data'] = zuwu_lib.encode_sao(None, 0, 0)
            self._zuwu_save(rid, row)
            return [frame(amf3_encode(
                ['108003', [int(cfg['id']), formarts]]))]
        self._zuwu_refresh_daily(rid, row)
        everyday = zuwu_lib.parse_counts(row.get('everyday_pass_data'))
        try:
            pass_max = int(row.get('pass_max_id') or 0)
        except (TypeError, ValueError):
            pass_max = 0
        nxt = zuwu_lib.first_sweep_id(everyday, pass_max)
        end = 0
        if nxt is not None:
            duration = self.config.vip_zuwu_time_ms(
                self._zuwu_vip_level(role)) if self.config is not None else 0
            now = int(self._world_now_ms())
            end = now + int(duration)
            vo = {'sdid': int(nxt), 'start': now, 'chixu': int(duration),
                  'autopass': True, 'center': bool(vo.get('center'))}
        out = [frame(amf3_encode(
            ['108005', [int(cfg['id']), nxt,
                        [nxt, end], formarts, used]]))]
        if nxt is not None:
            row['saodang_data'] = zuwu_lib.encode_sao(
                vo['sdid'], vo['start'], vo['chixu'], True,
                vo.get('center'))
            row['everyday_time'] = int(self._world_now_ms())
            everyday[int(nxt)] = int(everyday.get(int(nxt), 0)) - 1
            row['everyday_pass_data'] = zuwu_lib.format_counts(everyday)
            self._zuwu_save(rid, row)
            try:
                self.stage_scheduler.cancel(f'zuwu_sweep:{rid}')
            except (AttributeError, KeyError, ValueError):
                pass
            self.schedule_stage(
                f'zuwu_sweep:{rid}', '108005',
                lambda: self._zuwu_sweep_timer(rid),
                delay=int(vo['chixu']), unit='MILLISECONDS')
        else:
            row['saodang_data'] = zuwu_lib.encode_sao(None, 0, 0)
            self._zuwu_save(rid, row)
        return out

    def zuwu_refresh(self, msg):
        """Command 108010 [dungeonId]: finish a sweep now for gold.

        refreshFubenCd: idle answers 114007, auto-pass 114010, a wrong
        id [0, 0.0]; otherwise the gold decrCheck/decr (1002 when
        short) runs first, the sweep settles with its 108003 push, the
        timer is cancelled, ZuWuFuBenRefreshEvent is skipped (no ported
        subscriber), and [1] answers.
        """
        from . import zuwu as zuwu_lib
        args = self.safe(msg, 1, [])
        try:
            did = int(args[0]) if isinstance(args, list) else int(args)
        except (TypeError, ValueError):
            did = 0
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        rid = _wire_id(role)
        row = self._zuwu_row(rid)
        if row.get('saodang_data') is None and \
                self.get_role_zuwufuben(rid) is None:
            return frame(amf3_encode(
                ['108010', [0, zuwu_lib.ERR_NOT_SAODANG]]))
        vo = zuwu_lib.decode_sao(row.get('saodang_data'))
        if not zuwu_lib.is_sweeping(vo):
            return frame(amf3_encode(
                ['108010', [0, zuwu_lib.ERR_NOT_SAODANG]]))
        if vo['autopass']:
            return frame(amf3_encode(
                ['108010', [0, zuwu_lib.ERR_AUTO_PASS]]))
        if int(did) != int(vo['sdid']):
            return frame(amf3_encode(['108010', [0, 0.0]]))
        cfg = self._zuwu_cfg(vo['sdid'])
        if cfg is None:
            return frame(amf3_encode(
                ['108010', [0, zuwu_lib.ERR_NOT_SAODANG]]))
        if not self._zuwu_spend_yb(role, cfg['gold']):
            return frame(amf3_encode(
                ['108010', [0, zuwu_lib.ERR_YB_NOT_ENOUGH]]))
        frames = self._zuwu_settle(rid, row, force=True)
        try:
            self.stage_scheduler.cancel(f'zuwu_sweep:{rid}')
        except (AttributeError, KeyError, ValueError):
            pass
        frames.append(frame(amf3_encode(['108010', [1]])))
        return tuple(frames)

    def zuwu_buy(self, msg):
        """Command 108009 [dungeonId]: buy one more daily attempt.

        buyFightCount: locked dungeons answer 114004, the vip cap 114006,
        the gold decrCheck/decr runs first (1002 when short); bought and
        remaining both grow by one and [1, id, used, total] answers.
        """
        from . import zuwu as zuwu_lib
        args = self.safe(msg, 1, [])
        try:
            did = int(args[0]) if isinstance(args, list) else int(args)
        except (TypeError, ValueError):
            did = 0
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        rid = _wire_id(role)
        row = self._zuwu_ensure(rid)
        try:
            pass_max = int(row.get('pass_max_id') or 0)
        except (TypeError, ValueError):
            pass_max = 0
        if int(did) > pass_max + 1:
            return frame(amf3_encode(
                ['108009', [0, zuwu_lib.ERR_BUY_LOCKED]]))
        buy = zuwu_lib.parse_counts(row.get('buy_count_data'))
        cap = self.config.vip_zuwu_cishu(self._zuwu_vip_level(role)) \
            if self.config is not None else 0
        if int(buy.get(int(did), 0)) + 1 > int(cap):
            return frame(amf3_encode(
                ['108009', [0, zuwu_lib.ERR_BUY_MAX]]))
        price = self.config.zuwu_goumai_price(
            int(buy.get(int(did), 0)) + 1) if self.config is not None else None
        if price is None:
            return frame(amf3_encode(
                ['108009', [0, zuwu_lib.ERR_BUY_MAX]]))
        if not self._zuwu_spend_yb(role, price):
            return frame(amf3_encode(
                ['108009', [0, zuwu_lib.ERR_YB_NOT_ENOUGH]]))
        buy[int(did)] = int(buy.get(int(did), 0)) + 1
        row['buy_count_data'] = zuwu_lib.format_counts(buy)
        everyday = zuwu_lib.parse_counts(row.get('everyday_pass_data'))
        everyday[int(did)] = int(everyday.get(int(did), 0)) + 1
        row['everyday_pass_data'] = zuwu_lib.format_counts(everyday)
        self._zuwu_save(rid, row)
        used, total = zuwu_lib.used_total(everyday, buy, did)
        return frame(amf3_encode(['108009', [1, int(did), used, total]]))

    def zuwu_buy_all(self):
        """Command 108011: buy every remaining attempt the vip cap allows.

        buyFightCountAll: no clears answers [0]; no buyable dungeon
        answers [0, 114006]; otherwise the summed gold decrCheck/decr
        runs first (1002 when short) and [1, [[id, used, total]]] answers.
        """
        from . import zuwu as zuwu_lib
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        if role is None:
            return None
        rid = _wire_id(role)
        row = self._zuwu_ensure(rid)
        try:
            pass_max = int(row.get('pass_max_id') or 0)
        except (TypeError, ValueError):
            pass_max = 0
        if pass_max == 0:
            return frame(amf3_encode(['108011', [0]]))
        buy = zuwu_lib.parse_counts(row.get('buy_count_data'))
        everyday = zuwu_lib.parse_counts(row.get('everyday_pass_data'))
        cap = self.config.vip_zuwu_cishu(self._zuwu_vip_level(role)) \
            if self.config is not None else 0
        total_cost = 0
        for did in range(1, pass_max + 2):
            if did > pass_max + 1:
                break
            if int(buy.get(did, 0)) + 1 > int(cap):
                continue
            price = self.config.zuwu_goumai_price(
                int(buy.get(did, 0)) + 1) \
                if self.config is not None else None
            if price is None:
                continue
            total_cost += int(price)
            buy[did] = int(buy.get(did, 0)) + 1
            everyday[did] = int(everyday.get(did, 0)) + 1
        if total_cost <= 0:
            return frame(amf3_encode(
                ['108011', [0, zuwu_lib.ERR_BUY_MAX]]))
        if not self._zuwu_spend_yb(role, total_cost):
            return frame(amf3_encode(
                ['108011', [0, zuwu_lib.ERR_YB_NOT_ENOUGH]]))
        row['buy_count_data'] = zuwu_lib.format_counts(buy)
        row['everyday_pass_data'] = zuwu_lib.format_counts(everyday)
        self._zuwu_save(rid, row)
        return frame(amf3_encode(
            ['108011', [1, zuwu_lib.info_rows(everyday, buy)]]))

    def _zuwu_on_enter(self, rid):
        """handleLogin: a running sweep restarts its clock at login."""
        from . import zuwu as zuwu_lib
        row = self._zuwu_row(rid)
        if row.get('saodang_data') is None:
            return
        vo = zuwu_lib.decode_sao(row.get('saodang_data'))
        if not zuwu_lib.is_sweeping(vo):
            return
        row['saodang_data'] = zuwu_lib.encode_sao(
            vo.get('sdid'), int(self._world_now_ms()), vo.get('chixu'),
            vo.get('autopass'), vo.get('center'))
        self._zuwu_save(rid, row)

    def _zuwu_on_disconnect(self):
        """handleLogout: bank the sweep remainder and release the stage."""
        from . import zuwu as zuwu_lib
        try:
            roles = self.get_roles(self.authed_user or '',
                                   self.server_id or '')
        except Exception:
            return
        now = int(self._world_now_ms())
        for role in roles or []:
            try:
                rid = _wire_id(role)
            except Exception:
                continue
            self._zuwu_attempt.pop(str(rid), None)
            row = self._zuwu_row(rid)
            if row.get('saodang_data') is None:
                continue
            vo = zuwu_lib.decode_sao(row.get('saodang_data'))
            if not zuwu_lib.is_sweeping(vo):
                continue
            row['saodang_data'] = zuwu_lib.encode_sao(
                vo.get('sdid'), vo.get('start'),
                zuwu_lib.offline_chixu(vo, now),
                vo.get('autopass'), False)
            self._zuwu_save(rid, row)

    def _zuwu_kill_frames(self, actor, dead_monster):
        """Zuwu kill fan-out for one dead monster (role/pet killers)."""
        killer_role = None
        try:
            if actor.get('kind') == 'role':
                killer_role = actor.get('role')
            elif actor.get('kind') == 'pet':
                roles = self.get_roles(self.authed_user or '',
                                       self.server_id or '')
                killer_role = _find_role(roles, actor.get('owner'))
        except Exception:
            killer_role = None
        if killer_role is None:
            return []
        tpl = dead_monster.get('template') or {}
        try:
            return self._zuwu_kill_progress(killer_role, tpl.get('id'))
        except Exception:
            return []

    def _zuwu_kill_progress(self, owner_role, monster_tpl_id):
        """ZuWuStageCopy.killMonster for shared-world dungeon kills.

        Only the active attempt's wanted templates count; every kill
        pushes 108008 like the stage copy, and reaching the wanted
        total ends the copy (finishFuBen): unlock, rewards, 108003.
        """
        try:
            rid = _wire_id(owner_role)
        except Exception:
            return []
        attempt = self._zuwu_attempt.get(str(rid))
        if attempt is None:
            return []
        cfg = self._zuwu_cfg(attempt.get('dungeon'))
        if cfg is None:
            return []
        wanted = {str(mid): int(n) for mid, n in cfg.get('wanted') or []}
        mid = str(monster_tpl_id)
        if mid not in wanted:
            return []
        kills = dict(attempt.get('kills') or {})
        kills[mid] = int(kills.get(mid, 0)) + 1
        attempt['kills'] = kills
        out = [frame(amf3_encode(['108008', mid]))]
        if any(int(kills.get(m, 0)) < n for m, n in wanted.items()):
            return out
        out.extend(self._zuwu_victory(owner_role, rid, attempt, cfg))
        return out

    def _zuwu_victory(self, role, rid, attempt, cfg):
        """finishFuBen: unlock, burn the attempt, grant, push 108003.

        First clears advance passMax, activate the guardian (jihuoZuwu)
        and open the next dungeon; every clear burns one attempt. The
        fixed drops grant without the zubao lottery (finishReward is
        called with lottery False); events have no ported subscribers
        and are skipped like every other publish.
        """
        from . import zuwu as zuwu_lib
        row = self._zuwu_row(rid)
        vo = zuwu_lib.decode_sao(row.get('saodang_data'))
        did = int(attempt.get('dungeon'))
        try:
            pass_max = int(row.get('pass_max_id') or 0)
        except (TypeError, ValueError):
            pass_max = 0
        out = []
        if did > pass_max:
            out.extend(self._zuwu_jihuo(role, cfg.get('wuhunid')))
            row['pass_max_id'] = did
            everyday = zuwu_lib.parse_counts(row.get('everyday_pass_data'))
            buy = zuwu_lib.parse_counts(row.get('buy_count_data'))
            everyday[did + 1] = 1
            buy[did + 1] = 0
            row['everyday_pass_data'] = zuwu_lib.format_counts(everyday)
            row['buy_count_data'] = zuwu_lib.format_counts(buy)
        everyday = zuwu_lib.parse_counts(row.get('everyday_pass_data'))
        everyday[did] = int(everyday.get(did, 0)) - 1
        row['everyday_pass_data'] = zuwu_lib.format_counts(everyday)
        if vo is not None:
            row['saodang_data'] = zuwu_lib.encode_sao(
                vo.get('sdid'), vo.get('start'), vo.get('chixu'),
                vo.get('autopass'), False)
        self._zuwu_save(rid, row)
        formarts = self._zuwu_grant_models(
            role, [list(g) for g in cfg.get('fixed_goods') or []])
        self._zuwu_attempt.pop(str(rid), None)
        try:
            self.stage_scheduler.cancel(f'zuwu_expire:{rid}')
        except (AttributeError, KeyError, ValueError):
            pass
        out.append(frame(amf3_encode(['108003', [did, formarts]])))
        return out

    def role_settings(self, msg):
        role_id = str(self.safe(msg, 1, '') or '')
        settings = self.get_role_settings(role_id, self.authed_user or '',
                                          self.server_id or '')
        if settings is None:
            values = [None, None, None, None]
        else:
            values = [settings.get('quickbar_info'), settings.get('panel_config'),
                      settings.get('ui_info'), settings.get('guaji_info')]
        return frame(amf3_encode(['13000', values]))

    def setting_quickbar(self, msg):
        """Command 13001: SettingAction.changeQuickbar -> changeQuickBar.

        C> [slotInt, skillStr]; nothing is sent back. A missing row
        (or blank quickbar) starts [''] * (slot + 1); a short bar
        grows with '' padding, then the slot takes the skill and the
        bar re-joins with ','. Negative slots and mistyped cells are
        silent (Java throws before persisting).
        """
        data = self.safe(msg, 1)
        try:
            index, skill = data[0], data[1]
        except (TypeError, IndexError):
            return None
        if isinstance(index, bool) or not isinstance(index, int) or \
                not isinstance(skill, str) or index < 0:
            return None
        role = self._equip_role()
        if role is None:
            return None
        rid = role.get('id')
        try:
            settings = self.get_role_settings(
                str(rid), self.authed_user or '', self.server_id or '')
        except Exception:
            settings = None
        current = (settings or {}).get('quickbar_info') or ''
        cells = current.split(',') if current else []
        while len(cells) <= index:
            cells.append('')
        cells[index] = skill
        try:
            self.save_role_settings(str(rid), self.authed_user or '',
                                    self.server_id or '',
                                    quickbar_info=','.join(cells))
        except Exception:
            pass
        return None

    def _setting_bytes(self, msg, field):
        """13002/13003/13004: raw byte[] C> overwrites one blob column."""
        data = self.safe(msg, 1)
        if not isinstance(data, (bytes, bytearray, ByteArray,
                                 memoryview)):
            return None
        role = self._equip_role()
        if role is None:
            return None
        try:
            self.save_role_settings(str(role.get('id')),
                                    self.authed_user or '',
                                    self.server_id or '',
                                    **{field: bytes(data)})
        except Exception:
            pass
        return None

    def setting_panel(self, msg):
        """Command 13002: SettingAction.savePanel -> savePanelConfig."""
        return self._setting_bytes(msg, 'panel_config')

    def setting_ui(self, msg):
        """Command 13003: SettingAction.saveUiInfo -> saveUIInfo."""
        return self._setting_bytes(msg, 'ui_info')

    def setting_guaji(self, msg):
        """Command 13004: SettingAction.saveGuaJi -> saveGuajiInfo."""
        return self._setting_bytes(msg, 'guaji_info')

    def attribute_info(self):
        """Command 12000: role attribute map (StageInfoAction.info -> send2One)."""
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        attrs = self.role_attribute_map(role)
        if attrs is None:
            log.info('conn %d: 12000 without role/level row (ignored)', self.conn_id)
            return None
        return frame(amf3_encode(['12000', Obj(attrs)]))

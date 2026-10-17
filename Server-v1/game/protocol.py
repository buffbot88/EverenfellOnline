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
    slot -> anonymous object with rawOffset (ServerInfoVO.decode reads it).
  - role entries: shape unknown, so only the empty-roles case is served.
"""
import json
import logging
import random
import re
import struct
import threading
import time
import uuid

from .amf3 import ByteArray, Obj
from .attributes import entry_attribute_map
from .buffs import buff_change, buff_value, dynamic_cd, prop_buff, timed_buff
from . import ai as ai_lib
from . import combat as combat_lib
from . import eventbus as eventbus_lib
from . import scheduler as scheduler_lib
from .ratelimit import TokenBucket
from .amf3 import decode as amf3_decode
from .config import MALL_PRICE_COLUMNS, equip_vo, fujia_client_map, qh_xingxings_client, richang_condition_interval, richang_loop_interval, richang_reward_interval, xingxing_lv
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
CMD_VIP = 62000
CMD_ZUWU = 111000
CMD_ZUWUFUBEN = 108001
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
CMD_ZUOQI_JINJIE = 33003
CMD_ZUOQI_CLAIM = 33004
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
CMD_ATTR_CHANGE = 85010
CMD_LIHE_PREVIEW = 30304
BAG_ERR_BIND_NO_DISCARD = 430218
# PropStageAction.consumeGoods reply id; the 30104/30105 ids below are
# server pushes emitted by splitGoods (no inbound route exists for them).
PROP_SKILL_USE = frozenset([1, 2, 3, 5, 11, 14, 36, 37])
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
                 get_role_meiren=None, get_role_zuoqi=None, save_role_zuoqi=None,
                 get_role_skills=None,                  get_role_shenjiang=None, save_role_stage=None,
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
                 get_task_main=None, save_task_main=None,
                 get_task_taofa=None, get_task_taofas=None,
                 insert_task_taofa=None, update_task_taofa=None,
                 delete_task_taofa=None, get_task_taofa_state=None,
                 save_task_taofa_state=None, get_task_richang=None,
                 save_task_richang=None, delete_task_richang=None,
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
        self.save_role_skill = save_role_skill or (lambda *a, **k: False)
        self.get_role_zuoqi = get_role_zuoqi or (lambda role_id: None)
        self.save_role_zuoqi = save_role_zuoqi or (lambda *a, **k: False)
        self.get_role_skills = get_role_skills or (lambda role_id: [])
        self.get_role_shenjiang = get_role_shenjiang or (lambda role_id: [])
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
        self.update_role_bag_slot = update_role_bag_slot or (lambda *a, **k: False)
        self.delete_role_bag_slot = delete_role_bag_slot or (lambda *a: False)
        self.move_role_bag_slot = move_role_bag_slot or (lambda *a: False)
        self.insert_role_bag_slot = insert_role_bag_slot or (lambda *a: None)
        self.rewrite_role_bag_slots = rewrite_role_bag_slots or (lambda *a: False)
        self.save_role_bag_state = save_role_bag_state or (lambda *a, **k: False)
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
        self._monster_hp = {}
        self._pet_state = {}
        self._dead = set()
        # Monster AI state (Phase 4: AiFightServiceImpl + MonsterEventManager).
        # _monster_reg: fighter id -> {template, map, born:[x,y], pos:[x,y]}
        # (snapshot monsters seed on first sight; respawns register here).
        # _hatred: monster id -> attacker fighter id (MonsterHatredManager).
        # _leaving: dead id -> ticks until the 24002 AOI leave (asheslast).
        # _spawning: list of [template_id, map, born, ticks] until the 23002
        # re-enter (creattime). _respawn_next: per-map fresh-id counter.
        self._monster_reg = {}
        self._hatred = {}
        self._leaving = {}
        self._spawning = []
        self._respawn_next = {}
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
            reply = self.handle(payload)
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
            return self.apply_stage_bootstrap(msg)
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
            # getChapterList's 3-arg overload unconditionally returns
            # null, so the chapters panel is client-config driven.
            return frame(amf3_encode(['50001', None]))
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
        if cmd_num == CMD_ZUOQI_PANEL:
            return self.zuoqi_panel(msg)
        if cmd_num == CMD_ZUOQI_RIDE:
            return self.zuoqi_ride(msg)
        if cmd_num == CMD_ZUOQI_CLAIM:
            return self.zuoqi_claim()
        if cmd_num == CMD_BAG_MOVE:
            return self.bag_move(msg)
        if cmd_num == CMD_BAG_SPLIT:
            return self.bag_split(msg)
        if cmd_num == CMD_BAG_DISCARD:
            return self.bag_discard(msg)
        if cmd_num == CMD_BAG_DELETE:
            return self.bag_delete(msg)
        if cmd_num == CMD_PROP_USE:
            return self.prop_use(msg)
        if cmd_num == CMD_PROP_DUOXUAN:
            return self.prop_duoxuan(msg)
        if cmd_num == CMD_PROP_YOUHUI:
            return self.prop_youhui(msg)
        if cmd_num == CMD_PROP_TESHU:
            return self.prop_teshu_count(msg)
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
            return frame(amf3_encode(['64010', None]))
        if cmd_num == CMD_JUQING_INFO:
            return frame(amf3_encode(['64001', [1, [0, None, None, None]]]))
        if cmd_num == CMD_VIP:
            return self.vip_info()
        if cmd_num == CMD_ZUWU:
            return self.zuwu_info()
        if cmd_num == CMD_ZUWUFUBEN:
            return frame(amf3_encode(['108001', [1, [None, [], None]]]))
        log.warning('conn %d: unknown command %r payload=%r (ignored)',
                      self.conn_id, cmd, msg)
        return None

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
        bootstrap = ()
        if ok:
            self.authed_user = user_id
            self.server_id = server_id
            role_rows = self.get_roles(user_id, server_id)
            roles = [self.role_info(r) for r in role_rows]
            # The captured Java login stream pushes settings and currency for
            # the sole role before the client sends its enter-world command.
            if len(role_rows) == 1:
                role = role_rows[0]
                role_id = str(role['id'])
                settings = self.get_role_settings(role_id, user_id, server_id)
                setting_values = ([settings.get('quickbar_info'),
                                   settings.get('panel_config'),
                                   settings.get('ui_info'),
                                   settings.get('guaji_info')]
                                  if settings is not None else [None] * 4)
                bootstrap = (
                    frame(amf3_encode(['13000', setting_values])),
                    self.money_info(role),
                )
            # Slot 3 is a serialized java.util.TimeZone object, not a string:
            # ServerInfoVO.decode() reads `.rawOffset` off it. The capture has
            # exactly {'rawOffset': -18000000, 'ID': 'America/New_York'} and
            # nothing else (tap-decoded.txt line 2).
            tz = Obj({'rawOffset': self.tz_raw_offset, 'ID': self.tz_id})
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
        login_reply = frame(amf3_encode(env))
        return (login_reply, *bootstrap) if bootstrap else login_reply

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
        state = [role.get('face') or '', role.get('level', 1), exp,
                 role.get('sex', 0), str(role.get('job', '')),
                 False, 0, 10, [20000000, 0], 0]
        stage = [str(role.get('map_id') or '0'),
                 role.get('map_x') if role.get('map_x') is not None else 57,
                 role.get('map_y') if role.get('map_y') is not None else 148]
        result = [1, state, stage]
        return frame(amf3_encode(['10003', result]))

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
        if self.stage_registry is not None:
            self.stage_registry.register(_wire_id(role), map_id, self,
                                         x=x, y=y)
        return frame(amf3_encode(['20000', [1, map_id, [x, y]]]))

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
        chenghao, meiren and zuoqi.

        Port of RoleFactoryHelper's replace*Attribute sequence over the
        migrated role_equip / role_attribute_buff / role_xianjiechenhao /
        role_meiren / role_zuoqi rows; empty sources yield no bags,
        exactly Java's clear-and-skip behavior. The ZUOQI_SPEED bag stays
        empty: it needs rideOrNot, which decodeZuoQiInfo reads false from
        the stage blob at entry, so Java skips replaceZuoqiSudu too.
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
            mount = self.get_role_zuoqi(role.get('id'))
        except Exception:
            mount = None
        if mount is not None:
            bags.append(self.config.zuoqi_attribute_map(
                mount.get('zuoqi_rank'), role.get('level')))
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
        self.save_role_state(_wire_id(role), map_x=int(x), map_y=int(y))
        if self.stage_registry is not None:
            self.stage_registry.set_position(_wire_id(role), x, y)
        self._presence_aggro(role, int(x), int(y))
        return None

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
        out = self._dazuo_broadcast(rid, CMD_TELEPORT, args)
        return tuple(out) if out else None

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
        snapshot = self.monster_snapshot_frame(map_id)
        if snapshot is not None:
            frames.append(snapshot)
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
        return frame(amf3_encode(['42001', [1, actor, action, pos, path, flag, None]]))

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
            try:
                records = self.config.monster_snapshot(parts[1])
                rec = records[int(parts[2])]
            except (ValueError, IndexError):
                rec = None
            if rec is not None and rec[0] == fid:
                tpl = self.config.monster_template(rec[1])
                if tpl is not None:
                    hp = self._monster_hp.setdefault(
                        fid, float(rec[4] if rec[4] is not None else 0))
                    self._monster_reg.setdefault(fid, {
                        'template': tpl, 'map': parts[1],
                        'born': [rec[11], rec[12]], 'pos': [rec[11], rec[12]]})
                    self._respawn_next.setdefault(
                        parts[1], len(records))
                    return {'kind': 'monster', 'id': fid, 'template': tpl,
                            'record': rec, 'hp': hp}
        return None

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
                self._persist_mount_hp(pet.get('owner'), new_hp)
        return new_hp

    def _persist_mount_hp(self, owner_id, hp):
        """Write a mount's HP into its owner's role_stage.zuoqi_info.

        The next scene entry reads it back (23009 record, skipped at 0), so a
        hit survives a reconnect. Owners without a stored mount are skipped.
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = _find_role(roles, owner_id)
        if role is None:
            return
        info = decode_zuoqi_info(role.get('zuoqi_info'))
        if info is None:
            return
        info['hp'] = int(round(hp))
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
        total = int(role.get('exp') or 0) + granted
        self.save_role_state(owner['id'], exp=total)
        return [frame(amf3_encode(combat_lib.exp_notice(total, role.get('level') or 0))),
                frame(amf3_encode(combat_lib.exp_drop_frame(
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
        frames = self._resolve_fire(actor, action, index, targets, arg4, arg5)
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
        """One monster/pet AI tick (AiFightServiceImpl.defaultHandle).

        Hatred (FIGHT-state) monsters adjacent to their target emit the
        42001 skillReady + 42002 fire; distant ones chase one tile (BACK:
        toward born, clearing hatred on arrival). Pets step toward owners
        past 2 tiles. The 1-second clock retires corpses (24002 after
        asheslast) and re-produces spawns (23002 after creattime, flag
        True). The server tick loop drives this via tick(); handle() also
        runs it after every 42002, and explicit calls drive tests. Returns
        the frame tuple, or None when the stage is quiet.
        """
        frames = []
        for mid in sorted(self._hatred):
            if mid in self._dead:
                continue
            reg = self._monster_reg.get(mid)
            if reg is None:
                self._hatred.pop(mid, None)
                continue
            target = self._stage_fighter(self._hatred[mid])
            if target is None or target['id'] in self._dead:
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
        for mid in sorted(self._leaving):
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
        for mid in [m for m in self._leaving if self._leaving[m] <= 0]:
            del self._leaving[mid]
        still = []
        for tpl_id, map_id, born, ticks in self._spawning:
            ticks -= 1
            if ticks > 0:
                still.append([tpl_id, map_id, born, ticks])
                continue
            tpl = (self.config.monster_template(tpl_id)
                   if self.config is not None else None)
            if tpl is None:
                log.info('conn %d: respawn template %r gone (skipped)',
                         self.conn_id, tpl_id)
                continue
            n = self._respawn_next.get(str(map_id), 0)
            self._respawn_next[str(map_id)] = n + 1
            nid = 'm_%s_%d' % (map_id, n)
            self._monster_reg[nid] = {'template': tpl, 'map': str(map_id),
                                      'born': list(born), 'pos': list(born)}
            self._monster_hp[nid] = float(tpl.get('hitpoints') or 0)
            frames.append(frame(amf3_encode(
                ['23002', [ai_lib.respawn_record(nid, tpl, born)]])))
        self._spawning = still
        return tuple(frames) if frames else None

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
        out = self._dazuo_broadcast(rid, CMD_DAZUO_EXIT, None)
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
        if exp_gain > 0:
            self.save_role_state(role_id, exp=int(role.get('exp') or 0) + exp_gain)
        if zhenqi_gain > 0:
            self.save_role_state(role_id,
                                 zhenqi=int(role.get('zhenqi') or 0) + zhenqi_gain)
        self._dazuo_timer(role_id)
        return frame(amf3_encode(['44004', [exp_gain, zhenqi_gain]]))

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
        try:
            vip = self.get_role_vip(role.get('id'))
        except Exception:
            vip = None
        buff_id = (self.config.vip_buff_id((vip or {}).get('vip_level'))
                   if self.config is not None else None)
        if buff_id is not None:
            adds.append(timed_buff(self.next_buff_id('buff'), buff_id, None,
                                   1, wire_id))
        else:
            log.info('conn %d: no VIP buff for role %r (no vip row/mapping)',
                     self.conn_id, wire_id)
        lasttime = (self.config.buff_lasttime('birthprotect')
                    if self.config is not None else None)
        if lasttime is None:
            log.info('conn %d: no birthprotect lasttime (no XiaoGuoBiao)',
                     self.conn_id)
        else:
            adds.append(timed_buff(self.next_buff_id('buff'), 'birthprotect',
                                   lasttime, 1, wire_id))
        if not adds:
            return None
        return frame(amf3_encode(buff_change(wire_id, adds)))

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

    def apply_stage_bootstrap(self, msg):
        """Reply to 20000, then push the scene entry and role HP/MP like Java."""
        reply = self.apply_stage(msg)
        if reply is None:
            return None
        args = self.safe(msg, 1, [])
        role_id = str(self.safe(args, 0, '') or '')
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = _find_role(roles, role_id)
        frames = [reply]
        target = str(self.safe(args, 1, '') or role.get('map_id') or '')
        # Java always sends this on stage entry, for every map, not just the
        # ones we have a captured type for.
        map_type = self.map_type_for(target)
        frames.append(frame(amf3_encode(['21000', [1, 1, map_type]])))
        snapshot = self.monster_snapshot_frame(target)
        if snapshot is not None:
            frames.append(snapshot)
        # Tap order line 9: the mount pet enters the stage right after the
        # monster snapshot and before the stats pushes.
        pet = self.zuoqi_pet_frame(role, target)
        if pet is not None:
            frames.append(pet)
        hp = [role.get(k) for k in ('hp', 'max_hp', 'mp', 'max_mp')]
        if all(v is not None for v in hp):
            frames.append(frame(amf3_encode(
                ['12004', [_wire_id(role), *hp]])))
        # Captured entry order after 12004 (tap lines 11-13): shanbi value,
        # zhenqi+cap, attribute map. The last two need the level row.
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
        # Captured entry order after 12000 (tap lines 13, 21, 24): the
        # 42100 buff flush, the 42005 skill cooldown, then 40501. The
        # fight-state notice needs no config, so it closes every entry;
        # the buff/cooldown frames skip themselves when their data is
        # absent (no XiaoGuoBiao/CdBiao rows, no role skill state).
        self._stage_serial += 1
        self._obj_seq = 0
        buff_frame = self.entry_buff_frame(role)
        if buff_frame is not None:
            frames.append(buff_frame)
        cd_frame = self.skill_cd_frame(role)
        if cd_frame is not None:
            frames.append(cd_frame)
        frames.append(self.fight_state_frame(role))
        return tuple(frames) if len(frames) > 1 else reply

    def change_stage(self, msg):
        """Acknowledge the role's scene entry with line number and map type."""
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
        snapshot = self.monster_snapshot_frame(map_id)
        if snapshot is not None:
            frames.append(snapshot)
        return tuple(frames) if len(frames) > 1 else frames[0]

    def monster_snapshot_frame(self, map_id):
        """23002 monster snapshot from monster.mm, or None when the map has no spawns."""
        if self.config is None:
            return None
        records = self.config.monster_snapshot(map_id)
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

        [mount, level, skills, clothes, longhun1, longhun0, zhanli,
        skillBook]. Mount and level come from zuoqi_info and ZuoJiBiao; the
        rest lives in tables the migration does not carry (role_zuoqi_skill,
        clothes, zhanli computation), which is exactly what Java returns
        from those sources when they are empty: null/0.
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
        return frame(amf3_encode(
            ['12102', [mount, level, None, None, 0, 0, 0, None]]))

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
        if role is None:
            roles = self.get_roles(self.authed_user or '', self.server_id or '')
            role = roles[0] if roles else {}
        return frame(amf3_encode(['32010', [role.get('tongqian') or 0,
                                             role.get('lingshi') or 0,
                                             role.get('bind_lingshi') or 0,
                                             role.get('recive_yb') or 0]]))

    def role_extra_info(self):
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else {}
        values = [1, role.get('hp') or 0, role.get('mp') or 0, 9999,
                  role.get('zhenqi') or 0, role.get('shengwang') or 0,
                  0, None, None, 0, 1]
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
        [-105, -100] equip rows (none exist for any legacy role), and 0
        for longhun (getlongLingOrLongHun returns 0 on an empty goods
        map, and attribute_goods_id is NULL for every legacy role).
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        level, base, qianghua, fujia, dan, vip = 0, 0, 0, 0, 0, 0
        zuoqi, zuoqi_equip = 0, 0
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
        return frame(amf3_encode(['12010', [
            [base, qianghua, fujia, 0, 0], level, skill_pair,
            [zuoqi, zuoqi_equip, 0],
            [0, 0], vip, shenjiang_slot, 0, 0, dan, [0, 0], 0, 0, 0, 0, 0,
            [0, 0, 0], 0, 0, 0, 0, 0, 0, [0, 0], 0]]))

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
        try:
            total = int(role.get('exp') or 0) + add
        except (TypeError, ValueError):
            total = add
        self.save_role_state(rid, exp=total)
        return (frame(amf3_encode(combat_lib.exp_notice(total, role_lv))),
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
        skills 1/2/3/5/14/36/37 have portable effects so far (3 is the
        taofa scroll hook); other known skills stay open and silent
        pending their systems (documented).
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
        # consumePrior default true; HpMp/skillBook/LiHe/TaoFa null (their
        # services consume internally, so the pipeline never does).
        prior = skill not in (1, 37, 11, 3)
        if prior and not self._prop_decr(rid, row):
            return None
        frames = self._prop_effect(role, rid, row, grow, skill)
        if frames is None:
            return None
        frames, terminal = frames
        if frames is None:
            return None
        if terminal:
            if not prior:
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
        total = int(role.get('exp') or 0) + amount
        self.save_role_state(rid, exp=total)
        return [frame(amf3_encode(
            combat_lib.exp_notice(total, role.get('level') or 0)))]

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
            total = int(role.get('exp') or 0) + add_exp
            self.save_role_state(rid, exp=total)
            frames.append(frame(amf3_encode(
                combat_lib.exp_notice(total, role.get('level') or 0))))
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
            total = int(role.get('exp') or 0) + cfg['add_exp']
            self.save_role_state(rid, exp=total)
            frames.append(frame(amf3_encode(
                combat_lib.exp_notice(total, role.get('level') or 0))))
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
        """reward(): currencies, exp, zhenqi, goods, shenjiang, event."""
        try:
            exp = int(cfg.get('exp') or 0)
        except (TypeError, ValueError):
            exp = 0
        if exp > 0:
            try:
                total = int(role.get('exp') or 0) + exp
            except (TypeError, ValueError):
                total = exp
            try:
                self.save_role_state(rid, exp=total)
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

    def _task_reward_result(self, cfg):
        """CreateTaskOutputWrapper.getRewardResultOutPut for the 50005 push."""
        items = cfg.get('reward_items')
        pairs = [[i['goods_id'], i['count']] for i in items] \
            if items else []
        return [1, [cfg['id'], pairs, cfg.get('exp') or 0,
                    cfg.get('jb') or 0, cfg.get('bound_ob') or 0,
                    cfg.get('prestige') or 0, cfg.get('zhiqi') or 0]]

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
            self._task_reward(role, rid, current)
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
            frames.append(frame(amf3_encode(['50007', row['task_id']])))
            if cfg.get('pay_type') == '1':
                frames.extend(self._task_submit_chain(role, rid, cfg))
        self.save_task_main(rid, **row)
        return frames

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
            result = self._taofa_pay(role, rid, row)
            if result is not None:
                frames.append(frame(amf3_encode(
                    [str(CMD_TAOFA_PAY), result])))
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
        if totals['exp'] > 0:
            try:
                total = int(role.get('exp') or 0) + totals['exp']
            except (TypeError, ValueError):
                total = totals['exp']
            try:
                self.save_role_state(rid, exp=total)
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
        return [cfg['id'],
                self._taofa_show_pairs(cfg.get('show_items')),
                int(cfg.get('exp') or 0), int(cfg.get('jb') or 0),
                int(cfg.get('bind_yb') or 0), prestige,
                int(cfg.get('zhenqi') or 0)]

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
        result = self._richang_pay(role, rid, False)
        if result is not None:
            frames.append(frame(amf3_encode(
                [str(CMD_RICHANG_PAY), result])))
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
        result = self._richang_pay(role, rid, False)
        if result is not None:
            frames.append(frame(amf3_encode(
                [str(CMD_RICHANG_PAY), result])))
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
        if row.get('current_loop') == RICHANG_MAX_LOOP and \
                row.get('task_state') != 2:
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
                total = int(role.get('exp') or 0) + exp
            except (TypeError, ValueError):
                total = exp
            try:
                self.save_role_state(rid, exp=total)
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
        return [task_uid, pairs, int(reward.get('exp') or 0),
                int(reward.get('jb') or 0), int(reward.get('bind_yb') or 0),
                0, int(reward.get('zhenqi') or 0)]

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
            result = self._richang_pay(role, rid, True)
            if result is not None:
                frames.append(frame(amf3_encode(
                    [str(CMD_RICHANG_PAY), result])))
                if self._richang_stop(rid, frames) is False:
                    nxt = self._richang_receive(role, rid, False)
                    if nxt is not None:
                        frames.append(nxt)
        self._richang_save(rid, row)
        return frames

    # Mount panel/ride/claim (zuoqi 33001/33000/33004). Evidence:
    # ZuoQiAction (ZuoqiMianban/rideZuoQi/lingquZuoqi) and
    # RoleZuoQiServiceImpl (getZuoQiPannel/rideZuoqi/changeZuoqiRank).
    ZUOQI_MIN_RANK = 1
    ZUOQI_EMPTY_CODE = 520005
    ZUOQI_NOCONFIG_CODE = 520006

    def _zuoqi_row(self, rid):
        """Role's mount row, created zeroed like createRoleZuoqi, or None."""
        try:
            row = self.get_role_zuoqi(rid)
        except Exception:
            row = None
        if row is not None:
            return dict(row)
        row = {'zuoqi_rank': 0, 'zuoqi_cur_rank': 0, 'lucky_value': 0,
               'update_time': 0}
        try:
            self.save_role_zuoqi(rid, 0, 0, 0, 0)
        except Exception:
            return None
        return row

    def _zuoqi_save(self, rid, row):
        """Persist a mount row dict under its role id."""
        try:
            self.save_role_zuoqi(
                rid, row.get('zuoqi_rank'), row.get('zuoqi_cur_rank'),
                row.get('lucky_value'), row.get('update_time'))
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
        # map, which lives in RoleZuoqi's unmigrated kaifuData column.
        reply = [1, [rank, self._zuoqi_level(level, cfg), lucky,
                     self.config.zuoqi_fight(req, level)],
                 [], self._zuoqi_in_kaifu(rank), 0]
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
        """Command 32000: MallServiceImpl.shopList [1, None, items].

        The request is [sign, category]; Java answers nothing when the
        category is empty, else the raw WuPinChuShouBiao rows of the
        category. The sign is always null (see GameConfig.mall_sign), so
        the [-1, echo] branch in bytecode is unreachable.
        """
        args = self.safe(msg, 1, [])
        category = self.safe(args, 1)
        if not category:
            return None
        items = (self.config.mall_shop_list(category)
                 if self.config is not None else [])
        return frame(amf3_encode(['32000', [1, None, items]]))

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

        Port of ZuwuServiceImpl.getInfo with no owned zuwu: one mockZuwuInfo
        [id,0,0,0,type] per ZuWuShuxing type, then the fragment bag count
        (0: no bag data is migrated).
        """
        entries = (self.config.zuwu_info()[0] if self.config is not None else [])
        return frame(amf3_encode(['111000', [entries, 0]]))

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

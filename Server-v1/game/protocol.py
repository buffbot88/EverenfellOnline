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
import time

from .amf3 import Obj
from .attributes import entry_attribute_map
from .buffs import buff_change, buff_value, dynamic_cd, prop_buff, timed_buff
from . import ai as ai_lib
from . import combat as combat_lib
from .amf3 import decode as amf3_decode
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
CMD_MALL = 32000
CMD_JUQING_AWARD = 64010
CMD_JUQING_INFO = 64001
CMD_VIP = 62000
CMD_ZUWU = 111000
CMD_ZUWUFUBEN = 108001
CMD_ROLE_SETTINGS = 13000
CMD_ROLE_ATTRS = 12000
CMD_ZUOQI_INFO = 12102
CMD_TILE = 40000
CMD_JUMP = 40001
CMD_TELEPORT = 40100
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


def _find_role(roles, role_id):
    """Resolve the id the client sends: local id or migrated legacy id."""
    return next((r for r in roles if str(r.get('id')) == role_id
                 or str(r.get('legacy_id') or '') == role_id), None)


class Session:
    def __init__(self, conn_id, check_sign, get_roles, server_start_ms,
                 gm_open=False, tz_raw_offset=-18000000,
                 tz_id='America/New_York',
                 get_role_settings=None, create_role=None, save_role_state=None,
                 get_role_equip=None, get_role_attr_buffs=None,
                 get_role_vip=None,
                 config=None):
        self.conn_id = conn_id
        self.config = config
        self.get_role_equip = get_role_equip or (lambda role_id: [])
        self.get_role_attr_buffs = get_role_attr_buffs or (lambda role_id: [])
        self.get_role_vip = get_role_vip or (lambda role_id: None)
        self.buf = bytearray()
        self.cipher = None
        self.key = None
        self.authed_user = None
        self.server_id = None
        self.check_sign = check_sign
        self.get_roles = get_roles
        self.get_role_settings = get_role_settings or (lambda role_id, user, server: None)
        self.create_role_cb = create_role or (lambda *args: None)
        self.save_role_state = save_role_state or (lambda *args, **kwargs: False)
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

    def feed(self, data: bytes):
        """Consume TCP bytes, return list of complete out-frames to send."""
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
        if cmd_num == CMD_TILE:
            return self.tile_step(msg)
        if cmd_num == CMD_JUMP:
            return self.jump(msg)
        if cmd_num == CMD_TELEPORT:
            return self.teleport(msg)
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
        if cmd_num == CMD_MALL:
            return self.mall_info(msg)
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
        return frame(amf3_encode(['20000', [1, map_id, [x, y]]]))

    def role_bags(self, role):
        """No-effect attribute bags for a role: gear + shuxingdan pills.

        Port of RoleFactoryHelper's replace*Attribute sequence over the
        migrated role_equip / role_attribute_buff rows; empty sources
        yield no bags, exactly Java's empty-bag behavior.
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
        return [b for b in bags if b]

    def role_attribute_map(self, role):
        """12000 map for a role: level row + gear/dan bags (empty effect)."""
        if role is None or self.config is None:
            return None
        row = self.config.role_attribute_row(role.get('level'))
        if row is None:
            return None
        return entry_attribute_map(row, role.get('max_mp'),
                                   bags=self.role_bags(role))

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
        self._presence_aggro(role, int(x), int(y))
        return None

    def jump(self, msg):
        """Command 40001: log only; no Java reply captured."""
        log.info('conn %d: jump %r (logged, no reply)', self.conn_id, msg[1:2])
        return None

    def teleport(self, msg):
        """Command 40100: log only; no Java reply captured."""
        log.info('conn %d: teleport %r (logged, no reply)', self.conn_id, msg[1:2])
        return None

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
            self._pet_state[fighter['id']]['hp'] = new_hp
        return new_hp

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
        lv_diff = max(int(role.get('level') or 0) - int(tpl.get('level') or 0), 0)
        revise = (self.config.exp_revise(100, solo=True)
                  if self.config is not None else None)
        decay = (self.config.exp_decay(lv_diff)
                 if self.config is not None else None)
        if revise is None or decay is None:
            log.info('conn %d: no exp tables for %r (no 12001/12030)',
                     self.conn_id, dead_fighter['id'])
            return []
        base = combat_lib.base_kill_exp(tpl.get('basicexp') or 0,
                                        xiuZheng=revise, levelXishu=decay)
        granted = combat_lib.fight_exp_with_bonuses(base)
        total = int(role.get('exp') or 0) + granted
        self.save_role_state(owner['id'], exp=total)
        return [frame(amf3_encode(combat_lib.exp_notice(total, role.get('level') or 0))),
                frame(amf3_encode(combat_lib.exp_drop_frame(
                    dead_fighter['id'], tpl.get('id'), granted)))]

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
        True). Without a server loop the tick rides role actions (handle()
        runs it after every 42002); explicit calls drive tests. Returns the
        frame tuple, or None when the stage is quiet.
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
                ['12050', [int(role.get('zhenqi') or 0),
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
        """
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        level, base, qianghua, fujia, dan, vip = 0, 0, 0, 0, 0, 0
        if role is not None and self.config is not None:
            level = self.config.level_fight(
                self.config.role_attribute_row(role.get('level')))
            try:
                items = self.get_role_equip(role.get('id')) or []
            except Exception:
                items = []
            base, qianghua, fujia = self.config.equip_fight_parts(items)
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
            [base, qianghua, fujia, 0, 0], level, [0, 0], [0, 0, 0],
            [0, 0], vip, [0, 0, 0], 0, 0, dan, [0, 0], 0, 0, 0, 0, 0,
            [0, 0, 0], 0, 0, 0, 0, 0, 0, [0, 0], 0]]))

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

    def attribute_info(self):
        """Command 12000: role attribute map (StageInfoAction.info -> send2One)."""
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = roles[0] if roles else None
        attrs = self.role_attribute_map(role)
        if attrs is None:
            log.info('conn %d: 12000 without role/level row (ignored)', self.conn_id)
            return None
        return frame(amf3_encode(['12000', Obj(attrs)]))

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
import re
import struct
import time

from .amf3 import Obj
from .attributes import entry_attribute_map
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
# Observed on the wire but with no captured reply or confirmed semantics yet;
# logged so a live run shows the real post-entry command sequence.
CMD_UNKNOWN_OBSERVED = frozenset({19000, 24002, 42005, 43000, 53021})


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
                 config=None):
        self.conn_id = conn_id
        self.config = config
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
            return self.skill_fire(msg)
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
        if cmd_num == CMD_ZUOQI_INFO:
            return self.zuoqi_info()
        if cmd_num == CMD_RECIVE_YB:
            return frame(amf3_encode(['35011', 0]))
        if cmd_num == CMD_MALL:
            return frame(amf3_encode(['32000', [1, '', []]]))
        if cmd_num == CMD_JUQING_AWARD:
            return frame(amf3_encode(['64010', []]))
        if cmd_num == CMD_JUQING_INFO:
            return frame(amf3_encode(['64001', []]))
        if cmd_num == CMD_VIP:
            return frame(amf3_encode(['62000', None]))
        if cmd_num == CMD_ZUWU:
            return frame(amf3_encode(['111000', [[], []]]))
        if cmd_num == CMD_ZUWUFUBEN:
            return frame(amf3_encode(['108001', []]))
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
        return frame(amf3_encode(['42001', [1, actor, action, pos, path, flag, None]]))

    def skill_fire(self, msg):
        """Command 42002 C> [actor, action, 0, [targets], None, 1]."""
        args = self.safe(msg, 1, [])
        actor = str(self.safe(args, 0, '') or '')
        targets = self.safe(args, 3, [])
        if not actor:
            log.info('conn %d: 42002 without actor (ignored)', self.conn_id)
            return None
        if self._owned_actor(actor) is None:
            log.info('conn %d: 42002 for unowned %r (ignored)', self.conn_id, actor)
            return None
        log.info('conn %d: 42002 %r targets=%r (logged, no damage invented)',
                 self.conn_id, actor, targets)
        return None

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
            frames.append(frame(amf3_encode(
                ['12000', Obj(entry_attribute_map(row, role.get('max_mp')))])))
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
            float(entry_attribute_map(level_row, role.get('max_mp'))['7']),
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
        return frame(amf3_encode(['12010', [[0] * 5 for _ in range(5)]]))

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
        row = (self.config.role_attribute_row(role.get('level'))
               if role is not None and self.config is not None else None)
        if row is None:
            log.info('conn %d: 12000 without role/level row (ignored)', self.conn_id)
            return None
        return frame(amf3_encode(
            ['12000', Obj(entry_attribute_map(row, role.get('max_mp')))]))

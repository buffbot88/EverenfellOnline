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
import logging
import struct
import time

from .amf3 import Obj
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
CMD_MONEY = 32010
CMD_ROLE_EWAI = 12011
CMD_FIGHTING = 12010
CMD_RECIVE_YB = 35011
CMD_MALL = 32000
CMD_JUQING_AWARD = 64010
CMD_JUQING_INFO = 64001
CMD_VIP = 62000
CMD_ZUWU = 111000
CMD_ZUWUFUBEN = 108001


def frame(payload: bytes) -> bytes:
    return struct.pack('>I', len(payload)) + payload


class Session:
    def __init__(self, conn_id, check_sign, get_roles, server_start_ms,
                 gm_open=False, tz_raw_offset=0, tz_id='UTC'):
        self.conn_id = conn_id
        self.buf = bytearray()
        self.cipher = None
        self.key = None
        self.authed_user = None
        self.server_id = None
        self.check_sign = check_sign
        self.get_roles = get_roles
        self.server_start_ms = server_start_ms
        self.gm_open = gm_open
        self.tz_raw_offset = tz_raw_offset
        self.tz_id = tz_id

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
            if reply is not None:
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
            log.warning('conn %d: createRole not yet served (shape TBD)', self.conn_id)
            return None
        if cmd_num == CMD_GETTIME:
            return frame(amf3_encode(['19001', int(time.time() * 1000)]))
        if cmd_num == CMD_APPLY_STAGE:
            return frame(amf3_encode(['20000', [1, '0', [57, 148]]]))
        if cmd_num == CMD_MONEY:
            return frame(amf3_encode(['32010', [0, 0, 0, 0]]))
        if cmd_num == CMD_ROLE_EWAI:
            return frame(amf3_encode(['12011', [0, 0, 0, 0, 0, 0, 0, 0, '', 0, 0]]))
        if cmd_num == CMD_FIGHTING:
            return frame(amf3_encode(['12010', [[0] * 5 for _ in range(5)]]))
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
            str(r['id']),
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
            roles = [self.role_info(r) for r in self.get_roles(user_id, server_id)]
            # Slot 3 is a serialized java.util.TimeZone object, not a string:
            # ServerInfoVO.decode() reads `.rawOffset` off it (it reflects the
            # Java bean, hence ID/displayName/dstSavings alongside).
            tz = Obj({'rawOffset': self.tz_raw_offset, 'ID': self.tz_id,
                      'displayName': self.tz_id, 'dstSavings': 0})
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
        return frame(amf3_encode(env))

    def enter_world(self, msg):
        """10003 stagecontroll LOGIN: enter the world with a role.

        Request is [10003, roleId str] (captured live from the projector).
        Reply mirrors StageControllOutputWrapper.login bytecode:
          [1, [face, level, exp, sex, job, chenmi, chenmiTime,
                vipLevel, rechargeArr, gmState], [mapId, mapX, mapY]]
        Unimplemented server state is zeroed (no vip/recharge/gm/chenmi in
        our store). Spawn position mirrors a fresh account's saved row
        (map 0, x 57, y 148) until real per-character positions are stored.
        """
        role_id = str(self.safe(msg, 1, '') or '')
        roles = self.get_roles(self.authed_user or '', self.server_id or '')
        role = next((r for r in roles if str(r.get('id')) == role_id), None)
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
        result = [1, [role.get('face') or '', role.get('level', 1),
                      role.get('exp', 0), role.get('sex', 0),
                      str(role.get('job', '')), False, 0, 0, [0, 0], 0],
                  ['0', 57, 148]]
        return frame(amf3_encode(['10003', result]))

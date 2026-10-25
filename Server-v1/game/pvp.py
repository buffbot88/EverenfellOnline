"""PvP rules recovered from the legacy stage fight pipeline (dntg_start.jar).

Provenance:
- BattleMode.convert: 0 PEACE, 1 TEAM, 2 GUILD, 3 ALL, 4 SHANE; anything
  else reads as PEACE.
- RoleBattleModeRelation.isEnemy and SkillTargetFilterFactory.stageProtect:
  who a role may hit with an ENEMY skill, in the bytecode's own gate order.
- RolePkManager: pkVal/startTime/runTime/grayTime encoded through
  MapUtil.map2String (``key:value`` pairs joined by ``;``); gray lasts
  60_000 ms; the PKCHECK minute decays one point once the safe/unsafe span
  has elapsed.
- RoleEventManager.hanlePkIncr: a role kill adds the victim row's addpk
  unless the killer is gray, in SHANE mode, in the PKFREE state, or the
  victim's row adds nothing.
- FightServiceImpl.redNameDropYxb + PkUtil.calDropYxb: a red name
  (diaoqian) drops min(pk - 3, 20) * 5,000 tongqian as money ground items
  worth 5,000 each plus the remainder.
"""
import threading

BATTLE_PEACE = 0
BATTLE_TEAM = 1
BATTLE_GUILD = 2
BATTLE_ALL = 3
BATTLE_SHANE = 4

MIN_PVP_LEVEL = 30
RED_PK_VALUE = 7
GRAY_MS = 60000
PK_CHECK_MS = 60000
PK_DROP_OFFSET = 3
PK_DROP_MAX_STACKS = 20
MONEY_STACK = 5000

MONEY_GOODS_ID = 'money'
REVIVE_GOODS_ID = 'fuhuo'


def battle_mode(value):
    """BattleMode.convert: the client's int, PEACE for anything outside 0-4."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return BATTLE_PEACE
    return value if 0 <= value <= 4 else BATTLE_PEACE


def is_red(pk_value):
    """PkConfigExportServiceImpl.isRed: 7 or more is a red name."""
    try:
        return int(pk_value) >= RED_PK_VALUE
    except (TypeError, ValueError):
        return False


def pk_config_row(config, pk_value):
    """PkConfig for a value, clamped into the configured pkvalue range."""
    if config is None:
        return None
    return config.pk_config(pk_value)


# GameConfig.pk_table stores the pkbiao columns under snake_case keys; the
# Java field names are accepted as a fallback so unit rows in either shape work.
_KEY_ALIASES = {'active_state': ('activestate',), 'add_pk': ('addpk',)}


def _row_attr(row, key, default=0):
    if not row:
        return default
    candidates = (key,) + _KEY_ALIASES.get(key, ())
    for candidate in candidates:
        if row.get(candidate) is None:
            continue
        try:
            return int(row.get(candidate) or default)
        except (TypeError, ValueError):
            continue
    return default


def row_active_state(row):
    """PkConfig.isActiveState as configured (blank reads False, like object2boolean)."""
    if not row:
        return False
    value = row.get('active_state', row.get('activestate'))
    if isinstance(value, bool):
        return value
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return False


def need_gray(attacker_pk, target_pk, config):
    """RoleEventManager.isNeedGray: both rows must be in an active PK state."""
    return (row_active_state(pk_config_row(config, attacker_pk))
            and row_active_state(pk_config_row(config, target_pk)))


def pk_gain(victim_pk, killer_pk, killer_mode, killer_gray, config,
            killer_pk_free=False):
    """RoleEventManager.hanlePkIncr: PK the killer earns for this kill.

    PKFREE (a buff state) and the SHANE/gray protection skip the gain
    entirely; the amount is the victim's row addpk, so killing an innocent
    (pk 0 row: 1) costs a point while killing a red name (rows 7+: 0) is free.
    """
    if killer_pk_free or killer_mode == BATTLE_SHANE or killer_gray:
        return 0
    row = pk_config_row(config, victim_pk)
    return max(_row_attr(row, 'add_pk'), 0)


def drop_amount(pk_value):
    """PkUtil.calDropYxb: min(pk - 3, 20), never below 0."""
    try:
        value = int(pk_value) - PK_DROP_OFFSET
    except (TypeError, ValueError):
        return 0
    return max(min(value, PK_DROP_MAX_STACKS), 0)


def money_chunks(amount):
    """Red-name drop split: whole 5,000 stacks then the remainder."""
    try:
        left = int(amount)
    except (TypeError, ValueError):
        return []
    if left <= 0:
        return []
    chunks = [MONEY_STACK] * (left // MONEY_STACK)
    if left % MONEY_STACK:
        chunks.append(left % MONEY_STACK)
    return chunks


def is_enemy(*, attacker_id, attacker_mode, attacker_team, attacker_guild,
             target_id, target_level, target_team, target_guild,
             target_pk=0, target_gray=False, friendly_guild=False,
             target_protected=False):
    """RoleBattleModeRelation.isEnemy for an ENEMY skill's role target.

    Order is the bytecode's: self, the level-30 floor, PEACE, the target's
    protected buff (birth protection), then the attacker's mode. GUILD and
    TEAM treat a missing side as an enemy and an equal (or allied) side as
    friendly; ALL hits everyone; SHANE only hits gray or red names.
    """
    if str(attacker_id) == str(target_id):
        return False
    try:
        if int(target_level or 0) < MIN_PVP_LEVEL:
            return False
    except (TypeError, ValueError):
        return False
    if attacker_mode == BATTLE_PEACE:
        return False
    if target_protected:
        return False
    if attacker_mode == BATTLE_GUILD:
        if attacker_guild is None:
            return True
        if target_guild is None:
            return True
        if str(attacker_guild) == str(target_guild):
            return False
        return not friendly_guild
    if attacker_mode == BATTLE_TEAM:
        if attacker_team is None:
            return True
        if target_team is None:
            return True
        return str(attacker_team) != str(target_team)
    if attacker_mode == BATTLE_ALL:
        return True
    if attacker_mode == BATTLE_SHANE:
        if target_gray:
            return True
        return is_red(target_pk)
    return True


def strips_protection(*, attacker_id, attacker_mode, target_id, target_level):
    """Whether the swing strips the attacker's own protected buff.

    isEnemy removes every protected buff on the attacker after the self,
    level and PEACE gates and before the relation switch, so a role that
    starts a fight loses birth protection even against a teammate.
    """
    if attacker_mode == BATTLE_PEACE:
        return False
    if str(attacker_id) == str(target_id):
        return False
    try:
        return int(target_level or 0) >= MIN_PVP_LEVEL
    except (TypeError, ValueError):
        return False


class PkState:
    """RolePkManager: the pk value and its decay/gray timers for one role."""

    __slots__ = ('value', 'last_time', 'run_time', 'gray_start')

    def __init__(self, value=0, last_time=0, run_time=0, gray_start=0):
        self.value = max(int(value or 0), 0)
        self.last_time = int(last_time or 0)
        self.run_time = int(run_time or 0)
        self.gray_start = int(gray_start or 0)

    @classmethod
    def decode(cls, text, now_ms=0):
        """PkState from RoleStage.pkInfo (decodePkInfo restarts lastTime now)."""
        state = cls()
        if not text or not isinstance(text, str):
            return state
        for cell in str(text).split(';'):
            key, _, raw = cell.partition(':')
            if not raw:
                continue
            try:
                value = int(float(raw))
            except (TypeError, ValueError):
                continue
            if key == 'pkVal':
                state.value = max(value, 0)
            elif key == 'runTime':
                state.run_time = max(value, 0)
            elif key == 'grayTime':
                state.gray_start = max(value, 0)
        state.last_time = int(now_ms or 0)
        return state

    def encode(self, now_ms=0):
        """encodePkInfo: fold the live epoch into runTime, then zero startTime."""
        if self.last_time:
            self.run_time += max(int(now_ms or 0) - self.last_time, 0)
            self.last_time = 0
        return 'pkVal:%d;startTime:%d;runTime:%d;grayTime:%d' % (
            self.value, self.last_time, self.run_time, self.gray_start)

    def copy(self):
        return PkState(self.value, self.last_time, self.run_time,
                       self.gray_start)

    def is_gray(self, now_ms):
        """grayState: a live gray stamp younger than 60 s."""
        if self.gray_start <= 0:
            return False
        return int(now_ms or 0) - self.gray_start < GRAY_MS

    def enter_gray(self, now_ms):
        self.gray_start = int(now_ms or 0)

    def leave_gray(self):
        self.gray_start = 0

    def elapsed_ms(self, now_ms):
        """Time counted toward the next PK point: runTime + (now - lastTime)."""
        if not self.last_time:
            return self.run_time
        return self.run_time + max(int(now_ms or 0) - self.last_time, 0)

    def reset_recovery(self, now_ms):
        """resetRecoveryTime: start a fresh decay span from now."""
        self.last_time = int(now_ms or 0)
        self.run_time = 0

    def incr(self, amount):
        self.value = max(self.value + int(amount or 0), 0)

    def decr(self, amount):
        """decrPkValue: only from a positive value, clamped at 0."""
        if self.value > 0:
            self.value = max(self.value - int(amount or 0), 0)


class PvpWorld:
    """Process-wide PK/gray/protection state, like Java's per-role elements.

    A role's PK value and birth protection are stage-element state in Java and
    so are visible to every connection; this object gives our sessions the same
    view instead of a per-connection copy.
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.pk = {}             # role id -> PkState
        self.protect_until = {}  # role id -> epoch ms the birth buff ends

    def state(self, role_id, encoded=None, now_ms=0):
        """PkState for a role, seeded from its persisted pk_info once."""
        key = str(role_id)
        with self.lock:
            state = self.pk.get(key)
            if state is None:
                state = PkState.decode(encoded, now_ms)
                self.pk[key] = state
            return state

    def live(self, role_id):
        """The cached PkState for a role, or None when it was never loaded."""
        with self.lock:
            return self.pk.get(str(role_id))

    def forget(self, role_id):
        """Drop a role's live PK state (logout keeps the persisted copy)."""
        with self.lock:
            self.pk.pop(str(role_id), None)
            self.protect_until.pop(str(role_id), None)

    def protect(self, role_id, until_ms):
        with self.lock:
            self.protect_until[str(role_id)] = int(until_ms)

    def protected(self, role_id, now_ms):
        """True while the role still carries stage-entry birth protection."""
        with self.lock:
            until = self.protect_until.get(str(role_id))
        if not until:
            return False
        if int(now_ms or 0) >= until:
            with self.lock:
                self.protect_until.pop(str(role_id), None)
            return False
        return True

    def clear_protection(self, role_id):
        with self.lock:
            self.protect_until.pop(str(role_id), None)

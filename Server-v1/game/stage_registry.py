"""Server-wide stage registry: map id -> roles on it, their session, and tile position.

Lets one connection queue frames for another (cross-session pushes) and find the
surround of a role. Pushes never hold the registry lock while calling into a
session, and sessions take only their outbox lock, so no lock cycle forms.

Surround geometry (StageAoi, from dntg_start.jar and config/stage/csl-stage.properties):
the AOI grid is 600x400 px with cell index ``x / AOI_WIDTH + 1``, and a tile is
60 px wide and 30 px tall (see Session.tile pixels). The surround is the 3x3
block of cells around the role's cell (AOI.getElements(ROLE, 9)).

Stage copies (checkStageAndEnter): dungeon families run one stage object per
owner (per role for zuwu/juqing, per guild for guildfuben). The registry keys
live membership by stage key; the client-visible base map is unchanged.
Ordinary maps use the map id as its own stage key, so existing behavior holds.
Each non-trivial stage owns an isolated MonsterWorld (monsters, drops, ground,
leave/respawn queues); ordinary stages share the server-wide world.
"""
import threading

from .monster_world import MonsterWorld
from .pvp import PvpWorld

TILE_W = 60
TILE_H = 30
AOI_W = 600
AOI_H = 400


def aoi_cell(tile_x, tile_y):
    """AOI cell (col, row) of a tile position, in Java's 1-based grid."""
    px = int(tile_x) * TILE_W
    py = int(tile_y) * TILE_H
    return px // AOI_W + 1, py // AOI_H + 1


class StageRegistry:
    """Thread-safe role/map/session/position index shared by every game connection."""

    def __init__(self):
        self._lock = threading.Lock()
        self._maps = {}     # stage_key -> {role_id: session}
        self._where = {}    # role_id -> stage_key
        self._base = {}     # stage_key -> base map_id (client-visible)
        self._pos = {}      # role_id -> (tile_x, tile_y)
        self._presence = {} # role_id -> session (login, placed or not)
        self._worlds = {}   # stage_key -> MonsterWorld (non-trivial stages only)
        self.monsters = MonsterWorld()  # shared monster lifecycle for ordinary stages
        # PK value/gray/protection live on the Java stage role element, so
        # every connection reads the same copy; this is that shared copy.
        self.pvp = PvpWorld()

    # -- stage copies ----------------------------------------------------
    def create_instance(self, base_map, kind, owner):
        """Create (or reuse) a dungeon stage key for an owner on a base map."""
        base_map, kind, owner = str(base_map), str(kind), str(owner)
        key = '%s-%s-%s' % (kind, owner, base_map)
        with self._lock:
            self._base.setdefault(key, base_map)
            if key not in self._maps:
                self._maps[key] = {}
            if key not in self._worlds:
                self._worlds[key] = MonsterWorld()
        return key

    def stage_of(self, role_id):
        """Stage key a role is placed on, or None when it is not placed."""
        with self._lock:
            return self._where.get(str(role_id))

    def base_map_of_stage(self, stage_key):
        """Client-visible base map for a stage key (ordinary maps echo)."""
        with self._lock:
            if stage_key is None:
                return None
            return self._base.get(str(stage_key), str(stage_key))

    def monster_world_for(self, stage_key):
        """Isolated monster world for a stage; ordinary stages share one."""
        if stage_key is None:
            return self.monsters
        with self._lock:
            return self._worlds.get(str(stage_key), self.monsters)

    def destroy_instance_if_empty(self, stage_key):
        """Drop an empty non-trivial stage and its runtime entities."""
        if stage_key is None:
            return False
        key = str(stage_key)
        with self._lock:
            base = self._base.get(key)
            if base is None or base == key:
                return False
            if self._maps.get(key):
                return False
            self._maps.pop(key, None)
            self._base.pop(key, None)
            self._worlds.pop(key, None)
            return True

    def register(self, role_id, map_id, session, x=None, y=None, stage_key=None):
        """Place a role on a map under its session, relocating it if it moved."""
        role_id, map_id = str(role_id), str(map_id)
        key = str(stage_key) if stage_key is not None else map_id
        with self._lock:
            old = self._where.get(role_id)
            if old is not None and old != key:
                self._drop_locked(role_id, old)
            self._maps.setdefault(key, {})[role_id] = session
            self._where[role_id] = key
            self._base.setdefault(key, map_id)
            if key != map_id:
                self._base[key] = map_id
            if key not in self._worlds and key != map_id:
                self._worlds[key] = MonsterWorld()
            if x is not None and y is not None:
                self._pos[role_id] = (int(x), int(y))

    def set_position(self, role_id, x, y):
        """Record a role's tile position after a step; False when the role is not placed."""
        role_id = str(role_id)
        with self._lock:
            if role_id not in self._where:
                return False
            self._pos[role_id] = (int(x), int(y))
            return True

    def unregister(self, role_id):
        """Remove one role from the registry; True when it was present."""
        role_id = str(role_id)
        with self._lock:
            stage_key = self._where.pop(role_id, None)
            self._pos.pop(role_id, None)
            if stage_key is None:
                return False
            self._drop_locked(role_id, stage_key, forget=False)
            empty = not self._maps.get(stage_key)
            base = self._base.get(stage_key, stage_key)
            if empty and base != stage_key:
                self._maps.pop(stage_key, None)
                self._base.pop(stage_key, None)
                self._worlds.pop(stage_key, None)
            return True

    def unregister_session(self, session):
        """Remove every role owned by a disconnecting session."""
        with self._lock:
            owned = [r for r, m in self._where.items()
                     if self._maps.get(m, {}).get(r) is session]
            emptied = []
            for role_id in owned:
                stage_key = self._where.pop(role_id)
                self._drop_locked(role_id, stage_key)
                self._pos.pop(role_id, None)
                self._presence.pop(role_id, None)
                emptied.append(stage_key)
            for stage_key in emptied:
                base = self._base.get(stage_key, stage_key)
                if base != stage_key and not self._maps.get(stage_key):
                    self._maps.pop(stage_key, None)
                    self._base.pop(stage_key, None)
                    self._worlds.pop(stage_key, None)
            return len(owned)

    def peers(self, map_id, exclude_role=None):
        """Snapshot of (role_id, session) on a map, excluding one role."""
        exclude = None if exclude_role is None else str(exclude_role)
        with self._lock:
            members = list(self._maps.get(str(map_id), {}).items())
        return [(r, s) for r, s in members if r != exclude]

    def peers_in_stage(self, stage_key, exclude_role=None):
        """Snapshot of (role_id, session) sharing one stage copy."""
        return self.peers(stage_key, exclude_role=exclude_role)

    def roles_of(self, session):
        """Role ids currently placed under a session (the connection's own roles)."""
        with self._lock:
            return [r for r, m in self._where.items()
                    if self._maps.get(m, {}).get(r) is session]

    def session_of(self, role_id):
        """Session currently owning a role, or None when it is not placed."""
        role_id = str(role_id)
        with self._lock:
            stage_key = self._where.get(role_id)
            return self._maps.get(stage_key, {}).get(role_id) if stage_key else None

    def map_of(self, role_id):
        """Map a role is placed on (client-visible base map), or None."""
        with self._lock:
            stage_key = self._where.get(str(role_id))
            if stage_key is None:
                return None
            return self._base.get(stage_key, stage_key)

    def position_of(self, role_id):
        """Tile (x, y) of a placed role, or None."""
        with self._lock:
            pos = self._pos.get(str(role_id))
        if pos is None:
            return None
        try:
            return (int(pos[0]), int(pos[1]))
        except (TypeError, ValueError, IndexError):
            return None

    def mark_online(self, role_id, session):
        """Login presence (PublicRoleState): placed or not."""
        with self._lock:
            self._presence[str(role_id)] = session

    def mark_offline(self, role_id):
        """Drop login presence."""
        with self._lock:
            self._presence.pop(str(role_id), None)

    def presence_of(self, role_id):
        """Session of a logged-in role, or None (placement-independent)."""
        with self._lock:
            return self._presence.get(str(role_id))

    def surround(self, role_id):
        """(role_id, session) pairs in the 3x3 AOI block around a role, itself included."""
        role_id = str(role_id)
        with self._lock:
            stage_key = self._where.get(role_id)
            if stage_key is None:
                return []
            members = list(self._maps.get(stage_key, {}).items())
            here = self._pos.get(role_id)
            positions = {r: self._pos.get(r) for r, _ in members}
        if here is None:
            return [(r, s) for r, s in members if r == role_id]
        return self._block_members(positions, members, here)

    def surround_at(self, map_id, point):
        """(role_id, session) pairs in the 3x3 AOI block around a tile on a map."""
        with self._lock:
            members = list(self._maps.get(str(map_id), {}).items())
            positions = {r: self._pos.get(r) for r, _ in members}
        return self._block_members(positions, members, point)

    def surround_in_stage(self, stage_key, point):
        """(role_id, session) pairs around a tile within one stage copy."""
        return self.surround_at(stage_key, point)

    @staticmethod
    def _block_members(positions, members, here):
        """Members whose AOI cell lies within one cell of the tile `here`."""
        cx, cy = aoi_cell(*here)
        out = []
        for r, s in members:
            pos = positions.get(r)
            if pos is None:
                continue
            x, y = aoi_cell(*pos)
            if abs(x - cx) <= 1 and abs(y - cy) <= 1:
                out.append((r, s))
        return out

    def push(self, role_id, frames):
        """Queue frames on the session that owns a role; False when none is online."""
        session = self.session_of(role_id)
        if session is None:
            return False
        session.push_frames(frames)
        return True

    def _drop_locked(self, role_id, map_id, forget=True):
        """Remove a role from one map bucket; caller holds the lock."""
        bucket = self._maps.get(map_id)
        if bucket is not None:
            bucket.pop(role_id, None)
            if not bucket:
                base = self._base.get(map_id, map_id)
                if base == map_id:
                    self._maps.pop(map_id, None)
        if forget:
            self._where.pop(role_id, None)

"""Server-wide stage registry: map id -> roles on it, their session, and tile position.

Lets one connection queue frames for another (cross-session pushes) and find the
surround of a role. Pushes never hold the registry lock while calling into a
session, and sessions take only their outbox lock, so no lock cycle forms.

Surround geometry (StageAoi, from dntg_start.jar and config/stage/csl-stage.properties):
the AOI grid is 600x400 px with cell index ``x / AOI_WIDTH + 1``, and a tile is
60 px wide and 30 px tall (see Session.tile pixels). The surround is the 3x3
block of cells around the role's cell (AOI.getElements(ROLE, 9)).
"""
import threading

from .monster_world import MonsterWorld

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
        self._maps = {}     # map_id -> {role_id: session}
        self._where = {}    # role_id -> map_id
        self._pos = {}      # role_id -> (tile_x, tile_y)
        self.monsters = MonsterWorld()  # shared monster lifecycle for every session

    def register(self, role_id, map_id, session, x=None, y=None):
        """Place a role on a map under its session, relocating it if it moved."""
        role_id, map_id = str(role_id), str(map_id)
        with self._lock:
            old = self._where.get(role_id)
            if old is not None and old != map_id:
                self._drop_locked(role_id, old)
            self._maps.setdefault(map_id, {})[role_id] = session
            self._where[role_id] = map_id
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
            map_id = self._where.pop(role_id, None)
            self._pos.pop(role_id, None)
            if map_id is None:
                return False
            self._drop_locked(role_id, map_id, forget=False)
            return True

    def unregister_session(self, session):
        """Remove every role owned by a disconnecting session."""
        with self._lock:
            owned = [r for r, m in self._where.items()
                     if self._maps.get(m, {}).get(r) is session]
            for role_id in owned:
                self._drop_locked(role_id, self._where.pop(role_id))
                self._pos.pop(role_id, None)
            return len(owned)

    def peers(self, map_id, exclude_role=None):
        """Snapshot of (role_id, session) on a map, excluding one role."""
        exclude = None if exclude_role is None else str(exclude_role)
        with self._lock:
            members = list(self._maps.get(str(map_id), {}).items())
        return [(r, s) for r, s in members if r != exclude]

    def roles_of(self, session):
        """Role ids currently placed under a session (the connection's own roles)."""
        with self._lock:
            return [r for r, m in self._where.items()
                    if self._maps.get(m, {}).get(r) is session]

    def session_of(self, role_id):
        """Session currently owning a role, or None when it is not placed."""
        role_id = str(role_id)
        with self._lock:
            map_id = self._where.get(role_id)
            return self._maps.get(map_id, {}).get(role_id) if map_id else None

    def surround(self, role_id):
        """(role_id, session) pairs in the 3x3 AOI block around a role, itself included."""
        role_id = str(role_id)
        with self._lock:
            map_id = self._where.get(role_id)
            if map_id is None:
                return []
            members = list(self._maps.get(map_id, {}).items())
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
                self._maps.pop(map_id, None)
        if forget:
            self._where.pop(role_id, None)

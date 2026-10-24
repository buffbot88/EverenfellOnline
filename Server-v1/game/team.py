"""In-memory party/team graph (TeamServiceImpl DataContainer regions).

Java keeps teams in the game-server DataContainer (regions ``team``,
``role_team`` and ``map_team``): nothing is persisted to MySQL, so a
server restart drops every team. This store mirrors that lifecycle with
plain dicts under one lock: no SQLite rows, teardown on process exit.

Shapes mirror the Java models: a team holds its leader, the leader's
map (the map bucket the team id is listed under), an optional pending
next-leader (leadership-transfer handshake) and a member map of role
id -> join millisecond; a role entry snapshots the member card.
"""
import threading
import time


def now_ms():
    """System.currentTimeMillis for join stamps."""
    return int(time.time() * 1000)


class TeamState:
    """Thread-safe team/role_team/map_team regions shared by sessions."""

    def __init__(self):
        self.lock = threading.RLock()
        self.teams = {}       # team_id -> team dict
        self.role_team = {}   # role_id -> role dict
        self.map_teams = {}   # map_id -> [team_id]
        self._seq = 0

    def next_team_id(self):
        """IdUtil.nextString('T'): unique T-prefixed team id."""
        with self.lock:
            self._seq += 1
            return 'T%d%d' % (now_ms(), self._seq)

    # -- role region ----------------------------------------------------
    def get_role_team(self, role_id):
        """RoleTeamData snapshot for a role, or None when teamless."""
        with self.lock:
            entry = self.role_team.get(str(role_id))
            return dict(entry) if entry is not None else None

    def put_role_team(self, entry):
        """Store a RoleTeamData snapshot keyed by its role id."""
        with self.lock:
            self.role_team[str(entry['role_id'])] = dict(entry)

    def remove_role_team(self, role_id):
        """Drop a role entry; True when one existed."""
        with self.lock:
            return self.role_team.pop(str(role_id), None) is not None

    # -- team region ----------------------------------------------------
    def get_team(self, team_id):
        """Live team dict (mutations persist) or None."""
        with self.lock:
            return self.teams.get(str(team_id))

    def put_team(self, team):
        """Store a team dict under its team id."""
        with self.lock:
            self.teams[str(team['team_id'])] = team

    def remove_team(self, team_id):
        """Drop a team; True when one existed."""
        with self.lock:
            return self.teams.pop(str(team_id), None) is not None

    # -- map region -----------------------------------------------------
    def get_map_teams(self, map_id):
        """Team ids listed under a map (a copy)."""
        with self.lock:
            return list(self.map_teams.get(str(map_id), []))

    def add_map_team(self, map_id, team_id):
        """List a team id under a map (no duplicates)."""
        with self.lock:
            bucket = self.map_teams.setdefault(str(map_id), [])
            if str(team_id) not in bucket:
                bucket.append(str(team_id))

    def remove_map_team(self, map_id, team_id):
        """Unlist a team id from a map; True when one was listed."""
        with self.lock:
            bucket = self.map_teams.get(str(map_id))
            if not bucket or str(team_id) not in bucket:
                return False
            bucket.remove(str(team_id))
            return True

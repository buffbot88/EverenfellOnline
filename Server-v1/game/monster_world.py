"""Shared monster world: one authoritative state for every session on a server.

Monster ids are map-scoped (m_<map>_<n>), so one world keyed by id covers every
map. Sessions bind their monster dicts to this object, so HP, death, hatred,
leave and respawn are seen the same way by every connection. The world ticks
once per server round (see claim_round), not once per session.
"""
import threading


class MonsterWorld:
    """Monster HP, dead set, registry, hatred, leave/respawn queues and a lock."""

    def __init__(self):
        self.lock = threading.RLock()
        self.reg = {}           # monster id -> {template, map, born, pos}
        self.hp = {}            # monster id -> current HP (float)
        self.dead = set()       # ids that have died (never re-seeded alive)
        self.hatred = {}        # monster id -> attacker fighter id
        self.leaving = {}       # dead id -> ticks until the 24002 leave
        self.spawning = []      # [template_id, map, born, ticks] until 23002
        self.respawn_next = {}  # map id -> next fresh-id index
        self._driven = False    # True once a scheduler has started rounds
        self._round = 0
        self._claimed = -1

    def begin_round(self):
        """Start one server tick round; the next claim_round() may run the world."""
        with self.lock:
            self._driven = True
            self._round += 1

    def claim_round(self):
        """True for exactly one caller per round (undriven worlds always grant)."""
        with self.lock:
            if not self._driven:
                return True
            if self._claimed == self._round:
                return False
            self._claimed = self._round
            return True

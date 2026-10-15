"""In-process event bus: EventCenter / EventType / HandlerNode mirror.

Provenance (all from ``dntg_start.jar`` via ``tools/javap.py``):
- ``EventCenter.subscribe(type, order, handler)`` finds or creates the
  ``EventType`` for the type string and adds a handler node.
- ``EventType.subscribe`` adds a ``HandlerNode(handler, handleOrder)`` and
  re-sorts ascending by handle order (``EventType$1.compare``).
- ``EventType.publish`` runs every handler in order under the type's monitor
  with ``handle(source, data)``. A handler exception is isolated: role_logout
  goes to ``XianlingLog.offlineError`` and every other type to
  ``XianlingLog.frameError`` with the message ``eventType:{},handler:{}
  handle error! {}``; the loop continues with the next handler.
- ``EventCenter.publish`` looks the type up and is a no-op when nothing
  subscribed to it.

Approximations: the Java monitor becomes a per-type lock. Equal handle orders
keep subscription order (Java's comparator is not a total order on ties).
"""
import logging
import threading

log = logging.getLogger(__name__)

ROLE_LOGOUT = 'role_logout'


class Event:
    """IEvent: type, source (rource in Java), and payload."""

    def __init__(self, event_type, source=None, data=None):
        self.type = str(event_type)
        self.source = source
        self.data = data


class _HandlerNode:
    """EventType$HandlerNode: a handler and its ordering key."""

    def __init__(self, handler, order):
        self.handler = handler
        self.order = int(order)


class EventType:
    """One named event: ordered handler nodes, publish isolates failures."""

    def __init__(self, event_type):
        self.event_type = event_type
        self._nodes = []
        self._lock = threading.Lock()

    def subscribe(self, order, handler):
        """Add a handler and keep the nodes sorted ascending by order."""
        with self._lock:
            self._nodes.append(_HandlerNode(handler, order))
            self._nodes.sort(key=lambda node: node.order)

    def handler_count(self):
        """Number of subscribed handlers (test hook)."""
        return len(self._nodes)

    def publish(self, event):
        """Run every handler in order; a failing handler is logged and skipped."""
        with self._lock:
            for node in list(self._nodes):
                try:
                    node.handler.handle(event.source, event.data)
                except Exception as exc:
                    if event.type == ROLE_LOGOUT:
                        log.warning('offline error on %s: %s', event.source, exc)
                    else:
                        log.warning('eventType:%s,handler:%s handle error! %s',
                                    self.event_type, type(node.handler).__name__,
                                    exc)


class EventCenter:
    """Map of event type -> EventType; publish is silent without subscribers."""

    def __init__(self):
        self._types = {}
        self._lock = threading.Lock()

    def subscribe(self, event_type, order, handler):
        """Subscribe a handler to a type string, creating the type on demand."""
        with self._lock:
            etype = self._types.get(event_type)
            if etype is None:
                etype = EventType(event_type)
                self._types[event_type] = etype
        etype.subscribe(order, handler)

    def publish(self, event):
        """Publish an Event to its type's handlers (no-op when none exist)."""
        with self._lock:
            etype = self._types.get(event.type)
        if etype is not None:
            etype.publish(event)

    def subscriber_count(self, event_type):
        """Handlers subscribed to a type (test hook)."""
        with self._lock:
            etype = self._types.get(event_type)
        return etype.handler_count() if etype is not None else 0

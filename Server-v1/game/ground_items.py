"""Authoritative ground items dropped by monsters (Java Goods element and StageContainer).

Verified Java rules (dntg_start.jar bytecode):
- A drop is an ItemModel in StageContainer.goodsMap (global, keyed by item id).
- StageServiceImpl.goodsEnterStage turns each id into a Goods element, sets the
  expiry from MonsterConfig.getDropGoodsDuration (dropitemlast, seconds) and
  enters it on the stage.
- Placement is AoiStage.getSurroundValidPoint(point, true, GOODS): the monster
  tile when free, else the first free surround in AExtend order; no path node
  means the item is skipped (see config.surround_valid_point_for_goods).
- Monster drops are always owner-protected (formatDrop's constant 1): the
  killer role id owns the item and the killer team shares it.
- Goods.checkIdentity: after 20 seconds from drop time anyone may pick it up.
  Before that, a null owner is open to everyone; otherwise the owner id or the
  owner's team id must match.
- Expiry is scheduled as S:GOODS_DIS (StageServiceImpl.goodsDisappear) and
  removes the element once.

Client wire (AoiMsgListener + AbsAoiMsgListener bytecode):
- Appearance is 23004 [Goods.getMsgData] to the item's surround (enter).
- Disappearance (pickup leave, expiry, S:GOODS_DIS) is 24004 [itemId].
- S:DROP_GOODS / S:GOODS_DIS are internal stage messages (StageMsgQueue
  StageMsg -> send2StageInner -> goodsEnterStage/goodsDisappear), never
  client packets.

Ids: Java builds them as 'goods_' + IdUtil.nextString (AiServiceImpl
  goodsPrefix), an opaque unique string the client echoes back in C:30103.
  Ours are process-unique 'g<N>' strings under the same contract (unique,
  echoed verbatim); the Id suffix scheme itself is unverified.
"""
import threading

OWNER_WINDOW_MS = 20000
DEFAULT_DURATION_SECONDS = 60


class GroundItem:
    """One dropped item on a map."""

    def __init__(self, item_id, goods_id, count, map_id, x, y, drop_time_ms,
                 owner_id=None, owner_team_id=None, duration_seconds=DEFAULT_DURATION_SECONDS,
                 bind=0):
        self.id = item_id
        self.goods_id = goods_id
        self.count = count
        self.map_id = map_id
        self.x = x
        self.y = y
        self.drop_time_ms = drop_time_ms
        self.owner_id = owner_id
        self.owner_team_id = owner_team_id
        self.expires_at_ms = drop_time_ms + duration_seconds * 1000
        # ItemModel.bind: 0 for ordinary monster drops (DropRule.isBind is
        # false when the drop cell carries no bind marker, and hpadd002's
        # obtainLocked is 0, so ItemCreatorServiceImpl.getBind yields 0).
        # canStack compares it, so it travels with the item to the bag.
        self.bind = bind


def can_pick_up(item, role_id, role_team_id, now_ms):
    """Goods.checkIdentity: whether a role may pick up this item right now."""
    if now_ms - item.drop_time_ms > OWNER_WINDOW_MS:
        return True
    if item.owner_id is None:
        return True
    if role_id == item.owner_id:
        return True
    return item.owner_team_id is not None and item.owner_team_id == role_team_id


class GroundItemStore:
    """Thread-safe registry of ground items, keyed by a unique item id."""

    def __init__(self):
        self.lock = threading.RLock()
        self._items = {}
        self._next = 1

    def add(self, goods_id, count, map_id, x, y, now_ms, owner_id=None,
            owner_team_id=None, duration_seconds=DEFAULT_DURATION_SECONDS,
            bind=0):
        """Create one item with a fresh id and return it."""
        with self.lock:
            item_id = 'g%d' % self._next
            self._next += 1
            item = GroundItem(item_id, goods_id, count, map_id, x, y, now_ms,
                              owner_id, owner_team_id, duration_seconds, bind)
            self._items[item_id] = item
            return item

    def get(self, item_id):
        with self.lock:
            return self._items.get(item_id)

    def remove(self, item_id):
        """Remove an item once; returns it, or None when already gone.

        The one-shot claim behind pickup: whichever session pops the item
        owns it, so two simultaneous pickups cannot both succeed.
        """
        with self.lock:
            return self._items.pop(item_id, None)

    def restore(self, item):
        """Put a claimed item back under its original id (bag-write rollback).

        Returns True when the slot was free; False leaves the store
        untouched when something already holds the id.
        """
        with self.lock:
            if item.id in self._items:
                return False
            self._items[item.id] = item
            return True

    def expire(self, now_ms):
        """Remove every item whose lifetime has ended; returns the removed items."""
        with self.lock:
            gone = [i for i in self._items.values() if now_ms >= i.expires_at_ms]
            for item in gone:
                del self._items[item.id]
            return gone

    def on_map(self, map_id):
        with self.lock:
            return [i for i in self._items.values() if i.map_id == map_id]

    def __len__(self):
        with self.lock:
            return len(self._items)

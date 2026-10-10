"""Monster and pet AI ticks, recovered from the jar via tools/javap.py.

Provenance (shapes/order verified against output/orig-stack/tap-decoded.txt):
- AiFightServiceImpl.defaultHandle: refreshState (XUNLUO -> FIGHT on hatred,
  FIGHT -> BACK when hatred clears, BACK -> XUNLUO at born + hatred clear),
  then FIGHT monsters pick a skill + hatredest target and monsterReadyForFire.
- monsterReadyForFire -> FightOutputWrapper.skillReady Object[7]:
  [1, monsterId, category, targetPixel(int[]), None, 1, roleId]. The pixel is
  the target's tile scaled (role tile 44,33 -> [2640, 990], i.e. x*60, y*30).
- AiFightServiceImpl.move: A* toward the target, one step (path[1]), then
  AiFightOutput.move 40000 [x, y, bornFlag, 6, monsterId] (bornFlag 0 at born
  else 1; the capture's just-spawned movers show 0, chasers show 1).
- Monster.deadHandle: deadDrop + scheduleDisappearHandle, which schedules
  'AI:RETRIEVE' after disappearDuration SECONDS; AiServiceImpl.retrieve then
  recycles the element through the produce team, which emits the AOI leave
  (24002 [[deadId]]). GuaiWuBiao.asheslast (D040011: 3) is the corpse delay;
  creattime (D040011: 5) re-produces the spawn as a 23002 record with the
  respawn flag set (index 15 True; entry spawns show False).
- PetFightServiceImpl.skillExecute: the same fight pipeline as roles
  (chooseTargets/confirmTargets/fight) against the owner's hatred target; the
  pet's 42001 ready carries a path like a role's and a null target
  ([1, petId, 'zuoqi11', [px, py], [[...]], 1, None]). Pet tile steps are
  40000 [x, y, flag, 2, petId] (element-type slot 2, not the monster 6).
- Aggro comes from MonsterHatredManager (fireAttackedEvent on damage plus
  eyeshot presence; D040011 eyeshot 5, maxrange 9, ifactive 1, velocity 450).

Approximations (all logged where they bite): one ai_tick() call advances
both combat and a 1-second clock (Java runs HeartBeatRate(velocity) /
XUNLUO_PERIOD+roll(5000) scheduler ticks; without a server loop the tick is
driven inline off role actions instead, which the capture's interleaving --
a few monster swings per role swing -- supports). A* degrades to a greedy
walkable step on the path.mm grid; tile->pixel is x*60/y*30; pet ready paths
are a single straight-line waypoint (Java sends the A* path). The 42001
hit-flag roleId on monster readies is the hatred target's role id.
"""

MONSTER_SKILL = 'monster06'
PET_SKILL = 'zuoqi11'

# 40000 element-type slot: monsters send 6, pets send 2 (capture).
MOVE_KIND_MONSTER = 6
MOVE_KIND_PET = 2


def chebyshev(a, b):
    """Tile distance in king moves."""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def in_aggro(mon_pos, role_pos, eyeshot):
    """Presence aggro: role within eyeshot tiles (MonsterHatredManager)."""
    try:
        return chebyshev(mon_pos, role_pos) <= int(eyeshot)
    except (TypeError, ValueError):
        return False


def tile_to_pixel(tile):
    """Tile -> pixel for 42001 ready positions (44,33 -> [2640, 990])."""
    return [int(tile[0]) * 60, int(tile[1]) * 30]


def step_toward(src, dst, walkable):
    """Greedy one-step chase (AStarUtil.findPath path[1] degraded).

    Returns the walkable 8-neighbour cell closest to dst, or None when src
    already equals dst or nothing walkable is nearer. Diagonal steps count
    one, like a king move on the grid.
    """
    if tuple(src) == tuple(dst):
        return None
    best = None
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if not dx and not dy:
                continue
            cell = (src[0] + dx, src[1] + dy)
            if not walkable(cell[0], cell[1]):
                continue
            if best is None or chebyshev(cell, dst) < chebyshev(best, dst):
                best = cell
    if best is None or chebyshev(best, dst) >= chebyshev(src, dst):
        return None
    return [best[0], best[1]]


def tile_move_frame(actor_id, pos, at_born, kind=6):
    """AiFightOutput.move 40000 [x, y, bornFlag, kind, actorId]."""
    return ['40000', [int(pos[0]), int(pos[1]), 0 if at_born else 1, kind,
                      actor_id]]


def skill_ready_frame(actor_id, category, pixel, path, target):
    """FightOutputWrapper.skillReady 42001 Object[7] broadcast."""
    return ['42001', [1, actor_id, category, [int(pixel[0]), int(pixel[1])],
                      path, 1, target]]


def respawn_record(new_id, template, pos):
    """23002 single-record re-enter for a reproduced monster (flag True).

    Layout matches config.monster_snapshot; index 15 (the respawn marker)
    is True where entry spawns carry False.
    """
    hp = template.get('hitpoints')
    mp = template.get('mana')
    speed = template.get('velocity')
    return [new_id, template.get('id'), template.get('name'),
            template.get('level'), hp, hp, mp, mp, speed, speed,
            0, int(pos[0]), int(pos[1]), 0, None, True, None, 0]

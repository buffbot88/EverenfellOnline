"""Monster direct-item drop evaluation (AiServiceImpl.monsterGoodsDrop / calDropRule).

Pure logic: no packets, no ground items, no inventory writes. A rule resolves to a
structured result that the caller can place on the ground once that path is verified.

Java semantics reproduced here (dntg_start.jar bytecode):
- Slot keys: drop<N> (item id), drop<N>odds (float rate), drop<N>sp (flag string).
  Only N in 1..20 is read (createDropRules).
- An id starting with '@' is a zubao group, not a direct item. Groups are out of scope.
- Lottery.roll(rate, TENTHOUSAND): fires when rate > 0 and
  nextInt(10000) <= (int)(rate * 10000). Note the inclusive bound.
- A direct item always drops count 1 (dropCal/calDropRule builds ItemParamVo(id, 1, bind)).
- Level gate (calNormalDropRule): skipped when roleLevel - monsterLevel > levelDifference,
  where levelDifference comes from DiaoLuoShuaiJianBiao keyed by monstertype.
- Daily limit: calDropRule applies it only when BOTH the monster flag
  (countlimit != 0) and the goods flag (goods count > 0) are set. The daily count needs
  per-role state that is not persisted, so when the gate applies it returns an explicit
  unsupported outcome instead of rolling.
"""
import struct


LOTTERY_TENTHOUSAND = 10000
DROP_SLOTS = range(1, 21)

OUTCOME_DROPPED = 'dropped'
OUTCOME_MISSED = 'missed'
OUTCOME_SKIPPED_LEVEL = 'skipped_level'
OUTCOME_UNSUPPORTED = 'unsupported'


def f32(value):
    """Round a Python float to float32, matching Java's float arithmetic."""
    return struct.unpack('>f', struct.pack('>f', float(value)))[0]


def lottery_threshold(rate):
    """(int)(rate * 10000) for a float32 rate, as Lottery.roll(float, Lottery) computes it."""
    return int(f32(f32(rate) * LOTTERY_TENTHOUSAND))


def lottery_fires(rate, roll):
    """Lottery.roll(rate, TENTHOUSAND) with the random draw injected.

    `roll` is the value Random.nextInt(10000) would return (0..9999).
    """
    if not rate or rate <= 0:
        return False
    return roll <= lottery_threshold(rate)


def direct_slots(template):
    """Direct-item drop slots of a monster template, in slot order.

    Returns dicts {slot, goods_id, odds, flags}. Zubao groups ('@...') and empty
    slots are excluded here; the caller decides how to report them.
    """
    slots = []
    for n in DROP_SLOTS:
        goods = template.get('drop%d' % n)
        if goods is None or str(goods).strip() == '':
            continue
        goods = str(goods)
        if goods.startswith('@'):
            continue
        odds = template.get('drop%dodds' % n)
        slots.append({
            'slot': n,
            'goods_id': goods,
            'odds': float(odds) if odds not in (None, '') else 0.0,
            'flags': str(template.get('drop%dsp' % n) or ''),
        })
    return slots


def level_gate_open(role_level, monster_level, level_difference):
    """calNormalDropRule: drop only when roleLevel - monsterLevel <= levelDifference."""
    return (int(role_level) - int(monster_level)) <= int(level_difference)


def daily_limit_applies(monster_count_limit, goods_count):
    """calDropRule's daily gate: monster countlimit != 0 AND goods count > 0.

    Java object2int maps blank or unparseable values to 0, so `None` and '' give 0.
    """
    return _int_or_zero(monster_count_limit) != 0 and _int_or_zero(goods_count) > 0


def _int_or_zero(value):
    """ConvertObjectUtil.object2int: blank or unparseable is 0."""
    try:
        return int(str(value).strip()) if value not in (None, '') else 0
    except ValueError:
        return 0


def evaluate_direct_drop(template, slot, *, role_level, level_difference,
                         daily_limit=False, roll):
    """Evaluate one direct-item slot of a monster for one killer.

    Returns a structured dict: outcome, goods_id, count, slot. `roll` is the injected
    Random.nextInt(10000) draw. Gates run in Java order: level gate, daily limit,
    then the lottery. A gate that cannot be evaluated is reported as unsupported.
    """
    base = {'slot': slot['slot'], 'goods_id': slot['goods_id'], 'count': 1}
    if slot.get('flags'):
        return dict(base, outcome=OUTCOME_UNSUPPORTED, count=0,
                    reason='slot flags %r not yet verified' % slot['flags'])
    if not level_gate_open(role_level, template.get('level') or 0, level_difference):
        return dict(base, outcome=OUTCOME_SKIPPED_LEVEL, count=0)
    if not lottery_fires(slot['odds'], roll):
        return dict(base, outcome=OUTCOME_MISSED, count=0)
    # calDropRule checks the daily gate only after the lottery succeeds.
    if daily_limit:
        return dict(base, outcome=OUTCOME_UNSUPPORTED, count=0,
                    reason='daily drop limit applies; per-role daily state is unported')
    return dict(base, outcome=OUTCOME_DROPPED)

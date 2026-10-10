"""Stage buff wire shapes for 42100/42102, ported from jar bytecode.

42100 (FightOutputWrapper.buffChange): [fighterId, addBuffInfos, removeBuffIds]
where both buff lists are null when empty (BuffStatistics returns null for a
null/empty list) and cleared after every flush -- which is why combat rounds
carry [fighterId, None, None] while the stage-entry flush carries the role's
8 live buffs (capture: vip, pools, exp-folds, birthprotect).

Buff.getClientMsg (5 slots): [id, buffId, remainingMs, layer, attackerId];
remaining is duration-(now-start) for timed buffs, -1 for permanent ones
(vip010 has no lasttime, hence the captured -1.0).
PropBuff.getClientMsg (6 slots): [id, buffId, remainingOrValue, layer,
attackerId, timedFlag]; timed buffs (expfolds, lasttime 3600000) show the
remaining ms with flag 0, value buffs (xuechi/lanchi pools, no lasttime) show
the pool value with flag 1 and tick it via 42102.
42102 (FightOutputWrapper.buffValueChange): [ownerId, propBuffId, poolValue].

AMF3 number discipline: Java Longs arrive as doubles (captured 288103.0,
-1.0) and Integers as ints (layer 1, flag 0/1), so durations/values go out
as float() and layer/flag as int().
"""


def dynamic_cd(cdtime_ms, gongjisudu):
    """PublicCdManager.toDynamicCd: int(cdTime / (1 + gongJiSuDu/2000)).

    Golden: cdtime 700 (CdBiao t070) with the captured role's live 147.4
    attack speed gives 651, the captured 42005 value, in float32 and float64.
    """
    return int(float(cdtime_ms) / (1.0 + float(gongjisudu) / 2000.0))


def timed_buff(instance_id, buff_id, remaining_ms, layer=1, attacker_id=None):
    """One Buff.getClientMsg entry; remaining None renders permanent (-1.0)."""
    remaining = -1.0 if remaining_ms is None else float(remaining_ms)
    return [str(instance_id), str(buff_id), remaining, int(layer),
            attacker_id]


def prop_buff(instance_id, buff_id, remaining_ms, value, layer=1,
              attacker_id=None):
    """One PropBuff.getClientMsg entry (timed flag 0, value flag 1)."""
    timed = remaining_ms is not None and float(remaining_ms) > 0
    shown = float(remaining_ms) if timed else float(value)
    return [str(instance_id), str(buff_id), shown, int(layer), attacker_id,
            0 if timed else 1]


def buff_change(fighter_id, adds=None, removes=None):
    """42100 payload; empty lists stay null (BuffStatistics semantics)."""
    return ['42100', [str(fighter_id), list(adds) if adds else None,
                      list(removes) if removes else None]]


def buff_value(owner_id, instance_id, value):
    """42102 payload: a pool buff's live value (xuechi regen ticks)."""
    return ['42102', [str(owner_id), str(instance_id), float(value)]]

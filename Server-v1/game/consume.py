"""Skill resource consumption, ported from ConsumeCalRule* (isolated).

Evidence (javap of the shipped jar, output/javap-extract):
- SkillConsumes <clinit>: CONSUME_TYPE_EMPTY=0, CONSUME_TYPE_MP=1,
  CONSUME_TYPE_TILI=2, CONSUME_TYPE_MP_PERCENT=4.
- ConsumeCalRuleFactory: maps those four types to the four rule classes.
- ConsumeCalRuleMp.isSatify: curMp >= consume1 (float32 compare).
  execute: IBuffService._222SpecialEffectHandler(fighter, 0f, consume1).
- ConsumeCalRuleMpPercent.isSatify: curMp >= maxMp * consume1 (float32).
  execute: _222SpecialEffectHandler(fighter, consume1, 0f).
- ConsumeCalRuleTiLi.isSatify: tiLi >= (int) consume1.
  execute: RoleFightAttribute.decrTiLi((int) consume1); tiLi -= n, clamped
  to 0 when negative. No broadcast.
- ConsumeCalRuleEmpty: isSatify always true; execute does nothing.
- BuffServiceImpl._222SpecialEffectHandler(fighter, pct, flat): returns unless
  pct > 0 or flat > 0. newMp = curMp - (maxMp * pct + flat), clamped to 0
  when <= 0, then setCurMp and FightOutputWrapper.outputAttributeChange.

All MP arithmetic is float32. The MP rules use the same formula with only the
pct/flat roles swapped, so the Mp rule is a flat cost and the MpPercent rule
a fraction of max MP.

This module is pure state. The attribute-change broadcast is produced by the
caller through the `on_attribute_change` callback, not built here.
"""

from .cooldown import f32

CONSUME_TYPE_EMPTY = 0
CONSUME_TYPE_MP = 1
CONSUME_TYPE_TILI = 2
CONSUME_TYPE_MP_PERCENT = 4


def _consume_value(skill):
    """SkillConfig.getConsume1 as a float32 (missing or blank -> 0)."""
    raw = skill.get('config', {}).get('consume1')
    try:
        return f32(float(raw)) if raw not in (None, '') else f32(0.0)
    except (TypeError, ValueError):
        return f32(0.0)


def is_satisfied(consume_type, fighter, skill):
    """ISkillConsume.isSatify for the given consume type."""
    value = _consume_value(skill)
    if consume_type == CONSUME_TYPE_MP:
        return f32(fighter['cur_mp']) >= value
    if consume_type == CONSUME_TYPE_MP_PERCENT:
        return f32(fighter['cur_mp']) >= f32(f32(fighter['max_mp']) * value)
    if consume_type == CONSUME_TYPE_TILI:
        return int(fighter['tili']) >= int(value)
    if consume_type == CONSUME_TYPE_EMPTY:
        return True
    return False


def special_effect_mp(fighter, pct, flat, on_attribute_change=None):
    """BuffServiceImpl._222SpecialEffectHandler on a fighter dict.

    Returns the new current MP, or None when both values are non-positive
    (no state change, no broadcast).
    """
    if not (f32(pct) > 0 or f32(flat) > 0):
        return None
    cur = f32(fighter['cur_mp'])
    cost = f32(f32(f32(fighter['max_mp']) * f32(pct)) + f32(flat))
    new_mp = f32(cur - cost)
    if new_mp <= 0:
        new_mp = f32(0.0)
    fighter['cur_mp'] = new_mp
    if on_attribute_change is not None:
        on_attribute_change(fighter)
    return new_mp


def consume(consume_type, fighter, skill, on_attribute_change=None):
    """Apply one consume rule's execute() after isSatify has passed.

    Returns True when a resource changed. Insufficient resources are rejected
    by the caller via is_satisfied(); this function does not re-check them.
    """
    value = _consume_value(skill)
    if consume_type == CONSUME_TYPE_MP:
        return special_effect_mp(fighter, 0.0, value, on_attribute_change) is not None
    if consume_type == CONSUME_TYPE_MP_PERCENT:
        return special_effect_mp(fighter, value, 0.0, on_attribute_change) is not None
    if consume_type == CONSUME_TYPE_TILI:
        amount = int(value)
        tili = int(fighter['tili']) - amount
        fighter['tili'] = tili if tili >= 0 else 0
        return True
    return False

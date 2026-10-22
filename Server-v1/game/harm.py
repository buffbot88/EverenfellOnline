"""HP change from one harm value, ported from SkillProcessHelper.acceptHarm (isolated).

Evidence (javap of the shipped jar, output/javap-extract):
- SkillProcessHelper.acceptHarm(IHarm, IFighter): returns null when the harm is
  null or its val is <= 0 (no state change). Otherwise curHp is read as float32,
  changed by val (converted with i2f), and written back. Healing types add,
  all others subtract. No clamp and no death check happen here; the bytecode
  shows neither.
- HarmType.isZhiLiaoHarmType: true for ZHILIAO and ZHILIAOBAOJI only.

Death detection, minimum HP, and the attribute broadcast are not in this
function. They are separate steps and are not ported here.
"""

from .cooldown import f32

HEALING_HARM_TYPES = frozenset({'ZHILIAO', 'ZHILIAOBAOJI'})


def is_healing(harm_type):
    """HarmType.isZhiLiaoHarmType."""
    return harm_type in HEALING_HARM_TYPES


def accept_harm(fighter, harm_type, val):
    """SkillProcessHelper.acceptHarm on a fighter dict.

    Returns a change record {'fighter', 'cur_hp'} when HP was written, or None
    when val <= 0 (no state change).
    """
    if val is None or int(val) <= 0:
        return None
    amount = f32(int(val))
    current = f32(fighter['cur_hp'])
    if is_healing(harm_type):
        new_hp = f32(current + amount)
    else:
        new_hp = f32(current - amount)
    fighter['cur_hp'] = new_hp
    return {'fighter': fighter.get('id'), 'cur_hp': new_hp}

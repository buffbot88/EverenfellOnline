"""Skill readiness state, ported from SkillManager (isolated; not wired to dispatch).

Evidence (javap of the shipped jar, output/javap-extract):
- SkillConfigExportServiceImpl: setLastingSkill(skillnum > 1), i.e. the
  JiNengBiao column `skillnum`, true only when its integer value is above 1.
  Blank or missing skillnum is false.
- SkillConfigExportServiceImpl: setWaveNum(jinengboshu if > 0 else 1).
- ConvertObjectUtil.object2int: a missing/blank/unparseable value is 0.
- SkillManager.setReadyForFire: readyForFireSkillMap.put(category, new
  SkillStatus(now)); if the skill is lasting, lastingSkill = that skill
  INSTANCE. A later non-lasting prepare does not clear lastingSkill.
- SkillManager.isReadyForFire: if skill == lastingSkill (reference compare)
  return true; otherwise the category entry must exist and
  now - fireTime >= casttime.

Times are integer milliseconds. Cooldown, resource cost and cleanup are not
modelled here (their bytecode is not yet fully decoded).
"""


def object2int(value):
    """Java ConvertObjectUtil.object2int: missing, blank or unparseable -> 0."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return 0
    if text == 'true':
        return 1
    if text == 'false':
        return 0
    head = text.split('.', 1)[0]
    try:
        return int(head)
    except ValueError:
        return 0


def wave_num(jinengboshu):
    """SkillConfigExportServiceImpl: jinengboshu when > 0, else 1."""
    n = object2int(jinengboshu)
    return n if n > 0 else 1


def is_lasting(config):
    """SkillConfigExportServiceImpl: skillnum > 1 (blank/missing is not lasting)."""
    return object2int(config.get('skillnum')) > 1


class SkillStatus:
    """One prepared skill: category, fire time (ms), remaining waves."""

    __slots__ = ('category', 'fire_time_ms', 'remain_wave_num')

    def __init__(self, category, fire_time_ms, jinengboshu=None):
        self.category = category
        self.fire_time_ms = int(fire_time_ms)
        self.remain_wave_num = wave_num(jinengboshu)


class SkillReadiness:
    """Per-fighter readiness map keyed by skill category, plus the lasting instance."""

    def __init__(self):
        self._by_category = {}
        self._lasting = None

    def set_ready(self, skill, now_ms):
        """Store a SkillStatus for the skill's category, replacing any earlier one."""
        cfg = skill.get('config', {})
        status = SkillStatus(skill['category'], now_ms, cfg.get('jinengboshu'))
        self._by_category[skill['category']] = status
        if is_lasting(cfg):
            self._lasting = skill
        return status

    def get(self, category):
        """The SkillStatus for a category, or None."""
        return self._by_category.get(category)

    def is_ready(self, skill, now_ms):
        """SkillManager.isReadyForFire: lasting instance (identity), or elapsed >= casttime."""
        if self._lasting is not None and skill is self._lasting:
            return True
        status = self._by_category.get(skill['category'])
        if status is None:
            return False
        casttime = object2int(skill.get('config', {}).get('casttime'))
        return int(now_ms) - status.fire_time_ms >= casttime

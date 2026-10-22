"""Skill fire (42002) coordinator, isolated from live dispatch.

Evidence (javap of the shipped jar, output/javap-extract):
- FightServiceImpl.skillFire, in order:
    1. stage and fighter lookup; a null fighter returns with no output.
    2. skill = skillManager.getSkillByCategory(category).
    3. SkillProcessHelper.skillFireCheck: skill != null AND stageCheck (always
       true) AND fighterCheck (not dead, not ATTACK-forbidden) AND
       isReadyForFire(skill). Failure returns with no output.
    4. SkillProcessHelper.skillWaveCheck: failure returns with no output. On
       success it decrements remainWaveNum (see readiness.wave_check).
    5. skill.setIndex(index).
    6. targets = SkillProcessHelper.confirmTargets(...). Not ported; the caller
       supplies the targets.
    7. beforeSkillFireHandle: returns immediately in both branches (no-op).
    8. callSkillHandle, if the skill is a call-skill. Not ported; see the gap below.
    9. SkillProcessHelper.fight(fighter, skill, index, targets, ...): effects.
       Not ported; injected through the effects boundary.
   10. Surrounding roles get FightOutputWrapper.skillFire(...) with the result.
- Firing performs no resource consumption and no cooldown or readiness write.
  skillReadyFireConsume is used only by the follow-up chain paths
  (triggerFollowSkills, followUpSkillRelease), not by 42002.

Validation runs before any mutation. The wave decrement is a mutation that
happens before effects, and Java has no rollback, so a fight that fails after the
decrement keeps the wave consumed.

Gap: callSkillHandle is not ported. The column that marks a call-skill is not
verified, so the coordinator does not branch on it.
"""

from .preparation import Preparation


class Firing:
    """Fire a prepared skill against an injected effects boundary."""

    def __init__(self, preparation, effects):
        self.preparation = preparation
        self.effects = effects

    def fire(self, fighter, skill, index, targets, now_ms):
        """Run skillFire. Returns (accepted, events). Rejections return ([], no output)."""
        if fighter is None or skill is None:
            return False, []
        if not Preparation._fighter_ok(fighter):
            return False, []
        readiness = self.preparation.readiness
        if not readiness.is_ready(skill, now_ms):
            return False, []
        if not readiness.wave_check(skill):
            return False, []

        skill['index'] = index
        result = self.effects.fight(fighter, skill, index, targets)
        events = [{
            'type': 'skill_fire',
            'category': skill['category'],
            'skill_id': skill['id'],
            'index': index,
            'targets': result,
            'scope': 'surrounding',
        }]
        return True, events

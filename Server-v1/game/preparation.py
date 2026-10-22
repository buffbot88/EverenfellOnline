"""Skill preparation (42001) coordinator, isolated from live dispatch.

Evidence (javap of the shipped jar, output/javap-extract):
- FightServiceImpl.skillReadyFire: look up the fighter and skill by category,
  then skillReadyFireCheck. On failure, return the payload (the self path sends
  it to the caller). On success: skill.toCd(fighter), skillManager.setReadyForFire
  (skill), consume rule execute(fighter, skill), then FightOutputWrapper.skillReady
  to surrounding roles and, for the self path only, 42005 with getDynamicCd().
- FightServiceImpl.skillReadyFireCheck (private) error payloads, in order:
    null skill                      -> [0]
    skill.remainCd() > 0            -> [-1, category, remainCdMs]
    SkillProcessHelper check fails  -> [0]
- SkillProcessHelper.skillReadyFireCheck: skill != null, stageCheck (always
  true), skillCheck (consume rule isSatify), fighterCheck (not dead and not
  ATTACK-forbidden).
- Skill.toCd(fighter): cdType1 through toDynamicCd (value computed in float32),
  then cdType2 through static toCd. Skill.getDynamicCd() is
  publicCdManager.getCd(cdType1), the remaining cd1 time after toCd.
- BuffServiceImpl._222SpecialEffectHandler broadcasts an attribute change after
  an MP deduction that proceeds past its early return.
- ConsumeCalRuleFactory: an unknown consume type falls back to the EMPTY rule.

Validation runs before any mutation, so a rejected preparation changes nothing.
Mutation order on success is cooldown, then readiness, then consumption. No
rollback is modelled because the bytecode has none.

Outgoing updates are returned as plain dicts. Frame serialization is separate.
The cooldown-table lookup (CdBiao cdtime by cd name) is injected as cd_table.
"""

from . import consume as consume_rules
from .cooldown import SkillCooldowns
from .readiness import SkillReadiness, object2int


class Preparation:
    """Per-fighter preparation state: public cooldowns plus skill readiness."""

    def __init__(self, cooldowns, cd_table, readiness=None):
        self.cooldowns = cooldowns
        self.cd_table = cd_table
        self.readiness = readiness or SkillReadiness()

    @staticmethod
    def _config(skill):
        return skill.get('config', {})

    def _skill_cooldowns(self, skill):
        cfg = self._config(skill)
        return SkillCooldowns(self.cooldowns, cfg.get('cd1'), cfg.get('cd2'))

    def _consume_type(self, skill):
        """SkillConfig.getConsumeType as an int (missing or invalid -> 0 EMPTY)."""
        return object2int(self._config(skill).get('consumetype'))

    @staticmethod
    def _fighter_ok(fighter):
        """SkillProcessHelper.fighterCheck: not dead and not ATTACK-forbidden."""
        return not fighter.get('dead', False) and not fighter.get('attack_forbidden', False)

    def prepare(self, fighter, skill, now_ms, self_cast=False):
        """Run skillReadyFire for one skill. Returns (accepted, error, events).

        error is the Java payload when rejected, else None. events is the list of
        outgoing updates in emission order, empty when rejected.
        """
        if skill is None:
            return False, [0], []

        remain = self._skill_cooldowns(skill).remain_cd(now_ms)
        if remain > 0:
            return False, [-1, skill['category'], remain], []

        consume_type = self._consume_type(skill)
        if not self._fighter_ok(fighter) or not consume_rules.is_satisfied(
                consume_type, fighter, skill):
            return False, [0], []

        cfg = self._config(skill)
        cdtime1 = self.cd_table.get(cfg.get('cd1'))
        cdtime2 = self.cd_table.get(cfg.get('cd2'))

        # Java mutation order: cooldown, readiness, consumption.
        self._skill_cooldowns(skill).to_cd(
            cdtime1, cdtime2, fighter.get('gongjisudu', 0.0), now_ms)
        self.readiness.set_ready(skill, now_ms)

        events = []
        consume_rules.consume(
            consume_type, fighter, skill,
            on_attribute_change=lambda f: events.append(
                {'type': 'attr_change', 'fighter': f.get('id')}))

        events.append({'type': 'skill_ready', 'category': skill['category'],
                       'skill_id': skill['id'], 'scope': 'surrounding'})
        if self_cast:
            events.append({'type': 'dynamic_cd', 'category': skill['category'],
                           'remain_ms': self.cooldowns.get_cd(cfg.get('cd1'), now_ms)})
        return True, None, events

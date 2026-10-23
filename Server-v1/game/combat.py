"""Combat resolution for the stage fight pipeline, recovered from the jar via tools/javap.py.

Provenance (all shapes/order verified against output/orig-stack/tap-decoded.txt):
- FightServiceImpl.skillFire: resolve fighter + skill by category, checks,
  confirmTargets, SkillProcessHelper.fight, then one FightOutputWrapper.skillFire
  broadcast [fighterId, skillCategory, index, hits[], arg4, arg5] (Object[6]).
- SkillProcessHelper.fight per target: calculator by damageType, harm
  calculator by damageFormuleType, acceptHarm (curHp -= val; val <= 0 or null
  harm changes nothing), changeOutput, then getHarmOutput appended to hits.
- changeOutput order: outputAttributeChange(target), outputAttributeChange
  (attacker), buffChange(target), buffChange(attacker), 43000 if target dead.
  outputAttributeChange sends 12004 [id, curHp, maxHp, curMp, maxMp] (Floats,
  hence AMF3 doubles) only when HP/MP changed; buffChange sends 42100
  [fighterId, adds, removes] with nulls when empty.
- getHarmOutput: [targetId, HarmType.getVal, harm.getVal (int), isDead 1/0].
  HarmType clinit values: PUTONG 0, SHANBI 1, BAOJI 2, GEDANG 3, ... A missed
  swing is Harm(SHANBI, 0.0); acceptHarm ignores it so no 12004 follows.
- getDeadOutput: 43000 [DeadPositionType.NORMAL=1, [targetId, attackerId,
  attackerName, 0, skillCategory]]; when the killer is a partner pet the inner
  array carries the owner instead ([target, ownerId, ownerName, 0, category,
  petName], Object[6]).
- ShanghaiResultCalculator.harmCalculate (monster involved either side):
    E = max(wuli - max(fangyu*(1-pojia) - qiege, 0)
            * max(1 - max(lvAtt-lvDef, 0)/100, 0), 0)
    Q = formulea*E + formuleb + maxHpAtt*shishenAtt          (T21: fa*wuli+fb)
    Tm = max(1 + eff122Att + damageAtt - defenceTgt - eff126Tgt, 0)
    v = max(Q*Tm + (eff121Att - eff125Tgt), max(lvAtt*formuleg, 0))
      + formulea * sum(attackerElement - targetElementResist) over the five
      elements (lei/mu/shui/huo/tu)
    putongHarmCalculate: if formulec > 0: v *= formulec^(lvAtt-1)
    crit (skill.criticalCalculate and T7.isBaoji): v *= max(1.5 + criticalbAtt
      + eff19Att - criticalcTgt - eff20Tgt, 1), type BAOJI
    block (T9.isBiHu: max(geDangTgt - poJiAtt, 0) per-mille): v *= 0.5
    role-vs-role (or JingJi-vs-JingJi): v *= 0.8
    clamp: v > 2147483648.0 -> 2047483648.0; Harm value is (int)v.
  Crit chance (T7): role->monster baojiAtt/(baojiAtt+baojiTgt) * lvAtt/(sum)
    * 0.7; monster->role the same * 0.3; otherwise * 0.7; clamped to
    [0.05, 0.95], rolled with Lottery.isSuccess.    Miss chance (T8.isMingZhong, only when skill.voltCalculate): role->monster
    shanbiTgt/(shanbiAtt+shanbiTgt) * lvTgt/(sum) * 0.5; monster->role * 0.2;
    otherwise * 0.7; clamped to [0.05, 0.95]. isMingZhong returns
    !Lottery.isSuccess(chance), so the swing misses when Lottery.isSuccess
    succeeds (nextFloat() < chance).
    Elemental (the monster branch, offsets 493-540, before putong): harm +=
    formulea * (damageAtt_e - defenceTgt_e) for lei, mu, shui, huo, tu.
- AbsFightResultCalculator.calculate order: fixed-harm target, fixed-harm
  attacker, DiKang resist, miss check (!checkMingZhong -> SHANBI harm),
  skill resist, then buffs + harmCalculate. Only the miss path is ported;
  DiKang/skill-resist/fixed-harm have no captured instances and are logged.
- AiServiceImpl.monsterExpDrop per killer role: harmPercent = min(harm/total
  fight harm, 1) as an int percent (solo killer -> 100); correction from
  ShaGuaiXiuZhengBiao (solo vs team column); level gap max(roleLv-monLv, 0)
  decay from JingYanShuaiJianBiao; exp = (long)(basicExp * (1+(n-1)*0.05)
  * xiuZheng * levelXishu) * (1+serverRate) through calFightExp (ewai odds +
  exp-fold items + guild + VIP + event factors); RoleExportService.incrExp
  persists and sends 12001 [expTotal(Long->double), level], then 12030
  [deadMonsterId, templateId, expGranted(Long->double)] is queued.

Approximations (logged where they bite): effect attributes (121/122/125/126,
19/20), elemental damage/resist, shishen, damage/defence, pojia/qiege,
criticalb/c, geDang/poJi all default to 0 (their source tables and buff
wiring are unmigrated); heal (ZhiLiao) calculators are not ported; level-up
thresholds are unknown so kills only persist exp. The captured goldens this
reproduces exactly: normal003 1649 / crit 2474 / miss [1,0,0], monster06 30,
zuoqi11 100, +51 exp per D040011 kill at the captured bonuses is NOT
reproduced (needs the role's unmigrated exp-fold buffs; base without bonuses
is 4).
"""

HARM_PUTONG = 0
HARM_SHANBI = 1
HARM_BAOJI = 2
HARM_GEDANG = 3
HARM_BIHU = 9
HARM_BAOJIBIHU = 10

PVP_DAMAGE_SCALE = 0.8
CRIT_BASE = 1.5
BIHU_SCALE = 0.5
HARM_CLAMP_TO = 2047483648.0
HARM_CLAMP_ABOVE = 2147483648.0


def t21_base(formulea, wuli, formuleb):
    """T21HarmCalculator.getSkillHaram: formulea * wuliGongJi + formuleb."""
    return formulea * wuli + formuleb


def effective_attack(wuli, fangyu, pojia=0.0, qiege=0.0, att_lv=0, def_lv=0):
    """Defence-discounted attack E; negatives floor at 0 (max(FF) at each step)."""
    disc = max(fangyu * (1.0 - pojia) - qiege, 0.0)
    disc *= max(1.0 - max(att_lv - def_lv, 0) / 100.0, 0.0)
    return max(wuli - disc, 0.0)


def damage_multiplier(eff122=0.0, damage=0.0, defence=0.0, eff126=0.0):
    """T multiplier max(1 + eff122 + damageAtt - defenceTgt - eff126, 0)."""
    return max(1.0 + eff122 + damage - defence - eff126, 0.0)


def putong_scale(value, formulec, att_lv):
    """putongHarmCalculate: pow(formulec, lv-1) scaling only when formulec > 0."""
    if formulec and formulec > 0:
        return value * pow(formulec, att_lv - 1)
    return value


def baoji_value(harm, criticalb=0.0, criticalc=0.0, eff19=0.0, eff20=0.0):
    """baojiHarmCalculate: harm * max(1.5 + bAtt + e19 - cTgt - e20, 1)."""
    return harm * max(CRIT_BASE + criticalb + eff19 - criticalc - eff20, 1.0)


def _clamp_chance(value):
    """T7/T8 clamp lottery chances into [0.05, 0.95]."""
    return min(0.95, max(0.05, value))


def crit_chance(att_baoji, tgt_baoji, att_lv, tgt_lv, att_is_role,
               tgt_is_monster, tgt_is_role=False):
    """T7.isBaoji crit chance for attacker -> target."""
    total = att_baoji + tgt_baoji
    ratio = att_baoji / total if total > 0 else 0.0
    lv_ratio = att_lv / (att_lv + tgt_lv) if att_lv + tgt_lv > 0 else 0.0
    if att_is_role and tgt_is_monster:
        factor = 0.7
    elif not att_is_role and tgt_is_role:
        factor = 0.3
    else:
        factor = 0.7
    return _clamp_chance(ratio * lv_ratio * factor)


def miss_chance(att_shanbi, tgt_shanbi, att_lv, tgt_lv, att_is_role,
               tgt_is_monster, tgt_is_role=False):
    """T8.isMingZhong miss probability (the swing misses if the roll fails)."""
    total = att_shanbi + tgt_shanbi
    ratio = tgt_shanbi / total if total > 0 else 0.0
    lv_ratio = tgt_lv / (att_lv + tgt_lv) if att_lv + tgt_lv > 0 else 0.0
    if att_is_role and tgt_is_monster:
        factor = 0.5
    elif not att_is_role and tgt_is_role:
        factor = 0.2
    else:
        factor = 0.7
    return _clamp_chance(ratio * lv_ratio * factor)


def resolve_hit(att, tgt, skill, force=None, roll=None):
    """(harm_int, harm_type) for one attacker -> target swing.

    att/tgt are dicts with wuli, fangyu, baoji, shanbi, level, max_hp and
    is_role/is_monster flags; skill carries formulea/b/c/g, volt/crit flags
    and damageformule (only T21 is ported). force overrides the lotteries
    ('hit', 'crit', 'miss', 'bihu') for tests; roll defaults to random.random.
    """
    import random
    roll = roll or random.random
    if skill.get('damageformule') not in (None, '', 'T21'):
        raise ValueError('unsupported damageformule %r'
                         % (skill.get('damageformule'),))
    fa = float(skill.get('formulea') or 0)
    fb = float(skill.get('formuleb') or 0)
    fc = skill.get('formulec') or 0
    fg = float(skill.get('formuleg') or 0)
    try:
        fc = float(fc)
    except (TypeError, ValueError):
        fc = 0.0
    outcome = force
    if outcome is None:
        if skill.get('voltcalculate') and roll() < miss_chance(
                att.get('shanbi', 0.0), tgt.get('shanbi', 0.0),
                att.get('level', 0), tgt.get('level', 0),
                att.get('is_role', False), tgt.get('is_monster', False),
                tgt.get('is_role', False)):
            # T8.isMingZhong returns !Lottery.isSuccess(chance): success means a miss.
            outcome = 'miss'
        else:
            outcome = 'hit'
    if outcome == 'miss':
        return 0, HARM_SHANBI
    eff = effective_attack(att.get('wuli', 0.0), tgt.get('fangyu', 0.0),
                           att.get('pojia', 0.0), att.get('qiege', 0.0),
                           att.get('level', 0), tgt.get('level', 0))
    skill_harm = (t21_base(fa, eff, fb)
                  + float(att.get('max_hp', 0.0)) * float(att.get('shishen', 0.0)))
    skill_harm *= damage_multiplier(0.0, att.get('damage', 0.0),
                                    tgt.get('defence', 0.0), 0.0)
    value = max(skill_harm, max(att.get('level', 0) * fg, 0.0))
    elem_att = att.get('elem_damage') or (0.0,) * 5
    elem_tgt = tgt.get('elem_defence') or (0.0,) * 5
    for dmg, dfn in zip(elem_att, elem_tgt):
        value += fa * (float(dmg) - float(dfn))
    value = putong_scale(value, fc, att.get('level', 0))
    harm_type = HARM_PUTONG
    if outcome not in ('hit', 'crit', 'bihu'):
        raise ValueError('unknown forced outcome %r' % (outcome,))
    want_crit = (outcome == 'crit')
    if force is None and not want_crit and skill.get('criticalcalculate'):
        want_crit = roll() < crit_chance(
            att.get('baoji', 0.0), tgt.get('baoji', 0.0),
            att.get('level', 0), tgt.get('level', 0),
            att.get('is_role', False), tgt.get('is_monster', False),
            tgt.get('is_role', False))
    if want_crit:
        value = baoji_value(value, att.get('criticalb', 0.0),
                            tgt.get('criticalc', 0.0),
                            att.get('eff19', 0.0), tgt.get('eff20', 0.0))
        harm_type = HARM_BAOJI
    if force == 'bihu' or (force is None and _roll_bihu(att, tgt, roll)):
        value *= BIHU_SCALE
        harm_type = HARM_BAOJIBIHU if harm_type == HARM_BAOJI else HARM_BIHU
    if (att.get('is_role') and tgt.get('is_role')) or (
            att.get('is_jingji') and tgt.get('is_jingji')):
        value *= PVP_DAMAGE_SCALE
    if value > HARM_CLAMP_ABOVE:
        value = HARM_CLAMP_TO
    return int(value), harm_type


def _roll_bihu(att, tgt, roll):
    """T9.isBiHu: Lottery.roll(odds, THOUSAND), odds = max(geDangTgt - poJiAtt, 0).

    Lottery.roll(p, L) succeeds when p > 0 and nextInt(L.val) <= (int)(p * L.val);
    int(roll() * 1000) stands in for nextInt(1000).
    """
    odds = max(float(tgt.get('gedang', 0.0)) - float(att.get('poji', 0.0)), 0.0)
    if odds <= 0.0:
        return False
    return int(roll() * 1000) <= int(odds * 1000)


def hit_record(target_id, harm_type, harm_val, dead):
    """FightOutputWrapper.getHarmOutput: [targetId, typeVal, harm, isDead]."""
    return [target_id, int(harm_type), int(harm_val), 1 if dead else 0]


def hp_changed_frame(fighter_id, cur_hp, max_hp, cur_mp, max_mp):
    """FightOutputWrapper.hpMpChangedOutput: 12004 floats (Java Floats)."""
    return ['12004', [fighter_id, float(cur_hp), float(max_hp),
                      float(cur_mp), float(max_mp)]]


def buff_flush_frame(fighter_id, adds=None, removes=None):
    """42100 [fighterId, addBuffInfos, removeBuffIds], nulls when empty."""
    return ['42100', [fighter_id, adds, removes]]


def dead_notice(dead_id, attacker_id, attacker_name, skill_category,
               owner_id=None, owner_name=None, attacker_name_full=None):
    """FightOutputWrapper.getDeadOutput 43000 [1, inner].

    Role killers send the 5-slot inner array; partner-pet killers send the
    6-slot owner variant (IPartner branch).
    """
    if owner_id is None:
        inner = [dead_id, attacker_id, attacker_name, 0, skill_category]
    else:
        inner = [dead_id, owner_id, owner_name, 0, skill_category,
                 attacker_name_full]
    return ['43000', [1, inner]]


def skill_fire_frame(actor_id, skill_category, index, hits, arg4=None,
                     arg5=1):
    """FightOutputWrapper.skillFire 42002 Object[6] broadcast."""
    return ['42002', [actor_id, skill_category, int(index), hits, arg4, arg5]]


def exp_notice(new_total, level):
    """RoleExportServiceImpl.incrExp 12001 [expTotal(Long), level]."""
    return ['12001', [float(new_total), int(level)]]


def apply_exp_gain(level, exp, gain, need_exp, max_level):
    """UserRoleServiceImpl.calUpgradeAndExp: (level, exp, levels_gained).

    need_exp(level) is the ZhuJueShuXingBiao needexp cell; max_level is
    loadMaxLevel (95). At cap the gain banks onto exp with no level-up;
    otherwise each rung with total >= needexp(level) spends it for +1
    level and a zeroed bar, recursing on the remainder.
    """
    try:
        level = int(level or 0)
    except (TypeError, ValueError):
        level = 0
    try:
        total = int(exp or 0) + int(gain or 0)
    except (TypeError, ValueError):
        total = int(gain or 0)
    try:
        cap = int(max_level)
    except (TypeError, ValueError):
        cap = 0
    if level >= cap:
        return level, total, 0
    gained = 0
    while True:
        try:
            need = int(need_exp(level))
        except (TypeError, ValueError):
            break
        if need <= 0 or total < need:
            break
        total -= need
        level += 1
        gained += 1
        if level >= cap:
            break
    return level, total, gained


def exp_drop_frame(dead_id, template_id, exp_granted):
    """AiServiceImpl.monsterExpDrop 12030 [deadId, templateId, exp(Long)]."""
    return ['12030', [dead_id, template_id, float(exp_granted)]]


def aoi_leave_frame(fighter_id):
    """AoiMsgListener.getLeaveCommand 24002 [[fighterId]]."""
    return ['24002', [[fighter_id]]]


def base_kill_exp(basic_exp, team_size=1, xiuZheng=1.0, levelXishu=1.0,
                  server_rate=0.0):
    """AiServiceImpl.monsterExpDrop base: (long)(basic*(1+(n-1)*0.05)*xz*lx).

    The harm percent only selects the ShaGuaiXiuZheng row (xiuZheng arg here),
    and the level gap only selects the JingYanShuaiJian row (levelXishu arg).
    """
    value = int(float(basic_exp) * (1.0 + (max(team_size, 1) - 1) * 0.05)
                * float(xiuZheng) * float(levelXishu))
    return int(value * (1.0 + float(server_rate)))


def fight_exp_with_bonuses(base_exp, ewai_odds=0.0, exp_fold=0, guild_add=0.0,
                           vip_add=0.0, event_factor=0.0):
    """RoleCalExpExportService.calFightExp: base*(1+sum) iff the sum is positive."""
    factor = (float(ewai_odds) + float(exp_fold) + float(guild_add)
              + float(vip_add) + float(event_factor))
    if factor <= 0:
        return int(base_exp)
    return int(float(base_exp) * (1.0 + factor))

"""Pet (PetServiceImpl) helpers: error codes and fresh row shapes.

Ports PetErrorCode (<clinit> values are identity: CODE_13600x is
13600x) plus the RolePet/RolePetZhenfa insert shapes from
propActivatePet and online(); timestamps are epoch millis like the
rest of the port.
"""

import random as _random
import time as _time

# PetErrorCode <clinit> values (dntg_start.jar).
ERR_ACTIVATE_DUP = 136000
ERR_MAX_LEVEL = 136001
ERR_NO_JINJIE = 136002
ERR_ZHENFA_MAXED = 136003
ERR_ZHENFA_JINJIE_GATE = 136004
ERR_NO_PET = 136005
ERR_DEPLOYED = 136006
ERR_CHUANCHEN_GATE = 136007
ERR_PET_NOTICE = 136009
ERR_CHUZHAN_DUP = 136010
ERR_ZHENFA_MAXLV = 136011
# GeneralErrorCode values shared with the other ports.
ERR_LEVEL_NOT_ENOUGH = 1000
ERR_GOODS_NOT_ENOUGH = 1005

# JISHU_1: activation always loads the jieshu-1 config row.
FIRST_JIESHU = 1
# online() seeds the formation at zhenfa '1' with empty maps.
FIRST_ZHENFA_ID = '1'


def fresh_pet(rid, pet_id, now_ms=None):
    """propActivatePet insert shape: lv/rank 1, zero exps and fails."""
    now = int(now_ms) if now_ms is not None else int(_time.time() * 1000)
    return {'user_role_id': str(rid), 'pet_id': str(pet_id), 'pet_lv': 1,
            'pet_lv_exp': 0, 'pet_rank': FIRST_JIESHU,
            'pet_rank_exp': 0, 'pet_rank_fail': 0,
            'pet_rank_update_time': now, 'create_time': now}


def fresh_zhenfa(rid, now_ms=None):
    """online() insert shape for a first-login formation row."""
    now = int(now_ms) if now_ms is not None else int(_time.time() * 1000)
    return {'user_role_id': str(rid), 'zhenfa_id': FIRST_ZHENFA_ID,
            'pet_chuzhan_id': None, 'upgrade_exp': 0,
            'jinjie_fail_count': 0, 'jinjie_time': now,
            'jinjie_data': '{}', 'zhenfa_pet': '{}',
            'pet_upgrade_count': 0, 'pet_upgrade_time': now}


def roll_success(odds):
    """Lottery.isSuccess: a fresh Random's nextFloat() under the rate."""
    try:
        rate = float(odds)
    except (TypeError, ValueError):
        return False
    return _random.random() < rate


def random_blessing(addmin, addmax):
    """Lottery.randomInt: lo when equal, else lo + nextInt(hi - lo)."""
    try:
        lo, hi = int(addmin), int(addmax)
    except (TypeError, ValueError):
        return 0
    if hi <= lo:
        return lo
    return lo + _random.randrange(hi - lo)


def pet_jinjie_success(fail_count, cfg):
    """PetServiceImpl.isSucc: pity floor/ceiling around the odds roll."""
    try:
        fail = int(fail_count or 0)
        floor = int(cfg.get('min_times') or 0)
        ceiling = int(cfg.get('max_times') or 0)
    except (TypeError, ValueError):
        return False
    if fail < floor:
        return False
    if fail >= ceiling:
        return True
    return roll_success(cfg.get('odds'))


def zhenfa_jinjie_success(fail_count, cfg):
    """PetServiceImpl.isZhanfaJinJieSucc: the ceiling is strict here."""
    try:
        fail = int(fail_count or 0)
        floor = int(cfg.get('min_times') or 0)
        ceiling = int(cfg.get('max_times') or 0)
    except (TypeError, ValueError):
        return False
    if fail < floor:
        return False
    if fail > ceiling:
        return True
    return roll_success(cfg.get('odds'))


def reset_pet(pet):
    """chuanChen source reset: back to a lv/rank-1 blank pet."""
    out = dict(pet or {})
    out['pet_lv'] = 1
    out['pet_lv_exp'] = 0
    out['pet_rank'] = FIRST_JIESHU
    out['pet_rank_exp'] = 0
    out['pet_rank_fail'] = 0
    return out

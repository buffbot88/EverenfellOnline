"""Role fight attributes for command 12000, ported from jar bytecode.

Key ids come from AbsFightAttribute.changeAttribute call sites (captured
12000 has exactly this set): 1 maxMp, 2 WuLiGongJi, 3 WuLiFangYu, 4 BaoJi,
5 ShanBi, 6 GongJiSuDu, 7 YiDongSuDu, 10 MaxShanbiVal. Key 0 (maxHp) is
never recorded as changed, which is why Java's entry push omits it.

Each value is the jar's formula (GongJiFormula, FangYuFormula, BaoJiFormula,
ShanBiFormula, GongjiSuduFormula, ShenFaFormula, MaxShanBiValFormula) with
its effect slots left empty: equipment/effects are not in the migrated data,
so a role's attributes here are its ZhuJueShuXingBiao level row plus the
persisted max_mp, exactly what our data model knows.
"""


def _gongji(base, perdamage=0.0, e6=0.0, e5=0.0):
    """GongJiFormula: base*(1+perdamage+e6) + e5, floor 1 (jar bytecode)."""
    return max(base * (1.0 + perdamage + e6) + e5, 1.0)


def _fangyu(base, jiangu=0.0, e8=0.0, e7=0.0):
    """FangYuFormula: base*(1+jiangu+e8) + e7, floor 1."""
    return max(base * (1.0 + jiangu + e8) + e7, 1.0)


def _baoji(base, e10=0.0, e9=0.0):
    """BaoJiFormula: base*(1+e10) + e9, floor 0."""
    return max(base * (1.0 + e10) + e9, 0.0)


def _shanbi(base, e12=0.0, e11=0.0):
    """ShanBiFormula: base*(1+e12) + e11, floor 0."""
    return max(base * (1.0 + e12) + e11, 0.0)


def _gongjisudu(base, e14=0.0, e13=0.0):
    """GongjiSuduFormula: attackrate*(1+e14) + e13, floor 0."""
    return max(base * (1.0 + e14) + e13, 0.0)


def _yidongsudu(base, e16=0.0, e15=0.0):
    """ShenFaFormula: velocity*(1+e16) + e15, floor 0."""
    return max(base * (1.0 + e16) + e15, 0.0)


def entry_attribute_map(row, max_mp=None, bags=(), effect=None):
    """The 12000 map for stage entry: keys '1'..'7','10', all float values.

    `row` is the ZhuJueShuXingBiao level row; `bags` are the no-effect
    attribute bags to add to it (equipment, shuxingdan, meiren, ...); `effect`
    is the buff bag the numbered formula slots read. max_mp prefers the
    persisted role value (the same one 12004 reports, and the same value
    Java's live attribute held for the captured role).
    """
    eff = effect or {}

    def f(key):
        return float(row.get(key) or 0)

    def bag(key):
        return sum(float(b.get(key) or 0) for b in bags)

    def base(key):
        return f(key) + bag(key)

    def slot(key):
        return float(eff.get(key) or 0)

    mp = float(max_mp) if max_mp is not None else base('mana')
    return {
        '1': mp,
        '2': _gongji(base('physicdamage'), base('perdamage'), slot('6'), slot('5')),
        '3': _fangyu(base('physicdefence'), base('jiangu'), slot('8'), slot('7')),
        '4': _baoji(base('critical'), slot('10'), slot('9')),
        '5': _shanbi(base('volt'), slot('12'), slot('11')),
        '6': _gongjisudu(base('attackrate'), slot('14'), slot('13')),
        '7': _yidongsudu(base('velocity'), slot('16'), slot('15')),
        '10': float(int(base('dunshudian'))),  # MaxShanBiValFormula casts to int
    }

"""Public cooldown state, ported from PublicCdManager and Skill (isolated).

Evidence (javap of the shipped jar, output/javap-extract):
- PublicCdManager.toCd(String, int): lastTriggerTimes.put(name,
  System.currentTimeMillis() + ms). The map stores an absolute expiry in
  milliseconds; a later call for the same name overwrites it.
- PublicCdManager.remainCd(String): 0 for a null or empty name or an
  unregistered name; otherwise expiry - now (may be negative once expired).
- PublicCdManager.getCd(String): 0 for null/empty/unregistered; otherwise
  the remaining ms as int when positive, else 0.
- PublicCdManager.toDynamicCd(String, IFighter): cdTime = CdBiao cdtime (int);
  value = (int)( (float)cdTime / (1.0f + gongJiSuDu / 2000.0f) ). All
  arithmetic is float32 (i2f, fdiv, fadd, f2i), so truncation is toward zero.
  It then calls toCd(name, value) and returns value. An unknown cd id returns 0
  without storing anything.
- PublicCdManager.toCd(String): loads CdBiao cdtime and stores it statically
  (no dynamic reduction). Unknown id stores nothing.
- Skill.remainCd(): max(remainCd(cdType1), remainCd(cdType2)).
- Skill.toCd(fighter): cdType1 -> toDynamicCd (ignores result beyond storing),
  cdType2 -> static toCd. A null cd type is skipped.

The cooldown map belongs to one PublicCdManager; SkillManager owns it
(cdManager), so the state is per fighter and keyed by cd name.
"""

import struct


def f32(x):
    """Round a Python float to IEEE-754 float32, as the JVM does for float."""
    return struct.unpack('f', struct.pack('f', float(x)))[0]


def dynamic_cd(cdtime_ms, gongjisudu):
    """PublicCdManager.toDynamicCd arithmetic, performed in float32.

    Java: (int) ((float) cdTime / (1.0f + gongJiSuDu / 2000.0f)). Each step is
    rounded to float32; the final int cast truncates toward zero.
    """
    numerator = f32(cdtime_ms)
    denominator = f32(f32(1.0) + f32(f32(gongjisudu) / f32(2000.0)))
    return int(f32(numerator / denominator))


class PublicCooldowns:
    """Per-fighter named cooldowns: name -> absolute expiry (ms)."""

    def __init__(self):
        self._expiry = {}

    @staticmethod
    def _blank(name):
        return name is None or name == ''

    def to_cd(self, name, ms, now_ms):
        """PublicCdManager.toCd(String,int): store now + ms, overwriting any earlier value."""
        if self._blank(name):
            return
        self._expiry[name] = int(now_ms) + int(ms)

    def remain_cd(self, name, now_ms):
        """PublicCdManager.remainCd: expiry - now, or 0 when blank or unregistered."""
        if self._blank(name):
            return 0
        expiry = self._expiry.get(name)
        if expiry is None:
            return 0
        return expiry - int(now_ms)

    def get_cd(self, name, now_ms):
        """PublicCdManager.getCd: remaining ms when positive, else 0."""
        remain = self.remain_cd(name, now_ms)
        return remain if remain > 0 else 0

    def dynamic_to_cd(self, name, cdtime_ms, gongjisudu, now_ms):
        """PublicCdManager.toDynamicCd after the CdBiao lookup: store and return the value."""
        if self._blank(name) or cdtime_ms is None:
            return 0
        value = dynamic_cd(cdtime_ms, gongjisudu)
        self.to_cd(name, value, now_ms)
        return value


class SkillCooldowns:
    """Skill.cdType1 / cdType2 over one PublicCooldowns (Skill.remainCd / toCd)."""

    def __init__(self, manager, cd_type1, cd_type2):
        self.manager = manager
        self.cd_type1 = cd_type1
        self.cd_type2 = cd_type2

    def remain_cd(self, now_ms):
        """Skill.remainCd: the larger of the two named remainders."""
        first = self.manager.remain_cd(self.cd_type1, now_ms)
        second = self.manager.remain_cd(self.cd_type2, now_ms)
        return first if first > second else second

    def to_cd(self, cdtime1, cdtime2, gongjisudu, now_ms):
        """Skill.toCd(IFighter): cdType1 uses the dynamic value, cdType2 the static cdtime."""
        if self.cd_type1 is not None:
            self.manager.dynamic_to_cd(self.cd_type1, cdtime1, gongjisudu, now_ms)
        if self.cd_type2 is not None and cdtime2 is not None:
            self.manager.to_cd(self.cd_type2, cdtime2, now_ms)

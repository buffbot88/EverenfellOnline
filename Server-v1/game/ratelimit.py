"""Token-bucket rate limiter for per-connection frame throughput."""
import time


class TokenBucket:
    """Allows ``rate`` events per second sustained, with bursts up to ``burst``."""

    def __init__(self, rate, burst, clock=time.monotonic):
        self.rate = float(rate)
        self.burst = float(burst)
        self._clock = clock
        self._tokens = self.burst
        self._last = clock()

    def allow(self):
        """Consume one token; False when the bucket is empty."""
        now = self._clock()
        self._tokens = min(self.burst, self._tokens + (now - self._last) * self.rate)
        self._last = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

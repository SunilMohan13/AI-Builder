"""Per-source client-side rate limiting (LLD §7.1).

Sources publish their own request budgets and several of them (FIRMS, OpenAQ)
throttle aggressively. Limiting on our side keeps a backfill from burning a
day's quota in a few seconds and turning every later fetch into a 429.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from time import monotonic, sleep


class RateLimiter:
    """Token bucket enforcing a sustained rate with a burst allowance.

    The bucket refills continuously, so a connector that polls slower than its
    budget accumulates a burst it can spend on a backfill without ever
    exceeding the long-run average.

    Args:
        rate_per_second: Sustained refill rate in permits per second.
        burst: Maximum permits that may accumulate. Defaults to one second of
            rate, with a floor of one so the limiter is never a deadlock.
        clock: Monotonic time source, injectable for tests.
        sleeper: Blocking sleep function, injectable for tests.

    Raises:
        ValueError: If ``rate_per_second`` is not positive.
    """

    def __init__(
        self,
        rate_per_second: float,
        *,
        burst: float | None = None,
        clock: Callable[[], float] = monotonic,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        self.rate_per_second = rate_per_second
        self.burst = max(1.0, burst if burst is not None else rate_per_second)
        self._clock = clock
        self._sleeper = sleeper
        self._tokens = self.burst
        self._updated = clock()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate_per_second)
            self._updated = now

    def try_acquire(self) -> bool:
        """Take one permit if available, without blocking.

        Returns:
            True if a permit was taken.
        """
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def acquire(self) -> float:
        """Block until a permit is available, then take it.

        Returns:
            Seconds spent waiting. Zero when a permit was already available,
            which makes the return value usable as a throttling metric.
        """
        waited = 0.0
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return waited
                deficit = 1.0 - self._tokens
                delay = deficit / self.rate_per_second
            self._sleeper(delay)
            waited += delay

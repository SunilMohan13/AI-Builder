"""In-process circuit breaker for source isolation.

A production deployment can back this with Redis; the contract stays the same.
"""

from __future__ import annotations

from enum import StrEnum
from time import monotonic


class CircuitState(StrEnum):
    """Breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Fail-fast after consecutive source errors.

    Args:
        failure_threshold: Consecutive failures before opening.
        recovery_seconds: Time to wait before a half-open probe.
    """

    def __init__(self, failure_threshold: int = 5, recovery_seconds: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.failures = 0
        self.state = CircuitState.CLOSED
        self.opened_at = 0.0

    def allow(self) -> bool:
        """Return True if a call may proceed."""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if monotonic() - self.opened_at >= self.recovery_seconds:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True

    def record_success(self) -> None:
        """Reset failure count after a successful call."""
        self.failures = 0
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Increment failures and open the circuit when the threshold is hit."""
        self.failures += 1
        if self.failures >= self.failure_threshold or self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self.opened_at = monotonic()

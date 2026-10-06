"""Circuit breaker tests."""

from aeropulse_connector_sdk.circuit import CircuitBreaker, CircuitState


def test_opens_after_threshold() -> None:
    breaker = CircuitBreaker(failure_threshold=3, recovery_seconds=60)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.allow()
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    assert not breaker.allow()


def test_success_resets() -> None:
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=60)
    breaker.record_failure()
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failures == 0

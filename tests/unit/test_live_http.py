"""Reliability primitives must be wired into the live transport, not merely exist."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from aeropulse_common.settings import Settings, get_settings
from aeropulse_connector_sdk.circuit import CircuitBreaker, CircuitState
from aeropulse_connector_sdk.live_http import (
    CircuitOpenError,
    LiveHttpClient,
    LiveModeDisabledError,
)
from aeropulse_connector_sdk.rate_limit import RateLimiter
from aeropulse_connector_sdk.retry import RETRYABLE_STATUS, is_retryable


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _Response:
    """Minimal stand-in for an httpx response.

    ``text`` and ``headers`` are part of the contract because the client reads
    bodies as text (CSV sources) and captures rate-limit headers.
    """

    def __init__(
        self, status: int, payload: Any, *, text: str | None = None, headers: Any = None
    ) -> None:
        self.status_code = status
        self._payload = payload
        self._text = text
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=httpx.Request("GET", "https://example.test"),
                response=httpx.Response(self.status_code),
            )

    @property
    def text(self) -> str:
        if self._text is not None:
            return self._text
        return json.dumps(self._payload)

    def json(self) -> Any:
        return self._payload


class _Transport:
    """Records calls and replays a scripted sequence of responses."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})
        item = self.responses.pop(0) if self.responses else _Response(200, {})
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _live_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force live connector mode for these transport tests."""
    monkeypatch.setattr(
        "aeropulse_connector_sdk.live_http.get_settings",
        lambda: Settings(connector_mode="live"),
    )


def _client(transport: _Transport, **kwargs: Any) -> LiveHttpClient:
    clock = _FakeClock()
    client = LiveHttpClient("testsource", transport_get=transport, **kwargs)
    client.limiter = RateLimiter(1000.0, clock=clock, sleeper=clock.sleep)
    return client


# --- mode gate ---


def test_replay_mode_blocks_live_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """The platform default must never silently reach the network."""
    monkeypatch.setattr(
        "aeropulse_connector_sdk.live_http.get_settings",
        lambda: Settings(connector_mode="replay"),
    )
    transport = _Transport(_Response(200, {"ok": True}))
    client = LiveHttpClient("testsource", transport_get=transport)
    with pytest.raises(LiveModeDisabledError):
        client.get_json("https://example.test")
    assert transport.calls == []


def test_default_settings_are_replay_mode() -> None:
    """Guard the documented default so live mode stays opt-in."""
    assert get_settings().connector_mode == "replay"


# --- retry classification ---


def test_client_errors_are_not_retried() -> None:
    """A 404 is permanent; retrying wastes the source's rate budget."""
    transport = _Transport(_Response(404, None), _Response(200, {"ok": True}))
    client = _client(transport)
    with pytest.raises(httpx.HTTPStatusError):
        client.get_json("https://example.test")
    assert len(transport.calls) == 1


def test_throttling_is_retried_then_succeeds() -> None:
    """429 is transient and must be replayed."""
    transport = _Transport(_Response(429, None), _Response(200, {"ok": True}))
    payload = _client(transport).get_json("https://example.test")
    assert payload == {"ok": True}
    assert len(transport.calls) == 2


def test_server_errors_are_retried() -> None:
    """5xx is transient."""
    transport = _Transport(_Response(503, None), _Response(200, {"ok": True}))
    assert _client(transport).get_json("https://example.test") == {"ok": True}


def test_transport_faults_are_retried() -> None:
    """Connect/read failures are transient."""
    transport = _Transport(
        httpx.ConnectError("boom", request=httpx.Request("GET", "https://example.test")),
        _Response(200, {"ok": True}),
    )
    assert _client(transport).get_json("https://example.test") == {"ok": True}


def test_retryable_status_set_excludes_client_contract_errors() -> None:
    """401/403/404 must never appear in the retry set."""
    for code in (400, 401, 403, 404, 422):
        assert code not in RETRYABLE_STATUS
    assert is_retryable(
        httpx.HTTPStatusError(
            "x",
            request=httpx.Request("GET", "https://e.test"),
            response=httpx.Response(429),
        )
    )


# --- circuit breaker wiring ---


def test_breaker_opens_after_repeated_failures_and_blocks_calls() -> None:
    """This is the wiring the audit found missing: failures must reach the breaker."""
    breaker = CircuitBreaker(failure_threshold=2)
    transport = _Transport(*[_Response(404, None) for _ in range(10)])
    client = _client(transport, breaker=breaker)

    for _ in range(2):
        with pytest.raises(httpx.HTTPStatusError):
            client.get_json("https://example.test")

    assert breaker.state is CircuitState.OPEN
    calls_before = len(transport.calls)
    with pytest.raises(CircuitOpenError):
        client.get_json("https://example.test")
    assert len(transport.calls) == calls_before, "open breaker must not reach the network"


def test_success_resets_the_breaker() -> None:
    """A recovered source must close its breaker."""
    breaker = CircuitBreaker(failure_threshold=3)
    transport = _Transport(_Response(500, None), _Response(200, {"ok": True}))
    client = _client(transport, breaker=breaker)
    client.get_json("https://example.test")
    assert breaker.state is CircuitState.CLOSED
    assert breaker.failures == 0


# --- timeout propagation ---


def test_timeout_is_passed_to_the_transport() -> None:
    """A missing timeout is how connectors hang forever."""
    transport = _Transport(_Response(200, {}))
    _client(transport, timeout=3.5).get_json("https://example.test")
    assert transport.calls[0]["timeout"] == 3.5


# --- rate limiter ---


def test_limiter_allows_burst_then_throttles() -> None:
    """Burst capacity is spendable, after which callers must wait."""
    clock = _FakeClock()
    limiter = RateLimiter(2.0, burst=2.0, clock=clock, sleeper=clock.sleep)
    assert limiter.acquire() == 0.0
    assert limiter.acquire() == 0.0
    waited = limiter.acquire()
    assert waited > 0.0


def test_limiter_refills_over_time() -> None:
    """A slow poller accumulates permits rather than being penalised."""
    clock = _FakeClock()
    limiter = RateLimiter(10.0, burst=1.0, clock=clock, sleeper=clock.sleep)
    assert limiter.try_acquire() is True
    assert limiter.try_acquire() is False
    clock.now += 1.0
    assert limiter.try_acquire() is True


def test_limiter_rejects_non_positive_rate() -> None:
    """A zero rate would deadlock every fetch."""
    with pytest.raises(ValueError, match="must be positive"):
        RateLimiter(0.0)


def test_client_records_throttled_seconds() -> None:
    """Throttling must be observable, not silent."""
    clock = _FakeClock()
    transport = _Transport(_Response(200, {}), _Response(200, {}))
    client = LiveHttpClient("testsource", transport_get=transport)
    client.limiter = RateLimiter(1.0, burst=1.0, clock=clock, sleeper=clock.sleep)
    client.get_json("https://example.test")
    client.get_json("https://example.test")
    assert client.throttled_seconds > 0.0

"""Live HTTP transport with the SDK reliability primitives actually wired in.

The platform default remains fixture replay. When a source is switched to
``AEROPULSE_CONNECTOR_MODE=live``, every request routed through
:class:`LiveHttpClient` passes through, in order:

    rate limiter -> circuit breaker -> jittered retry -> timeout

Each primitive already existed in this SDK but nothing composed them, so a
connector could not obtain a hardened transport without assembling it by hand.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from aeropulse_common.errors import ConnectorError
from aeropulse_common.settings import get_settings

from aeropulse_connector_sdk.circuit import CircuitBreaker
from aeropulse_connector_sdk.rate_limit import RateLimiter
from aeropulse_connector_sdk.retry import retry_http

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_RATE_PER_SECOND = 5.0


class CircuitOpenError(ConnectorError):
    """Raised when a source's breaker is open and the call was not attempted."""

    def __init__(self, source_id: str) -> None:
        super().__init__(f"circuit open for source {source_id!r}; call not attempted")
        self.source_id = source_id


class LiveModeDisabledError(ConnectorError):
    """Raised when live HTTP is attempted while the platform is in replay mode."""

    def __init__(self) -> None:
        super().__init__("live HTTP disabled; set AEROPULSE_CONNECTOR_MODE=live")


class LiveHttpClient:
    """Hardened JSON transport scoped to a single upstream source.

    One instance per source keeps failure isolation genuine: an outage at FIRMS
    opens only the FIRMS breaker and leaves CPCB ingestion untouched
    (LLD §5.2).

    Args:
        source_id: Source this client fetches for, used in errors and metrics.
        rate_per_second: Client-side request budget.
        timeout: Per-request timeout in seconds.
        breaker: Existing breaker to share across clients for one source.
        transport_get: Injectable GET callable, for tests. Must accept
            ``url``, ``params``, ``headers`` and ``timeout``.
        require_live_mode: When False, skip the connector-mode gate. Used by
            explicitly opt-in live validation scripts.
    """

    def __init__(
        self,
        source_id: str,
        *,
        rate_per_second: float = DEFAULT_RATE_PER_SECOND,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        breaker: CircuitBreaker | None = None,
        transport_get: Any | None = None,
        require_live_mode: bool = True,
        burst: float | None = None,
    ) -> None:
        self.source_id = source_id
        self.timeout = timeout
        self.breaker = breaker or CircuitBreaker()
        self.limiter = (
            RateLimiter(rate_per_second, burst=burst)
            if burst is not None
            else RateLimiter(rate_per_second)
        )
        self.require_live_mode = require_live_mode
        self._get = transport_get or httpx.get
        self.throttled_seconds = 0.0
        #: Response headers from the most recent call. Providers publish their
        #: remaining quota here (OpenAQ's ``x-ratelimit-remaining``), which is
        #: unreadable if only the parsed body is returned.
        self.last_headers: dict[str, str] = {}

    def _assert_live_mode(self) -> None:
        if not self.require_live_mode:
            return
        if get_settings().connector_mode != "live":
            raise LiveModeDisabledError

    def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        """GET a response body as text, applying every reliability primitive.

        The JSON path is built on this one so both share a single chain of
        rate limiter, breaker, retry and timeout. Sources that answer in CSV
        (FIRMS) use this directly.

        Args:
            url: Absolute HTTPS URL. Some providers put the credential in the
                path, so this must never be logged.
            params: Query parameters.
            headers: Request headers. Credentials come from the environment
                and are never logged.

        Returns:
            The raw response body.

        Raises:
            LiveModeDisabledError: If the platform is in replay mode.
            CircuitOpenError: If this source's breaker is open.
            httpx.HTTPError: On transport failure after retries are exhausted.
        """
        self._assert_live_mode()
        if not self.breaker.allow():
            raise CircuitOpenError(self.source_id)

        self.throttled_seconds += self.limiter.acquire()

        @retry_http
        def _call() -> Any:
            response = self._get(url, params=params, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            return response

        try:
            response = _call()
        except Exception:
            self.breaker.record_failure()
            raise
        self.breaker.record_success()
        self.last_headers = {str(k).lower(): str(v) for k, v in dict(response.headers).items()}
        return response.text

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """GET and parse JSON, applying every reliability primitive.

        Args:
            url: Absolute HTTPS URL.
            params: Query parameters.
            headers: Request headers. Credentials come from the environment and
                are never logged.

        Returns:
            Parsed JSON body.

        Raises:
            LiveModeDisabledError: If the platform is in replay mode.
            CircuitOpenError: If this source's breaker is open.
            httpx.HTTPError: On transport failure after retries are exhausted.
        """
        return json.loads(self.get_text(url, params=params, headers=headers))


def fetch_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    source_id: str = "unknown",
) -> Any:
    """GET JSON from a live endpoint using a single-use hardened client.

    Prefer holding a :class:`LiveHttpClient` per source so that breaker and
    rate-limiter state survive across calls; this helper is for one-off probes.

    Args:
        url: Absolute HTTPS URL.
        headers: Optional request headers.
        timeout: Seconds.
        source_id: Source label for error messages.

    Returns:
        Parsed JSON.

    Raises:
        LiveModeDisabledError: If connector mode is not live.
        httpx.HTTPError: On transport failure after retries.
    """
    client = LiveHttpClient(source_id, timeout=timeout)
    return client.get_json(url, headers=headers)

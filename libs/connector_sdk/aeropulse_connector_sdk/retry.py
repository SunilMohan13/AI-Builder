"""HTTP retry policy with jittered exponential backoff."""

from collections.abc import Callable
from typing import TypeVar

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

T = TypeVar("T")

MAX_ATTEMPTS = 5

#: Status codes worth a second attempt. Everything else is a client-side
#: contract error that will fail identically however many times we resend it.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def is_retryable(exc: BaseException) -> bool:
    """Return True when an exception represents a transient transport fault.

    A 4xx such as ``401`` or ``404`` is a permanent contract failure: retrying
    it wastes the source's rate budget and delays the dead-letter path. Only
    throttling and server-side faults are replayed.

    Args:
        exc: Exception raised by an HTTP call.

    Returns:
        True if the call should be retried.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS
    # TimeoutError, ConnectError, ReadError and friends are all transient.
    return isinstance(exc, httpx.TransportError)


def retry_http(fn: Callable[..., T]) -> Callable[..., T]:
    """Retry an HTTP callable on throttling and 5xx/transport faults.

    Backoff is exponential with random jitter so that many connector workers
    recovering from the same source outage do not resynchronise into a
    thundering herd.

    Args:
        fn: Callable that may raise ``httpx.HTTPError``.

    Returns:
        Wrapped callable, at most :data:`MAX_ATTEMPTS` attempts.
    """
    return retry(
        reraise=True,
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=wait_exponential_jitter(initial=0.5, max=16.0, jitter=0.5),
        retry=retry_if_exception(is_retryable),
    )(fn)

"""
retrieval/failures.py — retry + circuit breaker (ADR-0005 §10, ADR-0004 policy).

Retry: config.MAX_RETRIES total attempts, exponential backoff, 20% jitter.
Circuit breaker: 3 consecutive MongoDB failures → open; blocks further calls.
  Once open, the breaker stays open for config.CIRCUIT_BREAKER_RESET_SECONDS,
  then allows a single half-open probe request through — the probe slot is
  reserved under _lock, so concurrent requests arriving after the cooldown do
  not all become "the probe" and hammer a recovering MongoDB. record_success()
  on that probe closes the breaker; record_failure() re-opens it and refreshes
  the timer; release_probe() frees the slot when the probing request finishes
  without reaching a MongoDB outcome. This guarantees the breaker is
  self-healing instead of permanently open until process restart.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

from pymongo.errors import ConnectionFailure, OperationFailure

from app import config

log = logging.getLogger("ai-orchestrator.retrieval.failures")

F = TypeVar("F", bound=Callable)

# Transient MongoDB errors that with_retry treats as retryable. Anything else
# (e.g. an invalid query, a Bedrock embedding error) propagates immediately —
# matches the (OperationFailure, ConnectionFailure) the router's dense-failure
# handler treats as expected.
RETRYABLE_EXC = (OperationFailure, ConnectionFailure)

_lock = threading.Lock()
_consecutive_failures: int = 0
_circuit_open: bool = False
_opened_at: float | None = None  # monotonic timestamp when breaker last opened
_probe_in_flight: bool = False  # half-open: one probe reserved at a time
_CB_THRESHOLD = 3


class CircuitBreakerOpen(Exception):
    """Raised when the MongoDB circuit breaker is open."""


def check_circuit() -> None:
    """Raise CircuitBreakerOpen if the breaker is tripped and still cooling down.

    Once the cooldown (config.CIRCUIT_BREAKER_RESET_SECONDS) has elapsed the
    breaker enters half-open: a SINGLE probe request is allowed through — the
    probe slot is reserved (_probe_in_flight) under _lock before returning, so
    every other concurrent request keeps getting CircuitBreakerOpen until the
    probe's outcome (record_success / record_failure) or release_probe() frees
    the slot. The fast path read stays lock-free; we only take _lock to make
    the half-open transition decision atomic.
    """
    global _probe_in_flight
    if not _circuit_open:
        return

    with _lock:
        # Re-check under the lock — another thread may have closed/re-opened it.
        if not _circuit_open:
            return
        elapsed = time.monotonic() - (_opened_at or 0.0)
        if elapsed >= config.CIRCUIT_BREAKER_RESET_SECONDS and not _probe_in_flight:
            _probe_in_flight = True  # reserve the single half-open probe slot
            log.warning(
                "circuit breaker HALF-OPEN — %.1fs elapsed, allowing probe request",
                elapsed,
            )
            return
        raise CircuitBreakerOpen(
            f"MongoDB circuit breaker open after {_consecutive_failures} consecutive failures"
        )


def record_success() -> None:
    global _consecutive_failures, _circuit_open, _opened_at, _probe_in_flight
    with _lock:
        _consecutive_failures = 0
        _circuit_open = False
        _opened_at = None
        _probe_in_flight = False


def record_failure() -> None:
    global _consecutive_failures, _circuit_open, _opened_at, _probe_in_flight
    with _lock:
        _consecutive_failures += 1
        _probe_in_flight = False
        if _consecutive_failures >= _CB_THRESHOLD:
            _circuit_open = True
            _opened_at = time.monotonic()  # (re)start the cooldown timer
            log.error(
                "circuit breaker OPEN — %d consecutive MongoDB failures",
                _consecutive_failures,
            )


def release_probe() -> None:
    """Free the half-open probe slot without recording an outcome.

    Called by the router when a request that may hold the probe slot finishes
    without ever reaching a MongoDB success/failure (e.g. a non-Mongo error in
    both retrieval paths). No-op when no probe is reserved. Without this, a
    leaked probe slot would block half-open recovery forever.
    """
    global _probe_in_flight
    with _lock:
        _probe_in_flight = False


def reset_circuit() -> None:
    """Test hook — resets breaker state between tests."""
    global _consecutive_failures, _circuit_open, _opened_at, _probe_in_flight
    with _lock:
        _consecutive_failures = 0
        _circuit_open = False
        _opened_at = None
        _probe_in_flight = False


def _backoff_seconds(attempt: int) -> float:
    base = 2.0 ** attempt
    jitter_range = base * config.RETRY_JITTER
    return max(0.05, base + random.uniform(-jitter_range, jitter_range))


def with_retry(fn: F) -> F:
    """Decorator: make config.MAX_RETRIES total attempts at fn with exponential
    backoff + jitter between attempts.

    Only transient MongoDB errors (RETRYABLE_EXC: OperationFailure,
    ConnectionFailure) are retried; any other exception (invalid query, Bedrock
    embedding error, etc.) propagates on the first occurrence so the router's
    generic except can handle it. After MAX_RETRIES attempts have all failed the
    last exception is re-raised.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        last_exc: BaseException | None = None
        for attempt in range(config.MAX_RETRIES):
            try:
                return fn(*args, **kwargs)
            except RETRYABLE_EXC as exc:
                last_exc = exc
                if attempt < config.MAX_RETRIES - 1:
                    delay = _backoff_seconds(attempt)
                    log.warning(
                        "%s attempt %d/%d failed (%s) — retry in %.2fs",
                        fn.__name__,
                        attempt + 1,
                        config.MAX_RETRIES,
                        type(exc).__name__,
                        delay,
                    )
                    time.sleep(delay)
        log.error(
            "%s exhausted %d attempts — %s", fn.__name__, config.MAX_RETRIES, last_exc
        )
        raise last_exc  # type: ignore[misc]

    return wrapper  # type: ignore[return-value]

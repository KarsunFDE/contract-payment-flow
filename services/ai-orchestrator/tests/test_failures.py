"""Tests for retrieval/failures.py circuit breaker — no MongoDB connection required."""
import pytest

from app.retrieval import failures


@pytest.fixture(autouse=True)
def _reset_breaker():
    failures.reset_circuit()
    yield
    failures.reset_circuit()


# --- breaker opens after threshold ---

def test_breaker_opens_after_consecutive_failures():
    for _ in range(failures._CB_THRESHOLD):
        failures.record_failure()
    with pytest.raises(failures.CircuitBreakerOpen):
        failures.check_circuit()


def test_breaker_stays_closed_below_threshold():
    for _ in range(failures._CB_THRESHOLD - 1):
        failures.record_failure()
    # below threshold — must not raise
    failures.check_circuit()


# --- half-open recovery (the fix) ---

def test_breaker_half_opens_after_cooldown(monkeypatch):
    # Make the cooldown effectively immediate so the probe is allowed through.
    monkeypatch.setattr(failures.config, "CIRCUIT_BREAKER_RESET_SECONDS", 0.0)
    for _ in range(failures._CB_THRESHOLD):
        failures.record_failure()
    # cooldown elapsed → half-open probe allowed (no raise)
    failures.check_circuit()


def test_breaker_blocks_during_cooldown(monkeypatch):
    monkeypatch.setattr(failures.config, "CIRCUIT_BREAKER_RESET_SECONDS", 999.0)
    for _ in range(failures._CB_THRESHOLD):
        failures.record_failure()
    with pytest.raises(failures.CircuitBreakerOpen):
        failures.check_circuit()


def test_success_on_probe_closes_breaker(monkeypatch):
    monkeypatch.setattr(failures.config, "CIRCUIT_BREAKER_RESET_SECONDS", 0.0)
    for _ in range(failures._CB_THRESHOLD):
        failures.record_failure()
    failures.check_circuit()  # half-open probe allowed
    failures.record_success()  # probe succeeded → close fully
    assert failures._circuit_open is False
    assert failures._consecutive_failures == 0
    failures.check_circuit()  # still closed


def test_failure_on_probe_reopens_and_refreshes_timer(monkeypatch):
    monkeypatch.setattr(failures.config, "CIRCUIT_BREAKER_RESET_SECONDS", 999.0)
    for _ in range(failures._CB_THRESHOLD):
        failures.record_failure()
    first_opened = failures._opened_at
    # probe fails → re-open and refresh timestamp
    failures.record_failure()
    assert failures._circuit_open is True
    assert failures._opened_at is not None
    assert failures._opened_at >= first_opened
    with pytest.raises(failures.CircuitBreakerOpen):
        failures.check_circuit()

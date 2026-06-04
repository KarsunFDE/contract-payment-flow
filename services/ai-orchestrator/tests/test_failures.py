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


def test_half_open_admits_single_probe_only(monkeypatch):
    """Once cooldown elapses only ONE request gets the probe slot — every
    other concurrent request keeps getting CircuitBreakerOpen until the
    probe's outcome is recorded."""
    monkeypatch.setattr(failures.config, "CIRCUIT_BREAKER_RESET_SECONDS", 0.0)
    for _ in range(failures._CB_THRESHOLD):
        failures.record_failure()
    failures.check_circuit()  # first caller reserves the probe slot
    with pytest.raises(failures.CircuitBreakerOpen):
        failures.check_circuit()  # second caller must NOT also be "the probe"


def test_release_probe_frees_slot_without_outcome(monkeypatch):
    monkeypatch.setattr(failures.config, "CIRCUIT_BREAKER_RESET_SECONDS", 0.0)
    for _ in range(failures._CB_THRESHOLD):
        failures.record_failure()
    failures.check_circuit()  # probe reserved
    # Probe request finished without a Mongo outcome (e.g. non-Mongo error) —
    # the slot must be freed so half-open recovery is not blocked forever.
    failures.release_probe()
    failures.check_circuit()  # next caller can take the probe slot


def test_probe_failure_frees_slot_and_reopens(monkeypatch):
    monkeypatch.setattr(failures.config, "CIRCUIT_BREAKER_RESET_SECONDS", 999.0)
    for _ in range(failures._CB_THRESHOLD):
        failures.record_failure()
    monkeypatch.setattr(failures.config, "CIRCUIT_BREAKER_RESET_SECONDS", 0.0)
    failures.check_circuit()  # probe reserved
    failures.record_failure()  # probe failed → re-open, slot freed
    assert failures._probe_in_flight is False
    assert failures._circuit_open is True


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

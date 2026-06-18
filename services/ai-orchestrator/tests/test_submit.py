"""
test_submit.py — submit_node + supersede_node (m3.md Phase 5, Steps 5.2-5.3).

modification_client and audit are stubbed; tests pin publish/cancel calls +
state returned. Also covers modification_client identity-guard negative paths
(anonymous / missing actor → raises before HTTP call).
"""
from __future__ import annotations

import pytest

from app.workflow import nodes_gate
from app.workflow.modification_client import _identity_headers
from app.workflow.state import compute_package_hash


def _make_state(**overrides):
    """Return a minimal valid state that passes submit_node's fail-closed guards."""
    base = {
        "correlation_id": "corr-1",
        "agency_id": "DOD",
        "form_draft_id": "draft-1",
        "co_user_id": "co-456",
        "co_role": "CO",
        "co_decision": "approved",
        "contractor_consent": "recorded",
        # A unilateral modType so consent_required_for returns False — submit proceeds.
        "block13_classification": {"mod_type": "unilateral_admin"},
    }
    base.update(overrides)
    # Bind the package_hash after all other fields are set so it matches current hash.
    base.setdefault("package_hash", compute_package_hash(base))
    return base


_STATE = _make_state()


# ---------------------------------------------------------------------------
# submit_node — happy path
# ---------------------------------------------------------------------------

def test_submit_calls_publish_with_consent_recorded(monkeypatch):
    published: list = []
    monkeypatch.setattr(nodes_gate.modification_client, "publish",
                        lambda draft_id, **kw: published.append({"draft_id": draft_id, **kw}))
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    result = nodes_gate.submit_node(_make_state(
        block13_classification={"mod_type": "bilateral_supplemental"},
        contractor_consent="recorded",
    ))

    assert result["gate_status"] == "SUBMITTED"
    assert result["co_execution"] == "executed"
    assert len(published) == 1
    assert published[0]["draft_id"] == "draft-1"
    assert published[0]["consent_recorded"] is True  # contractor_consent == "recorded"


# INVERTED (was: submit proceeds when contractor_consent is not "recorded")
# NEW behaviour: bilateral_supplemental requires consent → no consent recorded → RAISES.
def test_submit_consent_not_recorded_raises_when_required(monkeypatch):
    """submit_node raises (fail-CLOSED) when consent is required and not recorded."""
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    state = _make_state(
        block13_classification={"mod_type": "bilateral_supplemental"},
        contractor_consent="not_required",  # wrong — bilateral always needs recorded
    )
    with pytest.raises(RuntimeError, match="consent required"):
        nodes_gate.submit_node(state)


# INVERTED (was: submit proceeds when contractor_consent key is absent)
# NEW behaviour: bilateral_supplemental + no consent key → RAISES (fail-CLOSED).
def test_submit_no_consent_key_raises_when_required(monkeypatch):
    """submit_node raises (fail-CLOSED) when consent key absent and consent required."""
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    # Build state without contractor_consent; bilateral_supplemental requires it.
    base = {
        "correlation_id": "corr-1",
        "agency_id": "DOD",
        "form_draft_id": "draft-1",
        "co_user_id": "co-456",
        "co_role": "CO",
        "co_decision": "approved",
        "block13_classification": {"mod_type": "bilateral_supplemental"},
    }
    base["package_hash"] = compute_package_hash(base)
    with pytest.raises(RuntimeError, match="consent required"):
        nodes_gate.submit_node(base)


def test_submit_writes_audit(monkeypatch):
    monkeypatch.setattr(nodes_gate.modification_client, "publish",
                        lambda draft_id, **kw: None)
    audit_calls: list = []
    monkeypatch.setattr(nodes_gate, "record_event",
                        lambda state, event_type, details: audit_calls.append(event_type))

    nodes_gate.submit_node(_make_state())
    assert "modification_submitted" in audit_calls


def test_submit_fails_closed_on_anonymous_actor(monkeypatch):
    """submit_node raises when actor_id is 'anonymous' (non-anonymous enforcement)."""
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)
    state = _make_state(co_user_id="anonymous")
    with pytest.raises(ValueError, match="anonymous"):
        nodes_gate.submit_node(state)


def test_submit_fails_closed_on_missing_actor(monkeypatch):
    """submit_node raises when co_user_id is absent."""
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)
    base = {
        "correlation_id": "corr-1",
        "agency_id": "DOD",
        "form_draft_id": "draft-1",
        # no co_user_id, no co_role
        "co_decision": "approved",
        "contractor_consent": "recorded",
        "block13_classification": {"mod_type": "unilateral_admin"},
    }
    base["package_hash"] = compute_package_hash(base)
    with pytest.raises(ValueError, match="co_user_id"):
        nodes_gate.submit_node(base)


def test_submit_fails_closed_on_package_hash_mismatch(monkeypatch):
    """submit_node raises when current hash differs from the approved hash (fail-CLOSED)."""
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)
    state = _make_state(
        package_hash="0000000000000000000000000000000000000000000000000000000000000000",
    )
    with pytest.raises(RuntimeError, match="package_hash mismatch"):
        nodes_gate.submit_node(state)


def test_submit_unilateral_consent_not_required(monkeypatch):
    """unilateral_admin modType → consent_required=False → submit proceeds without consent."""
    published: list = []
    monkeypatch.setattr(nodes_gate.modification_client, "publish",
                        lambda draft_id, **kw: published.append(kw))
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    state = _make_state(
        block13_classification={"mod_type": "unilateral_admin"},
        contractor_consent="pending",  # not "recorded" — but consent not required
    )
    result = nodes_gate.submit_node(state)
    assert result["gate_status"] == "SUBMITTED"
    assert published[0]["consent_recorded"] is False


# ---------------------------------------------------------------------------
# supersede_node
# ---------------------------------------------------------------------------

def test_supersede_cancels_draft(monkeypatch):
    cancelled: list = []
    monkeypatch.setattr(nodes_gate.modification_client, "cancel_draft",
                        lambda draft_id, **kw: cancelled.append(draft_id))
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    result = nodes_gate.supersede_node({**_STATE, "co_decision": "denied"})
    assert result["co_execution"] == "aborted"
    assert "draft-1" in cancelled


def test_supersede_writes_audit(monkeypatch):
    monkeypatch.setattr(nodes_gate.modification_client, "cancel_draft",
                        lambda d, **kw: None)
    audit_calls: list = []
    monkeypatch.setattr(nodes_gate, "record_event",
                        lambda state, event_type, details: audit_calls.append(event_type))

    nodes_gate.supersede_node({**_STATE, "co_decision": "denied"})
    assert "package_superseded" in audit_calls


def test_supersede_no_draft_id(monkeypatch):
    monkeypatch.setattr(nodes_gate.modification_client, "cancel_draft",
                        lambda d, **kw: (_ for _ in ()).throw(Exception("should not call")))
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    state = {k: v for k, v in _STATE.items() if k != "form_draft_id"}
    result = nodes_gate.supersede_node(state)
    assert result["co_execution"] == "aborted"


# ---------------------------------------------------------------------------
# NEW negative-path coverage — modification_client identity guards
# (anonymous / missing identity → raises before any HTTP call)
# ---------------------------------------------------------------------------

def test_modification_client_anonymous_actor_raises():
    """_identity_headers raises RuntimeError when actor_id is 'anonymous'."""
    with pytest.raises(RuntimeError, match="anonymous"):
        _identity_headers(
            actor_id="anonymous",
            actor_role="CO",
            agency_id="DOD",
            correlation_id="corr-1",
        )


def test_modification_client_missing_actor_id_raises():
    """_identity_headers raises RuntimeError when actor_id is blank."""
    with pytest.raises(RuntimeError, match="actor_id"):
        _identity_headers(
            actor_id="",
            actor_role="CO",
            agency_id="DOD",
            correlation_id="corr-1",
        )


def test_modification_client_missing_actor_role_raises():
    """_identity_headers raises RuntimeError when actor_role is blank."""
    with pytest.raises(RuntimeError, match="actor_role"):
        _identity_headers(
            actor_id="co-123",
            actor_role="",
            agency_id="DOD",
            correlation_id="corr-1",
        )


def test_modification_client_missing_agency_id_raises():
    """_identity_headers raises RuntimeError when agency_id is blank."""
    with pytest.raises(RuntimeError, match="agency_id"):
        _identity_headers(
            actor_id="co-123",
            actor_role="CO",
            agency_id="",
            correlation_id="corr-1",
        )


def test_modification_client_valid_identity_returns_headers():
    """_identity_headers returns the expected header dict when all fields are present."""
    headers = _identity_headers(
        actor_id="co-123",
        actor_role="CO",
        agency_id="DOD",
        correlation_id="corr-1",
    )
    assert headers["X-User-Id"] == "co-123"
    assert headers["X-User-Role"] == "CO"
    assert headers["X-Tenant-Id"] == "DOD"
    assert headers["X-Correlation-Id"] == "corr-1"

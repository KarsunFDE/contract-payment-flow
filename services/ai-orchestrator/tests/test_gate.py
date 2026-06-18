"""
test_gate.py — CO gate routing logic (m3.md Phase 4, Steps 4.1-4.3).

interrupt() and audit are stubbed; tests pin the routing decisions.
"""
from __future__ import annotations

from langgraph.graph import END

from app.workflow import nodes_gate
from app.workflow.state import compute_package_hash


# ---------------------------------------------------------------------------
# route_after_co_gate
# ---------------------------------------------------------------------------

def test_route_deny_to_supersede():
    state = {"co_decision": "denied", "modification_bilateral": True}
    assert nodes_gate.route_after_co_gate(state) == "supersede"


def test_route_approve_bilateral_to_consent_gate():
    state = {"co_decision": "approved", "modification_bilateral": True}
    assert nodes_gate.route_after_co_gate(state) == "consent_gate"


def test_route_approve_unilateral_to_submit():
    state = {"co_decision": "approved", "modification_bilateral": False}
    assert nodes_gate.route_after_co_gate(state) == "submit"


# INVERTED (was: missing bilateral defaults to submit — tested old bilateral-flag behaviour)
# NEW behaviour: unknown/missing/empty co_decision is a security anomaly → always supersede,
# never submit or consent_gate (fail-CLOSED on every ambiguous/unknown/missing decision).
def test_route_missing_decision_routes_to_supersede():
    """None / absent co_decision must route to supersede, never submit (fail-CLOSED)."""
    state = {}  # no co_decision key at all
    assert nodes_gate.route_after_co_gate(state) == "supersede"


def test_route_empty_decision_routes_to_supersede():
    """Empty-string co_decision is outside the valid enum → supersede."""
    state = {"co_decision": ""}
    assert nodes_gate.route_after_co_gate(state) == "supersede"


def test_route_unknown_decision_routes_to_supersede():
    """Typo / injected payload that doesn't match {"approved","denied"} → supersede."""
    state = {"co_decision": "APPROVE"}  # capitalisation typo
    assert nodes_gate.route_after_co_gate(state) == "supersede"


def test_route_approve_missing_bilateral_defaults_to_unilateral_submit():
    """Approved + absent bilateral → unilateral path → submit (not consent_gate).
    modification_bilateral must be explicitly True for the bilateral path."""
    state = {"co_decision": "approved"}  # no modification_bilateral key
    assert nodes_gate.route_after_co_gate(state) == "submit"


# ---------------------------------------------------------------------------
# route_after_consent_gate
# ---------------------------------------------------------------------------

def test_route_consent_recorded_to_submit():
    assert nodes_gate.route_after_consent_gate({"contractor_consent": "recorded"}) == "submit"


def test_route_consent_pending_to_end():
    assert nodes_gate.route_after_consent_gate({"contractor_consent": "pending"}) == END


def test_route_consent_missing_to_end():
    assert nodes_gate.route_after_consent_gate({}) == END


# ---------------------------------------------------------------------------
# consent_gate_node — package_hash re-verification
# ---------------------------------------------------------------------------

def test_consent_gate_signed(monkeypatch):
    state = {
        "correlation_id": "c-1",
        "form_draft_id": "d-1",
        "co_user_id": "co-123",
        "co_role": "CO",
    }
    # package_hash must match current hash so the gate doesn't abort.
    state["package_hash"] = compute_package_hash(state)

    monkeypatch.setattr(nodes_gate, "interrupt", lambda payload: {"signed": True})
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    result = nodes_gate.consent_gate_node(state)
    assert result == {"contractor_consent": "recorded"}


def test_consent_gate_unsigned(monkeypatch):
    state = {
        "correlation_id": "c-1",
        "form_draft_id": "d-1",
        "co_user_id": "co-123",
        "co_role": "CO",
    }
    state["package_hash"] = compute_package_hash(state)

    monkeypatch.setattr(nodes_gate, "interrupt", lambda payload: {"signed": False})
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    result = nodes_gate.consent_gate_node(state)
    assert result["contractor_consent"] == "pending"
    assert result["gate_status"] == "AWAITING_CONTRACTOR_CONSENT"


def test_consent_gate_no_signed_key(monkeypatch):
    state = {
        "correlation_id": "c-1",
        "form_draft_id": "d-1",
        "co_user_id": "co-123",
        "co_role": "CO",
    }
    state["package_hash"] = compute_package_hash(state)

    monkeypatch.setattr(nodes_gate, "interrupt", lambda payload: {})
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    result = nodes_gate.consent_gate_node(state)
    assert result["contractor_consent"] == "pending"


def test_consent_gate_hash_mismatch_blocks(monkeypatch):
    """Package mutated after CO approval → consent_gate returns hash_mismatch (fail-CLOSED)."""
    state = {
        "correlation_id": "c-1",
        "form_draft_id": "d-1",
        "co_user_id": "co-123",
        "co_role": "CO",
        # package_hash set to a stale value — current hash will differ.
        "package_hash": "0000000000000000000000000000000000000000000000000000000000000000",
    }
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    result = nodes_gate.consent_gate_node(state)
    assert result["contractor_consent"] == "hash_mismatch"
    assert result["gate_status"] == "BLOCKED_HASH_MISMATCH"
    assert result["co_execution"] == "aborted"

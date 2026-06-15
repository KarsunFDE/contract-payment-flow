"""
test_gate.py — CO gate routing logic (m3.md Phase 4, Steps 4.1-4.3).

interrupt() and audit are stubbed; tests pin the routing decisions.
"""
from __future__ import annotations

from langgraph.graph import END

from app.workflow import nodes_gate


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


def test_route_approve_missing_bilateral_defaults_to_submit():
    # modification_bilateral absent -> falsy -> unilateral path (safe default)
    state = {"co_decision": "approved"}
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
# consent_gate_node
# ---------------------------------------------------------------------------

def test_consent_gate_signed(monkeypatch):
    monkeypatch.setattr(nodes_gate, "interrupt", lambda payload: {"signed": True})
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    result = nodes_gate.consent_gate_node({"correlation_id": "c-1", "form_draft_id": "d-1"})
    assert result == {"contractor_consent": "recorded"}


def test_consent_gate_unsigned(monkeypatch):
    monkeypatch.setattr(nodes_gate, "interrupt", lambda payload: {"signed": False})
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    result = nodes_gate.consent_gate_node({"correlation_id": "c-1", "form_draft_id": "d-1"})
    assert result["contractor_consent"] == "pending"
    assert result["gate_status"] == "AWAITING_CONTRACTOR_CONSENT"


def test_consent_gate_no_signed_key(monkeypatch):
    monkeypatch.setattr(nodes_gate, "interrupt", lambda payload: {})
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    result = nodes_gate.consent_gate_node({"correlation_id": "c-1", "form_draft_id": "d-1"})
    assert result["contractor_consent"] == "pending"

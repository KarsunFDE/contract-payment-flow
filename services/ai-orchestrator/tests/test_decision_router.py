"""
test_decision_router.py — three-lane routing + auto-process idempotency (m3.md
Steps 7.4-7.5).

The router is a pure sorter over adjudications + policy, so the tests pin each lane
from a crafted state. record_event is stubbed (no Mongo); the lane decision is what
matters here.
"""
from __future__ import annotations

import pytest

from app.workflow import nodes_triage


@pytest.fixture(autouse=True)
def _stub_audit(monkeypatch):
    """Audit writes are fail-closed against Mongo; stub them for unit isolation."""
    monkeypatch.setattr(nodes_triage, "record_event", lambda *a, **k: None)


def test_improper_invoice_returns():
    state = {"item_type": "invoice", "invoice": {"missing_elements": ["invoice_date"]},
             "adjudications": []}
    command = nodes_triage.decision_router_node(state)
    assert command.goto == "return_route"
    assert command.update["lane"] == "return_route"


def test_clean_reversible_invoice_auto_processes():
    state = {"item_type": "invoice", "adjudications": [],
             "invoice": {"action": "invoice_intake_ack", "reversible": True,
                         "within_delegated_authority": True, "amount": 100, "threshold": 1000}}
    assert nodes_triage.decision_router_node(state).goto == "auto_process"


def test_modification_escalates_to_hitl():
    """A modification's action defaults to the reserved modification_execution -> HITL."""
    state = {"item_type": "modification", "change_request": {}, "adjudications": []}
    assert nodes_triage.decision_router_node(state).goto == "hitl_escalate"


def test_substantiated_flag_forces_escalation():
    state = {"item_type": "invoice", "adjudications": [{"verdict": "substantiated"}],
             "invoice": {"action": "ack", "reversible": True,
                         "within_delegated_authority": True, "amount": 1, "threshold": 1000}}
    assert nodes_triage.decision_router_node(state).goto == "hitl_escalate"


def test_auto_process_is_idempotent(monkeypatch):
    """A replayed idempotency_key is a no-op (no double-pay)."""
    monkeypatch.setattr(nodes_triage.execution_log, "already_processed", lambda key: True)
    result = nodes_triage.auto_process_node({"idempotency_key": "k-1"})
    assert result["gate_status"] == "ALREADY_PROCESSED"


def test_auto_process_executes_first_time(monkeypatch):
    seen = {}
    monkeypatch.setattr(nodes_triage.execution_log, "already_processed", lambda key: False)
    monkeypatch.setattr(nodes_triage.mock_executor, "process",
                        lambda draft_id, key: seen.update(draft_id=draft_id, key=key))
    result = nodes_triage.auto_process_node(
        {"idempotency_key": "k-1", "form_draft_id": "d-1", "disposition_rationale": "clean"})
    assert result["gate_status"] == "AUTO_PROCESSED"
    assert seen == {"draft_id": "d-1", "key": "k-1"}

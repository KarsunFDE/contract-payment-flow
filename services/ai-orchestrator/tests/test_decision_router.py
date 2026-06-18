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


# FIXED (was: monkeypatched execution_log.already_processed — old TOCTOU API removed)
# NEW behaviour: atomic claim() replaces already_processed()+mark_processed(); DuplicateKeyError
# from the unique index is the replay guard. Stub claim() returning False → replay no-op.
def test_auto_process_is_idempotent(monkeypatch):
    """A replayed idempotency_key (claim returns False) is a no-op (no double-pay)."""
    monkeypatch.setattr(nodes_triage.execution_log, "claim", lambda key: False)
    result = nodes_triage.auto_process_node({"idempotency_key": "k-1"})
    assert result["gate_status"] == "ALREADY_PROCESSED"


# FIXED (was: monkeypatched execution_log.already_processed — old API removed)
# NEW: stub claim() returning True (first claimant) and mark_done/mark_failed.
def test_auto_process_executes_first_time(monkeypatch):
    seen = {}
    monkeypatch.setattr(nodes_triage.execution_log, "claim", lambda key: True)
    monkeypatch.setattr(nodes_triage.execution_log, "mark_done",
                        lambda key, draft_id: seen.update(done=True))
    monkeypatch.setattr(nodes_triage.execution_log, "mark_failed",
                        lambda key, reason: seen.update(failed=True))
    monkeypatch.setattr(nodes_triage.mock_executor, "process",
                        lambda draft_id, key: seen.update(draft_id=draft_id, key=key))
    result = nodes_triage.auto_process_node(
        {"idempotency_key": "k-1", "form_draft_id": "d-1", "disposition_rationale": "clean"})
    assert result["gate_status"] == "AUTO_PROCESSED"
    assert seen["draft_id"] == "d-1"
    assert seen["key"] == "k-1"
    assert seen.get("done") is True


# ---------------------------------------------------------------------------
# NEW negative-path coverage
# ---------------------------------------------------------------------------

def test_decision_router_missing_amount_escalates():
    """Item missing 'amount' → fail-closed → escalate, never auto-process."""
    state = {
        "item_type": "invoice",
        "adjudications": [],
        "invoice": {
            "action": "invoice_intake_ack",
            "reversible": True,
            "within_delegated_authority": True,
            # amount absent — threshold present
            "threshold": 1000,
        },
    }
    assert nodes_triage.decision_router_node(state).goto == "hitl_escalate"


def test_decision_router_missing_threshold_escalates():
    """Item missing 'threshold' → fail-closed → escalate, never auto-process."""
    state = {
        "item_type": "invoice",
        "adjudications": [],
        "invoice": {
            "action": "invoice_intake_ack",
            "reversible": True,
            "within_delegated_authority": True,
            "amount": 500,
            # threshold absent
        },
    }
    assert nodes_triage.decision_router_node(state).goto == "hitl_escalate"


def test_auto_process_missing_idempotency_key_fails_closed(monkeypatch):
    """auto_process_node without an idempotency_key refuses to execute (fail-CLOSED)."""
    result = nodes_triage.auto_process_node({})
    assert result["gate_status"] == "MISSING_IDEMPOTENCY_KEY_AWAITING_REVIEW"


def test_auto_process_idempotency_replay_is_noop(monkeypatch):
    """Second claim() of the same key (DuplicateKeyError path) is a no-op, no double-execute."""
    executed: list = []
    # claim returns False on the second call — simulates DuplicateKeyError path.
    monkeypatch.setattr(nodes_triage.execution_log, "claim", lambda key: False)
    monkeypatch.setattr(nodes_triage.mock_executor, "process",
                        lambda draft_id, key: executed.append(key))
    result = nodes_triage.auto_process_node({"idempotency_key": "k-dup"})
    assert result["gate_status"] == "ALREADY_PROCESSED"
    assert executed == [], "side effect must not run on replay"


# ---------------------------------------------------------------------------
# NEW negative-path coverage — adjudicator dismissed-with-bad-cite hardening
# ---------------------------------------------------------------------------

from app.workflow.llm import JsonResult
from app.workflow.nodes_triage import Adjudication


def _adj_result(verdict, far_cite=""):
    """Build a fake call_json return for the adjudicator."""
    adj = Adjudication(verdict=verdict, far_cite=far_cite)
    return JsonResult(data=adj, model="m", model_version="v1", stub=False)


def test_adjudicator_dismissed_with_empty_cite_stays_substantiated(monkeypatch):
    """A 'dismissed' verdict with empty far_cite must be overridden to 'substantiated'."""
    monkeypatch.setattr(nodes_triage.retrieve_client, "retrieve_for_state",
                        lambda *a, **k: [{"chunk_ref": "FAR-43.103"}])
    # Model returns dismissed but with no far_cite — injection-hardening check.
    monkeypatch.setattr(nodes_triage, "call_json",
                        lambda *a, **k: _adj_result("dismissed", far_cite=""))

    state = {
        "correlation_id": "c-1",
        "item_type": "modification",
        "anomaly_flags": [{"code": "OUT_OF_SCOPE", "detail": "scope change", "far_part": "43"}],
    }
    result = nodes_triage.adjudicator_node(state)
    assert result["adjudications"][0]["verdict"] == "substantiated"
    assert result["adjudications"][0].get("note") == "dismissal_rejected_cite_not_in_retrieved_set"


def test_adjudicator_dismissed_with_unknown_cite_stays_substantiated(monkeypatch):
    """A 'dismissed' verdict whose far_cite is not in the retrieved set → substantiated."""
    monkeypatch.setattr(nodes_triage.retrieve_client, "retrieve_for_state",
                        lambda *a, **k: [{"chunk_ref": "FAR-43.103"}])
    # Model claims to cite a clause that was NOT in the retrieved set.
    monkeypatch.setattr(nodes_triage, "call_json",
                        lambda *a, **k: _adj_result("dismissed", far_cite="FAR-32.905"))

    state = {
        "correlation_id": "c-1",
        "item_type": "modification",
        "anomaly_flags": [{"code": "OUT_OF_SCOPE", "detail": "scope change", "far_part": "43"}],
    }
    result = nodes_triage.adjudicator_node(state)
    assert result["adjudications"][0]["verdict"] == "substantiated"


def test_adjudicator_dismissed_with_valid_cite_is_accepted(monkeypatch):
    """A 'dismissed' verdict whose far_cite IS in the retrieved set is honoured."""
    monkeypatch.setattr(nodes_triage.retrieve_client, "retrieve_for_state",
                        lambda *a, **k: [{"chunk_ref": "FAR-43.103"}])
    monkeypatch.setattr(nodes_triage, "call_json",
                        lambda *a, **k: _adj_result("dismissed", far_cite="FAR-43.103"))

    state = {
        "correlation_id": "c-1",
        "item_type": "modification",
        "anomaly_flags": [{"code": "OUT_OF_SCOPE", "detail": "scope change", "far_part": "43"}],
    }
    result = nodes_triage.adjudicator_node(state)
    assert result["adjudications"][0]["verdict"] == "dismissed"


def test_adjudicator_retrieval_error_keeps_flag_substantiated(monkeypatch):
    """Retrieval error during adjudication keeps the flag as substantiated (fail-safe)."""
    from app.workflow import retrieve_client

    monkeypatch.setattr(nodes_triage.retrieve_client, "retrieve_for_state",
                        lambda *a, **k: (_ for _ in ()).throw(
                            retrieve_client.RetrieveError("down")))

    state = {
        "correlation_id": "c-1",
        "item_type": "modification",
        "anomaly_flags": [{"code": "OUT_OF_SCOPE", "detail": "scope change", "far_part": "43"}],
    }
    result = nodes_triage.adjudicator_node(state)
    adj = result["adjudications"][0]
    assert adj["verdict"] == "substantiated"
    assert adj.get("note") == "adjudication_unavailable"

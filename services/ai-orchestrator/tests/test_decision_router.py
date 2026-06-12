"""
Tasks B4/B5 — decision router (three lanes, default-deny) + lane nodes
(m3.md Steps 7.4-7.5). Uses the conftest fake Mongo: the router's mandatory
item_triaged audit write and the auto lane's idempotency ledger exercise their
real fail-closed logic in memory.
"""
from __future__ import annotations

import pytest

from app.workflow import nodes_triage
from app.workflow.audit_events import WORKFLOW_AUDIT_COLLECTION
from app.workflow.execution_log import WORKFLOW_EXECUTIONS_COLLECTION


def _invoice_state(**overrides) -> dict:
    state = {
        "correlation_id": "33333333-3333-3333-3333-333333333333",
        "agency_id": "agency-gsa",
        "contract_number": "GS-35F-0001V",
        "item_type": "invoice",
        "idempotency_key": "inv-001-key",
        "change_request": {
            "amount": 1200.0,
            "within_delegated_authority": True,
        },
        "anomaly_flags": [],
        "adjudications": [],
    }
    state.update(overrides)
    return state


def test_clean_small_invoice_goes_to_auto_lane(fake_mongo):
    command = nodes_triage.decision_router_node(_invoice_state())
    assert command.goto == "auto_process"
    assert command.update["lane"] == "auto_process"


def test_modification_always_escalates_reserved_action(fake_mongo):
    """FAR 43.102 — modification execution is reserved; never the auto lane."""
    state = _invoice_state(item_type="modification", idempotency_key="mod-key",
                           change_request={"scope": "add CLIN",
                                           "within_delegated_authority": True,
                                           "amount": 10.0})
    command = nodes_triage.decision_router_node(state)
    assert command.goto == "hitl_escalate"
    assert "reserved action" in command.update["disposition_rationale"]


def test_improper_invoice_routes_to_return_lane(fake_mongo):
    state = _invoice_state(anomaly_flags=[
        {"code": "INVOICE_MISSING_FAR_32_905_ELEMENTS",
         "detail": "missing invoice_number", "far_part": "32.905",
         "severity": "high"},
    ])
    command = nodes_triage.decision_router_node(state)
    assert command.goto == "return_route"
    assert "32.905" in command.update["disposition_rationale"]


def test_substantiated_flag_blocks_auto_lane(fake_mongo):
    state = _invoice_state(adjudications=[
        {"flag_code": "UNIT_PRICE_VARIANCE", "verdict": "substantiated",
         "far_cite": "31.201-3", "precedent_id": None},
    ])
    command = nodes_triage.decision_router_node(state)
    assert command.goto == "hitl_escalate"


def test_failed_closed_adjudication_counts_as_substantiated(fake_mongo):
    """An unverifiable flag escalates — it never clears the auto lane."""
    state = _invoice_state(adjudications=[
        {"flag_code": "UNALLOWABLE_COST_SUSPECT", "verdict": "error_failed_closed",
         "far_cite": "31.205-14", "precedent_id": None},
    ])
    assert nodes_triage.decision_router_node(state).goto == "hitl_escalate"


def test_dismissed_flags_do_not_block_auto_lane(fake_mongo):
    state = _invoice_state(adjudications=[
        {"flag_code": "UNIT_PRICE_VARIANCE", "verdict": "dismissed",
         "far_cite": None, "precedent_id": None},
    ])
    assert nodes_triage.decision_router_node(state).goto == "auto_process"


def test_over_threshold_invoice_escalates(fake_mongo):
    state = _invoice_state(change_request={"amount": 50_000.0,
                                           "within_delegated_authority": True})
    assert nodes_triage.decision_router_node(state).goto == "hitl_escalate"


def test_missing_delegated_authority_escalates_default_deny(fake_mongo):
    state = _invoice_state(change_request={"amount": 100.0})
    assert nodes_triage.decision_router_node(state).goto == "hitl_escalate"


def test_router_audits_every_item(fake_mongo):
    """REQ-AGT-4 / Phase 6: item_triaged written for EVERY routed item."""
    nodes_triage.decision_router_node(_invoice_state())
    records = fake_mongo[WORKFLOW_AUDIT_COLLECTION].docs
    assert len(records) == 1
    assert records[0]["event_type"] == "item_triaged"
    assert records[0]["details"]["lane"] == "auto_process"
    assert records[0]["correlation_id"] == "33333333-3333-3333-3333-333333333333"


def test_auto_process_executes_once_and_audits(fake_mongo):
    state = _invoice_state(lane="auto_process",
                           disposition_rationale="policy-clean")
    update = nodes_triage.auto_process_node(state)
    assert update["gate_status"] == "AUTO_PROCESSED"
    assert fake_mongo[WORKFLOW_EXECUTIONS_COLLECTION].count_documents(
        {"idempotency_key": "inv-001-key"}) == 1
    events = [r["event_type"] for r in fake_mongo[WORKFLOW_AUDIT_COLLECTION].docs]
    assert "auto_processed" in events


def test_auto_process_replay_is_a_noop(fake_mongo):
    """REQ-AGT-2: a replayed idempotency_key never double-pays."""
    state = _invoice_state(lane="auto_process", disposition_rationale="x")
    nodes_triage.auto_process_node(state)
    update = nodes_triage.auto_process_node(state)
    assert update["gate_status"] == "ALREADY_PROCESSED"
    assert fake_mongo[WORKFLOW_EXECUTIONS_COLLECTION].count_documents(
        {"idempotency_key": "inv-001-key"}) == 1


def test_auto_process_rejects_missing_idempotency_key(fake_mongo):
    """No dedupe key -> no execution (fail toward no-pay)."""
    state = _invoice_state(idempotency_key="")
    with pytest.raises(ValueError):
        nodes_triage.auto_process_node(state)


def test_return_route_node_sets_status():
    update = nodes_triage.return_route_node({"disposition_rationale": "improper"})
    assert update["gate_status"] == "RETURNED_FOR_CORRECTION"


def test_triage_graph_end_to_end_auto_lane(fake_mongo, monkeypatch):
    """Full outer-graph run: clean small invoice -> Command routes to the auto
    lane, the ledger records once, and the audit trail carries both events."""
    from app.workflow import llm
    from app.workflow.triage_graph import build_triage_graph

    # No LLM in this path (no scope pass for invoices, no flags to adjudicate),
    # but guard anyway so a stub Bedrock can never hang the test.
    def _reject(prompt, *, schema, system=None, **kwargs):
        raise llm.LLMOutputError("stub (test)")
    monkeypatch.setattr(llm, "call_json", _reject)

    # A PROPER invoice (all FAR 32.905 elements) — the real detector runs in
    # this path and an element gap would correctly divert to return_route.
    state = _invoice_state(change_request={
        "vendor_name": "Acme Integration LLC",
        "invoice_number": "INV-001",
        "invoice_date": "2026-06-01",
        "contract_number": "GS-35F-0001V",
        "amount": 1200.0,
        "description": "monthly maintenance",
        "line_items": [{"description": "maintenance", "unit_price": 100.0,
                        "contracted_unit_price": 100.0}],
        "within_delegated_authority": True,
    })
    graph = build_triage_graph().compile()
    result = graph.invoke(state)

    assert result["lane"] == "auto_process"
    assert result["gate_status"] == "AUTO_PROCESSED"
    assert fake_mongo[WORKFLOW_EXECUTIONS_COLLECTION].count_documents(
        {"idempotency_key": "inv-001-key"}) == 1
    events = [r["event_type"] for r in fake_mongo[WORKFLOW_AUDIT_COLLECTION].docs]
    assert events == ["item_triaged", "auto_processed"]

"""
nodes_lookup.py — Person A: lookup front end (m3.md Phase 1, Steps 1.1-1.3).

Three nodes in sequence (lookup → validate → populate) plus the bridge edge to
classify (Person B's node). Deterministic, no LLM — SAM.gov is called as plain
backend code so the agent can never widen the query or cross agency boundaries
(ADR-0006 §"Lookup is not an LLM step"; ADR-0005 §11).

The module-level _sam_gov singleton is the Phase 1 mock; swap for the live
SAM.gov adapter later by replacing this one assignment.
"""
from __future__ import annotations

from langgraph.graph import StateGraph

from app.workflow import contract_lookup
from app.workflow.audit_events import record_event
from app.workflow.mock_sam_gov_client import MockSamGovClient
from app.workflow.state import WorkflowState

_sam_gov = MockSamGovClient()


def lookup_node(state: WorkflowState) -> dict:
    """Resolve the contract number via the SAM.gov client (deterministic, no LLM)."""
    number = state["contract_number"]
    agency_id = state.get("agency_id") or state.get("change_request", {}).get("agency_id", "")

    record = contract_lookup.find_by_number(number, agency_id, _sam_gov)
    record_event(state, "contract_lookup", {
        "contract_number": number,
        "agency_id": agency_id,
        "match": record.get("match", "unknown"),
    })
    return {"contract_record": record}


def validate_lookup_node(state: WorkflowState) -> dict:
    """Check the lookup result. On any problem, flag for CO review."""
    match = state["contract_record"].get("match")
    if match == "found":
        return {"gate_status": "OK"}
    return {"gate_status": "CONTRACT_NOT_FOUND_AWAITING_CO_REVIEW"}


def populate_fields_node(state: WorkflowState) -> dict:
    """Copy authoritative values into SF-30 blocks, each with a source citation."""
    record = state["contract_record"]
    citation = record.get("source_citation", {})
    fields = {
        block: {"value": value, "source_citation": citation}
        for block, value in record.get("static_fields", {}).items()
    }
    record_event(state, "static_fields_populated", {"blocks": list(fields.keys())})
    return {"populated_fields": fields}


def register(builder: StateGraph) -> None:
    """Add the lookup nodes + their edges, including the bridge to classify.

    The downstream node ("classify") is referenced by NAME, not import — Person B
    owns it. LangGraph resolves the reference at compile time.
    """
    builder.add_node("lookup", lookup_node)
    builder.add_node("validate", validate_lookup_node)
    builder.add_node("populate", populate_fields_node)

    builder.add_edge("lookup", "validate")
    builder.add_edge("validate", "populate")
    builder.add_edge("populate", "classify")

"""
nodes_lookup.py — Person A: lookup front end (m3.md Phase 1, Steps 1.1-1.3).

Three nodes in sequence (lookup → validate → populate) plus the bridge edge to
classify (Person B's node). Deterministic, no LLM — SAM.gov is called as plain
backend code so the agent can never widen the query or cross agency boundaries
(ADR-0006 §"Lookup is not an LLM step"; ADR-0005 §11).

The module-level _sam_gov singleton is the Phase 1 mock; swap for the live
SAM.gov adapter later by replacing this one assignment.

validate_lookup_node is a CONDITIONAL gate: only a "found" match continues to
populate. All blocking statuses are sticky — a later node may NEVER overwrite
a blocking gate_status with "OK" (see _is_blocking below, shared with
nodes_retrieval and nodes_form).
"""
from __future__ import annotations

from langgraph.graph import StateGraph

from app.workflow import contract_lookup
from app.workflow.audit_events import record_event
from app.workflow.mock_sam_gov_client import MockSamGovClient
from app.workflow.state import WorkflowState

_sam_gov = MockSamGovClient()

# Statuses that are terminal — no downstream node may clobber them to "OK".
# Shared constant: add any new blocking status string here so all routing
# functions in this module (and callers) stay in sync automatically.
BLOCKING_STATUSES: frozenset[str] = frozenset({
    "CONTRACT_NOT_FOUND_AWAITING_CO_REVIEW",
    "RAG_FAILED_AWAITING_CO_REVIEW",
    "FAITHFULNESS_FAILED_AWAITING_CO_REVIEW",
    "BLOCK13_UNCLASSIFIED_AWAITING_CO_REVIEW",
    "CLASSIFICATION_MISSING_AWAITING_CO_REVIEW",
})


def is_blocking(status: str | None) -> bool:
    """Return True when *status* is a terminal CO-review state that must not be overwritten."""
    return status in BLOCKING_STATUSES


def lookup_node(state: WorkflowState) -> dict:
    """Resolve the contract number via the SAM.gov client (deterministic, no LLM).

    Identity fields (agency_id) are taken ONLY from verified workflow state —
    never from the change_request body (ADR-0006 §"Client-Controlled Identity").
    """
    number = state["contract_number"]
    # agency_id must come from the verified state injected by the auth router.
    # If absent from verified state, fail closed rather than trusting the body.
    agency_id = state.get("agency_id")
    if not agency_id:
        record_event(state, "contract_lookup_failed", {
            "contract_number": number,
            "reason": "agency_id missing from verified state",
        })
        return {"gate_status": "CONTRACT_NOT_FOUND_AWAITING_CO_REVIEW"}

    record = contract_lookup.find_by_number(number, agency_id, _sam_gov)
    record_event(state, "contract_lookup", {
        "contract_number": number,
        "agency_id": agency_id,
        "match": record.get("match", "unknown"),
    })
    return {"contract_record": record}


def validate_lookup_node(state: WorkflowState) -> dict:
    """Check the lookup result. On any problem, flag for CO review.

    This is a pure status-setter only; routing is handled by the conditional
    edge registered in `register` via `route_after_lookup`.
    """
    # If a prior node already set a blocking status, do not overwrite it.
    if is_blocking(state.get("gate_status")):
        return {}

    match = state.get("contract_record", {}).get("match")
    if match == "found":
        return {"gate_status": "OK"}
    return {"gate_status": "CONTRACT_NOT_FOUND_AWAITING_CO_REVIEW"}


def route_after_lookup(state: WorkflowState) -> str:
    """Pass -> populate fields. Any blocking status -> terminal CO-review state."""
    if state.get("gate_status") == "OK":
        return "populate"
    return "co_gate"


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

    validate is a CONDITIONAL gate: found/OK -> populate; anything else ->
    co_gate (terminal, no draft assembly). The downstream node ("classify") is
    referenced by NAME, not import — Person B owns it. LangGraph resolves the
    reference at compile time.
    """
    builder.add_node("lookup", lookup_node)
    builder.add_node("validate", validate_lookup_node)
    builder.add_node("populate", populate_fields_node)

    builder.add_edge("lookup", "validate")
    builder.add_conditional_edges("validate", route_after_lookup,
                                  {"populate": "populate", "co_gate": "co_gate"})
    builder.add_edge("populate", "classify")

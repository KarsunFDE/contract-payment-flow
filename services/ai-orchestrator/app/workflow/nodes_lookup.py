"""
nodes_lookup.py — Person A: lookup front end (m3.md Phase 1).

FOUNDATION STUBS: no-op passthrough nodes + this slice's graph wiring, so the
full graph compiles and invokes end-to-end (Phase 0 exit criteria). Person A
replaces the node bodies in tasks A1-A2; the register() edges below are the
frozen wiring this owner maintains.
"""
from __future__ import annotations

from langgraph.graph import StateGraph

from app.workflow.state import WorkflowState


def lookup_node(state: WorkflowState) -> dict:
    """Resolve the contract number via the SAM.gov client (deterministic, no LLM).
    STUB — A2 implements (m3.md Step 1.1)."""
    return {}


def validate_lookup_node(state: WorkflowState) -> dict:
    """Check the lookup result; flag not-found / ambiguous / cross-agency to the CO.
    STUB — A2 implements (m3.md Step 1.2)."""
    return {}


def populate_fields_node(state: WorkflowState) -> dict:
    """Auto-fill the static SF-30 blocks from the record, each with a citation.
    STUB — A2 implements (m3.md Step 1.3)."""
    return {}


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
    builder.add_edge("populate", "classify")  # cross-seam bridge (Person B owns "classify")

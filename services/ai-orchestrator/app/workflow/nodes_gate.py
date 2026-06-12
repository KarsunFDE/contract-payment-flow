"""
nodes_gate.py — Person A: CO hard gate + bilateral consent + CO-only submit
(m3.md Phases 4-5).

FOUNDATION STUBS — Person A implements in tasks A4-A5. co_gate_node is a LangGraph
`interrupt()` (pause for approve/deny) backed by the MongoDB checkpointer in
runner.py; consent_gate_node is a second interrupt for the contractor's Block 15
signature; submit_node records the CO-triggered, irreversible transition. The
register() edges are frozen.
"""
from __future__ import annotations

from langgraph.graph import StateGraph, END

from app.workflow.state import WorkflowState


def co_gate_node(state: WorkflowState) -> dict:
    """Hard CO gate — pauses (interrupt) until the CO approves or denies.
    STUB — A4 implements (m3.md Step 4.1)."""
    return {}


def consent_gate_node(state: WorkflowState) -> dict:
    """Bilateral only — pauses until contractor consent (Block 15) is recorded.
    STUB — A5 implements (m3.md Step 5.2)."""
    return {}


def submit_node(state: WorkflowState) -> dict:
    """CO-triggered submit (DRAFT -> MODIFICATION_REQUEST); write path enforces
    CO role + recorded consent, fail-closed. STUB — A5 implements (m3.md Step 5.3)."""
    return {}


def register(builder: StateGraph) -> None:
    """Add the gate/consent/submit nodes + their edges to END.

    FOUNDATION STUB uses a LINEAR co_gate -> consent_gate -> submit path. In tasks
    A4-A5 Person A replaces these with the conditional routers:
      - route_after_co_gate (deny -> supersede; approve -> consent check), Step 4.3
      - route_after_approve (bilateral -> consent_gate; unilateral -> submit), Step 5.1
    and adds the supersede_node on the deny path.
    """
    builder.add_node("co_gate", co_gate_node)
    builder.add_node("consent_gate", consent_gate_node)
    builder.add_node("submit", submit_node)

    builder.add_edge("co_gate", "consent_gate")   # STUB: A4 -> conditional route
    builder.add_edge("consent_gate", "submit")    # STUB: A5 -> conditional route
    builder.add_edge("submit", END)

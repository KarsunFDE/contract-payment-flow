"""
nodes_triage.py — Person B: anomaly-detector + adjudicator + decision-router +
lane nodes (m3.md Phase 7).

FOUNDATION STUBS — Person B implements in tasks B3-B5. The wiring lives in
triage_graph.py (also B-owned). In B4, decision_router_node returns a
`Command(goto=..., update=...)` for three-lane routing; until then it is a no-op
passthrough so the Foundation triage skeleton compiles linearly.
"""
from __future__ import annotations

from app.workflow.triage_state import TriageState


def anomaly_detector_node(state: TriageState) -> dict:
    """Flag typed anomalies (detection only — no disposition).
    STUB — B3 implements (m3.md Step 7.1)."""
    return {}


def adjudicator_node(state: TriageState) -> dict:
    """Test each flag against governing FAR + precedent (M2 retrieval).
    STUB — B3 implements (m3.md Step 7.2)."""
    return {}


def decision_router_node(state: TriageState) -> dict:
    """Sort the item into one lane (default-deny). STUB — B4 returns a Command
    for three-lane routing (m3.md Step 7.4)."""
    return {}


def auto_process_node(state: TriageState) -> dict:
    """Auto lane: idempotent mock execution + mandatory audit (no double-pay).
    STUB — B5 implements (m3.md Step 7.5)."""
    return {}


def return_route_node(state: TriageState) -> dict:
    """Return/route/hold lane (non-terminal). STUB — B5 implements (m3.md Step 7.5)."""
    return {}

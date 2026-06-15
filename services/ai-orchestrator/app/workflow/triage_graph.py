"""
triage_graph.py — the multi-agent triage flow (m3.md Phase 7, Step 7.5).

Wires anomaly_detector -> adjudicator -> decision_router, then the three lanes the
router sorts into: auto_process, hitl_escalate (the SF-30 workflow as a compiled
subgraph), and return_route.

The inner workflow compiles straight in as a node because TriageState extends
WorkflowState (shared state keys — no wrapper needed):
  https://docs.langchain.com/oss/python/langgraph/use-subgraphs
"""
from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from app.workflow.triage_state import TriageState
from app.workflow.graph import build_graph
from app.workflow import nodes_triage


def build_triage_graph() -> StateGraph:
    """Build (but do not compile) the outer triage graph."""
    builder = StateGraph(TriageState)

    builder.add_node("anomaly_detector", nodes_triage.anomaly_detector_node)
    builder.add_node("adjudicator", nodes_triage.adjudicator_node)
    builder.add_node("decision_router", nodes_triage.decision_router_node)
    builder.add_node("auto_process", nodes_triage.auto_process_node)
    builder.add_node("return_route", nodes_triage.return_route_node)

    # The SF-30 workflow (Phases 0-6) runs as the HITL processing subgraph.
    builder.add_node("hitl_escalate", build_graph().compile())

    builder.add_edge(START, "anomaly_detector")
    builder.add_edge("anomaly_detector", "adjudicator")
    # decision_router returns Command(goto=...) — the lane edges are dynamic, so
    # there are no static edges out of it (the three targets are declared via the
    # node's Command[Literal[...]] return annotation).
    builder.add_edge("adjudicator", "decision_router")
    builder.add_edge("auto_process", END)
    builder.add_edge("hitl_escalate", END)
    builder.add_edge("return_route", END)

    return builder

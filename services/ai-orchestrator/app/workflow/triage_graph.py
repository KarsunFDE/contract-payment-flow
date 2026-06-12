"""
triage_graph.py — Person B: the multi-agent triage flow (m3.md Phase 7, Step 7.5).

FOUNDATION SKELETON: wires anomaly_detector -> adjudicator -> decision_router and
mounts the inner SF-30 workflow as the HITL subgraph, so the outer graph compiles.
In task B5, Person B replaces decision_router's linear edge with Command-based
three-lane routing (auto_process / hitl_escalate / return_route).

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

    # The SF-30 workflow (Phases 0-6) runs as the HITL processing subgraph.
    # Inner graph is compiled WITHOUT a checkpointer here. When Phase 4 (task A4) adds
    # interrupt() in co_gate, the PARENT triage graph must be compiled with a checkpointer
    # (LangGraph propagates it to compiled subgraphs) — A4 must verify that propagation.
    builder.add_node("hitl_escalate", build_graph().compile())

    builder.add_edge(START, "anomaly_detector")
    builder.add_edge("anomaly_detector", "adjudicator")
    builder.add_edge("adjudicator", "decision_router")
    # FOUNDATION STUB: linear default to the HITL lane. B5 replaces this with
    # Command(goto=...) routing to auto_process / hitl_escalate / return_route,
    # and adds the auto_process_node + return_route_node from nodes_triage.
    builder.add_edge("decision_router", "hitl_escalate")
    builder.add_edge("hitl_escalate", END)

    return builder

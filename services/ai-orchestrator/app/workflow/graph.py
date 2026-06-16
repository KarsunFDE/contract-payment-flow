"""
graph.py — assembles the inner SF-30 modification workflow (m3.md Phase 0, Step 0.2).

build_graph() wires the StateGraph by calling each node module's register(builder)
in a FIXED order, then returns the UNCOMPILED builder. This file is frozen after
Foundation: each workstream edits only its own nodes_*.py register(), never this
file, so the two owners never collide here.

The straight-line backbone order is a hard rule (ADR-0006 "Workflow State Order").
Conditional routing (confidence fail -> CO gate; deny -> supersede; bilateral ->
consent) is added by the owning module in its phase, replacing the Foundation's
linear stub edges.

Official StateGraph / add_node / add_edge / START / END pattern:
  https://docs.langchain.com/oss/python/langgraph/graph-api
"""
from __future__ import annotations

from langgraph.graph import StateGraph, START

from app.workflow.state import WorkflowState
from app.workflow import (
    nodes_lookup,
    nodes_classify,
    nodes_retrieval,
    nodes_form,
    nodes_gate,
)


def build_graph() -> StateGraph:
    """Build (but do not compile) the inner SF-30 workflow graph.

    Caller compiles it: `build_graph().compile().invoke(initial_state)` — or, in
    Phase 4, `.compile(checkpointer=MongoDBSaver(...))` for pause/resume.
    """
    builder = StateGraph(WorkflowState)

    # Entry edge. Each register() adds its own nodes + outgoing edges (including
    # the cross-seam bridges by node name); LangGraph resolves names at compile.
    builder.add_edge(START, "lookup")

    nodes_lookup.register(builder)      # lookup -> validate -> populate -> (classify)
    nodes_classify.register(builder)    # classify -> derive_consent -> (retrieve)
    nodes_retrieval.register(builder)   # retrieve -> confidence -> draft -> faithfulness -> (assemble)
    nodes_form.register(builder)        # assemble -> (co_gate)
    nodes_gate.register(builder)        # co_gate -> consent_gate -> submit -> END

    return builder

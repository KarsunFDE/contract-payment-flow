"""runner.py — compile + drive the M3 workflow with the MongoDB checkpointer.

Phase 4 (m3.md Step 4.2): interrupt() only works when the graph has a checkpointer
that persists the paused state across process restarts. MongoDBSaver reuses the
Mongo instance already configured in app/config.py (MONGO_URL / MONGO_DB).

Two entry pairs:
  run_until_gate / resume_after_decision  — the inner SF-30 workflow alone.
  run_triage_until_gate / resume_triage_after_decision  — the outer triage graph
    (the start-to-finish entry: anomaly → adjudicator → router → lane). The SF-30
    workflow runs as the hitl_escalate subgraph and inherits this parent
    checkpointer, so the co_gate interrupt() pauses/resumes on the same thread_id.

Official MongoDBSaver.from_conn_string + compile(checkpointer=) + Command(resume=):
  https://pypi.org/project/langgraph-checkpoint-mongodb/
  https://docs.langchain.com/oss/python/langgraph/add-memory
  https://docs.langchain.com/oss/python/langgraph/interrupts
  https://docs.langchain.com/oss/python/langgraph/use-subgraphs (checkpointer propagation)
"""
from __future__ import annotations

from typing import Any

from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.types import Command

from app import config
from app.workflow.graph import build_graph
from app.workflow.triage_graph import build_triage_graph


def _thread_cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


# --- inner SF-30 workflow ----------------------------------------------------

def run_until_gate(initial_state: dict, thread_id: str) -> dict:
    """Start the inner workflow; runs until the CO gate interrupt, then pauses."""
    with MongoDBSaver.from_conn_string(config.MONGO_URL, config.MONGO_DB) as saver:
        graph = build_graph().compile(checkpointer=saver)
        return graph.invoke(initial_state, _thread_cfg(thread_id))


def resume_after_decision(decision: Any, thread_id: str) -> dict:
    """Resume the paused inner workflow with the CO's approve/deny decision."""
    with MongoDBSaver.from_conn_string(config.MONGO_URL, config.MONGO_DB) as saver:
        graph = build_graph().compile(checkpointer=saver)
        return graph.invoke(Command(resume=decision), _thread_cfg(thread_id))


# --- outer triage graph (full start-to-finish entry) -------------------------

def run_triage_until_gate(initial_state: dict, thread_id: str) -> dict:
    """Start the triage flow; runs until a lane completes or the embedded SF-30
    workflow hits the CO gate interrupt, then pauses.

    Compiling the parent with a checkpointer is what makes the subgraph interrupt
    work — the inner graph is compiled without its own checkpointer so it inherits
    this one.
    """
    with MongoDBSaver.from_conn_string(config.MONGO_URL, config.MONGO_DB) as saver:
        graph = build_triage_graph().compile(checkpointer=saver)
        return graph.invoke(initial_state, _thread_cfg(thread_id))


def resume_triage_after_decision(decision: Any, thread_id: str) -> dict:
    """Resume a paused triage run. `decision` is forwarded to whichever interrupt
    paused it: the co_gate expects an approve/deny string; the consent_gate expects
    a dict like {"signed": true}."""
    with MongoDBSaver.from_conn_string(config.MONGO_URL, config.MONGO_DB) as saver:
        graph = build_triage_graph().compile(checkpointer=saver)
        return graph.invoke(Command(resume=decision), _thread_cfg(thread_id))

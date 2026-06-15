"""runner.py — compile + drive the inner SF-30 workflow with the MongoDB checkpointer.

Phase 4 (m3.md Step 4.2): interrupt() only works when the graph has a checkpointer
that persists the paused state across process restarts. MongoDBSaver reuses the
Mongo instance already configured in app/config.py (MONGO_URL / MONGO_DB).

run_until_gate   : start a new workflow run; returns when the CO gate interrupt fires.
resume_after_decision : resume a paused run with the CO's approve/deny decision.

Official MongoDBSaver.from_conn_string + compile(checkpointer=) + Command(resume=):
  https://pypi.org/project/langgraph-checkpoint-mongodb/
  https://docs.langchain.com/oss/python/langgraph/add-memory
  https://docs.langchain.com/oss/python/langgraph/interrupts
"""
from __future__ import annotations

from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.types import Command

from app import config
from app.workflow.graph import build_graph


def run_until_gate(initial_state: dict, thread_id: str) -> dict:
    """Start the workflow; runs until the CO gate interrupt, then pauses."""
    with MongoDBSaver.from_conn_string(config.MONGO_URL, config.MONGO_DB) as saver:
        graph = build_graph().compile(checkpointer=saver)
        cfg = {"configurable": {"thread_id": thread_id}}
        return graph.invoke(initial_state, cfg)


def resume_after_decision(decision: str, thread_id: str) -> dict:
    """Resume the paused workflow with the CO's approve/deny decision."""
    with MongoDBSaver.from_conn_string(config.MONGO_URL, config.MONGO_DB) as saver:
        graph = build_graph().compile(checkpointer=saver)
        cfg = {"configurable": {"thread_id": thread_id}}
        return graph.invoke(Command(resume=decision), cfg)

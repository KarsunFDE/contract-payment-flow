"""
test_triage_runner.py — Phase 7 + Phase 4 seam (m3.md Steps 7.5, 4.2; ADR-0006).

The parent triage graph is compiled with the MongoDB checkpointer, which propagates
into the inner SF-30 subgraph so its co_gate interrupt() pauses — and the run resumes
on the same thread_id with the CO decision.

The spec pins the checkpoint to MongoDB (m3.md Step 4.2 "We use MongoDBSaver";
ADR-0006: "backed by a MongoDB checkpoint, so a package survives … a restart"). So
this drives the real runner entrypoints. run + resume are two separate runner calls,
each with its own MongoDBSaver connection — a passing resume proves the paused state
persisted across connections, not just in-process.

Skips when no MongoDB is reachable. The fail-closed path (retrieval + LLM
unavailable) is forced so the item escalates to hitl and reaches the gate without
AWS creds.
"""
from __future__ import annotations

import uuid

import pytest

from app.workflow import (
    nodes_classify,
    nodes_gate,
    nodes_lookup,
    nodes_triage,
    retrieve_client,
    runner,
)
from app.workflow.llm import LLMOutputError


def _mongo_available() -> bool:
    """True when the configured MongoDB answers a ping (compose `mongodb` service)."""
    try:
        from pymongo import MongoClient

        from app import config
        MongoClient(config.MONGO_URL, serverSelectionTimeoutMS=1500).admin.command("ping")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _mongo_available(), reason="needs the MongoDB checkpointer (compose `mongodb`)"
)


def _force_fail_closed_path(monkeypatch):
    """Make retrieval + the LLM judges unavailable so every gate fails closed and the
    item is driven to the CO gate (no AWS creds / no retrieval service needed)."""
    def boom_retrieve(*a, **k):
        raise retrieve_client.RetrieveError("retrieval down (test)")

    def boom_llm(*a, **k):
        raise LLMOutputError("no creds (test)")

    monkeypatch.setattr(retrieve_client, "retrieve_for_state", boom_retrieve)
    monkeypatch.setattr(nodes_classify, "call_json", boom_llm)
    monkeypatch.setattr(nodes_triage, "call_json", boom_llm)

    # Keep the audit collection clean — the checkpointer (not the audit log) is the
    # subject under test. The Mongo checkpoint write still happens for real.
    for mod in (nodes_lookup, nodes_triage, nodes_gate):
        monkeypatch.setattr(mod, "record_event", lambda *a, **k: None)


def _initial_state():
    # Unique correlation_id == thread_id per run so re-runs never collide on a
    # persisted Mongo checkpoint.
    cid = str(uuid.uuid4())
    return cid, {
        "correlation_id": cid,
        "agency_id": "agency-gsa",
        "item_type": "modification",
        "contract_number": "GS-35F-0001V",
        "change_request": {"agency_id": "agency-gsa", "scope": "extend PoP 90 days"},
    }


def test_triage_pauses_at_co_gate_via_mongo_checkpointer(monkeypatch):
    """Escalated item runs the SF-30 subgraph and pauses at the inner co_gate
    interrupt — proving the parent MongoDBSaver reached the subgraph."""
    _force_fail_closed_path(monkeypatch)
    thread_id, state = _initial_state()

    result = runner.run_triage_until_gate(state, thread_id)

    assert result["lane"] == "hitl_escalate"
    assert result.get("__interrupt__"), "expected the inner co_gate to pause the run"


def test_triage_resumes_after_co_decision_across_connections(monkeypatch):
    """A second runner call (fresh MongoDBSaver connection) resumes the paused run
    with a CO 'denied' decision — the checkpoint survived the connection close."""
    _force_fail_closed_path(monkeypatch)
    thread_id, state = _initial_state()

    runner.run_triage_until_gate(state, thread_id)                 # pauses, persists to Mongo
    resumed = runner.resume_triage_after_decision("denied", thread_id)

    assert resumed.get("co_decision") == "denied"
    assert not resumed.get("__interrupt__"), "run should have resumed past the gate"

"""
Task B2 — Block 14 grounded sub-pipeline nodes (m3.md Steps 2.2-2.4).
Confidence is an LLM-as-judge (task-split finding #7), both judges gate at
config.CONFIDENCE_THRESHOLD, and every failure path lands at the CO gate.
"""
from __future__ import annotations

import pytest

from app import bedrock_client
from app.workflow import llm, nodes_retrieval, retrieve_client


def _chunks(n: int) -> list[dict]:
    return [
        {"chunk_id": f"far-chunk-{i}", "chunk_text": f"clause text {i}",
         "score": 0.8, "source_document": None}
        for i in range(n)
    ]


class FakeRetrieveClient:
    def __init__(self, chunks=None, fail=False):
        self.chunks = chunks if chunks is not None else _chunks(4)
        self.fail = fail
        self.calls: list[dict] = []

    def retrieve(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        if self.fail:
            raise retrieve_client.RetrievalUnavailable("circuit open (test)")
        return self.chunks


@pytest.fixture
def fake_retrieval():
    """Swap in the fake; conftest's autouse fixture restores the real client."""
    fake = FakeRetrieveClient()
    retrieve_client.set_client(fake)
    yield fake


def _fake_judge(scores=None, faithfulness=None):
    """call_json fake serving both judge schemas."""
    def _call(prompt, *, schema, system=None, **kwargs):
        if schema is nodes_retrieval.ChunkScores:
            data = nodes_retrieval.ChunkScores(scores=scores)
        else:
            data = nodes_retrieval.FaithfulnessVerdict(score=faithfulness)
        return llm.JsonResult(data=data, model="m", model_version="v1:0")
    return _call


_STATE = {
    "correlation_id": "22222222-2222-2222-2222-222222222222",
    "agency_id": "agency-gsa",
    "contract_number": "GS-35F-0001V",
    "change_request": {"scope": "extend period of performance 90 days"},
}


def test_retrieve_node_returns_chunks_and_threads_identity(fake_retrieval):
    update = nodes_retrieval.retrieve_node(dict(_STATE))
    assert len(update["retrieved_chunks"]) == 4
    call = fake_retrieval.calls[0]
    assert call["sf30_block"] == "14"
    assert call["agency_id"] == "agency-gsa"
    assert call["correlation_id"] == _STATE["correlation_id"]


def test_retrieve_node_fails_soft_to_co_review():
    retrieve_client.set_client(FakeRetrieveClient(fail=True))
    update = nodes_retrieval.retrieve_node(dict(_STATE))
    assert update["gate_status"] == "RAG_FAILED_AWAITING_CO_REVIEW"
    assert update["retrieved_chunks"] == []
    assert update["confidence"] == 0.0


def test_confidence_judge_pass_sets_ok(monkeypatch):
    monkeypatch.setattr(llm, "call_json", _fake_judge(scores=[0.9, 0.9, 0.9, 0.9]))
    state = dict(_STATE, retrieved_chunks=_chunks(4))
    update = nodes_retrieval.confidence_check_node(state)
    assert update["gate_status"] == "OK"
    assert update["confidence"] == pytest.approx(0.9)


def test_confidence_judge_below_threshold_routes_to_co(monkeypatch):
    monkeypatch.setattr(llm, "call_json", _fake_judge(scores=[0.9, 0.8, 0.7, 0.6]))
    state = dict(_STATE, retrieved_chunks=_chunks(4))
    update = nodes_retrieval.confidence_check_node(state)
    assert update["gate_status"] == "RAG_FAILED_AWAITING_CO_REVIEW"
    assert update["confidence"] < 0.85


def test_confidence_fails_closed_below_min_chunks():
    """ADR-0005 §10: partial retrieval is a confidence failure — no judge call."""
    state = dict(_STATE, retrieved_chunks=_chunks(2))
    update = nodes_retrieval.confidence_check_node(state)
    assert update["gate_status"] == "RAG_FAILED_AWAITING_CO_REVIEW"
    assert update["confidence"] == 0.0


def test_confidence_fails_closed_on_judge_error(monkeypatch):
    def _reject(prompt, *, schema, system=None, **kwargs):
        raise llm.LLMOutputError("stub (test)")
    monkeypatch.setattr(llm, "call_json", _reject)
    state = dict(_STATE, retrieved_chunks=_chunks(4))
    update = nodes_retrieval.confidence_check_node(state)
    assert update["gate_status"] == "RAG_FAILED_AWAITING_CO_REVIEW"


def test_confidence_fails_closed_on_score_count_mismatch(monkeypatch):
    monkeypatch.setattr(llm, "call_json", _fake_judge(scores=[0.9]))  # 1 for 4
    state = dict(_STATE, retrieved_chunks=_chunks(4))
    update = nodes_retrieval.confidence_check_node(state)
    assert update["gate_status"] == "RAG_FAILED_AWAITING_CO_REVIEW"


def test_confidence_preserves_upstream_retrieval_failure():
    state = dict(_STATE, retrieved_chunks=[],
                 gate_status="RAG_FAILED_AWAITING_CO_REVIEW")
    assert nodes_retrieval.confidence_check_node(state) == {}


def test_route_after_confidence():
    assert nodes_retrieval.route_after_confidence({"gate_status": "OK"}) == "draft"
    assert nodes_retrieval.route_after_confidence(
        {"gate_status": "RAG_FAILED_AWAITING_CO_REVIEW"}) == "co_gate"


def test_draft_node_grounds_in_retrieved_chunks(monkeypatch):
    captured = {}

    def _fake_invoke(prompt, *, system=None, **kwargs):
        captured["prompt"] = prompt
        return {"body": "Drafted Block 14 rationale.", "model": "m",
                "region": "us-east-1", "stub": False}

    monkeypatch.setattr(bedrock_client, "invoke_model", _fake_invoke)
    state = dict(_STATE, retrieved_chunks=_chunks(3), gate_status="OK")
    update = nodes_retrieval.draft_node(state)
    assert update["block_14_draft"] == "Drafted Block 14 rationale."
    assert "clause text 0" in captured["prompt"]


def test_faithfulness_pass_routes_to_assemble(monkeypatch):
    monkeypatch.setattr(llm, "call_json", _fake_judge(faithfulness=0.95))
    state = dict(_STATE, retrieved_chunks=_chunks(3), block_14_draft="draft")
    update = nodes_retrieval.faithfulness_gate_node(state)
    assert update["gate_status"] == "OK"
    assert nodes_retrieval.route_after_faithfulness(update) == "assemble"


def test_faithfulness_below_threshold_routes_to_co(monkeypatch):
    monkeypatch.setattr(llm, "call_json", _fake_judge(faithfulness=0.5))
    state = dict(_STATE, retrieved_chunks=_chunks(3), block_14_draft="draft")
    update = nodes_retrieval.faithfulness_gate_node(state)
    assert update["gate_status"] == "FAITHFULNESS_FAILED_AWAITING_CO_REVIEW"
    assert nodes_retrieval.route_after_faithfulness(update) == "co_gate"


def test_faithfulness_fails_closed_on_judge_error(monkeypatch):
    """An unverifiable draft is never submitted onward."""
    def _reject(prompt, *, schema, system=None, **kwargs):
        raise llm.LLMOutputError("stub (test)")
    monkeypatch.setattr(llm, "call_json", _reject)
    state = dict(_STATE, retrieved_chunks=_chunks(3), block_14_draft="draft")
    update = nodes_retrieval.faithfulness_gate_node(state)
    assert update["gate_status"] == "FAITHFULNESS_FAILED_AWAITING_CO_REVIEW"

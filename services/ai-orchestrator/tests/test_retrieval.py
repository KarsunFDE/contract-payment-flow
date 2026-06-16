"""
test_retrieval.py — Block 14 grounded sub-pipeline (m3.md Steps 2.2-2.4).

The read path and the LLM judges are stubbed; the test pins the gate behaviour:
aggregate confidence threshold, fail-closed routing to the CO gate, and the
draft/faithfulness flow.
"""
from __future__ import annotations

from app.workflow import nodes_retrieval
from app.workflow.llm import LLMOutputError, JsonResult
from app.workflow.nodes_retrieval import ChunkRelevanceScores, FaithfulnessScore

_STATE = {
    "correlation_id": "c-1",
    "agency_id": "agency-gsa",
    "contract_number": "GS-35F-0001V",
    "change_request": {"scope": "extend PoP", "co_user_id": "co-1", "co_role": "CO"},
}


def _judge(score_model):
    return lambda *a, **k: JsonResult(data=score_model, model="m", model_version="v1", stub=False)


def test_retrieve_failure_routes_to_co(monkeypatch):
    def boom(*a, **k):
        raise nodes_retrieval.retrieve_client.RetrieveError("both paths down")

    monkeypatch.setattr(nodes_retrieval.retrieve_client, "retrieve_for_state", boom)
    result = nodes_retrieval.retrieve_node(_STATE)
    assert result["retrieved_chunks"] == []
    assert result["gate_status"] == "RAG_FAILED_AWAITING_CO_REVIEW"


def test_confidence_pass_above_threshold(monkeypatch):
    monkeypatch.setattr(nodes_retrieval, "call_json",
                        _judge(ChunkRelevanceScores(scores=[0.9, 0.9])))
    state = {**_STATE, "retrieved_chunks": [{"chunk_text": "a"}, {"chunk_text": "b"}]}
    result = nodes_retrieval.confidence_check_node(state)
    assert result["gate_status"] == "OK"
    assert nodes_retrieval.route_after_confidence(result) == "draft"


def test_confidence_fail_below_threshold(monkeypatch):
    monkeypatch.setattr(nodes_retrieval, "call_json",
                        _judge(ChunkRelevanceScores(scores=[0.5, 0.4])))
    state = {**_STATE, "retrieved_chunks": [{"chunk_text": "a"}, {"chunk_text": "b"}]}
    result = nodes_retrieval.confidence_check_node(state)
    assert result["gate_status"] == "RAG_FAILED_AWAITING_CO_REVIEW"
    assert nodes_retrieval.route_after_confidence(result) == "co_gate"


def test_confidence_no_chunks_fails_closed():
    result = nodes_retrieval.confidence_check_node({**_STATE, "retrieved_chunks": []})
    assert result["gate_status"] == "RAG_FAILED_AWAITING_CO_REVIEW"


def test_confidence_judge_error_fails_closed(monkeypatch):
    def boom(*a, **k):
        raise LLMOutputError("stub")

    monkeypatch.setattr(nodes_retrieval, "call_json", boom)
    state = {**_STATE, "retrieved_chunks": [{"chunk_text": "a"}]}
    assert nodes_retrieval.confidence_check_node(state)["gate_status"] == "RAG_FAILED_AWAITING_CO_REVIEW"


def test_draft_node_uses_bedrock(monkeypatch):
    monkeypatch.setattr(nodes_retrieval.bedrock_client, "invoke_model",
                        lambda *a, **k: {"body": "drafted rationale", "stub": False})
    state = {**_STATE, "retrieved_chunks": [{"chunk_text": "a"}]}
    assert nodes_retrieval.draft_node(state)["block_14_draft"] == "drafted rationale"


def test_faithfulness_pass_and_fail(monkeypatch):
    monkeypatch.setattr(nodes_retrieval, "call_json", _judge(FaithfulnessScore(score=0.95)))
    assert nodes_retrieval.faithfulness_gate_node(_STATE)["gate_status"] == "OK"
    assert nodes_retrieval.route_after_faithfulness({"gate_status": "OK"}) == "assemble"

    monkeypatch.setattr(nodes_retrieval, "call_json", _judge(FaithfulnessScore(score=0.5)))
    failed = nodes_retrieval.faithfulness_gate_node(_STATE)
    assert failed["gate_status"] == "FAITHFULNESS_FAILED_AWAITING_CO_REVIEW"
    assert nodes_retrieval.route_after_faithfulness(failed) == "co_gate"

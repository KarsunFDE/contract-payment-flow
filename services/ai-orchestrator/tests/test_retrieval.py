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
    assert result["draft_model_tier"] == "haiku"
    assert nodes_retrieval.route_after_confidence(result) == "draft"


def test_confidence_fail_escalates_to_sonnet(monkeypatch):
    # Confidence-fail WITH chunks now escalates the draft model to Sonnet (ADR-0006),
    # routing to draft (not the CO); faithfulness_gate remains the arbiter.
    monkeypatch.setattr(nodes_retrieval, "call_json",
                        _judge(ChunkRelevanceScores(scores=[0.5, 0.4])))
    monkeypatch.setattr(nodes_retrieval, "record_event", lambda *a, **k: None)
    state = {**_STATE, "retrieved_chunks": [{"chunk_text": "a"}, {"chunk_text": "b"}]}
    result = nodes_retrieval.confidence_check_node(state)
    assert result["gate_status"] == "OK"
    assert result["draft_model_tier"] == "sonnet"
    assert nodes_retrieval.route_after_confidence(result) == "draft"


def test_force_low_confidence_escalates_to_sonnet(monkeypatch):
    # Dev/demo flag forces the Sonnet path deterministically (no judge call).
    monkeypatch.setattr(nodes_retrieval, "record_event", lambda *a, **k: None)
    state = {
        **_STATE,
        "change_request": {**_STATE["change_request"], "force_low_confidence": True},
        "retrieved_chunks": [{"chunk_text": "a"}],
    }
    result = nodes_retrieval.confidence_check_node(state)
    assert result["draft_model_tier"] == "sonnet"
    assert result["gate_status"] == "OK"


def test_confidence_no_chunks_fails_closed():
    result = nodes_retrieval.confidence_check_node({**_STATE, "retrieved_chunks": []})
    assert result["gate_status"] == "RAG_FAILED_AWAITING_CO_REVIEW"


def test_confidence_judge_error_fails_closed(monkeypatch):
    def boom(*a, **k):
        raise LLMOutputError("stub")

    monkeypatch.setattr(nodes_retrieval, "call_json", boom)
    state = {**_STATE, "retrieved_chunks": [{"chunk_text": "a"}]}
    assert nodes_retrieval.confidence_check_node(state)["gate_status"] == "RAG_FAILED_AWAITING_CO_REVIEW"


def test_draft_node_uses_haiku_by_default(monkeypatch):
    captured = {}

    def fake_invoke(*a, model_id=None, **k):
        captured["model_id"] = model_id
        return {"body": "drafted rationale", "model": model_id, "stub": False}

    monkeypatch.setattr(nodes_retrieval.bedrock_client, "invoke_model", fake_invoke)
    state = {**_STATE, "retrieved_chunks": [{"chunk_text": "a"}]}  # no tier → haiku
    result = nodes_retrieval.draft_node(state)
    assert result["block_14_draft"] == "drafted rationale"
    assert captured["model_id"] == nodes_retrieval.bedrock_client.BEDROCK_MODEL_ID
    assert result["draft_model"] == nodes_retrieval.bedrock_client.BEDROCK_MODEL_ID


def test_draft_node_uses_sonnet_on_escalation(monkeypatch):
    captured = {}

    def fake_invoke(*a, model_id=None, **k):
        captured["model_id"] = model_id
        return {"body": "sonnet rationale", "model": model_id, "stub": False}

    monkeypatch.setattr(nodes_retrieval.bedrock_client, "invoke_model", fake_invoke)
    state = {**_STATE, "retrieved_chunks": [{"chunk_text": "a"}], "draft_model_tier": "sonnet"}
    result = nodes_retrieval.draft_node(state)
    assert captured["model_id"] == nodes_retrieval.bedrock_client.BEDROCK_FALLBACK_MODEL_ID
    assert result["draft_model"] == nodes_retrieval.bedrock_client.BEDROCK_FALLBACK_MODEL_ID


def test_faithfulness_pass_and_fail(monkeypatch):
    monkeypatch.setattr(nodes_retrieval, "call_json", _judge(FaithfulnessScore(score=0.95)))
    assert nodes_retrieval.faithfulness_gate_node(_STATE)["gate_status"] == "OK"
    assert nodes_retrieval.route_after_faithfulness({"gate_status": "OK"}) == "assemble"

    monkeypatch.setattr(nodes_retrieval, "call_json", _judge(FaithfulnessScore(score=0.5)))
    failed = nodes_retrieval.faithfulness_gate_node(_STATE)
    assert failed["gate_status"] == "FAITHFULNESS_FAILED_AWAITING_CO_REVIEW"
    assert nodes_retrieval.route_after_faithfulness(failed) == "co_gate"


# ---------------------------------------------------------------------------
# NEW negative-path coverage
# ---------------------------------------------------------------------------

def test_faithfulness_judge_error_fails_closed(monkeypatch):
    """faithfulness_gate_node fails closed to CO gate on LLM error (no assemble)."""
    from app.workflow.llm import LLMOutputError

    def boom(*a, **k):
        raise LLMOutputError("stub")

    monkeypatch.setattr(nodes_retrieval, "call_json", boom)
    state = {**_STATE, "retrieved_chunks": [{"chunk_text": "a"}], "block_14_draft": "x"}
    result = nodes_retrieval.faithfulness_gate_node(state)
    assert result["gate_status"] == "FAITHFULNESS_FAILED_AWAITING_CO_REVIEW"
    assert nodes_retrieval.route_after_faithfulness(result) == "co_gate"


def test_faithfulness_below_threshold_routes_to_co_gate(monkeypatch):
    """Faithfulness score below threshold → CO gate, draft is NOT assembled."""
    monkeypatch.setattr(nodes_retrieval, "call_json", _judge(FaithfulnessScore(score=0.1)))
    state = {**_STATE, "retrieved_chunks": [{"chunk_text": "a"}], "block_14_draft": "low"}
    result = nodes_retrieval.faithfulness_gate_node(state)
    assert result["gate_status"] == "FAITHFULNESS_FAILED_AWAITING_CO_REVIEW"
    assert nodes_retrieval.route_after_faithfulness(result) == "co_gate"


def test_faithfulness_gate_sticky_blocking_not_overwritten(monkeypatch):
    """A prior blocking gate_status (e.g. from retrieve) must not be cleared by faithfulness."""
    # faithfulness_gate_node has an is_blocking guard — if an earlier node set a
    # blocking status, this node returns {} and leaves the status unchanged.
    blocking_state = {
        **_STATE,
        "gate_status": "RAG_FAILED_AWAITING_CO_REVIEW",
        "retrieved_chunks": [{"chunk_text": "a"}],
        "block_14_draft": "x",
    }
    result = nodes_retrieval.faithfulness_gate_node(blocking_state)
    assert result == {}  # no overwrite


def test_confidence_sticky_blocking_not_overwritten(monkeypatch):
    """A prior blocking gate_status from retrieve_node must not be cleared by confidence."""
    blocking_state = {
        **_STATE,
        "gate_status": "RAG_FAILED_AWAITING_CO_REVIEW",
        "retrieved_chunks": [{"chunk_text": "a"}],
    }
    result = nodes_retrieval.confidence_check_node(blocking_state)
    assert result == {}  # no overwrite


def test_confidence_mismatched_score_count_fails_closed(monkeypatch):
    """Judge returning wrong number of scores → CO gate (cannot average misaligned list)."""
    # 2 chunks but only 1 score returned.
    monkeypatch.setattr(nodes_retrieval, "call_json",
                        _judge(ChunkRelevanceScores(scores=[0.9])))
    state = {**_STATE, "retrieved_chunks": [{"chunk_text": "a"}, {"chunk_text": "b"}]}
    result = nodes_retrieval.confidence_check_node(state)
    assert result["gate_status"] == "RAG_FAILED_AWAITING_CO_REVIEW"
    assert nodes_retrieval.route_after_confidence(result) == "co_gate"

"""
test_classify.py — Block 13 classification + consent derivation (m3.md Steps 2.1, 2.1b).

The LLM and the read path are stubbed: the test pins the node behaviour (provenance
capture, fail-closed routing, deterministic consent), not the model output.
"""
from __future__ import annotations

from app.workflow import nodes_classify
from app.workflow.llm import LLMOutputError, JsonResult
from app.workflow.nodes_classify import Block13Proposal

_STATE = {
    "correlation_id": "c-1",
    "agency_id": "agency-gsa",
    "contract_number": "GS-35F-0001V",
    "change_request": {"scope": "extend PoP 90 days", "co_user_id": "co-1", "co_role": "CO"},
}


def test_classify_captures_proposal_and_provenance(monkeypatch):
    monkeypatch.setattr(nodes_classify.retrieve_client, "retrieve_for_state",
                        lambda *a, **k: [{"chunk_id": "FAR-43.103"}])

    def fake_call_json(*a, **k):
        proposal = Block13Proposal(block13_path="13A", mod_type="bilateral_supplemental",
                                   far_basis="43.103(a)", confidence=0.9)
        return JsonResult(data=proposal, model="anthropic.claude-x-v1:0",
                          model_version="v1:0", stub=False)

    monkeypatch.setattr(nodes_classify, "call_json", fake_call_json)

    result = nodes_classify.classify_modification_node(_STATE)
    classification = result["block13_classification"]
    assert classification["mod_type"] == "bilateral_supplemental"
    assert classification["retrieved_clause_ids"] == ["FAR-43.103"]
    assert classification["model_version"] == "v1:0"


def test_classify_fails_closed_on_llm_error(monkeypatch):
    monkeypatch.setattr(nodes_classify.retrieve_client, "retrieve_for_state",
                        lambda *a, **k: [{"chunk_id": "FAR-43.103"}])

    def boom(*a, **k):
        raise LLMOutputError("stub response")

    monkeypatch.setattr(nodes_classify, "call_json", boom)

    result = nodes_classify.classify_modification_node(_STATE)
    assert result["gate_status"] == "BLOCK13_UNCLASSIFIED_AWAITING_CO_REVIEW"
    assert result["block13_classification"]["mod_type"] == "unknown"


def test_derive_consent_bilateral():
    state = {"block13_classification": {"mod_type": "bilateral_supplemental"}}
    assert nodes_classify.derive_consent_node(state) == {"modification_bilateral": True}


def test_derive_consent_unknown_flags_co_review():
    state = {"block13_classification": {"mod_type": "unknown"}}
    result = nodes_classify.derive_consent_node(state)
    assert result["modification_bilateral"] is True  # fail safe -> needs consent
    assert result["gate_status"] == "BLOCK13_UNCLASSIFIED_AWAITING_CO_REVIEW"

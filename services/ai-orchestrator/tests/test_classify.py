"""
Task B1 — Block 13 classification + consent derivation nodes (m3.md Steps
2.1/2.1b). The retrieve client and the LLM wrapper are injected fakes; the
nodes' fail-soft contract (never raise; surface at the CO gate) is the thing
under test.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.workflow import llm, nodes_classify, retrieve_client


class FakeRetrieveClient:
    def __init__(self, chunks=None, fail=False):
        self.chunks = chunks if chunks is not None else [
            {"chunk_id": "far-43-103-a", "chunk_text": "FAR 43.103(a) ...",
             "score": 0.9, "source_document": None},
        ]
        self.fail = fail
        self.calls: list[dict] = []

    def retrieve(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        if self.fail:
            raise retrieve_client.RetrievalUnavailable("both paths failed (test)")
        return self.chunks


@pytest.fixture
def fake_retrieval():
    fake = FakeRetrieveClient()
    retrieve_client.set_client(fake)
    yield fake
    retrieve_client.set_client(retrieve_client.RouterRetrieveClient())


def _fake_call_json(data: BaseModel):
    def _call(prompt, *, schema, system=None, **kwargs):
        return llm.JsonResult(
            data=data, model="anthropic.claude-3-7-sonnet-20250219-v1:0",
            model_version="v1:0",
        )
    return _call


_STATE = {
    "correlation_id": "11111111-1111-1111-1111-111111111111",
    "agency_id": "agency-gsa",
    "contract_number": "GS-35F-0001V",
    "change_request": {"scope": "add CLIN for extended support"},
}


def test_classify_success_carries_full_provenance(fake_retrieval, monkeypatch):
    """Issue 4: classification carries clause ids + model + version + confidence."""
    proposal = nodes_classify.Block13Proposal(
        block13_path="13B", mod_type="unilateral_change_order",
        far_basis="43.103(b)(1)", confidence=0.93,
    )
    monkeypatch.setattr(llm, "call_json", _fake_call_json(proposal))

    update = nodes_classify.classify_modification_node(dict(_STATE))
    classification = update["block13_classification"]
    assert classification["mod_type"] == "unilateral_change_order"
    assert classification["block13_path"] == "13B"
    assert classification["retrieved_clause_ids"] == ["far-43-103-a"]
    assert classification["model_version"] == "v1:0"
    assert classification["confidence"] == 0.93
    assert "gate_status" not in update


def test_classify_threads_tenant_identity_into_retrieval(fake_retrieval, monkeypatch):
    """ADR-0005 §11: agency_id from state; contract_id as audit metadata."""
    proposal = nodes_classify.Block13Proposal(
        block13_path="13B", mod_type="unilateral_admin",
        far_basis="43.103(b)(3)", confidence=0.9,
    )
    monkeypatch.setattr(llm, "call_json", _fake_call_json(proposal))

    nodes_classify.classify_modification_node(dict(_STATE))
    call = fake_retrieval.calls[0]
    assert call["agency_id"] == "agency-gsa"
    assert call["contract_id"] == "GS-35F-0001V"
    assert call["correlation_id"] == _STATE["correlation_id"]
    assert call["sf30_block"] == "13"


def test_classify_fails_soft_when_retrieval_unavailable(monkeypatch):
    """G2 grounded-or-withheld: no FAR context -> unclassified + CO review."""
    retrieve_client.set_client(FakeRetrieveClient(fail=True))
    try:
        update = nodes_classify.classify_modification_node(dict(_STATE))
    finally:
        retrieve_client.set_client(retrieve_client.RouterRetrieveClient())

    assert update["gate_status"] == "BLOCK13_UNCLASSIFIED_AWAITING_CO_REVIEW"
    assert update["block13_classification"]["mod_type"] == "unknown"


def test_classify_fails_soft_on_rejected_llm_output(fake_retrieval, monkeypatch):
    def _reject(prompt, *, schema, system=None, **kwargs):
        raise llm.LLMOutputError("stub response (test)")
    monkeypatch.setattr(llm, "call_json", _reject)

    update = nodes_classify.classify_modification_node(dict(_STATE))
    assert update["gate_status"] == "BLOCK13_UNCLASSIFIED_AWAITING_CO_REVIEW"
    assert update["block13_classification"]["mod_type"] == "unknown"
    # Provenance still records what retrieval found before the LLM failed.
    assert update["block13_classification"]["retrieved_clause_ids"] == ["far-43-103-a"]


def test_derive_consent_bilateral():
    state = {"block13_classification": {"mod_type": "bilateral_supplemental"}}
    update = nodes_classify.derive_consent_node(state)
    assert update == {"modification_bilateral": True}


def test_derive_consent_unilateral():
    state = {"block13_classification": {"mod_type": "unilateral_change_order"}}
    update = nodes_classify.derive_consent_node(state)
    assert update == {"modification_bilateral": False}


def test_derive_consent_unknown_fails_safe_to_consent_plus_co_review():
    """Unmapped modType never falls through to unilateral (m3.md Step 2.1b)."""
    state = {"block13_classification": {"mod_type": "unknown"}}
    update = nodes_classify.derive_consent_node(state)
    assert update["modification_bilateral"] is True
    assert update["gate_status"] == "BLOCK13_UNCLASSIFIED_AWAITING_CO_REVIEW"


def test_derive_consent_missing_classification_fails_safe():
    update = nodes_classify.derive_consent_node({})
    assert update["modification_bilateral"] is True
    assert update["gate_status"] == "BLOCK13_UNCLASSIFIED_AWAITING_CO_REVIEW"

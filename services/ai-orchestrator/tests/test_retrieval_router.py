"""Endpoint tests for POST /retrieve/ — TestClient through the full
orchestration (identity headers, fallback ladder, audit pairing, response
assembly) with dense/sparse/reranker/audit mocked. No Mongo/Bedrock required."""
import logging
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from pymongo.errors import OperationFailure

from app.main import app
from app.retrieval import failures, fusion

client = TestClient(app)

IDENTITY_HEADERS = {
    "X-Tenant-Id": "agency_x",
    "X-User-Id": "co-001",
    "X-User-Role": "contracting_officer",
}

BODY = {
    "query": "extend period of performance 90 days",
    "sf30_block": "13",
    "contract_id": "W912-26-C-0001",
}


def _doc(chunk_id: str, text: str) -> Document:
    return Document(
        page_content=text,
        metadata={"chunk_id": chunk_id, "source_document": {"far_part": "43"}},
    )


# Three distinct chunks — above MIN_RETRIEVED_CHUNKS so the happy path is
# not flagged degraded.
DENSE = [
    (_doc("d1", "dense one text"), 0.9),
    (_doc("d2", "dense two text"), 0.8),
]
SPARSE = [
    _doc("d1", "dense one text"),  # overlap — fusion dedupes
    _doc("s1", "sparse one text"),
]


class FakeEncoder:
    """Cross-encoder stub: scores by page_content lookup so tests control
    the rerank ORDER independent of fused order."""

    def __init__(self, score_by_text: dict[str, float]):
        self.score_by_text = score_by_text

    def score(self, pairs):
        return [self.score_by_text[text] for _, text in pairs]


@pytest.fixture(autouse=True)
def _reset_breaker():
    failures.reset_circuit()
    yield
    failures.reset_circuit()


@pytest.fixture
def mocks():
    with patch("app.retrieval.retriever.dense_search", return_value=list(DENSE)) as dense, \
         patch("app.retrieval.retriever.sparse_search", return_value=list(SPARSE)) as sparse, \
         patch(
             "app.retrieval.reranker._get_encoder",
             return_value=FakeEncoder(
                 {"dense one text": 0.3, "dense two text": 0.2, "sparse one text": 0.1}
             ),
         ) as encoder, \
         patch("app.audit.logger.write_audit_record") as audit:
        yield {"dense": dense, "sparse": sparse, "encoder": encoder, "audit": audit}


# --- identity (gateway-asserted headers, never the body) ---

def test_missing_identity_headers_rejected_401(mocks):
    resp = client.post("/retrieve/", json=BODY)
    assert resp.status_code == 401
    mocks["dense"].assert_not_called()
    mocks["audit"].assert_not_called()


def test_malformed_tenant_header_rejected_401(mocks):
    headers = {"X-Tenant-Id": "agency x; drop", "X-User-Id": "co-001"}
    resp = client.post("/retrieve/", json=BODY, headers=headers)
    assert resp.status_code == 401
    mocks["dense"].assert_not_called()


def test_missing_role_header_rejected_401(mocks):
    # Role is required: without X-User-Role the audit record would otherwise
    # default to 'contracting_officer' and falsify the authority trail.
    headers = {"X-Tenant-Id": "agency_x", "X-User-Id": "co-001"}
    resp = client.post("/retrieve/", json=BODY, headers=headers)
    assert resp.status_code == 401
    mocks["dense"].assert_not_called()
    mocks["audit"].assert_not_called()


def test_body_supplied_identity_is_ignored(mocks):
    # A caller smuggling tenant_id/user_id/role in the body must not influence
    # the corpus scope or the audit trail — identity comes from headers only.
    body = {**BODY, "tenant_id": "agency_evil", "user_id": "forged-co", "role": "sys_admin"}
    resp = client.post("/retrieve/", json=body, headers=IDENTITY_HEADERS)
    assert resp.status_code == 200

    tenant_ids = mocks["dense"].call_args[0][1]
    assert tenant_ids == ["far_corpus_global", "agency_x"]
    assert "agency_evil" not in tenant_ids

    record = mocks["audit"].call_args[0][0]
    assert record.tenant_id == "agency_x"
    assert record.user_id == "co-001"
    # Real role comes from the X-User-Role header, never the body.
    assert record.role == "contracting_officer"


def test_audit_records_real_non_co_role(mocks):
    # A non-CO caller's retrieval is recorded with their REAL role, not a
    # defaulted 'contracting_officer' (review finding — no falsified authority).
    headers = {**IDENTITY_HEADERS, "X-User-Role": "contract_specialist"}
    resp = client.post("/retrieve/", json=BODY, headers=headers)
    assert resp.status_code == 200
    record = mocks["audit"].call_args[0][0]
    assert record.role == "contract_specialist"


# --- input bounds ---

def test_oversized_query_rejected_422(mocks):
    body = {**BODY, "query": "x" * 5000}
    resp = client.post("/retrieve/", json=body, headers=IDENTITY_HEADERS)
    assert resp.status_code == 422
    mocks["dense"].assert_not_called()


def test_empty_query_rejected_422(mocks):
    body = {**BODY, "query": ""}
    resp = client.post("/retrieve/", json=body, headers=IDENTITY_HEADERS)
    assert resp.status_code == 422


# --- happy path + audit pairing after cross-encoder reorder ---

def test_rerank_reorder_keeps_per_index_alignment(mocks):
    """The cross-encoder reorders results — chunks_retrieved[i],
    retrieval_scores[i], reranked_scores[i] must stay aligned by chunk
    identity, not by pre-rerank position."""
    # Fused order (RRF): d1 (both lists) > d2 / s1. FakeEncoder reverses:
    # sparse one (0.9) > dense two (0.5) > dense one (0.1).
    mocks["encoder"].return_value = FakeEncoder(
        {"dense one text": 0.1, "dense two text": 0.5, "sparse one text": 0.9}
    )

    resp = client.post("/retrieve/", json=BODY, headers=IDENTITY_HEADERS)
    assert resp.status_code == 200
    payload = resp.json()

    # Response order follows the cross-encoder, not fused order.
    assert [c["chunk_id"] for c in payload["chunks"]] == ["s1", "d2", "d1"]
    assert [c["score"] for c in payload["chunks"]] == [0.9, 0.5, 0.1]

    # Audit record: per-index alignment by identity against an independently
    # computed fusion of the same inputs.
    expected_fused = {
        doc.metadata["chunk_id"]: score
        for doc, score in fusion.reciprocal_rank_fusion(DENSE, SPARSE)
    }
    record = mocks["audit"].call_args[0][0]
    assert record.chunks_retrieved == ["s1", "d2", "d1"]
    assert record.reranked_scores == [0.9, 0.5, 0.1]
    for i, cid in enumerate(record.chunks_retrieved):
        assert record.retrieval_scores[i] == pytest.approx(expected_fused[cid])
    assert record.retrieval_strategy == "hybrid_rrf_reranked"


def test_no_empty_chunk_ids_in_audit(mocks):
    resp = client.post("/retrieve/", json=BODY, headers=IDENTITY_HEADERS)
    assert resp.status_code == 200
    record = mocks["audit"].call_args[0][0]
    assert all(record.chunks_retrieved)


# --- shared identity key (FIX 10): audit scores pair via fusion.doc_key ---

def test_router_uses_fusion_doc_key_for_audit_pairing(mocks):
    # The router's audit-score lookup must go through fusion.doc_key — the same
    # helper fusion dedupes with — so the keys can never drift.
    with patch(
        "app.retrieval.router.fusion.doc_key", side_effect=fusion.doc_key
    ) as spy:
        resp = client.post("/retrieve/", json=BODY, headers=IDENTITY_HEADERS)
    assert resp.status_code == 200
    # Called for the fused-score map build AND each per-chunk audit lookup.
    assert spy.called


def test_audit_score_miss_logs_warning(mocks, caplog):
    # Simulate identity drift: the reranker hands back a chunk whose key was
    # never in the fused-score map (what a divergent lookup key would cause).
    # The router must warn loudly before zeroing the audit score — silent
    # zeroing is the exact hazard fusion.doc_key exists to prevent.
    ghost = _doc("ghost", "ghost text never fused")
    ranked = [
        (ghost, 0.7),
        (_doc("d1", "dense one text"), 0.5),
        (_doc("d2", "dense two text"), 0.3),
    ]
    with patch("app.retrieval.reranker.rerank", return_value=(ranked, False)):
        with caplog.at_level(
            logging.WARNING, logger="ai-orchestrator.retrieval.router"
        ):
            resp = client.post("/retrieve/", json=BODY, headers=IDENTITY_HEADERS)

    assert resp.status_code == 200
    assert any("audit retrieval_score zeroed" in r.message for r in caplog.records)
    # Only the ghost chunk is zeroed; real chunks keep their fused scores.
    record = mocks["audit"].call_args[0][0]
    assert record.chunks_retrieved[0] == "ghost"
    assert record.retrieval_scores[0] == 0.0
    assert all(s > 0 for s in record.retrieval_scores[1:])


# --- audit fail-closed ---

def test_audit_write_failure_fails_closed_503(mocks):
    mocks["audit"].side_effect = Exception("mongo down")
    resp = client.post("/retrieve/", json=BODY, headers=IDENTITY_HEADERS)
    assert resp.status_code == 503
    # No unaudited retrieval content leaves the service.
    assert "chunks" not in resp.json()


# --- fallback ladder + breaker accounting ---

def test_dense_mongo_failure_falls_back_and_counts(mocks):
    mocks["dense"].side_effect = OperationFailure("vector index gone")
    resp = client.post("/retrieve/", json=BODY, headers=IDENTITY_HEADERS)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["degraded"] is True
    assert payload["retrieval_strategy"] == "sparse_bm25_fallback"
    # Mongo-typed dense failure counts toward the breaker and is NOT erased
    # by the sparse path succeeding in the same request.
    assert failures._consecutive_failures == 1


def test_dense_non_mongo_failure_does_not_move_breaker(mocks):
    # e.g. a Bedrock embedding error — breaker is MongoDB-only (failures.py).
    mocks["dense"].side_effect = RuntimeError("bedrock throttled")
    resp = client.post("/retrieve/", json=BODY, headers=IDENTITY_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["retrieval_strategy"] == "sparse_bm25_fallback"
    assert failures._consecutive_failures == 0


def test_sparse_mongo_failure_counts_toward_breaker(mocks):
    mocks["sparse"].side_effect = OperationFailure("text index gone")
    resp = client.post("/retrieve/", json=BODY, headers=IDENTITY_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["retrieval_strategy"] == "dense_only_fallback"
    assert failures._consecutive_failures == 1


def test_both_paths_failing_returns_502(mocks):
    mocks["dense"].side_effect = OperationFailure("down")
    mocks["sparse"].side_effect = OperationFailure("down")
    resp = client.post("/retrieve/", json=BODY, headers=IDENTITY_HEADERS)
    assert resp.status_code == 502
    mocks["audit"].assert_not_called()


def test_open_breaker_returns_503_without_searching(mocks):
    for _ in range(failures._CB_THRESHOLD):
        failures.record_failure()
    resp = client.post("/retrieve/", json=BODY, headers=IDENTITY_HEADERS)
    assert resp.status_code == 503
    mocks["dense"].assert_not_called()

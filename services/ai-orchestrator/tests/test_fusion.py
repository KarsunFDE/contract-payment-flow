"""Tests for retrieval/fusion.py — no Mongo/Bedrock required."""
import logging

import pytest
from langchain_core.documents import Document

from app.retrieval.fusion import doc_key, reciprocal_rank_fusion


def _doc(chunk_id: str, text: str = "text") -> Document:
    return Document(page_content=text, metadata={"chunk_id": chunk_id})


# --- doc_key (shared identity helper) ---

def test_doc_key_uses_chunk_id_when_present():
    doc = Document(page_content="some text", metadata={"chunk_id": "far-43-103"})
    assert doc_key(doc) == "far-43-103"


def test_doc_key_falls_back_to_content_prefix_when_missing(caplog):
    text = "x" * 100
    doc = Document(page_content=text, metadata={})
    with caplog.at_level(logging.WARNING, logger="ai-orchestrator.retrieval.fusion"):
        key = doc_key(doc)
    assert key == text[:64]
    assert any("missing chunk_id" in r.message for r in caplog.records)


def test_doc_key_empty_chunk_id_falls_back():
    doc = Document(page_content="content here", metadata={"chunk_id": ""})
    assert doc_key(doc) == "content here"


def test_rrf_returns_all_unique_chunks():
    dense = [(_doc("a"), 0.9), (_doc("b"), 0.7)]
    sparse = [_doc("b"), _doc("c")]
    result = reciprocal_rank_fusion(dense, sparse)
    ids = [d.metadata["chunk_id"] for d, _ in result]
    assert sorted(ids) == ["a", "b", "c"]


def test_rrf_deduplicates_overlap():
    dense = [(_doc("a"), 0.9), (_doc("b"), 0.7)]
    sparse = [_doc("a"), _doc("b")]
    result = reciprocal_rank_fusion(dense, sparse)
    assert len(result) == 2


def test_rrf_dense_rank1_beats_sparse_rank1():
    # a: rank 0 dense (weight 0.6) + rank 1 sparse (weight 0.4)
    # b: rank 1 dense + rank 0 sparse
    # a should beat b because dense weight is higher and a is rank 0 in dense
    dense = [(_doc("a"), 0.9), (_doc("b"), 0.5)]
    sparse = [_doc("b"), _doc("a")]
    result = reciprocal_rank_fusion(dense, sparse, dense_weight=0.6, sparse_weight=0.4)
    top_id = result[0][0].metadata["chunk_id"]
    assert top_id == "a"


def test_rrf_sparse_only():
    result = reciprocal_rank_fusion([], [_doc("x"), _doc("y")])
    assert len(result) == 2
    assert result[0][0].metadata["chunk_id"] == "x"


def test_rrf_dense_only():
    result = reciprocal_rank_fusion([(_doc("x"), 0.9), (_doc("y"), 0.5)], [])
    assert len(result) == 2
    assert result[0][0].metadata["chunk_id"] == "x"


def test_rrf_empty_inputs():
    assert reciprocal_rank_fusion([], []) == []


def test_rrf_score_formula():
    doc = _doc("a")
    result = reciprocal_rank_fusion([(doc, 0.99)], [doc], dense_weight=0.6, sparse_weight=0.4, k=60)
    # dense rank 0 + sparse rank 0 → (0.6 + 0.4) / 61
    expected = 1.0 / 61
    assert abs(result[0][1] - expected) < 1e-10


def test_rrf_descending_order():
    docs = [_doc(str(i)) for i in range(5)]
    dense = [(d, 1.0) for d in docs]
    result = reciprocal_rank_fusion(dense, [])
    scores = [s for _, s in result]
    assert scores == sorted(scores, reverse=True)

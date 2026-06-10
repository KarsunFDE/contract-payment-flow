"""Tests for retrieval/retriever.py — mocks MongoDB, no live connection required."""
from unittest.mock import MagicMock, patch
import app.retrieval.retriever  # ensure module in sys.modules before patch resolves target

import pytest
from langchain_core.documents import Document


# --- sparse_search ---

def test_sparse_search_applies_tenant_filter():
    mock_col = MagicMock()
    mock_col.aggregate.return_value = iter([])

    with patch("app.retrieval.retriever.db.get_far_corpus", return_value=mock_col):
        from app.retrieval.retriever import sparse_search
        sparse_search("contract modifications", ["far_corpus_global", "agency_x"])

    pipeline = mock_col.aggregate.call_args[0][0]
    # tenant scoping must live inside $search (filter clause), not only as a
    # post-$search $match — otherwise BM25 ranks across all tenants.
    search_stage = next(s for s in pipeline if "$search" in s)
    search_filter = search_stage["$search"]["compound"]["filter"]
    assert {"in": {"path": "tenant_id", "value": ["far_corpus_global", "agency_x"]}} in search_filter
    # defensive $match retained as defense-in-depth
    match_stage = next(s for s in pipeline if "$match" in s)
    assert match_stage["$match"]["tenant_id"]["$in"] == ["far_corpus_global", "agency_x"]


def test_sparse_search_limits_results():
    mock_col = MagicMock()
    mock_col.aggregate.return_value = iter([])

    with patch("app.retrieval.retriever.db.get_far_corpus", return_value=mock_col):
        from app.retrieval.retriever import sparse_search
        sparse_search("query", ["far_corpus_global"], k=5)

    pipeline = mock_col.aggregate.call_args[0][0]
    limit_stage = next(s for s in pipeline if "$limit" in s)
    assert limit_stage["$limit"] == 5


def test_sparse_search_maps_raw_to_documents():
    raw_doc = {
        "chunk_id": "abc-123",
        "chunk_text": "FAR 43.103 defines types of contract modifications.",
        "source_document": {"far_part": "43", "clause_number": "43.103"},
        "tenant_id": "far_corpus_global",
        "_search_score": 0.85,
    }
    mock_col = MagicMock()
    mock_col.aggregate.return_value = iter([raw_doc])

    with patch("app.retrieval.retriever.db.get_far_corpus", return_value=mock_col):
        from app.retrieval.retriever import sparse_search
        results = sparse_search("43.103", ["far_corpus_global"])

    assert len(results) == 1
    assert results[0].page_content == "FAR 43.103 defines types of contract modifications."
    assert results[0].metadata["chunk_id"] == "abc-123"
    assert results[0].metadata["score"] == 0.85


def test_sparse_search_returns_empty_on_no_results():
    mock_col = MagicMock()
    mock_col.aggregate.return_value = iter([])

    with patch("app.retrieval.retriever.db.get_far_corpus", return_value=mock_col):
        from app.retrieval.retriever import sparse_search
        results = sparse_search("no match", ["far_corpus_global"])

    assert results == []


# --- dense_search chunk_id integrity (security review finding) ---

def _patch_dense(results):
    """Patch the vector store + embeddings so dense_search runs offline and
    similarity_search_with_score returns `results`."""
    vector_store = MagicMock()
    vector_store.similarity_search_with_score.return_value = results
    return patch.multiple(
        "app.retrieval.retriever",
        db=MagicMock(),
        _get_embeddings=MagicMock(return_value=object()),
        MongoDBAtlasVectorSearch=MagicMock(return_value=vector_store),
    )


def test_dense_search_passes_through_real_chunk_id():
    doc = Document(page_content="FAR 43.103", metadata={"chunk_id": "uuid-1", "_id": "OID"})
    with _patch_dense([(doc, 0.9)]):
        from app.retrieval.retriever import dense_search
        results = dense_search("mods", ["far_corpus_global"])
    assert results[0][0].metadata["chunk_id"] == "uuid-1"
    # Mongo _id stripped so nothing downstream mistakes it for chunk identity.
    assert "_id" not in results[0][0].metadata


def test_dense_search_fails_closed_when_chunk_id_missing():
    """A dense result without the UUID chunk_id must NOT fall back to the Mongo
    _id — that ObjectId can't resolve back to the corpus chunk and would corrupt
    the DCAA-traceable audit log. Fail closed instead."""
    doc = Document(page_content="FAR 43.103", metadata={"_id": "OID-only"})
    with _patch_dense([(doc, 0.9)]):
        from app.retrieval.retriever import dense_search
        with pytest.raises(ValueError) as exc:
            dense_search("mods", ["far_corpus_global"])
    assert "chunk_id" in str(exc.value)
    # The unresolvable _id must NOT have been substituted in as chunk_id.
    assert doc.metadata.get("chunk_id") in (None, "")


def test_dense_search_fails_closed_on_blank_chunk_id():
    doc = Document(page_content="x", metadata={"chunk_id": "  ", "_id": "OID"})
    with _patch_dense([(doc, 0.5)]):
        from app.retrieval.retriever import dense_search
        with pytest.raises(ValueError):
            dense_search("q", ["far_corpus_global"])


# --- _tenant_ids ---

def test_tenant_ids_includes_global():
    from app.retrieval.retriever import _tenant_ids
    ids = _tenant_ids("agency_42")
    assert "far_corpus_global" in ids
    assert "agency_42" in ids


def test_tenant_ids_no_duplicate_global():
    from app.retrieval.retriever import _tenant_ids
    from app import config
    ids = _tenant_ids(config.GLOBAL_TENANT_ID)
    assert ids.count("far_corpus_global") == 1


# --- _get_embeddings uses the shared write-path factory ---

def test_get_embeddings_uses_shared_factory():
    # Query vectors must come from the SAME factory as the indexed vectors so
    # the kwargs can never drift (ADR-0005 §3). Reset the module cache first.
    import app.retrieval.retriever as retriever_mod

    retriever_mod._embeddings = None
    sentinel = object()
    with patch(
        "app.retrieval.retriever.build_bedrock_embeddings", return_value=sentinel
    ) as factory:
        result = retriever_mod._get_embeddings()

    factory.assert_called_once()
    assert result is sentinel
    # cached: a second call must not rebuild
    with patch(
        "app.retrieval.retriever.build_bedrock_embeddings"
    ) as factory2:
        assert retriever_mod._get_embeddings() is sentinel
        factory2.assert_not_called()
    retriever_mod._embeddings = None


# --- hybrid_search delegates correctly ---

def test_hybrid_search_calls_both_searches():
    with patch("app.retrieval.retriever.dense_search", return_value=[]) as mock_dense, \
         patch("app.retrieval.retriever.sparse_search", return_value=[]) as mock_sparse:
        from app.retrieval.retriever import hybrid_search
        hybrid_search("query", agency_id="agency_99")

    mock_dense.assert_called_once()
    mock_sparse.assert_called_once()
    # both must receive the same tenant_ids
    assert mock_dense.call_args[0][1] == mock_sparse.call_args[0][1]
    assert "far_corpus_global" in mock_dense.call_args[0][1]
    assert "agency_99" in mock_dense.call_args[0][1]

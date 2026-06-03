"""
test_ingestion_pipeline.py — chunk → embed → insert pipeline (ADR-0005).

Owner: Person A. Bedrock and MongoDB are mocked — these tests verify
orchestration and §12 provenance assembly, not external services.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from app import config
from app.ingestion import pipeline
from app.schemas import ChunkDocument, IngestedBy, SourceDocument


@pytest.fixture
def far_source() -> SourceDocument:
    return SourceDocument(
        title="FAR Part 43 — Contract Modifications",
        far_part="43",
        subpart="43.1",
        clause_number="43.103",
        url="https://www.acquisition.gov/far/part-43",
    )


@pytest.fixture
def co_identity() -> IngestedBy:
    return IngestedBy(user_id="co-001")


# --- shared test helpers ---

def _fake_chunks():
    return [
        {
            "chunk_text": "43.103 Types of contract modifications. A bilateral modification requires both parties.",
            "chunk_sequence": 0,
            "far_part": "43",
            "subpart": "43.1",
            "clause_number": "43.103",
        },
        {
            "chunk_text": "Unilateral modifications are signed only by the contracting officer.",
            "chunk_sequence": 1,
            "far_part": "43",
            "subpart": "43.1",
            "clause_number": "43.103",
        },
    ]


def _mock_embedder(hits: int = 1, dims: int = 3) -> MagicMock:
    """Return a mock MongoCachedEmbedder whose embed_documents returns dummy vectors."""
    emb = MagicMock()
    emb.embed_documents.side_effect = lambda texts: [[0.1] * dims for _ in texts]
    emb._last_hits = hits
    emb._last_misses = 0
    return emb


# --- tests ---

def test_ingest_document_inserts_full_provenance(far_source, co_identity):
    """Every inserted doc carries the complete §12 field set.

    Mock chunker + embedder + far_corpus collection; assert each insert_many
    document validates as ChunkDocument and carries embedding_model,
    embedding_dimensions=512, tenant_id, ingestion_timestamp, ingested_by.
    """
    mock_collection = MagicMock()

    with patch("app.ingestion.chunker.chunk_document", return_value=_fake_chunks()), \
         patch("app.ingestion.embedder.build_cached_embedder", return_value=_mock_embedder()), \
         patch("app.db.get_far_corpus", return_value=mock_collection):

        result = pipeline.ingest_document(
            document_text="43.103 Types of contract modifications.\n\n" + "A" * 200,
            source=far_source,
            document_version="2024-01-01",
            ingested_by=co_identity,
        )

    mock_collection.insert_many.assert_called_once()
    inserted = mock_collection.insert_many.call_args[0][0]
    assert len(inserted) == 2

    for raw in inserted:
        doc = ChunkDocument(**raw)
        assert doc.embedding_model == config.EMBEDDING_MODEL_ID
        assert doc.embedding_dimensions == 512
        assert doc.embedding_model_version == config.EMBEDDING_MODEL_VERSION
        assert doc.tenant_id == config.GLOBAL_TENANT_ID
        assert doc.ingestion_timestamp is not None
        assert doc.ingested_by.user_id == "co-001"
        assert doc.document_version == "2024-01-01"

    assert result["chunks_inserted"] == 2
    assert result["cache_hits"] == 1
    assert result["source_title"] == far_source.title


def test_ingest_document_default_tenant_is_global(far_source, co_identity):
    """Seed/dev ingestion defaults to tenant_id='far_corpus_global' (§11)."""
    mock_collection = MagicMock()

    with patch("app.ingestion.chunker.chunk_document", return_value=_fake_chunks()), \
         patch("app.ingestion.embedder.build_cached_embedder", return_value=_mock_embedder()), \
         patch("app.db.get_far_corpus", return_value=mock_collection):

        pipeline.ingest_document(
            document_text="dummy text",
            source=far_source,
            document_version="2024-01-01",
            ingested_by=co_identity,
            # tenant_id deliberately omitted — should default to GLOBAL_TENANT_ID
        )

    inserted = mock_collection.insert_many.call_args[0][0]
    for raw in inserted:
        assert raw["tenant_id"] == config.GLOBAL_TENANT_ID


def test_embedding_failure_does_not_insert(far_source, co_identity):
    """§10 — embedding failure propagates; nothing partial reaches far_corpus."""
    failing_embedder = MagicMock()
    failing_embedder.embed_documents.side_effect = RuntimeError("Bedrock auth failure")

    mock_collection = MagicMock()

    with patch("app.ingestion.chunker.chunk_document", return_value=_fake_chunks()), \
         patch("app.ingestion.embedder.build_cached_embedder", return_value=failing_embedder), \
         patch("app.db.get_far_corpus", return_value=mock_collection):

        with pytest.raises(RuntimeError, match="Bedrock auth failure"):
            pipeline.ingest_document(
                document_text="dummy text",
                source=far_source,
                document_version="2024-01-01",
                ingested_by=co_identity,
            )

    mock_collection.insert_many.assert_not_called()


def test_ingest_seed_corpus_walks_seed_directory(tmp_path):
    """Seed loader ingests every .md (excluding README.md) under the seed dir."""
    (tmp_path / "far-43-103-types.md").write_text(
        "43.103 Types of contract modifications.\n\nA bilateral modification is signed by both parties.\n",
        encoding="utf-8",
    )
    (tmp_path / "far-32-905-clauses.md").write_text(
        "32.905 Payment documentation and process.\n\nInvoices must cite the contract number.\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("Seed data overview — not a FAR document.\n", encoding="utf-8")

    ingested_sources: list[str] = []

    def _capture_ingest(document_text, source, document_version, ingested_by, tenant_id):
        ingested_sources.append(source.title)
        return {"chunks_inserted": 1, "chunks_discarded": 0, "cache_hits": 0, "source_title": source.title}

    with patch("app.ingestion.pipeline.ingest_document", side_effect=_capture_ingest):
        result = pipeline.ingest_seed_corpus(str(tmp_path))

    assert result["files_ingested"] == 2
    assert result["chunks_inserted"] == 2
    # README.md must not have been passed to ingest_document
    assert all("readme" not in t.lower() for t in ingested_sources)
    # Both .md files were processed
    assert len(ingested_sources) == 2


def test_ingestion_run_record_shape():
    """Audit entry has event type, counts, started/finished, duration_ms."""
    started = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    summary = {"chunks_inserted": 42, "cache_hits": 10, "source_title": "FAR 43"}

    record = pipeline.make_ingestion_run_record(summary, started)

    assert record["event"] == "corpus_ingestion"
    assert record["summary"] is summary
    assert record["started_at"] == started
    assert isinstance(record["finished_at"], datetime)
    assert record["finished_at"] >= started
    assert isinstance(record["duration_ms"], int)
    assert record["duration_ms"] >= 0

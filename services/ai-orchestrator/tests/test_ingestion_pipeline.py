"""
test_ingestion_pipeline.py — chunk → embed → insert pipeline (ADR-0005).

Owner: Person A. Bedrock and MongoDB are mocked — these tests verify
orchestration and §12 provenance assembly, not external services.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app import config
from app.ingestion import pipeline
from app.schemas import IngestedBy, SourceDocument


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


@pytest.mark.skip(reason="Person A W1 — pipeline not implemented yet")
def test_ingest_document_inserts_full_provenance(far_source, co_identity):
    """Every inserted doc carries the complete §12 field set.

    Mock chunker + embedder + far_corpus collection; assert each insert_many
    document validates as ChunkDocument and carries embedding_model,
    embedding_dimensions=512, tenant_id, ingestion_timestamp, ingested_by.
    """
    # TODO(A): patch chunker.chunk_document, embedder.build_cached_embedder,
    #   db.get_far_corpus; capture insert_many payload.
    ...


@pytest.mark.skip(reason="Person A W1 — pipeline not implemented yet")
def test_ingest_document_default_tenant_is_global(far_source, co_identity):
    """Seed/dev ingestion defaults to tenant_id='far_corpus_global' (§11)."""
    ...


@pytest.mark.skip(reason="Person A W1 — pipeline not implemented yet")
def test_embedding_failure_does_not_insert(far_source, co_identity):
    """§10 — embedding failure propagates; nothing partial reaches far_corpus."""
    # TODO(A): make the embedder raise; assert insert_many never called and
    #   the exception escapes (caller queues retry).
    ...


@pytest.mark.skip(reason="Person A W1 — pipeline not implemented yet")
def test_ingest_seed_corpus_walks_seed_directory(tmp_path):
    """Seed loader ingests every .md (excluding README.md) under the seed dir."""
    # TODO(A): write 2 fixture .md files + a README.md into tmp_path; assert
    #   ingest_document called twice with derived metadata.
    ...


@pytest.mark.skip(reason="Person A W1 — pipeline not implemented yet")
def test_ingestion_run_record_shape():
    """Audit entry has event type, counts, started/finished, duration_ms."""
    ...

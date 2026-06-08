"""
Day 0 scaffolding smoke tests (ADR-0005 Phase 1).

Verifies the shared contract files import cleanly with no MongoDB running
and that both routers are registered on the app. Owned jointly — frozen
after Day 0 like the files it covers.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app import config
from app.main import app
from app.schemas import (
    ChunkDocument,
    IngestedBy,
    RetrievalAuditRecord,
    SourceDocument,
)


def test_config_adr_values():
    """Pinned ADR-0005 values — a drive-by change here should fail loudly."""
    assert config.EMBEDDING_MODEL_ID == "amazon.titan-embed-text-v2:0"
    assert config.EMBEDDING_DIMENSIONS == 512
    assert config.FAR_VECTOR_INDEX == "far_vector_idx"
    assert config.FAR_TEXT_INDEX == "far_text_idx"
    assert config.RRF_DENSE_WEIGHT == 0.6
    assert config.RRF_SPARSE_WEIGHT == 0.4
    assert config.RERANK_TOP_N == 8
    assert config.CHUNK_SIZE_TOKENS == 512
    assert config.CHUNK_OVERLAP_TOKENS == 64
    assert config.GLOBAL_TENANT_ID == "far_corpus_global"
    assert config.CONFIDENCE_THRESHOLD == 0.85


def test_routers_registered():
    """Both Phase 1 routers mounted — main.py stays frozen after Day 0."""
    tags = {tag for route in app.routes for tag in getattr(route, "tags", []) or []}
    assert "corpus-ingestion" in tags
    assert "retrieval" in tags


def test_db_module_imports_without_mongo():
    """db.py is lazy — importing it must not attempt a connection."""
    from app import db  # noqa: F401


def test_chunk_document_provenance_fields():
    """ChunkDocument carries the full ADR-0005 §12 provenance field set."""
    chunk = ChunkDocument(
        chunk_text="(a) Contract modifications may be issued...",
        chunk_sequence=0,
        source_document=SourceDocument(
            title="FAR Part 43 — Contract Modifications",
            far_part="43",
            subpart="43.1",
            clause_number="43.103",
            url="https://www.acquisition.gov/far/43.103",
        ),
        document_version="2026-06-01",
        ingested_by=IngestedBy(user_id="co-001", role="contracting_officer"),
        embedding_model=config.EMBEDDING_MODEL_ID,
        tenant_id=config.GLOBAL_TENANT_ID,
        embedding=[0.0] * config.EMBEDDING_DIMENSIONS,
    )
    assert chunk.chunk_id  # auto-generated UUID
    assert chunk.embedding_dimensions == 512
    # role is required and stored verbatim — no CO default.
    assert chunk.ingested_by.role == "contracting_officer"
    assert chunk.ingested_by.service == "ai-orchestrator-ingestion"
    assert chunk.ingestion_timestamp.tzinfo is not None


def test_retrieval_audit_record_fields():
    """RetrievalAuditRecord carries the full ADR-0005 §12 log field set."""
    record = RetrievalAuditRecord(
        correlation_id="11111111-1111-1111-1111-111111111111",
        sf30_block="13",
        contract_id="W912-26-C-0001",
        tenant_id=config.GLOBAL_TENANT_ID,
        user_id="co-001",
        role="sys_admin",
        query_text="extend period of performance 90 days",
        retrieval_strategy="hybrid_rrf_reranked",
        embedding_model=config.EMBEDDING_MODEL_ID,
        latency_ms=420,
    )
    assert record.retrieval_id  # auto-generated UUID
    # role is required and stored verbatim — no 'contracting_officer' default.
    assert record.role == "sys_admin"
    assert record.cache_hit is False
    assert record.confidence is None  # Phase 2 fills this
    assert record.timestamp <= datetime.now(timezone.utc)

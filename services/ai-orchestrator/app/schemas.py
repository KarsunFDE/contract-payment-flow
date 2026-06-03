"""
schemas.py — shared Pydantic contracts for the retrieval layer (ADR-0005 §12).

Day 0 contract file: frozen after the scaffolding commit. This is THE
contract between the write path (ingestion inserts ChunkDocument) and the
read path (retrieval queries chunks, emits RetrievalAuditRecord). Changing
a field here requires both owners to agree.

Field sets mirror the ADR-0005 §12 provenance and retrieval-log tables
exactly — do not add or drop fields without updating the ADR.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid_str() -> str:
    return str(uuid4())


class SourceDocument(BaseModel):
    """Lineage of the document a chunk came from (ADR-0005 §12)."""
    title: str = Field(description='e.g. "FAR Part 43 — Contract Modifications"')
    far_part: str = Field(description='FAR part number, e.g. "43"')
    subpart: str = Field(description='FAR subpart, e.g. "43.1"')
    clause_number: str = Field(description='Clause identifier, e.g. "43.103"')
    url: str = Field(description="Canonical URL of the source document")


class IngestedBy(BaseModel):
    """Identity that triggered ingestion (HITL corpus-approval trail)."""
    user_id: str
    role: str = "contracting_officer"  # CO is the only role in the system
    service: str = "ai-orchestrator-ingestion"


class ChunkDocument(BaseModel):
    """One chunk in the far_corpus vector collection — full ADR-0005 §12
    provenance field set. Written by ingestion, read by retrieval."""
    chunk_id: str = Field(default_factory=_uuid_str)
    chunk_text: str
    chunk_sequence: int = Field(ge=0, description="Position within source document")
    source_document: SourceDocument
    document_version: str = Field(description="Date of the FAR corpus version ingested")
    ingestion_timestamp: datetime = Field(default_factory=_utc_now)
    ingested_by: IngestedBy
    embedding_model: str = Field(description='Bedrock model ID, e.g. "amazon.titan-embed-text-v2:0"')
    embedding_dimensions: int = 512
    embedding_model_version: str = "v2"
    tenant_id: str = Field(
        description='"far_corpus_global" or an <agency_id> for tenant-scoped docs'
    )
    embedding: list[float] = Field(description="The vector representation")


class RetrievalAuditRecord(BaseModel):
    """One retrieval event in the audit collection — full ADR-0005 §12
    retrieval-log field set. Append-only; satisfies DCAA traceability."""
    correlation_id: str = Field(
        description="UUID generated at CO request entry; shared across all "
                    "pipeline node audit records for this request"
    )
    retrieval_id: str = Field(default_factory=_uuid_str)
    sf30_block: str = Field(description='Which SF-30 block triggered retrieval, e.g. "13"')
    contract_id: str
    tenant_id: str
    user_id: str
    role: str = "contracting_officer"
    timestamp: datetime = Field(default_factory=_utc_now)
    query_text: str
    retrieval_strategy: str = Field(description='e.g. "hybrid_rrf_reranked"')
    chunks_retrieved: list[str] = Field(default_factory=list, description="chunk_id UUIDs")
    retrieval_scores: list[float] = Field(default_factory=list, description="Pre-rerank")
    reranked_scores: list[float] = Field(default_factory=list, description="Post-rerank")
    confidence: float | None = Field(
        default=None, description="LLM-as-judge aggregate (Phase 2 fills this)"
    )
    embedding_model: str
    llm_model: str | None = Field(
        default=None, description="Haiku/Sonnet ID for confidence check (Phase 2)"
    )
    cache_hit: bool = False
    latency_ms: int = Field(ge=0)

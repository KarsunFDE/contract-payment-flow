"""
pipeline.py — corpus ingestion pipeline: chunk → embed → insert (ADR-0005).

Owner: Person A (write path).

Orchestrates one document's journey into the far_corpus vector collection:

    raw document text
        → chunker.chunk_document()          (§13 section-boundary chunks)
        → embedder.build_cached_embedder()  (§3 Titan V2, §14 cache)
        → ChunkDocument provenance assembly (§12 full lineage metadata)
        → far_corpus insert_many

Ingestion is OFFLINE/ASYNC relative to CO requests — never runs inside a
retrieval request (§8 anti-pattern: synchronous ingestion). Triggered by
the /corpus/ingest endpoint or the seed script.

HITL gate (§15): a CO must approve a document batch before it is ingested.
The router enforces the approval flow; this module assumes the caller is
already authorized.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app import config, db
from app.ingestion import chunker, embedder
from app.schemas import ChunkDocument, IngestedBy, SourceDocument

log = logging.getLogger("ai-orchestrator.ingestion.pipeline")


def ingest_document(
    document_text: str,
    source: SourceDocument,
    document_version: str,
    ingested_by: IngestedBy,
    tenant_id: str = config.GLOBAL_TENANT_ID,
) -> dict:
    """Ingest one source document end-to-end into far_corpus.

    Steps:
      1. Chunk via chunker.chunk_document() — §13 rules applied there.
      2. Embed all chunk texts in one batch through the cached embedder
         (cache hits skip Bedrock entirely, §14).
      3. Assemble full ChunkDocument provenance per chunk (§12 field set —
         model ID, dimensions, version, timestamps, ingested_by, tenant).
      4. insert_many into far_corpus.

    Args:
        document_text: Raw text of the source document.
        source: Document lineage (title, far_part, subpart, clause, url).
        document_version: Date string of the FAR corpus version ingested.
        ingested_by: Identity that triggered ingestion (HITL trail).
        tenant_id: "far_corpus_global" or an <agency_id> (§11).

    Returns:
        Summary dict: {"chunks_inserted": int, "chunks_discarded": int,
        "cache_hits": int, "source_title": str}.

    Raises:
        Embedding failures propagate — caller queues a retry and writes an
        audit record (§10: no proceeding to draft, no silent failure).
    """
    # TODO(A): wire steps 1-4. Validate every chunk through ChunkDocument
    #   BEFORE insert — Pydantic is the §12 contract gate with Person B.
    raise NotImplementedError


def ingest_seed_corpus(seed_dir: str = "data/seed/far-part-42-43-32") -> dict:
    """Bulk-ingest the seed FAR stub documents (dev/local bootstrap).

    Walks the seed directory, derives SourceDocument metadata from each
    file's frontmatter/filename (e.g. far-43-103-types.md → far_part "43",
    clause "43.103"), and runs ingest_document() per file under
    tenant_id="far_corpus_global".

    Real government documents (full FAR 32 etc.) swap in later — same
    pipeline, different source files.

    Returns:
        Aggregate summary across all seed files.
    """
    # TODO(A): glob *.md (skip README.md), parse metadata, loop
    #   ingest_document(); log per-file chunk counts.
    raise NotImplementedError


def make_ingestion_run_record(summary: dict, started_at: datetime) -> dict:
    """Build a structured ingestion audit entry for the audit collection.

    Ingestion is a write-path event but still auditable (§12 "who done it"
    trail — ingested_by, counts, duration). Keeps DCAA lineage complete
    even before Person B's retrieval audit logger lands.
    """
    # TODO(A): shape: {event: "corpus_ingestion", summary, started_at,
    #   finished_at: datetime.now(timezone.utc), duration_ms}.
    raise NotImplementedError

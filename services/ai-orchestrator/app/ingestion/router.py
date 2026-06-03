"""
ingestion/router.py — corpus write-path endpoints (ADR-0005 Phase 1).

Owner: Person A.

Endpoints:
  GET  /corpus/_status — Day 0 wiring check.
  POST /corpus/upload  — accept a FAR/DFARS/WAWF/PIEE source document file
                         (md/txt) plus its provenance metadata; stage it
                         for ingestion. HITL gate (§15): upload is the CO
                         review/approval step — nothing reaches the vector
                         store until /corpus/ingest is called.
  POST /corpus/ingest  — run the staged document(s) through the ingestion
                         pipeline: chunk → embed → insert with full §12
                         provenance metadata.
  GET  /corpus/stats   — corpus visibility: chunk counts by tenant/far_part,
                         embedding model versions present (supports §9
                         index-management monitoring).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app import config, db
from app.ingestion import pipeline
from app.schemas import IngestedBy, SourceDocument

log = logging.getLogger("ai-orchestrator.ingestion.router")

router = APIRouter(prefix="/corpus", tags=["corpus-ingestion"])

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_CONTENT_TYPES = {"text/markdown", "text/plain", "text/x-markdown"}
_ALLOWED_EXTENSIONS = {".md", ".txt"}


class UploadResponse(BaseModel):
    """Returned by /corpus/upload — staged document identity."""
    staged_document_id: str
    title: str
    size_bytes: int
    status: str = "staged_awaiting_ingest"


class IngestRequest(BaseModel):
    """Body for /corpus/ingest — which staged docs to ingest, and as whom."""
    staged_document_ids: list[str] = Field(min_length=1)
    user_id: str = Field(description="CO identity approving this batch (HITL §15)")
    tenant_id: str = config.GLOBAL_TENANT_ID
    document_version: str = Field(description="Date of the FAR corpus version")


class IngestResponse(BaseModel):
    """Returned by /corpus/ingest — per-document chunk summary."""
    documents_ingested: int
    chunks_inserted: int
    chunks_discarded: int
    cache_hits: int


@router.get("/_status")
def status() -> dict[str, str]:
    """Day 0 wiring check — confirms the write-path router is mounted."""
    return {"router": "corpus-ingestion", "status": "ok"}


@router.post("/upload", response_model=UploadResponse)
async def upload_corpus_document(
    file: UploadFile = File(description="FAR/DFARS/WAWF/PIEE source document (md/txt)"),
    title: str = Form(description='e.g. "FAR Part 43 — Contract Modifications"'),
    far_part: str = Form(description='FAR part number, e.g. "43"'),
    subpart: str = Form(default="", description='FAR subpart, e.g. "43.1"'),
    clause_number: str = Form(default="", description='e.g. "43.103"'),
    source_url: str = Form(default="", description="Canonical URL of the document"),
) -> UploadResponse:
    """Stage one source document for ingestion (HITL upload step).

    Validates the file type, reads the text, stores it with its
    SourceDocument metadata in a staging collection. Returns the staged
    ID the CO passes to /corpus/ingest after review.
    """
    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    ct = (file.content_type or "").lower().split(";")[0].strip()

    if ct not in _ALLOWED_CONTENT_TYPES and ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            415,
            f"Unsupported file type. Accept .md/.txt "
            f"(got content-type={ct!r}, extension={ext!r})",
        )

    raw = await file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(422, "File must be UTF-8 encoded text")

    staged_id = str(uuid4())
    staging_doc = {
        "staged_document_id": staged_id,
        "title": title,
        "far_part": far_part,
        "subpart": subpart,
        "clause_number": clause_number,
        "source_url": source_url,
        "text": text,
        "size_bytes": len(raw),
        "status": "staged_awaiting_ingest",
        "created_at": datetime.now(timezone.utc),
    }
    db.get_db()["corpus_staging"].insert_one(staging_doc)
    log.info("staged %r as %s (%d bytes)", title, staged_id, len(raw))

    return UploadResponse(staged_document_id=staged_id, title=title, size_bytes=len(raw))


@router.post("/ingest", response_model=IngestResponse)
def ingest_staged_documents(req: IngestRequest) -> IngestResponse:
    """Ingest CO-approved staged documents into the vector store.

    For each staged ID: load text + metadata from staging, run
    pipeline.ingest_document(), mark the staged doc consumed. Aggregates
    chunk counts across the batch.
    """
    staging = db.get_db()["corpus_staging"]
    started_at = datetime.now(timezone.utc)

    totals: dict[str, int] = {
        "documents_ingested": 0,
        "chunks_inserted": 0,
        "chunks_discarded": 0,
        "cache_hits": 0,
    }
    per_doc_summaries: list[dict] = []

    for sid in req.staged_document_ids:
        staged = staging.find_one({"staged_document_id": sid})
        if staged is None:
            raise HTTPException(404, f"staged_document_id {sid!r} not found")
        if staged.get("status") != "staged_awaiting_ingest":
            raise HTTPException(
                409, f"Document {sid!r} already consumed (status={staged.get('status')!r})"
            )

        source = SourceDocument(
            title=staged["title"],
            far_part=staged["far_part"],
            subpart=staged.get("subpart", ""),
            clause_number=staged.get("clause_number", ""),
            url=staged.get("source_url", ""),
        )
        ingested_by = IngestedBy(user_id=req.user_id)

        summary = pipeline.ingest_document(
            document_text=staged["text"],
            source=source,
            document_version=req.document_version,
            ingested_by=ingested_by,
            tenant_id=req.tenant_id,
        )

        staging.update_one(
            {"staged_document_id": sid},
            {"$set": {"status": "consumed", "consumed_at": datetime.now(timezone.utc)}},
        )

        totals["documents_ingested"] += 1
        totals["chunks_inserted"] += summary.get("chunks_inserted", 0)
        totals["chunks_discarded"] += summary.get("chunks_discarded", 0)
        totals["cache_hits"] += summary.get("cache_hits", 0)
        per_doc_summaries.append(summary)
        log.info("ingested staged doc %r — %d chunks", sid, summary.get("chunks_inserted", 0))

    run_record = pipeline.make_ingestion_run_record(
        summary={"per_document": per_doc_summaries, **totals},
        started_at=started_at,
    )
    db.get_retrieval_audit().insert_one(run_record)

    return IngestResponse(**totals)


@router.get("/stats")
def corpus_stats() -> dict:
    """Chunk counts by tenant_id / far_part + embedding model versions.

    Supports §9 routine monitoring (index size scale signal) and gives the
    frontend upload page something to display.
    """
    corpus = db.get_far_corpus()

    agg = list(corpus.aggregate([
        {
            "$group": {
                "_id": {
                    "tenant_id": "$tenant_id",
                    "far_part": "$source_document.far_part",
                },
                "chunk_count": {"$sum": 1},
            }
        },
        {"$sort": {"_id.tenant_id": 1, "_id.far_part": 1}},
    ]))

    model_versions = corpus.distinct("embedding_model_version")

    by_tenant_and_part = [
        {
            "tenant_id": r["_id"]["tenant_id"],
            "far_part": r["_id"]["far_part"],
            "chunk_count": r["chunk_count"],
        }
        for r in agg
    ]

    return {
        "by_tenant_and_part": by_tenant_and_part,
        "embedding_model_versions": model_versions,
        "total_chunks": sum(r["chunk_count"] for r in agg),
    }

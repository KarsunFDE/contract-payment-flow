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

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app import config
from app.ingestion import pipeline
from app.schemas import IngestedBy, SourceDocument

log = logging.getLogger("ai-orchestrator.ingestion.router")

router = APIRouter(prefix="/corpus", tags=["corpus-ingestion"])


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
    return {"router": "corpus-ingestion", "status": "scaffolded"}


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
    # TODO(A): reject non-md/txt content types; cap file size; insert into
    #   a corpus_staging collection with status "staged_awaiting_ingest".
    raise HTTPException(501, "upload not implemented yet — Person A W1")


@router.post("/ingest", response_model=IngestResponse)
def ingest_staged_documents(req: IngestRequest) -> IngestResponse:
    """Ingest CO-approved staged documents into the vector store.

    For each staged ID: load text + metadata from staging, run
    pipeline.ingest_document(), mark the staged doc consumed. Aggregates
    chunk counts across the batch.
    """
    # TODO(A): load staged docs (404 on unknown ID), build IngestedBy from
    #   req.user_id, call pipeline.ingest_document() per doc, write the
    #   ingestion run record (pipeline.make_ingestion_run_record).
    raise HTTPException(501, "ingest not implemented yet — Person A W1")


@router.get("/stats")
def corpus_stats() -> dict:
    """Chunk counts by tenant_id / far_part + embedding model versions.

    Supports §9 routine monitoring (index size scale signal) and gives the
    frontend upload page something to display.
    """
    # TODO(A): aggregate far_corpus: group by tenant_id + source_document.far_part;
    #   distinct embedding_model_version.
    raise HTTPException(501, "stats not implemented yet — Person A W1")

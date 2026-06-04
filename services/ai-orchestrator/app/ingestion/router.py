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

Security (review findings 1/2/3): /upload and /ingest require an authenticated
CO/sys_admin principal (app.ingestion.auth.require_corpus_admin). Identity
(ingested_by) and tenant scope are derived from that principal server-side —
never accepted from the request body.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import ConfigurationError, OperationFailure

from app import config, db
from app.ingestion import pipeline
from app.ingestion.auth import CorpusPrincipal, require_corpus_admin
from app.schemas import IngestedBy, SourceDocument

log = logging.getLogger("ai-orchestrator.ingestion.router")

router = APIRouter(prefix="/corpus", tags=["corpus-ingestion"])

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_CONTENT_TYPES = {"text/markdown", "text/plain", "text/x-markdown"}
_ALLOWED_EXTENSIONS = {".md", ".txt"}

# Staged uploads carry the full source text — retain it only as long as a CO
# realistically needs to review/approve, then let the TTL index reap it
# (review finding 2). The matching TTL index lives in scripts/create_indexes.py.
_STAGING_TTL = timedelta(days=7)

# Stale-claim recovery window (review finding 1). A doc flipped to "ingesting"
# but never finished (process died between the pipeline insert and the
# status→consumed flip) is re-claimable after this threshold. The deterministic
# chunk_ref upsert in pipeline.py makes the re-run a no-op, not a duplicate.
_STALE_CLAIM = timedelta(minutes=15)

# Metadata format validation (review finding 3). FAR citations:
#   far_part      — 1-2 digits ("4", "43").
#   subpart       — part.section ("43.1"); section is 1-3 digits (e.g. 32.7, 42.15).
#   clause_number — part.section with an optional "-N" suffix ("43.205-1").
_FAR_PART_RE = re.compile(r"^\d{1,2}$")
_SUBPART_RE = re.compile(r"^\d{1,2}\.\d{1,3}$")
_CLAUSE_RE = re.compile(r"^\d{1,2}\.\d{1,3}(?:-\d+)?$")

# Dedicated ingestion-audit collection (review finding 6). Accessed dynamically
# (like corpus_staging) to avoid editing the frozen db.py. Kept SEPARATE from
# RETRIEVAL_AUDIT_COLLECTION, whose contract is RetrievalAuditRecord — corpus
# ingestion records have a different shape and must not pollute the shared
# retrieval audit log. The collection contract is owned here; coordinate with
# the retrieval-path owner before any cross-reads.
_INGESTION_AUDIT_COLLECTION = "ingestion_audit"


class UploadResponse(BaseModel):
    """Returned by /corpus/upload — staged document identity."""
    staged_document_id: str
    title: str
    size_bytes: int
    status: str = "staged_awaiting_ingest"


class IngestRequest(BaseModel):
    """Body for /corpus/ingest — which staged docs to ingest.

    Note (findings 2/3): tenant_id and user_id are intentionally absent. Both
    are derived server-side from the authenticated principal, never trusted
    from the client.
    """
    staged_document_ids: list[str] = Field(min_length=1)
    document_version: str = Field(description="Date of the FAR corpus version")


class IngestResponse(BaseModel):
    """Returned by /corpus/ingest — per-document chunk summary."""
    documents_ingested: int
    chunks_inserted: int
    chunks_discarded: int
    cache_hits: int


def _txn_unsupported(exc: Exception) -> bool:
    """True when the deployment cannot do transactions (standalone mongod).

    A standalone server raises OperationFailure code 20 (IllegalOperation,
    "Transaction numbers are only allowed on a replica set member or mongos");
    older drivers/topologies surface ConfigurationError instead.
    """
    if isinstance(exc, ConfigurationError):
        return True
    return (
        isinstance(exc, OperationFailure)
        and (exc.code == 20 or "Transaction numbers" in str(exc))
    )


def _commit_in_transaction(client, commit):
    """Run commit(session) inside a Mongo transaction where available.

    Crash-safety (review finding 1): the corpus insert and the staging
    status flip commit or roll back together, so a crash mid-commit can no
    longer leave chunks in far_corpus with the staged doc still "ingesting".
    On deployments without transaction support (standalone mongod — Atlas
    Local is a replica set, so dev/prod both support them) we fall back to
    commit(None): the deterministic chunk_ref upsert plus the stale-claim
    recovery window below keep that path safe too (idempotent re-run).
    """
    try:
        with client.start_session() as session:
            return session.with_transaction(commit)
    except (ConfigurationError, OperationFailure) as exc:
        if not _txn_unsupported(exc):
            raise
        log.warning("transactions unsupported on this deployment — falling back: %s", exc)
        return commit(None)


def _writable_tenant(principal: CorpusPrincipal) -> str:
    """Derive the tenant the principal may write (review finding 2).

    Agency-scoped admins write their own agency corpus; an unscoped admin
    (e.g. sys_admin without an agency_id) writes the global FAR corpus. Never
    taken from the request body — this is the §11 isolation control at the
    write path.
    """
    return principal.agency_id or config.GLOBAL_TENANT_ID


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
    principal: CorpusPrincipal = Depends(require_corpus_admin),
) -> UploadResponse:
    """Stage one source document for ingestion (HITL upload step).

    Requires an authenticated CO/sys_admin (finding 1). Validates the file
    type, reads the text, stores it with its SourceDocument metadata plus the
    staging actor in a staging collection. Returns the staged ID the CO passes
    to /corpus/ingest after review.
    """
    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    ct = (file.content_type or "").lower().split(";")[0].strip()

    # AND-semantics (review finding 3): the extension MUST be allowed, and if a
    # content-type was supplied it must also be allowed. The old OR check let
    # arbitrary bytes named ".txt" with a bogus content-type through. A missing
    # or blank content-type is acceptable (many clients omit it on form uploads).
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            415,
            f"Unsupported file extension {ext!r}. Accept one of "
            f"{sorted(_ALLOWED_EXTENSIONS)}.",
        )
    if ct and ct not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            415,
            f"Unsupported content-type {ct!r}. Accept one of "
            f"{sorted(_ALLOWED_CONTENT_TYPES)} (or omit it).",
        )

    # Validate provenance metadata formats (review finding 3) before reading the
    # body, so malformed citations are rejected cheaply.
    title = title.strip()
    if not title:
        raise HTTPException(422, "title must be non-empty.")
    if not _FAR_PART_RE.match(far_part):
        raise HTTPException(422, f"far_part {far_part!r} must be 1-2 digits, e.g. '43'.")
    if subpart and not _SUBPART_RE.match(subpart):
        raise HTTPException(
            422,
            f"subpart {subpart!r} must match part.section, e.g. '43.1' or '32.7'.",
        )
    if clause_number and not _CLAUSE_RE.match(clause_number):
        raise HTTPException(
            422,
            f"clause_number {clause_number!r} must match e.g. '43.103' or '43.205-1'.",
        )

    raw = await file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(422, "File must be UTF-8 encoded text")

    # Reject empty/whitespace-only documents — nothing to chunk (finding 3).
    if not text.strip():
        raise HTTPException(422, "File is empty or whitespace-only — nothing to ingest.")

    staged_id = str(uuid4())
    now = datetime.now(timezone.utc)
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
        "created_at": now,
        "expires_at": now + _STAGING_TTL,
        # Provenance of who staged it (HITL trail), from trusted auth.
        "staged_by": principal.user_id,
        "staged_by_role": principal.role,
    }
    db.get_db()["corpus_staging"].insert_one(staging_doc)
    log.info("staged %r as %s (%d bytes) by %s", title, staged_id, len(raw), principal.user_id)

    return UploadResponse(staged_document_id=staged_id, title=title, size_bytes=len(raw))


@router.post("/ingest", response_model=IngestResponse)
def ingest_staged_documents(
    req: IngestRequest,
    principal: CorpusPrincipal = Depends(require_corpus_admin),
) -> IngestResponse:
    """Ingest CO-approved staged documents into the vector store.

    Requires an authenticated CO/sys_admin (finding 1). Identity and tenant
    scope come from the principal (findings 2/3). Each staged doc is claimed
    atomically (finding 5) so concurrent /ingest calls cannot double-ingest.
    Success and failure both write a run record to the dedicated
    ingestion_audit collection (finding 6, §10 no-silent-failure).
    """
    staging = db.get_db()["corpus_staging"]
    ingestion_audit = db.get_db()[_INGESTION_AUDIT_COLLECTION]
    started_at = datetime.now(timezone.utc)

    tenant_id = _writable_tenant(principal)
    ingested_by = IngestedBy(user_id=principal.user_id, role=principal.role)

    totals: dict[str, int] = {
        "documents_ingested": 0,
        "chunks_inserted": 0,
        "chunks_discarded": 0,
        "cache_hits": 0,
    }
    per_doc_summaries: list[dict] = []
    current_sid: str | None = None

    # Crash-safety (review finding 1): the corpus insert + status flip run in
    # one transaction (_commit_in_transaction). The stale-claim window below is
    # the backstop for the non-transactional fallback and for a crash *before*
    # the commit — a doc left "ingesting" past _STALE_CLAIM is re-claimable,
    # and the deterministic chunk_ref upsert makes the re-run idempotent.
    stale_before = datetime.now(timezone.utc) - _STALE_CLAIM

    # Pre-flight (review finding 3): validate the WHOLE batch before claiming
    # or ingesting anything, so a bad ID aborts with zero side effects instead
    # of mid-batch with earlier docs already in the corpus. The atomic per-doc
    # claim below still guards the (rare) race between this check and the claim.
    requested = req.staged_document_ids
    found = {
        d["staged_document_id"]: d
        for d in staging.find({"staged_document_id": {"$in": requested}})
    }
    missing = [sid for sid in requested if sid not in found]
    if missing:
        raise HTTPException(404, f"staged_document_id(s) not found: {missing}")

    def _claimable(doc: dict) -> bool:
        if doc.get("status") == "staged_awaiting_ingest":
            return True
        claimed_at = doc.get("claimed_at")
        return (
            doc.get("status") == "ingesting"
            and claimed_at is not None
            and claimed_at < stale_before
        )

    unclaimable = [sid for sid in requested if not _claimable(found[sid])]
    if unclaimable:
        raise HTTPException(
            409,
            f"Document(s) not claimable: {unclaimable} — already consumed or "
            "being ingested by another request. No documents from this batch "
            "were ingested.",
        )

    try:
        for sid in req.staged_document_ids:
            current_sid = sid
            # Atomic claim (finding 5): flip → ingesting in one op. Claimable if
            # freshly staged OR a stale "ingesting" leftover from a crashed run.
            # Only the request that wins the claim proceeds; a concurrent caller
            # gets None and is rejected below.
            claimed = staging.find_one_and_update(
                {
                    "staged_document_id": sid,
                    "$or": [
                        {"status": "staged_awaiting_ingest"},
                        {"status": "ingesting", "claimed_at": {"$lt": stale_before}},
                    ],
                },
                {"$set": {
                    "status": "ingesting",
                    "claimed_at": datetime.now(timezone.utc),
                    "claimed_by": principal.user_id,
                }},
                return_document=ReturnDocument.AFTER,
            )
            if claimed is None:
                exists = staging.find_one({"staged_document_id": sid})
                if exists is None:
                    raise HTTPException(404, f"staged_document_id {sid!r} not found")
                raise HTTPException(
                    409,
                    f"Document {sid!r} not claimable (status={exists.get('status')!r}) — "
                    "already consumed or being ingested by another request.",
                )

            source = SourceDocument(
                title=claimed["title"],
                far_part=claimed["far_part"],
                subpart=claimed.get("subpart", ""),
                clause_number=claimed.get("clause_number", ""),
                url=claimed.get("source_url", ""),
            )

            # Slow phase (chunk + Bedrock embed) runs OUTSIDE the transaction —
            # Mongo transactions have a ~60 s lifetime limit.
            prepared = pipeline.prepare_document(
                document_text=claimed["text"],
                source=source,
                document_version=req.document_version,
                ingested_by=ingested_by,
                tenant_id=tenant_id,
            )

            # Commit phase: corpus upsert + consumed flip, atomically where the
            # deployment supports transactions (finding 1). The flip $unsets the
            # full source text (finding 2); metadata/audit fields and expires_at
            # are kept for the TTL reap.
            def _commit(session, sid=sid, prepared=prepared):
                result = (
                    pipeline.insert_records(prepared["records"], session=session)
                    if prepared["records"] else None
                )
                staging.update_one(
                    {"staged_document_id": sid},
                    {
                        "$set": {"status": "consumed", "consumed_at": datetime.now(timezone.utc)},
                        "$unset": {"text": ""},
                    },
                    session=session,
                )
                return result

            result = _commit_in_transaction(db.get_db().client, _commit)
            summary = pipeline.build_summary(prepared, result)

            totals["documents_ingested"] += 1
            totals["chunks_inserted"] += summary.get("chunks_inserted", 0)
            totals["chunks_discarded"] += summary.get("chunks_discarded", 0)
            totals["cache_hits"] += summary.get("cache_hits", 0)
            per_doc_summaries.append(summary)
            current_sid = None
            log.info("ingested staged doc %r — %d chunks", sid, summary.get("chunks_inserted", 0))

    except HTTPException as http_exc:
        # Claim-time 404/409: pre-flight makes this a rare race (doc consumed
        # between the batch check and the claim). The offending doc was never
        # claimed, so nothing to roll back — but earlier docs in the batch ARE
        # ingested, so record the partial batch (§10: no silent failure state).
        if per_doc_summaries:
            partial_record = pipeline.make_ingestion_run_record(
                summary={
                    "status": "aborted_partial",
                    "detail": str(http_exc.detail),
                    "per_document": per_doc_summaries,
                    **totals,
                },
                started_at=started_at,
            )
            partial_record["event"] = "corpus_ingestion_partial"
            partial_record["ingested_by"] = ingested_by.model_dump()
            partial_record["tenant_id"] = tenant_id
            ingestion_audit.insert_one(partial_record)
        raise
    except Exception as exc:  # pipeline / embedding failure (§10)
        log.exception("ingest failed on %r", current_sid)
        if current_sid is not None:
            staging.update_one(
                {"staged_document_id": current_sid},
                {"$set": {
                    "status": "failed",
                    "failed_at": datetime.now(timezone.utc),
                    "error": str(exc)[:500],
                }},
            )
        fail_record = pipeline.make_ingestion_run_record(
            summary={
                "status": "failed",
                "failed_document_id": current_sid,
                "error": str(exc)[:500],
                "per_document": per_doc_summaries,
                **totals,
            },
            started_at=started_at,
        )
        fail_record["event"] = "corpus_ingestion_failed"
        fail_record["ingested_by"] = ingested_by.model_dump()
        fail_record["tenant_id"] = tenant_id
        ingestion_audit.insert_one(fail_record)
        raise HTTPException(
            500,
            f"Ingestion failed on {current_sid!r}; that document was marked failed and "
            "left out of the corpus. Earlier documents in the batch were ingested. "
            "See the ingestion_audit collection.",
        )

    run_record = pipeline.make_ingestion_run_record(
        summary={"status": "succeeded", "per_document": per_doc_summaries, **totals},
        started_at=started_at,
    )
    run_record["ingested_by"] = ingested_by.model_dump()
    run_record["tenant_id"] = tenant_id
    ingestion_audit.insert_one(run_record)

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

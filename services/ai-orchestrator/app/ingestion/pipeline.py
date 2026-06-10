"""
pipeline.py — corpus ingestion pipeline: chunk → embed → insert (ADR-0005).

Owner: Person A (write path).

Orchestrates one document's journey into the far_corpus vector collection:

    raw document text
        → chunker.chunk_document()          (§13 section-boundary chunks)
        → embedder.build_cached_embedder()  (§3 Titan V2, §14 cache)
        → ChunkDocument provenance assembly (§12 full lineage metadata)
        → far_corpus idempotent bulk upsert (deterministic chunk_ref)

The slow phase (chunk + embed) and the write phase are split into
prepare_document() / insert_records() so a caller can run the Bedrock calls
outside a MongoDB transaction and keep the transaction window tight (the
router wraps insert_records + its staging status flip in one transaction).
ingest_document() composes both for callers that don't need the split.

Ingestion is OFFLINE/ASYNC relative to CO requests — never runs inside a
retrieval request (§8 anti-pattern: synchronous ingestion). Triggered by
the /corpus/ingest endpoint or the seed script.

HITL gate (§15): a CO must approve a document batch before it is ingested.
The router enforces the approval flow; this module assumes the caller is
already authorized.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from pymongo import UpdateOne

from app import config, db
from app.ingestion import chunker, embedder
from app.schemas import ChunkDocument, IngestedBy, SourceDocument

log = logging.getLogger("ai-orchestrator.ingestion.pipeline")

# --- seed frontmatter helpers ---

_FRONTMATTER_RE = re.compile(r"^---[ \t]*\n(.*?)\n---[ \t]*\n", re.DOTALL)
_YAML_KV_RE = re.compile(r'^(\w+):\s*["\']?([^"\'\n]+?)["\']?\s*$', re.MULTILINE)
# A clause/section identifier inside a `cite` value: a run that starts with a
# digit and continues with digits, dots, or hyphens.
_CITE_TOKEN_RE = re.compile(r"\d[\d.\-]*")


def _clause_from_cite(cite: str) -> str:
    """Extract the clause/section identifier from a frontmatter ``cite`` value.

    "FAR 43.103" -> "43.103", "DFARS 252.232-7003" -> "252.232-7003",
    "FAR Part 42" -> "42", "5 CFR 1315" -> "1315". Returns "" when the cite
    carries no numeric token. The last token wins so a leading title number
    ("5 CFR ...") doesn't shadow the real section.
    """
    tokens = _CITE_TOKEN_RE.findall(cite or "")
    return tokens[-1].rstrip(".-") if tokens else ""


def _subpart_from_clause(far_part: str, clause: str) -> str:
    """Derive a FAR subpart from a "part.section" clause ("43.103" -> "43.1").

    Only fires for FAR-style ``NN.N...`` clauses; DFARS ("252.232-7003"),
    CFR ("1315"), and bare parts ("42") have no subpart in this scheme.
    """
    m = re.match(r"^(\d{1,2})\.(\d)", clause)
    return f"{m.group(1)}.{m.group(2)}" if m else ""


def _source_from_file(path: Path, content: str) -> SourceDocument:
    """Derive SourceDocument from YAML frontmatter or filename pattern.

    Seed frontmatter uses ``cite:`` (e.g. "DFARS 252.232-7003") and ``source:``
    (the canonical URL); an explicit ``clause_number:`` / ``url:`` key still
    wins if present. Filename fallback handles the far-<part>-<section>-*.md
    convention, but only when the section token is numeric (so far-42-overview
    does not yield clause "42.overview").
    """
    meta: dict[str, str] = {}
    fm_match = _FRONTMATTER_RE.match(content)
    if fm_match:
        for m in _YAML_KV_RE.finditer(fm_match.group(1)):
            meta[m.group(1)] = m.group(2).strip()

    cite_clause = _clause_from_cite(meta.get("cite", ""))
    src_url = meta.get("url") or meta.get("source", "")

    # Filename fallback: far-<part>-<section>-<label>.md
    stem = path.stem
    parts = stem.split("-")
    if len(parts) >= 3 and parts[0] == "far" and parts[2].isdigit():
        fb_part = parts[1]
        fb_clause = f"{fb_part}.{parts[2]}"
        fb_url = f"https://www.acquisition.gov/far/{fb_clause}"
    elif len(parts) >= 2 and parts[0] == "far" and parts[1].isdigit():
        fb_part = parts[1]
        fb_clause = ""
        fb_url = f"https://www.acquisition.gov/far/part-{fb_part}"
    else:
        fb_part = fb_clause = fb_url = ""
    fb_title = stem.replace("-", " ").title()

    far_part = meta.get("far_part", fb_part)
    clause_number = meta.get("clause_number") or cite_clause or fb_clause
    subpart = meta.get("subpart") or _subpart_from_clause(far_part, clause_number)

    return SourceDocument(
        title=meta.get("title", fb_title or stem),
        far_part=far_part,
        subpart=subpart,
        clause_number=clause_number,
        url=src_url or fb_url,
    )


# --- pipeline ---

def prepare_document(
    document_text: str,
    source: SourceDocument,
    document_version: str,
    ingested_by: IngestedBy,
    tenant_id: str = config.GLOBAL_TENANT_ID,
) -> dict:
    """Run the slow phase: chunk + embed + assemble far_corpus records.

    No database write happens here — the caller passes the returned records
    to insert_records(), optionally inside a MongoDB transaction. Keeping
    the Bedrock round-trips out of the transaction window matters: Mongo
    transactions have a ~60 s lifetime limit, which a large document's
    embedding batch could blow through.

    Steps:
      1. Chunk via chunker.chunk_document() — §13 rules applied there.
      2. Embed all chunk texts in one batch through the cached embedder
         (cache hits skip Bedrock entirely, §14).
      3. Assemble full ChunkDocument provenance per chunk (§12 field set)
         plus the deterministic chunk_ref upsert key.

    Returns:
        {"records": list[dict], "chunks_discarded": int, "cache_hits": int,
         "source_title": str}. records is empty when every fragment was
        discarded (caller skips the insert).

    Raises:
        Embedding failures propagate — caller queues a retry and writes an
        audit record (§10: no proceeding to draft, no silent failure).
    """
    # Step 1: chunk (discards fragments < MIN_CHUNK_CHARS internally).
    chunk_result = chunker.chunk_document(document_text, source)
    chunks = chunk_result.chunks
    chunks_discarded = chunk_result.discarded_count

    if not chunks:
        log.warning("prepare_document: no chunks produced for %r — nothing to insert", source.title)
        return {
            "records": [],
            "chunks_discarded": chunks_discarded,
            "cache_hits": 0,
            "source_title": source.title,
        }

    # Step 2: embed all chunk texts in one batch.
    # Raises on Bedrock failure — §10: no silent failure, caller retries.
    emb = embedder.build_cached_embedder()
    texts = [c["chunk_text"] for c in chunks]
    vectors = emb.embed_documents(texts)

    # Step 3: assemble ChunkDocument per chunk.
    # Pydantic validation here is the §12 contract gate with Person B —
    # an invalid field set raises before any data reaches the database.
    chunk_docs: list[ChunkDocument] = []
    for chunk_dict, vector in zip(chunks, vectors):
        chunk_source = SourceDocument(
            title=source.title,
            far_part=chunk_dict["far_part"],
            subpart=chunk_dict["subpart"],
            clause_number=chunk_dict["clause_number"],
            url=source.url,
        )
        chunk_docs.append(ChunkDocument(
            chunk_text=chunk_dict["chunk_text"],
            chunk_sequence=chunk_dict["chunk_sequence"],
            source_document=chunk_source,
            document_version=document_version,
            ingested_by=ingested_by,
            embedding_model=config.EMBEDDING_MODEL_ID,
            embedding_dimensions=config.EMBEDDING_DIMENSIONS,
            embedding_model_version=config.EMBEDDING_MODEL_VERSION,
            tenant_id=tenant_id,
            embedding=vector,
        ))

    # Deterministic chunk_ref upsert key so that re-ingest / crash-retry /
    # concurrent ingest is a no-op rather than duplicating chunks.
    #
    # The key includes doc_digest — a SHA-256 of the source text (review
    # finding 3). source_url is optional (the /upload router defaults it to
    # ""), so without the digest two DIFFERENT uploads sharing title + tenant +
    # version would fall back to the same title component and collide on
    # chunk_ref per sequence, silently clobbering one document with the other.
    # Binding an immutable per-document content identity removes the collision
    # while preserving idempotency: re-ingesting byte-identical text yields the
    # same digest → same chunk_ref → the upsert stays a no-op.
    doc_digest = hashlib.sha256(document_text.encode("utf-8")).hexdigest()
    records = [doc.model_dump() for doc in chunk_docs]
    for record in records:
        canonical = "\x1f".join([
            tenant_id,
            source.url or source.title,
            doc_digest,
            document_version,
            str(record["chunk_sequence"]),
        ])
        record["chunk_ref"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return {
        "records": records,
        "chunks_discarded": chunks_discarded,
        "cache_hits": emb.last_hits,
        "source_title": source.title,
    }


def insert_records(records: list[dict], session=None):
    """Step 4: idempotent upsert of prepared records into far_corpus.

    Keyed on the deterministic chunk_ref so reruns converge on the same
    documents. Pass a pymongo ClientSession to make the write part of a
    caller-managed transaction (the router pairs it with the staging
    status flip); without one, each UpdateOne is independently atomic
    and the unordered bulk_write is NOT atomic as a whole.

    chunk_id is written via $setOnInsert, NOT $set (review finding 2): the
    upsert is keyed on chunk_ref, so the chunk_id is minted once on first
    insert and never overwritten. A re-ingest / crash-retry / stale-claim
    re-run updates the chunk's content/embedding ($set) but keeps the
    original chunk_id, so chunk_ids already cited in prior
    RetrievalAuditRecords still resolve to the corpus chunk.

    Returns:
        pymongo BulkWriteResult (upserted_count / modified_count).
    """
    corpus = db.get_far_corpus()
    ops = []
    for r in records:
        on_insert = {"chunk_id": r["chunk_id"]}
        to_set = {k: v for k, v in r.items() if k != "chunk_id"}
        ops.append(UpdateOne(
            {"chunk_ref": r["chunk_ref"]},
            {"$set": to_set, "$setOnInsert": on_insert},
            upsert=True,
        ))
    return corpus.bulk_write(ops, ordered=False, session=session)


def build_summary(prepared: dict, result) -> dict:
    """Build the per-document ingest summary from a prepare + insert pair.

    result is the BulkWriteResult from insert_records(), or None when no
    records were inserted (all fragments discarded).
    """
    return {
        "chunks_inserted": result.upserted_count if result is not None else 0,
        "chunks_updated": result.modified_count if result is not None else 0,
        "chunks_discarded": prepared["chunks_discarded"],
        "cache_hits": prepared["cache_hits"],
        "source_title": prepared["source_title"],
    }


def ingest_document(
    document_text: str,
    source: SourceDocument,
    document_version: str,
    ingested_by: IngestedBy,
    tenant_id: str = config.GLOBAL_TENANT_ID,
    session=None,
) -> dict:
    """Ingest one source document end-to-end into far_corpus.

    Convenience composition of prepare_document() + insert_records() for
    callers that don't need the transaction split (seed script, tests).

    Args:
        document_text: Raw text of the source document.
        source: Document lineage (title, far_part, subpart, clause, url).
        document_version: Date string of the FAR corpus version ingested.
        ingested_by: Identity that triggered ingestion (HITL trail).
        tenant_id: "far_corpus_global" or an <agency_id> (§11).
        session: Optional pymongo ClientSession for the insert phase.

    Returns:
        Summary dict: {"chunks_inserted": int, "chunks_discarded": int,
        "cache_hits": int, "source_title": str}.

    Raises:
        Embedding failures propagate — caller queues a retry and writes an
        audit record (§10: no proceeding to draft, no silent failure).
    """
    prepared = prepare_document(document_text, source, document_version, ingested_by, tenant_id)
    if not prepared["records"]:
        return build_summary(prepared, None)

    result = insert_records(prepared["records"], session=session)
    log.info(
        "ingest_document: %r — inserted %d / updated %d chunks (cache hits %d/%d)",
        source.title,
        result.upserted_count,
        result.modified_count,
        prepared["cache_hits"],
        len(prepared["records"]),
    )
    return build_summary(prepared, result)


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
    seed_path = Path(seed_dir)
    empty = {"files_ingested": 0, "chunks_inserted": 0, "chunks_updated": 0,
             "chunks_discarded": 0, "cache_hits": 0}
    if not seed_path.is_dir():
        log.warning("ingest_seed_corpus: seed directory %r not found — skipping", seed_dir)
        return dict(empty)

    md_files = sorted(p for p in seed_path.glob("*.md") if p.name.lower() != "readme.md")
    if not md_files:
        log.warning("ingest_seed_corpus: no .md files (excluding README.md) in %r", seed_dir)
        return dict(empty)

    system_user = IngestedBy(user_id="system:seed-ingest", role="system")
    total: dict[str, int] = dict(empty)

    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8")
        source = _source_from_file(md_file, content)
        # Strip frontmatter before ingesting so it does not land in chunks.
        body = _FRONTMATTER_RE.sub("", content, count=1)

        try:
            summary = ingest_document(
                document_text=body,
                source=source,
                document_version="seed",
                ingested_by=system_user,
                tenant_id=config.GLOBAL_TENANT_ID,
            )
            total["files_ingested"] += 1
            total["chunks_inserted"] += summary["chunks_inserted"]
            total["chunks_updated"] += summary.get("chunks_updated", 0)
            total["chunks_discarded"] += summary.get("chunks_discarded", 0)
            total["cache_hits"] += summary.get("cache_hits", 0)
            log.info(
                "seeded %r — %d inserted / %d updated chunks",
                md_file.name,
                summary["chunks_inserted"],
                summary.get("chunks_updated", 0),
            )
        except Exception:
            log.exception("ingest_seed_corpus: failed on %r — continuing", md_file.name)

    return total


def make_ingestion_run_record(summary: dict, started_at: datetime) -> dict:
    """Build a structured ingestion audit entry for the audit collection.

    Ingestion is a write-path event but still auditable (§12 "who done it"
    trail — ingested_by, counts, duration). Keeps DCAA lineage complete
    even before Person B's retrieval audit logger lands.
    """
    finished_at = datetime.now(timezone.utc)
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    return {
        "event": "corpus_ingestion",
        "summary": summary,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
    }

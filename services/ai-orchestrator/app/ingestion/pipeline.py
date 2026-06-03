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
import re
from datetime import datetime, timezone
from pathlib import Path

from app import config, db
from app.ingestion import chunker, embedder
from app.schemas import ChunkDocument, IngestedBy, SourceDocument

log = logging.getLogger("ai-orchestrator.ingestion.pipeline")

# --- seed frontmatter helpers ---

_FRONTMATTER_RE = re.compile(r"^---[ \t]*\n(.*?)\n---[ \t]*\n", re.DOTALL)
_YAML_KV_RE = re.compile(r'^(\w+):\s*["\']?([^"\'\n]+?)["\']?\s*$', re.MULTILINE)


def _source_from_file(path: Path, content: str) -> SourceDocument:
    """Derive SourceDocument from YAML frontmatter or filename pattern.

    Frontmatter takes precedence; filename fallback handles
    far-<part>-<section>-*.md naming convention.
    """
    meta: dict[str, str] = {}
    fm_match = _FRONTMATTER_RE.match(content)
    if fm_match:
        for m in _YAML_KV_RE.finditer(fm_match.group(1)):
            meta[m.group(1)] = m.group(2).strip()

    # Filename fallback: far-<part>-<section>-<label>.md
    stem = path.stem
    parts = stem.split("-")
    if len(parts) >= 3 and parts[0] == "far":
        fb_part = parts[1]
        fb_section = parts[2]
        fb_clause = f"{fb_part}.{fb_section}"
        fb_subpart = f"{fb_part}.{fb_section[0]}" if fb_section else fb_part
        fb_title = stem.replace("-", " ").title()
        fb_url = f"https://www.acquisition.gov/far/part-{fb_part}"
    else:
        fb_part = fb_section = fb_clause = fb_subpart = fb_title = fb_url = ""

    return SourceDocument(
        title=meta.get("title", fb_title or stem),
        far_part=meta.get("far_part", fb_part),
        subpart=meta.get("subpart", fb_subpart),
        clause_number=meta.get("clause_number", fb_clause),
        url=meta.get("url", fb_url),
    )


# --- pipeline ---

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
    # Step 1: chunk (discards fragments < MIN_CHUNK_CHARS internally).
    chunks = chunker.chunk_document(document_text, source)

    if not chunks:
        log.warning("ingest_document: no chunks produced for %r — skipping insert", source.title)
        return {
            "chunks_inserted": 0,
            "chunks_discarded": 0,
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

    # Step 4: insert all validated docs atomically (§10: no partial inserts).
    records = [doc.model_dump() for doc in chunk_docs]
    db.get_far_corpus().insert_many(records)

    log.info(
        "ingest_document: %r — inserted %d chunks (cache hits %d/%d)",
        source.title,
        len(records),
        emb._last_hits,
        len(texts),
    )

    return {
        "chunks_inserted": len(records),
        "chunks_discarded": 0,
        "cache_hits": emb._last_hits,
        "source_title": source.title,
    }


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
    if not seed_path.is_dir():
        log.warning("ingest_seed_corpus: seed directory %r not found — skipping", seed_dir)
        return {"files_ingested": 0, "chunks_inserted": 0, "chunks_discarded": 0, "cache_hits": 0}

    md_files = sorted(p for p in seed_path.glob("*.md") if p.name.lower() != "readme.md")
    if not md_files:
        log.warning("ingest_seed_corpus: no .md files (excluding README.md) in %r", seed_dir)
        return {"files_ingested": 0, "chunks_inserted": 0, "chunks_discarded": 0, "cache_hits": 0}

    system_user = IngestedBy(user_id="system:seed-ingest")
    total: dict[str, int] = {"files_ingested": 0, "chunks_inserted": 0, "chunks_discarded": 0, "cache_hits": 0}

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
            total["chunks_discarded"] += summary.get("chunks_discarded", 0)
            total["cache_hits"] += summary.get("cache_hits", 0)
            log.info("seeded %r — %d chunks", md_file.name, summary["chunks_inserted"])
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

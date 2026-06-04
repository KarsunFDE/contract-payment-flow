"""
create_indexes.py — one-time Atlas Local search index setup (ADR-0005 §2/§3,
Migration Step 5).

Owner: Person A (write path).

Creates both search indexes on the far_corpus collection:

  far_vector_idx — $vectorSearch index
      type: knnVector on the `embedding` field
      dimensions: 512, similarity: cosine
      filter fields: tenant_id, source_document.far_part,
          source_document.clause_number  (far_part/clause_number are nested
          under source_document on the stored doc — see SourceDocument in
          app/schemas.py; tenant_id is genuinely top-level)
          (chunk_text deliberately excluded — see build_vector_index_model;
           it stays indexed for sparse retrieval in far_text_idx)
      dynamic mapping: DISABLED — only declared fields indexed (§3)

  far_text_idx — Atlas Search BM25 index
      on the `chunk_text` field (sparse retrieval for hybrid search)

Run from the service root with the compose stack up:

    python -m scripts.create_indexes

Idempotent: re-running against existing indexes is a no-op (checks by
name first). Exits non-zero if either index fails to reach ACTIVE/READY —
the migration plan requires both verified before go-live (Step 5.3).
"""
from __future__ import annotations

import logging
import sys
import time

from pymongo.operations import SearchIndexModel

from app import config, db

logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")
log = logging.getLogger("create-indexes")

# Atlas Local builds indexes asynchronously — these control the readiness poll.
POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 300

# Terminal "good" statuses. Atlas Local and different search index types can report
# either READY or ACTIVE for a usable index — keying on READY alone made the poll
# hang to the full timeout on backends that only ever report ACTIVE.
READY_STATUSES = frozenset({"READY", "ACTIVE"})
# Terminal "bad" statuses that should abort immediately rather than wait out the timeout.
FAILED_STATUSES = frozenset({"FAILED", "DOES_NOT_EXIST"})


def build_vector_index_model() -> SearchIndexModel:
    """Define far_vector_idx per ADR-0005 §3 vector index specification."""
    return SearchIndexModel(
        definition={
            "fields": [
                # Primary vector field — cosine similarity on 512-dim Titan V2 embeddings (§3).
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": config.EMBEDDING_DIMENSIONS,
                    "similarity": "cosine",
                },
                # Filter fields allow $vectorSearch to pre-filter before ANN scoring.
                # tenant_id MUST be here — Person B's §11 tenant pre-filter runs inside
                # $vectorSearch, not at the application layer (security control, §6).
                {"type": "filter", "path": "tenant_id"},
                # far_part / clause_number live NESTED under source_document on the
                # stored ChunkDocument (app/schemas.py SourceDocument; assembled in
                # app/ingestion/pipeline.py). A top-level path here would pre-filter
                # against a field that does not exist, matching zero docs — so the
                # filter paths must use the dotted source_document.* shape. tenant_id
                # is genuinely top-level (ChunkDocument.tenant_id) — left as-is.
                {"type": "filter", "path": "source_document.far_part"},
                {"type": "filter", "path": "source_document.clause_number"},
                # NOTE: chunk_text intentionally NOT a vector filter field — deliberate
                # deviation from ADR-0005 §3 (which lists it among the vector index's
                # "additional indexed fields"). No ADR retrieval pattern ever filters
                # $vectorSearch on body text, and adversarial review finding 12 already
                # flags this for the ADR's next revision. chunk_text remains fully
                # indexed for BM25/sparse retrieval in far_text_idx (build_text_index_model).
                # CAUTION: a dev far_vector_idx created with the OLD filter set still
                # carries chunk_text — the idempotency check skips by name, so that index
                # must be dropped + recreated to shed the field.
            ]
        },
        name=config.FAR_VECTOR_INDEX,
        type="vectorSearch",
    )


def build_text_index_model() -> SearchIndexModel:
    """Define far_text_idx — BM25 Atlas Search index for hybrid sparse retrieval (§4)."""
    return SearchIndexModel(
        definition={
            "mappings": {
                # dynamic=False — index only declared fields; no accidental PII indexing (§6).
                "dynamic": False,
                "fields": {
                    # "string" type triggers full-text BM25 analysis on chunk text.
                    "chunk_text": {"type": "string"},
                    # "token" type = exact-match; lets BM25 $search also pre-filter by
                    # tenant so sparse retrieval enforces the same §11 isolation as dense.
                    "tenant_id": {"type": "token"},
                },
            }
        },
        name=config.FAR_TEXT_INDEX,
        type="search",
    )


def existing_search_index_names(collection) -> set[str]:
    """Return names of search indexes already on the collection (idempotency check)."""
    return {idx["name"] for idx in collection.list_search_indexes()}


def wait_until_indexes_ready(collection, index_names: list[str]) -> bool:
    """Poll list_search_indexes until all named indexes are queryable.

    Migration Step 5.3 requires both indexes usable before go-live. An index is
    treated as ready when it reaches a known-good terminal status (READY/ACTIVE)
    OR reports queryable==true (the field Atlas exposes in list_search_indexes to
    say the index can serve queries regardless of its textual status label).
    Returns False on timeout or a terminal-bad status (FAILED/DOES_NOT_EXIST) —
    main() converts that to exit 1.
    """
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    pending = set(index_names)  # shrinks as each index becomes queryable

    while pending and time.monotonic() < deadline:
        for idx in collection.list_search_indexes():
            name = idx.get("name", "")
            if name not in pending:
                continue  # skip indexes we're not waiting on

            status = idx.get("status", "UNKNOWN")
            # 'queryable' is an Atlas-provided bool; absent on backends that don't
            # report it, so only treat an explicit True as ready (don't assume).
            queryable = idx.get("queryable")
            log.info("  %-30s → %s (queryable=%s)", name, status, queryable)

            if status in READY_STATUSES or queryable is True:
                pending.discard(name)
            elif status in FAILED_STATUSES:
                # Terminal-bad: non-recoverable without dropping and recreating the index.
                log.error("index %r entered %s state — aborting", name, status)
                return False

        if pending:
            log.info(
                "still building: %s — next check in %ds",
                sorted(pending),
                POLL_INTERVAL_SECONDS,
            )
            time.sleep(POLL_INTERVAL_SECONDS)

    if pending:
        log.error(
            "timed out after %ds; indexes never became queryable: %s",
            POLL_TIMEOUT_SECONDS,
            sorted(pending),
        )
        return False

    return True


def main() -> int:
    """Create both indexes if absent, wait for READY, exit 0 on success / 1 on failure."""
    collection = db.get_far_corpus()

    # createSearchIndexes fails with NamespaceNotFound on a brand-new database —
    # ensure the collection exists first (no-op if it already does).
    database = db.get_db()
    if collection.name not in database.list_collection_names():
        log.info("collection %r not found — creating it", collection.name)
        database.create_collection(collection.name)

    # Unique index on the deterministic chunk_ref (sha256) so duplicate upserts are
    # rejected at the DB layer. create_index is idempotent — same name/spec is a no-op.
    collection.create_index(
        [("chunk_ref", 1)],
        unique=True,
        name="chunk_ref_unique",
        partialFilterExpression={"chunk_ref": {"$exists": True}},
    )
    log.info("ensured unique index %r on chunk_ref", "chunk_ref_unique")

    # TTL index on corpus_staging.expires_at (finding 2): the router stamps
    # expires_at = created_at + 7d; expireAfterSeconds=0 reaps each doc at its
    # own expires_at so staged source text is not retained forever. Idempotent.
    staging = database["corpus_staging"]
    staging.create_index([("expires_at", 1)], name="staging_ttl", expireAfterSeconds=0)
    log.info("ensured TTL index %r on %s.expires_at", "staging_ttl", staging.name)

    # Check what already exists so re-runs are safe to call repeatedly.
    existing = existing_search_index_names(collection)
    log.info("existing search indexes: %s", sorted(existing))

    # Pair each index name with its builder so we skip only the ones already present.
    candidates = [
        (config.FAR_VECTOR_INDEX, build_vector_index_model),
        (config.FAR_TEXT_INDEX, build_text_index_model),
    ]

    to_create = []
    for name, builder in candidates:
        if name in existing:
            log.info("index %r already exists — skipping", name)
        else:
            log.info("index %r not found — queuing for creation", name)
            to_create.append(builder())

    if to_create:
        # create_search_indexes accepts a list; Atlas Local starts building asynchronously.
        log.info("creating %d index(es)...", len(to_create))
        collection.create_search_indexes(to_create)
    else:
        log.info("all indexes already present — nothing to create")

    # Always wait on both indexes regardless of whether we created them just now,
    # so a partial-READY state from a prior run is also caught.
    all_names = [config.FAR_VECTOR_INDEX, config.FAR_TEXT_INDEX]
    log.info("waiting for indexes to reach READY (timeout %ds)...", POLL_TIMEOUT_SECONDS)

    if not wait_until_indexes_ready(collection, all_names):
        return 1  # non-zero exit blocks the migration (Step 5.3)

    log.info("OK — both indexes READY. Migration Step 5.3 satisfied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
create_indexes.py — one-time Atlas Local search index setup (ADR-0005 §2/§3,
Migration Step 5).

Owner: Person A (write path).

Creates both search indexes on the far_corpus collection:

  far_vector_idx — $vectorSearch index
      type: knnVector on the `embedding` field
      dimensions: 512, similarity: cosine
      filter fields: chunk_text, far_part, clause_number, tenant_id
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
                {"type": "filter", "path": "far_part"},
                {"type": "filter", "path": "clause_number"},
                {"type": "filter", "path": "chunk_text"},
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
    """Poll list_search_indexes until all named indexes report READY.

    Migration Step 5.3 requires both indexes ACTIVE before go-live.
    Returns False on timeout or FAILED status — main() converts that to exit 1.
    """
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    pending = set(index_names)  # shrinks as each index reaches READY

    while pending and time.monotonic() < deadline:
        for idx in collection.list_search_indexes():
            name = idx.get("name", "")
            if name not in pending:
                continue  # skip indexes we're not waiting on

            status = idx.get("status", "UNKNOWN")
            log.info("  %-30s → %s", name, status)

            if status == "READY":
                pending.discard(name)
            elif status == "FAILED":
                # FAILED is non-recoverable without dropping and recreating the index.
                log.error("index %r entered FAILED state — aborting", name)
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
            "timed out after %ds; indexes never reached READY: %s",
            POLL_TIMEOUT_SECONDS,
            sorted(pending),
        )
        return False

    return True


def main() -> int:
    """Create both indexes if absent, wait for READY, exit 0 on success / 1 on failure."""
    collection = db.get_far_corpus()

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

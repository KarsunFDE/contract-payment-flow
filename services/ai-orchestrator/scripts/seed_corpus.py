"""seed_corpus.py — one-shot CLI to ingest the seed FAR/DFARS/CFR stubs.

Populates the far_corpus vector collection from data/seed/far-part-42-43-32/
under tenant_id="far_corpus_global", so Person B's retrieval read path has
real chunks (with real Titan V2 512-d embeddings) to query.

Re-running is an idempotent upsert keyed on the deterministic chunk_ref, so
identical content converges on the same documents. But changing the chunk_ref
formula (or the source text) re-keys chunks, leaving the OLD chunks behind —
far_corpus has no TTL to reap them. Pass --drop for a clean reload that clears
those stragglers first.

Run (from services/ai-orchestrator/, after `scripts.create_indexes`):

    # host shell needs the Bedrock token + an auth'd MONGO_URL:
    #   export AWS_BEARER_TOKEN_BEDROCK=...           (do NOT cat .env)
    #   export MONGO_URL='mongodb://app:app_dev_password@localhost:27017/?directConnection=true'
    python -m scripts.seed_corpus                 # default seed dir (repo-root data/seed)
    python -m scripts.seed_corpus <seed_dir>      # explicit seed-dir override
    python -m scripts.seed_corpus --drop          # clear far_corpus, then reseed
    python -m scripts.seed_corpus --drop <seed_dir>

--drop is destructive: it deletes EVERY chunk in far_corpus (all tenants), not
just the seed set. Off by default. It clears documents only (delete_many), so
the vector/text indexes survive — no create_indexes rerun needed.

Exits non-zero if no files or no chunks were ingested (so it can gate a
verification step), per ADR-0005 §10 (no silent failure).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from app import config, db
from app.ingestion import pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("ai-orchestrator.scripts.seed_corpus")

# Repo root from this file: scripts/ -> ai-orchestrator/ -> services/ -> root.
# Inside the container the layout is /app/scripts/ (too shallow for parents[3]);
# fall back to the CWD so `docker cp data/seed ...:/app/data/` + a run from /app
# resolves the same relative path. An explicit CLI seed_dir always wins.
try:
    _REPO_ROOT = Path(__file__).resolve().parents[3]
except IndexError:
    _REPO_ROOT = Path.cwd()
_DEFAULT_SEED_DIR = _REPO_ROOT / "data" / "seed" / "far-part-42-43-32"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    # --drop is opt-in (destructive). Strip it from argv; the lone remaining
    # positional, if any, is the seed-dir override.
    drop = False
    positionals = []
    for arg in argv:
        if arg in ("--drop", "-d"):
            drop = True
        else:
            positionals.append(arg)
    seed_dir = Path(positionals[0]) if positionals else _DEFAULT_SEED_DIR

    if not seed_dir.is_dir():
        log.error("seed directory not found: %s", seed_dir)
        return 1

    if drop:
        # Clean reload: clear stale chunks (e.g. left by a chunk_ref formula
        # change) so the reseed isn't shadowed by orphaned documents. Clears the
        # WHOLE collection — all tenants, not just the seed set. delete_many
        # (not drop) keeps the vector/text indexes from scripts.create_indexes
        # intact, so no index rebuild is needed afterward.
        corpus = db.get_far_corpus()
        deleted = corpus.delete_many({}).deleted_count
        log.warning("--drop: cleared far_corpus (%d existing chunks removed)", deleted)

    log.info("ingesting seed corpus from %s (tenant=%s)", seed_dir, config.GLOBAL_TENANT_ID)
    summary = pipeline.ingest_seed_corpus(str(seed_dir))
    log.info("seed ingest summary: %s", summary)

    if summary.get("files_ingested", 0) == 0:
        log.error("no files ingested — check the seed directory contents")
        return 1
    # Success = chunks were WRITTEN, whether newly inserted or updated in place.
    # An idempotent re-seed legitimately inserts 0 and updates N (deterministic
    # chunk_ref upsert) — gating on inserted alone would falsely fail it.
    chunks_written = summary.get("chunks_inserted", 0) + summary.get("chunks_updated", 0)
    if chunks_written == 0:
        log.error(
            "0 chunks written (inserted + updated) — likely an embedding failure "
            "(Bedrock token unset/expired) or all fragments discarded"
        )
        return 1

    print(
        f"seeded {summary['files_ingested']} files · "
        f"{summary['chunks_inserted']} inserted · "
        f"{summary.get('chunks_updated', 0)} updated · "
        f"{summary.get('chunks_discarded', 0)} discarded · "
        f"{summary.get('cache_hits', 0)} cache hits"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

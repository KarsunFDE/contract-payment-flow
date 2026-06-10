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
    python -m scripts.seed_corpus --drop          # clear the SEED set, then reseed
    python -m scripts.seed_corpus --drop <seed_dir>

--drop is SCOPED (security review finding): it deletes only the seed set —
chunks under tenant_id=far_corpus_global ingested by "system:seed-ingest" — so
it can never wipe another tenant's corpus. The vector/text indexes survive
(delete_many, not drop) so no create_indexes rerun is needed.

--drop-all-tenants performs the old cross-tenant wipe of the WHOLE collection.
It is irreversible cross-tenant data loss, so it is gated twice: refused unless
APP_ENV is a dev environment, AND requires a typed confirmation phrase
(interactive prompt, or SEED_DROP_ALL_CONFIRM env for non-interactive runs).

Exits non-zero if no files or no chunks were ingested (so it can gate a
verification step), per ADR-0005 §10 (no silent failure).
"""
from __future__ import annotations

import logging
import os
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

# The seed pipeline stamps every chunk with this identity (see
# pipeline.ingest_seed_corpus). --drop is scoped to exactly this set so it can
# never delete another tenant's chunks (security review finding).
_SEED_USER_ID = "system:seed-ingest"
# Environments where the cross-tenant wipe is outright refused.
_PROD_ENVS = frozenset({"prod", "production", "staging"})
# Typed confirmation phrase for --drop-all-tenants.
_DROP_ALL_PHRASE = "drop all tenants"


def _seed_delete_filter() -> dict:
    """Mongo filter matching ONLY the seed set: the global tenant's chunks
    ingested by the system seed user. Scopes --drop so a clean reload never
    touches another tenant (security review finding)."""
    return {
        "tenant_id": config.GLOBAL_TENANT_ID,
        "ingested_by.user_id": _SEED_USER_ID,
    }


def _confirm_drop_all() -> bool:
    """Gate the irreversible cross-tenant wipe behind a dev-only env check AND a
    typed confirmation (security review finding). Returns True only when both
    pass; logs the reason and returns False otherwise.
    """
    app_env = os.environ.get("APP_ENV", "dev").strip().lower()
    if app_env in _PROD_ENVS:
        log.error(
            "--drop-all-tenants REFUSED: APP_ENV=%r is not a dev environment. "
            "Cross-tenant wipe is dev-only.",
            app_env,
        )
        return False

    # Non-interactive opt-in via env (CI/docker exec without a TTY); otherwise
    # prompt interactively. Either way the phrase must match exactly.
    typed = os.environ.get("SEED_DROP_ALL_CONFIRM")
    if typed is None:
        if not sys.stdin.isatty():
            log.error(
                "--drop-all-tenants needs confirmation but stdin is not a TTY. "
                "Set SEED_DROP_ALL_CONFIRM=%r to confirm a non-interactive wipe.",
                _DROP_ALL_PHRASE,
            )
            return False
        typed = input(
            f"This DELETES EVERY tenant's chunks in far_corpus and is "
            f"IRREVERSIBLE.\nType '{_DROP_ALL_PHRASE}' to proceed: "
        )
    if typed.strip().lower() != _DROP_ALL_PHRASE:
        log.error("--drop-all-tenants aborted: confirmation phrase did not match.")
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    # Destructive flags are opt-in. Strip them from argv; the lone remaining
    # positional, if any, is the seed-dir override.
    drop = False
    drop_all = False
    positionals = []
    for arg in argv:
        if arg in ("--drop", "-d"):
            drop = True
        elif arg == "--drop-all-tenants":
            drop_all = True
        else:
            positionals.append(arg)
    seed_dir = Path(positionals[0]) if positionals else _DEFAULT_SEED_DIR

    if not seed_dir.is_dir():
        log.error("seed directory not found: %s", seed_dir)
        return 1

    if drop_all:
        # Cross-tenant wipe: irreversible, so gate behind dev-env + typed
        # confirmation (security review finding). delete_many (not drop) keeps
        # the vector/text indexes intact, so no index rebuild is needed.
        if not _confirm_drop_all():
            return 1
        corpus = db.get_far_corpus()
        deleted = corpus.delete_many({}).deleted_count
        log.warning(
            "--drop-all-tenants: cleared the ENTIRE far_corpus (%d chunks across "
            "ALL tenants removed)",
            deleted,
        )
    elif drop:
        # Clean reload SCOPED to the seed set only (security review finding):
        # clears stale global-tenant seed chunks (e.g. left by a chunk_ref
        # formula change) without ever touching another tenant's corpus.
        # delete_many (not drop) keeps the indexes intact.
        corpus = db.get_far_corpus()
        delete_filter = _seed_delete_filter()
        deleted = corpus.delete_many(delete_filter).deleted_count
        log.warning(
            "--drop: cleared seed set %s (%d chunks removed)", delete_filter, deleted
        )

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

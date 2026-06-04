"""
embedder.py — Titan V2 embeddings with MongoDB-backed cache (ADR-0005 §3, §14).

Owner: Person A (write path).

ADR-0005 decisions enforced here:
  §3  — model amazon.titan-embed-text-v2:0, dimensions=512, normalize=True,
        region us-east-1.
  §14 — cache backend is MongoDB (one database, no Redis). No TTL:
        embeddings are deterministic for identical text + model version.
        Cache is invalidated only on embedding model version change via
        purge_cache_for_old_model_versions().

⚠ ADR DEVIATION — NEEDS TEAM CONFIRMATION:
  ADR-0005 §14/§16 names ``CacheBackedEmbeddings`` (listed as
  langchain-community). In the installed LangChain 1.x ecosystem that class
  now lives ONLY in ``langchain_classic`` — whose import is BANNED by
  ADR-0005 §1 hard rule + the CI linter. The two rules conflict, so this
  module implements the same §14 behavior (check Mongo before calling
  Bedrock; identical text + model version never re-embeds) as a thin
  custom wrapper around ``BedrockEmbeddings`` instead. Raise at standup;
  update ADR-0005 §16 once confirmed.

NOTE: Embedding requires Bedrock credentials — the team must explicitly
enable the .env bearer token before running ingestion (ADR-0005 migration
Step 4). Without credentials, embed calls raise; ingestion surfaces the
failure rather than silently stubbing (no silent failure paths, §10).
"""
from __future__ import annotations

import hashlib
import logging

from langchain_aws import BedrockEmbeddings

from app import config, db

log = logging.getLogger("ai-orchestrator.ingestion.embedder")


def build_bedrock_embeddings() -> BedrockEmbeddings:
    """Construct the raw Titan V2 embeddings client (§3 configuration)."""
    return BedrockEmbeddings(
        model_id=config.EMBEDDING_MODEL_ID,
        region_name=config.AWS_REGION,
        # dimensions and normalize are Titan V2-specific model kwargs (§3).
        model_kwargs={
            "dimensions": config.EMBEDDING_DIMENSIONS,
            "normalize": config.EMBEDDING_NORMALIZE,
        },
    )


def cache_key_for_text(text: str) -> str:
    """Deterministic cache key: model ID + version + content hash.

    Namespacing by model ID/version means a model upgrade can never serve
    stale vectors (§14 invalidation rule, §8 anti-pattern).
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{config.EMBEDDING_MODEL_ID}:{config.EMBEDDING_MODEL_VERSION}:{digest}"


class MongoCachedEmbedder:
    """Cache-through wrapper around BedrockEmbeddings (§14 replacement for
    the banned-in-1.x CacheBackedEmbeddings — see module docstring).

    Vectors persist in the embedding_cache collection so the cache survives
    container restarts. Only cache misses hit Bedrock.

    Exposes read-only ``last_hits`` / ``last_misses`` properties after each
    embed_documents() call so pipeline.py can include cache_hits in the
    ingestion summary (§7).
    """

    def __init__(self, inner: BedrockEmbeddings | None = None) -> None:
        # inner is injectable for unit tests (mock Bedrock, real cache logic).
        self._inner = inner
        self._cache = db.get_embedding_cache()
        # Reset on each embed_documents() call; exposed read-only via the
        # last_hits / last_misses properties (read by pipeline.py).
        self._last_hits: int = 0
        self._last_misses: int = 0

    @property
    def last_hits(self) -> int:
        """Cache hits served from Mongo on the most recent embed_documents()."""
        return self._last_hits

    @property
    def last_misses(self) -> int:
        """Cache misses sent to Bedrock on the most recent embed_documents()."""
        return self._last_misses

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of chunk texts, serving repeats from the Mongo cache.

        Steps:
          1. Compute a deterministic cache key per text (model-version namespaced).
          2. One batched find() to pull all existing cache entries at once.
          3. Send ONLY cache misses to Bedrock (single batch call).
          4. Upsert new vectors tagged with embedding_model_version for
             targeted purge on model change (§14 invalidation).
          5. Return vectors in original input order; update hit/miss counters
             so the ingestion run summary can surface cache_hits (§7).
        """
        # Step 1 — compute cache keys for all texts.
        keys = [cache_key_for_text(t) for t in texts]

        # Step 2 — batch fetch; _id is the cache key string.
        cached: dict[str, list[float]] = {
            doc["_id"]: doc["embedding"]
            for doc in self._cache.find({"_id": {"$in": keys}})
        }

        # Step 3 — identify misses; preserve original indices for ordering.
        miss_indices = [i for i, k in enumerate(keys) if k not in cached]
        miss_texts = [texts[i] for i in miss_indices]

        if miss_texts:
            if self._inner is None:
                # Cache-hit-only usage works without an inner embedder (tests);
                # a miss without one is a configuration error, not an AttributeError.
                raise RuntimeError(
                    "MongoCachedEmbedder has no inner embedder configured — "
                    "pass one to __init__ or use get_embedder()"
                )
            # Bedrock batch call — raises on auth/throttle failure (§10: no silence).
            new_vectors = self._inner.embed_documents(miss_texts)

            # Step 4 — upsert each new vector with its model version tag.
            for idx, vector in zip(miss_indices, new_vectors):
                self._cache.update_one(
                    {"_id": keys[idx]},
                    {
                        "$set": {
                            "embedding": vector,
                            # Version tag enables targeted delete on model change (§14).
                            "embedding_model_version": config.EMBEDDING_MODEL_VERSION,
                        }
                    },
                    upsert=True,
                )
                cached[keys[idx]] = vector

        # Step 5 — update counters before return.
        self._last_hits = len(keys) - len(miss_indices)
        self._last_misses = len(miss_indices)
        log.debug(
            "embed_documents: %d texts, %d cache hits, %d Bedrock calls",
            len(texts),
            self._last_hits,
            self._last_misses,
        )

        # Return in original input order by resolving each key.
        return [cached[k] for k in keys]

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string (same cache-through path, batch of 1)."""
        return self.embed_documents([text])[0]


def build_cached_embedder() -> MongoCachedEmbedder:
    """Construct the cache-wrapped embedder used by the ingestion pipeline."""
    return MongoCachedEmbedder(build_bedrock_embeddings())


def purge_cache_for_old_model_versions() -> int:
    """Delete cache entries whose model version != current config version.

    Called manually on embedding model change (ADR-0005 §9 / §14 migration).
    Stale vectors from the old model are incompatible with new query embeddings
    and would silently degrade retrieval precision (§8 anti-pattern).
    Returns the number of purged entries.
    """
    result = db.get_embedding_cache().delete_many(
        # $ne current version — targets all entries from superseded model versions.
        {"embedding_model_version": {"$ne": config.EMBEDDING_MODEL_VERSION}}
    )
    log.info("purged %d stale cache entries (model version != %s)", result.deleted_count, config.EMBEDDING_MODEL_VERSION)
    return result.deleted_count

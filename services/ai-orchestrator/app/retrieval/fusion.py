"""
retrieval/fusion.py — Reciprocal Rank Fusion (plain Python, no EnsembleRetriever).

ADR-0005 §4: RRF weights 0.6 dense / 0.4 sparse, k=60 (Cormack et al. 2009).
Unit-testable without any MongoDB or Bedrock connection.
"""
from __future__ import annotations

import logging

from langchain_core.documents import Document

from app import config

log = logging.getLogger("ai-orchestrator.retrieval.fusion")


def doc_key(doc: Document) -> str:
    """Stable dedup/identity key for a chunk: chunk_id, else content prefix.

    This is the single source of truth for chunk identity across the read path:
    fusion's dedup AND the router's audit-score pairing key on it. They MUST use
    this same helper — if they diverge, the router's per-chunk fused-score lookup
    misses and silently zeroes the DCAA audit trail's retrieval_scores.
    """
    cid = doc.metadata.get("chunk_id")
    if cid:
        return cid
    # Content-prefix fallback is collision-prone (FAR boilerplate clause
    # headers share prefixes) — the retriever boundary normalizes chunk_id
    # on both paths, so reaching this in prod means a chunk lost identity.
    log.warning("document missing chunk_id — falling back to content-prefix key")
    return doc.page_content[:64]


def reciprocal_rank_fusion(
    dense_results: list[tuple[Document, float]],
    sparse_results: list[Document],
    dense_weight: float = config.RRF_DENSE_WEIGHT,
    sparse_weight: float = config.RRF_SPARSE_WEIGHT,
    k: int = 60,
) -> list[tuple[Document, float]]:
    """Merge dense + sparse ranked lists into a single fused ranking.

    Uses doc_key() (chunk_id from metadata, else a page_content prefix) as the
    deduplication key — the same helper the router uses for audit-score pairing.

    Returns list of (Document, fused_score) sorted by score descending.
    """
    scores: dict[str, float] = {}
    docs: dict[str, Document] = {}

    for rank, (doc, _) in enumerate(dense_results):
        cid = doc_key(doc)
        scores[cid] = scores.get(cid, 0.0) + dense_weight / (k + rank + 1)
        docs[cid] = doc

    for rank, doc in enumerate(sparse_results):
        cid = doc_key(doc)
        scores[cid] = scores.get(cid, 0.0) + sparse_weight / (k + rank + 1)
        if cid not in docs:
            docs[cid] = doc

    return [
        (docs[cid], scores[cid])
        for cid in sorted(scores, key=scores.__getitem__, reverse=True)
    ]

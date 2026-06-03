"""
retrieval/fusion.py — Reciprocal Rank Fusion (plain Python, no EnsembleRetriever).

ADR-0005 §4: RRF weights 0.6 dense / 0.4 sparse, k=60 (Cormack et al. 2009).
Unit-testable without any MongoDB or Bedrock connection.
"""
from __future__ import annotations

from langchain_core.documents import Document

from app import config


def reciprocal_rank_fusion(
    dense_results: list[tuple[Document, float]],
    sparse_results: list[Document],
    dense_weight: float = config.RRF_DENSE_WEIGHT,
    sparse_weight: float = config.RRF_SPARSE_WEIGHT,
    k: int = 60,
) -> list[tuple[Document, float]]:
    """Merge dense + sparse ranked lists into a single fused ranking.

    Uses chunk_id from metadata as the deduplication key. Falls back to a
    prefix of page_content when chunk_id is absent (should not happen in prod).

    Returns list of (Document, fused_score) sorted by score descending.
    """
    scores: dict[str, float] = {}
    docs: dict[str, Document] = {}

    def _key(doc: Document) -> str:
        return doc.metadata.get("chunk_id") or doc.page_content[:64]

    for rank, (doc, _) in enumerate(dense_results):
        cid = _key(doc)
        scores[cid] = scores.get(cid, 0.0) + dense_weight / (k + rank + 1)
        docs[cid] = doc

    for rank, doc in enumerate(sparse_results):
        cid = _key(doc)
        scores[cid] = scores.get(cid, 0.0) + sparse_weight / (k + rank + 1)
        if cid not in docs:
            docs[cid] = doc

    return [
        (docs[cid], scores[cid])
        for cid in sorted(scores, key=scores.__getitem__, reverse=True)
    ]

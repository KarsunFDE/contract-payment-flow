"""
retrieval/reranker.py — cross-encoder reranking (ADR-0005 §5).

Model: cross-encoder/ms-marco-MiniLM-L-6-v2, pre-downloaded at build time.
Fallback: unranked fused top-k when the cross-encoder fails (ADR §10).
"""
from __future__ import annotations

import logging

from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain_core.documents import Document

from app import config

log = logging.getLogger("ai-orchestrator.retrieval.reranker")

_encoder: HuggingFaceCrossEncoder | None = None


def _get_encoder() -> HuggingFaceCrossEncoder:
    global _encoder
    if _encoder is None:
        _encoder = HuggingFaceCrossEncoder(model_name=config.CROSS_ENCODER_MODEL)
    return _encoder


def rerank(
    query: str,
    fused_results: list[tuple[Document, float]],
    top_n: int = config.RERANK_TOP_N,
) -> tuple[list[tuple[Document, float | None]], bool]:
    """Score fused candidates with the cross-encoder and return top_n.

    Returns (ranked_results, is_degraded). is_degraded=True means the
    cross-encoder failed and the caller should record degraded retrieval_strategy.

    On the degraded (fallback) path the rerank score slot is set to None rather
    than the RRF fused score: emitting a fused score in the rerank column would
    conflate two different score spaces in one audit field. The caller pairs each
    chunk with its own fused score separately, so the fallback ordering (fused
    top-n) is preserved while the rerank score is explicitly absent.
    """
    if not fused_results:
        return [], False

    docs = [doc for doc, _ in fused_results]
    try:
        encoder = _get_encoder()
        pairs = [(query, doc.page_content) for doc in docs]
        scores = encoder.score(pairs)
        ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
        return list(ranked[:top_n]), False

    except Exception:
        log.warning(
            "cross-encoder reranker failed — degraded mode, returning fused top-%d "
            "with null rerank scores",
            top_n,
            exc_info=True,
        )
        # Preserve fused ordering but null the rerank score slot (sentinel) so the
        # audit/response rerank score column is not polluted with RRF scores.
        degraded = [(doc, None) for doc, _ in fused_results[:top_n]]
        return degraded, True

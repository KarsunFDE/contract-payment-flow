"""
retrieval/router.py — read-path endpoint (ADR-0005 Phase 1).

POST /retrieve  — query, sf30_block, tenant_id, contract_id →
                  hybrid retrieve → RRF fuse → rerank → audit log → response
"""
from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pymongo.errors import ConnectionFailure, OperationFailure

from app import config
from app.audit import logger as audit
from app.retrieval import failures, fusion, reranker, retriever
from app.schemas import RetrievalAuditRecord

log = logging.getLogger("ai-orchestrator.retrieval.router")

router = APIRouter(prefix="/retrieve", tags=["retrieval"])


class RetrieveRequest(BaseModel):
    query: str
    sf30_block: str
    tenant_id: str
    contract_id: str
    user_id: str = "anonymous"
    correlation_id: str | None = None


class RetrievedChunk(BaseModel):
    chunk_id: str
    chunk_text: str
    # None when the cross-encoder reranker degraded — no valid rerank score
    # exists for the chunk (clients must not read it as a real similarity score).
    score: float | None = None
    source_document: dict | None = None


class RetrieveResponse(BaseModel):
    correlation_id: str
    chunks: list[RetrievedChunk]
    retrieval_strategy: str
    latency_ms: int
    chunk_count: int
    degraded: bool = False


@router.get("/_status")
def status() -> dict[str, str]:
    return {"router": "retrieval", "status": "active"}


@router.post("/", response_model=RetrieveResponse)
def retrieve(request: RetrieveRequest) -> RetrieveResponse:
    """Hybrid FAR corpus retrieval for a single SF-30 block query.

    1. dense $vectorSearch (Titan V2) k=20
    2. sparse BM25 $search k=20
    3. RRF fusion (0.6/0.4)
    4. cross-encoder rerank → top 8
    5. structured audit log write
    """
    correlation_id = request.correlation_id or str(uuid4())
    start = time.monotonic()
    is_degraded = False
    retrieval_strategy = "hybrid_rrf_reranked"

    tenant_ids = retriever._tenant_ids(request.tenant_id)

    try:
        failures.check_circuit()
    except failures.CircuitBreakerOpen as exc:
        log.error("circuit breaker open — correlation_id=%s", correlation_id)
        raise HTTPException(status_code=503, detail=str(exc))

    # --- dense search (with $vectorSearch fallback on OperationFailure) ---
    dense_results = []
    try:
        dense_results = retriever.dense_search(request.query, tenant_ids)
        failures.record_success()
    except (OperationFailure, ConnectionFailure) as exc:
        log.warning(
            "$vectorSearch failed — BM25-only fallback. correlation_id=%s error=%s",
            correlation_id,
            exc,
        )
        failures.record_failure()
        retrieval_strategy = "sparse_bm25_fallback"
        is_degraded = True
    except Exception as exc:
        log.error(
            "dense_search unexpected error — correlation_id=%s", correlation_id, exc_info=True
        )
        failures.record_failure()
        retrieval_strategy = "sparse_bm25_fallback"
        is_degraded = True

    # --- sparse search ---
    sparse_results = []
    try:
        sparse_results = retriever.sparse_search(request.query, tenant_ids)
    except Exception:
        log.error("sparse_search failed — correlation_id=%s", correlation_id, exc_info=True)
        if not dense_results:
            raise HTTPException(status_code=502, detail="Both retrieval paths failed")
        # Dense succeeded but sparse failed — serve dense-only results, flagged degraded.
        retrieval_strategy = "dense_only_fallback"
        is_degraded = True

    # --- RRF fusion ---
    fused = fusion.reciprocal_rank_fusion(dense_results, sparse_results)
    # Map document identity → pre-rerank fused score so the audit record can pair
    # each reranked chunk with its OWN fused score. The cross-encoder reorders
    # results, so positional pre_rerank_scores[i] would be misaligned. Key logic
    # mirrors fusion._key (chunk_id from metadata, falling back to page_content
    # prefix) so lookups hit the same identity fusion used to dedupe.
    fused_score_by_key = {
        (doc.metadata.get("chunk_id") or doc.page_content[:64]): score
        for doc, score in fused
    }

    # --- rerank ---
    ranked, reranker_degraded = reranker.rerank(request.query, fused)
    if reranker_degraded:
        _unranked_strategy = {
            "sparse_bm25_fallback": "sparse_bm25_unranked_fallback",
            "dense_only_fallback": "dense_only_unranked_fallback",
        }
        retrieval_strategy = _unranked_strategy.get(
            retrieval_strategy, "hybrid_rrf_unranked_fallback"
        )
        is_degraded = True

    # --- partial retrieval check (ADR §10) ---
    # Below MIN_RETRIEVED_CHUNKS we still return the chunks but flag degraded so
    # Phase-2 confidence gating treats it as a confidence failure (config.py §10).
    # We do NOT raise — the partial result is surfaced, just marked degraded.
    if len(ranked) < config.MIN_RETRIEVED_CHUNKS:
        log.warning(
            "partial retrieval — %d chunks below MIN_RETRIEVED_CHUNKS=%d. correlation_id=%s",
            len(ranked),
            config.MIN_RETRIEVED_CHUNKS,
            correlation_id,
        )
        is_degraded = True

    # --- build response ---
    chunk_ids: list[str] = []
    # rerank scores are None in the reranker-degraded fallback path (sentinel):
    # the audit/response rerank column must not be filled with RRF fused scores.
    reranked_scores: list[float | None] = []
    # Pre-rerank fused scores in reranked order — retrieval_scores[i] is the
    # fused score of chunks_retrieved[i], looked up by document identity.
    retrieval_scores: list[float] = []
    response_chunks: list[RetrievedChunk] = []
    for doc, score in ranked:
        cid = doc.metadata.get("chunk_id", "")
        chunk_ids.append(cid)
        rerank_score = None if score is None else float(score)
        reranked_scores.append(rerank_score)
        fused_key = doc.metadata.get("chunk_id") or doc.page_content[:64]
        fused_score = float(fused_score_by_key.get(fused_key, 0.0))
        retrieval_scores.append(fused_score)
        response_chunks.append(
            RetrievedChunk(
                chunk_id=cid,
                chunk_text=doc.page_content,
                # Surface the rerank score to clients; in degraded mode it is
                # null (no valid cross-encoder score exists for this chunk).
                score=rerank_score,
                source_document=doc.metadata.get("source_document"),
            )
        )

    latency = audit.elapsed_ms(start)

    # --- audit record (insert-only, never fails silently) ---
    record = RetrievalAuditRecord(
        correlation_id=correlation_id,
        sf30_block=request.sf30_block,
        contract_id=request.contract_id,
        tenant_id=request.tenant_id,
        user_id=request.user_id,
        query_text=request.query,
        retrieval_strategy=retrieval_strategy,
        chunks_retrieved=chunk_ids,
        retrieval_scores=retrieval_scores,
        reranked_scores=reranked_scores,
        embedding_model=config.EMBEDDING_MODEL_ID,
        cache_hit=False,
        latency_ms=latency,
    )
    try:
        audit.write_audit_record(record)
    except Exception:
        log.error("audit write failed — continuing. correlation_id=%s", correlation_id)

    return RetrieveResponse(
        correlation_id=correlation_id,
        chunks=response_chunks,
        retrieval_strategy=retrieval_strategy,
        latency_ms=latency,
        chunk_count=len(response_chunks),
        degraded=is_degraded,
    )

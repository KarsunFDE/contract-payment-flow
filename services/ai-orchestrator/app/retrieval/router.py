"""
retrieval/router.py — read-path endpoint (ADR-0005 Phase 1).

POST /retrieve  — query, sf30_block, contract_id (body) +
                  X-Tenant-Id / X-User-Id / X-User-Role (gateway-asserted
                  identity) →
                  hybrid retrieve → RRF fuse → rerank → audit log → response

Identity is NEVER read from the request body (ADR-0005 §11): the API gateway
validates the caller's JWT and injects X-Tenant-Id / X-User-Id / X-User-Role
from the verified claims (agency_id / sub / role), stripping any client-supplied
copies of those headers. This service is reachable only on the compose-internal
network, so the headers are trusted as gateway-asserted identity. Requests
without all three headers are rejected 401 — an unauthenticated retrieval must
not happen, and the append-only audit trail (FAR 1.602-1 — CO authority) must
never carry self-asserted identity NOR a defaulted role: the caller's real role
is recorded so a non-CO retrieval is never misattributed as CO activity
(review finding).

contract_id is audit metadata only: ADR-0005 §11 — "No contract-instance
data enters the vector index regardless of tenant scope" — so there is no
contract dimension to filter retrieval by. It scopes audit-log queries
(§11 audit log isolation), not the corpus.
"""
from __future__ import annotations

import logging
import re
import time
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import ConnectionFailure, OperationFailure

from app import config
from app.audit import logger as audit
from app.retrieval import failures, fusion, reranker, retriever
from app.schemas import RetrievalAuditRecord

log = logging.getLogger("ai-orchestrator.retrieval.router")

router = APIRouter(prefix="/retrieve", tags=["retrieval"])

# Identity header values are gateway-asserted but still shape-validated as
# defense-in-depth (they end up in Mongo filters and the audit collection).
_TENANT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_USER_ID_RE = re.compile(r"^[A-Za-z0-9.@_:-]{1,128}$")
_ROLE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Query length cap: bounds Bedrock embedding cost, Atlas $search work, and
# cross-encoder input before any of them run.
MAX_QUERY_CHARS = 2000


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    sf30_block: str = Field(
        min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.-]+$",
        description='SF-30 block that triggered retrieval, e.g. "13"',
    )
    contract_id: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$",
        description="Audit metadata — never a retrieval filter (ADR-0005 §11)",
    )
    correlation_id: str | None = Field(default=None, min_length=1, max_length=64)


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


def _require_identity(
    tenant_id: str | None, user_id: str | None, role: str | None
) -> tuple[str, str, str]:
    """Validate gateway-asserted identity headers; 401 on absence or bad shape.

    Role is required alongside tenant/user: the audit record stores the real
    role, so a blank/absent role must fail closed rather than fall back to a
    CO-authority default (review finding — falsified authority record).
    """
    if not tenant_id or not user_id or not role:
        raise HTTPException(
            status_code=401,
            detail="Missing gateway identity headers (X-Tenant-Id / X-User-Id / X-User-Role)",
        )
    if (
        not _TENANT_ID_RE.fullmatch(tenant_id)
        or not _USER_ID_RE.fullmatch(user_id)
        or not _ROLE_RE.fullmatch(role)
    ):
        raise HTTPException(status_code=401, detail="Malformed identity headers")
    return tenant_id, user_id, role


@router.post("/", response_model=RetrieveResponse)
def retrieve(
    request: RetrieveRequest,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
) -> RetrieveResponse:
    """Hybrid FAR corpus retrieval for a single SF-30 block query.

    1. dense $vectorSearch (Titan V2) k=20
    2. sparse BM25 $search k=20
    3. RRF fusion (0.6/0.4)
    4. cross-encoder rerank → top 8
    5. structured audit log write (fail-closed — no unaudited results)
    """
    tenant_id, user_id, role = _require_identity(x_tenant_id, x_user_id, x_user_role)

    correlation_id = request.correlation_id or str(uuid4())
    start = time.monotonic()
    is_degraded = False
    retrieval_strategy = "hybrid_rrf_reranked"

    tenant_ids = retriever._tenant_ids(tenant_id)

    try:
        failures.check_circuit()
    except failures.CircuitBreakerOpen as exc:
        log.error("circuit breaker open — correlation_id=%s", correlation_id)
        raise HTTPException(status_code=503, detail=str(exc))

    # Breaker accounting (failures.py — MongoDB-only): record_failure() only on
    # Mongo-typed errors, on BOTH retrieval paths; record_success() only when
    # every Mongo op this request attempted succeeded — otherwise a persistent
    # dense-side Mongo outage would be erased by sparse success each request
    # and the breaker would never trip. Non-Mongo errors (e.g. Bedrock
    # embedding, cross-encoder) must not move the Mongo breaker.
    # release_probe() in the finally frees a reserved half-open probe slot if
    # this request never reached a Mongo outcome (record_* calls already free
    # it themselves).
    mongo_failed = False
    try:
        # --- dense search (with $vectorSearch fallback on OperationFailure) ---
        dense_results = []
        try:
            dense_results = retriever.dense_search(request.query, tenant_ids)
        except (OperationFailure, ConnectionFailure) as exc:
            log.warning(
                "$vectorSearch failed — BM25-only fallback. correlation_id=%s error=%s",
                correlation_id,
                exc,
            )
            failures.record_failure()
            mongo_failed = True
            retrieval_strategy = "sparse_bm25_fallback"
            is_degraded = True
        except Exception:
            # Non-Mongo failure (e.g. Bedrock embedding error) — fall back to
            # sparse, but do NOT count it against the MongoDB circuit breaker.
            log.error(
                "dense_search unexpected error — correlation_id=%s",
                correlation_id,
                exc_info=True,
            )
            retrieval_strategy = "sparse_bm25_fallback"
            is_degraded = True

        # --- sparse search ---
        sparse_results = []
        try:
            sparse_results = retriever.sparse_search(request.query, tenant_ids)
        except (OperationFailure, ConnectionFailure):
            log.error(
                "sparse_search Mongo failure — correlation_id=%s",
                correlation_id,
                exc_info=True,
            )
            failures.record_failure()
            mongo_failed = True
            if not dense_results:
                raise HTTPException(status_code=502, detail="Both retrieval paths failed")
            # Dense succeeded but sparse failed — serve dense-only, flagged degraded.
            retrieval_strategy = "dense_only_fallback"
            is_degraded = True
        except Exception:
            log.error(
                "sparse_search failed — correlation_id=%s", correlation_id, exc_info=True
            )
            if not dense_results:
                raise HTTPException(status_code=502, detail="Both retrieval paths failed")
            retrieval_strategy = "dense_only_fallback"
            is_degraded = True

        if not mongo_failed:
            failures.record_success()
    finally:
        failures.release_probe()

    # --- RRF fusion ---
    fused = fusion.reciprocal_rank_fusion(dense_results, sparse_results)
    # Map document identity → pre-rerank fused score so the audit record can pair
    # each reranked chunk with its OWN fused score. The cross-encoder reorders
    # results, so positional pre_rerank_scores[i] would be misaligned. Key on
    # fusion.doc_key — the SAME helper fusion used to dedupe — so these lookups
    # hit the identity fusion assigned (divergence silently zeroes audit scores).
    fused_score_by_key = {fusion.doc_key(doc): score for doc, score in fused}

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
        if not cid:
            # Retriever boundary normalizes chunk_id on both paths — an empty id
            # here breaks chunk-level audit traceability, so make it loud.
            log.error(
                "chunk missing chunk_id in audit assembly — correlation_id=%s",
                correlation_id,
            )
        chunk_ids.append(cid)
        rerank_score = None if score is None else float(score)
        reranked_scores.append(rerank_score)
        fused_key = fusion.doc_key(doc)
        if fused_key not in fused_score_by_key:
            # A reranked chunk whose identity is absent from the fused map means
            # the key drifted from fusion's — the 0.0 fallback would silently
            # zero this chunk's DCAA audit retrieval score. Make it loud.
            log.warning(
                "fused score missing for chunk %r — audit retrieval_score zeroed. "
                "correlation_id=%s",
                fused_key,
                correlation_id,
            )
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

    # --- audit record (insert-only, fail-closed) ---
    # FAR 43.102: only the CO executes modifications — the retrieval that feeds
    # CO drafting must leave a durable trace. If the audit write fails, the
    # results are NOT returned: an unaudited retrieval is a traceability hole,
    # not a degraded success.
    record = RetrievalAuditRecord(
        correlation_id=correlation_id,
        sf30_block=request.sf30_block,
        contract_id=request.contract_id,
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
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
    except (OperationFailure, ConnectionFailure):
        log.error(
            "audit write Mongo failure — failing closed. correlation_id=%s",
            correlation_id,
            exc_info=True,
        )
        failures.record_failure()
        raise HTTPException(
            status_code=503,
            detail="Retrieval audit write failed — results withheld (audit required)",
        )
    except Exception:
        log.error(
            "audit write failed — failing closed. correlation_id=%s",
            correlation_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=503,
            detail="Retrieval audit write failed — results withheld (audit required)",
        )

    return RetrieveResponse(
        correlation_id=correlation_id,
        chunks=response_chunks,
        retrieval_strategy=retrieval_strategy,
        latency_ms=latency,
        chunk_count=len(response_chunks),
        degraded=is_degraded,
    )

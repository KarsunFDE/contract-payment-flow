"""
retrieval/retriever.py — hybrid dense + sparse search (ADR-0005 Phase 1 §4/§11).

Two public functions:
  dense_search  — $vectorSearch via MongoDBAtlasVectorSearch (Titan V2 512d)
  sparse_search — BM25 $search via Atlas Text Search

tenant_id pre-filter is applied INSIDE these functions, never trusted from the
app layer (ADR-0005 §11 security control, §6).
"""
from __future__ import annotations

import logging

import boto3
from langchain_aws import BedrockEmbeddings
from langchain_core.documents import Document
from langchain_mongodb import MongoDBAtlasVectorSearch

from app import config
from app import db
from app.retrieval.failures import with_retry

log = logging.getLogger("ai-orchestrator.retrieval.retriever")

_embeddings: BedrockEmbeddings | None = None


def _get_embeddings() -> BedrockEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = BedrockEmbeddings(
            model_id=config.EMBEDDING_MODEL_ID,
            region_name=config.AWS_REGION,
            model_kwargs={
                "dimensions": config.EMBEDDING_DIMENSIONS,
                "normalize": config.EMBEDDING_NORMALIZE,
            },
        )
    return _embeddings


def _tenant_ids(agency_id: str) -> list[str]:
    """Mandatory tenant filter: global corpus + requesting agency (ADR §11)."""
    ids = [config.GLOBAL_TENANT_ID]
    if agency_id and agency_id != config.GLOBAL_TENANT_ID:
        ids.append(agency_id)
    return ids


@with_retry
def dense_search(
    query: str,
    tenant_ids: list[str],
    k: int = config.DENSE_K,
) -> list[tuple[Document, float]]:
    """$vectorSearch k=20 with mandatory tenant_id pre-filter.

    Wrapped in @with_retry: transient Mongo errors (OperationFailure,
    ConnectionFailure) are retried config.MAX_RETRIES times before propagating.
    Non-Mongo errors (e.g. a Bedrock embedding failure) are not retried and
    propagate immediately. After retries exhaust, raises pymongo.errors.* —
    caller (router) catches this, records the failure, and falls back to
    sparse_search.
    """
    collection = db.get_far_corpus()
    vector_store = MongoDBAtlasVectorSearch(
        collection=collection,
        embedding=_get_embeddings(),
        index_name=config.FAR_VECTOR_INDEX,
        text_key="chunk_text",
        embedding_key="embedding",
    )
    return vector_store.similarity_search_with_score(
        query=query,
        k=k,
        pre_filter={"tenant_id": {"$in": tenant_ids}},
    )


@with_retry
def sparse_search(
    query: str,
    tenant_ids: list[str],
    k: int = config.SPARSE_K,
) -> list[Document]:
    """BM25 Atlas Text Search ($search) with tenant_id filter inside $search.

    Wrapped in @with_retry: transient Mongo errors (OperationFailure,
    ConnectionFailure) are retried config.MAX_RETRIES times before propagating;
    other exceptions propagate immediately to the router's sparse handler.

    Tenant scoping is a compound `filter` clause inside the $search stage so the
    BM25 ranking is computed only over the requesting tenant(s) — a post-$search
    $match would let $search rank across all tenants and then discard most of the
    candidates, starving the $limit and degrading recall. A defensive $match is
    kept after $search as cheap defense-in-depth against index misconfiguration.

    Returns Documents with chunk_id, score, and source metadata in .metadata.
    """
    collection = db.get_far_corpus()
    pipeline = [
        {
            "$search": {
                "index": config.FAR_TEXT_INDEX,
                "compound": {
                    "must": [
                        {
                            "text": {
                                "query": query,
                                "path": "chunk_text",
                            }
                        }
                    ],
                    "filter": [
                        {"in": {"path": "tenant_id", "value": tenant_ids}}
                    ],
                },
            }
        },
        # Defense-in-depth: redundant given the in-search filter above, but cheap
        # and guards against an index that is not configured to filter tenant_id.
        {"$match": {"tenant_id": {"$in": tenant_ids}}},
        {"$addFields": {"_search_score": {"$meta": "searchScore"}}},
        {"$limit": k},
    ]
    docs: list[Document] = []
    for raw in collection.aggregate(pipeline):
        metadata = {
            "chunk_id": str(raw.get("chunk_id", "")),
            "tenant_id": raw.get("tenant_id", ""),
            "score": raw.get("_search_score", 0.0),
            "source_document": raw.get("source_document", {}),
        }
        docs.append(Document(page_content=raw.get("chunk_text", ""), metadata=metadata))
    return docs


def hybrid_search(
    query: str,
    agency_id: str,
    dense_k: int = config.DENSE_K,
    sparse_k: int = config.SPARSE_K,
) -> tuple[list[tuple[Document, float]], list[Document]]:
    """Run both searches. Caller handles OperationFailure from dense_search."""
    tids = _tenant_ids(agency_id)
    return dense_search(query, tids, k=dense_k), sparse_search(query, tids, k=sparse_k)

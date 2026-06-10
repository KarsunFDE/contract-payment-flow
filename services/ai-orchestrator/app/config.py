"""
config.py — shared retrieval-layer settings (ADR-0005 Phase 1).

Day 0 contract file: frozen after the scaffolding commit. Both the
ingestion (write path) and retrieval (read path) packages read from here —
neither edits this without telling the other.

Values follow ADR-0005:
  §2  — MongoDB Atlas Local vector store
  §3  — Titan V2 embeddings, 512 dimensions, cosine
  §4  — hybrid retrieval k values, RRF weights
  §5  — cross-encoder reranker, top_n=8
  §13 — chunking (512 tokens / 64 overlap)

Plain os.environ access matches the existing idiom in bedrock_client.py —
no pydantic-settings dependency.
"""
from __future__ import annotations

import os

# --- MongoDB (Atlas Local) ---
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "acquire_gov")

# Collections
FAR_CORPUS_COLLECTION = os.environ.get("FAR_CORPUS_COLLECTION", "far_corpus")
RETRIEVAL_AUDIT_COLLECTION = os.environ.get(
    "RETRIEVAL_AUDIT_COLLECTION", "retrieval_audit"
)
EMBEDDING_CACHE_COLLECTION = os.environ.get(
    "EMBEDDING_CACHE_COLLECTION", "embedding_cache"
)

# Index names (ADR-0005 §2, Migration Step 5)
FAR_VECTOR_INDEX = os.environ.get("FAR_VECTOR_INDEX", "far_vector_idx")
FAR_TEXT_INDEX = os.environ.get("FAR_TEXT_INDEX", "far_text_idx")

# --- Embeddings (ADR-0005 §3) ---
EMBEDDING_MODEL_ID = os.environ.get(
    "EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0"
)
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "512"))
EMBEDDING_MODEL_VERSION = os.environ.get("EMBEDDING_MODEL_VERSION", "v2")
EMBEDDING_NORMALIZE = True
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# --- Hybrid retrieval (ADR-0005 §4, Block 13 pipeline) ---
DENSE_K = int(os.environ.get("DENSE_K", "20"))
SPARSE_K = int(os.environ.get("SPARSE_K", "20"))
RRF_DENSE_WEIGHT = float(os.environ.get("RRF_DENSE_WEIGHT", "0.6"))
RRF_SPARSE_WEIGHT = float(os.environ.get("RRF_SPARSE_WEIGHT", "0.4"))

# --- Re-ranking (ADR-0005 §5) ---
CROSS_ENCODER_MODEL = os.environ.get(
    "CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
)
RERANK_TOP_N = int(os.environ.get("RERANK_TOP_N", "8"))

# --- Chunking (ADR-0005 §13) ---
CHUNK_SIZE_TOKENS = int(os.environ.get("CHUNK_SIZE_TOKENS", "512"))
CHUNK_OVERLAP_TOKENS = int(os.environ.get("CHUNK_OVERLAP_TOKENS", "64"))
MIN_CHUNK_CHARS = 100  # discard fragments below this (§13 rule 4)

# --- Multi-tenancy (ADR-0005 §11) ---
GLOBAL_TENANT_ID = "far_corpus_global"

# --- Quality gates (ADR-0005 §4/§7 — Phase 2 consumes, defined here for parity) ---
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.85"))
MIN_RETRIEVED_CHUNKS = 3  # below this → treat as confidence failure (§10)

# --- Retry policy (ADR-0005 §10, aligned with ADR-0004) ---
MAX_RETRIES = 4
RETRY_JITTER = 0.2  # 20% jitter on exponential backoff

# --- Circuit breaker (ADR-0005 §10) ---
# Seconds the breaker stays fully open before allowing a half-open probe request.
CIRCUIT_BREAKER_RESET_SECONDS = float(
    os.environ.get("CIRCUIT_BREAKER_RESET_SECONDS", "30")
)

"""
db.py — PyMongo client factory and collection handles (ADR-0005 Phase 1).

Day 0 contract file: frozen after the scaffolding commit.

Lazy singleton client mirrors the bedrock_client.py pattern — the module
imports cleanly with no MongoDB running (tests / CI without compose up).
Connection only happens on first collection access.
"""
from __future__ import annotations

import logging

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from app import config

log = logging.getLogger("ai-orchestrator.db")

_client: MongoClient | None = None


def get_client() -> MongoClient:
    """Lazy singleton MongoClient. serverSelectionTimeoutMS kept short so a
    missing container fails fast instead of hanging the request."""
    global _client
    if _client is None:
        log.info("creating MongoClient for %s", config.MONGO_DB)
        _client = MongoClient(config.MONGO_URL, serverSelectionTimeoutMS=5000)
    return _client


def get_db() -> Database:
    return get_client()[config.MONGO_DB]


def get_far_corpus() -> Collection:
    """FAR/DFARS/WAWF/PIEE chunk collection — vector index lives here.
    Write path (ingestion) inserts; read path (retrieval) queries."""
    return get_db()[config.FAR_CORPUS_COLLECTION]


def get_retrieval_audit() -> Collection:
    """Append-only retrieval audit log (ADR-0005 §6/§12). Insert-only by
    convention here; the MongoDB role restriction enforces it server-side."""
    return get_db()[config.RETRIEVAL_AUDIT_COLLECTION]


def get_embedding_cache() -> Collection:
    """Backing collection for CacheBackedEmbeddings byte store (ADR-0005 §14)."""
    return get_db()[config.EMBEDDING_CACHE_COLLECTION]


def reset_client() -> None:
    """Test hook — drop the singleton so tests can swap MONGO_URL."""
    global _client
    if _client is not None:
        _client.close()
    _client = None

"""
execution_log.py — idempotency ledger for the auto-process lane (m3.md Step 7.5).

The money path must be replay-safe: a re-delivered item with the same
idempotency_key must be a no-op, never a double-pay (REQ-AGT-2). This is the
durable record of which keys have already been executed, kept in its own Mongo
collection. A unique index on idempotency_key makes the guard race-safe even if
two replays arrive concurrently.
"""
from __future__ import annotations

import os

from app import db

EXECUTION_LOG_COLLECTION = os.environ.get("EXECUTION_LOG_COLLECTION", "execution_log")


def _collection():
    return db.get_db()[EXECUTION_LOG_COLLECTION]


def already_processed(idempotency_key: str) -> bool:
    """True if this idempotency_key has already been executed (a replay)."""
    return _collection().find_one({"idempotency_key": idempotency_key}) is not None


def mark_processed(idempotency_key: str, draft_id: str) -> None:
    """Record that this key has been executed. Caller checks already_processed first."""
    _collection().insert_one({"idempotency_key": idempotency_key, "draft_id": draft_id})

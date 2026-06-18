"""
execution_log.py — idempotency ledger for the auto-process lane (m3.md Step 7.5).

The money path must be replay-safe: a re-delivered item with the same
idempotency_key must be a no-op, never a double-pay (REQ-AGT-2). This is the
durable record of which keys have already been executed, kept in its own Mongo
collection.

Race-safety guarantee: a unique index on idempotency_key (created by
scripts/create_indexes.py) makes concurrent replays race-safe at the DB layer.
`claim()` performs an ATOMIC insert-before-execute: the very first caller that
inserts the key wins; every subsequent concurrent caller hits DuplicateKeyError
and receives False (replay/no-op). The old check-then-act pattern (find_one +
insert_one) has been removed — it was a TOCTOU race that could let two concurrent
callers both pass the check and both execute the money path.
"""
from __future__ import annotations

import datetime
import logging
import os

from pymongo.errors import DuplicateKeyError

from app import db

log = logging.getLogger("ai-orchestrator.workflow.execution_log")

EXECUTION_LOG_COLLECTION = os.environ.get("EXECUTION_LOG_COLLECTION", "execution_log")


def _collection():
    return db.get_db()[EXECUTION_LOG_COLLECTION]


def claim(idempotency_key: str) -> bool:
    """Atomically claim an idempotency_key for processing.

    Inserts a 'processing' sentinel BEFORE the side effect executes.  The unique
    index on idempotency_key (scripts/create_indexes.py) guarantees at most one
    caller wins, even under concurrent replays.

    Returns True  — this caller won the race; it MUST call mark_done/mark_failed.
    Returns False — another caller already claimed (or completed) this key; the
                    caller MUST treat this as a replay and skip the side effect.

    This replaces the old already_processed() + mark_processed() pattern which was
    a TOCTOU race (double-pay class defect, Codex finding 1).
    """
    try:
        _collection().insert_one({
            "idempotency_key": idempotency_key,
            "status": "processing",
            "claimed_at": datetime.datetime.utcnow(),
        })
        return True
    except DuplicateKeyError:
        # Another thread/process already claimed or finished this key.
        log.debug("idempotency_key %r already claimed — replay no-op", idempotency_key)
        return False


def mark_done(idempotency_key: str, draft_id: str) -> None:
    """Update the claimed record to 'done' after the side effect succeeds."""
    _collection().update_one(
        {"idempotency_key": idempotency_key},
        {"$set": {
            "status": "done",
            "draft_id": draft_id,
            "completed_at": datetime.datetime.utcnow(),
        }},
    )


def mark_failed(idempotency_key: str, reason: str) -> None:
    """Update the claimed record to 'failed' so a human can retry after investigation.

    A failed key is NOT released for automatic re-processing — an operator must
    inspect and manually clear it to prevent a delayed double-pay on retry.
    """
    _collection().update_one(
        {"idempotency_key": idempotency_key},
        {"$set": {
            "status": "failed",
            "failure_reason": reason,
            "failed_at": datetime.datetime.utcnow(),
        }},
    )

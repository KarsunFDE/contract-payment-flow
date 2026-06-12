"""
execution_log.py — Person B: idempotency ledger for the auto lane (m3.md
Step 7.5 — task B5).

Backs REQ-AGT-2's no-double-pay guarantee: every auto-processed item is keyed
by its idempotency_key; a replay finds the key and becomes a no-op. Writes are
synchronous and fail-closed (a key we cannot durably record is a key we must
not process against — at-most-once on the money path).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from app import db

log = logging.getLogger("ai-orchestrator.workflow.execution_log")

WORKFLOW_EXECUTIONS_COLLECTION = os.environ.get(
    "WORKFLOW_EXECUTIONS_COLLECTION", "workflow_executions"
)


def already_processed(idempotency_key: str) -> bool:
    """True if this key has an execution record (replay -> no-op).

    Raises on lookup failure: if we cannot CHECK the ledger we must not
    process — an unverifiable replay risks a double-pay.
    """
    if not idempotency_key:
        raise ValueError("idempotency_key is required on the auto lane (REQ-AGT-2)")
    found = db.get_db()[WORKFLOW_EXECUTIONS_COLLECTION].find_one(
        {"idempotency_key": idempotency_key}
    )
    return found is not None


def mark_processed(idempotency_key: str, item_ref: str, correlation_id: str) -> None:
    """Record the execution. Raises on write failure (fail-closed)."""
    db.get_db()[WORKFLOW_EXECUTIONS_COLLECTION].insert_one(
        {
            "idempotency_key": idempotency_key,
            "item_ref": item_ref,
            "correlation_id": correlation_id,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    log.info("execution recorded — idempotency_key=%s", idempotency_key)

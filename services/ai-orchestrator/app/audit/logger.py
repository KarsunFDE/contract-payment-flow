"""
audit/logger.py — structured retrieval audit log (ADR-0005 §7/§12).

Insert-only. Every retrieval event gets a full RetrievalAuditRecord written
to the retrieval_audit collection. No updates, no deletes.
"""
from __future__ import annotations

import logging
import time

from app import db
from app.schemas import RetrievalAuditRecord

log = logging.getLogger("ai-orchestrator.audit")


def write_audit_record(record: RetrievalAuditRecord) -> None:
    """Insert a retrieval audit record. Raises on failure — no silent drops."""
    collection = db.get_retrieval_audit()
    doc = record.model_dump()
    doc["timestamp"] = record.timestamp.isoformat()
    try:
        collection.insert_one(doc)
        log.debug("audit record written — correlation_id=%s", record.correlation_id)
    except Exception:
        log.error(
            "audit write failed — correlation_id=%s retrieval_id=%s",
            record.correlation_id,
            record.retrieval_id,
            exc_info=True,
        )
        raise


def elapsed_ms(start_monotonic: float) -> int:
    """Milliseconds since start_monotonic (from time.monotonic())."""
    return int((time.monotonic() - start_monotonic) * 1000)

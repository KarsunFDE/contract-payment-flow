"""
mock_executor.py — Person B: mock execution for the auto lane (m3.md Step 7.5
— task B5).

PRD §4: the auto lane "processes" against synthetic systems only — no real
payment or contract write happens here. The executor's one real side effect is
the execution-log record (the idempotency mark), written BEFORE the mock action
so a crash mid-process replays as a no-op (at-most-once — fail toward no-pay,
never double-pay).
"""
from __future__ import annotations

import logging

from app.workflow import execution_log

log = logging.getLogger("ai-orchestrator.workflow.mock_executor")


def process(item_ref: str, idempotency_key: str, correlation_id: str) -> dict:
    """Mock-execute the item. Marks the idempotency ledger first (fail-closed).

    Returns a receipt dict for the caller's audit details.
    """
    execution_log.mark_processed(idempotency_key, item_ref, correlation_id)
    # The "execution" itself is a mock — synthetic systems only (PRD §4).
    log.info("mock-executed item %s (idempotency_key=%s)", item_ref, idempotency_key)
    return {
        "item_ref": item_ref,
        "idempotency_key": idempotency_key,
        "executor": "mock",
    }

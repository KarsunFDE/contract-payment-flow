"""
mock_executor.py — stand-in for the auto-process side effect (m3.md Step 7.5).

The auto lane performs a reversible, policy-cleared administrative action. The real
side effect (e.g. acknowledging an intake, routing a record) lives in the downstream
services; here it is mocked so the triage graph runs end-to-end. The caller guards on
the execution_log idempotency key BEFORE calling process, so this stays a plain
side-effect recorder.
"""
from __future__ import annotations

import logging

from app.workflow import execution_log

log = logging.getLogger("ai-orchestrator.workflow.executor")


def process(draft_id: str, idempotency_key: str) -> None:
    """Perform (mock) the auto-lane action and record the idempotency key."""
    log.info("auto-process executing draft_id=%s idempotency_key=%s",
             draft_id, idempotency_key)
    execution_log.mark_processed(idempotency_key, draft_id)

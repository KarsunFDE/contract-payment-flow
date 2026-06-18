"""
audit_events.py — workflow + triage audit log (m3.md Phase 6, ADR-0006 §Audit Log).

Distinct from app/audit/logger.py, which is RETRIEVAL-specific (it only writes a
RetrievalAuditRecord to the retrieval_audit collection). The SF-30 workflow and
the triage flow emit their own event types — contract_lookup, co_decision,
modification_submitted, item_triaged, auto_processed, ... — so they get their own
typed record and their own collection.

Append-only, synchronous, fail-closed: a write failure RAISES (ADR-0006
Integration Note 3 — the submit/decision/supersede trail must never be silently
dropped, unlike the brownfield async-flush pattern). Every record carries the
run's correlation_id so a workflow run is reconstructable end to end (ADR-0005
§7/§12; DCAA traceability).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app import db
from app.workflow.state import WorkflowState

log = logging.getLogger("ai-orchestrator.workflow.audit")

# This module owns its storage contract, so the collection name lives here rather
# than in the frozen config.py. Env-overridable, same idiom as config.py.
WORKFLOW_AUDIT_COLLECTION = os.environ.get("WORKFLOW_AUDIT_COLLECTION", "workflow_audit")

# The closed set of workflow/triage audit events (m3.md Phase 6 table + Step 7.5).
# Hard frozenset — record_event raises on any unknown event_type so typos and
# arbitrary strings never reach the append-only workflow_audit collection
# (DCAA reconstruction requires a clean, known-event trail).
WORKFLOW_EVENT_TYPES: frozenset[str] = frozenset({
    "contract_lookup",
    "contract_lookup_failed",
    "static_fields_populated",
    "confidence_escalation",
    "form_field_written",
    "co_decision",
    "contractor_consent_recorded",
    "package_superseded",
    "modification_submitted",
    "item_triaged",
    "auto_processed",
})

# High-consequence events that MUST carry actor identity, role, and package_hash
# in their details payload (ADR-0006 audit contract; Codex finding #2).
_HIGH_CONSEQUENCE_EVENTS: frozenset[str] = frozenset({
    "co_decision",
    "contractor_consent_recorded",
    "package_superseded",
    "modification_submitted",
})

# Exact key names callers (nodes_gate.py) must supply for high-consequence events.
_REQUIRED_HC_KEYS: tuple[str, ...] = ("actor_id", "actor_role", "package_hash")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowAuditRecord(BaseModel):
    """One workflow/triage audit event. Append-only; DCAA-reconstructable."""

    audit_id: str = Field(default_factory=lambda: str(uuid4()))
    correlation_id: str = Field(description="Shared across every node in one run")
    event_type: str = Field(description="One of WORKFLOW_EVENT_TYPES")
    agency_id: str | None = Field(default=None, description="Tenant scope of the run")
    form_draft_id: str | None = Field(default=None, description="The draft this event concerns")
    timestamp: datetime = Field(default_factory=_utc_now)
    details: dict[str, Any] = Field(default_factory=dict)


def record_event(state: WorkflowState, event_type: str, details: dict) -> None:
    """Append one workflow audit record. Raises on write failure — no silent drops.

    Pulls correlation_id + agency_id + form_draft_id off the run state so every
    event in a run shares the same correlation_id (ADR-0005 §12 traceability).
    Raises ValueError if the state has no correlation_id — an untraceable event
    must never be written. Callers treat a raised exception as fatal for the
    step (fail-closed).

    Raises ValueError for unknown event_type (not in WORKFLOW_EVENT_TYPES) or for
    high-consequence events missing required actor/package keys (actor_id,
    actor_role, package_hash — Codex findings #1 and #2).
    """
    # Guard #1: strict event-type whitelist — typos must never reach the DB.
    if event_type not in WORKFLOW_EVENT_TYPES:
        raise ValueError(
            f"unknown workflow audit event_type {event_type!r} — "
            f"add it to WORKFLOW_EVENT_TYPES or fix the typo"
        )

    # Guard #2: high-consequence events must carry actor identity + package_hash.
    if event_type in _HIGH_CONSEQUENCE_EVENTS:
        missing = [k for k in _REQUIRED_HC_KEYS if not details.get(k)]
        if missing:
            raise ValueError(
                f"high-consequence event {event_type!r} is missing required "
                f"payload keys: {missing!r} — actor identity and package_hash "
                "are mandatory for DCAA reconstruction (ADR-0006 audit contract)"
            )

    # Fail-closed BEFORE touching the DB: an empty correlation_id would make the
    # event unreconstructable, defeating the whole point of this module.
    correlation_id = state.get("correlation_id")
    if not correlation_id:
        raise ValueError(
            f"workflow audit event '{event_type}' has no correlation_id — "
            "every run must mint one at entry (ADR-0005 §12)"
        )

    record = WorkflowAuditRecord(
        correlation_id=correlation_id,
        event_type=event_type,
        agency_id=state.get("agency_id"),
        form_draft_id=state.get("form_draft_id"),
        details=details,
    )

    # Store the timestamp as an ISO string (mirrors the retrieval audit idiom in
    # app/audit/logger.py) so both audit collections are queried the same way.
    doc = record.model_dump()
    doc["timestamp"] = record.timestamp.isoformat()

    try:
        db.get_db()[WORKFLOW_AUDIT_COLLECTION].insert_one(doc)
        log.debug("workflow audit written — %s correlation_id=%s",
                  event_type, record.correlation_id)
    except Exception:
        # Fail-closed: the caller must NOT proceed as if the event were recorded.
        log.error("workflow audit write failed — %s correlation_id=%s",
                  event_type, record.correlation_id, exc_info=True)
        raise

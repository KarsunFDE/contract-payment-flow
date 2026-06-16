"""
router.py — M3 workflow API surface (mount point).

Exposes the multi-agent triage flow (the real start-to-finish entry) and the
resume-after-CO-gate hop, both driven through app.workflow.runner with the
MongoDB checkpointer. A request that escalates to the HITL lane pauses at the CO
gate interrupt; the caller resumes it on the same thread_id with the CO decision.

Stub vs real LLM: the nodes call Bedrock via app.bedrock_client, which returns a
stub when no AWS creds resolve (dev/test) and a real InvokeModel otherwise. When
LANGSMITH_TRACING + LANGSMITH_API_KEY are set, the compiled graph (a LangChain
Runnable) traces every node to LangSmith automatically on invoke.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.workflow import contract_lookup, runner
from app.workflow.mock_sam_gov_client import MockSamGovClient

log = logging.getLogger("ai-orchestrator.workflow.router")

router = APIRouter(prefix="/workflow", tags=["workflow"])

# Phase 1 mock; swap for the live SAM.gov adapter by replacing this assignment
# (mirrors nodes_lookup._sam_gov). Deterministic backend lookup — no LLM, no graph.
_sam_gov = MockSamGovClient()


class TriageRequest(BaseModel):
    """Start a triage run. One of change_request / invoice is required, matching
    item_type. agency_id is the tenant scope (never trusted from a free field)."""
    item_type: str = Field(description='"modification" | "invoice"')
    agency_id: str
    contract_number: str | None = None
    change_request: dict | None = None
    invoice: dict | None = None
    idempotency_key: str | None = None  # money-path dedupe (auto_process lane)


class ResumeRequest(BaseModel):
    """Resume a paused run. `decision` is forwarded to whichever gate paused it:
    the CO gate expects "approved" | "denied"; the consent gate expects an object
    like {"signed": true}."""
    decision: Any


def _render(result: dict, thread_id: str, correlation_id: str) -> dict:
    """Shape a graph result into a JSON-safe response, surfacing any interrupt.

    LangGraph puts the value passed to interrupt() under the "__interrupt__" key
    when a run pauses; we lift it to `interrupt` and report `paused`."""
    interrupts = result.get("__interrupt__") or ()
    interrupt_payload = None
    if interrupts:
        first = interrupts[0]
        interrupt_payload = getattr(first, "value", first)

    return {
        "thread_id": thread_id,
        "correlation_id": correlation_id,
        "paused": bool(interrupts),
        "lane": result.get("lane"),
        "gate_status": result.get("gate_status"),
        "co_decision": result.get("co_decision"),
        "interrupt": interrupt_payload,
    }


@router.get("/_status")
def status() -> dict[str, str]:
    """Liveness probe for the workflow surface (mirrors the retrieval router)."""
    return {"router": "workflow", "status": "ready"}


class ContractLookupRequest(BaseModel):
    """Resolve a contract-of-record for SF-30 field autofill. agency_id is the
    tenant scope — the lookup is filtered by it in the query (ADR-0005 §11), so a
    CO can never autofill from another agency's contract."""
    contract_number: str
    agency_id: str


@router.post("/contract-lookup")
def contract_lookup_endpoint(req: ContractLookupRequest) -> dict:
    """Deterministic contract-of-record lookup for SF-30 autofill (no LLM, no graph).

    Reuses the same find_by_number + mock SAM.gov client the lookup_node runs, so
    the wizard's typeahead autofill and the agent workflow resolve identically.
    Returns {match, static_fields, source_citation}; match != "found" means no
    autofill (not_found / ambiguous)."""
    log.info("workflow/contract-lookup number=%r agency=%r",
             req.contract_number, req.agency_id)
    return contract_lookup.find_by_number(req.contract_number, req.agency_id, _sam_gov)


@router.post("/triage")
def start_triage(req: TriageRequest) -> dict:
    """Start a triage run; returns when a lane completes or the CO gate pauses it."""
    if req.item_type == "modification" and req.change_request is None:
        raise HTTPException(422, "change_request is required for item_type=modification")
    if req.item_type == "invoice" and req.invoice is None:
        raise HTTPException(422, "invoice is required for item_type=invoice")

    correlation_id = str(uuid.uuid4())
    thread_id = correlation_id  # one thread per request; CO resume reuses it
    state: dict[str, Any] = {
        "correlation_id": correlation_id,
        "agency_id": req.agency_id,
        "item_type": req.item_type,
        "contract_number": req.contract_number,
        "change_request": req.change_request or {},
        "invoice": req.invoice or {},
    }
    if req.idempotency_key:
        state["idempotency_key"] = req.idempotency_key

    log.info("workflow/triage start correlation_id=%s item_type=%s", correlation_id, req.item_type)
    result = runner.run_triage_until_gate(state, thread_id)
    return _render(result, thread_id, correlation_id)


@router.post("/triage/{thread_id}/resume")
def resume_triage(thread_id: str, req: ResumeRequest) -> dict:
    """Resume a paused triage run with the CO decision (or consent payload)."""
    log.info("workflow/triage resume thread_id=%s", thread_id)
    result = runner.resume_triage_after_decision(req.decision, thread_id)
    return _render(result, thread_id, thread_id)

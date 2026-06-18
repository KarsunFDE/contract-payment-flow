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

Identity on resume: the gateway MUST assert X-User-Id / X-User-Role / X-Tenant-Id
on every resume request. The endpoint reads them via FastAPI Header() params
(Annotated[str, Header()] — official FastAPI pattern; underscores auto-converted
to hyphens). Missing/blank/"anonymous" values are rejected before the graph is
resumed so the downstream submit node always receives a verified identity.
"""
from __future__ import annotations

import enum
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException
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


class CoDecision(str, enum.Enum):
    """Strict enum for CO gate decisions (approved | denied).

    Inherits str so Pydantic v2 validates the raw JSON string against the members
    (official Pydantic v2 pattern: class Foo(str, enum.Enum)).  Any other value
    causes a 422 Unprocessable Entity before the handler runs.
    """
    approved = "approved"
    denied = "denied"


class ResumeRequest(BaseModel):
    """Resume a paused CO-gate run.

    `decision` is validated against CoDecision ("approved" | "denied").
    Any other value is rejected with HTTP 422 by Pydantic before the handler runs.
    Body-supplied identity fields are intentionally absent — identity is read
    exclusively from gateway-asserted headers (X-User-Id / X-User-Role /
    X-Tenant-Id) so callers cannot self-elevate.
    """
    decision: CoDecision


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
def resume_triage(
    thread_id: str,
    req: ResumeRequest,
    # Gateway-asserted identity headers — required, no default.
    # FastAPI Header() automatically converts underscores → hyphens, so
    # x_user_id reads from the HTTP header X-User-Id, etc.
    # Ref: https://fastapi.tiangolo.com/tutorial/header-params/
    x_user_id: Annotated[str, Header()],
    x_user_role: Annotated[str, Header()],
    x_tenant_id: Annotated[str, Header()],
) -> dict:
    """Resume a paused triage run with the CO decision.

    Identity is read exclusively from gateway-asserted headers — body-supplied
    values are never trusted.  The endpoint:
      1. Rejects missing/blank/"anonymous" identity (HTTP 401/403).
      2. Validates `decision` via CoDecision enum — only "approved"/"denied"
         accepted; anything else is rejected with HTTP 422 by Pydantic before
         this handler even runs.
      3. Reads the checkpointed thread state via graph.get_state() (official
         LangGraph API: StateSnapshot.values — langchain-ai/langgraph types.py)
         to verify the thread exists and the caller's tenant matches.
      4. Patches the verified identity (co_user_id, co_role, agency_id,
         correlation_id) into the graph via graph.update_state() before
         resuming so downstream submit/cancel nodes always receive a confirmed
         CO identity, not body-supplied values.
    """
    from langgraph.checkpoint.mongodb import MongoDBSaver
    from langgraph.types import Command

    from app import config as app_config
    from app.workflow.triage_graph import build_triage_graph

    # --- 1. Identity guard: reject missing/blank/"anonymous" ---
    for header_name, header_value in (
        ("X-User-Id",   x_user_id),
        ("X-User-Role", x_user_role),
        ("X-Tenant-Id", x_tenant_id),
    ):
        if not header_value or not header_value.strip():
            raise HTTPException(
                status_code=401,
                detail=f"{header_name} header is missing or blank",
            )
    if x_user_id.strip().lower() == "anonymous":
        raise HTTPException(
            status_code=403,
            detail="anonymous callers may not resume a workflow",
        )

    actor_id   = x_user_id.strip()
    actor_role = x_user_role.strip()
    agency_id  = x_tenant_id.strip()

    thread_cfg: dict = {"configurable": {"thread_id": thread_id}}

    with MongoDBSaver.from_conn_string(app_config.MONGO_URL, app_config.MONGO_DB) as saver:
        graph = build_triage_graph().compile(checkpointer=saver)

        # --- 2. Verify thread exists; extract agency for mismatch check ---
        # graph.get_state() returns a StateSnapshot NamedTuple; .values is the
        # state dict.  Returns an empty snapshot (values={}) when unknown.
        # Ref: langchain-ai/langgraph types.py — StateSnapshot.values
        snapshot = graph.get_state(thread_cfg)
        if not snapshot or not snapshot.values:
            raise HTTPException(status_code=404, detail=f"thread {thread_id!r} not found")

        thread_state: dict[str, Any] = snapshot.values
        thread_agency = thread_state.get("agency_id")
        if thread_agency and thread_agency != agency_id:
            raise HTTPException(
                status_code=403,
                detail="caller agency does not match thread agency",
            )

        correlation_id: str = thread_state.get("correlation_id") or thread_id

        # --- 3. Patch verified identity into graph state before resuming ---
        # graph.update_state() merges the values dict into the latest checkpoint
        # for this thread using the state reducers (LangGraph persistence API).
        # Ref: https://docs.langchain.com/oss/python/langgraph/use-time-travel
        identity_patch: dict[str, Any] = {
            "co_user_id":     actor_id,
            "co_role":        actor_role,
            "agency_id":      agency_id,
            "correlation_id": correlation_id,
        }
        graph.update_state(thread_cfg, identity_patch)

        log.info(
            "workflow/triage resume thread_id=%s actor=%s role=%s agency=%s decision=%s",
            thread_id, actor_id, actor_role, agency_id, req.decision.value,
        )

        # --- 4. Resume the graph interrupt with the validated decision string ---
        # CoDecision is a str-enum; .value gives the plain string the co_gate
        # interrupt expects ("approved" | "denied").
        result = graph.invoke(Command(resume=req.decision.value), thread_cfg)

    return _render(result, thread_id, correlation_id)

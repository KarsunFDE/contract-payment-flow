"""
nodes_triage.py — the multi-agent triage flow (m3.md Phase 7).

Three stages then a deterministic router:
  anomaly_detector  — FLAGS typed anomalies (detection only, Step 7.1)
  adjudicator       — substantiates each flag against real FAR text (Step 7.2)
  decision_router   — sorts the item into exactly one lane (Step 7.4, default-deny)

then the lane nodes (Step 7.5): auto_process (idempotent + audited), hitl_escalate
(the SF-30 subgraph, wired in triage_graph.py), and return_route (non-terminal).

"Detection is not disposition": no agent self-authorizes — the lane is derived by a
pure policy, never an LLM free-text opinion.
"""
from __future__ import annotations

import logging
from typing import Literal

from langgraph.types import Command
from pydantic import BaseModel, Field

from app.workflow import (
    anomaly_rules,
    auto_approval_policy,
    execution_log,
    mock_executor,
    retrieve_client,
)
from app.workflow.audit_events import record_event
from app.workflow.llm import call_json, LLMOutputError
from app.workflow.triage_state import TriageState

log = logging.getLogger("ai-orchestrator.workflow.triage")


class Adjudication(BaseModel):
    """One flag's verdict against the governing FAR clause + precedent (Step 7.2)."""

    verdict: str = Field(description="substantiated | dismissed")
    far_cite: str = Field(default="")
    precedent_id: str = Field(default="")


def _item_of(state: TriageState) -> dict:
    """The payload under triage — the modification change or the invoice."""
    if state["item_type"] == "modification":
        return state.get("change_request", {})
    return state.get("invoice", {})


# --- Step 7.1: detection -----------------------------------------------------

def anomaly_detector_node(state: TriageState) -> dict:
    """Flag typed anomalies (detection only — no disposition, REQ-AGT-1)."""
    flags = anomaly_rules.scan(_item_of(state), state["item_type"])
    return {"anomaly_flags": flags}


# --- Step 7.2: adjudication --------------------------------------------------

def adjudicator_node(state: TriageState) -> dict:
    """Test each flag against governing FAR + precedent via the M2 retrieval path.

    A flag is substantiated ONLY if a real retrieved clause supports it (G2,
    "grounded or withheld"). If adjudication is unavailable (retrieval/LLM error),
    the flag is kept as substantiated so the item fails safe to escalation —
    an un-adjudicated flag must never clear the auto-process gate.
    """
    results = []
    for flag in state.get("anomaly_flags") or []:
        try:
            clauses = retrieve_client.retrieve_for_state(
                state, flag["detail"], sf30_block=flag.get("far_part", "triage"),
            )
            verdict = call_json(
                prompt=f"Flag: {flag}\nFAR + precedent: {clauses}\n"
                       f"Return JSON: verdict (substantiated|dismissed), far_cite, precedent_id.",
                system="You adjudicate contract/invoice anomalies against FAR. A flag is "
                       "substantiated ONLY if a real, retrieved clause supports it.",
                schema=Adjudication,
            )
            results.append(verdict.data.model_dump() | {"flag_code": flag["code"]})
        except (retrieve_client.RetrieveError, LLMOutputError) as exc:
            log.warning("adjudication unavailable for %s (%s) — keeping substantiated. "
                        "correlation_id=%s", flag["code"], exc, state.get("correlation_id"))
            results.append({
                "flag_code": flag["code"],
                "verdict": "substantiated",  # fail safe -> forces escalation
                "far_cite": flag.get("far_part", ""),
                "precedent_id": "",
                "note": "adjudication_unavailable",
            })
    return {"adjudications": results}


# --- Step 7.4: routing (default-deny) ----------------------------------------

def _is_improper_invoice(state: TriageState) -> bool:
    """An invoice missing FAR 32.905 required elements is improper (7-day return)."""
    if state["item_type"] != "invoice":
        return False
    return bool(_item_of(state).get("missing_elements"))


def _action_of(state: TriageState) -> str:
    """The action under consideration. Defaults to the reserved action for the item
    type, so a missing/unknown action escalates (default-deny)."""
    default = "modification_execution" if state["item_type"] == "modification" else "payment_certification"
    return _item_of(state).get("action", default)


def decision_router_node(
    state: TriageState,
) -> Command[Literal["auto_process", "hitl_escalate", "return_route"]]:
    """Sort the item into one lane. Default-deny: escalate unless auto is proven.

    Records `item_triaged` for EVERY item (REQ-AGT-4), then returns a Command that
    both stores the lane (update=) and routes to it (goto=).
    """
    item = _item_of(state)
    substantiated = [a for a in state.get("adjudications") or [] if a.get("verdict") == "substantiated"]

    if _is_improper_invoice(state):  # FAR 32.905 -> return within 7 days
        lane, rationale = "return_route", "improper invoice (FAR 32.905)"
    elif auto_approval_policy.may_auto_process(
        _action_of(state),
        reversible=item.get("reversible", False),
        within_delegated_authority=item.get("within_delegated_authority", False),
        amount=item.get("amount", 0),
        threshold=item.get("threshold", 0),
        substantiated_flags=len(substantiated),
    ):
        lane = "auto_process"
        rationale = "policy-clean: reversible, delegated, under threshold, no substantiated flags"
    else:  # the default lane
        lane = "hitl_escalate"
        rationale = (f"escalated: {len(substantiated)} substantiated flag(s)"
                     if substantiated else "escalated: auto-approval policy not satisfied")

    record_event(state, "item_triaged", {"lane": lane, "rationale": rationale})
    return Command(goto=lane, update={"lane": lane, "disposition_rationale": rationale})


# --- Step 7.5: lane nodes ----------------------------------------------------

def auto_process_node(state: TriageState) -> dict:
    """Auto lane: idempotent mock execution + mandatory audit (REQ-AGT-2/4).

    A replayed idempotency_key is a no-op (no double-pay).
    """
    idempotency_key = state.get("idempotency_key")
    # No idempotency key means we cannot detect a replay, so we must NOT auto-execute
    # the money path. Fail closed (report for review) instead of risking a double
    # process or crashing the graph with a KeyError on the missing key.
    if not idempotency_key:
        log.warning("auto_process reached without an idempotency_key — refusing to "
                    "auto-execute. correlation_id=%s", state.get("correlation_id"))
        return {"gate_status": "MISSING_IDEMPOTENCY_KEY_AWAITING_REVIEW"}

    if execution_log.already_processed(idempotency_key):
        return {"gate_status": "ALREADY_PROCESSED"}  # replay -> no double-pay

    mock_executor.process(state.get("form_draft_id", ""), idempotency_key)
    # Ordering caveat for a REAL executor: the side effect above runs before this
    # audit write, and record_event is fail-closed (it raises if the write fails). If
    # a real side effect succeeded but the audit then failed, a later replay would
    # short-circuit at already_processed() above and never re-record the audit. The
    # mock is in-memory so this is harmless today; a real executor needs execute +
    # audit to be atomic (transactional outbox) — see debt D3 (Item 2).
    record_event(state, "auto_processed",
                 {"lane": "auto_process", "rationale": state.get("disposition_rationale", "")})
    return {"gate_status": "AUTO_PROCESSED"}


def return_route_node(state: TriageState) -> dict:
    """Return/route/hold lane (non-terminal): return-to-vendor, more-info, COR<->CO."""
    return {"gate_status": "RETURNED_FOR_ROUTING"}

"""
nodes_triage.py — Person B: anomaly-detector + adjudicator + decision-router +
lane nodes (m3.md Phase 7 — tasks B3-B5).

Detection is not disposition: the detector only FLAGS (deterministic rules +
an LLM pass only for scope / unallowable-cost judgment), the adjudicator only
SUBSTANTIATES flags against retrieved FAR text (G2 grounded-or-withheld), and
the router — policy + pure helpers — derives the lane. No agent self-authorizes
(REQ-AGT-1/2); the lane is never an LLM free-text opinion.

Fail-closed bias: an adjudication that cannot complete (retrieval down, judge
output rejected) is recorded as `error_failed_closed` and COUNTS as
substantiated for routing — an unverifiable flag escalates, it never clears
the auto lane. The router's `item_triaged` audit write is mandatory and raises
on failure (Phase 6 — a triage decision without a trail must not proceed).

Invoice payloads ride in `change_request` (the frozen TriageState has no
separate invoice channel); `item_type` discriminates.
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
    llm,
    mock_executor,
    retrieve_client,
)
from app.workflow.audit_events import record_event
from app.workflow.triage_state import TriageState

log = logging.getLogger("ai-orchestrator.workflow.triage")


# --------------------------------------------------------------------------
# B3 — anomaly detector + adjudicator
# --------------------------------------------------------------------------

class ScopeVerdict(BaseModel):
    """LLM judgment for the out-of-scope check (modifications only)."""

    out_of_scope: bool
    rationale: str = ""


_SCOPE_SYSTEM = (
    "You judge whether a proposed contract modification is OUT OF SCOPE of the "
    "original contract (a cardinal change). Detection only — you do not decide "
    'disposition. Return ONLY JSON: {"out_of_scope": bool, "rationale": str}.'
)


def anomaly_detector_node(state: TriageState) -> dict:
    """Flag typed anomalies. Detection only — no disposition (REQ-AGT-1).

    Deterministic rules first (anomaly_rules.scan); then an LLM pass ONLY for
    the scope judgment on modifications. The LLM pass degrades silently when
    Bedrock is stubbed/unavailable — losing it only loses a flag, and the
    router's default-deny means modifications escalate regardless.
    """
    item = state.get("change_request") or {}
    item_type = state.get("item_type", "modification")

    flags = anomaly_rules.scan(item, item_type)

    if item_type == "modification" and item.get("scope"):
        try:
            result = llm.call_json(
                f"Original scope summary: {item.get('original_scope', '(not provided)')}\n"
                f"Proposed change: {item.get('scope')}",
                schema=ScopeVerdict,
                system=_SCOPE_SYSTEM,
            )
            if result.data.out_of_scope:
                flags.append(
                    {
                        "code": "OUT_OF_SCOPE_CHANGE",
                        "detail": result.data.rationale,
                        "far_part": "43.201",
                        "severity": "high",
                    }
                )
        except llm.LLMOutputError as exc:
            log.warning("scope LLM pass unavailable — deterministic flags only: %s", exc)

    return {"anomaly_flags": flags}


class Adjudication(BaseModel):
    """The closed verdict shape the adjudicator judge must return."""

    verdict: Literal["substantiated", "dismissed"]
    far_cite: str | None = None
    precedent_id: str | None = None
    rationale: str = ""


_ADJUDICATE_SYSTEM = (
    "You adjudicate contract/invoice anomalies against FAR. A flag is "
    "substantiated ONLY if a real, retrieved clause supports it — otherwise "
    "dismissed. Return ONLY JSON: "
    '{"verdict": "substantiated"|"dismissed", "far_cite": str|null, '
    '"precedent_id": str|null, "rationale": str}.'
)


def _sf30_tag(far_part: str) -> str:
    """Squeeze a FAR part into the retrieval request's sf30_block shape
    (audit tag of what triggered the retrieval, pattern [A-Za-z0-9.-]{1,16})."""
    cleaned = "".join(ch for ch in far_part if ch.isalnum() or ch in ".-")
    return cleaned[:16] or "triage"


def adjudicator_node(state: TriageState) -> dict:
    """Test each flag against governing FAR + precedent (M2 retrieval, ADR-0005).

    Grounded-or-withheld (G2): substantiated requires a retrieved clause. An
    adjudication that cannot complete fails CLOSED — verdict
    `error_failed_closed`, which the router counts as substantiated.
    """
    agency_id, user_id, role = retrieve_client.identity_for(state)
    results = []

    for flag in state.get("anomaly_flags") or []:
        failed_closed = {
            "flag_code": flag["code"],
            "verdict": "error_failed_closed",
            "far_cite": flag.get("far_part"),
            "precedent_id": None,
            "rationale": "",
        }
        try:
            clauses = retrieve_client.retrieve(
                f"FAR {flag.get('far_part', '')}: {flag.get('detail', '')}",
                sf30_block=_sf30_tag(flag.get("far_part", "")),
                agency_id=agency_id,
                user_id=user_id,
                role=role,
                correlation_id=state.get("correlation_id"),
                contract_id=state.get("contract_number"),
            )
        except (retrieve_client.RetrievalUnavailable, ValueError) as exc:
            log.warning("adjudication retrieval failed closed — %s: %s", flag["code"], exc)
            failed_closed["rationale"] = f"retrieval unavailable: {exc}"
            results.append(failed_closed)
            continue

        clause_text = "\n\n".join(c.get("chunk_text", "") for c in clauses)
        try:
            verdict = llm.call_json(
                f"Flag: {flag}\nFAR + precedent:\n{clause_text}",
                schema=Adjudication,
                system=_ADJUDICATE_SYSTEM,
            )
        except llm.LLMOutputError as exc:
            log.warning("adjudication judge failed closed — %s: %s", flag["code"], exc)
            failed_closed["rationale"] = f"judge output rejected: {exc}"
            results.append(failed_closed)
            continue

        results.append(
            {
                "flag_code": flag["code"],
                "verdict": verdict.data.verdict,
                "far_cite": verdict.data.far_cite,
                "precedent_id": verdict.data.precedent_id,
                "rationale": verdict.data.rationale,
            }
        )

    return {"adjudications": results}


# --------------------------------------------------------------------------
# B4 — decision router (three lanes, Command routing, default-deny)
# --------------------------------------------------------------------------

def _action_of(state: TriageState) -> str:
    """The action the auto lane would take for this item.

    Modification execution is FAR 43.102 CO-only (reserved). Routine invoice
    processing (intake + schedule, pre-certification) is the reversible action
    the auto lane may perform; payment CERTIFICATION stays reserved.
    """
    if state.get("item_type") == "invoice":
        return "invoice_processing"
    return "modification_execution"


def _is_reversible(state: TriageState) -> bool:
    """Invoice processing is reversible until certification; executing a
    modification is not. Unknown item types count as irreversible (default-deny)."""
    return state.get("item_type") == "invoice"


def _amount(state: TriageState) -> float:
    item = state.get("change_request") or {}
    value = item.get("amount", item.get("funding_delta", 0.0))
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return float("inf")  # unparseable amount -> over any threshold (deny)


def _within_delegated_authority(state: TriageState) -> bool:
    """Delegated-authority attestation must be threaded in by the intake layer;
    absent means False (default-deny)."""
    return bool((state.get("change_request") or {}).get("within_delegated_authority"))


def _substantiated(adjudications: list[dict]) -> list[dict]:
    """Anything not affirmatively dismissed counts (fail-closed: errors stand)."""
    return [a for a in adjudications if a.get("verdict") != "dismissed"]


def _escalation_reason(state: TriageState, substantiated: list[dict]) -> str:
    if substantiated:
        codes = ", ".join(a.get("flag_code", "?") for a in substantiated)
        return f"substantiated/unresolved flags: {codes}"
    if _action_of(state) in auto_approval_policy.RESERVED_ACTIONS:
        return f"reserved action '{_action_of(state)}' — human authority required"
    return "auto-approval conditions not met (default-deny)"


def decision_router_node(
    state: TriageState,
) -> Command[Literal["auto_process", "hitl_escalate", "return_route"]]:
    """Sort the item into one lane. Default-deny: escalate unless auto is proven.

    Writes the mandatory `item_triaged` audit record (every item, fail-closed —
    an audit failure raises and stops the run, Phase 6) and returns a Command
    that both records the lane (update=) and routes to it (goto=).
    """
    adjudications = state.get("adjudications") or []
    substantiated = _substantiated(adjudications)

    # Improper invoice (FAR 32.905) -> 7-day return, before any other lane.
    improper = state.get("item_type") == "invoice" and any(
        f.get("code") == "INVOICE_MISSING_FAR_32_905_ELEMENTS"
        for f in state.get("anomaly_flags") or []
    )
    if improper:
        lane, rationale = "return_route", "improper invoice (FAR 32.905) — return within 7 days"
    elif auto_approval_policy.may_auto_process(
        _action_of(state),
        reversible=_is_reversible(state),
        within_delegated_authority=_within_delegated_authority(state),
        amount=_amount(state),
        threshold=auto_approval_policy.AUTO_PROCESS_THRESHOLD_USD,
        substantiated_flags=len(substantiated),
    ):
        lane, rationale = "auto_process", (
            "policy-clean: reversible, delegated, under threshold, "
            "no substantiated flags"
        )
    else:
        lane, rationale = "hitl_escalate", _escalation_reason(state, substantiated)

    # Mandatory, fail-closed: every item leaves a triage trail (REQ-AGT-4).
    record_event(
        state,
        "item_triaged",
        {
            "lane": lane,
            "rationale": rationale,
            "item_type": state.get("item_type"),
            "flag_codes": [f.get("code") for f in state.get("anomaly_flags") or []],
            "substantiated_count": len(substantiated),
        },
    )

    return Command(goto=lane, update={"lane": lane, "disposition_rationale": rationale})


# --------------------------------------------------------------------------
# B5 — lane nodes
# --------------------------------------------------------------------------

def auto_process_node(state: TriageState) -> dict:
    """Auto lane: idempotent mock execution + mandatory audit (REQ-AGT-2/4).

    Guards on idempotency_key — a replayed item is a no-op (no double-pay).
    The ledger mark happens BEFORE the mock action (at-most-once: a crash
    fails toward no-pay, never double-pay); the audit write raises on failure.
    """
    idempotency_key = state.get("idempotency_key", "")
    if execution_log.already_processed(idempotency_key):
        log.info("replay detected — no-op (idempotency_key=%s)", idempotency_key)
        return {"gate_status": "ALREADY_PROCESSED"}

    item_ref = (
        state.get("form_draft_id")
        or state.get("contract_number")
        or state.get("correlation_id", "")
    )
    receipt = mock_executor.process(
        item_ref, idempotency_key, state.get("correlation_id", "")
    )
    record_event(
        state,
        "auto_processed",
        {
            "lane": "auto_process",
            "rationale": state.get("disposition_rationale", ""),
            "receipt": receipt,
        },
    )
    return {"gate_status": "AUTO_PROCESSED"}


def return_route_node(state: TriageState) -> dict:
    """Return/route/hold lane (non-terminal for the item): the item goes back
    to the vendor/COR with the disposition rationale; nothing is executed.
    The router already audited the lane decision (item_triaged)."""
    return {"gate_status": "RETURNED_FOR_CORRECTION"}

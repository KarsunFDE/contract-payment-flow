"""
nodes_gate.py — Person A: CO hard gate + bilateral consent + CO-only submit
(m3.md Phases 4-5, Steps 4.1-4.3, 5.1-5.3).

Three interrupt-backed pause points:
  co_gate_node      — hard CO gate (approve/deny). Every run stops here.
  consent_gate_node — bilateral only; blocks until contractor signs Block 15.
  submit_node       — CO-triggered DRAFT → MODIFICATION_REQUEST (irreversible).
  supersede_node    — CO deny path; marks the package cancelled + audits.

Routing:
  co_gate → route_after_co_gate →  "supersede"   (denied)
                                    "consent_gate" (approved, bilateral)
                                    "submit"       (approved, unilateral)
  consent_gate → route_after_consent_gate → "submit" (consent recorded)
                                             END      (consent pending)

Audit: co_decision, contractor_consent_recorded, package_superseded,
       modification_submitted — all synchronous + fail-closed (ADR-0006 Note 3).

Flag (finding #10): real CO-role + agency enforcement lives in the Java service.
This node fails closed on HTTP errors but cannot enforce CO identity itself.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.workflow import modification_client
from app.workflow.audit_events import record_event
from app.workflow.state import WorkflowState


def co_gate_node(state: WorkflowState) -> dict:
    """Hard CO gate — pauses (interrupt) until the CO approves or denies."""
    decision = interrupt({
        "populated_fields":       state.get("populated_fields"),
        "block_14_draft":         state.get("block_14_draft"),
        "gate_status":            state.get("gate_status"),
        "bilateral":              state.get("modification_bilateral"),
        "block13_classification": state.get("block13_classification"),
    })
    record_event(state, "co_decision", {
        "decision":     decision,
        "form_draft_id": state.get("form_draft_id"),
    })
    return {"co_decision": decision}


def route_after_co_gate(state: WorkflowState) -> str:
    """Deny → supersede. Approve bilateral → consent_gate. Approve unilateral → submit."""
    if state.get("co_decision") == "denied":
        return "supersede"
    if state.get("modification_bilateral"):
        return "consent_gate"
    return "submit"


def consent_gate_node(state: WorkflowState) -> dict:
    """Bilateral only — pauses until contractor consent (Block 15) is recorded."""
    consent = interrupt({
        "awaiting": "contractor_consent",
        "draft_id": state.get("form_draft_id"),
    })
    if consent.get("signed") is True:
        record_event(state, "contractor_consent_recorded", {
            "form_draft_id": state.get("form_draft_id"),
        })
        return {"contractor_consent": "recorded"}
    return {"contractor_consent": "pending", "gate_status": "AWAITING_CONTRACTOR_CONSENT"}


def route_after_consent_gate(state: WorkflowState) -> str:
    return "submit" if state.get("contractor_consent") == "recorded" else END


def supersede_node(state: WorkflowState) -> dict:
    """On CO deny: mark the package superseded + audit. Terminal."""
    draft_id = state.get("form_draft_id")
    if draft_id:
        modification_client.cancel_draft(draft_id)
    record_event(state, "package_superseded", {
        "co_decision":   state.get("co_decision"),
        "form_draft_id": draft_id,
    })
    return {"co_execution": "aborted"}


def submit_node(state: WorkflowState) -> dict:
    """CO-triggered submit (DRAFT → MODIFICATION_REQUEST). Fail-closed, audit synchronous."""
    draft_id = state.get("form_draft_id")
    consent_recorded = state.get("contractor_consent") == "recorded"
    modification_client.publish(draft_id=draft_id, consent_recorded=consent_recorded)
    record_event(state, "modification_submitted", {
        "form_draft_id":      draft_id,
        "contractor_consent": state.get("contractor_consent"),
    })
    return {"gate_status": "SUBMITTED", "co_execution": "executed"}


def register(builder: StateGraph) -> None:
    """Add gate/consent/submit/supersede nodes + conditional routing edges."""
    builder.add_node("co_gate",     co_gate_node)
    builder.add_node("consent_gate", consent_gate_node)
    builder.add_node("submit",      submit_node)
    builder.add_node("supersede",   supersede_node)

    builder.add_conditional_edges("co_gate", route_after_co_gate, {
        "supersede":    "supersede",
        "consent_gate": "consent_gate",
        "submit":       "submit",
    })
    builder.add_conditional_edges("consent_gate", route_after_consent_gate, {
        "submit": "submit",
        END:      END,
    })
    builder.add_edge("submit",    END)
    builder.add_edge("supersede", END)

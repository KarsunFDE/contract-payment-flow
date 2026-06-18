"""
nodes_form.py — Person A: form-fill tool layer (m3.md Phase 3, Step 3.2).

assemble_form_node writes the looked-up static blocks + the AI-drafted Block 14
rationale into the ContractModification DRAFT via the allow-listed form_tools.
There is NO submit call here — submission is a CO-only UI action (ADR-0006
§"Form-Fill Tool Layer"). The DRAFT remains DRAFT until the CO gate approves.

Security hardening (Codex PR #9 findings):
  - mod_type + far_authority are sourced ONLY from state["block13_classification"]
    (the classifier's output); they are NEVER re-derived from modification_bilateral.
  - Identity fields (co_user_id, co_role, agency_id) are read ONLY from verified
    workflow state, never from the change_request body.
  - Both sources fail closed when missing or carrying an unknown/unclassified value.
"""
from __future__ import annotations

import logging

from langgraph.graph import StateGraph

from app.workflow import form_tools
from app.workflow.audit_events import record_event
from app.workflow.nodes_lookup import BLOCKING_STATUSES, is_blocking
from app.workflow.state import WorkflowState

log = logging.getLogger("ai-orchestrator.workflow.form")

# mod_types that are fully classified and safe to write into the draft.
_VALID_MOD_TYPES: frozenset[str] = frozenset({
    "unilateral_change_order",
    "unilateral_admin",
    "bilateral_supplemental",
})


def assemble_form_node(state: WorkflowState) -> dict:
    """Write the looked-up blocks + drafted rationale into the DRAFT record.

    Fails closed (routes to CO review) when:
      - block13_classification is absent or carries an unknown/unclassified mod_type
      - verified identity (co_user_id, co_role, agency_id) is absent from state
    """
    # --- Identity: verified state only, never the request body ---
    co_user_id = state.get("co_user_id")
    co_role = state.get("co_role")
    agency_id = state.get("agency_id")
    if not co_user_id or not co_role or not agency_id:
        log.warning(
            "assemble_form_node: verified identity missing from state "
            "(co_user_id=%r, co_role=%r, agency_id=%r) — routing to CO review. "
            "correlation_id=%s",
            co_user_id, co_role, agency_id, state.get("correlation_id"),
        )
        return {"gate_status": "CONTRACT_NOT_FOUND_AWAITING_CO_REVIEW"}

    # --- Classification: must come from the classifier, never re-derived ---
    classification = state.get("block13_classification") or {}
    mod_type = classification.get("mod_type", "unknown")
    far_authority = classification.get("far_basis", "")

    if mod_type not in _VALID_MOD_TYPES:
        log.warning(
            "assemble_form_node: mod_type %r is not a valid classified type — "
            "routing to CO review. correlation_id=%s",
            mod_type, state.get("correlation_id"),
        )
        return {"gate_status": "CLASSIFICATION_MISSING_AWAITING_CO_REVIEW"}

    draft_id = state["form_draft_id"]
    fields = state.get("populated_fields", {})

    form_tools.set_modification_basics(
        draft_id=draft_id,
        contract_number=state["contract_number"],
        modification_number=fields.get("2", {}).get("value", ""),
        mod_type=mod_type,
        far_authority=far_authority,
        effective_date=fields.get("3", {}).get("value", ""),
        actor_id=co_user_id,
        actor_role=co_role,
        agency_id=agency_id,
        correlation_id=state.get("correlation_id", ""),
    )
    form_tools.set_block_14_rationale(
        draft_id=draft_id,
        narrative=state.get("block_14_draft", ""),
        price_cost_impact=state.get("change_request", {}).get("price_impact", ""),
        funding_citation=state.get("change_request", {}).get("funding_citation", ""),
        actor_id=co_user_id,
        actor_role=co_role,
        agency_id=agency_id,
        correlation_id=state.get("correlation_id", ""),
    )
    record_event(state, "form_field_written", {"draft_id": draft_id})
    return {"co_decision": "pending"}


def register(builder: StateGraph) -> None:
    """Add the assemble node + the bridge to the CO gate."""
    builder.add_node("assemble", assemble_form_node)
    builder.add_edge("assemble", "co_gate")

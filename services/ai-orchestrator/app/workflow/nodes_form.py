"""
nodes_form.py — Person A: form-fill tool layer (m3.md Phase 3, Step 3.2).

assemble_form_node writes the looked-up static blocks + the AI-drafted Block 14
rationale into the ContractModification DRAFT via the allow-listed form_tools.
There is NO submit call here — submission is a CO-only UI action (ADR-0006
§"Form-Fill Tool Layer"). The DRAFT remains DRAFT until the CO gate approves.
"""
from __future__ import annotations

from langgraph.graph import StateGraph

from app.workflow import form_tools
from app.workflow.audit_events import record_event
from app.workflow.state import WorkflowState


def assemble_form_node(state: WorkflowState) -> dict:
    """Write the looked-up blocks + drafted rationale into the DRAFT record."""
    draft_id = state["form_draft_id"]
    fields = state.get("populated_fields", {})

    form_tools.set_modification_basics(
        draft_id=draft_id,
        contract_number=state["contract_number"],
        modification_number=fields.get("2", {}).get("value", ""),
        mod_type=(
            "bilateral_supplemental" if state.get("modification_bilateral")
            else "unilateral_admin"
        ),
        far_authority=fields.get("13", {}).get("value", ""),
        effective_date=fields.get("3", {}).get("value", ""),
        agency_id=state.get("agency_id", ""),
    )
    form_tools.set_block_14_rationale(
        draft_id=draft_id,
        narrative=state.get("block_14_draft", ""),
        price_cost_impact=state.get("change_request", {}).get("price_impact", ""),
        funding_citation=state.get("change_request", {}).get("funding_citation", ""),
    )
    record_event(state, "form_field_written", {"draft_id": draft_id})
    return {"co_decision": "pending"}


def register(builder: StateGraph) -> None:
    """Add the assemble node + the bridge to the CO gate."""
    builder.add_node("assemble", assemble_form_node)
    builder.add_edge("assemble", "co_gate")

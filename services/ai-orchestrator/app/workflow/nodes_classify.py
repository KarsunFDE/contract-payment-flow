"""
nodes_classify.py — Block 13 classification + consent derivation
(m3.md Steps 2.1, 2.1b).

classify_modification_node lets the LLM PROPOSE the Block 13 path/modType (grounded
in retrieved FAR text, validated through app.workflow.llm.call_json) and records the
provenance of that call for the CO gate (Issue 4). derive_consent_node then maps the
modType to FAR 43.103 DETERMINISTICALLY (far_rules) — the model never decides consent.

Both fail closed: a retrieval/LLM failure or an unmapped modType flags the package for
CO review rather than guessing.
"""
from __future__ import annotations

import logging

from langgraph.graph import StateGraph
from pydantic import BaseModel, Field

from app.workflow import far_rules, retrieve_client
from app.workflow.llm import call_json, LLMOutputError
from app.workflow.state import WorkflowState

log = logging.getLogger("ai-orchestrator.workflow.classify")

# The closed set of modTypes the classifier may propose. far_rules maps each to a
# FAR 43.103 consent rule; "unknown" routes to CO review (never assumed unilateral).
_MOD_TYPES = "unilateral_change_order|unilateral_admin|bilateral_supplemental|unknown"


class Block13Proposal(BaseModel):
    """The LLM's PROPOSED Block 13 classification (not the final decision).

    Consent is NOT a field here — it is derived server-side in derive_consent_node.
    """

    block13_path: str = Field(description="13A | 13B | 13C | 13D")
    mod_type: str = Field(default="unknown", description=_MOD_TYPES)
    far_basis: str = Field(default="", description="e.g. '43.103(a)'")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


def classify_modification_node(state: WorkflowState) -> dict:
    """Block 13: classify the modification type against FAR 43.103 (Step 2.1).

    The LLM proposes; we attach the provenance (retrieved clause ids, model +
    version, confidence) so the CO can verify the call at the gate. On any
    failure the package is flagged unclassified for CO review (fail-closed).
    """
    change = state["change_request"]

    try:
        # Deterministic retrieval of the governing FAR text; keep the clause ids
        # as provenance so the CO sees exactly what grounded the classification.
        clauses = retrieve_client.retrieve_for_state(state, change["scope"], sf30_block="13")
        result = call_json(
            prompt=f"Change: {change}\nFAR context: {clauses}\n"
                   f"Return JSON: block13_path (13A|13B|13C|13D), mod_type "
                   f"({_MOD_TYPES}), far_basis (e.g. '43.103(a)'), confidence (0-1).",
            system="You classify post-award contract modifications under FAR 43.103. "
                   "You classify only; you do not decide whether consent is required.",
            schema=Block13Proposal,
        )
    except (retrieve_client.RetrieveError, LLMOutputError) as exc:
        log.warning("classify failed (%s) — flagging for CO review. correlation_id=%s",
                    exc, state.get("correlation_id"))
        return {
            "block13_classification": {"mod_type": "unknown", "confidence": 0.0},
            "gate_status": "BLOCK13_UNCLASSIFIED_AWAITING_CO_REVIEW",
        }

    proposed = result.data
    classification = {
        "block13_path": proposed.block13_path,
        "mod_type": proposed.mod_type,
        "far_basis": proposed.far_basis,
        "confidence": proposed.confidence,
        # --- provenance surfaced at the CO gate (Issue 4) ---
        "retrieved_clause_ids": [c.get("chunk_id") for c in clauses],
        "model": result.model,
        "model_version": result.model_version,
    }
    return {"block13_classification": classification}


def derive_consent_node(state: WorkflowState) -> dict:
    """Map the classified modType -> consent rule (FAR 43.103), no LLM (Step 2.1b).

    An unmapped / "unknown" modType does NOT fall through to unilateral: it fails
    safe to consent-required AND flags the package for CO review.
    """
    mod_type = state["block13_classification"]["mod_type"]
    required = far_rules.consent_required_for(mod_type)

    if required is None:  # unmapped / "unknown"
        return {
            "modification_bilateral": True,  # fail safe: treat as needing consent
            "gate_status": "BLOCK13_UNCLASSIFIED_AWAITING_CO_REVIEW",
        }
    return {"modification_bilateral": required}  # True = bilateral (consent required)


def register(builder: StateGraph) -> None:
    """Add the classify + derive_consent nodes and the bridge to retrieval."""
    builder.add_node("classify", classify_modification_node)
    builder.add_node("derive_consent", derive_consent_node)

    builder.add_edge("classify", "derive_consent")
    builder.add_edge("derive_consent", "retrieve")  # bridge to the retrieval slice

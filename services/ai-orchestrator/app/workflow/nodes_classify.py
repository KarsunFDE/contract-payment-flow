"""
nodes_classify.py — Person B: Block 13 classification + consent derivation
(m3.md Steps 2.1, 2.1b — task B1).

The classifier PROPOSES the Block 13 path/modType via `llm.call_json` (grounded
in retrieved FAR 43.103 text) and captures full provenance for the CO gate
(Issue 4). It never decides consent — `derive_consent_node` maps the modType to
FAR 43.103 deterministically (far_rules.py, no LLM), and an unknown/unmapped
modType fails safe to consent-required + CO review.

Fail-soft contract: classification failure (retrieval down, stub Bedrock,
non-schema model output) NEVER raises out of the node — it returns the
"unknown" classification + BLOCK13_UNCLASSIFIED_AWAITING_CO_REVIEW so the run
surfaces at the CO gate instead of crashing the graph (the graph stays total).
The register() edges are frozen.
"""
from __future__ import annotations

import logging

from langgraph.graph import StateGraph
from pydantic import BaseModel, Field

from app.workflow import far_rules, llm, prompt_guard, retrieve_client
from app.workflow.state import WorkflowState

log = logging.getLogger("ai-orchestrator.workflow.classify")


class Block13Proposal(BaseModel):
    """The closed shape the classifier must return (schema-validated JSON)."""

    block13_path: str = Field(pattern=r"^13[A-E]$")
    mod_type: str
    far_basis: str
    confidence: float = Field(ge=0.0, le=1.0)


_CLASSIFY_SYSTEM = (
    "You classify post-award contract modifications under FAR 43.103. "
    "You classify only; you do not decide whether consent is required. "
    "Return ONLY a JSON object with keys block13_path, mod_type, far_basis, "
    "confidence." + prompt_guard.DATA_GUARD
)


def _unclassified(reason: str, clause_ids: list[str]) -> dict:
    """Fail-safe partial update: unknown modType + CO-review gate status."""
    return {
        "block13_classification": {
            "block13_path": None,
            "mod_type": "unknown",
            "far_basis": None,
            "confidence": 0.0,
            "retrieved_clause_ids": clause_ids,
            "model": None,
            "model_version": None,
            "error": reason,
        },
        "gate_status": "BLOCK13_UNCLASSIFIED_AWAITING_CO_REVIEW",
    }


def classify_modification_node(state: WorkflowState) -> dict:
    """Block 13: classify the modification type against FAR 43.103.

    The LLM proposes (block13_path, mod_type, far_basis, confidence). It does
    NOT decide consent — that is derive_consent_node (deterministic). Every
    input that drove the call is captured as provenance (Issue 4): retrieved
    clause ids + model + model version + confidence.
    """
    change = state.get("change_request") or {}
    scope = str(change.get("scope", ""))

    # Ground the classifier in the real FAR text; keep clause ids for provenance.
    try:
        agency_id, user_id, role = retrieve_client.identity_for(state)
        clauses = retrieve_client.retrieve(
            f"FAR 43.103 modification type for: {scope}",
            sf30_block="13",
            agency_id=agency_id,
            user_id=user_id,
            role=role,
            correlation_id=state.get("correlation_id"),
            contract_id=state.get("contract_number"),
        )
    except (retrieve_client.RetrievalUnavailable, ValueError) as exc:
        # Grounded-or-withheld (G2): no FAR context -> do not classify ungrounded.
        log.warning("classify retrieval unavailable — failing to CO review: %s", exc)
        return _unclassified(f"retrieval unavailable: {exc}", [])

    clause_ids = [c.get("chunk_id", "") for c in clauses]
    clause_text = "\n\n".join(c.get("chunk_text", "") for c in clauses)

    mod_types = " | ".join(far_rules.KNOWN_MOD_TYPES)
    # Untrusted text (CO-typed change, corpus chunks) rides in data envelopes —
    # never as bare prompt text (review finding 1).
    prompt = (
        f"{prompt_guard.data_block('change_request', change)}\n"
        f"{prompt_guard.data_block('far_context', clause_text)}\n\n"
        f"Classify the change_request against the far_context. block13_path is "
        f"one of 13A|13B|13C|13D|13E; mod_type is one of {mod_types}; far_basis "
        f"like '43.103(a)'; confidence 0-1."
    )

    try:
        result = llm.call_json(prompt, schema=Block13Proposal, system=_CLASSIFY_SYSTEM)
    except llm.LLMOutputError as exc:
        log.warning("classifier output rejected — failing to CO review: %s", exc)
        return _unclassified(f"classifier output rejected: {exc}", clause_ids)

    proposal = result.data
    return {
        "block13_classification": {
            "block13_path": proposal.block13_path,
            "mod_type": proposal.mod_type,
            "far_basis": proposal.far_basis,
            "confidence": proposal.confidence,
            # --- provenance surfaced at the CO gate (Issue 4) ---
            "retrieved_clause_ids": clause_ids,
            "model": result.model,
            "model_version": result.model_version,
        }
    }


def derive_consent_node(state: WorkflowState) -> dict:
    """Map the classified modType -> consent rule (FAR 43.103). Unknown -> CO review.

    Pure rule lookup — no LLM in this path. The agent never writes
    contractorConsentRequired; the write path re-derives it from modType
    (ADR-0006 §"Bilateral vs Unilateral").
    """
    classification = state.get("block13_classification") or {}
    mod_type = classification.get("mod_type", "unknown")
    required = far_rules.consent_required_for(mod_type)

    if required is None:  # unmapped / "unknown"
        return {
            "modification_bilateral": True,  # fail safe: needs consent
            "gate_status": "BLOCK13_UNCLASSIFIED_AWAITING_CO_REVIEW",
        }
    return {"modification_bilateral": required}  # True = bilateral


def register(builder: StateGraph) -> None:
    """Add the classify + derive_consent nodes and the bridge to retrieval."""
    builder.add_node("classify", classify_modification_node)
    builder.add_node("derive_consent", derive_consent_node)

    builder.add_edge("classify", "derive_consent")
    builder.add_edge("derive_consent", "retrieve")  # bridge to the retrieval slice

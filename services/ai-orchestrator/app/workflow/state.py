"""
state.py — shared LangGraph state for the M3 SF-30 modification workflow.

This is THE state contract every inner-workflow node reads from and writes to
(m3.md Phase 0, Step 0.1). Frozen after the Foundation commit — changing a field
here is a shared-contract change both workstream owners review.

Field set = ADR-0006 "State Schema Additions" + the Block 13/14 fields added in
m3.md Steps 2.1-2.4, reconciled with the ADR-0005 §1 pipeline-state requirements:
every request carries a `correlation_id` (threads through all nodes AND all audit
records — ADR-0005 §7/§12) and an `agency_id` tenant scope (ADR-0005 §11).

LangGraph passes one TypedDict state dict between nodes; declaring it with
`TypedDict` is the official LangGraph v1.0 pattern.
  https://docs.langchain.com/oss/python/langgraph/graph-api
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from typing_extensions import TypedDict


class WorkflowState(TypedDict, total=False):
    """State threaded through the inner SF-30 workflow.

    `total=False` so each node may return only the keys it changes (LangGraph
    merges them) and a run can start from a partial input.
    """

    # --- request identity (ADR-0005 §1/§7/§11/§12) ---
    correlation_id: str           # UUID minted at request entry; threads every
                                  # node and every workflow_audit record
    agency_id: str                # tenant scope — lookup + retrieval filter on it,
                                  # never trusted from the request body

    # --- CO input ---
    contract_number: str          # base contract the CO entered, e.g. "GS-35F-0001V"
    change_request: dict          # CO-stated change: funding delta, PoP, scope

    # --- filled by the workflow ---
    contract_record: dict         # the looked-up record + source-of-record citation
    populated_fields: dict        # SF-30 block -> {value, source_citation}
    form_draft_id: str            # the draft ContractModification being written

    # --- classification (Block 13) + provenance ---
    block13_classification: dict  # 13A-13E path, modType, FAR basis, retrieved
                                  # clause ids, model+version, confidence

    # --- Block 14 grounded sub-pipeline (ADR-0005 §4) ---
    retrieved_chunks: list        # ADR-0005 §1 names this `documents`; same data
    confidence: float             # aggregate LLM-as-judge score (ADR-0005 §4)
    draft_model_tier: str         # "haiku" (default) | "sonnet" — set to "sonnet" by
                                  # confidence_check on confidence-fail (ADR-0006 fallback)
    draft_model: str              # the Bedrock model id that actually produced block_14_draft
    block_14_draft: str           # ADR-0005 §1 names this `draft`; the Block 14 text

    # --- integrity ---
    package_hash: str             # immutable hash of the material package; CO
                                  # approval, consent, and execution all bind to it

    # --- gate + decision ---
    gate_status: str              # e.g. "CONTRACT_NOT_FOUND_AWAITING_CO_REVIEW"
    co_decision: str              # "pending" | "approved" | "denied" (review gate)
    modification_bilateral: bool  # FAR 43.103(a) bilateral vs (b) unilateral —
                                  # DERIVED server-side from modType, never the LLM
    contractor_consent: str       # "not_required" | "pending" | "recorded"
    co_execution: str             # "pending" | "executed" | "aborted" — the
                                  # final-package execution decision (FAR 43.102),
                                  # distinct from co_decision


def compute_package_hash(state: "WorkflowState") -> str:
    """Return a stable SHA-256 hex digest of the package-defining fields.

    Covers the three fields whose content fully defines the modification package
    for DCAA audit binding: populated_fields, block_14_draft, and
    block13_classification.  Serialised with sort_keys=True for determinism so
    the same logical package always produces the same hash regardless of dict
    insertion order (Codex finding #3).

    Imported by nodes_gate.py as:
        from app.workflow.state import compute_package_hash
    """
    payload: dict[str, Any] = {
        "populated_fields":       state.get("populated_fields"),
        "block_14_draft":         state.get("block_14_draft"),
        "block13_classification": state.get("block13_classification"),
    }
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()

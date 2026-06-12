"""
nodes_classify.py — Person B: Block 13 classification + consent derivation
(m3.md Steps 2.1, 2.1b).

FOUNDATION STUBS — Person B implements in task B1. The classifier proposes the
Block 13 path/modType (via app.workflow.llm.call_json); derive_consent maps the
modType to FAR 43.103 deterministically (no LLM). The register() edges are frozen.
"""
from __future__ import annotations

from langgraph.graph import StateGraph

from app.workflow.state import WorkflowState


def classify_modification_node(state: WorkflowState) -> dict:
    """Classify the modification (Block 13, FAR 43.103) + capture provenance.
    STUB — B1 implements (m3.md Step 2.1)."""
    return {}


def derive_consent_node(state: WorkflowState) -> dict:
    """Map the classified modType -> consent rule (FAR 43.103); unknown -> CO review.
    STUB — B1 implements (m3.md Step 2.1b)."""
    return {}


def register(builder: StateGraph) -> None:
    """Add the classify + derive_consent nodes and the bridge to retrieval."""
    builder.add_node("classify", classify_modification_node)
    builder.add_node("derive_consent", derive_consent_node)

    builder.add_edge("classify", "derive_consent")
    builder.add_edge("derive_consent", "retrieve")  # bridge to the retrieval slice

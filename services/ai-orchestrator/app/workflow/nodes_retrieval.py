"""
nodes_retrieval.py — Person B: Block 14 grounded sub-pipeline (m3.md Steps 2.2-2.4,
ADR-0005 §4 verbatim).

FOUNDATION STUBS — Person B implements in task B2. retrieve_node wraps the
ADR-0005 /retrieve read path; confidence_check_node is a Haiku LLM-as-judge
(NOT a mean); draft_node generates Block 14; faithfulness_gate_node runs the
RAGAS judge. The register() edges are frozen.
"""
from __future__ import annotations

from langgraph.graph import StateGraph

from app.workflow.state import WorkflowState


def retrieve_node(state: WorkflowState) -> dict:
    """Hybrid retrieval for the Block 14 rationale (ADR-0005 /retrieve).
    STUB — B2 implements (m3.md Step 2.2)."""
    return {}


def confidence_check_node(state: WorkflowState) -> dict:
    """Haiku LLM-as-judge scores retrieval; < 0.85 -> RAG_FAILED_AWAITING_CO_REVIEW.
    STUB — B2 implements (m3.md Step 2.2, ADR-0005 §4)."""
    return {}


def draft_node(state: WorkflowState) -> dict:
    """Haiku drafts the Block 14 rationale, grounded in the retrieved clauses.
    STUB — B2 implements (m3.md Step 2.4)."""
    return {}


def faithfulness_gate_node(state: WorkflowState) -> dict:
    """RAGAS faithfulness judge; < 0.85 -> FAITHFULNESS_FAILED_AWAITING_CO_REVIEW.
    STUB — B2 implements (m3.md Step 2.4, ADR-0005 §7)."""
    return {}


def register(builder: StateGraph) -> None:
    """Add the Block 14 nodes + the bridge to the form-fill slice.

    FOUNDATION STUB uses a LINEAR confidence -> draft edge. In task B2, Person B
    replaces it with the conditional `route_after_confidence` (>= 0.85 -> draft;
    fail -> "co_gate"), m3.md Step 2.3.
    """
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("confidence", confidence_check_node)
    builder.add_node("draft", draft_node)
    builder.add_node("faithfulness", faithfulness_gate_node)

    builder.add_edge("retrieve", "confidence")
    builder.add_edge("confidence", "draft")        # STUB: B2 -> conditional route
    builder.add_edge("draft", "faithfulness")
    builder.add_edge("faithfulness", "assemble")   # bridge to the form-fill slice

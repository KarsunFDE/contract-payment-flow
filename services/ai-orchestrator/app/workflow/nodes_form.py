"""
nodes_form.py — Person A: form-fill tool layer (m3.md Phase 3).

FOUNDATION STUB — Person A implements in task A3. assemble_form_node calls the
allow-listed write tools to populate the ContractModification DRAFT (never the
live record; there is no submit tool). The register() edge is frozen.
"""
from __future__ import annotations

from langgraph.graph import StateGraph

from app.workflow.state import WorkflowState


def assemble_form_node(state: WorkflowState) -> dict:
    """Write the looked-up blocks + drafted rationale into the DRAFT record.
    STUB — A3 implements (m3.md Step 3.2)."""
    return {}


def register(builder: StateGraph) -> None:
    """Add the assemble node + the bridge to the CO gate."""
    builder.add_node("assemble", assemble_form_node)
    builder.add_edge("assemble", "co_gate")  # cross-seam bridge (Person A owns "co_gate")

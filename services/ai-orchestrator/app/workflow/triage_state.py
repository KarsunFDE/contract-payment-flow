"""
triage_state.py — state for the M3 multi-agent triage flow (m3.md Step 7.0).

`TriageState` EXTENDS `WorkflowState` so the SF-30 workflow can run as a compiled
subgraph on the HITL lane with no wrapper: LangGraph requires a parent graph and
an embedded subgraph to share state keys.
  https://docs.langchain.com/oss/python/langgraph/use-subgraphs
"""
from __future__ import annotations

from app.workflow.state import WorkflowState


class TriageState(WorkflowState, total=False):
    """Outer-graph state. Inherits every WorkflowState key (shared channels) and
    adds the triage-only fields the anomaly/adjudicator/router stages set."""

    item_type: str             # "modification" | "invoice"
    idempotency_key: str       # money-path dedupe; a replay is a no-op (REQ-AGT-2)
    anomaly_flags: list        # [{code, detail, far_part, severity}] from the detector
    adjudications: list        # [{flag_code, verdict, far_cite, precedent_id}]
    lane: str                  # "auto_process" | "hitl_escalate" | "return_route"
    disposition_rationale: str  # why this lane — written to the audit trail (REQ-AGT-4)

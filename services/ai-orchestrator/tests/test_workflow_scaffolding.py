"""
M3 Foundation / Phase 0 scaffolding smoke tests (m3.md Phase 0).

Verifies the shared workflow contracts import cleanly with no MongoDB running and
that the graph compiles + invokes end-to-end through the no-op stub nodes (Phase 0
exit criteria). Mirrors tests/test_day0_scaffolding.py. Owned jointly; frozen with
the Foundation files it covers.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.main import app
from app.workflow.state import WorkflowState
from app.workflow.triage_state import TriageState
from app.workflow.graph import build_graph
from app.workflow.triage_graph import build_triage_graph
from app.workflow.audit_events import WorkflowAuditRecord, WORKFLOW_EVENT_TYPES
from app.workflow.clients import SamGovClient, RetrieveClient  # noqa: F401
from app.workflow import llm


def test_state_carries_identity_fields():
    """WorkflowState must carry correlation_id + agency_id (ADR-0005 §1/§7/§11)."""
    annotations = WorkflowState.__annotations__
    assert "correlation_id" in annotations
    assert "agency_id" in annotations
    # TriageState extends WorkflowState and adds the triage-only fields.
    assert "lane" in TriageState.__annotations__
    assert "idempotency_key" in TriageState.__annotations__


def test_inner_graph_compiles_and_runs_end_to_end():
    """build_graph().compile().invoke(...) runs through the stub nodes (Phase 0)."""
    graph = build_graph().compile()
    result = graph.invoke(
        {
            "correlation_id": "00000000-0000-0000-0000-000000000000",
            "agency_id": "agency-gsa",
            "contract_number": "GS-35F-0001V",
            "change_request": {"agency_id": "agency-gsa", "scope": "extend PoP 90 days"},
        }
    )
    # No-op nodes return {}, so the input survives end-to-end without error.
    assert result["contract_number"] == "GS-35F-0001V"


def test_triage_graph_compiles_and_runs_end_to_end():
    """The outer triage graph compiles with the inner workflow as a subgraph."""
    graph = build_triage_graph().compile()
    result = graph.invoke(
        {
            "correlation_id": "00000000-0000-0000-0000-000000000000",
            "agency_id": "agency-gsa",
            "item_type": "modification",
            "contract_number": "GS-35F-0001V",
            "change_request": {"agency_id": "agency-gsa", "scope": "add CLIN"},
        }
    )
    assert result["item_type"] == "modification"


def test_workflow_audit_record_fields():
    """WorkflowAuditRecord constructs with an auto audit_id + UTC timestamp."""
    record = WorkflowAuditRecord(
        correlation_id="11111111-1111-1111-1111-111111111111",
        event_type="co_decision",
        agency_id="agency-gsa",
        details={"decision": "approved"},
    )
    assert record.audit_id  # auto-generated UUID
    assert record.event_type in WORKFLOW_EVENT_TYPES
    assert record.timestamp.tzinfo is not None


def test_llm_call_json_is_stub_safe():
    """With no AWS creds, bedrock returns a stub; call_json fails closed, not crashes."""

    class _Demo(BaseModel):
        verdict: str

    with pytest.raises(llm.LLMOutputError):
        llm.call_json("classify this", schema=_Demo, system="test")


def test_model_version_extraction():
    """Provenance helper pulls the version tag off a Bedrock model id."""
    assert llm.model_version("anthropic.claude-3-7-sonnet-20250219-v1:0") == "v1:0"
    assert llm.model_version("garbage") == "unknown"


def test_workflow_router_mounted():
    """The workflow surface is mounted on the app (additive to the Phase 1 routers)."""
    tags = {tag for route in app.routes for tag in getattr(route, "tags", []) or []}
    assert "workflow" in tags
    # The ADR-0005 Phase 1 routers must still be present.
    assert "retrieval" in tags
    assert "corpus-ingestion" in tags

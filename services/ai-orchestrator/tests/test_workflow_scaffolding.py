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
from app.workflow.audit_events import WorkflowAuditRecord, WORKFLOW_EVENT_TYPES, record_event
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


def test_record_event_fails_closed_without_correlation_id():
    """record_event raises before any DB write when correlation_id is absent (fail-closed)."""
    with pytest.raises(ValueError):
        record_event({}, "co_decision", {})


# ---------------------------------------------------------------------------
# NEW negative-path coverage — audit_events whitelist + high-consequence guards
# ---------------------------------------------------------------------------

def test_record_event_unknown_event_type_raises():
    """record_event raises ValueError for any event_type not in WORKFLOW_EVENT_TYPES."""
    with pytest.raises(ValueError, match="unknown workflow audit event_type"):
        record_event(
            {"correlation_id": "c-1"},
            "made_up_event",       # not in the whitelist
            {"actor_id": "x", "actor_role": "CO", "package_hash": "h"},
        )


def test_record_event_typo_event_type_raises():
    """A case-typo event_type (e.g. 'Co_Decision') is not whitelisted → raises."""
    with pytest.raises(ValueError, match="unknown workflow audit event_type"):
        record_event(
            {"correlation_id": "c-1"},
            "Co_Decision",         # capitalisation typo — not in frozenset
            {"actor_id": "x", "actor_role": "CO", "package_hash": "h"},
        )


def test_record_event_high_consequence_missing_actor_id_raises():
    """High-consequence event missing actor_id → raises before any DB write."""
    with pytest.raises(ValueError, match="missing required payload keys"):
        record_event(
            {"correlation_id": "c-1"},
            "modification_submitted",
            # actor_id absent
            {"actor_role": "CO", "package_hash": "abc123"},
        )


def test_record_event_high_consequence_missing_actor_role_raises():
    """High-consequence event missing actor_role → raises before any DB write."""
    with pytest.raises(ValueError, match="missing required payload keys"):
        record_event(
            {"correlation_id": "c-1"},
            "package_superseded",
            # actor_role absent
            {"actor_id": "co-123", "package_hash": "abc123"},
        )


def test_record_event_high_consequence_missing_package_hash_raises():
    """High-consequence event missing package_hash → raises before any DB write."""
    with pytest.raises(ValueError, match="missing required payload keys"):
        record_event(
            {"correlation_id": "c-1"},
            "co_decision",
            # package_hash absent
            {"actor_id": "co-123", "actor_role": "CO"},
        )


def test_record_event_non_high_consequence_does_not_require_actor_fields(monkeypatch):
    """Non-high-consequence events (e.g. contract_lookup) do not require actor/hash fields."""
    # Stub the DB write — we only care that no ValueError is raised for the missing actor keys.
    from unittest.mock import MagicMock
    import app.db as _db
    mock_col = MagicMock()
    fake_db = type("FakeDB", (), {"__getitem__": lambda s, k: mock_col})()
    monkeypatch.setattr(_db, "get_db", lambda: fake_db)
    record_event(
        {"correlation_id": "c-1", "agency_id": "DOD"},
        "contract_lookup",
        {"contract_number": "W911-001"},   # no actor fields — allowed for non-HC events
    )


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


def test_llm_call_json_strips_markdown_fences(monkeypatch):
    """call_json strips a ```json fence off the model body before json.loads."""

    class _Demo(BaseModel):
        verdict: str

    def _fenced_response(prompt, **kwargs):
        return {
            "body": '```json\n{"verdict": "ok"}\n```',
            "model": "anthropic.claude-3-7-sonnet-20250219-v1:0",
        }

    monkeypatch.setattr(llm.bedrock_client, "invoke_model", _fenced_response)
    result = llm.call_json("x", schema=_Demo)
    assert result.data.verdict == "ok"
    assert result.model_version == "v1:0"


def test_workflow_router_mounted():
    """The workflow surface is mounted on the app (additive to the Phase 1 routers)."""
    tags = {tag for route in app.routes for tag in getattr(route, "tags", []) or []}
    assert "workflow" in tags
    # The ADR-0005 Phase 1 routers must still be present.
    assert "retrieval" in tags
    assert "corpus-ingestion" in tags

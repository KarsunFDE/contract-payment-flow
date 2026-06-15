"""
test_submit.py — submit_node + supersede_node (m3.md Phase 5, Steps 5.2-5.3).

modification_client and audit are stubbed; tests pin publish/cancel calls +
state returned.
"""
from __future__ import annotations

from app.workflow import nodes_gate


_STATE = {
    "correlation_id": "corr-1",
    "agency_id": "DOD",
    "form_draft_id": "draft-1",
    "co_decision": "approved",
    "contractor_consent": "recorded",
}


# ---------------------------------------------------------------------------
# submit_node
# ---------------------------------------------------------------------------

def test_submit_calls_publish_with_consent_recorded(monkeypatch):
    published: list = []
    monkeypatch.setattr(nodes_gate.modification_client, "publish",
                        lambda **kw: published.append(kw))
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    result = nodes_gate.submit_node(_STATE)

    assert result["gate_status"] == "SUBMITTED"
    assert result["co_execution"] == "executed"
    assert len(published) == 1
    assert published[0]["draft_id"] == "draft-1"
    assert published[0]["consent_recorded"] is True


def test_submit_consent_not_recorded(monkeypatch):
    published: list = []
    monkeypatch.setattr(nodes_gate.modification_client, "publish",
                        lambda **kw: published.append(kw))
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    nodes_gate.submit_node({**_STATE, "contractor_consent": "not_required"})
    assert published[0]["consent_recorded"] is False


def test_submit_no_consent_key(monkeypatch):
    published: list = []
    monkeypatch.setattr(nodes_gate.modification_client, "publish",
                        lambda **kw: published.append(kw))
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    state = {k: v for k, v in _STATE.items() if k != "contractor_consent"}
    nodes_gate.submit_node(state)
    assert published[0]["consent_recorded"] is False


def test_submit_writes_audit(monkeypatch):
    monkeypatch.setattr(nodes_gate.modification_client, "publish", lambda **kw: None)
    audit_calls: list = []
    monkeypatch.setattr(nodes_gate, "record_event",
                        lambda state, event_type, details: audit_calls.append(event_type))

    nodes_gate.submit_node(_STATE)
    assert "modification_submitted" in audit_calls


# ---------------------------------------------------------------------------
# supersede_node
# ---------------------------------------------------------------------------

def test_supersede_cancels_draft(monkeypatch):
    cancelled: list = []
    monkeypatch.setattr(nodes_gate.modification_client, "cancel_draft",
                        lambda draft_id: cancelled.append(draft_id))
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    result = nodes_gate.supersede_node({**_STATE, "co_decision": "denied"})
    assert result["co_execution"] == "aborted"
    assert "draft-1" in cancelled


def test_supersede_writes_audit(monkeypatch):
    monkeypatch.setattr(nodes_gate.modification_client, "cancel_draft", lambda d: None)
    audit_calls: list = []
    monkeypatch.setattr(nodes_gate, "record_event",
                        lambda state, event_type, details: audit_calls.append(event_type))

    nodes_gate.supersede_node({**_STATE, "co_decision": "denied"})
    assert "package_superseded" in audit_calls


def test_supersede_no_draft_id(monkeypatch):
    monkeypatch.setattr(nodes_gate.modification_client, "cancel_draft",
                        lambda d: (_ for _ in ()).throw(Exception("should not call")))
    monkeypatch.setattr(nodes_gate, "record_event", lambda *a, **k: None)

    state = {k: v for k, v in _STATE.items() if k != "form_draft_id"}
    result = nodes_gate.supersede_node(state)
    assert result["co_execution"] == "aborted"

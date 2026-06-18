"""
test_form_tools.py — form-fill tools + assemble_form_node (m3.md Phase 3).

modification_client is stubbed; tests pin the payload shape written to the draft.
"""
from __future__ import annotations

from app.workflow import form_tools, nodes_form


# ---------------------------------------------------------------------------
# form_tools
# ---------------------------------------------------------------------------

def test_set_modification_basics_payload(monkeypatch):
    calls: list = []
    # patch_draft now requires keyword-only identity args — accept via **kwargs.
    monkeypatch.setattr(form_tools.modification_client, "patch_draft",
                        lambda draft_id, fields, **kwargs: calls.append((draft_id, fields)))

    form_tools.set_modification_basics(
        draft_id="d-1",
        contract_number="W911-001",
        modification_number="P00001",
        mod_type="bilateral_supplemental",
        far_authority="43.103(a)",
        effective_date="2024-01-01",
        actor_id="co-123",
        actor_role="CO",
        agency_id="DOD",
        correlation_id="corr-1",
    )

    assert len(calls) == 1
    did, fields = calls[0]
    assert did == "d-1"
    assert fields["contractNumber"] == "W911-001"
    assert fields["modType"] == "bilateral_supplemental"
    assert fields["farAuthority"] == "43.103(a)"
    assert fields["agencyId"] == "DOD"


def test_set_block_14_rationale_payload(monkeypatch):
    calls: list = []
    # patch_draft now requires keyword-only identity args — accept via **kwargs.
    monkeypatch.setattr(form_tools.modification_client, "patch_draft",
                        lambda draft_id, fields, **kwargs: calls.append((draft_id, fields)))

    form_tools.set_block_14_rationale(
        draft_id="d-1",
        narrative="Extend PoP by 90 days.",
        price_cost_impact="No cost impact.",
        funding_citation="ACRN AA",
        actor_id="co-123",
        actor_role="CO",
        agency_id="DOD",
        correlation_id="corr-1",
    )

    assert len(calls) == 1
    _, fields = calls[0]
    assert fields["description"] == "Extend PoP by 90 days."
    assert fields["sections"]["changeNarrative"] == "Extend PoP by 90 days."
    assert fields["sections"]["priceCostImpact"] == "No cost impact."
    assert fields["sections"]["fundingCitation"] == "ACRN AA"


# ---------------------------------------------------------------------------
# assemble_form_node
# ---------------------------------------------------------------------------

# Updated: now includes co_user_id / co_role (required for identity guards) and
# block13_classification (mod_type sourced here, not from modification_bilateral).
_ASSEMBLE_STATE = {
    "correlation_id": "corr-1",
    "agency_id": "DOD",
    "co_user_id": "co-123",
    "co_role": "CO",
    "contract_number": "W911-001",
    "form_draft_id": "d-1",
    "modification_bilateral": True,
    "block13_classification": {
        "mod_type": "bilateral_supplemental",
        "far_basis": "43.103(a)",
    },
    "block_14_draft": "Rationale text.",
    "change_request": {"price_impact": "None", "funding_citation": "ACRN AA"},
    "populated_fields": {
        "2": {"value": "W911-001", "source_citation": {}},
        "3": {"value": "2024-01-01", "source_citation": {}},
    },
}


def test_assemble_form_node_calls_both_tools(monkeypatch):
    basic_calls: list = []
    rationale_calls: list = []
    monkeypatch.setattr(nodes_form.form_tools, "set_modification_basics",
                        lambda **kw: basic_calls.append(kw))
    monkeypatch.setattr(nodes_form.form_tools, "set_block_14_rationale",
                        lambda **kw: rationale_calls.append(kw))
    monkeypatch.setattr(nodes_form, "record_event", lambda *a, **k: None)

    result = nodes_form.assemble_form_node(_ASSEMBLE_STATE)

    assert result == {"co_decision": "pending"}
    assert len(basic_calls) == 1
    assert len(rationale_calls) == 1
    # mod_type must come from block13_classification, not modification_bilateral.
    assert basic_calls[0]["mod_type"] == "bilateral_supplemental"
    assert rationale_calls[0]["narrative"] == "Rationale text."


# INVERTED (was: passing modification_bilateral=False → mod_type=="unilateral_admin" from flag)
# NEW behaviour: mod_type is sourced ONLY from block13_classification; the bilateral flag
# does not determine mod_type. Passing a different flag with explicit classification should
# use the classification's mod_type, not infer one from the flag.
def test_assemble_form_node_mod_type_from_classification_not_bilateral_flag(monkeypatch):
    """mod_type comes from block13_classification regardless of the bilateral flag."""
    basic_calls: list = []
    monkeypatch.setattr(nodes_form.form_tools, "set_modification_basics",
                        lambda **kw: basic_calls.append(kw))
    monkeypatch.setattr(nodes_form.form_tools, "set_block_14_rationale",
                        lambda **kw: None)
    monkeypatch.setattr(nodes_form, "record_event", lambda *a, **k: None)

    state = {
        **_ASSEMBLE_STATE,
        "modification_bilateral": False,  # flag says unilateral
        "block13_classification": {
            "mod_type": "unilateral_admin",  # classification independently confirms it
            "far_basis": "43.103(b)(3)",
        },
    }
    nodes_form.assemble_form_node(state)
    # mod_type must equal the value from block13_classification, not a value
    # inferred from the bilateral flag.
    assert basic_calls[0]["mod_type"] == "unilateral_admin"
    assert basic_calls[0]["far_authority"] == "43.103(b)(3)"


def test_assemble_form_node_fails_closed_on_missing_classification(monkeypatch):
    """assemble_form_node returns CO-review gate when block13_classification absent."""
    monkeypatch.setattr(nodes_form.form_tools, "set_modification_basics",
                        lambda **kw: None)
    monkeypatch.setattr(nodes_form.form_tools, "set_block_14_rationale",
                        lambda **kw: None)
    monkeypatch.setattr(nodes_form, "record_event", lambda *a, **k: None)

    state = {k: v for k, v in _ASSEMBLE_STATE.items() if k != "block13_classification"}
    result = nodes_form.assemble_form_node(state)
    assert result["gate_status"] == "CLASSIFICATION_MISSING_AWAITING_CO_REVIEW"


def test_assemble_form_node_fails_closed_on_unknown_mod_type(monkeypatch):
    """assemble_form_node returns CO-review gate when mod_type is 'unknown'."""
    monkeypatch.setattr(nodes_form.form_tools, "set_modification_basics",
                        lambda **kw: None)
    monkeypatch.setattr(nodes_form.form_tools, "set_block_14_rationale",
                        lambda **kw: None)
    monkeypatch.setattr(nodes_form, "record_event", lambda *a, **k: None)

    state = {
        **_ASSEMBLE_STATE,
        "block13_classification": {"mod_type": "unknown", "far_basis": ""},
    }
    result = nodes_form.assemble_form_node(state)
    assert result["gate_status"] == "CLASSIFICATION_MISSING_AWAITING_CO_REVIEW"


def test_assemble_form_node_fails_closed_on_missing_identity(monkeypatch):
    """assemble_form_node returns CO-review gate when co_user_id/co_role/agency_id absent."""
    monkeypatch.setattr(nodes_form.form_tools, "set_modification_basics",
                        lambda **kw: None)
    monkeypatch.setattr(nodes_form.form_tools, "set_block_14_rationale",
                        lambda **kw: None)
    monkeypatch.setattr(nodes_form, "record_event", lambda *a, **k: None)

    state = {k: v for k, v in _ASSEMBLE_STATE.items() if k != "co_user_id"}
    result = nodes_form.assemble_form_node(state)
    assert result["gate_status"] == "CONTRACT_NOT_FOUND_AWAITING_CO_REVIEW"

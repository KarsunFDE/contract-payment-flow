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
    monkeypatch.setattr(form_tools.modification_client, "patch_draft",
                        lambda draft_id, fields: calls.append((draft_id, fields)))

    form_tools.set_modification_basics(
        draft_id="d-1",
        contract_number="W911-001",
        modification_number="P00001",
        mod_type="bilateral_supplemental",
        far_authority="43.103(a)",
        effective_date="2024-01-01",
        agency_id="DOD",
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
    monkeypatch.setattr(form_tools.modification_client, "patch_draft",
                        lambda draft_id, fields: calls.append((draft_id, fields)))

    form_tools.set_block_14_rationale(
        draft_id="d-1",
        narrative="Extend PoP by 90 days.",
        price_cost_impact="No cost impact.",
        funding_citation="ACRN AA",
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

_ASSEMBLE_STATE = {
    "correlation_id": "corr-1",
    "agency_id": "DOD",
    "contract_number": "W911-001",
    "form_draft_id": "d-1",
    "modification_bilateral": True,
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
    assert basic_calls[0]["mod_type"] == "bilateral_supplemental"
    assert rationale_calls[0]["narrative"] == "Rationale text."


def test_assemble_form_node_unilateral_mod_type(monkeypatch):
    basic_calls: list = []
    monkeypatch.setattr(nodes_form.form_tools, "set_modification_basics",
                        lambda **kw: basic_calls.append(kw))
    monkeypatch.setattr(nodes_form.form_tools, "set_block_14_rationale",
                        lambda **kw: None)
    monkeypatch.setattr(nodes_form, "record_event", lambda *a, **k: None)

    nodes_form.assemble_form_node({**_ASSEMBLE_STATE, "modification_bilateral": False})
    assert basic_calls[0]["mod_type"] == "unilateral_admin"

"""
Task B3 — deterministic anomaly detection rules (m3.md Step 7.1).
"""
from __future__ import annotations

from app.workflow import anomaly_rules


def _codes(flags):
    return {f["code"] for f in flags}


def test_clean_modification_yields_no_flags():
    item = {"scope": "extend PoP 90 days", "funding_delta": 0,
            "obligated": 50_000, "ceiling": 100_000}
    assert anomaly_rules.scan(item, "modification") == []


def test_funding_ceiling_breach_flagged():
    item = {"funding_delta": 60_000, "obligated": 50_000, "ceiling": 100_000}
    flags = anomaly_rules.scan(item, "modification")
    assert _codes(flags) == {"FUNDING_CEILING_BREACH"}
    assert flags[0]["far_part"] == "43.105"
    assert flags[0]["severity"] == "high"


def test_ceiling_check_skipped_when_fields_absent():
    """No numbers -> no deterministic verdict (the LLM scope pass is separate)."""
    assert anomaly_rules.scan({"scope": "add CLIN"}, "modification") == []


def _proper_invoice() -> dict:
    return {
        "vendor_name": "Acme Integration LLC",
        "invoice_number": "INV-001",
        "invoice_date": "2026-06-01",
        "contract_number": "GS-35F-0001V",
        "amount": 1200.0,
        "description": "monthly maintenance",
        "line_items": [
            {"description": "maintenance", "unit_price": 100.0,
             "contracted_unit_price": 100.0},
        ],
    }


def test_proper_invoice_yields_no_flags():
    assert anomaly_rules.scan(_proper_invoice(), "invoice") == []


def test_missing_far_32_905_elements_flagged():
    invoice = _proper_invoice()
    del invoice["invoice_number"]
    invoice["amount"] = None
    flags = anomaly_rules.scan(invoice, "invoice")
    assert "INVOICE_MISSING_FAR_32_905_ELEMENTS" in _codes(flags)
    detail = next(f for f in flags
                  if f["code"] == "INVOICE_MISSING_FAR_32_905_ELEMENTS")["detail"]
    assert "invoice_number" in detail and "amount" in detail


def test_unit_price_variance_flagged_beyond_tolerance():
    invoice = _proper_invoice()
    invoice["line_items"][0]["unit_price"] = 111.0  # > 10% over 100.0
    flags = anomaly_rules.scan(invoice, "invoice")
    assert "UNIT_PRICE_VARIANCE" in _codes(flags)


def test_unit_price_within_tolerance_not_flagged():
    invoice = _proper_invoice()
    invoice["line_items"][0]["unit_price"] = 109.0  # within 10%
    assert "UNIT_PRICE_VARIANCE" not in _codes(anomaly_rules.scan(invoice, "invoice"))


def test_unallowable_cost_keyword_flagged_with_far_cite():
    invoice = _proper_invoice()
    invoice["line_items"].append(
        {"description": "team entertainment night", "unit_price": 50.0,
         "contracted_unit_price": 50.0}
    )
    flags = anomaly_rules.scan(invoice, "invoice")
    suspect = [f for f in flags if f["code"] == "UNALLOWABLE_COST_SUSPECT"]
    assert suspect and suspect[0]["far_part"] == "31.205-14"


# --- B3 node layer: detector LLM pass + adjudicator (fakes injected) ---

from app.workflow import llm, nodes_triage, retrieve_client  # noqa: E402


def test_detector_degrades_silently_without_llm(monkeypatch):
    """Stub Bedrock loses only the scope flag — deterministic flags survive."""
    def _reject(prompt, *, schema, system=None, **kwargs):
        raise llm.LLMOutputError("stub (test)")
    monkeypatch.setattr(llm, "call_json", _reject)

    state = {"item_type": "modification",
             "change_request": {"scope": "add CLIN", "funding_delta": 60_000,
                                "obligated": 50_000, "ceiling": 100_000}}
    update = nodes_triage.anomaly_detector_node(state)
    assert _codes(update["anomaly_flags"]) == {"FUNDING_CEILING_BREACH"}


def test_detector_llm_pass_adds_out_of_scope_flag(monkeypatch):
    def _scope(prompt, *, schema, system=None, **kwargs):
        return llm.JsonResult(
            data=nodes_triage.ScopeVerdict(out_of_scope=True,
                                           rationale="cardinal change"),
            model="m", model_version="v1:0",
        )
    monkeypatch.setattr(llm, "call_json", _scope)

    state = {"item_type": "modification",
             "change_request": {"scope": "replace entire deliverable set"}}
    update = nodes_triage.anomaly_detector_node(state)
    assert _codes(update["anomaly_flags"]) == {"OUT_OF_SCOPE_CHANGE"}


class _FakeRetrieve:
    def __init__(self, fail=False):
        self.fail = fail

    def retrieve(self, query, **kwargs):
        if self.fail:
            raise retrieve_client.RetrievalUnavailable("down (test)")
        return [{"chunk_id": "c1", "chunk_text": "FAR text", "score": 0.9,
                 "source_document": None}]


_FLAG_STATE = {
    "correlation_id": "44444444-4444-4444-4444-444444444444",
    "agency_id": "agency-gsa",
    "item_type": "invoice",
    "change_request": {},
    "anomaly_flags": [
        {"code": "UNALLOWABLE_COST_SUSPECT", "detail": "mentions entertainment",
         "far_part": "31.205-14", "severity": "high"},
    ],
}


def test_adjudicator_substantiates_against_retrieved_far(monkeypatch):
    """(conftest autouse fixture restores the real client after every test.)"""
    retrieve_client.set_client(_FakeRetrieve())

    def _verdict(prompt, *, schema, system=None, **kwargs):
        return llm.JsonResult(
            data=nodes_triage.Adjudication(verdict="substantiated",
                                           far_cite="31.205-14"),
            model="m", model_version="v1:0",
        )
    monkeypatch.setattr(llm, "call_json", _verdict)
    update = nodes_triage.adjudicator_node(dict(_FLAG_STATE))

    assert update["adjudications"][0]["verdict"] == "substantiated"
    assert update["adjudications"][0]["flag_code"] == "UNALLOWABLE_COST_SUSPECT"


def test_adjudicator_fails_closed_when_retrieval_down(monkeypatch):
    """G2: an unverifiable flag is error_failed_closed, never dismissed."""
    retrieve_client.set_client(_FakeRetrieve(fail=True))
    update = nodes_triage.adjudicator_node(dict(_FLAG_STATE))
    assert update["adjudications"][0]["verdict"] == "error_failed_closed"


def test_adjudicator_fails_closed_on_judge_error(monkeypatch):
    retrieve_client.set_client(_FakeRetrieve())

    def _reject(prompt, *, schema, system=None, **kwargs):
        raise llm.LLMOutputError("stub (test)")
    monkeypatch.setattr(llm, "call_json", _reject)
    update = nodes_triage.adjudicator_node(dict(_FLAG_STATE))
    assert update["adjudications"][0]["verdict"] == "error_failed_closed"

"""
test_anomaly.py — deterministic anomaly detection (m3.md Step 7.1).

Detection is data-driven and deterministic, so each typed flag is asserted from a
crafted item, and a clean item yields no flags.
"""
from __future__ import annotations

from app.workflow import anomaly_rules


def _codes(flags):
    return {f["code"] for f in flags}


def test_funding_ceiling_breach_flagged():
    item = {"current_obligated": 900, "funding_delta": 200, "contract_ceiling": 1000}
    assert "FUNDING_CEILING_BREACH" in _codes(anomaly_rules.scan(item, "modification"))


def test_modification_within_ceiling_is_clean():
    item = {"current_obligated": 100, "funding_delta": 200, "contract_ceiling": 1000}
    assert anomaly_rules.scan(item, "modification") == []


def test_out_of_scope_flagged():
    assert "OUT_OF_SCOPE" in _codes(anomaly_rules.scan({"changes_scope": True}, "modification"))


def test_improper_invoice_flagged():
    item = {"missing_elements": ["invoice_date"]}
    assert "IMPROPER_INVOICE" in _codes(anomaly_rules.scan(item, "invoice"))


def test_unit_price_variance_flagged_above_limit_only():
    over = {"unit_price_variance_pct": 0.25}
    under = {"unit_price_variance_pct": 0.05}
    assert "UNIT_PRICE_VARIANCE" in _codes(anomaly_rules.scan(over, "invoice"))
    assert "UNIT_PRICE_VARIANCE" not in _codes(anomaly_rules.scan(under, "invoice"))


def test_unknown_item_type_has_no_flags():
    assert anomaly_rules.scan({}, "something_else") == []

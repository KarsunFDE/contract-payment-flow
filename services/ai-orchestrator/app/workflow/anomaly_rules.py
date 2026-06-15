"""
anomaly_rules.py — Person B: deterministic anomaly detection (m3.md Step 7.1).

The anomaly detector FLAGS typed anomalies; it never decides a lane (that is the
router, Step 7.4) and never substantiates a flag (that is the adjudicator against
real FAR text, Step 7.2). These checks are deterministic and data-driven so the
same input always yields the same flags — the LLM is reserved for the adjudicator.

A flag is `{code, detail, far_part, severity}`. The thresholds are intentionally
explicit constants, not magic numbers buried in the checks.
"""
from __future__ import annotations

# A unit price more than this fraction above the contract baseline is flagged for
# adjudication (not auto-rejected) — DCAA-style price-reasonableness trigger.
UNIT_PRICE_VARIANCE_LIMIT = 0.10


def _scan_modification(item: dict) -> list[dict]:
    """Mod-side flags: funding-ceiling breach + out-of-scope change."""
    flags = []

    # Funding-ceiling breach: would this delta push obligations past the ceiling?
    ceiling = item.get("contract_ceiling")
    projected = item.get("current_obligated", 0) + item.get("funding_delta", 0)
    if ceiling is not None and projected > ceiling:
        flags.append({
            "code": "FUNDING_CEILING_BREACH",
            "detail": f"obligated {projected} would exceed contract ceiling {ceiling}",
            "far_part": "43.102",
            "severity": "high",
        })

    # Out-of-scope change (a modification cannot exceed the scope of the contract).
    if item.get("changes_scope") is True:
        flags.append({
            "code": "OUT_OF_SCOPE",
            "detail": "change appears to fall outside the contract's general scope",
            "far_part": "43.203",
            "severity": "high",
        })

    return flags


def _scan_invoice(item: dict) -> list[dict]:
    """Invoice-side flags: unit-price variance, improper invoice, unallowable cost."""
    flags = []

    # Unit-price variance against the contract baseline.
    variance = item.get("unit_price_variance_pct", 0)
    if variance > UNIT_PRICE_VARIANCE_LIMIT:
        flags.append({
            "code": "UNIT_PRICE_VARIANCE",
            "detail": f"unit price {variance:.0%} above contract baseline",
            "far_part": "31.201",
            "severity": "medium",
        })

    # Improper invoice — missing FAR 32.905(b) required elements.
    missing = item.get("missing_elements") or []
    if missing:
        flags.append({
            "code": "IMPROPER_INVOICE",
            "detail": f"missing FAR 32.905 required elements: {missing}",
            "far_part": "32.905",
            "severity": "high",
        })

    # Potentially unallowable cost (FAR 31.205) — surfaced for adjudication.
    if item.get("flagged_unallowable") is True:
        flags.append({
            "code": "UNALLOWABLE_COST",
            "detail": "line item may be an unallowable cost under FAR 31.205",
            "far_part": "31.205",
            "severity": "medium",
        })

    return flags


def scan(item: dict, item_type: str) -> list[dict]:
    """Return the typed anomaly flags for one inbound item (modification or invoice)."""
    if item_type == "modification":
        return _scan_modification(item)
    if item_type == "invoice":
        return _scan_invoice(item)
    return []

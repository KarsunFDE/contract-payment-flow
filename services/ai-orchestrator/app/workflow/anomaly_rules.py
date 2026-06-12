"""
anomaly_rules.py — Person B: deterministic anomaly detection rules (m3.md
Step 7.1 — task B3).

Pure functions, no I/O, no LLM. The detector node layers an optional LLM pass
on top (scope / unallowable-cost judgment only); everything here is the
deterministic core: numeric and structural checks that never depend on model
availability. Detection only — no rule here decides a lane (REQ-AGT-1).

Flag shape (frozen TriageState contract): {code, detail, far_part, severity}.

Invoice payloads ride in `change_request` (the frozen TriageState has no
separate invoice channel); `item_type` discriminates.
"""
from __future__ import annotations

# FAR 32.905(b) — a proper invoice's required elements, mapped to the payload
# fields the intake form captures. Missing any -> improper invoice.
FAR_32_905_REQUIRED_FIELDS = (
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "contract_number",
    "amount",
    "line_items",
)

# FAR 31.205 expressly-unallowable cost keywords -> governing subsection.
# Deterministic first pass; the LLM judgment in the detector node refines.
UNALLOWABLE_COST_KEYWORDS = {
    "alcohol": "31.205-51",
    "entertainment": "31.205-14",
    "lobbying": "31.205-22",
    "fine": "31.205-15",
    "penalty": "31.205-15",
    "donation": "31.205-8",
    "contribution": "31.205-8",
}

# Unit price more than this fraction above the contracted price -> flag.
UNIT_PRICE_VARIANCE_TOLERANCE = 0.10


def _flag(code: str, detail: str, far_part: str, severity: str) -> dict:
    return {"code": code, "detail": detail, "far_part": far_part, "severity": severity}


def _scan_modification(item: dict) -> list[dict]:
    flags: list[dict] = []

    # Funding-ceiling breach: obligated + delta exceeds the contract ceiling.
    funding_delta = item.get("funding_delta")
    obligated = item.get("obligated")
    ceiling = item.get("ceiling")
    if (
        isinstance(funding_delta, (int, float))
        and isinstance(obligated, (int, float))
        and isinstance(ceiling, (int, float))
        and obligated + funding_delta > ceiling
    ):
        flags.append(
            _flag(
                "FUNDING_CEILING_BREACH",
                f"obligated {obligated} + delta {funding_delta} exceeds "
                f"ceiling {ceiling}",
                "43.105",
                "high",
            )
        )

    return flags


def _scan_invoice(item: dict) -> list[dict]:
    flags: list[dict] = []

    # FAR 32.905 proper-invoice elements.
    missing = [f for f in FAR_32_905_REQUIRED_FIELDS if not item.get(f)]
    if missing:
        flags.append(
            _flag(
                "INVOICE_MISSING_FAR_32_905_ELEMENTS",
                f"missing required elements: {', '.join(missing)}",
                "32.905",
                "high",
            )
        )

    # Unit-price variance vs the contracted price.
    for idx, line in enumerate(item.get("line_items") or []):
        unit_price = line.get("unit_price")
        contracted = line.get("contracted_unit_price")
        if (
            isinstance(unit_price, (int, float))
            and isinstance(contracted, (int, float))
            and contracted > 0
            and unit_price > contracted * (1 + UNIT_PRICE_VARIANCE_TOLERANCE)
        ):
            flags.append(
                _flag(
                    "UNIT_PRICE_VARIANCE",
                    f"line {idx}: unit price {unit_price} exceeds contracted "
                    f"{contracted} by more than "
                    f"{UNIT_PRICE_VARIANCE_TOLERANCE:.0%}",
                    "31.201-3",
                    "medium",
                )
            )

    # FAR 31.205 expressly-unallowable cost keywords (deterministic pass).
    texts = [str(item.get("description", ""))] + [
        str(line.get("description", "")) for line in item.get("line_items") or []
    ]
    haystack = " ".join(texts).lower()
    seen: set[str] = set()
    for keyword, far_cite in UNALLOWABLE_COST_KEYWORDS.items():
        if keyword in haystack and far_cite not in seen:
            seen.add(far_cite)
            flags.append(
                _flag(
                    "UNALLOWABLE_COST_SUSPECT",
                    f"description mentions '{keyword}' (FAR {far_cite})",
                    far_cite,
                    "high",
                )
            )

    return flags


def scan(item: dict, item_type: str) -> list[dict]:
    """Deterministic anomaly scan. Returns typed flags; never decides a lane."""
    if item_type == "invoice":
        return _scan_invoice(item or {})
    return _scan_modification(item or {})

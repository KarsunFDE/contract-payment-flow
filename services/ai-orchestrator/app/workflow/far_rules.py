"""
far_rules.py — Person B: deterministic FAR 43.103 consent rules (m3.md Step 2.1b).

Consent-required is a LEGAL RULE on modType, not a model opinion (ADR-0006
§"Bilateral vs Unilateral"). Pure functions only — no LLM, no I/O. An unmapped
modType returns None and the caller treats it as "CO must decide"; it never
silently falls through to unilateral.
"""
from __future__ import annotations

# FAR 43.103: modType -> contractor consent required?  Pure, deterministic, no LLM.
_CONSENT_RULES = {
    "bilateral_supplemental":  True,    # 43.103(a) — supplemental agreement, both sign
    "unilateral_change_order": False,   # 43.103(b)(1) — Changes clause, CO signs alone
    "unilateral_admin":        False,   # 43.103(b)(3) — administrative, CO signs alone
}

# The closed set the classifier may propose (prompt vocabulary + validation).
KNOWN_MOD_TYPES = tuple(_CONSENT_RULES) + ("unknown",)


def consent_required_for(mod_type: str):
    """True/False per FAR 43.103, or None if the modType is unmapped.
    Caller treats None as 'CO must decide' — never assume unilateral."""
    return _CONSENT_RULES.get(mod_type)

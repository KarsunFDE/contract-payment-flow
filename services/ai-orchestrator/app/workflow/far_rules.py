"""
far_rules.py — deterministic FAR 43.103 consent rule (m3.md Step 2.1b).

Whether a modification needs contractor consent is a LEGAL rule on the classified
modType, never a model opinion (m3.md Issue 1). This module is the single source
of that rule; both the agent's derive_consent_node and the write-path re-derivation
(contract-modification-service) apply the same mapping, so the agent can never
widen or narrow the legal requirement.

Pure + deterministic — no LLM, no I/O.
"""
from __future__ import annotations

# FAR 43.103: modType -> is contractor consent required?
#   bilateral_supplemental  43.103(a)    — supplemental agreement, both parties sign
#   unilateral_change_order 43.103(b)(1) — Changes clause, CO signs alone
#   unilateral_admin        43.103(b)(3) — administrative change, CO signs alone
_CONSENT_RULES = {
    "bilateral_supplemental": True,
    "unilateral_change_order": False,
    "unilateral_admin": False,
}


def consent_required_for(mod_type: str) -> bool | None:
    """Return True/False per FAR 43.103, or None when modType is unmapped.

    None is NOT "no consent" — the caller treats it as "CO must decide" and never
    assumes unilateral (fail-safe to consent-required). See derive_consent_node.
    """
    return _CONSENT_RULES.get(mod_type)

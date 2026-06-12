"""
Task B1 — deterministic FAR 43.103 consent rules (m3.md Step 2.1b).
"""
from __future__ import annotations

from app.workflow import far_rules


def test_bilateral_supplemental_requires_consent():
    """FAR 43.103(a) — supplemental agreement, both parties sign."""
    assert far_rules.consent_required_for("bilateral_supplemental") is True


def test_unilateral_types_do_not_require_consent():
    """FAR 43.103(b)(1)/(b)(3) — CO signs alone."""
    assert far_rules.consent_required_for("unilateral_change_order") is False
    assert far_rules.consent_required_for("unilateral_admin") is False


def test_unmapped_mod_type_returns_none_never_unilateral():
    """Unknown modType -> None ('CO must decide'); never silently unilateral."""
    assert far_rules.consent_required_for("unknown") is None
    assert far_rules.consent_required_for("") is None
    assert far_rules.consent_required_for("creative_new_type") is None


def test_known_mod_types_cover_rules_plus_unknown():
    """The classifier prompt vocabulary = every mapped type + 'unknown'."""
    assert "unknown" in far_rules.KNOWN_MOD_TYPES
    for mod_type in far_rules.KNOWN_MOD_TYPES:
        if mod_type != "unknown":
            assert far_rules.consent_required_for(mod_type) is not None

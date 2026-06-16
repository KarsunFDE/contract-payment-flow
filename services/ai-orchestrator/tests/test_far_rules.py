"""
test_far_rules.py — FAR 43.103 consent rule (m3.md Step 2.1b).

The mapping is a legal rule, so the unmapped case is the important one: it must
return None (-> "CO must decide"), never silently fall through to "no consent".
"""
from __future__ import annotations

from app.workflow import far_rules


def test_bilateral_requires_consent():
    assert far_rules.consent_required_for("bilateral_supplemental") is True


def test_unilateral_does_not_require_consent():
    assert far_rules.consent_required_for("unilateral_change_order") is False
    assert far_rules.consent_required_for("unilateral_admin") is False


def test_unknown_mod_type_is_none_not_false():
    """Unmapped modType -> None so the caller fails safe to CO review."""
    assert far_rules.consent_required_for("unknown") is None
    assert far_rules.consent_required_for("something_new") is None

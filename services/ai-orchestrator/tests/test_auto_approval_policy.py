"""
Task B4 — bounded, default-deny auto-approval policy (m3.md Step 7.3, REQ-AGT-6).
"""
from __future__ import annotations

from app.workflow import auto_approval_policy as policy

_ALL_CLEAR = dict(
    reversible=True,
    within_delegated_authority=True,
    amount=100.0,
    threshold=10_000.0,
    substantiated_flags=0,
)


def test_all_gates_clear_allows_auto():
    assert policy.may_auto_process("invoice_processing", **_ALL_CLEAR) is True


def test_reserved_actions_never_auto_even_when_all_else_clear():
    """REQ-AGT-2 'authority over accuracy' — no condition overrides reserved."""
    for action in policy.RESERVED_ACTIONS:
        assert policy.may_auto_process(action, **_ALL_CLEAR) is False


def test_irreversible_never_auto():
    args = dict(_ALL_CLEAR, reversible=False)
    assert policy.may_auto_process("invoice_processing", **args) is False


def test_outside_delegated_authority_never_auto():
    args = dict(_ALL_CLEAR, within_delegated_authority=False)
    assert policy.may_auto_process("invoice_processing", **args) is False


def test_over_threshold_never_auto():
    args = dict(_ALL_CLEAR, amount=10_000.01)
    assert policy.may_auto_process("invoice_processing", **args) is False


def test_substantiated_flags_never_auto():
    args = dict(_ALL_CLEAR, substantiated_flags=1)
    assert policy.may_auto_process("invoice_processing", **args) is False


def test_reserved_actions_cover_the_two_hard_exclusions():
    """FAR 43.102 mod execution + the irreversible money path stay reserved."""
    assert "modification_execution" in policy.RESERVED_ACTIONS
    assert "payment_certification" in policy.RESERVED_ACTIONS

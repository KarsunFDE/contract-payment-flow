"""
test_auto_approval_policy.py — default-deny auto-approval (m3.md Step 7.3, REQ-AGT-6).

The policy is the single bounded gate, so the tests pin every way it must say "no"
and the one way it says "yes".
"""
from __future__ import annotations

import pytest

from app.workflow import auto_approval_policy as policy

# A fully clean call — the only combination that may auto-process.
_CLEAN = dict(
    reversible=True,
    within_delegated_authority=True,
    amount=100.0,
    threshold=1000.0,
    substantiated_flags=0,
)


def test_clean_reversible_action_auto_processes():
    assert policy.may_auto_process("invoice_intake_ack", **_CLEAN) is True


@pytest.mark.parametrize("action", sorted(policy.RESERVED_ACTIONS))
def test_reserved_actions_never_auto_process(action):
    """Reserved/irreversible actions are excluded even when every other gate passes."""
    assert policy.may_auto_process(action, **_CLEAN) is False


def test_any_single_failing_gate_blocks():
    assert policy.may_auto_process("ack", **{**_CLEAN, "reversible": False}) is False
    assert policy.may_auto_process("ack", **{**_CLEAN, "within_delegated_authority": False}) is False
    assert policy.may_auto_process("ack", **{**_CLEAN, "amount": 5000.0}) is False
    assert policy.may_auto_process("ack", **{**_CLEAN, "substantiated_flags": 1}) is False

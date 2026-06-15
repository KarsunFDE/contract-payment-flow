"""
auto_approval_policy.py — explicit, bounded, default-deny auto-approval (m3.md Step 7.3,
REQ-AGT-6).

The conditions under which the system may auto-act are written down here and testable,
never implicit. `may_auto_process` returns True ONLY when every gate holds; any unmet or
uncertain condition returns False -> escalate. Reserved and irreversible actions are HARD
exclusions — model confidence cannot override them (REQ-AGT-2, "authority over accuracy").
"""
from __future__ import annotations

# Actions that NEVER auto-process, regardless of confidence or any other gate.
RESERVED_ACTIONS = {
    "modification_execution",  # FAR 43.102 — only the CO executes a modification
    "payment_certification",   # irreversible money path
}


def may_auto_process(
    action: str,
    *,
    reversible: bool,
    within_delegated_authority: bool,
    amount: float,
    threshold: float,
    substantiated_flags: int,
) -> bool:
    """True only if ALL conditions hold. Hard-excludes reserved/irreversible actions."""
    if action in RESERVED_ACTIONS:
        return False  # never auto-process a reserved action, regardless of confidence
    if not reversible:
        return False
    if not within_delegated_authority:
        return False
    if amount > threshold:
        return False
    if substantiated_flags > 0:
        return False
    return True  # all gates clear -> auto lane

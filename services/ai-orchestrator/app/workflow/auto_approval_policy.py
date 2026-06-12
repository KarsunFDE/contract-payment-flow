"""
auto_approval_policy.py — Person B: the bounded auto-approval policy (m3.md
Step 7.3 — task B4).

REQ-AGT-6: the conditions under which the system may auto-act are WRITTEN DOWN
and testable, not implicit. Pure function, default-deny: True only when every
gate passes; any unmet or uncertain condition -> escalate. Reserved and
irreversible actions are hard exclusions — model confidence cannot override
them (REQ-AGT-2, "authority over accuracy").
"""
from __future__ import annotations

import os

RESERVED_ACTIONS = {
    "modification_execution",   # FAR 43.102 — only the CO executes a mod
    "payment_certification",    # irreversible money path
}

# Dollar ceiling for the auto lane (micro-purchase-threshold default).
# Env-overridable so an agency can tighten it without a code change.
AUTO_PROCESS_THRESHOLD_USD = float(
    os.environ.get("AUTO_PROCESS_THRESHOLD_USD", "10000")
)


def may_auto_process(action: str, *, reversible: bool,
                     within_delegated_authority: bool, amount: float,
                     threshold: float, substantiated_flags: int) -> bool:
    """True only if ALL hold. Hard-excludes reserved / irreversible actions."""
    if action in RESERVED_ACTIONS:      return False   # never, regardless of confidence
    if not reversible:                  return False
    if not within_delegated_authority:  return False
    if amount > threshold:              return False
    if substantiated_flags > 0:         return False
    return True                                         # all gates clear -> auto lane

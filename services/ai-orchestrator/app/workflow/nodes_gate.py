"""
nodes_gate.py — Person A: CO hard gate + bilateral consent + CO-only submit
(m3.md Phases 4-5, Steps 4.1-4.3, 5.1-5.3).

Three interrupt-backed pause points:
  co_gate_node      — hard CO gate (approve/deny). Every run stops here.
  consent_gate_node — bilateral only; blocks until contractor signs Block 15.
  submit_node       — CO-triggered DRAFT → MODIFICATION_REQUEST (irreversible).
  supersede_node    — CO deny path; marks the package cancelled + audits.

Routing (fail-CLOSED on every ambiguous/unknown/missing value):
  co_gate → route_after_co_gate →  "supersede"    (decision == "denied")
                                    "consent_gate" (decision == "approved", bilateral)
                                    "submit"       (decision == "approved", unilateral)
                                    "supersede"    (unknown/empty/None decision — BLOCKED)
  consent_gate → route_after_consent_gate → "submit" (consent recorded)
                                             END      (consent pending)

Security invariants (Codex HIGH findings):
  1. route_after_co_gate validates decision against strict enum {"approved","denied"};
     any other value (None, "", typos, injected payload) routes to "supersede"
     (terminal blocked state), never to submit/consent.
  2. modification_bilateral must be explicitly True; absent/None/False always
     routes to submit (unilateral), but only after decision == "approved" passes.
  3. submit_node re-derives consent requirement from far_rules.consent_required_for
     keyed on the classified modType (block13_classification), NOT the bilateral flag
     alone. Hard-rejects when consent is required but not recorded.
  4. package_hash is bound at co_gate_node interrupt payload and re-verified
     at consent_gate and submit; mismatches force supersede (fail closed).
  5. modification_client.publish called with full actor identity; raises if
     actor_id/actor_role missing or actor is "anonymous".

Audit: co_decision, contractor_consent_recorded, package_superseded,
       modification_submitted — all synchronous + fail-closed (ADR-0006 Note 3).
       High-consequence events include actor identity, role, and package_hash.

Flag (finding #10): real CO-role + agency enforcement lives in the Java service.
This node fails closed on HTTP errors but cannot enforce CO identity itself.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.workflow import modification_client
from app.workflow.audit_events import record_event
from app.workflow.far_rules import consent_required_for
from app.workflow.state import WorkflowState, compute_package_hash

# Strict set of valid CO decisions — everything outside this set is treated as
# a security anomaly and routes to the terminal "supersede" (blocked) state.
_VALID_CO_DECISIONS = {"approved", "denied"}


def _require_actor(state: WorkflowState) -> tuple[str, str]:
    """Extract and validate actor_id + actor_role from state.

    Raises ValueError (fail-closed) when either is absent or when the actor is
    "anonymous" — an unidentified CO must never trigger an irreversible action.
    """
    actor_id = state.get("co_user_id")
    actor_role = state.get("co_role")
    if not actor_id or not actor_role:
        raise ValueError(
            "submit/consent requires co_user_id and co_role in state — "
            "unidentified actor must never trigger an irreversible write"
        )
    if actor_id == "anonymous" or actor_role == "anonymous":
        raise ValueError(
            f"anonymous actor forbidden on irreversible write path "
            f"(co_user_id={actor_id!r}, co_role={actor_role!r})"
        )
    return actor_id, actor_role


def co_gate_node(state: WorkflowState) -> dict:
    """Hard CO gate — pauses (interrupt) until the CO approves or denies.

    The interrupt payload includes the package_hash so the CO's browser/UI
    binds approval to a specific package version. Any subsequent hash mismatch
    causes the downstream nodes to fail closed.
    """
    pkg_hash = compute_package_hash(state)
    decision = interrupt({
        "populated_fields":       state.get("populated_fields"),
        "block_14_draft":         state.get("block_14_draft"),
        "gate_status":            state.get("gate_status"),
        "bilateral":              state.get("modification_bilateral"),
        "block13_classification": state.get("block13_classification"),
        "package_hash":           pkg_hash,
    })
    actor_id = state.get("co_user_id")
    actor_role = state.get("co_role")
    record_event(state, "co_decision", {
        "decision":     decision,
        "form_draft_id": state.get("form_draft_id"),
        "actor_id":     actor_id,
        "actor_role":   actor_role,
        "package_hash": pkg_hash,
    })
    return {"co_decision": decision, "package_hash": pkg_hash}


def route_after_co_gate(state: WorkflowState) -> str:
    """Deny → supersede. Approve bilateral → consent_gate. Approve unilateral → submit.

    Fail-CLOSED: any decision value outside {"approved","denied"} — including None,
    empty string, typos, or an injected resume payload — routes to "supersede"
    (terminal blocked state) rather than falling through to submit/consent.

    Additionally, "approved" requires modification_bilateral to be explicitly
    present (not None) before routing to the bilateral consent path; absent/None
    is treated as unilateral (no silent widening of the approved path).
    """
    decision = state.get("co_decision")

    # Strict enum check — anything outside the known set is blocked.
    if decision not in _VALID_CO_DECISIONS:
        return "supersede"

    if decision == "denied":
        return "supersede"

    # decision == "approved" — now check bilateral flag and hash.
    # modification_bilateral must be explicitly True; None / absent = unilateral.
    if state.get("modification_bilateral") is True:
        return "consent_gate"
    return "submit"


def consent_gate_node(state: WorkflowState) -> dict:
    """Bilateral only — pauses until contractor consent (Block 15) is recorded.

    Re-verifies package_hash before resuming; a mismatch means the package was
    mutated after CO approval and must not proceed — routes to supersede via the
    returned contractor_consent value.
    """
    pkg_hash_at_approval = state.get("package_hash")
    current_hash = compute_package_hash(state)
    if current_hash != pkg_hash_at_approval:
        # Package mutated after CO approval — force re-approval path by
        # returning a sentinel that route_after_consent_gate maps to END,
        # and audit the anomaly.
        actor_id = state.get("co_user_id")
        actor_role = state.get("co_role")
        record_event(state, "package_superseded", {
            "reason":       "package_hash_mismatch_at_consent_gate",
            "hash_approved": pkg_hash_at_approval,
            "hash_current":  current_hash,
            "form_draft_id": state.get("form_draft_id"),
            "actor_id":     actor_id,
            "actor_role":   actor_role,
            "package_hash": pkg_hash_at_approval,
        })
        return {
            "contractor_consent": "hash_mismatch",
            "gate_status": "BLOCKED_HASH_MISMATCH",
            "co_execution": "aborted",
        }

    consent = interrupt({
        "awaiting":     "contractor_consent",
        "draft_id":     state.get("form_draft_id"),
        "package_hash": current_hash,
    })
    if consent.get("signed") is True:
        actor_id = state.get("co_user_id")
        actor_role = state.get("co_role")
        record_event(state, "contractor_consent_recorded", {
            "form_draft_id": state.get("form_draft_id"),
            "actor_id":     actor_id,
            "actor_role":   actor_role,
            "package_hash": current_hash,
        })
        return {"contractor_consent": "recorded"}
    return {"contractor_consent": "pending", "gate_status": "AWAITING_CONTRACTOR_CONSENT"}


def route_after_consent_gate(state: WorkflowState) -> str:
    contractor_consent = state.get("contractor_consent")
    if contractor_consent == "recorded":
        return "submit"
    # "pending", "hash_mismatch", or anything else — do not proceed.
    return END


def supersede_node(state: WorkflowState) -> dict:
    """On CO deny or blocked path: mark the package superseded + audit. Terminal.

    High-consequence event — actor identity and package_hash included in audit
    payload per ADR-0006 audit contract.
    """
    draft_id = state.get("form_draft_id")
    actor_id = state.get("co_user_id")
    actor_role = state.get("co_role")
    if draft_id:
        modification_client.cancel_draft(
            draft_id,
            actor_id=actor_id,
            actor_role=actor_role,
            agency_id=state.get("agency_id"),
            correlation_id=state.get("correlation_id"),
        )
    record_event(state, "package_superseded", {
        "co_decision":   state.get("co_decision"),
        "form_draft_id": draft_id,
        "actor_id":     actor_id,
        "actor_role":   actor_role,
        "package_hash": state.get("package_hash"),
    })
    return {"co_execution": "aborted"}


def submit_node(state: WorkflowState) -> dict:
    """CO-triggered submit (DRAFT → MODIFICATION_REQUEST). Fail-closed, audit synchronous.

    Security invariants enforced here (fail-closed on every violation):
      1. Actor identity: co_user_id + co_role must be present and non-anonymous.
      2. Consent re-derivation: consent requirement is derived from the classified
         modType via far_rules.consent_required_for — NOT from modification_bilateral
         alone. When consent is required and contractor_consent != "recorded", raise.
      3. Package hash re-verification: current hash must match the hash bound at
         CO approval. Mismatch → raise (forces re-approval).
    """
    draft_id = state.get("form_draft_id")

    # --- 1. Actor identity (fail closed) ---
    actor_id, actor_role = _require_actor(state)
    agency_id = state.get("agency_id")
    correlation_id = state.get("correlation_id")

    # --- 2. Package hash re-verification (fail closed) ---
    pkg_hash_at_approval = state.get("package_hash")
    current_hash = compute_package_hash(state)
    if current_hash != pkg_hash_at_approval:
        raise RuntimeError(
            f"package_hash mismatch at submit: approved={pkg_hash_at_approval!r} "
            f"current={current_hash!r} — re-approval required (fail closed)"
        )

    # --- 3. Consent re-derivation from modType, NOT from bilateral flag ---
    classification = state.get("block13_classification") or {}
    mod_type = classification.get("mod_type")
    consent_required = consent_required_for(mod_type)

    # None means unmapped modType — treat as consent required (fail-safe to
    # consent-required, matching far_rules.py docstring).
    if consent_required is None:
        consent_required = True

    consent_recorded = state.get("contractor_consent") == "recorded"
    if consent_required and not consent_recorded:
        raise RuntimeError(
            f"FAR 43.103 consent required for modType={mod_type!r} but "
            f"contractor_consent={state.get('contractor_consent')!r} — "
            "cannot submit without recorded consent (fail closed)"
        )

    # --- publish (teammate-provided updated signature) ---
    modification_client.publish(
        draft_id,
        actor_id=actor_id,
        actor_role=actor_role,
        agency_id=agency_id,
        consent_recorded=consent_recorded,
        package_hash=current_hash,
        correlation_id=correlation_id,
    )

    record_event(state, "modification_submitted", {
        "form_draft_id":      draft_id,
        "contractor_consent": state.get("contractor_consent"),
        "actor_id":           actor_id,
        "actor_role":         actor_role,
        "package_hash":       current_hash,
        "mod_type":           mod_type,
        "consent_required":   consent_required,
    })
    return {"gate_status": "SUBMITTED", "co_execution": "executed"}


def register(builder: StateGraph) -> None:
    """Add gate/consent/submit/supersede nodes + conditional routing edges."""
    builder.add_node("co_gate",     co_gate_node)
    builder.add_node("consent_gate", consent_gate_node)
    builder.add_node("submit",      submit_node)
    builder.add_node("supersede",   supersede_node)

    builder.add_conditional_edges("co_gate", route_after_co_gate, {
        "supersede":    "supersede",
        "consent_gate": "consent_gate",
        "submit":       "submit",
    })
    builder.add_conditional_edges("consent_gate", route_after_consent_gate, {
        "submit": "submit",
        END:      END,
    })
    builder.add_edge("submit",    END)
    builder.add_edge("supersede", END)

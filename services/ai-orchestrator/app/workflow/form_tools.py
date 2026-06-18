"""form_tools.py — allow-listed write tools for the SF-30 draft (m3.md Phase 3).

Two functions, each writing one slice of the ContractModification DRAFT (never
the live record). There is NO submit tool — submission is a CO-only UI action
(ADR-0006 §"Form-Fill Tool Layer"). assemble_form_node calls these; nothing else
may write to the draft.

Fields map to ContractModification.java:
  contractNumber, modificationNumber, modType, farAuthority, effectiveDate,
  agencyId, description, sections.{changeNarrative, priceCostImpact, fundingCitation}

Identity hardening (Codex PR #9): every patch_draft call now forwards the
verified actor identity (actor_id, actor_role, agency_id, correlation_id) so
the Java service can enforce CO-role + agency isolation server-side.  Callers
MUST supply these from verified workflow state — never from the request body.
"""
from __future__ import annotations

from app.workflow import modification_client


def set_modification_basics(
    draft_id: str,
    contract_number: str,
    modification_number: str,
    mod_type: str,
    far_authority: str,
    effective_date: str,
    *,
    actor_id: str,
    actor_role: str,
    agency_id: str,
    correlation_id: str,
) -> None:
    """SF-30 blocks 1, 2, 3, 10A, 13 → ContractModification DRAFT."""
    modification_client.patch_draft(
        draft_id,
        {
            "contractNumber":     contract_number,
            "modificationNumber": modification_number,
            "modType":            mod_type,
            "farAuthority":       far_authority,
            "effectiveDate":      effective_date,
            "agencyId":           agency_id,
        },
        actor_id=actor_id,
        actor_role=actor_role,
        agency_id=agency_id,
        correlation_id=correlation_id,
    )


def set_block_14_rationale(
    draft_id: str,
    narrative: str,
    price_cost_impact: str,
    funding_citation: str,
    *,
    actor_id: str,
    actor_role: str,
    agency_id: str,
    correlation_id: str,
) -> None:
    """SF-30 block 14 → description + sections on the DRAFT."""
    modification_client.patch_draft(
        draft_id,
        {
            "description": narrative,
            "sections": {
                "changeNarrative":  narrative,
                "priceCostImpact":  price_cost_impact,
                "fundingCitation":  funding_citation,
            },
        },
        actor_id=actor_id,
        actor_role=actor_role,
        agency_id=agency_id,
        correlation_id=correlation_id,
    )

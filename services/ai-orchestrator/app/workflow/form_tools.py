"""form_tools.py — allow-listed write tools for the SF-30 draft (m3.md Phase 3).

Two functions, each writing one slice of the ContractModification DRAFT (never
the live record). There is NO submit tool — submission is a CO-only UI action
(ADR-0006 §"Form-Fill Tool Layer"). assemble_form_node calls these; nothing else
may write to the draft.

Fields map to ContractModification.java:
  contractNumber, modificationNumber, modType, farAuthority, effectiveDate,
  agencyId, description, sections.{changeNarrative, priceCostImpact, fundingCitation}
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
    agency_id: str,
) -> None:
    """SF-30 blocks 1, 2, 3, 10A, 13 → ContractModification DRAFT."""
    modification_client.patch_draft(draft_id, {
        "contractNumber":     contract_number,
        "modificationNumber": modification_number,
        "modType":            mod_type,
        "farAuthority":       far_authority,
        "effectiveDate":      effective_date,
        "agencyId":           agency_id,
    })


def set_block_14_rationale(
    draft_id: str,
    narrative: str,
    price_cost_impact: str,
    funding_citation: str,
) -> None:
    """SF-30 block 14 → description + sections on the DRAFT."""
    modification_client.patch_draft(draft_id, {
        "description": narrative,
        "sections": {
            "changeNarrative":  narrative,
            "priceCostImpact":  price_cost_impact,
            "fundingCitation":  funding_citation,
        },
    })

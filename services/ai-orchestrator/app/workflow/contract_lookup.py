"""contract_lookup.py — deterministic contract-of-record resolution (m3.md Step 1.4).

find_by_number is the sole entry point. It delegates to the injected SamGovClient
(mock in Phase 1, live adapter later) and converts the raw response into the
WorkflowState record shape that lookup_node, validate_lookup_node, and
populate_fields_node all read from.

Agency scope is enforced IN THE QUERY, not here — the client is responsible for
filtering by agency_id (ADR-0005 §11). _to_record maps the SAM.gov Contract Awards
+ Entity Management API fields to the SF-30 block positions.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.workflow.clients import SamGovClient


def find_by_number(contract_number: str, agency_id: str, client: SamGovClient) -> dict:
    """Resolve the contract-of-record. Returns a record dict with match + static_fields.

    Outcomes:
      {"match": "found",      "static_fields": {...}, "source_citation": {...}}
      {"match": "not_found"}
      {"match": "ambiguous"}

    Agency scope is part of the client query — a CO can never resolve another
    agency's contract (ADR-0005 §11 tenant isolation).
    """
    matches = client.get_award(contract_number, agency_id)

    if len(matches) == 0:
        return {"match": "not_found"}
    if len(matches) > 1:
        return {"match": "ambiguous"}
    return _to_record(matches[0])


def _to_record(award: dict) -> dict:
    """Convert a SAM.gov award document to the WorkflowState record shape.

    The Phase-1 mock reads the seeded `contracts` collection (scripts/seed_contracts.py),
    which already stores the SF-30 `static_fields` + `source_citation` — so the common
    path is a pass-through. The raw-field fallback below maps a live SAM.gov Contract
    Awards / Entity Management response (piid, effectiveDate, entity, …) for the later
    client-internal swap to the live adapter, with no change to lookup_node.
    """
    # Seed / pre-shaped path: the document already carries the block map + citation.
    if "static_fields" in award:
        return {
            "match": "found",
            "source_citation": award.get("source_citation", {}),
            "static_fields": award["static_fields"],
        }

    # Live SAM.gov path: map raw award + entity fields to the SF-30 blocks.
    entity = award.get("entity", {})
    citation = {
        "system": "sam.gov",
        "record_id": award.get("awardId", award.get("contractNumber")),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    return {
        "match": "found",
        "source_citation": citation,
        "static_fields": {
            "2":   award.get("contractNumber", ""),
            "3":   award.get("effectiveDate", ""),
            "6":   award.get("issuedBy", ""),
            "7":   award.get("administeredBy", ""),
            "8":   {
                "name":    entity.get("legalBusinessName", ""),
                "uei":     entity.get("ueiSAM", ""),
                "cage":    entity.get("cageCode", ""),
                "address": entity.get("physicalAddress", {}),
            },
            "10A": award.get("acrn", ""),
            "10B": award.get("totalContractValue", ""),
            "12":  award.get("accountingData", ""),
        },
    }

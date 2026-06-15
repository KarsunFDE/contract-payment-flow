"""mock_sam_gov_client.py — Phase 1 mock for the SAM.gov client (m3.md Step 1.4).

Reads from the seeded `contracts` collection (agency-scoped, SAM.gov Contract
Awards API shape). Tenant isolation is enforced in the MongoDB query — a CO
can never resolve another agency's contract (ADR-0005 §11).

Phase 1 ships this mock per PRD §4 (live SAM.gov verification is a non-goal).
The live adapter is a later client-internal swap; lookup_node does not change.
"""
from __future__ import annotations

from app import db


class MockSamGovClient:
    """Serves the Contract Awards response shape from the seeded contracts collection."""

    def get_award(self, contract_number: str, agency_id: str) -> list[dict]:
        return list(db.get_db()["contracts"].find(
            {"contractNumber": contract_number, "agencyId": agency_id},
            {"_id": 0},
        ))

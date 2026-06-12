"""
seed_contracts.py — Foundation seed for the contract-of-record lookup (m3.md
Phase 1, finding #4 in the task-split doc).

The ai-orchestrator Mongo has no contract records (those live in the Java
contract-modification-service). The mock SAM.gov client reads
`db.get_db()["contracts"]`, so this script seeds a few agency-scoped records
SHAPED like a SAM.gov Contract Awards response — enough for A1/A2 to build and
test lookup against.

Idempotent: upserts by (contractNumber, agencyId). Run inside the container:
    python -m scripts.seed_contracts

NOTE: synthetic data only (PRD §10 — no live PII).
"""
from __future__ import annotations

import logging

from app import db

log = logging.getLogger("ai-orchestrator.seed.contracts")

CONTRACTS_COLLECTION = "contracts"

# Synthetic contract-of-record fixtures. `static_fields` are the SF-30 blocks the
# lookup auto-fills (ADR-0005 §4 / ADR-0006); `source_citation` is the provenance
# the populate step attaches to each field.
_SEED_CONTRACTS: list[dict] = [
    {
        "contractNumber": "GS-35F-0001V",
        "agencyId": "agency-gsa",
        "static_fields": {
            "1": "GS-35F-0001V",            # Contract ID No.
            "2": "P00003",                   # next modification no. in the mod history
            "3": "2026-06-15",               # effective date
            "6": "GSA FAS Region 4",         # issued by
            "7": "GSA FAS Region 4",         # administered by
            "8": "Acme Integration LLC, 100 Main St, Atlanta GA 30303",  # contractor
            "10A": "GS-35F-0001V",           # contract/order no. being modified
            "10B": "2024-01-10",             # dated
            "12": "Appropriation 47X0535.202601",  # accounting & appropriation data
        },
        "source_citation": {
            "system": "SAM.gov",             # live source later; mock-backed now
            "record_id": "PIID:GS-35F-0001V",
            "fetched_at": "2026-06-12T00:00:00Z",
        },
    },
    {
        "contractNumber": "W912DY-24-C-0042",
        "agencyId": "agency-usace",
        "static_fields": {
            "1": "W912DY-24-C-0042",
            "2": "A00001",
            "3": "2026-07-01",
            "6": "USACE Huntsville",
            "7": "DCMA Atlanta",
            "8": "Beacon Civil Works Inc, 22 Harbor Rd, Mobile AL 36602",
            "10A": "W912DY-24-C-0042",
            "10B": "2024-03-22",
            "12": "Appropriation 96X3121.202607",
        },
        "source_citation": {
            "system": "SAM.gov",
            "record_id": "PIID:W912DY-24-C-0042",
            "fetched_at": "2026-06-12T00:00:00Z",
        },
    },
]


def seed() -> int:
    """Upsert the synthetic contracts. Returns the number of records seeded."""
    collection = db.get_db()[CONTRACTS_COLLECTION]
    for record in _SEED_CONTRACTS:
        # Upsert keyed on (contractNumber, agencyId) so re-running is a no-op.
        collection.update_one(
            {"contractNumber": record["contractNumber"], "agencyId": record["agencyId"]},
            {"$set": record},
            upsert=True,
        )
    log.info("seeded %d contract-of-record fixtures into %r",
             len(_SEED_CONTRACTS), CONTRACTS_COLLECTION)
    return len(_SEED_CONTRACTS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = seed()
    print(f"seeded {count} contracts into '{CONTRACTS_COLLECTION}'")

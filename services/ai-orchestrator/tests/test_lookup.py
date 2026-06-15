"""
test_lookup.py — SAM.gov mock client + lookup nodes (m3.md Phase 1, Steps 1.1-1.4).

MongoDB and audit_events are stubbed; tests pin node behaviour and contract_lookup
logic, not I/O. The seeded record shape mirrors scripts/seed_contracts.py.
"""
from __future__ import annotations

from app.workflow import contract_lookup, nodes_lookup
from app.workflow.contract_lookup import _to_record

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# Pre-shaped record as seeded by scripts/seed_contracts.py (Foundation, finding #4).
_SEEDED = {
    "contractNumber": "GS-35F-0001V",
    "agencyId": "agency-gsa",
    "static_fields": {
        "1": "GS-35F-0001V",
        "2": "P00003",
        "3": "2026-06-15",
        "6": "GSA FAS Region 4",
        "8": "Acme Integration LLC, 100 Main St, Atlanta GA 30303",
        "10A": "GS-35F-0001V",
    },
    "source_citation": {
        "system": "SAM.gov",
        "record_id": "PIID:GS-35F-0001V",
        "fetched_at": "2026-06-12T00:00:00Z",
    },
}

# Raw SAM.gov Contract Awards / Entity shape (the later live-adapter fallback path).
_RAW_AWARD = {
    "contractNumber": "W911QY-21-C-0001",
    "agencyId": "DOD",
    "awardId": "award-1",
    "effectiveDate": "2021-01-01",
    "totalContractValue": 500_000,
    "acrn": "AA",
    "entity": {"legalBusinessName": "ACME Corp", "ueiSAM": "UEI123", "cageCode": "CAGE1"},
}

_STATE = {
    "correlation_id": "corr-1",
    "agency_id": "agency-gsa",
    "contract_number": "GS-35F-0001V",
    "change_request": {"scope": "extend PoP", "agency_id": "agency-gsa"},
}


class _MockClient:
    def __init__(self, records):
        self._records = records

    def get_award(self, contract_number, agency_id):
        return [
            r for r in self._records
            if r["contractNumber"] == contract_number and r["agencyId"] == agency_id
        ]


# ---------------------------------------------------------------------------
# contract_lookup.find_by_number
# ---------------------------------------------------------------------------

def test_find_by_number_not_found():
    result = contract_lookup.find_by_number("UNKNOWN", "agency-gsa", _MockClient([]))
    assert result == {"match": "not_found"}


def test_find_by_number_ambiguous():
    client = _MockClient([_SEEDED, {**_SEEDED, "source_citation": {"record_id": "dup"}}])
    result = contract_lookup.find_by_number("GS-35F-0001V", "agency-gsa", client)
    assert result == {"match": "ambiguous"}


def test_find_by_number_found_seeded_shape():
    result = contract_lookup.find_by_number("GS-35F-0001V", "agency-gsa", _MockClient([_SEEDED]))
    assert result["match"] == "found"
    # static_fields + source_citation pass through unchanged from the seed.
    assert result["static_fields"]["2"] == "P00003"
    assert result["static_fields"]["8"].startswith("Acme Integration LLC")
    assert result["source_citation"]["record_id"] == "PIID:GS-35F-0001V"


def test_find_by_number_cross_agency_returns_not_found():
    # GSA contract requested under a different agency -> client filter yields nothing.
    result = contract_lookup.find_by_number("GS-35F-0001V", "agency-usace", _MockClient([_SEEDED]))
    assert result == {"match": "not_found"}


# ---------------------------------------------------------------------------
# _to_record — both the seeded pass-through and the raw-award fallback
# ---------------------------------------------------------------------------

def test_to_record_seeded_passthrough():
    record = _to_record(_SEEDED)
    assert record["match"] == "found"
    assert record["static_fields"] is _SEEDED["static_fields"]
    assert record["source_citation"] == _SEEDED["source_citation"]


def test_to_record_raw_award_fallback():
    record = _to_record(_RAW_AWARD)
    assert record["match"] == "found"
    assert record["static_fields"]["2"] == "W911QY-21-C-0001"
    assert record["static_fields"]["8"]["name"] == "ACME Corp"
    assert record["static_fields"]["10A"] == "AA"
    assert record["source_citation"]["system"] == "sam.gov"


# ---------------------------------------------------------------------------
# validate_lookup_node
# ---------------------------------------------------------------------------

def test_validate_lookup_ok():
    assert nodes_lookup.validate_lookup_node({"contract_record": {"match": "found"}}) == {
        "gate_status": "OK"
    }


def test_validate_lookup_not_found():
    result = nodes_lookup.validate_lookup_node({"contract_record": {"match": "not_found"}})
    assert result["gate_status"] == "CONTRACT_NOT_FOUND_AWAITING_CO_REVIEW"


def test_validate_lookup_ambiguous():
    result = nodes_lookup.validate_lookup_node({"contract_record": {"match": "ambiguous"}})
    assert result["gate_status"] == "CONTRACT_NOT_FOUND_AWAITING_CO_REVIEW"


# ---------------------------------------------------------------------------
# populate_fields_node
# ---------------------------------------------------------------------------

def test_populate_fields_wraps_each_block_with_citation(monkeypatch):
    monkeypatch.setattr(nodes_lookup, "record_event", lambda *a, **k: None)
    record = _to_record(_SEEDED)
    result = nodes_lookup.populate_fields_node({**_STATE, "contract_record": record})
    pf = result["populated_fields"]
    assert pf["2"]["value"] == "P00003"
    assert pf["3"]["value"] == "2026-06-15"
    assert pf["2"]["source_citation"]["record_id"] == "PIID:GS-35F-0001V"


def test_populate_fields_empty_static_fields(monkeypatch):
    monkeypatch.setattr(nodes_lookup, "record_event", lambda *a, **k: None)
    result = nodes_lookup.populate_fields_node(
        {**_STATE, "contract_record": {"match": "found", "static_fields": {}, "source_citation": {}}}
    )
    assert result["populated_fields"] == {}


# ---------------------------------------------------------------------------
# lookup_node
# ---------------------------------------------------------------------------

def test_lookup_node_found(monkeypatch):
    monkeypatch.setattr(nodes_lookup, "_sam_gov", _MockClient([_SEEDED]))
    monkeypatch.setattr(nodes_lookup, "record_event", lambda *a, **k: None)
    result = nodes_lookup.lookup_node(_STATE)
    assert result["contract_record"]["match"] == "found"


def test_lookup_node_not_found(monkeypatch):
    monkeypatch.setattr(nodes_lookup, "_sam_gov", _MockClient([]))
    monkeypatch.setattr(nodes_lookup, "record_event", lambda *a, **k: None)
    result = nodes_lookup.lookup_node(_STATE)
    assert result["contract_record"]["match"] == "not_found"

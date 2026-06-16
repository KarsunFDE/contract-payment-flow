"""
clients.py — interface contracts for the workflow's external dependencies.

Frozen after Foundation. Defines the SHAPES both workstreams code against, so the
real implementations land independently behind a stable signature:
  - Person A implements `SamGovClient` (mock now, live SAM.gov adapter later).
  - Person B implements `RetrieveClient` (wraps the ADR-0005 /retrieve pipeline).

These are typing.Protocol contracts — no runtime base class to inherit; any class
with matching methods satisfies them (structural typing).
"""
from __future__ import annotations

from typing import Protocol


class SamGovClient(Protocol):
    """Contract-of-record lookup, shaped to the official SAM.gov API.

    Called PROGRAMMATICALLY from lookup_node — never an AI/agent tool (ADR-0006,
    "Lookup is not an LLM step"). Phase 1 ships a mock implementing this Protocol;
    the live SAM.gov adapter is a later client-internal swap.
      Contract Awards API:   https://open.gsa.gov/api/contract-awards/
      Entity Management API: https://open.gsa.gov/api/entity-api/
    """

    def get_award(self, contract_number: str, agency_id: str) -> list[dict]:
        """Return 0, 1, or many award records matching (contract_number, agency_id).

        `agency_id` is part of the query (tenant isolation, ADR-0005 §11) — a CO
        can never resolve another agency's contract.
        """
        ...


class RetrieveClient(Protocol):
    """The ADR-0005 grounded retrieval read path (the POST /retrieve pipeline:
    hybrid search -> RRF fusion -> cross-encoder rerank -> fail-closed audit).

    Threads gateway-asserted identity + correlation_id (ADR-0005 §11). NOTE:
    `contract_id` is AUDIT METADATA ONLY, never a retrieval filter (ADR-0005 §11);
    tenant scope is `agency_id`. This is why the signature does not let the caller
    filter the corpus by contract.
    """

    def retrieve(
        self,
        query: str,
        *,
        sf30_block: str,
        agency_id: str,
        user_id: str,
        role: str,
        correlation_id: str | None = None,
        contract_id: str | None = None,
    ) -> list[dict]:
        """Return reranked chunks: [{chunk_id, chunk_text, score, source_document}]."""
        ...

"""
retrieve_client.py — Person B: the workflow's view of the ADR-0005 read path.

The Block 14 sub-pipeline and the triage adjudicator both need grounded FAR
retrieval. Rather than re-roll hybrid search + RRF + rerank + fail-closed audit
(finding #5), this wraps the existing POST /retrieve core in app/retrieval/router.py
and calls it IN-PROCESS — same pipeline, same audit trail.

Identity is threaded the way /retrieve demands (ADR-0005 §11): tenant = agency_id,
plus the acting CO's user_id + role + the run's correlation_id. `contract_id` is
AUDIT METADATA ONLY — it never filters the corpus (ADR-0005 §11), which is why it
is optional here and is not used as a query filter.
"""
from __future__ import annotations

import logging

log = logging.getLogger("ai-orchestrator.workflow.retrieve")


class RetrieveError(RuntimeError):
    """Raised when the read path cannot return audited results (identity rejected,
    both retrieval paths down, audit write failed). Callers fail closed -> CO review."""


def retrieve(
    query: str,
    *,
    sf30_block: str,
    agency_id: str,
    user_id: str,
    role: str,
    correlation_id: str | None = None,
    contract_id: str | None = None,
) -> list[dict]:
    """Run one grounded retrieval through the ADR-0005 /retrieve core.

    Returns the reranked chunks as plain dicts
    [{chunk_id, chunk_text, score, source_document}]. Raises RetrieveError on any
    failure the endpoint signals as fail-closed (HTTP 4xx/5xx).
    """
    # Imported lazily: app.retrieval.router pulls in FastAPI + the retrieval stack,
    # so deferring the import keeps this module cheap to import (and unit-testable
    # by monkeypatching `retrieve`) without loading the whole read path.
    from fastapi import HTTPException
    from pydantic import ValidationError
    from app.retrieval.router import RetrieveRequest, retrieve as retrieve_endpoint

    try:
        # Build + validate the request, THEN call the endpoint — both inside this
        # try on purpose. RetrieveRequest enforces the ADR-0005 input rules (query
        # must be 1-2000 chars, sf30_block must match a shape, etc.), so a bad or
        # empty query raises pydantic ValidationError right here, before the call.
        # We turn that into a RetrieveError — the same error type an endpoint
        # failure raises — so the calling node's existing `except RetrieveError`
        # keeps the graph fail-closed (route to CO review) instead of crashing on
        # an unhandled ValidationError.
        request = RetrieveRequest(
            query=query,
            sf30_block=sf30_block,
            # contract_id is required by the request model but is audit metadata
            # only; use a non-empty placeholder when the caller has no contract.
            contract_id=contract_id or "unspecified",
            correlation_id=correlation_id,
        )
        # Call the endpoint function directly, passing the gateway-asserted identity
        # the same way the HTTP layer would inject it from the verified JWT claims.
        response = retrieve_endpoint(
            request,
            x_tenant_id=agency_id,
            x_user_id=user_id,
            x_user_role=role,
        )
    except ValidationError as exc:
        log.warning("retrieve request rejected as invalid (%s) — correlation_id=%s",
                    exc, correlation_id)
        raise RetrieveError(f"invalid retrieval request: {exc}") from exc
    except HTTPException as exc:
        log.warning("retrieve failed (%s) — correlation_id=%s", exc.detail, correlation_id)
        raise RetrieveError(str(exc.detail)) from exc

    return [chunk.model_dump() for chunk in response.chunks]


def retrieve_for_state(state: dict, query: str, sf30_block: str) -> list[dict]:
    """Convenience wrapper that pulls the run's identity off the workflow state.

    The acting CO's identity rides in `change_request` (gateway-asserted at request
    entry, alongside correlation_id), so every workflow node retrieves with the same
    threaded tenant + user + role + correlation_id without repeating the plumbing.
    """
    change = state.get("change_request", {})
    return retrieve(
        query,
        sf30_block=sf30_block,
        agency_id=state["agency_id"],
        user_id=change.get("co_user_id", ""),
        role=change.get("co_role", ""),
        correlation_id=state.get("correlation_id"),
        contract_id=state.get("contract_number"),
    )

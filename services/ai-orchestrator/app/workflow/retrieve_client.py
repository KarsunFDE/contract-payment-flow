"""
retrieve_client.py — Person B: the workflow's grounded-retrieval client (task B2).

Implements the frozen `RetrieveClient` Protocol (clients.py) by calling the REAL
ADR-0005 read path in-process — `app/retrieval/router.py:retrieve()` — so the
workflow reuses hybrid search -> RRF fusion -> cross-encoder rerank -> fail-closed
audit instead of re-rolling any of it (task-split finding #5). Nothing here edits
the retrieval package.

Identity (ADR-0005 §11): `agency_id` is the tenant scope and MUST come from the
run state — it is never defaulted. `user_id`/`role` identify the retrieving
principal; until the Phase 4 runner (Person A) threads the real CO identity, the
workflow retrieves as its own service principal so the retrieval audit records
the TRUE caller (the agent) — never a defaulted CO authority (router.py review
finding). `change_request` may carry runner-threaded overrides.

`contract_id` is audit metadata only — never a retrieval filter (ADR-0005 §11).
"""
from __future__ import annotations

import logging

from fastapi import HTTPException

from app.retrieval import router as retrieval_router
from app.workflow.state import WorkflowState

log = logging.getLogger("ai-orchestrator.workflow.retrieve_client")

# Service principal recorded in the retrieval audit when no human identity has
# been threaded into the run (Phase 0-2 dev, unit tests). Shapes satisfy the
# router's _USER_ID_RE / _ROLE_RE validation.
WORKFLOW_USER_ID = "workflow-runner"
WORKFLOW_ROLE = "workflow_agent"


class RetrievalUnavailable(RuntimeError):
    """The read path could not serve grounded chunks (circuit open, both search
    paths failed, or the retrieval audit write withheld results). Callers fail
    soft to the CO gate — they never proceed ungrounded (G2)."""


class RouterRetrieveClient:
    """`RetrieveClient` implementation over the in-process /retrieve core."""

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
        if not agency_id:
            raise ValueError(
                "agency_id is required — tenant scope is never defaulted (ADR-0005 §11)"
            )

        request = retrieval_router.RetrieveRequest(
            query=query[: retrieval_router.MAX_QUERY_CHARS],
            sf30_block=sf30_block,
            # contract_id is REQUIRED by the request model but is audit metadata
            # only; "unspecified" marks a run that had no contract in scope yet.
            contract_id=contract_id or "unspecified",
            correlation_id=correlation_id,
        )
        try:
            response = retrieval_router.retrieve(
                request,
                x_tenant_id=agency_id,
                x_user_id=user_id,
                x_user_role=role,
            )
        except HTTPException as exc:
            raise RetrievalUnavailable(
                f"/retrieve core failed ({exc.status_code}): {exc.detail}"
            ) from exc
        except Exception as exc:  # unexpected — still never proceed ungrounded
            log.error("retrieve core unexpected failure", exc_info=True)
            raise RetrievalUnavailable(str(exc)) from exc

        return [chunk.model_dump() for chunk in response.chunks]


# Swappable singleton (mirror of db.reset_client's test-hook idiom): nodes call
# the module-level retrieve(); tests swap the implementation with set_client().
_client = RouterRetrieveClient()


def set_client(client) -> None:
    """Test hook — swap the RetrieveClient implementation."""
    global _client
    _client = client


def get_client():
    return _client


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
    """Module-level convenience matching the frozen Protocol signature."""
    return _client.retrieve(
        query,
        sf30_block=sf30_block,
        agency_id=agency_id,
        user_id=user_id,
        role=role,
        correlation_id=correlation_id,
        contract_id=contract_id,
    )


def identity_for(state: WorkflowState) -> tuple[str, str, str]:
    """(agency_id, user_id, role) for a retrieval made by this run.

    agency_id comes from the run state (tenant scope — ADR-0005 §11); raises
    ValueError when absent so the gap surfaces at the call site, not deep in
    the router. Callers invoke this inside their fail-soft try blocks. user/role
    use runner-threaded overrides in change_request when present, else the
    workflow service principal.
    """
    agency_id = state.get("agency_id")
    if not agency_id:
        raise ValueError(
            "run state has no agency_id — tenant scope is never defaulted "
            "(ADR-0005 §11)"
        )
    change = state.get("change_request") or {}
    return (
        agency_id,
        change.get("requested_by_user_id", WORKFLOW_USER_ID),
        change.get("requested_by_role", WORKFLOW_ROLE),
    )

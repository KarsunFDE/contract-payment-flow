"""ingestion/auth.py — server-side authorization gate for corpus write endpoints.

ADR-0005 §6/§11/§15 + FAR 1.602-1 / 43.102: only an authenticated Contracting
Officer (or sys_admin) may stage or approve FAR/DFARS corpus that feeds SF-30
modification drafting. The Angular route guard is UX only, NOT a security
boundary — these dependencies are the boundary (review findings 1/2/3).

Identity source: the API gateway authenticates the JWT and forwards the verified
principal as trusted headers (X-User-Id / X-User-Role / X-User-Name /
X-Agency-Id). The orchestrator trusts these ONLY because it is network-isolated
behind the gateway (ADR-0005 §6 — port 8000 is never publicly exposed). That
isolation is enforced, not assumed: the ai-orchestrator service in
infra/docker/docker-compose.yml uses `expose` (compose-internal network), NOT a
host `ports:` publish, so no outside caller can reach port 8000 and spoof
X-User-Role (security review finding 1). This is the single integration point:
once the gateway auth/StripPrefix story is finished, swap the header read below
for direct JWT validation without touching any caller.

Absent/blank identity → 401. Authenticated but unauthorized role → 403.
"""
from __future__ import annotations

from fastapi import Header, HTTPException
from pydantic import BaseModel

# Roles permitted to write the corpus: the CO binds the government (FAR 1.602-1),
# sys_admin performs corpus operations on the CO's behalf.
_CORPUS_WRITE_ROLES = {"contracting_officer", "sys_admin"}

# Only this role may write the unscoped global FAR corpus (the corpus every
# tenant retrieves). Every other write role MUST carry a non-blank agency_id and
# is confined to that agency's tenant — see require_corpus_admin (security review
# finding: tenant-isolation escalation, ADR-0005 §11; FAR 1.602-1 / 43.102).
_GLOBAL_CORPUS_ROLES = {"sys_admin"}


class CorpusPrincipal(BaseModel):
    """The authenticated actor authorized to write the corpus."""
    user_id: str
    role: str
    display_name: str = ""
    # Tenant scope (ADR-0005 §11). For a global-corpus role (sys_admin) a blank
    # agency_id means the unscoped global FAR corpus; for every other write role
    # require_corpus_admin guarantees this is non-blank, so the write path can
    # never silently fall through to the global corpus.
    agency_id: str = ""


def require_corpus_admin(
    x_user_id: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
    x_user_name: str | None = Header(default=None),
    x_agency_id: str | None = Header(default=None),
) -> CorpusPrincipal:
    """FastAPI dependency: resolve + authorize the corpus-write principal.

    The returned principal is the ONLY source of identity (ingested_by) and
    tenant scope for the write path — neither is accepted from the request body.
    """
    user_id = (x_user_id or "").strip()
    role = (x_user_role or "").strip().lower()
    agency_id = (x_agency_id or "").strip()

    if not user_id or not role:
        raise HTTPException(
            401,
            "Unauthenticated: corpus write requires a gateway-verified identity "
            "(missing X-User-Id / X-User-Role).",
        )
    if role not in _CORPUS_WRITE_ROLES:
        raise HTTPException(
            403,
            f"Role {role!r} is not authorized to write the FAR corpus "
            f"(requires one of {sorted(_CORPUS_WRITE_ROLES)}).",
        )
    # Fail closed on tenant scope (security review finding — tenant-isolation
    # escalation, ADR-0005 §11). Only a global-corpus role may write unscoped;
    # every other write role MUST present a non-blank agency_id. Without this a
    # contracting_officer whose token is missing/blank agency_id would fall
    # through _writable_tenant to far_corpus_global — the corpus every tenant
    # retrieves for SF-30 drafting (FAR 1.602-1 / 43.102).
    if not agency_id and role not in _GLOBAL_CORPUS_ROLES:
        raise HTTPException(
            403,
            f"Role {role!r} requires a non-blank agency_id (X-Agency-Id) to write "
            "the corpus; only a global-corpus role may write the unscoped global "
            "FAR corpus.",
        )

    return CorpusPrincipal(
        user_id=user_id,
        role=role,
        display_name=(x_user_name or "").strip(),
        agency_id=agency_id,
    )

"""modification_client.py — HTTP client to the Java contract-modification-service.

Three operations on the ContractModification resource (Java service on :8081):
  - patch_draft  : PATCH /api/contract-modifications/{id}  — write draft fields
  - publish      : POST  /api/contract-modifications/{id}/publish — DRAFT → MODIFICATION_REQUEST
  - cancel_draft : POST  /api/contract-modifications/{id}/cancel  — DRAFT → CANCELLED (supersede)

All calls use stdlib urllib so no new dependency is introduced. Raises RuntimeError
on any non-success response — callers fail closed (ADR-0006 Integration Note 3).

Identity propagation (finding #10 — RESOLVED): every call now carries gateway-asserted
identity headers (X-User-Id, X-User-Role, X-Tenant-Id, X-Correlation-Id) so the Java
service can enforce CO-role + agency isolation server-side (ADR-0006 Integration Notes 2
& 4; debt Items 2, 10). _request fails closed before the network call if actor_id,
actor_role, or agency_id is missing/blank or actor_id is "anonymous" — anonymous callers
are never forwarded to an irreversible endpoint.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

_BASE_URL = os.environ.get("MODIFICATION_SERVICE_URL", "http://localhost:8081")


def _request(
    path: str,
    method: str,
    body: dict | None = None,
    *,
    extra_headers: dict[str, str] | None = None,
) -> None:
    """Send *method* to *path*, merging *extra_headers* into the request.

    Raises RuntimeError on any non-2xx response or network failure so callers
    always fail closed (ADR-0006 Integration Note 3).
    """
    data = json.dumps(body).encode() if body is not None else None
    headers: dict[str, str] = {"Content-Type": "application/json"} if data is not None else {}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(
        f"{_BASE_URL}{path}", data=data, method=method, headers=headers,
    )
    try:
        with urllib.request.urlopen(req):
            pass
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"{method} {path} → HTTP {exc.code}: {exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"{method} {path} connection error: {exc.reason}"
        ) from exc


def _identity_headers(
    *,
    actor_id: str,
    actor_role: str,
    agency_id: str,
    correlation_id: str,
) -> dict[str, str]:
    """Build and validate gateway-asserted identity headers.

    Fails closed (raises RuntimeError) if any of actor_id / actor_role /
    agency_id is missing, blank, or actor_id equals "anonymous".  This guard
    runs before any network call so an anonymous identity is never forwarded
    to an irreversible endpoint.
    """
    for name, value in (
        ("actor_id", actor_id),
        ("actor_role", actor_role),
        ("agency_id", agency_id),
    ):
        if not value or not value.strip():
            raise RuntimeError(
                f"modification_client: {name} is missing or blank — "
                "refusing to forward anonymous identity to write service"
            )
    if actor_id.strip().lower() == "anonymous":
        raise RuntimeError(
            "modification_client: actor_id='anonymous' is not permitted — "
            "refusing to forward anonymous identity to write service"
        )
    return {
        "X-User-Id":        actor_id,
        "X-User-Role":      actor_role,
        "X-Tenant-Id":      agency_id,
        "X-Correlation-Id": correlation_id or "",
    }


def patch_draft(
    draft_id: str,
    fields: dict,
    *,
    actor_id: str,
    actor_role: str,
    agency_id: str,
    correlation_id: str,
) -> None:
    """PATCH draft fields; forwards verified caller identity to the write service."""
    headers = _identity_headers(
        actor_id=actor_id,
        actor_role=actor_role,
        agency_id=agency_id,
        correlation_id=correlation_id,
    )
    _request(
        f"/api/contract-modifications/{draft_id}",
        "PATCH",
        fields,
        extra_headers=headers,
    )


def publish(
    draft_id: str,
    *,
    actor_id: str,
    actor_role: str,
    agency_id: str,
    consent_recorded: bool,
    package_hash: str,
    correlation_id: str,
) -> None:
    """POST publish (DRAFT → MODIFICATION_REQUEST); forwards verified caller identity."""
    headers = _identity_headers(
        actor_id=actor_id,
        actor_role=actor_role,
        agency_id=agency_id,
        correlation_id=correlation_id,
    )
    _request(
        f"/api/contract-modifications/{draft_id}/publish",
        "POST",
        {"consentRecorded": consent_recorded, "packageHash": package_hash},
        extra_headers=headers,
    )


def cancel_draft(
    draft_id: str,
    *,
    actor_id: str,
    actor_role: str,
    agency_id: str,
    correlation_id: str,
) -> None:
    """POST cancel (DRAFT → CANCELLED); forwards verified caller identity."""
    headers = _identity_headers(
        actor_id=actor_id,
        actor_role=actor_role,
        agency_id=agency_id,
        correlation_id=correlation_id,
    )
    _request(
        f"/api/contract-modifications/{draft_id}/cancel",
        "POST",
        extra_headers=headers,
    )

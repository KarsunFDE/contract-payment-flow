"""modification_client.py — HTTP client to the Java contract-modification-service.

Three operations on the ContractModification resource (Java service on :8081):
  - patch_draft  : PATCH /api/contract-modifications/{id}  — write draft fields
  - publish      : POST  /api/contract-modifications/{id}/publish — DRAFT → MODIFICATION_REQUEST
  - cancel_draft : POST  /api/contract-modifications/{id}/cancel  — DRAFT → CANCELLED (supersede)

All calls use stdlib urllib so no new dependency is introduced. Raises RuntimeError
on any non-success response — callers fail closed (ADR-0006 Integration Note 3).

NOTE: real CO-role + agency enforcement lives in the Java service, not here (ADR-0006
Integration Notes 2 & 4; debt Items 2, 10). This client trusts the service to reject
unauthorized calls. See finding #10 in the task split doc.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

_BASE_URL = os.environ.get("MODIFICATION_SERVICE_URL", "http://localhost:8081")


def _request(path: str, method: str, body: dict | None = None) -> None:
    data = json.dumps(body).encode() if body is not None else None
    headers: dict[str, str] = {"Content-Type": "application/json"} if data is not None else {}
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


def patch_draft(draft_id: str, fields: dict) -> None:
    _request(f"/api/contract-modifications/{draft_id}", "PATCH", fields)


def publish(draft_id: str, consent_recorded: bool) -> None:
    _request(
        f"/api/contract-modifications/{draft_id}/publish",
        "POST",
        {"consentRecorded": consent_recorded},
    )


def cancel_draft(draft_id: str) -> None:
    _request(f"/api/contract-modifications/{draft_id}/cancel", "POST")

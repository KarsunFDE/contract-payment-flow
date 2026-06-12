"""
router.py — workflow API surface (mount point). FOUNDATION STUB.

Phase 0 ships only a status probe so main.py can mount the workflow surface and
the scaffolding test can assert it is wired. The real endpoints — POST to start
the triage flow, and resume-after-CO-gate — land with Person A's runner (m3.md
Phase 4) and B5 integration.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/workflow", tags=["workflow"])


@router.get("/_status")
def status() -> dict[str, str]:
    """Liveness probe for the workflow surface (mirrors the retrieval router)."""
    return {"router": "workflow", "status": "scaffolded"}

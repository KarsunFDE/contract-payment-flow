"""
retrieval/router.py — read-path endpoint (ADR-0005 Phase 1).

Owner: Person B. Day 0 stub — endpoint lands this week:
  POST /retrieve — query, sf30_block, tenant_id, contract_id →
                   hybrid retrieve → RRF fuse → rerank → audit log
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/retrieve", tags=["retrieval"])


@router.get("/_status")
def status() -> dict[str, str]:
    """Day 0 wiring check — confirms the read-path router is mounted."""
    return {"router": "retrieval", "status": "scaffolded"}

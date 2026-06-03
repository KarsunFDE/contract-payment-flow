"""
ingestion/router.py — corpus write-path endpoints (ADR-0005 Phase 1).

Owner: Person A. Day 0 stub — endpoints land this week:
  POST /corpus/upload  — accept a FAR/DFARS/WAWF/PIEE source document
  POST /corpus/ingest  — chunk → embed → insert with provenance metadata
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/corpus", tags=["corpus-ingestion"])


@router.get("/_status")
def status() -> dict[str, str]:
    """Day 0 wiring check — confirms the write-path router is mounted."""
    return {"router": "corpus-ingestion", "status": "scaffolded"}

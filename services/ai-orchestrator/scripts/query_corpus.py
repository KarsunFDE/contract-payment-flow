"""query_corpus.py — one-shot CLI to test the /retrieve endpoint (dev/local).

Port 8000 is internal-only, so run this INSIDE the ai-orchestrator container.
It POSTs to the local /retrieve endpoint with the three gateway-asserted
identity headers (X-Tenant-Id / X-User-Id / X-User-Role) that the endpoint now
requires, so you don't have to hand-assemble them each time.

Run (from services/ai-orchestrator/, or via docker exec):

    docker exec -it docker-ai-orchestrator-1 \
        python -m scripts.query_corpus "bilateral modification price adjustment"

    # defaults to a sample query if none given:
    docker exec -it docker-ai-orchestrator-1 python -m scripts.query_corpus

Override identity / block / contract via env if needed:
    QUERY_TENANT_ID, QUERY_USER_ID, QUERY_USER_ROLE, QUERY_SF30_BLOCK,
    QUERY_CONTRACT_ID.

X-User-Role defaults to the non-authoritative "system_smoke_test" (NOT
contracting_officer): /retrieve records the role verbatim into the append-only
audit trail, so a CO default would falsify CO authority on every smoke run
(FAR 1.602-1). Set QUERY_USER_ROLE only with a real gateway-asserted role, and
never use this script as a stand-in for an authenticated CO request.

Exits non-zero if the request fails or returns zero chunks, so it can gate a
verification step.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

_DEFAULT_QUERY = "bilateral modification price adjustment"
_URL = "http://localhost:8000/retrieve/"

# Non-authoritative smoke-test identity (security review finding). This script
# bypasses the gateway and POSTs straight to the internal /retrieve, which
# records X-User-Role VERBATIM into the append-only RetrievalAuditRecord. The
# old "contracting_officer" default falsely attributed every local smoke run to
# a CO — exactly the authority-trail falsification this PR removed (FAR 1.602-1).
# Default to a role that is clearly NOT a CO and that audit/reporting excludes;
# real callers must go through the gateway, never this script.
_SMOKE_TEST_ROLE = "system_smoke_test"
_SMOKE_TEST_USER = "system-smoke-test"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    query = " ".join(argv).strip() or _DEFAULT_QUERY

    body = json.dumps({
        "query": query,
        "sf30_block": os.environ.get("QUERY_SF30_BLOCK", "13"),
        "contract_id": os.environ.get("QUERY_CONTRACT_ID", "TEST-001"),
    }).encode("utf-8")

    req = urllib.request.Request(
        _URL, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Tenant-Id": os.environ.get("QUERY_TENANT_ID", "far_corpus_global"),
            "X-User-Id": os.environ.get("QUERY_USER_ID", _SMOKE_TEST_USER),
            "X-User-Role": os.environ.get("QUERY_USER_ROLE", _SMOKE_TEST_ROLE),
        },
    )

    try:
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"retrieval failed: HTTP {exc.code} — {exc.read().decode(errors='replace')}")
        return 1
    except urllib.error.URLError as exc:
        print(f"retrieval failed: could not reach {_URL} — {exc.reason}")
        return 1

    chunks = data.get("chunks", [])
    print(
        f"query: {query!r}\n"
        f"strategy={data.get('retrieval_strategy')} "
        f"chunks={data.get('chunk_count')} degraded={data.get('degraded')} "
        f"latency_ms={data.get('latency_ms')}"
    )
    for c in chunks:
        sd = c.get("source_document") or {}
        score = c.get("score")
        score_str = "  n/a" if score is None else f"{score:5.3f}"
        snippet = " ".join((c.get("chunk_text") or "").split())[:70]
        print(f"  {score_str}  {sd.get('clause_number', '?'):>12}  {snippet}")

    if not chunks:
        print("0 chunks returned — corpus empty or Bedrock token missing/expired.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

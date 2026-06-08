"""
test_ingestion_router.py — corpus write-path endpoint tests (ADR-0005 Phase 1).

Owner: Person A. Covers the three medium-severity adversarial-review fixes on
app/ingestion/router.py:

  Finding 1 — crash-safety: stale "ingesting" claims are re-claimable so a
              process that died mid-ingest is recoverable (the deterministic
              chunk_ref upsert in pipeline.py keeps the re-run idempotent).
  Finding 2 — staged uploads get an expires_at (TTL reap target); the
              consumed flip $unsets the full source text.
  Finding 3 — upload validation is AND-semantics (ext required, content-type
              checked when supplied), empty/whitespace text rejected, and
              far_part/subpart/clause_number validated against FAR formats.

MongoDB and the ingestion pipeline are mocked — these tests verify the router's
validation, staging-write shape, claim logic, and consumed-flip behaviour, not
external services. db.get_db() is patched to return a fake Database that maps
collection names to MagicMocks; the auth dependency is overridden with a
FastAPI dependency_overrides entry (the gateway-header auth is exercised by its
own boundary, not re-tested here).
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi.testclient import TestClient
from pymongo.errors import OperationFailure

from app import db
from app.ingestion import router as router_module
from app.ingestion.auth import CorpusPrincipal, require_corpus_admin
from app.main import app


# --- fixtures / helpers ---


class _FakeDB:
    """Stands in for a pymongo Database: db[name] returns a stable MagicMock
    collection, created lazily so a test can reach in and assert on it. Also
    fakes .client.start_session()/with_transaction so the router's
    transactional commit path executes its callback (with the fake session)."""

    def __init__(self) -> None:
        self.collections: dict[str, MagicMock] = {}
        self.session = MagicMock(name="session")
        self.session.with_transaction.side_effect = lambda fn, **kw: fn(self.session)
        self.client = MagicMock(name="client")
        self.client.start_session.return_value.__enter__.return_value = self.session

    def __getitem__(self, name: str) -> MagicMock:
        if name not in self.collections:
            self.collections[name] = MagicMock(name=f"collection:{name}")
        return self.collections[name]


@pytest.fixture
def fake_db() -> _FakeDB:
    return _FakeDB()


@pytest.fixture
def client(fake_db):
    """TestClient with auth overridden to a fixed CO principal and db patched."""
    app.dependency_overrides[require_corpus_admin] = lambda: CorpusPrincipal(
        user_id="co-001", role="contracting_officer", display_name="Test CO"
    )
    with patch("app.db.get_db", return_value=fake_db):
        yield TestClient(app)
    app.dependency_overrides.pop(require_corpus_admin, None)


def _upload_files(content: bytes = b"43.103 Types of contract modifications.\n", *,
                  filename: str = "far-43-103.md", content_type: str | None = "text/markdown"):
    """Build the multipart `files=` arg for the /corpus/upload form."""
    return {"file": (filename, io.BytesIO(content), content_type)}


def _good_form() -> dict:
    return {"title": "FAR Part 43 — Modifications", "far_part": "43",
            "subpart": "43.1", "clause_number": "43.103"}


# --- Finding 3: OR → AND upload validation ---


def test_upload_rejects_bad_extension(client):
    """A .exe (or any non-md/txt) extension is rejected even with a valid form."""
    resp = client.post(
        "/corpus/upload",
        files=_upload_files(filename="payload.exe", content_type="text/plain"),
        data=_good_form(),
    )
    assert resp.status_code == 415
    assert "extension" in resp.json()["detail"].lower()


def test_upload_rejects_bad_content_type_with_good_extension(client):
    """OLD OR-bug let arbitrary bytes named .txt through; now a bad supplied
    content-type is rejected even though the extension is allowed."""
    resp = client.post(
        "/corpus/upload",
        files=_upload_files(filename="far-43.txt", content_type="application/x-msdownload"),
        data=_good_form(),
    )
    assert resp.status_code == 415
    assert "content-type" in resp.json()["detail"].lower()


def test_upload_accepts_missing_content_type(client, fake_db):
    """A blank/None content-type with a good extension is acceptable."""
    resp = client.post(
        "/corpus/upload",
        files=_upload_files(filename="far-43.txt", content_type=None),
        data=_good_form(),
    )
    assert resp.status_code == 200


def test_upload_rejects_empty_text(client):
    """Whitespace-only body decodes fine but has nothing to ingest → 422."""
    resp = client.post(
        "/corpus/upload",
        files=_upload_files(content=b"   \n\t  \n"),
        data=_good_form(),
    )
    assert resp.status_code == 422
    assert "empty" in resp.json()["detail"].lower()


def test_upload_rejects_blank_title(client):
    resp = client.post(
        "/corpus/upload",
        files=_upload_files(),
        data={**_good_form(), "title": "   "},
    )
    assert resp.status_code == 422
    assert "title" in resp.json()["detail"].lower()


@pytest.mark.parametrize("far_part", ["abcd", "2522", "4.3", "abc"])
def test_upload_rejects_bad_far_part(client, far_part):
    """Malformed but non-empty far_part hits our regex check (422 + message).
    far_part is now 1-3 digits OR the literal 'DFARS' (finding 8), so 4+ digits
    ('2522'), non-numeric ('abcd'), and dotted ('4.3') values are rejected.
    (An empty far_part is rejected earlier by FastAPI's required-Form check —
    also 422, but with the framework's own error shape.)"""
    resp = client.post(
        "/corpus/upload",
        files=_upload_files(),
        data={**_good_form(), "far_part": far_part},
    )
    assert resp.status_code == 422
    assert "far_part" in resp.json()["detail"]


@pytest.mark.parametrize("far_part", ["4", "43", "252", "DFARS"])
def test_upload_accepts_far_and_dfars_far_part(client, far_part):
    """Finding 8: far_part accepts 1-3 digits (FAR '43', DFARS-numbered '252')
    and the literal 'DFARS' the seed doc's frontmatter stores."""
    resp = client.post(
        "/corpus/upload",
        files=_upload_files(),
        # Clear subpart/clause so this test isolates far_part validation.
        data={**_good_form(), "far_part": far_part, "subpart": "", "clause_number": ""},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("subpart", ["43", "43.", ".1", "43.1.2", "abc"])
def test_upload_rejects_bad_subpart(client, subpart):
    resp = client.post(
        "/corpus/upload",
        files=_upload_files(),
        data={**_good_form(), "subpart": subpart},
    )
    assert resp.status_code == 422
    assert "subpart" in resp.json()["detail"]


@pytest.mark.parametrize("clause", ["43", "43-1", "43.103-", "abc.def", "43.103-x"])
def test_upload_rejects_bad_clause_number(client, clause):
    resp = client.post(
        "/corpus/upload",
        files=_upload_files(),
        data={**_good_form(), "clause_number": clause},
    )
    assert resp.status_code == 422
    assert "clause_number" in resp.json()["detail"]


@pytest.mark.parametrize("clause", ["43.103", "32.7", "42.15", "43.205-1", "252.232-7003"])
def test_upload_accepts_valid_far_section_formats(client, clause):
    """FAR sections can be 1-3 digits after the dot, with an optional -N suffix.
    Finding 8: the part may also be 3 digits and the suffix 4 digits, so the
    DFARS clause '252.232-7003' (the seed doc's clause_number) is accepted."""
    resp = client.post(
        "/corpus/upload",
        files=_upload_files(),
        data={**_good_form(), "subpart": "", "clause_number": clause},
    )
    assert resp.status_code == 200, resp.text


# --- Finding 2: expires_at on upload ---


def test_accepted_upload_sets_expires_at(client, fake_db):
    """A valid upload stamps created_at + expires_at (TTL reap target) and the
    full text on the staging doc."""
    before = datetime.now(timezone.utc)
    resp = client.post("/corpus/upload", files=_upload_files(), data=_good_form())
    after = datetime.now(timezone.utc)
    assert resp.status_code == 200

    staging = fake_db["corpus_staging"]
    staging.insert_one.assert_called_once()
    doc = staging.insert_one.call_args[0][0]

    assert "expires_at" in doc
    assert doc["expires_at"] > doc["created_at"]
    # 7-day retention window (allow a little slack around the call boundary).
    delta = doc["expires_at"] - doc["created_at"]
    assert timedelta(days=7) - timedelta(seconds=2) <= delta <= timedelta(days=7) + timedelta(seconds=2)
    assert before <= doc["created_at"] <= after
    assert doc["status"] == "staged_awaiting_ingest"
    assert doc["text"]  # full source text retained at staging time


# --- Finding 2: consumed flip $unsets text ---


def _wire_ingest_success(fake_db, claimed_doc, *, preflight_status="staged_awaiting_ingest",
                         preflight_claimed_at=None):
    """Make the batch pre-flight find() the doc as claimable, make
    find_one_and_update return claimed_doc, and stub the audit collection so
    /corpus/ingest reaches the consumed flip."""
    staging = fake_db["corpus_staging"]
    preflight_doc = {**claimed_doc, "status": preflight_status}
    if preflight_claimed_at is not None:
        preflight_doc["claimed_at"] = preflight_claimed_at
    staging.find.return_value = [preflight_doc]
    staging.find_one_and_update.return_value = claimed_doc
    fake_db["ingestion_audit"].insert_one.return_value = MagicMock()
    return staging


def _patch_pipeline(chunks_inserted=3, chunks_updated=0, chunks_discarded=0,
                    cache_hits=1, title="FAR 43"):
    """Patch the router's pipeline seam (prepare_document + insert_records).

    build_summary is left real — it derives the summary from these two."""
    prepared = {
        "records": [{"chunk_ref": f"ref-{i}"} for i in range(chunks_inserted)],
        "chunks_discarded": chunks_discarded,
        "cache_hits": cache_hits,
        "source_title": title,
    }
    result = MagicMock(upserted_count=chunks_inserted, modified_count=chunks_updated)
    return (
        patch.object(router_module.pipeline, "prepare_document", return_value=prepared),
        patch.object(router_module.pipeline, "insert_records", return_value=result),
    )


def test_consumed_flip_unsets_text(client, fake_db):
    """After successful ingestion the staging doc is flipped to consumed AND its
    text is $unset, while metadata/expires_at are retained (finding 2)."""
    claimed = {
        "staged_document_id": "sid-1", "title": "FAR 43", "far_part": "43",
        "subpart": "43.1", "clause_number": "43.103", "source_url": "",
        "text": "43.103 ...full body...", "status": "ingesting",
    }
    staging = _wire_ingest_success(fake_db, claimed)

    p_prepare, p_insert = _patch_pipeline()
    with p_prepare, p_insert, \
         patch.object(router_module.pipeline, "make_ingestion_run_record", return_value={}):
        resp = client.post(
            "/corpus/ingest",
            json={"staged_document_ids": ["sid-1"], "document_version": "2026-06-01"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["documents_ingested"] == 1
    assert resp.json()["chunks_inserted"] == 3

    staging.update_one.assert_called_once()
    flt, update = staging.update_one.call_args[0]
    assert flt == {"staged_document_id": "sid-1"}
    assert update["$set"]["status"] == "consumed"
    assert "consumed_at" in update["$set"]
    assert update["$unset"] == {"text": ""}
    # Finding 1: the consumed flip ran inside the transaction session.
    assert staging.update_one.call_args.kwargs["session"] is fake_db.session


def test_insert_and_flip_share_transaction_session(client, fake_db):
    """Finding 1 (crash-safety): the corpus insert and the staging status flip
    both receive the same ClientSession from with_transaction — they commit or
    roll back together."""
    claimed = {
        "staged_document_id": "sid-txn", "title": "FAR 43", "far_part": "43",
        "subpart": "", "clause_number": "", "source_url": "",
        "text": "body", "status": "ingesting",
    }
    staging = _wire_ingest_success(fake_db, claimed)

    p_prepare, p_insert = _patch_pipeline()
    with p_prepare, p_insert as insert_mock, \
         patch.object(router_module.pipeline, "make_ingestion_run_record", return_value={}):
        resp = client.post(
            "/corpus/ingest",
            json={"staged_document_ids": ["sid-txn"], "document_version": "2026-06-01"},
        )

    assert resp.status_code == 200, resp.text
    fake_db.session.with_transaction.assert_called_once()
    assert insert_mock.call_args.kwargs["session"] is fake_db.session
    assert staging.update_one.call_args.kwargs["session"] is fake_db.session


def test_transaction_fallback_on_standalone_mongod(client, fake_db):
    """When the deployment rejects transactions (OperationFailure code 20 on a
    standalone mongod), the router falls back to sessionless commits instead of
    failing the ingest — the chunk_ref upsert + stale-claim window keep that
    path safe."""
    claimed = {
        "staged_document_id": "sid-fb", "title": "FAR 43", "far_part": "43",
        "subpart": "", "clause_number": "", "source_url": "",
        "text": "body", "status": "ingesting",
    }
    staging = _wire_ingest_success(fake_db, claimed)
    fake_db.session.with_transaction.side_effect = OperationFailure(
        "Transaction numbers are only allowed on a replica set member or mongos",
        code=20,
    )

    p_prepare, p_insert = _patch_pipeline()
    with p_prepare, p_insert as insert_mock, \
         patch.object(router_module.pipeline, "make_ingestion_run_record", return_value={}):
        resp = client.post(
            "/corpus/ingest",
            json={"staged_document_ids": ["sid-fb"], "document_version": "2026-06-01"},
        )

    assert resp.status_code == 200, resp.text
    assert insert_mock.call_args.kwargs["session"] is None
    assert staging.update_one.call_args.kwargs["session"] is None


# --- Finding 1: stale-claim re-claim ---


def test_stale_ingesting_claim_query_allows_reclaim(client, fake_db):
    """The claim query must re-claim docs stuck in 'ingesting' past the stale
    window: it $or's fresh-staged with stale-ingesting (claimed_at < cutoff)."""
    claimed = {
        "staged_document_id": "sid-stale", "title": "FAR 43", "far_part": "43",
        "subpart": "", "clause_number": "", "source_url": "",
        "text": "body", "status": "ingesting",
    }
    staging = _wire_ingest_success(
        fake_db, claimed,
        preflight_status="ingesting",
        preflight_claimed_at=datetime.now(timezone.utc) - timedelta(minutes=20),
    )

    p_prepare, p_insert = _patch_pipeline(chunks_inserted=1, cache_hits=0)
    with p_prepare, p_insert, \
         patch.object(router_module.pipeline, "make_ingestion_run_record", return_value={}):
        resp = client.post(
            "/corpus/ingest",
            json={"staged_document_ids": ["sid-stale"], "document_version": "2026-06-01"},
        )

    assert resp.status_code == 200, resp.text

    # Inspect the claim filter the router built.
    claim_filter = staging.find_one_and_update.call_args[0][0]
    assert claim_filter["staged_document_id"] == "sid-stale"
    branches = claim_filter["$or"]
    assert {"status": "staged_awaiting_ingest"} in branches

    stale_branch = next(b for b in branches if b["status"] == "ingesting")
    assert "claimed_at" in stale_branch
    cutoff = stale_branch["claimed_at"]["$lt"]
    # Cutoff is ~15 min in the past — a doc claimed before it is re-claimable.
    age = datetime.now(timezone.utc) - cutoff
    assert timedelta(minutes=14) <= age <= timedelta(minutes=16)


def test_unclaimable_doc_returns_409(client, fake_db):
    """A doc that exists but isn't claimable (e.g. consumed, or freshly
    ingesting) yields 409 at pre-flight — before anything is claimed."""
    staging = fake_db["corpus_staging"]
    staging.find.return_value = [{"staged_document_id": "sid-x", "status": "consumed"}]

    resp = client.post(
        "/corpus/ingest",
        json={"staged_document_ids": ["sid-x"], "document_version": "2026-06-01"},
    )
    assert resp.status_code == 409
    assert "sid-x" in resp.json()["detail"]
    staging.find_one_and_update.assert_not_called()  # zero side effects


def test_missing_doc_returns_404(client, fake_db):
    staging = fake_db["corpus_staging"]
    staging.find.return_value = []

    resp = client.post(
        "/corpus/ingest",
        json={"staged_document_ids": ["nope"], "document_version": "2026-06-01"},
    )
    assert resp.status_code == 404
    staging.find_one_and_update.assert_not_called()


def test_preflight_rejects_whole_batch_before_any_ingest(client, fake_db):
    """Review finding 3: one bad ID in the batch → 404/409 with ZERO documents
    ingested, instead of aborting mid-batch with earlier docs in the corpus."""
    staging = fake_db["corpus_staging"]
    staging.find.return_value = [
        {"staged_document_id": "sid-good", "status": "staged_awaiting_ingest"},
        {"staged_document_id": "sid-bad", "status": "consumed"},
    ]

    p_prepare, p_insert = _patch_pipeline()
    with p_prepare as prepare_mock, p_insert:
        resp = client.post(
            "/corpus/ingest",
            json={"staged_document_ids": ["sid-good", "sid-bad"],
                  "document_version": "2026-06-01"},
        )

    assert resp.status_code == 409
    assert "sid-bad" in resp.json()["detail"]
    prepare_mock.assert_not_called()           # nothing embedded
    staging.find_one_and_update.assert_not_called()  # nothing claimed


# --- Finding 6: ingestion_audit write semantics per path ---


def test_failed_branch_audit_write_failure_does_not_mask_original_error(client, fake_db, caplog):
    """Finding 6 (error path): when the ingestion pipeline raises, an audit-insert
    failure must NOT mask the original error — the crafted 500 still surfaces, and
    the audit failure is logged loudly (§10 no-silent-failure)."""
    claimed = {
        "staged_document_id": "sid-f", "title": "FAR 43", "far_part": "43",
        "subpart": "", "clause_number": "", "source_url": "",
        "text": "body", "status": "ingesting",
    }
    staging = _wire_ingest_success(fake_db, claimed)
    # The audit insert itself blows up on the error path.
    fake_db["ingestion_audit"].insert_one.side_effect = OperationFailure("audit down")

    # prepare_document raising drives the `except Exception` (FAILED) branch.
    with patch.object(router_module.pipeline, "prepare_document",
                      side_effect=RuntimeError("bedrock exploded")), \
         patch.object(router_module.pipeline, "make_ingestion_run_record", return_value={}), \
         caplog.at_level("CRITICAL"):
        resp = client.post(
            "/corpus/ingest",
            json={"staged_document_ids": ["sid-f"], "document_version": "2026-06-01"},
        )

    # The ORIGINAL failure path (the crafted 500) surfaces, not a 503/audit error.
    assert resp.status_code == 500, resp.text
    assert "sid-f" in resp.json()["detail"]
    # The doc was still marked failed (original error-handling preserved).
    assert staging.update_one.call_args[0][1]["$set"]["status"] == "failed"
    # The audit failure is visible in the logs (loud, not silent).
    assert any(
        r.levelname == "CRITICAL" and "ingestion_audit write FAILED" in r.message
        for r in caplog.records
    )


def test_success_path_audit_write_failure_fails_closed_503(client, fake_db, caplog):
    """Finding 6 (success path): chunks are already committed, so an audit-write
    failure fails closed with a 503 that tells the client NOT to re-ingest —
    never a misleading 500 — and is logged loudly."""
    claimed = {
        "staged_document_id": "sid-s", "title": "FAR 43", "far_part": "43",
        "subpart": "", "clause_number": "", "source_url": "",
        "text": "body", "status": "ingesting",
    }
    staging = _wire_ingest_success(fake_db, claimed)
    fake_db["ingestion_audit"].insert_one.side_effect = OperationFailure("audit down")

    p_prepare, p_insert = _patch_pipeline()
    with p_prepare, p_insert, \
         patch.object(router_module.pipeline, "make_ingestion_run_record", return_value={}), \
         caplog.at_level("CRITICAL"):
        resp = client.post(
            "/corpus/ingest",
            json={"staged_document_ids": ["sid-s"], "document_version": "2026-06-01"},
        )

    assert resp.status_code == 503, resp.text
    detail = resp.json()["detail"].lower()
    assert "do not re-ingest" in detail
    assert "audit" in detail
    # The chunks WERE committed before the audit failed (consumed flip ran).
    assert staging.update_one.call_args[0][1]["$set"]["status"] == "consumed"
    assert any(
        r.levelname == "CRITICAL" and "ingestion_audit write FAILED" in r.message
        for r in caplog.records
    )


def test_success_path_audit_write_success_returns_200(client, fake_db):
    """Happy path: when the audit insert succeeds the request returns 200 with the
    chunk totals (the helper does not interfere with the success response)."""
    claimed = {
        "staged_document_id": "sid-ok", "title": "FAR 43", "far_part": "43",
        "subpart": "", "clause_number": "", "source_url": "",
        "text": "body", "status": "ingesting",
    }
    _wire_ingest_success(fake_db, claimed)

    p_prepare, p_insert = _patch_pipeline(chunks_inserted=2)
    with p_prepare, p_insert, \
         patch.object(router_module.pipeline, "make_ingestion_run_record", return_value={}):
        resp = client.post(
            "/corpus/ingest",
            json={"staged_document_ids": ["sid-ok"], "document_version": "2026-06-01"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["documents_ingested"] == 1
    assert resp.json()["chunks_inserted"] == 2
    fake_db["ingestion_audit"].insert_one.assert_called_once()


def test_reingest_reports_chunks_updated(client, fake_db):
    """Review finding: a re-ingest that REPLACES chunks (modified_count > 0,
    upserted_count == 0) must surface chunks_updated, not silently report
    '0 chunks inserted' to the approving operator."""
    claimed = {
        "staged_document_id": "sid-re", "title": "FAR 43", "far_part": "43",
        "subpart": "", "clause_number": "", "source_url": "",
        "text": "body", "status": "ingesting",
    }
    _wire_ingest_success(fake_db, claimed)

    # Records are non-empty (so the insert runs), but the upsert replaces rather
    # than inserts: upserted_count=0, modified_count=3 — the re-ingest case.
    prepared = {
        "records": [{"chunk_ref": f"ref-{i}"} for i in range(3)],
        "chunks_discarded": 0, "cache_hits": 0, "source_title": "FAR 43",
    }
    result = MagicMock(upserted_count=0, modified_count=3)
    with patch.object(router_module.pipeline, "prepare_document", return_value=prepared), \
         patch.object(router_module.pipeline, "insert_records", return_value=result), \
         patch.object(router_module.pipeline, "make_ingestion_run_record", return_value={}):
        resp = client.post(
            "/corpus/ingest",
            json={"staged_document_ids": ["sid-re"], "document_version": "2026-06-01"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["chunks_inserted"] == 0
    assert body["chunks_updated"] == 3


def test_failed_branch_with_committed_docs_fails_closed_503(client, fake_db, caplog):
    """Review finding: when EARLIER docs in the batch are already committed and a
    LATER doc fails, an audit-write failure must fail closed (503) — committed
    chunks with no durable audit record are a fail-open. (Contrast with the
    single-doc failure above, where nothing committed and the original 500
    surfaces.)"""
    claimed1 = {
        "staged_document_id": "sid-1", "title": "FAR 43", "far_part": "43",
        "subpart": "", "clause_number": "", "source_url": "",
        "text": "body1", "status": "ingesting",
    }
    claimed2 = {**claimed1, "staged_document_id": "sid-2", "text": "body2"}

    staging = fake_db["corpus_staging"]
    # Pre-flight: both docs claimable.
    staging.find.return_value = [
        {**claimed1, "status": "staged_awaiting_ingest"},
        {**claimed2, "status": "staged_awaiting_ingest"},
    ]
    # Each claim returns its own doc.
    staging.find_one_and_update.side_effect = [claimed1, claimed2]
    # The audit insert itself fails on the error path.
    fake_db["ingestion_audit"].insert_one.side_effect = OperationFailure("audit down")

    prepared_ok = {
        "records": [{"chunk_ref": "r1", "chunk_id": "c1"}],
        "chunks_discarded": 0, "cache_hits": 0, "source_title": "FAR 43",
    }
    insert_result = MagicMock(upserted_count=1, modified_count=0)

    # First doc commits; second doc's prepare raises → except Exception branch
    # with per_doc_summaries already non-empty.
    with patch.object(router_module.pipeline, "prepare_document",
                      side_effect=[prepared_ok, RuntimeError("bedrock exploded")]), \
         patch.object(router_module.pipeline, "insert_records", return_value=insert_result), \
         patch.object(router_module.pipeline, "make_ingestion_run_record", return_value={}), \
         caplog.at_level("CRITICAL"):
        resp = client.post(
            "/corpus/ingest",
            json={"staged_document_ids": ["sid-1", "sid-2"], "document_version": "2026-06-01"},
        )

    # Committed chunks + failed audit → fail closed, NOT the crafted 500.
    assert resp.status_code == 503, resp.text
    assert "re-ingest" in resp.json()["detail"].lower()
    assert any(
        r.levelname == "CRITICAL" and "ingestion_audit write FAILED" in r.message
        for r in caplog.records
    )


# --- corpus_stats tenant isolation (review finding) ---


def _stats_request(principal):
    """GET /corpus/stats with require_corpus_admin overridden to `principal`
    and far_corpus mocked; returns (response, mock_corpus)."""
    corpus = MagicMock()
    corpus.aggregate.return_value = []
    corpus.distinct.return_value = []
    app.dependency_overrides[require_corpus_admin] = lambda: principal
    try:
        with patch("app.db.get_far_corpus", return_value=corpus):
            resp = TestClient(app).get("/corpus/stats")
    finally:
        app.dependency_overrides.pop(require_corpus_admin, None)
    return resp, corpus


def test_stats_scopes_non_sysadmin_to_global_and_own_agency():
    principal = CorpusPrincipal(
        user_id="co-1", role="contracting_officer", agency_id="agency_x"
    )
    resp, corpus = _stats_request(principal)
    assert resp.status_code == 200

    scope = {"tenant_id": {"$in": ["far_corpus_global", "agency_x"]}}
    # Aggregation is fronted by a $match scoping to global + own agency.
    pipeline_stages = corpus.aggregate.call_args[0][0]
    assert pipeline_stages[0] == {"$match": scope}
    # distinct is scoped with the SAME filter so model versions can't leak.
    assert corpus.distinct.call_args == call("embedding_model_version", scope)


def test_stats_sysadmin_sees_whole_corpus():
    principal = CorpusPrincipal(user_id="admin", role="sys_admin", agency_id="")
    resp, corpus = _stats_request(principal)
    assert resp.status_code == 200

    # No $match stage — sys_admin sees every tenant.
    pipeline_stages = corpus.aggregate.call_args[0][0]
    assert not any("$match" in stage for stage in pipeline_stages)
    # distinct called with no tenant filter.
    assert corpus.distinct.call_args == call("embedding_model_version")


def test_stats_requires_identity():
    """Without gateway identity the endpoint must not return corpus-wide stats."""
    corpus = MagicMock()
    corpus.aggregate.return_value = []
    corpus.distinct.return_value = []
    # No dependency override → real require_corpus_admin runs; no headers → 401.
    with patch("app.db.get_far_corpus", return_value=corpus):
        resp = TestClient(app).get("/corpus/stats")
    assert resp.status_code == 401
    corpus.aggregate.assert_not_called()

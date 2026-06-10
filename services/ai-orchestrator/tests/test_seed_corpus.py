"""Tests for scripts.seed_corpus — destructive-flag safety (security review
finding 6).

--drop must be SCOPED to the seed set (global tenant, system:seed-ingest user)
so it can never wipe another tenant. The cross-tenant wipe (--drop-all-tenants)
must be gated behind a dev-only env check AND a typed confirmation.

MongoDB and the ingestion pipeline are mocked — no live connection required.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app import config
from scripts import seed_corpus as sc


# --- scoped delete filter ---

def test_seed_delete_filter_is_scoped_to_seed_set():
    f = sc._seed_delete_filter()
    assert f == {
        "tenant_id": config.GLOBAL_TENANT_ID,
        "ingested_by.user_id": "system:seed-ingest",
    }
    # Must NOT be an unscoped {} — that was the cross-tenant bug.
    assert f != {}


def _patch_run(corpus, *, summary=None):
    """Patch db.get_far_corpus + the seed pipeline so main() runs offline."""
    summary = summary or {
        "files_ingested": 1, "chunks_inserted": 1, "chunks_updated": 0,
        "chunks_discarded": 0, "cache_hits": 0,
    }
    return (
        patch("scripts.seed_corpus.db.get_far_corpus", return_value=corpus),
        patch("scripts.seed_corpus.pipeline.ingest_seed_corpus", return_value=summary),
        patch("scripts.seed_corpus.Path.is_dir", return_value=True),
    )


def test_drop_uses_scoped_filter_not_empty():
    """--drop must call delete_many with the seed-set filter, never {}."""
    corpus = MagicMock()
    corpus.delete_many.return_value = MagicMock(deleted_count=3)
    p_db, p_ingest, p_dir = _patch_run(corpus)
    with p_db, p_ingest, p_dir:
        rc = sc.main(["--drop"])
    assert rc == 0
    corpus.delete_many.assert_called_once_with(sc._seed_delete_filter())


def test_no_drop_does_not_delete():
    corpus = MagicMock()
    p_db, p_ingest, p_dir = _patch_run(corpus)
    with p_db, p_ingest, p_dir:
        rc = sc.main([])
    assert rc == 0
    corpus.delete_many.assert_not_called()


# --- cross-tenant wipe gating ---

def test_drop_all_refused_in_prod_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    corpus = MagicMock()
    p_db, p_ingest, p_dir = _patch_run(corpus)
    with p_db, p_ingest, p_dir:
        rc = sc.main(["--drop-all-tenants"])
    assert rc == 1
    corpus.delete_many.assert_not_called()


def test_drop_all_refused_without_confirmation_non_tty(monkeypatch):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.delenv("SEED_DROP_ALL_CONFIRM", raising=False)
    corpus = MagicMock()
    p_db, p_ingest, p_dir = _patch_run(corpus)
    with p_db, p_ingest, p_dir, \
         patch("scripts.seed_corpus.sys.stdin.isatty", return_value=False):
        rc = sc.main(["--drop-all-tenants"])
    assert rc == 1
    corpus.delete_many.assert_not_called()


def test_drop_all_rejects_wrong_confirmation_phrase(monkeypatch):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("SEED_DROP_ALL_CONFIRM", "yes please")
    corpus = MagicMock()
    p_db, p_ingest, p_dir = _patch_run(corpus)
    with p_db, p_ingest, p_dir:
        rc = sc.main(["--drop-all-tenants"])
    assert rc == 1
    corpus.delete_many.assert_not_called()


def test_drop_all_wipes_when_confirmed_in_dev(monkeypatch):
    """Dev env + exact confirmation phrase → the full {} wipe runs."""
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("SEED_DROP_ALL_CONFIRM", sc._DROP_ALL_PHRASE)
    corpus = MagicMock()
    corpus.delete_many.return_value = MagicMock(deleted_count=42)
    p_db, p_ingest, p_dir = _patch_run(corpus)
    with p_db, p_ingest, p_dir:
        rc = sc.main(["--drop-all-tenants"])
    assert rc == 0
    corpus.delete_many.assert_called_once_with({})

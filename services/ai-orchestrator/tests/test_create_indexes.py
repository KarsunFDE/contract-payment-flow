"""
Tests for scripts.create_indexes (adversarial-review findings 1 & 2).

Finding 1 — far_vector_idx must NOT declare chunk_text as a vector filter field
(deliberate ADR-0005 §3 deviation; chunk_text stays indexed in far_text_idx/BM25).

Finding 2 — wait_until_indexes_ready must accept any known-good terminal status
(READY/ACTIVE) or queryable==true as done, and abort on a terminal-bad status
(FAILED/DOES_NOT_EXIST) instead of hanging to the full timeout.

These exercise pure logic only — no MongoDB connection is required.
"""
from __future__ import annotations

import itertools

from app import config
from scripts import create_indexes as ci


# --------------------------------------------------------------------------- #
# Finding 1 — vector index filter fields                                      #
# --------------------------------------------------------------------------- #
def _filter_paths(model) -> set[str]:
    fields = model.document["definition"]["fields"]
    return {f["path"] for f in fields if f.get("type") == "filter"}


def test_vector_index_filter_fields_exact():
    """far_vector_idx filters are exactly {tenant_id, far_part, clause_number}."""
    model = ci.build_vector_index_model()
    assert _filter_paths(model) == {"tenant_id", "far_part", "clause_number"}


def test_vector_index_has_no_chunk_text_filter():
    """chunk_text must not be a vector filter field (finding 1 deviation)."""
    model = ci.build_vector_index_model()
    assert "chunk_text" not in _filter_paths(model)


def test_vector_index_still_has_embedding_vector_field():
    """The vector field itself is untouched — 512-dim cosine on `embedding`."""
    fields = ci.build_vector_index_model().document["definition"]["fields"]
    vector = next(f for f in fields if f.get("type") == "vector")
    assert vector["path"] == "embedding"
    assert vector["numDimensions"] == config.EMBEDDING_DIMENSIONS
    assert vector["similarity"] == "cosine"


def test_text_index_still_indexes_chunk_text():
    """chunk_text remains fully indexed for BM25 in far_text_idx."""
    model = ci.build_text_index_model()
    mapped = model.document["definition"]["mappings"]["fields"]
    assert "chunk_text" in mapped
    assert mapped["chunk_text"]["type"] == "string"


# --------------------------------------------------------------------------- #
# Finding 2 — readiness poll terminal states                                  #
# --------------------------------------------------------------------------- #
class _FakeCollection:
    """Yields a (possibly repeating) sequence of list_search_indexes() responses."""

    def __init__(self, responses):
        # Last response repeats forever so a poll loop can't run past the script.
        self._iter = itertools.chain(responses[:-1], itertools.repeat(responses[-1]))

    def list_search_indexes(self):
        return next(self._iter)


def test_ready_status_is_accepted():
    coll = _FakeCollection([[{"name": "idx", "status": "READY"}]])
    assert ci.wait_until_indexes_ready(coll, ["idx"]) is True


def test_active_status_is_accepted():
    """ACTIVE is a known-good terminal status (Atlas Local / other index types)."""
    coll = _FakeCollection([[{"name": "idx", "status": "ACTIVE"}]])
    assert ci.wait_until_indexes_ready(coll, ["idx"]) is True


def test_queryable_true_is_accepted_regardless_of_status_label():
    """queryable==true means the index can serve queries even on an odd status."""
    coll = _FakeCollection([[{"name": "idx", "status": "PENDING", "queryable": True}]])
    assert ci.wait_until_indexes_ready(coll, ["idx"]) is True


def test_failed_status_aborts():
    coll = _FakeCollection([[{"name": "idx", "status": "FAILED"}]])
    assert ci.wait_until_indexes_ready(coll, ["idx"]) is False


def test_does_not_exist_status_aborts():
    coll = _FakeCollection([[{"name": "idx", "status": "DOES_NOT_EXIST"}]])
    assert ci.wait_until_indexes_ready(coll, ["idx"]) is False


def test_all_indexes_must_become_ready():
    """One READY + one FAILED in the same batch aborts (FAILED wins)."""
    coll = _FakeCollection(
        [[{"name": "a", "status": "READY"}, {"name": "b", "status": "FAILED"}]]
    )
    assert ci.wait_until_indexes_ready(coll, ["a", "b"]) is False

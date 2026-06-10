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
    """far_vector_idx filters use the stored nested shape: tenant_id (top-level)
    plus source_document.far_part / source_document.clause_number (finding 5)."""
    model = ci.build_vector_index_model()
    assert _filter_paths(model) == {
        "tenant_id",
        "source_document.far_part",
        "source_document.clause_number",
    }


def test_vector_index_filter_paths_match_stored_nesting():
    """far_part / clause_number must be filtered at their nested document path,
    not top-level (finding 5: top-level paths matched zero docs)."""
    paths = _filter_paths(ci.build_vector_index_model())
    assert "far_part" not in paths
    assert "clause_number" not in paths
    assert "source_document.far_part" in paths
    assert "source_document.clause_number" in paths


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
# Finding 4 — vector index spec drift (drop + recreate, not skip-by-name)     #
# --------------------------------------------------------------------------- #
def _live_vector_index() -> dict:
    """A list_search_indexes() entry that MATCHES the configured spec."""
    return {
        "name": config.FAR_VECTOR_INDEX,
        "type": "vectorSearch",
        "latestDefinition": {"fields": ci._vector_index_fields()},
    }


def test_no_drift_when_live_index_matches_spec():
    assert ci.vector_index_drift(_live_vector_index()) is None


def test_drift_detected_on_dimension_change():
    """A 512→1024 numDimensions change must be flagged for drop+recreate."""
    live = _live_vector_index()
    for f in live["latestDefinition"]["fields"]:
        if f["type"] == "vector":
            f["numDimensions"] = config.EMBEDDING_DIMENSIONS + 512
    drift = ci.vector_index_drift(live)
    assert drift is not None
    assert "numDimensions" in drift


def test_drift_detected_on_filter_field_change():
    """An extra/stale filter field (e.g. a legacy chunk_text filter) is drift."""
    live = _live_vector_index()
    live["latestDefinition"]["fields"].append({"type": "filter", "path": "chunk_text"})
    drift = ci.vector_index_drift(live)
    assert drift is not None
    assert "filter fields" in drift


def test_drift_detected_on_type_change():
    live = _live_vector_index()
    live["type"] = "search"
    drift = ci.vector_index_drift(live)
    assert drift is not None
    assert "type" in drift


def test_drift_reads_definition_key_fallback():
    """Backends that report `definition` instead of `latestDefinition` still work."""
    live = {
        "name": config.FAR_VECTOR_INDEX,
        "type": "vectorSearch",
        "definition": {"fields": ci._vector_index_fields()},
    }
    assert ci.vector_index_drift(live) is None


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

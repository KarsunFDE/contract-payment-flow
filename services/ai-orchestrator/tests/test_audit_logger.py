"""Tests for audit/logger.py — mocks MongoDB, no live connection required."""
from unittest.mock import MagicMock, patch
import app.audit.logger  # ensure module in sys.modules before patch resolves target

import pytest

from app.schemas import RetrievalAuditRecord


def _make_record(**kwargs) -> RetrievalAuditRecord:
    defaults = dict(
        correlation_id="corr-001",
        sf30_block="13",
        contract_id="W912HQ-24-C-0001",
        tenant_id="far_corpus_global",
        user_id="co-001",
        role="contracting_officer",
        query_text="administrative modification adding new CLIN",
        retrieval_strategy="hybrid_rrf_reranked",
        embedding_model="amazon.titan-embed-text-v2:0",
        latency_ms=420,
    )
    defaults.update(kwargs)
    return RetrievalAuditRecord(**defaults)


def test_write_calls_insert_one():
    mock_col = MagicMock()
    with patch("app.audit.logger.db.get_retrieval_audit", return_value=mock_col):
        from app.audit.logger import write_audit_record
        write_audit_record(_make_record())
    mock_col.insert_one.assert_called_once()


def test_write_serializes_timestamp_as_iso_string():
    mock_col = MagicMock()
    with patch("app.audit.logger.db.get_retrieval_audit", return_value=mock_col):
        from app.audit.logger import write_audit_record
        write_audit_record(_make_record())
    doc = mock_col.insert_one.call_args[0][0]
    assert isinstance(doc["timestamp"], str)
    assert "T" in doc["timestamp"]  # ISO 8601 format


def test_write_includes_all_required_fields():
    mock_col = MagicMock()
    with patch("app.audit.logger.db.get_retrieval_audit", return_value=mock_col):
        from app.audit.logger import write_audit_record
        record = _make_record(
            chunks_retrieved=["c1", "c2"],
            retrieval_scores=[0.82, 0.74],
            reranked_scores=[0.91, 0.78],
        )
        write_audit_record(record)
    doc = mock_col.insert_one.call_args[0][0]
    assert doc["correlation_id"] == "corr-001"
    assert doc["sf30_block"] == "13"
    assert doc["contract_id"] == "W912HQ-24-C-0001"
    assert doc["chunks_retrieved"] == ["c1", "c2"]
    assert doc["retrieval_scores"] == [0.82, 0.74]
    assert doc["reranked_scores"] == [0.91, 0.78]
    assert doc["embedding_model"] == "amazon.titan-embed-text-v2:0"
    assert doc["latency_ms"] == 420


def test_write_raises_on_db_failure():
    mock_col = MagicMock()
    mock_col.insert_one.side_effect = Exception("connection refused")
    with patch("app.audit.logger.db.get_retrieval_audit", return_value=mock_col):
        from app.audit.logger import write_audit_record
        with pytest.raises(Exception, match="connection refused"):
            write_audit_record(_make_record())


def test_elapsed_ms_positive():
    import time
    from app.audit.logger import elapsed_ms
    start = time.monotonic()
    time.sleep(0.01)
    ms = elapsed_ms(start)
    assert ms >= 10
    assert ms < 500

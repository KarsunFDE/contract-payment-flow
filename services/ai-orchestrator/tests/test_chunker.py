"""
test_chunker.py — chunking rules verification (ADR-0005 §13).

Owner: Person A. Pure-function tests — no MongoDB, no Bedrock.

Each test pins one §13 rule so a regression names the rule it broke.
"""
from __future__ import annotations

import pytest

from app import config
from app.ingestion import chunker
from app.schemas import SourceDocument


# Representative FAR-shaped fixture text — clause headers + paragraphs.
FAR_43_SAMPLE = """\
43.103 Types of contract modifications.

(a) Bilateral. A bilateral modification (supplemental agreement) is a
contract modification that is signed by the contractor and the contracting
officer. Bilateral modifications are used to make negotiated equitable
adjustments resulting from the issuance of a change order.

(b) Unilateral. A unilateral modification is a contract modification that
is signed only by the contracting officer. Unilateral modifications are
used to make administrative changes, issue change orders, and make changes
authorized by clauses other than a changes clause.

43.104 Notification of contract changes.

(a) When a contractor considers that the Government has effected or may
effect a change in the contract that has not been identified as such in
writing and signed by the contracting officer, it is necessary that the
contractor notify the Government in writing as soon as possible.
"""


@pytest.fixture
def far_source() -> SourceDocument:
    return SourceDocument(
        title="FAR Part 43 — Contract Modifications",
        far_part="43",
        subpart="43.1",
        clause_number="43.103",
        url="https://www.acquisition.gov/far/part-43",
    )


def test_splitter_uses_adr_configuration():
    """Splitter built with 512-token size / 64-token overlap (§13 config)."""
    splitter = chunker.build_text_splitter()
    assert splitter._chunk_size == config.CHUNK_SIZE_TOKENS
    assert splitter._chunk_overlap == config.CHUNK_OVERLAP_TOKENS


def test_chunks_respect_clause_boundaries(far_source):
    """§13 rule 1/2 — clause number never separated from its definition text.

    "43.103" and "(a) Bilateral..." must land in the same chunk.
    """
    chunks = chunker.chunk_document(FAR_43_SAMPLE, far_source)
    texts = [c["chunk_text"] for c in chunks]

    clause_chunk = next((t for t in texts if "43.103" in t), None)
    assert clause_chunk is not None, "No chunk contains '43.103'"
    assert "Bilateral" in clause_chunk or "(a)" in clause_chunk, (
        "Clause header '43.103' was split from its opening text"
    )


def test_chunks_inherit_section_metadata(far_source):
    """§13 rule 3 — chunks under 43.104 carry clause_number '43.104'."""
    chunks = chunker.chunk_document(FAR_43_SAMPLE, far_source)

    chunks_104 = [c for c in chunks if "43.104" in c["chunk_text"] or "Notification" in c["chunk_text"]]
    assert chunks_104, "Expected at least one chunk from the 43.104 section"

    for c in chunks_104:
        assert c["clause_number"] == "43.104", (
            f"Chunk from 43.104 section has wrong clause_number: {c['clause_number']!r}"
        )
        assert c["far_part"] == "43"
        assert c["subpart"] == "43.1"


def test_short_fragments_discarded(far_source):
    """§13 rule 4 — fragments under MIN_CHUNK_CHARS (100) are dropped."""
    # Inject a lone page-number line that would produce a tiny fragment.
    doc_with_noise = "Page 5\n\n" + FAR_43_SAMPLE
    chunks = chunker.chunk_document(doc_with_noise, far_source)

    for c in chunks:
        assert len(c["chunk_text"]) >= config.MIN_CHUNK_CHARS, (
            f"Chunk below MIN_CHUNK_CHARS ({config.MIN_CHUNK_CHARS}): {c['chunk_text']!r}"
        )


def test_chunk_sequence_is_positional(far_source):
    """chunk_sequence increments by document position, starting at 0."""
    chunks = chunker.chunk_document(FAR_43_SAMPLE, far_source)
    sequences = [c["chunk_sequence"] for c in chunks]
    assert sequences == list(range(len(chunks)))

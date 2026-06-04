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
    chunks = chunker.chunk_document(FAR_43_SAMPLE, far_source).chunks
    texts = [c["chunk_text"] for c in chunks]

    clause_chunk = next((t for t in texts if "43.103" in t), None)
    assert clause_chunk is not None, "No chunk contains '43.103'"
    assert "Bilateral" in clause_chunk or "(a)" in clause_chunk, (
        "Clause header '43.103' was split from its opening text"
    )


def test_chunks_inherit_section_metadata(far_source):
    """§13 rule 3 — chunks under 43.104 carry clause_number '43.104'."""
    chunks = chunker.chunk_document(FAR_43_SAMPLE, far_source).chunks

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
    chunks = chunker.chunk_document(doc_with_noise, far_source).chunks

    for c in chunks:
        assert len(c["chunk_text"]) >= config.MIN_CHUNK_CHARS, (
            f"Chunk below MIN_CHUNK_CHARS ({config.MIN_CHUNK_CHARS}): {c['chunk_text']!r}"
        )


def test_chunk_sequence_is_positional(far_source):
    """chunk_sequence increments by document position, starting at 0."""
    chunks = chunker.chunk_document(FAR_43_SAMPLE, far_source).chunks
    sequences = [c["chunk_sequence"] for c in chunks]
    assert sequences == list(range(len(chunks)))


# --- §13 clause-header recognition (CLAUSE_HEADER_PATTERN) ---

def test_extract_section_metadata_one_and_two_digit_sections():
    """1- and 2-digit FAR sections (32.7, 42.15) are recognized as headers.

    The legacy `\\d{3}` pattern missed these entirely.
    """
    text = (
        "32.7 Contract funding.\n\n"
        "Agencies shall not contract for goods absent available funds.\n\n"
        "42.15 Contractor performance information.\n\n"
        "Past performance evaluations are recorded in CPARS.\n"
    )
    sections = chunker.extract_section_metadata(text)
    by_clause = {s["clause_number"]: s for s in sections}

    assert "32.7" in by_clause
    assert by_clause["32.7"]["far_part"] == "32"
    assert by_clause["32.7"]["subpart"] == "32.7"

    assert "42.15" in by_clause
    assert by_clause["42.15"]["far_part"] == "42"
    assert by_clause["42.15"]["subpart"] == "42.1"


def test_extract_section_metadata_dash_suffix_section():
    """Dash-suffixed clauses like 43.205-1 are recognized; subpart is 43.2."""
    text = (
        "43.205-1 Changes.\n\n"
        "The contracting officer may direct changes within the general scope.\n"
    )
    sections = chunker.extract_section_metadata(text)
    assert len(sections) == 1
    section = sections[0]
    assert section["clause_number"] == "43.205-1"
    assert section["far_part"] == "43"
    assert section["subpart"] == "43.2"


def test_extract_section_metadata_three_digit_section_unchanged():
    """3-digit sections (43.103) still derive subpart from the first digit."""
    text = "43.103 Types of contract modifications.\n\nA bilateral modification.\n"
    sections = chunker.extract_section_metadata(text)
    assert len(sections) == 1
    assert sections[0]["clause_number"] == "43.103"
    assert sections[0]["subpart"] == "43.1"


def test_prose_decimals_not_treated_as_headers():
    """Decimal numbers in prose must not be detected as clause headers.

    Mid-line decimals ("increased by 3.5 percent") never start a line, and a
    line-leading number followed by more digits ("12.345.678") fails the
    trailing-non-digit lookahead.
    """
    text = (
        "The equitable adjustment increased the price by 3.5 percent overall.\n\n"
        "12.345.678 is an account reference, not a FAR clause.\n\n"
        "See 32.7 for funding rules, which appears mid-sentence here.\n"
    )
    sections = chunker.extract_section_metadata(text)
    assert sections == [], f"Prose decimals wrongly matched as headers: {sections}"


def test_dash_suffix_header_recognized_in_chunk_document(far_source):
    """End-to-end: a 43.205-1 header propagates its clause_number to chunks."""
    text = (
        "43.205-1 Changes.\n\n"
        + "The contracting officer may unilaterally direct changes within the "
        "general scope of the contract under the Changes clause, and the "
        "contractor must continue performance while the adjustment is negotiated.\n"
    )
    chunks = chunker.chunk_document(text, far_source).chunks
    assert chunks, "Expected at least one chunk from the 43.205-1 section"
    assert all(c["clause_number"] == "43.205-1" for c in chunks)
    assert all(c["subpart"] == "43.2" for c in chunks)


def test_chunk_document_returns_real_discarded_count(far_source):
    """chunk_document reports how many sub-MIN_CHUNK_CHARS fragments it dropped."""
    # "Page 5" alone is far below MIN_CHUNK_CHARS and becomes a discarded fragment.
    doc_with_noise = "Page 5\n\n" + FAR_43_SAMPLE
    result = chunker.chunk_document(doc_with_noise, far_source)
    assert result.discarded_count >= 1
    # The kept list excludes every discarded fragment.
    assert all(len(c["chunk_text"]) >= config.MIN_CHUNK_CHARS for c in result.chunks)

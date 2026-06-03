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


@pytest.mark.skip(reason="Person A W1 — chunker not implemented yet")
def test_splitter_uses_adr_configuration():
    """Splitter built with 512-token size / 64-token overlap (§13 config)."""
    # TODO(A): build_text_splitter(); assert chunk size + overlap match config.
    ...


@pytest.mark.skip(reason="Person A W1 — chunker not implemented yet")
def test_chunks_respect_clause_boundaries(far_source):
    """§13 rule 1/2 — clause number never separated from its definition text.

    "43.103" and "(a) Bilateral..." must land in the same chunk.
    """
    # TODO(A): chunk_document(FAR_43_SAMPLE, far_source); find the chunk
    #   containing "43.103" and assert it also contains "(a) Bilateral".
    ...


@pytest.mark.skip(reason="Person A W1 — chunker not implemented yet")
def test_chunks_inherit_section_metadata(far_source):
    """§13 rule 3 — chunks under 43.104 carry clause_number '43.104'."""
    # TODO(A): assert chunks after the 43.104 header report clause_number
    #   "43.104", not the document-level "43.103".
    ...


@pytest.mark.skip(reason="Person A W1 — chunker not implemented yet")
def test_short_fragments_discarded(far_source):
    """§13 rule 4 — fragments under MIN_CHUNK_CHARS (100) are dropped."""
    # TODO(A): feed text with a stray page-number line; assert no returned
    #   chunk_text is shorter than config.MIN_CHUNK_CHARS.
    ...


@pytest.mark.skip(reason="Person A W1 — chunker not implemented yet")
def test_chunk_sequence_is_positional(far_source):
    """chunk_sequence increments by document position, starting at 0."""
    # TODO(A): assert sequences == list(range(len(chunks))).
    ...

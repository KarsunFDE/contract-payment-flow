"""
chunker.py — FAR/DFARS/WAWF/PIEE document chunking (ADR-0005 §13).

Owner: Person A (write path).

Splits source documents into section-boundary chunks using
``RecursiveCharacterTextSplitter`` from ``langchain-text-splitters``.
Configuration comes from app.config (512 tokens / 64 overlap).

ADR-0005 §13 chunking rules implemented here:
  1. Split at clause/section boundaries first — prefer ``\\n\\n`` splits,
     then ``\\n``, then ``. `` (sentence) as last resort.
  2. Never split a FAR clause number from its definition text
     (e.g. "43.103(a)" and its governing sentence stay in one chunk).
  3. Each chunk inherits ``far_part``, ``subpart``, ``clause_number``
     metadata from its parent section header.
  4. Discard fragments shorter than MIN_CHUNK_CHARS (100) — page numbers,
     headers, artifacts.

Rule 2 is enforced structurally: each detected clause section is split
independently, so the clause header can never land in a different chunk
than its opening text. See chunk_document() for details.

Do NOT write a custom chunker beyond this splitter — any custom parser
requires team approval (ADR-0005 §13 / Guideline 6).
"""
from __future__ import annotations

import logging
import re
from typing import NamedTuple

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app import config
from app.schemas import SourceDocument

log = logging.getLogger("ai-orchestrator.ingestion.chunker")

# §13 rule 1 — separator priority: clause/section boundary, paragraph, sentence.
SEPARATORS = ["\n\n", "\n", ". "]

# Matches FAR-style clause headers at the start of a line, e.g.
#   "43.103 Types of contract modifications."   (3-digit section)
#   "32.7 Contract funding."                     (1-digit section)
#   "42.15 Contractor performance information."  (2-digit section)
#   "43.205-1 Changes."                          (dash-suffixed clause)
# Group 1 = part number ("43"), Group 2 = section ("103" / "7" / "205-1").
#
# False-positive guard: the number must (a) start the line (MULTILINE ^) and
# (b) be followed by whitespace then a non-digit — i.e. the clause title text.
# This keeps prose decimals out: "3.5 percent" fails because the line does not
# start there; "1.2 million" would also fail the trailing non-digit test.
# A FAR section is 1–3 digits; a real header like "43.103 Types of..." or
# "43.205-1 Changes." satisfies the lookahead, a numeric run like "12.345.678"
# does not (the trailing char after the captured number is a digit).
CLAUSE_HEADER_PATTERN = re.compile(
    r"^(\d{1,2})\.(\d{1,3}(?:-\d+)?)(?=\s+\D)",
    re.MULTILINE,
)


class ChunkResult(NamedTuple):
    """Result of chunk_document: kept chunks plus how many were discarded.

    chunks: list of chunk dicts ready for embedding (see chunk_document).
    discarded_count: number of sub-MIN_CHUNK_CHARS fragments dropped (§13 rule 4).
    """

    chunks: list[dict]
    discarded_count: int


def build_text_splitter() -> RecursiveCharacterTextSplitter:
    """Construct the configured splitter (512 tokens, 64 overlap, §13 separators).

    Uses from_tiktoken_encoder so chunk_size means tokens (Titan V2 sizing),
    not raw characters — avoids truncation inside BedrockEmbeddings (§3).
    """
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=config.CHUNK_SIZE_TOKENS,
        chunk_overlap=config.CHUNK_OVERLAP_TOKENS,
        separators=SEPARATORS,
    )


def extract_section_metadata(document_text: str) -> list[dict]:
    """Map each clause section of the document to its FAR metadata.

    Scans for clause headers (e.g. "43.103 Types of contract modifications.")
    and returns one entry per detected section with its character span and
    inherited metadata. Chunks within each section receive these values
    (§13 rule 3).

    Returns:
        List of dicts: {"start": int, "end": int, "far_part": str,
        "subpart": str, "clause_number": str}.
        Empty list if no clause headers are found.
    """
    matches = list(CLAUSE_HEADER_PATTERN.finditer(document_text))
    sections = []

    for i, match in enumerate(matches):
        far_part = match.group(1)              # e.g. "43"
        section = match.group(2)               # e.g. "103" / "7" / "205-1"
        # clause_number excludes the trailing-non-digit lookahead, so it is
        # just "part.section" ("43.103", "32.7", "43.205-1").
        clause_number = f"{far_part}.{section}"
        # Subpart = part + first digit of the section number, ignoring any
        # dash suffix: "43.103" → "43.1", "42.15" → "42.1", "32.7" → "32.7",
        # "43.205-1" → "43.2". The first digit of the section is the subpart
        # digit regardless of how many section digits follow.
        subpart = f"{far_part}.{section[0]}"

        start = match.start()
        # Section ends where the next clause header begins (or at doc end).
        end = matches[i + 1].start() if i + 1 < len(matches) else len(document_text)

        sections.append({
            "start": start,
            "end": end,
            "far_part": far_part,
            "subpart": subpart,
            "clause_number": clause_number,
        })

    return sections


def chunk_document(
    document_text: str,
    source: SourceDocument,
) -> ChunkResult:
    """Split one source document into chunk dicts ready for embedding.

    Enforces all four §13 rules:
      Rule 1 — RCSTS uses separator priority [\\n\\n, \\n, ". "].
      Rule 2 — Each clause section is split independently (see below).
      Rule 3 — Chunks inherit far_part/subpart/clause_number from section.
      Rule 4 — Fragments < MIN_CHUNK_CHARS are discarded before return.

    Rule 2 implementation detail:
      Instead of splitting the full document at once, we first detect clause
      boundaries via extract_section_metadata(), then call split_text() on
      each section independently. This guarantees the clause header (e.g.
      "43.103") and its first sentence always land in the same chunk — the
      splitter never sees a boundary between the header and its opening text.

    Args:
        document_text: Raw text of the FAR/DFARS/WAWF/PIEE source document.
        source: Provenance of the document (title, far_part, url, ...).

    Returns:
        A ChunkResult(chunks, discarded_count) where ``chunks`` is a list of
        dicts with keys chunk_text, chunk_sequence, far_part, subpart,
        clause_number (embedding + remaining provenance fields are added
        downstream by pipeline.py), and ``discarded_count`` is the number of
        sub-MIN_CHUNK_CHARS fragments dropped under §13 rule 4.
    """
    splitter = build_text_splitter()
    sections = extract_section_metadata(document_text)

    # Accumulate (chunk_text, far_part, subpart, clause_number) tuples
    # before filtering so we can log the discard count accurately.
    raw_splits: list[tuple[str, str, str, str]] = []

    def _split_region(text: str, far_part: str, subpart: str, clause_number: str) -> None:
        """Split one text region and append results with inherited metadata."""
        for chunk_text in splitter.split_text(text):
            raw_splits.append((chunk_text, far_part, subpart, clause_number))

    if not sections:
        # No clause headers detected — split the whole doc with source-level metadata.
        _split_region(document_text, source.far_part, source.subpart, source.clause_number)
    else:
        # Preamble: text before the first clause header inherits source metadata.
        if sections[0]["start"] > 0:
            preamble = document_text[: sections[0]["start"]]
            _split_region(preamble, source.far_part, source.subpart, source.clause_number)

        # Split each detected clause section independently (§13 rule 2).
        for section in sections:
            section_text = document_text[section["start"] : section["end"]]
            _split_region(
                section_text,
                section["far_part"],
                section["subpart"],
                section["clause_number"],
            )

    # Rule 4 — discard fragments below the minimum character threshold.
    kept: list[dict] = []
    for chunk_text, far_part, subpart, clause_number in raw_splits:
        if len(chunk_text) < config.MIN_CHUNK_CHARS:
            continue  # page numbers, lone headers, whitespace artifacts
        kept.append({
            "chunk_text": chunk_text,
            "far_part": far_part,
            "subpart": subpart,
            "clause_number": clause_number,
        })

    # Assign sequential position within this source document (§12 chunk_sequence).
    for seq, chunk in enumerate(kept):
        chunk["chunk_sequence"] = seq

    discarded_count = len(raw_splits) - len(kept)
    log.info(
        "chunked %r — raw splits: %d  kept: %d  discarded: %d (< %d chars)",
        source.title,
        len(raw_splits),
        len(kept),
        discarded_count,
        config.MIN_CHUNK_CHARS,
    )

    return ChunkResult(chunks=kept, discarded_count=discarded_count)

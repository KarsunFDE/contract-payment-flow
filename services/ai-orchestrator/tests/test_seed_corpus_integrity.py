"""Seed corpus integrity gate (security review finding 7).

The seed corpus is retrieved as AUTHORITATIVE DFARS/FAR/CFR text into
payment/SF-30 workflows, so a transcription error (e.g. "4 U.S.C. 9606" instead
of the correct CERCLA "42 U.S.C. 9606") would be served as law. This test hashes
every embedded seed file against a known-good snapshot (seed_corpus_manifest.json)
BEFORE it can be embedded, so any drift from verified source text fails CI.

If a seed file legitimately changes, verify the new text against the canonical
acquisition.gov / DFARS / eCFR source, then regenerate the manifest hashes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

# tests/ -> ai-orchestrator/ -> services/ -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST_PATH = Path(__file__).resolve().parent / "seed_corpus_manifest.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
_SEED_DIR = _REPO_ROOT / _MANIFEST["seed_dir"]
_EXPECTED: dict[str, str] = _MANIFEST["sha256"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ingested_seed_files() -> list[Path]:
    """The files pipeline.ingest_seed_corpus actually embeds: *.md minus README."""
    return sorted(p for p in _SEED_DIR.glob("*.md") if p.name.lower() != "readme.md")


pytestmark = pytest.mark.skipif(
    not _SEED_DIR.is_dir(),
    reason=f"seed dir not present at {_SEED_DIR} (not mounted in this environment)",
)


def test_manifest_covers_exactly_the_ingested_files():
    """No embedded seed file may be unpinned, and the manifest must not list
    files that no longer exist — either gap would let drift slip through."""
    on_disk = {p.name for p in _ingested_seed_files()}
    pinned = set(_EXPECTED)
    assert on_disk == pinned, (
        f"unpinned (new) files: {sorted(on_disk - pinned)}; "
        f"stale manifest entries: {sorted(pinned - on_disk)}"
    )


@pytest.mark.parametrize("name", sorted(_EXPECTED))
def test_seed_file_matches_known_good_hash(name):
    path = _SEED_DIR / name
    assert path.is_file(), f"pinned seed file missing: {name}"
    assert _sha256(path) == _EXPECTED[name], (
        f"{name} drifted from the verified-source snapshot. If this change is "
        "intentional, verify the text against the canonical acquisition.gov / "
        "DFARS / eCFR source, then regenerate seed_corpus_manifest.json."
    )


def test_cercla_citation_is_correct_in_dfars_232_9():
    """Regression for the specific finding: CERCLA §106 is 42 U.S.C. 9606, not
    4 U.S.C. — guards the exact transcription error that prompted this gate."""
    text = (_SEED_DIR / "dfars-232-9-prompt-payment.md").read_text(encoding="utf-8")
    assert "42 U.S.C. 9606" in text
    assert "4 U.S.C. 9606" not in text

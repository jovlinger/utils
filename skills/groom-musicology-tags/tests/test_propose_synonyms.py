"""Tests for propose_synonyms (fixture multi-provider bags)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SKILL.parents[1] / "shadup"))

import propose_synonyms as ps  # noqa: E402


def _write_meta(album: Path, provider: str, *, genres: list[str], tags: list[str] | None = None) -> None:
    album.mkdir(parents=True, exist_ok=True)
    doc = {"metadata": {"genres": genres, "tags": tags or []}}
    (album / f".meta.{provider}.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    """Two albums: CCR-like genre overlap + decade axis separation."""
    a = tmp_path / "Creedence Clearwater Revival - Mardi Gras"
    _write_meta(
        a,
        "discogs",
        genres=["Rock", "Country Rock", "Folk Rock"],
    )
    _write_meta(
        a,
        "lastfm",
        genres=["blues rock", "classic rock", "country rock", "rock", "southern rock"],
    )

    b = tmp_path / "Decade Mix - Example"
    _write_meta(b, "discogs", genres=["Rock", "Pop"])
    _write_meta(b, "lastfm", genres=["rock", "80s", "90s", "pop"])

    # Second album reinforces country rock / rock slug matches
    c = tmp_path / "Other - Country Rock Sample"
    _write_meta(c, "discogs", genres=["Country Rock", "Rock"])
    _write_meta(c, "lastfm", genres=["country rock", "rock", "90s"])

    return tmp_path


def test_slug_synonym_candidate(corpus: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    doc = ps.propose(corpus, min_support=2, min_pmi=0.5, min_jaccard=0.1)
    ps.write_report(doc, out, write_patch=True)

    pairs = {(r["a"], r["b"]) for r in doc["candidates"]}
    # Discogs "Country Rock" ↔ lastfm "country rock" (slug equal, support≥2)
    assert (
        "discogs:Country Rock",
        "lastfm:country rock",
    ) in pairs or (
        "lastfm:country rock",
        "discogs:Country Rock",
    ) in pairs

    assert all(r.get("slug_equal") for r in doc["candidates"])
    assert (out / "report.json").is_file()
    assert (out / "report.tsv").is_file()
    assert (out / "map_patch.json").is_file()


def test_related_not_clustered_as_synonym(corpus: Path) -> None:
    """High co-occurrence with different slugs is related, not a synonym candidate."""
    doc = ps.propose(corpus, min_support=1, min_pmi=0.0, min_jaccard=0.0)
    for r in doc["candidates"]:
        assert r["slug_equal"]
    assert any(
        r.get("reason", "").startswith("axis_mismatch") for r in doc["non_synonyms"]
    )


def test_decade_same_axis_non_synonym() -> None:
    sa = ps.LabelStats(axis="year", canon="year;80s", slug="80s")
    sb = ps.LabelStats(axis="year", canon="year;90s", slug="90s")
    assert ps.is_non_synonym(sa, sb) == "same_axis_different_value:year;80s!=year;90s"


def test_map_patch_skips_existing(corpus: Path, tmp_path: Path) -> None:
    syn = tmp_path / "syn"
    syn.mkdir()
    (syn / "discogs.json").write_text(
        json.dumps({"map": {"Country Rock": "genre;countryrock"}}),
        encoding="utf-8",
    )
    (syn / "lastfm.json").write_text(json.dumps({"map": {}}), encoding="utf-8")
    doc = ps.propose(
        corpus,
        min_support=2,
        min_pmi=0.5,
        min_jaccard=0.1,
        synonyms_dir=syn,
    )
    # discogs Country Rock already mapped → not in patch
    assert "Country Rock" not in doc["map_patch"].get("discogs", {})
    # lastfm country rock may still be proposed
    assert "country rock" in doc["map_patch"].get("lastfm", {}) or doc["map_patch"]

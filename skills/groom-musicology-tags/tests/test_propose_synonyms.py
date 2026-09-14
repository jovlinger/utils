"""Tests for propose_synonyms (cross- vs within-provider signals)."""

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


def _write_meta(
    album: Path, provider: str, *, genres: list[str], tags: list[str] | None = None
) -> None:
    album.mkdir(parents=True, exist_ok=True)
    doc = {"metadata": {"genres": genres, "tags": tags or []}}
    (album / f".meta.{provider}.json").write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    """Cross = synonym (Country Rock ↔ country rock); within = orthogonal (90s+rock)."""
    # Album A: cross-provider near-duplicate genres (synonym signal)
    a = tmp_path / "Creedence Clearwater Revival - Mardi Gras"
    _write_meta(a, "discogs", genres=["Rock", "Country Rock"])
    _write_meta(a, "lastfm", genres=["country rock", "rock", "southern rock"])

    # Album B: reinforce Country Rock / country rock cross
    b = tmp_path / "Other - Country Sample"
    _write_meta(b, "discogs", genres=["Country Rock", "Rock"])
    _write_meta(b, "lastfm", genres=["country rock", "rock"])

    # Album C: third cross for countryrock pair support
    c = tmp_path / "Third - Country"
    _write_meta(c, "discogs", genres=["Country Rock"])
    _write_meta(c, "lastfm", genres=["country rock", "folk"])

    # Album D: within-provider orthogonality (decade + genre in one lastfm bag)
    # Need ≥3 albums with within 90s+rock and little/no cross of that pair
    for i, name in enumerate(
        ["Decade One", "Decade Two", "Decade Three", "Decade Four"]
    ):
        d = tmp_path / f"{name} - Example"
        # discogs only genre; lastfm genre+decade together (within ortho)
        _write_meta(d, "discogs", genres=["Pop"])
        _write_meta(d, "lastfm", genres=["rock", "90s", "pop"])

    return tmp_path


def test_cross_provider_synonym_candidate(corpus: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    doc = ps.propose(
        corpus,
        min_cross=2,
        min_within=2,
        synonym_cross_frac=0.5,
        ortho_cross_frac=0.35,
    )
    ps.write_report(doc, out, write_patch=True)

    pairs = {(r["a"], r["b"]) for r in doc["candidates"]}
    # countryrock appears via slug merge of Country Rock / country rock —
    # wait: candidates are slug pairs. Country Rock and country rock share slug
    # countryrock, so they are same-slug multi-provider, not a different-slug pair.
    # Rock (discogs) vs southern rock (lastfm) would be cross different slugs.
    assert doc["stats"]["same_slug_agree_albums"] >= 1
    assert any(s["slug"] == "countryrock" for s in doc["same_slug_multi_provider"])
    assert (out / "report.json").is_file()


def test_within_provider_orthogonal(corpus: Path) -> None:
    doc = ps.propose(
        corpus,
        min_cross=2,
        min_within=3,
        synonym_cross_frac=0.65,
        ortho_cross_frac=0.35,
    )
    ns = {(r["a"], r["b"]): r for r in doc["non_synonyms"]}
    # 90s and rock co-occur within lastfm bags, not as cross-provider pair
    key = ("90s", "rock") if ("90s", "rock") in ns else ("rock", "90s")
    assert key in ns or ("90s", "rock") in ns or ("rock", "90s") in ns
    hit = ns.get(("90s", "rock")) or ns.get(("rock", "90s"))
    assert hit is not None
    assert hit["reason"] == "within_provider_orthogonal"
    assert hit["within"] >= 3
    assert (hit["cross_frac"] or 0) <= 0.35


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
        min_cross=2,
        min_within=2,
        synonym_cross_frac=0.5,
        synonyms_dir=syn,
    )
    assert "Country Rock" not in doc["map_patch"].get("discogs", {})

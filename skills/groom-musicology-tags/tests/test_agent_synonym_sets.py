"""Tests for tag_vocab + agent_synonym_sets merge."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
UTILS = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(UTILS / "shadup"))

import agent_synonym_sets as ag  # noqa: E402
import tag_vocab as tv  # noqa: E402


def test_surface_key_case_and_hyphen() -> None:
    assert tv.surface_key("Trip-Hop") == tv.surface_key("trip hop")
    assert tv.surface_key("  Rock ") == "rock"
    assert tv.surface_key("Alternative_Rock") == "alternative rock"


def test_plural_peel_only_when_both_present() -> None:
    by = {
        "lastfm": Counter({"album": 2, "albums": 3, "blues": 5}),
    }
    doc = tv.build_vocab(by)
    keys = {e["key"] for e in doc["entries"]}
    assert "album" in keys
    assert "albums" not in keys  # merged into album
    assert "blues" in keys  # not peeled to blue


def test_prepare_and_merge(tmp_path: Path) -> None:
    by = {
        "discogs": Counter({"Trip Hop": 4, "Rock": 10}),
        "lastfm": Counter({"trip-hop": 3, "rock": 8, "90s": 5}),
    }
    vocab = tv.build_vocab(by, include_providers=["discogs", "lastfm"])
    vocab_path = tmp_path / "vocab.json"
    vocab_path.write_text(json.dumps(vocab), encoding="utf-8")

    batches = tmp_path / "batches"
    ag.prepare_batches(
        vocab, batches, batch_size=50, prompt_path=ag.DEFAULT_PROMPT
    )
    assert (batches / "batch-000.json").is_file()
    assert (batches / "PROMPT.md").is_file()

    resp = {
        "batch_id": "batch-000",
        "sets": [
            {
                "canonical": "trip hop",
                "members": ["Trip Hop", "trip-hop"],
                "type_hint": "genre",
            },
            {"canonical": "rock", "members": ["Rock", "rock"], "type_hint": "genre"},
        ],
        "singletons": ["90s"],
        "dropped": [],
    }
    (batches / "responses" / "batch-000.json").write_text(
        json.dumps(resp), encoding="utf-8"
    )

    syn = tmp_path / "syn"
    syn.mkdir()
    (syn / "discogs.json").write_text(json.dumps({"map": {}}), encoding="utf-8")
    (syn / "lastfm.json").write_text(json.dumps({"map": {}}), encoding="utf-8")

    doc = ag.merge_responses(
        vocab, batches / "responses", synonyms_dir=syn, force_mapped=False
    )
    assert doc["stats"]["sets"] == 2
    assert doc["map_patch"]["discogs"].get("Trip Hop") == "genre;triphop"
    assert doc["map_patch"]["lastfm"].get("trip-hop") == "genre;triphop"
    assert doc["map_patch"]["discogs"].get("Rock") == "genre;rock"

"""Tests for ``meta_combine`` (provider sidecars → ``.meta.combined.json``)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SHADUP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SHADUP))

import meta_combine as mc  # noqa: E402


def _write_provider(album: Path, provider: str, *, genres=None, tags=None, artist=None, album_name=None, year=None) -> None:
    payload = {
        "schema": 1,
        "directory": str(album),
        "metadata": {
            "provider": provider,
            "matched": True,
            "artist": artist,
            "album": album_name,
            "year": year,
            "genres": genres or [],
            "tags": tags or [],
        },
    }
    (album / f".meta.{provider}.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def test_combine_maps_genres_and_fields(tmp_path: Path) -> None:
    album = tmp_path / "So"
    album.mkdir()
    syn = tmp_path / "syn"
    syn.mkdir()
    (syn / "discogs.json").write_text(
        json.dumps(
            {
                "provider": "discogs",
                "map": {"Art Rock": "genre;artrock", "Pop Rock": "genre;poprock"},
                "dropped": [],
            }
        ),
        encoding="utf-8",
    )
    _write_provider(
        album,
        "discogs",
        genres=["Art Rock", "Pop Rock"],
        artist="Peter Gabriel",
        album_name="So",
        year="1986",
    )
    doc = mc.combine_from_providers(album, synonyms_dir=syn, providers=["discogs"])
    assert "genre;artrock" in doc["tags"]
    assert "genre;poprock" in doc["tags"]
    assert "artist;petergabriel" in doc["tags"]
    assert "album;so" in doc["tags"]
    assert "year;1986" in doc["tags"]
    assert mc.is_vfat_safe(doc["tags"][0])


def test_union_children_keeps_both(tmp_path: Path) -> None:
    box = tmp_path / "box"
    cd1 = box / "CD1"
    cd2 = box / "CD2"
    for d in (box, cd1, cd2):
        d.mkdir(parents=True)
    (cd1 / mc.COMBINED_NAME).write_text(
        json.dumps({"tags": ["genre;ambient", "artist;a"]}) + "\n"
    )
    (cd2 / mc.COMBINED_NAME).write_text(
        json.dumps({"tags": ["genre;downtempo", "artist;a"]}) + "\n"
    )
    doc = mc.combine_union_children(box, [cd1, cd2])
    assert doc["tags"] == ["artist;a", "genre;ambient", "genre;downtempo"]


def test_ensure_empty_sidecars(tmp_path: Path) -> None:
    album = tmp_path / "a"
    album.mkdir()
    written = mc.ensure_empty_sidecars(album, ["musicbrainz", "discogs"])
    assert len(written) == 2
    payload = json.loads((album / ".meta.musicbrainz.json").read_text())
    assert payload["metadata"]["matched"] is False
    assert payload["metadata"]["genres"] == []


def test_combined_stale_on_new_audio(tmp_path: Path) -> None:
    album = tmp_path / "a"
    album.mkdir()
    (album / "t.flac").write_bytes(b"x")
    assert mc.combined_is_stale(album, audio_exts={".flac"})
    mc.write_combined(album, {"schema": 1, "tags": []})
    assert not mc.combined_is_stale(album, audio_exts={".flac"})
    # Newer audio
    import time

    time.sleep(0.05)
    (album / "u.flac").write_bytes(b"y")
    assert mc.combined_is_stale(album, audio_exts={".flac"})

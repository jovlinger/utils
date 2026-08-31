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


def test_skips_johan_unless_requested(tmp_path: Path) -> None:
    album = tmp_path / "Leonard Cohen - Songs of Leonard Cohen"
    album.mkdir()
    syn = tmp_path / "syn"
    syn.mkdir()
    (syn / "lastfm.json").write_text(
        json.dumps({"map": {"folk": "genre;folk"}, "dropped": []}),
        encoding="utf-8",
    )
    _write_provider(
        album,
        "lastfm",
        genres=["folk"],
        artist="Leonard Cohen",
        album_name="Songs of Leonard Cohen",
        year="1968",
    )
    _write_provider(album, "johan", genres=["malesinger"], artist="leonardcohen")
    skipped = mc.combine_from_providers(album, synonyms_dir=syn)
    assert "johan" not in skipped["providers"]
    assert "genre;malesinger" not in skipped["tags"]
    assert "genre;folk" in skipped["tags"]
    explicit = mc.combine_from_providers(
        album, synonyms_dir=syn, providers=["lastfm", "johan"]
    )
    assert "johan" in explicit["providers"]
    assert "genre;malesinger" in explicit["tags"]


def test_years_not_genres_and_artist_slug_merge(tmp_path: Path) -> None:
    album = tmp_path / "Leonard Cohen - Songs of Leonard Cohen"
    album.mkdir()
    syn = tmp_path / "syn"
    syn.mkdir()
    (syn / "lastfm.json").write_text(
        json.dumps(
            {
                "map": {
                    "00s": "genre;00s",
                    "90's": "genre;90s",
                    "leonard cohen": "genre;leonard cohen",
                },
                "dropped": [],
            }
        ),
        encoding="utf-8",
    )
    _write_provider(
        album,
        "lastfm",
        genres=["00s", "90's", "leonard cohen", "leonardcohen"],
        artist="Leonard Cohen",
        album_name="Songs of Leonard Cohen",
        year="1968",
    )
    doc = mc.combine_from_providers(album, synonyms_dir=syn, providers=["lastfm"])
    assert "year;200x" in doc["tags"]
    assert "year;199x" in doc["tags"]
    assert "genre;00s" not in doc["tags"]
    assert "genre;leonardcohen" not in doc["tags"]
    assert "genre;leonard cohen" not in doc["tags"]
    assert "artist;leonardcohen" in doc["tags"]
    assert doc["tags"].count("artist;leonardcohen") == 1


def test_va_soundtrack_drops_various_artists(tmp_path: Path) -> None:
    album = tmp_path / "VA - Pulp Fiction- Music From the Motion Picture"
    album.mkdir()
    syn = tmp_path / "syn"
    syn.mkdir()
    (syn / "musicbrainz.json").write_text(
        json.dumps({"map": {}, "dropped": []}), encoding="utf-8"
    )
    _write_provider(
        album,
        "musicbrainz",
        artist="Various Artists",
        album_name="Pulp Fiction: Music From the Motion Picture",
        year="1994",
    )
    doc = mc.combine_from_providers(
        album, synonyms_dir=syn, providers=["musicbrainz"]
    )
    assert "artist;variousartists" not in doc["tags"]
    assert "artist;va" not in doc["tags"]
    assert "various;soundtrack" in doc["tags"]
    assert "artist;pulpfiction" in doc["tags"]
    assert "year;1994" in doc["tags"]


def test_va_curated_djkicks_uses_dj_name(tmp_path: Path) -> None:
    album = tmp_path / "VA - DJ-Kicks- DJ Cam"
    album.mkdir()
    syn = tmp_path / "syn"
    syn.mkdir()
    (syn / "musicbrainz.json").write_text(
        json.dumps({"map": {}, "dropped": []}), encoding="utf-8"
    )
    _write_provider(
        album,
        "musicbrainz",
        artist="DJ Cam",
        album_name="DJ-Kicks: DJ Cam",
        year="1997",
    )
    doc = mc.combine_from_providers(
        album, synonyms_dir=syn, providers=["musicbrainz"]
    )
    assert "various;curated" in doc["tags"]
    assert "artist;djcam" in doc["tags"]
    assert "artist;variousartists" not in doc["tags"]


def test_va_curated_verve_and_default_collection(tmp_path: Path) -> None:
    syn = tmp_path / "syn"
    syn.mkdir()
    (syn / "musicbrainz.json").write_text(
        json.dumps({"map": {}, "dropped": []}), encoding="utf-8"
    )
    remixed = tmp_path / "VA - Verve Remixed²"
    remixed.mkdir()
    _write_provider(
        remixed,
        "musicbrainz",
        artist="Various Artists",
        album_name="Verve//Remixed²",
        year="2003",
    )
    rdoc = mc.combine_from_providers(
        remixed, synonyms_dir=syn, providers=["musicbrainz"]
    )
    assert "various;curated" in rdoc["tags"]
    assert "artist;ververemixed" in rdoc["tags"]
    assert "artist;variousartists" not in rdoc["tags"]

    hits = tmp_path / "VA - Cream Anthems"
    hits.mkdir()
    _write_provider(
        hits, "musicbrainz", artist="Various Artists", album_name="Cream Anthems"
    )
    cdoc = mc.combine_from_providers(
        hits, synonyms_dir=syn, providers=["musicbrainz"]
    )
    assert "various;collection" in cdoc["tags"]
    assert "artist;creamanthems" in cdoc["tags"]


def test_hotel_costes_series_without_va_prefix(tmp_path: Path) -> None:
    album = tmp_path / "Hotel Costes - Hotel Costes 5"
    album.mkdir()
    syn = tmp_path / "syn"
    syn.mkdir()
    (syn / "musicbrainz.json").write_text(
        json.dumps({"map": {}, "dropped": []}), encoding="utf-8"
    )
    _write_provider(
        album,
        "musicbrainz",
        artist="Stéphane Pompougnac",
        album_name="Hôtel Costes 5",
        year="2004",
    )
    doc = mc.combine_from_providers(
        album, synonyms_dir=syn, providers=["musicbrainz"]
    )
    assert "various;curated" in doc["tags"]
    assert "artist;hotelcostes" in doc["tags"]
    assert "artist;stphanepompougnac" not in doc["tags"]


def test_single_artist_verve_jazz_masters_is_not_various(tmp_path: Path) -> None:
    album = tmp_path / "George Shearing - Verve Jazz Masters 57"
    album.mkdir()
    syn = tmp_path / "syn"
    syn.mkdir()
    (syn / "musicbrainz.json").write_text(
        json.dumps({"map": {}, "dropped": []}), encoding="utf-8"
    )
    _write_provider(
        album,
        "musicbrainz",
        artist="George Shearing",
        album_name="Verve Jazz Masters 57",
        year="1996",
    )
    doc = mc.combine_from_providers(
        album, synonyms_dir=syn, providers=["musicbrainz"]
    )
    assert "various;curated" not in doc["tags"]
    assert "artist;georgeshearing" in doc["tags"]
    assert "artist;vervejazzmasters" not in doc["tags"]


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

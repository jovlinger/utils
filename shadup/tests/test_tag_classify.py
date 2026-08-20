"""Unit tests for tag_classify (years, artist slugs, various policy)."""

from __future__ import annotations

import sys
from pathlib import Path

SHADUP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SHADUP))

import tag_classify as tc  # noqa: E402


def test_year_value_decades_and_apostrophe() -> None:
    assert tc.year_value("00s") == "00s"
    assert tc.year_value("90's") == "90s"
    assert tc.year_value("1980s") == "1980s"
    assert tc.year_value("2001") == "2001"
    assert tc.year_value("420") is None
    assert tc.year_value("acid jazz") is None


def test_canonicalize_genre_year_and_spaced_artist() -> None:
    assert tc.canonicalize_tag("genre;00s") == "year;00s"
    assert tc.canonicalize_tag("genre;90's") == "year;90s"
    assert tc.canonicalize_tag("genre;leonard cohen") == "artist;leonardcohen"
    assert tc.canonicalize_tag("genre;leonardchohen") == "artist;leonardcohen"
    assert tc.canonicalize_tag("genre;leonardcohen") == "artist;leonardcohen"
    assert tc.canonicalize_tag("artist;Leonard Cohen") == "artist;leonardcohen"


def test_classify_raw_own_artist_and_year() -> None:
    assert tc.classify_raw("00s") == "year;00s"
    assert tc.classify_raw("leonard cohen") == "artist;leonardcohen"
    assert tc.classify_raw("folk", artist_slugs={"leonardcohen"}) == "genre;folk"
    assert tc.classify_raw("Leonard Cohen", artist_slugs={"leonardcohen"}) == (
        "artist;leonardcohen"
    )


def test_various_kinds() -> None:
    assert tc.classify_various(
        "VA - Pulp Fiction- Music From the Motion Picture"
    ) == ("soundtrack", "pulpfiction")
    assert tc.classify_various("VA - DJ-Kicks- DJ Cam") == ("curated", "djcam")
    assert tc.classify_various("VA - Stereo MC's - DJ-Kicks") == (
        "curated",
        "stereomcs",
    )
    assert tc.classify_various(
        "VA-Nightmares_on_Wax_DJ_Kicks-(K7093CD)-CD-FLAC-2000-CMC"
    ) == ("curated", "nightmaresonwax")
    assert tc.classify_various("VA - Verve Remixed²") == ("curated", "ververemixed")
    assert tc.classify_various("VA - Cream Anthems") == (
        "collection",
        "creamanthems",
    )
    assert tc.classify_various("Hotel Costes - Hotel Costes 5") == (
        "curated",
        "hotelcostes",
    )
    assert tc.classify_various("Cafe Del Mar - Volume 15 Quince") == (
        "curated",
        "cafedelmar",
    )
    assert tc.classify_various("Leonard Cohen - Songs of Leonard Cohen") is None
    assert tc.classify_various("George Shearing - Verve Jazz Masters 57") is None
    assert tc.classify_various("VA - The Collection - Verve Jazz Masters 60") == (
        "curated",
        "vervejazzmasters",
    )


def test_va_rename_target_drops_va_prefix() -> None:
    assert tc.va_rename_target("VA - Pulp Fiction- Music From the Motion Picture") == (
        "Pulp Fiction - Music From the Motion Picture"
    )
    assert tc.va_rename_target("VA - DJ-Kicks- DJ Cam") == "DJ Cam - DJ-Kicks"
    assert tc.va_rename_target("VA - Verve Remixed²") == "Verve Remixed - 2"
    assert tc.va_rename_target("Leonard Cohen - Songs of Leonard Cohen") is None


def test_apply_various_drops_va_artist() -> None:
    tags = tc.apply_various_policy(
        ["artist;variousartists", "album;pulpfictionmusicfromthemotionpicture", "year;1994"],
        "VA - Pulp Fiction- Music From the Motion Picture",
    )
    assert "artist;variousartists" not in tags
    assert "various;soundtrack" in tags
    assert "artist;pulpfiction" in tags

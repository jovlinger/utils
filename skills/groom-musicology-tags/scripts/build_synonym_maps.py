#!/usr/bin/env python3
"""Build per-provider synonym maps from inventory/*.tsv into synonyms/*.json.

Review dropped + map entries after each run; commit curated fixes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INV = ROOT / "inventory"
OUT = ROOT / "synonyms"

YEAR_RE = re.compile(
    r"^(?:(?:19|20)\d{2}s?|[0-9]{2}s)$",
    re.I,
)

COLLECTIONS = {
    "djkicks": "djkicks",
    "dj kicks": "djkicks",
    "dj-kicks": "djkicks",
    "verve jazzclub": "vervejazzclub",
    "verve jazz masters": "vervejazzmasters",
    "cafe del mar": "cafedelmar",
    "café del mar": "cafedelmar",
    "buddah bar": "buddahbar",
    "buddha bar": "buddahbar",
    "5 leyendas": "5leyendas",
}

DROP = {
    "isrc",
    "no isrc",
    "vendu",
    "interesting booklet",
    "hi-res",
    "reissue",
    "bonus track",
    "animated cover art",
    "4x4",
    "fidget",
    "lush",
    "bedroom",
    "miami beach",
    "bulgaria",
    "added/2017/01/02",
}
DROP_PREFIXES = ("private/", "added/")

ARTISTS = {
    "u2": "u2",
    "michael nyman": "michaelnyman",
}

FIELD_ROLES = {
    "discogs": {
        "metadata.genres": "Discogs release.genres (broad) -> almost always genre;*",
        "metadata.tags": "Discogs release.styles (narrow) -> almost always genre;*",
        "metadata.artist": "direct -> artist;slug(value) when emitting typed tags",
        "metadata.album": "direct -> album;slug(value)",
        "metadata.year": "direct -> year;value",
    },
    "musicbrainz": {
        "metadata.genres": "MB genre-list (often empty in this corpus)",
        "metadata.tags": "MB tag-list (crowd) -> mostly genre;*; some noise/artist/year",
        "metadata.artist": "direct -> artist;slug(value)",
        "metadata.album": "direct -> album;slug(value)",
        "metadata.year": "often ISO date; take YYYY -> year;YYYY",
    },
    "lastfm": {
        "metadata.genres": "Top N album tags (mixed genre/year/mood) — classify each",
        "metadata.tags": "Overflow tags after genre_tag_limit (usually empty here)",
        "metadata.artist": "direct -> artist;slug(value)",
        "metadata.album": "direct -> album;slug(value)",
        "metadata.year": "direct -> year;YYYY",
    },
    "johan": {
        "metadata.genres": "Hand labels, already compact -> genre;*",
        "metadata.tags": "Hand labels -> classify",
        "metadata.artist": "often already slugged -> artist;value",
        "metadata.album": "direct -> album;slug(value)",
        "metadata.year": "direct -> year;value",
    },
}

# Exact raw -> canonical overrides (win over heuristics)
OVERRIDES: dict[str, dict[str, str | None]] = {
    "johan": {
        "scandinivia": "collection;scandinavia",
        "malesinger": "genre;malesinger",
        "tribute": "genre;tribute",
    },
    "musicbrainz": {
        "world & country": "genre;worldcountry",
        "trip‐hop": "genre;triphop",  # unicode hyphen
    },
    "lastfm": {
        "female vocalists": "genre;femalevocalists",
        "singer-songwriter": "genre;singersongwriter",
    },
}


def slug(s: str) -> str:
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s or "empty"


def classify(raw: str, *, provider: str) -> str | None:
    ov = OVERRIDES.get(provider, {})
    if raw in ov:
        return ov[raw]
    if raw.lower() in ov:
        return ov[raw.lower()]

    s = raw.strip()
    low = s.lower()
    if low in DROP or any(low.startswith(p) for p in DROP_PREFIXES):
        return None
    if low in ARTISTS:
        return f"artist;{ARTISTS[low]}"
    if low in COLLECTIONS:
        return f"collection;{COLLECTIONS[low]}"
    for k, v in COLLECTIONS.items():
        if k in low:
            return f"collection;{v}"
    compact = low.replace(" ", "")
    if YEAR_RE.match(compact) or re.fullmatch(r"(?:19|20)\d{2}", low):
        return f"year;{slug(low)}"
    return f"genre;{slug(s)}"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for tsv in sorted(INV.glob("*.tsv")):
        prov = tsv.stem
        mapping: dict[str, str] = {}
        dropped: list[dict] = []
        for line in tsv.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            count_s, key = line.split("\t", 1)
            field, _, raw = key.partition(":")
            canon = classify(raw, provider=prov)
            if canon is None:
                dropped.append(
                    {"raw": raw, "field": field, "count": int(count_s)}
                )
            else:
                mapping[raw] = canon
        doc = {
            "provider": prov,
            "separator": ";",
            "types": ["artist", "album", "year", "genre", "collection"],
            "value_slug": "lowercase alphanumeric only (strip spaces/punct)",
            "field_roles": FIELD_ROLES.get(prov, {}),
            "map": dict(sorted(mapping.items(), key=lambda kv: kv[0].lower())),
            "dropped": sorted(
                dropped, key=lambda d: (-d["count"], d["raw"].lower())
            ),
        }
        (OUT / f"{prov}.json").write_text(
            json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"{prov}: mapped={len(mapping)} dropped={len(dropped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

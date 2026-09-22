#!/usr/bin/env python3
"""Build per-provider synonym maps from inventory/*.tsv into synonyms/*.json.

Review dropped + map entries after each run; commit curated fixes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INV = ROOT / "inventory"
OUT = ROOT / "synonyms"
SHADUP = ROOT.parents[1] / "shadup"
if str(SHADUP) not in sys.path:
    sys.path.insert(0, str(SHADUP))

import tag_classify as tc  # noqa: E402

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
        "metadata.genres": "Top N album tags (mixed genre/year/mood/artist) — classify each",
        "metadata.tags": "Overflow tags after genre_tag_limit (usually empty here)",
        "metadata.artist": "direct -> artist;slug(value)",
        "metadata.album": "direct -> album;slug(value)",
        "metadata.year": "direct -> year;YYYY",
    },
    "johan": {
        "metadata.genres": "UNUSED at combine time (johan sidecars skipped)",
        "metadata.tags": "UNUSED at combine time (johan sidecars skipped)",
        "metadata.artist": "UNUSED at combine time",
        "metadata.album": "UNUSED at combine time",
        "metadata.year": "UNUSED at combine time",
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


def classify(raw: str, *, provider: str) -> str | None:
    ov = OVERRIDES.get(provider, {})
    if raw in ov:
        return ov[raw]
    if raw.lower() in ov:
        return ov[raw.lower()]
    mapped = tc.classify_raw(raw)
    if mapped is None:
        return None
    return tc.canonicalize_tag(mapped)


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
            "types": list(tc.CANON_TYPES),
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

#!/usr/bin/env python3
"""Build ``.meta.combined.json`` from provider sidecars + synonym maps.

Canonical tags are VFAT-safe ``type;value`` strings (artist, album, year, genre,
collection). Freeform provider tags/genres go through
``skills/groom-musicology-tags/synonyms/<provider>.json``; artist/album/year
fields are emitted directly as typed tags.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

COMBINED_NAME = ".meta.combined.json"
COMBINED_SCHEMA = 1
PROVIDER_SIDE_RE = re.compile(r"^\.meta\.([A-Za-z0-9_-]+)\.json$")
VFAT_BAD = re.compile(r'[:|<>"/\\?*\x00-\x1f]')

YEAR_RE = re.compile(r"^(?:(?:19|20)\d{2}s?|[0-9]{2}s)$", re.I)

UTILS_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SYNONYMS_DIR = UTILS_ROOT / "skills" / "groom-musicology-tags" / "synonyms"

SCAN_PROVIDERS = ("musicbrainz", "discogs", "lastfm")
# Included in combine when the sidecar exists (hand-edited; not musicscan).
EXTRA_COMBINE_PROVIDERS = ("johan",)


def slug(s: str) -> str:
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s or "empty"


def is_vfat_safe(tag: str) -> bool:
    return bool(tag) and ";" in tag and not VFAT_BAD.search(tag)


def synonyms_path(provider: str, synonyms_dir: Path = DEFAULT_SYNONYMS_DIR) -> Path:
    return synonyms_dir / f"{provider}.json"


def load_synonym_doc(
    provider: str, synonyms_dir: Path = DEFAULT_SYNONYMS_DIR
) -> dict[str, Any]:
    path = synonyms_path(provider, synonyms_dir)
    if not path.is_file():
        return {"map": {}, "dropped": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _dropped_raws(doc: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for item in doc.get("dropped") or []:
        if isinstance(item, dict) and isinstance(item.get("raw"), str):
            out.add(item["raw"])
            out.add(item["raw"].lower())
        elif isinstance(item, str):
            out.add(item)
            out.add(item.lower())
    return out


def map_raw_tag(
    raw: str,
    *,
    provider: str,
    doc: Mapping[str, Any],
) -> Optional[str]:
    """Map one freeform tag/genre string to ``type;value``, or None to skip."""
    s = raw.strip()
    if not s:
        return None
    mapping = doc.get("map") or {}
    if s in mapping:
        return str(mapping[s])
    low = s.lower()
    if low in mapping:
        return str(mapping[low])
    dropped = _dropped_raws(doc)
    if s in dropped or low in dropped:
        return None
    # Fallback heuristics (same spirit as build_synonym_maps.classify).
    compact = low.replace(" ", "")
    if YEAR_RE.match(compact) or re.fullmatch(r"(?:19|20)\d{2}", low):
        return f"year;{slug(low)}"
    return f"genre;{slug(s)}"


def _year_token(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, int):
        return str(raw)
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    m = re.search(r"(19|20)\d{2}", s)
    return m.group(0) if m else slug(s)


def tags_from_provider_sidecar(
    payload: Mapping[str, Any],
    *,
    provider: str,
    synonyms_dir: Path = DEFAULT_SYNONYMS_DIR,
) -> list[str]:
    """Emit canonical tags from one ``.meta.<provider>.json`` payload."""
    md = payload.get("metadata")
    if not isinstance(md, dict):
        return []
    doc = load_synonym_doc(provider, synonyms_dir)
    out: list[str] = []
    seen: set[str] = set()

    def add(tag: Optional[str]) -> None:
        if not tag or not is_vfat_safe(tag):
            return
        if tag not in seen:
            seen.add(tag)
            out.append(tag)

    for field in ("genres", "tags"):
        vals = md.get(field) or []
        if not isinstance(vals, list):
            continue
        for v in vals:
            if isinstance(v, str):
                add(map_raw_tag(v, provider=provider, doc=doc))

    artist = md.get("artist")
    if isinstance(artist, str) and artist.strip():
        add(f"artist;{slug(artist)}")
    album = md.get("album")
    if isinstance(album, str) and album.strip():
        add(f"album;{slug(album)}")
    year = _year_token(md.get("year"))
    if year:
        add(f"year;{slug(year)}" if not year.isdigit() else f"year;{year}")

    return out


def list_provider_sidecars(album_dir: Path) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    try:
        children = list(album_dir.iterdir())
    except OSError:
        return []
    for child in children:
        if not child.is_file():
            continue
        match = PROVIDER_SIDE_RE.match(child.name)
        if match is None:
            continue
        name = match.group(1)
        if name == "combined":
            continue
        found.append((name, child))
    found.sort(key=lambda item: item[0])
    return found


def empty_provider_sidecar(album_dir: Path, provider: str) -> dict[str, Any]:
    return {
        "schema": 1,
        "directory": str(album_dir),
        "local": {
            "artist_guess": None,
            "album_guess": None,
            "year_guess": None,
            "tracks": [],
        },
        "metadata": {
            "provider": provider,
            "matched": False,
            "artist": None,
            "album": None,
            "release_id": None,
            "year": None,
            "country": None,
            "genres": [],
            "tags": [],
            "tracks": [],
            "score": None,
        },
    }


def ensure_empty_sidecars(
    album_dir: Path,
    providers: Sequence[str],
    *,
    dry_run: bool = False,
) -> list[Path]:
    """Write empty ``.meta.<provider>.json`` when missing (non-error empty)."""
    written: list[Path] = []
    for provider in providers:
        path = album_dir / f".meta.{provider}.json"
        if path.is_file():
            continue
        written.append(path)
        if dry_run:
            continue
        path.write_text(
            json.dumps(empty_provider_sidecar(album_dir, provider), indent=2) + "\n",
            encoding="utf-8",
        )
    return written


def combine_from_providers(
    album_dir: Path,
    *,
    synonyms_dir: Path = DEFAULT_SYNONYMS_DIR,
    providers: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Union canonical tags from provider sidecars present in *album_dir*."""
    wanted = set(providers) if providers is not None else None
    tags: list[str] = []
    seen: set[str] = set()
    used: list[str] = []
    for name, path in list_provider_sidecars(album_dir):
        # Always merge johan when present; otherwise respect *providers* filter.
        if wanted is not None and name not in wanted and name != "johan":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        used.append(name)
        for tag in tags_from_provider_sidecar(
            payload, provider=name, synonyms_dir=synonyms_dir
        ):
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
    tags.sort()
    return {
        "schema": COMBINED_SCHEMA,
        "directory": str(album_dir.resolve()),
        "kind": "providers",
        "providers": used,
        "tags": tags,
    }


def combine_union_children(
    album_dir: Path,
    child_dirs: Sequence[Path],
    *,
    base_tags: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """Union tags from children's ``.meta.combined.json`` (plus optional base)."""
    seen: set[str] = set()
    tags: list[str] = []
    children_used: list[str] = []

    def add(tag: str) -> None:
        if is_vfat_safe(tag) and tag not in seen:
            seen.add(tag)
            tags.append(tag)

    for tag in base_tags or []:
        add(tag)
    for child in child_dirs:
        path = child / COMBINED_NAME
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        children_used.append(str(child))
        for tag in payload.get("tags") or []:
            if isinstance(tag, str):
                add(tag)
    tags.sort()
    return {
        "schema": COMBINED_SCHEMA,
        "directory": str(album_dir.resolve()),
        "kind": "union-children" if not base_tags else "providers+union-children",
        "children": children_used,
        "tags": tags,
    }


def write_combined(album_dir: Path, doc: Mapping[str, Any]) -> Path:
    path = album_dir / COMBINED_NAME
    path.write_text(json.dumps(dict(doc), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def read_combined_tags(album_dir: Path) -> list[str]:
    path = album_dir / COMBINED_NAME
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return []
    tags = payload.get("tags") or []
    if not isinstance(tags, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        if isinstance(tag, str) and is_vfat_safe(tag) and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def audio_mtime(album_dir: Path, audio_exts: set[str]) -> float:
    newest = 0.0
    try:
        for child in album_dir.iterdir():
            if not child.is_file():
                continue
            if child.suffix.lower() not in audio_exts:
                continue
            try:
                newest = max(newest, child.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        return 0.0
    return newest


def provider_sidecars_mtime(album_dir: Path) -> float:
    newest = 0.0
    for _name, path in list_provider_sidecars(album_dir):
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest


def combined_is_stale(
    album_dir: Path,
    *,
    audio_exts: set[str],
    child_dirs: Sequence[Path] = (),
) -> bool:
    """True when combined is missing or older than inputs."""
    combined = album_dir / COMBINED_NAME
    if not combined.is_file():
        return True
    try:
        combined_m = combined.stat().st_mtime
    except OSError:
        return True
    inputs = [
        audio_mtime(album_dir, audio_exts),
        provider_sidecars_mtime(album_dir),
    ]
    for child in child_dirs:
        child_combined = child / COMBINED_NAME
        if child_combined.is_file():
            try:
                inputs.append(child_combined.stat().st_mtime)
            except OSError:
                pass
        else:
            # Child should contribute but has no combined yet.
            return True
    return any(m > combined_m for m in inputs if m > 0)

"""Canonical musicology tag classification (VFAT-safe ``type;value``).

Shared by ``meta_combine`` (runtime) and ``groom-musicology-tags`` map building.
Johan sidecars are ignored at combine time; this module still classifies raw
strings from online providers.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

UTILS_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VARIOUS_CONFIG = (
    UTILS_ROOT / "skills" / "groom-musicology-tags" / "various-series.json"
)

CANON_TYPES = (
    "artist",
    "album",
    "year",
    "genre",
    "collection",
    "various",
)

# Raw (lowercased) or already-slugged aliases → canonical artist slug.
ARTIST_ALIASES: dict[str, str] = {
    "u2": "u2",
    "michael nyman": "michaelnyman",
    "michaelnyman": "michaelnyman",
    "leonard cohen": "leonardcohen",
    "leonardcohen": "leonardcohen",
    "leonardchohen": "leonardcohen",
    "billy idol": "billyidol",
    "depeche mode": "depechemode",
    "dire straits": "direstraits",
    "duran duran": "duranduran",
    "gipsy kings": "gipsykings",
    "johnny cash": "johnnycash",
    "led zeppelin": "ledzeppelin",
    "louis armstrong": "louisarmstrong",
    "manu chao": "manuchao",
    "mary j blige": "maryjblige",
    "mitch hedberg": "mitchhedberg",
    "monty python": "montypython",
    "neil young": "neilyoung",
    "tom waits": "tomwaits",
    "duke ellington": "dukeellington",
    "ella fitzgerald": "ellafitzgerald",
    "kali uchis": "kaliuchis",
    "rick james": "rickjames",
    "the rolling stones": "therollingstones",
    "rolling stones": "therollingstones",
}

# Compact decade / year tokens after stripping punct (``90's`` → ``90s``).
_YEAR_COMPACT = re.compile(r"^(?:(?:19|20)\d{2}s?|\d{2}s)$", re.I)
_VA_DIR_RE = re.compile(
    r"^(?:VA|Various(?:\s+Artists)?)\s*[-–—:]\s*",
    re.I,
)
_VA_DIR_START_RE = re.compile(r"^(?:VA|Various(?:\s+Artists)?)\b", re.I)

DEFAULT_VA_ARTIST_SLUGS = frozenset(
    {"va", "various", "variousartist", "variousartists"}
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

_various_cfg_cache: dict[tuple[str, int], dict[str, Any]] = {}


def slug(s: str) -> str:
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s or "empty"


def year_value(raw: str) -> Optional[str]:
    """Return canonical year/decade token, or None if *raw* is not a year tag."""
    compact = re.sub(r"[^a-z0-9]+", "", raw.strip().lower())
    if compact and _YEAR_COMPACT.fullmatch(compact):
        return compact
    return None


def artist_canonical(raw: str) -> Optional[str]:
    """If *raw* is a known artist (incl. spaced/typo variants), return slug."""
    s = raw.strip()
    if not s:
        return None
    low = s.lower()
    if low in ARTIST_ALIASES:
        return ARTIST_ALIASES[low]
    compact = slug(s)
    if compact in ARTIST_ALIASES:
        return ARTIST_ALIASES[compact]
    return None


def split_type_value(tag: str) -> Optional[tuple[str, str]]:
    s = tag.strip()
    if not s:
        return None
    for i, ch in enumerate(s):
        if ch in ";:/":
            left, right = s[:i].strip(), s[i + 1 :].strip()
            if left and right:
                return left.lower(), right
            return None
    return None


def canonicalize_tag(
    tag: str,
    *,
    artist_slugs: Optional[set[str]] = None,
) -> Optional[str]:
    """Normalize one ``type;value`` (also accepts ``:`` / ``/``) to slugged form.

    Years (``00s``, ``90's``, ``1980s``, ``2001``) become ``year;*`` even if a
    synonym map previously stored them as ``genre;*``. Artist-name values that
    match *artist_slugs* or :data:`ARTIST_ALIASES` become ``artist;*``.
    """
    split = split_type_value(tag)
    if split is None:
        return None
    typ, raw_val = split
    yv = year_value(raw_val)
    if yv:
        return f"year;{yv}"
    val = slug(raw_val)
    alias = artist_canonical(raw_val) or artist_canonical(val)
    if alias and typ in {"genre", "tag", "artist"}:
        return f"artist;{alias}"
    if artist_slugs and val in artist_slugs and typ in {"genre", "tag", "artist"}:
        return f"artist;{val}"
    if typ not in CANON_TYPES:
        # Keep unknown types only if they are already a simple token.
        if not re.fullmatch(r"[a-z][a-z0-9]*", typ):
            return None
    return f"{typ};{val}"


def classify_raw(
    raw: str,
    *,
    artist_slugs: Optional[set[str]] = None,
) -> Optional[str]:
    """Map a freeform provider tag/genre string to ``type;value``, or None to drop."""
    s = raw.strip()
    if not s:
        return None
    low = s.lower()
    if low in DROP or any(low.startswith(p) for p in DROP_PREFIXES):
        return None
    yv = year_value(s)
    if yv:
        return f"year;{yv}"
    alias = artist_canonical(s)
    if alias:
        return f"artist;{alias}"
    compact = slug(s)
    if artist_slugs and compact in artist_slugs:
        return f"artist;{compact}"
    if low in COLLECTIONS:
        return f"collection;{COLLECTIONS[low]}"
    for k, v in COLLECTIONS.items():
        if k in low:
            return f"collection;{v}"
    return f"genre;{compact}"


def load_various_config(path: Path = DEFAULT_VARIOUS_CONFIG) -> dict[str, Any]:
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    key = (str(path), mtime_ns)
    cached = _various_cfg_cache.get(key)
    if cached is not None:
        return cached
    if not path.is_file():
        cfg: dict[str, Any] = {
            "va_artist_slugs": list(DEFAULT_VA_ARTIST_SLUGS),
            "soundtrack_title": [],
            "soundtrack_overrides": [],
            "curated": [],
        }
    else:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    _various_cfg_cache[key] = cfg
    return cfg


def va_artist_slugs(cfg: Optional[Mapping[str, Any]] = None) -> set[str]:
    cfg = cfg or load_various_config()
    slugs = cfg.get("va_artist_slugs") or list(DEFAULT_VA_ARTIST_SLUGS)
    return {slug(s) for s in slugs}


def is_va_artist_name(name: str, cfg: Optional[Mapping[str, Any]] = None) -> bool:
    return slug(name) in va_artist_slugs(cfg)


def dir_looks_va(dir_name: str) -> bool:
    return bool(_VA_DIR_START_RE.match(dir_name.strip()))


def strip_va_prefix(name: str) -> str:
    return _VA_DIR_RE.sub("", name.strip()).strip()


def _haystack(dir_name: str, extra: Sequence[str] = ()) -> str:
    parts = [dir_name, strip_va_prefix(dir_name), *extra]
    return " ".join(p for p in parts if p)


def _first_parens(text: str) -> Optional[str]:
    m = re.search(r"\(([^)]+)\)", text)
    if not m:
        return None
    inner = m.group(1).strip()
    return inner or None


def djkicks_artist(text: str) -> str:
    """DJ-Kicks: the DJ/selector name, not the series."""
    s = strip_va_prefix(text).replace("_", " ")
    m = re.search(r"^(.+?)\s+[-–—]\s+dj[-_ ]?kicks\b", s, re.I)
    if m:
        left = strip_va_prefix(m.group(1)).strip()
        if left and not is_va_artist_name(left):
            return slug(left)
    m = re.search(r"^(.+?)\s+dj[-_ ]?kicks\b", s, re.I)
    if m:
        left = strip_va_prefix(m.group(1)).replace("_", " ").strip()
        if left and not is_va_artist_name(left) and slug(left) != "djkicks":
            return slug(left)
    m = re.search(r"dj[-_ ]?kicks\s*[-:]\s*(.+)$", s, re.I)
    if m:
        rest = m.group(1).strip()
        rest = re.sub(r"\s*[-:(].*$", "", rest).strip() or m.group(1).strip()
        if rest and slug(rest) not in {"djkicks", "va", "variousartists"}:
            return slug(rest)
    return "djkicks"


def soundtrack_artist(text: str) -> str:
    s = strip_va_prefix(text)
    s = re.sub(
        r"(?i)\s*[-:(]*\s*(?:complete\s+)?(?:unofficial\s+)?soundtrack.*$",
        "",
        s,
    )
    s = re.sub(r"(?i)\s*[-:(]*\s*\bost\b.*$", "", s)
    s = re.sub(
        r"(?i)\s*[-:]*\s*music from(?: and inspired by)?(?: the)?(?: motion picture)?.*$",
        "",
        s,
    )
    s = re.sub(r"(?i)\s*[-:]*\s*deluxe\s*$", "", s)
    s = s.strip(" -–—:")
    return slug(s) if s else "soundtrack"


def _compiled_title_res(cfg: Mapping[str, Any]) -> list[re.Pattern[str]]:
    out: list[re.Pattern[str]] = []
    for pat in cfg.get("soundtrack_title") or []:
        if isinstance(pat, str) and pat:
            out.append(re.compile(pat, re.I))
    return out


def classify_various(
    dir_name: str,
    *,
    extras: Sequence[str] = (),
    cfg: Optional[Mapping[str, Any]] = None,
) -> Optional[tuple[str, str]]:
    """Return ``(kind, artist_slug)`` when this album is various-artists-like.

    *kind* is ``soundtrack``, ``curated``, or ``collection``. ``None`` if the
    directory is not VA-prefixed and no curated series matches.
    """
    cfg = cfg or load_various_config()
    hay = _haystack(dir_name, extras)
    hay_l = hay.lower()
    remainder = strip_va_prefix(dir_name)
    is_va = dir_looks_va(dir_name)

    for row in cfg.get("curated") or []:
        if not isinstance(row, dict):
            continue
        if row.get("requires_va") and not is_va:
            continue
        pat = row.get("match")
        if not isinstance(pat, str) or not pat:
            continue
        if not re.search(pat, hay, re.I):
            continue
        spec = str(row.get("artist") or "fixed:collection")
        if spec == "djkicks_dj":
            artist = djkicks_artist(dir_name)
        elif spec == "parens":
            inner = _first_parens(hay)
            artist = slug(inner) if inner else slug(remainder)
        elif spec.startswith("fixed:"):
            artist = spec.split(":", 1)[1]
        else:
            artist = slug(spec)
        return "curated", artist

    for ov in cfg.get("soundtrack_overrides") or []:
        if isinstance(ov, str) and ov.lower() in hay_l:
            return "soundtrack", soundtrack_artist(dir_name)

    if any(rx.search(hay) for rx in _compiled_title_res(cfg)):
        return "soundtrack", soundtrack_artist(dir_name)

    if is_va:
        return "collection", slug(remainder) if remainder else "collection"
    return None


def apply_various_policy(
    tags: Sequence[str],
    dir_name: str,
    *,
    extras: Sequence[str] = (),
    cfg: Optional[Mapping[str, Any]] = None,
) -> list[str]:
    """Replace ``artist;va`` / Various Artists with ``various;kind`` + series artist."""
    cfg = cfg or load_various_config()
    va_slugs = va_artist_slugs(cfg)
    album_extras = [
        t.split(";", 1)[1]
        for t in tags
        if t.startswith("album;") and ";" in t
    ]
    all_extras = list(extras) + album_extras
    has_va_artist = any(
        t.startswith("artist;") and t.split(";", 1)[1] in va_slugs for t in tags
    )
    classified = classify_various(dir_name, extras=all_extras, cfg=cfg)
    if classified is None and not has_va_artist:
        return list(tags)

    if classified is None:
        remainder = strip_va_prefix(dir_name)
        kind, artist = "collection", slug(remainder) if remainder else "collection"
    else:
        kind, artist = classified

    seen: set[str] = set()
    out: list[str] = []

    def add(tag: str) -> None:
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)

    for tag in tags:
        if tag.startswith("artist;") and tag.split(";", 1)[1] in va_slugs:
            continue
        add(tag)
    add(f"various;{kind}")
    if artist and artist not in va_slugs:
        add(f"artist;{artist}")
    out.sort()
    return out


SERIES_DISPLAY = {
    "hotelcostes": "Hotel Costes",
    "cafedelmar": "Cafe Del Mar",
    "ververemixed": "Verve Remixed",
    "vervejazzmasters": "Verve Jazz Masters",
    "vervejazzclub": "Verve Jazzclub",
    "saintgermaindesprecafe": "Saint-Germain-Des-Prés Café",
    "supperclub": "Supperclub",
    "gitanesjazz": "Gitanes Jazz",
    "kdsessions": "K&D Sessions",
    "novabossa": "Nova Bossa",
    "buddahbar": "Buddha Bar",
    "djkicks": "DJ-Kicks",
}


def _clean_spaces(s: str) -> str:
    s = s.replace("_", " ").replace(",,", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip(" -–—")


def vfat_segment(s: str) -> str:
    s = s.replace(":", " -")
    s = re.sub(r'[:|<>"/\\?*]', "_", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s or "_empty"


def djkicks_display(text: str) -> str:
    """Human DJ/selector name for a DJ-Kicks dirname (not a slug)."""
    s = _clean_spaces(strip_va_prefix(text))
    m = re.search(r"^(.+?)\s+[-–—]\s+dj[-_ ]?kicks\b", s, re.I)
    if m:
        left = _clean_spaces(strip_va_prefix(m.group(1)))
        if left and not is_va_artist_name(left):
            return left
    m = re.search(r"^(.+?)\s+dj[-_ ]?kicks\b", s, re.I)
    if m:
        left = _clean_spaces(strip_va_prefix(m.group(1)))
        if left and not is_va_artist_name(left) and slug(left) != "djkicks":
            return left
    m = re.search(r"dj[-_ ]?kicks\s*[-:]\s*(.+)$", s, re.I)
    if m:
        rest = _clean_spaces(m.group(1))
        rest = re.sub(r"\s*[-:(].*$", "", rest).strip() or rest
        if rest and slug(rest) not in {"djkicks", "va", "variousartists"}:
            return rest
    return "DJ-Kicks"


def soundtrack_display_parts(dir_name: str) -> tuple[str, str]:
    raw = _clean_spaces(strip_va_prefix(dir_name))
    movie = raw
    movie = re.sub(
        r"(?i)\s*[-:(]*\s*(?:complete\s+)?(?:unofficial\s+)?soundtrack.*$",
        "",
        movie,
    )
    movie = re.sub(r"(?i)\s*[-:(]*\s*\bost\b.*$", "", movie)
    movie = re.sub(
        r"(?i)\s*[-:]*\s*music from(?: and inspired by)?(?: the)?(?: motion picture)?.*$",
        "",
        movie,
    )
    movie = re.sub(r"(?i)\s*[-:]*\s*deluxe\s*$", "", movie)
    movie = movie.strip(" -–—:")
    if movie and raw.lower().startswith(movie.lower()):
        rest = raw[len(movie) :].lstrip(" -–—:")
        rest = rest.strip("()[] ")
        album = rest if rest else raw
    else:
        album = raw
    return (movie or raw, album)


def va_folder_parts(
    dir_name: str,
    *,
    cfg: Optional[Mapping[str, Any]] = None,
) -> Optional[tuple[str, str]]:
    """Return ``(artist, album)`` display names for a VA-prefixed folder.

    Non-VA directories return None (Hotel Costes / Cafe Del Mar already use
    the series as artist).
    """
    if not dir_looks_va(dir_name):
        return None
    cfg = cfg or load_various_config()
    classified = classify_various(dir_name, cfg=cfg)
    remainder = _clean_spaces(strip_va_prefix(dir_name))
    remainder = re.sub(r"(?i)\s*[-_(]+\s*(?:cd|flac|dsf)\b.*$", "", remainder)
    remainder = _clean_spaces(remainder)
    kind, artist_slug = classified or ("collection", slug(remainder))

    if kind == "soundtrack":
        return soundtrack_display_parts(dir_name)

    if kind == "curated" and artist_slug not in SERIES_DISPLAY:
        # DJ-Kicks and Back to Mine: selector name is the artist.
        if re.search(r"dj[-_ ]?kicks", dir_name, re.I):
            return djkicks_display(dir_name), "DJ-Kicks"
        inner = _first_parens(remainder)
        if inner:
            album = re.sub(r"\s*\([^)]*\)\s*", " ", remainder)
            album = _clean_spaces(album) or remainder
            return _clean_spaces(inner), album
        return _clean_spaces(remainder), remainder

    if kind == "curated" and artist_slug in SERIES_DISPLAY:
        series = SERIES_DISPLAY[artist_slug]
        album = remainder
        album = re.sub(re.escape(series), " ", album, flags=re.I)
        album = re.sub(r"(?i)\bk\s*&\s*d sessions\b", " ", album)
        album = re.sub(r"[™®]", "", album)
        album = re.sub(r"(?i)\bpresent(?:s|ed)?\s+", "", album)
        album = re.sub(r"(?i)[-_]?\d*b?\d*khz\b", "", album)
        album = re.sub(r"\s+", " ", album).strip(" -,")
        if artist_slug == "djkicks":
            return djkicks_display(dir_name), "DJ-Kicks"
        superscript = {"²": "2", "³": "3", "¹": "1"}
        if album in superscript:
            album = superscript[album]
        if not album or slug(album) in {"the", "empty"}:
            album = remainder
            album = re.sub(r"[™®]", "", album)
            album = _clean_spaces(album)
        if slug(series) in slug(album) or slug(album) in slug(series):
            album = series
        return series, album

    if " - " in remainder:
        left, right = remainder.split(" - ", 1)
        return _clean_spaces(left), _clean_spaces(right)
    return remainder, remainder


def va_rename_target(dir_name: str) -> Optional[str]:
    """New ``Artist - Album`` basename, or None if this dir should keep its name."""
    parts = va_folder_parts(dir_name)
    if parts is None:
        return None
    artist, album = parts
    artist = vfat_segment(artist)
    album = vfat_segment(album)
    if artist.lower() == album.lower():
        return artist
    return f"{artist} - {album}"

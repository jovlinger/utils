"""Rename ingested album dirs from embedded-tag / cue consensus.

Used by ``ingest`` after hash copy. Target form: ``Artist - Album`` (+ ``CD1`` /
``DUP`` extras only). Year stays out of the folder name. Rename via ``shadup mv``.
"""

from __future__ import annotations

import re
import struct
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping, Optional, Sequence, Tuple

AUDIO_EXTS = frozenset(
    {
        ".mp3",
        ".flac",
        ".m4a",
        ".mp4",
        ".aac",
        ".ogg",
        ".oga",
        ".opus",
        ".wav",
        ".aiff",
        ".aif",
        ".wv",
        ".ape",
        ".dsf",
        ".dff",
    }
)

_VA_ARTISTS = frozenset(
    {
        "va",
        "v.a.",
        "v.a",
        "various",
        "various artists",
        "various artist",
        "variousartists",
    }
)

_LEADING_THE_RE = re.compile(r"^The\s+", re.IGNORECASE)
_TRAILING_COMMA_THE_RE = re.compile(r",\s*The$", re.IGNORECASE)
_ILLEGAL_SEGMENT_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_CUE_PERFORMER_RE = re.compile(
    r'^\s*PERFORMER\s+"(?P<val>.*)"\s*$', re.IGNORECASE | re.MULTILINE
)
_CUE_TITLE_RE = re.compile(
    r'^\s*TITLE\s+"(?P<val>.*)"\s*$', re.IGNORECASE | re.MULTILINE
)
_TRACK_HEADER_RE = re.compile(r"^\s*TRACK\s+\d+", re.IGNORECASE | re.MULTILINE)

# Require this fraction of tagged audio files to share the winning pair.
CONSENSUS_RATIO = 2.0 / 3.0


def strip_dirname_artist_the(artist: str) -> str:
    """Drop leading ``The`` / trailing ``, The`` for album folder artists."""
    s = artist.strip()
    s = _TRAILING_COMMA_THE_RE.sub("", s).strip()
    s = _LEADING_THE_RE.sub("", s).strip()
    return s


def sanitize_path_segment(part: str) -> str:
    """VFAT/Samba-safe single path segment (spaces, not underscores)."""
    s = part.replace(":", " - ")
    s = _ILLEGAL_SEGMENT_RE.sub(" ", s)
    s = s.replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s if s else "empty"


def is_various_artist(artist: str) -> bool:
    return artist.strip().lower() in _VA_ARTISTS


def format_album_dirname(artist: str, album: str) -> str:
    """Build ``Artist - Album`` with The-strip and path sanitize."""
    artist_part = sanitize_path_segment(strip_dirname_artist_the(artist))
    album_part = sanitize_path_segment(album)
    if is_various_artist(artist_part):
        raise ValueError(f"refusing VA folder artist: {artist!r}")
    if not artist_part or not album_part or artist_part == "empty" or album_part == "empty":
        raise ValueError(f"empty artist/album after sanitize: {artist!r} / {album!r}")
    return f"{artist_part} - {album_part}"


def iter_audio_files(album_dir: Path) -> list[Path]:
    out: list[Path] = []
    for path in sorted(album_dir.rglob("*")):
        if not path.is_file() and not path.is_symlink():
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() not in AUDIO_EXTS:
            continue
        # Skip AppleDouble sidecars even if somehow audio-suffixed.
        if path.name.startswith("._"):
            continue
        out.append(path)
    return out


def _decode_vorbis_comments(payload: bytes) -> dict[str, str]:
    if len(payload) < 8:
        return {}
    vendor_len = struct.unpack_from("<I", payload, 0)[0]
    offset = 4 + vendor_len
    if offset + 4 > len(payload):
        return {}
    n_comments = struct.unpack_from("<I", payload, offset)[0]
    offset += 4
    tags: dict[str, str] = {}
    for _ in range(n_comments):
        if offset + 4 > len(payload):
            break
        length = struct.unpack_from("<I", payload, offset)[0]
        offset += 4
        if offset + length > len(payload):
            break
        raw = payload[offset : offset + length]
        offset += length
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        key_u = key.strip().upper()
        value = value.strip()
        if key_u and value and key_u not in tags:
            tags[key_u] = value
    return tags


def read_flac_tags(path: Path) -> dict[str, str]:
    """Parse Vorbis comments from a FLAC file (no mutagen required)."""
    try:
        with path.open("rb") as handle:
            if handle.read(4) != b"fLaC":
                return {}
            while True:
                header = handle.read(4)
                if len(header) < 4:
                    return {}
                is_last = bool(header[0] & 0x80)
                block_type = header[0] & 0x7F
                length = int.from_bytes(header[1:4], "big")
                data = handle.read(length)
                if len(data) < length:
                    return {}
                if block_type == 4:
                    return _decode_vorbis_comments(data)
                if is_last:
                    return {}
    except OSError:
        return {}


def read_mutagen_tags(path: Path) -> dict[str, str]:
    """Optional mutagen fallback for non-FLAC audio."""
    try:
        import mutagen  # type: ignore
    except ImportError:
        return {}
    try:
        mf = mutagen.File(str(path))
    except Exception:
        return {}
    if mf is None:
        return {}
    tags: dict[str, str] = {}

    def take(key: str, *names: str) -> None:
        if key in tags:
            return
        for name in names:
            try:
                val = mf[name]  # type: ignore[index]
            except Exception:
                continue
            if val is None:
                continue
            if isinstance(val, list):
                if not val:
                    continue
                text = str(val[0]).strip()
            else:
                text = str(val).strip()
            if text:
                tags[key] = text
                return

    take("ALBUMARTIST", "albumartist", "ALBUMARTIST")
    take("ARTIST", "artist", "ARTIST")
    take("ALBUM", "album", "ALBUM")
    # ID3
    id3 = getattr(mf, "tags", None)
    if id3 is not None:
        take("ALBUMARTIST", "TPE2")
        take("ARTIST", "TPE1")
        take("ALBUM", "TALB")
    return tags


def read_track_artist_album(path: Path) -> Optional[Tuple[str, str]]:
    """Return ``(albumartist|artist, album)`` for one audio file, or None."""
    tags: dict[str, str]
    if path.suffix.lower() == ".flac":
        tags = read_flac_tags(path)
        if not tags:
            tags = read_mutagen_tags(path)
    else:
        tags = read_mutagen_tags(path)
    artist = tags.get("ALBUMARTIST") or tags.get("ARTIST")
    album = tags.get("ALBUM")
    if not artist or not album:
        return None
    return artist.strip(), album.strip()


def _album_level_cue_text(text: str) -> str:
    match = _TRACK_HEADER_RE.search(text)
    if match:
        return text[: match.start()]
    return text


def read_cue_artist_album(album_dir: Path) -> Optional[Tuple[str, str]]:
    """Album-level PERFORMER/TITLE from the first ``*.cue`` under album_dir."""
    cues = sorted(album_dir.rglob("*.cue")) + sorted(album_dir.rglob("*.CUE"))
    for cue in cues:
        if cue.name.startswith("._"):
            continue
        try:
            text = cue.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        header = _album_level_cue_text(text)
        performer = _CUE_PERFORMER_RE.search(header)
        title = _CUE_TITLE_RE.search(header)
        if performer and title:
            artist = performer.group("val").strip()
            album = title.group("val").strip()
            if artist and album:
                return artist, album
    return None


def consensus_artist_album(
    pairs: Sequence[Tuple[str, str]],
    *,
    cue: Optional[Tuple[str, str]] = None,
    ratio: float = CONSENSUS_RATIO,
) -> Optional[Tuple[str, str]]:
    """Pick a winning ``(artist, album)`` when tagged tracks mostly agree."""
    cleaned: list[Tuple[str, str]] = []
    for artist, album in pairs:
        a = artist.strip()
        b = album.strip()
        if a and b and not is_various_artist(a):
            cleaned.append((a, b))
    if cleaned:
        counts = Counter(cleaned)
        winner, n_win = counts.most_common(1)[0]
        if n_win / len(cleaned) + 1e-12 >= ratio:
            return winner
        return None
    if cue is not None:
        a, b = cue[0].strip(), cue[1].strip()
        if a and b and not is_various_artist(a):
            return a, b
    return None


def propose_album_dirname(album_dir: Path) -> Optional[str]:
    """Return target ``Artist - Album`` basename, or None if no consensus."""
    pairs: list[Tuple[str, str]] = []
    for path in iter_audio_files(album_dir):
        pair = read_track_artist_album(path)
        if pair is not None:
            pairs.append(pair)
    cue = read_cue_artist_album(album_dir)
    agreed = consensus_artist_album(pairs, cue=cue)
    if agreed is None:
        return None
    try:
        return format_album_dirname(agreed[0], agreed[1])
    except ValueError:
        return None


def unique_dirname(files_dir: Path, desired: str) -> str:
    """Avoid clobbering an existing album dir with ``DUP`` suffixes."""
    if not (files_dir / desired).exists():
        return desired
    candidate = f"{desired} DUP"
    while (files_dir / candidate).exists():
        candidate = f"{candidate} DUP"
    return candidate


def shadup_mv(
    *,
    store_root: Path,
    db_path: Path,
    shadup_py: Path,
    old_rel: str,
    new_rel: str,
    python: str | None = None,
) -> None:
    cmd = [
        python or sys.executable,
        str(shadup_py),
        "--shadir",
        str(store_root),
        "--db",
        str(db_path),
        "mv",
        old_rel,
        new_rel,
    ]
    subprocess.run(cmd, check=True)


def maybe_rename_ingested_album(
    *,
    album_dir: Path,
    files_dir: Path,
    store_root: Path,
    db_path: Path,
    shadup_py: Path,
) -> Optional[Path]:
    """If tags/cue agree, ``shadup mv`` album_dir to ``Artist - Album``.

    Returns the final album path (possibly unchanged).
    """
    if not album_dir.is_dir():
        return album_dir
    try:
        rel_old = str(album_dir.resolve().relative_to(files_dir.resolve()))
    except ValueError:
        print(
            f"ingest rename: skip {album_dir} (not under {files_dir})",
            file=sys.stderr,
        )
        return album_dir
    if "/" in rel_old:
        # Nested disc folders: only rename top-level ingest destinations.
        print(
            f"ingest rename: skip nested path {rel_old}",
            file=sys.stderr,
        )
        return album_dir

    target = propose_album_dirname(album_dir)
    if target is None:
        print(
            f"ingest rename: no tag/cue consensus for {rel_old}; leaving name",
            file=sys.stderr,
        )
        return album_dir
    if target == rel_old:
        return album_dir

    final_name = unique_dirname(files_dir, target)
    if final_name != target:
        print(
            f"ingest rename: {target!r} taken; using {final_name!r}",
            file=sys.stderr,
        )
    print(
        f"ingest rename: {rel_old!r} -> {final_name!r}",
        file=sys.stderr,
    )
    shadup_mv(
        store_root=store_root,
        db_path=db_path,
        shadup_py=shadup_py,
        old_rel=rel_old,
        new_rel=final_name,
    )
    return files_dir / final_name


def write_minimal_flac_with_tags(
    path: Path, tags: Mapping[str, str], payload: bytes = b"\x00" * 16
) -> None:
    """Test helper: tiny FLAC with a Vorbis comment block (STREAMINFO + comment)."""
    # STREAMINFO block (mandatory): 34 bytes of zeros is accepted by our reader;
    # mutagen may not like it, but we only need our parser + shadup byte store.
    streaminfo = b"\x00" * 34
    vendor = b"ingest_rename"
    comment_body = struct.pack("<I", len(vendor)) + vendor
    entries = [f"{k.upper()}={v}".encode("utf-8") for k, v in tags.items()]
    comment_body += struct.pack("<I", len(entries))
    for entry in entries:
        comment_body += struct.pack("<I", len(entry)) + entry

    def block(block_type: int, data: bytes, *, last: bool) -> bytes:
        header0 = block_type | (0x80 if last else 0)
        return bytes([header0]) + len(data).to_bytes(3, "big") + data

    blob = (
        b"fLaC"
        + block(0, streaminfo, last=False)
        + block(4, comment_body, last=True)
        + payload
    )
    path.write_bytes(blob)

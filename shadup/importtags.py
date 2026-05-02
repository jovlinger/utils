"""Import metatool ``export-json`` metadata as shadup tags on one file per album dir."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Final, Sequence

# Audio extensions aligned with musicology ``audio.AUDIO_EXTS`` (tracks only).
AUDIO_EXTS: Final[frozenset[str]] = frozenset(
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

IMAGE_EXTS: Final[frozenset[str]] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".bmp",
        ".tif",
        ".tiff",
    }
)

VIDEO_EXTS: Final[frozenset[str]] = frozenset(
    {
        ".mkv",
        ".avi",
        ".mov",
        ".webm",
        ".m4v",
        ".wmv",
        ".mpg",
        ".mpeg",
    }
)


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def _list_immediate_files(album_dir: str) -> list[str]:
    try:
        names = sorted(os.listdir(album_dir))
    except OSError:
        return []
    out: list[str] = []
    for name in names:
        path = os.path.join(album_dir, name)
        if os.path.isdir(path):
            continue
        if not os.path.isfile(path):
            continue
        out.append(path)
    out.sort(key=lambda p: os.path.basename(p))
    return out


def pick_target_file(album_dir: str) -> str | None:
    """Prefer first non–audio/non-image/non-video file, else first image, else first file."""
    paths = _list_immediate_files(album_dir)
    if not paths:
        return None

    def is_audio(p: str) -> bool:
        return _ext(p) in AUDIO_EXTS

    def is_image(p: str) -> bool:
        return _ext(p) in IMAGE_EXTS

    def is_video(p: str) -> bool:
        return _ext(p) in VIDEO_EXTS

    tier1 = [p for p in paths if not is_audio(p) and not is_image(p) and not is_video(p)]
    if tier1:
        return tier1[0]
    tier2 = [p for p in paths if is_image(p)]
    if tier2:
        return tier2[0]
    return paths[0]


def build_tags_from_export(obj: dict[str, Any]) -> list[str]:
    """Union of ``tag`` and ``genre`` entries plus ``artist:`` / ``album:`` prefixes."""
    out: list[str] = []
    seen: set[str] = set()
    for key in ("tag", "genre"):
        vals = obj.get(key)
        if not isinstance(vals, list):
            continue
        for v in vals:
            if not isinstance(v, str) or not v.strip():
                continue
            s = v.strip()
            if s not in seen:
                seen.add(s)
                out.append(s)
    artist = obj.get("artist")
    if isinstance(artist, str) and artist.strip():
        t = f"artist:{artist.strip()}"
        if t not in seen:
            seen.add(t)
            out.append(t)
    album = obj.get("album")
    if isinstance(album, str) and album.strip():
        t = f"album:{album.strip()}"
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _run_metatool_export_json(
    metatool: str, provider: str, album_dir: str
) -> dict[str, Any]:
    cmd: list[str] = [metatool, f"--provider={provider}", "export-json", album_dir]
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"metatool failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return json.loads(proc.stdout)


def _shadup_argv(shadup_cli: str | None) -> list[str]:
    """Resolve how to invoke shadup: explicit ``--shadup``, ``$SHADUP``, or sibling ``shadup.py``."""
    if shadup_cli:
        return [shadup_cli]
    env = os.environ.get("SHADUP")
    if env:
        return [env]
    sibling = Path(__file__).resolve().parent / "shadup.py"
    if sibling.is_file():
        return [sys.executable, str(sibling)]
    return ["shadup"]


def _shadup_base(shadup_cli: str | None, shadir: str | None) -> list[str]:
    cmd = list(_shadup_argv(shadup_cli))
    if shadir:
        cmd.extend(["--shadir", shadir])
    return cmd


def _existing_tags_for_path(
    shadup_cli: str | None, shadir: str | None, rel_path: str
) -> list[str]:
    cmd = _shadup_base(shadup_cli, shadir) + ["ls", rel_path]
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    tags_acc: list[str] = []
    reader = csv.reader(io.StringIO(proc.stdout))
    for row in reader:
        if len(row) < 3:
            continue
        try:
            parsed: list[str] = json.loads(row[2])
        except json.JSONDecodeError:
            continue
        tags_acc.extend(parsed)
    # De-duplicate while preserving shadup order
    seen: set[str] = set()
    uniq: list[str] = []
    for t in tags_acc:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def _run_shadup(
    shadup_cli: str | None, shadir: str | None, args: Sequence[str], *, cwd: str
) -> None:
    cmd = _shadup_base(shadup_cli, shadir) + list(args)
    proc = subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(
            f"shadup failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )


def _default_metatool() -> str:
    return os.environ.get("METATOOL", "metatool")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Per directory: run metatool export-json, then shadup tag-add on one "
            "chosen file (readme / image / first file)."
        )
    )
    p.add_argument(
        "--reset",
        action="store_true",
        help="Remove existing shadup tags on the target file before adding",
    )
    p.add_argument(
        "--provider",
        default=os.environ.get("IMPORTTAGS_PROVIDER", "ALL"),
        help="metatool --provider (default: ALL or $IMPORTTAGS_PROVIDER)",
    )
    p.add_argument(
        "--metatool",
        default=_default_metatool(),
        help="metatool executable (default: $METATOOL or metatool)",
    )
    p.add_argument(
        "--shadup",
        default=None,
        metavar="CMD",
        help=(
            "shadup executable (default: $SHADUP, else python shadup.py beside "
            "this module, else shadup on PATH)"
        ),
    )
    p.add_argument(
        "--shadir",
        default=os.environ.get("IMPORTTAGS_SHADIR"),
        help="Optional shadup store path (default: discover from cwd or $IMPORTTAGS_SHADIR)",
    )
    p.add_argument(
        "dirs",
        nargs="+",
        metavar="DIR",
        help="Album directories to process",
    )
    args = p.parse_args(argv)

    cwd = os.getcwd()
    shadir_opt: str | None = args.shadir or None

    for raw in args.dirs:
        album_dir = os.path.abspath(os.path.expanduser(raw))
        if not os.path.isdir(album_dir):
            continue
        try:
            payload = _run_metatool_export_json(args.metatool, args.provider, album_dir)
        except json.JSONDecodeError as e:
            raise SystemExit(f"invalid JSON from metatool for {album_dir}: {e}") from e
        tags = build_tags_from_export(payload)
        if not tags:
            continue
        target = pick_target_file(album_dir)
        if not target:
            continue
        try:
            rel = os.path.relpath(target, cwd)
        except ValueError:
            rel = target
        if args.reset:
            current = _existing_tags_for_path(args.shadup, shadir_opt, rel)
            if current:
                _run_shadup(
                    args.shadup,
                    shadir_opt,
                    ["tag-rm", rel, *current],
                    cwd=cwd,
                )
        _run_shadup(
            args.shadup,
            shadir_opt,
            ["tag-add", rel, *tags],
            cwd=cwd,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Import metatool ``export-json`` metadata as shadup tags on one file per album dir."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

# Must match ``META_KEY_SHADIR`` in ``shadup.py`` (store directory path in ``meta``).
_META_SHADIR_KEY = "shadir"

_MOD_DIR = Path(__file__).resolve().parent
_shadup_mod: Any | None = None


def _shadup_helpers() -> Any:
    """Load ``shadup.py`` from this directory for ``find_shadir`` / ``is_under_dir``."""
    global _shadup_mod
    if _shadup_mod is not None:
        return _shadup_mod
    import importlib.util

    path = _MOD_DIR / "shadup.py"
    spec = importlib.util.spec_from_file_location("shadup_importtags", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _shadup_mod = mod
    return mod


class ImportTagsError(Exception):
    """Cannot attach imported tags (no valid stored-file target)."""


def _shadir_from_database(db_path: str) -> str | None:
    """Return configured store path from ``meta`` (same source shadup uses with ``--db``)."""
    try:
        conn = sqlite3.connect(db_path)
    except OSError:
        return None
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (_META_SHADIR_KEY,)
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    return row[0] if row else None


def _walk_album_regular_files(album_dir: str) -> list[str]:
    """All regular-file paths under *album_dir* (recursive); album may be dirs-only at top."""
    out: list[str] = []
    try:
        top = os.path.abspath(album_dir)
    except OSError:
        return []
    for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            path = os.path.join(dirpath, name)
            if os.path.isdir(path):
                continue
            if not os.path.isfile(path):
                continue
            out.append(path)
    out.sort(key=lambda p: os.path.basename(p))
    return out


def _symlink_resolves_under_shadir(path: str, shadir_abs: str) -> bool:
    """True if *path* is a symlink whose target lies inside *shadir_abs* (sha blob tree)."""
    if not os.path.islink(path):
        return False
    resolved = os.path.realpath(path)
    sh = _shadup_helpers()
    return sh.is_under_dir(resolved, shadir_abs)


def pick_target_file(
    album_dir: str,
    shadir: str | None = None,
    *,
    db_path: str | None = None,
) -> str:
    """Pick the earliest stored file under *album_dir* (symlink into the sha tree).

    Walks subdirectories: an album folder may contain only disc subfolders, etc.

    Store resolution matches shadup: explicit *shadir*, else *db_path* reads
    ``meta.shadir``, else :func:`find_shadir` walking upward for ``.shadup`` /
    ``.shadir``.

    Raises :exc:`ImportTagsError` if there are no regular files under the album,
    the sha store cannot be resolved, or none of those files is a symlink into
    the resolved store root.
    """
    paths = _walk_album_regular_files(album_dir)
    if not paths:
        raise ImportTagsError(f"no files under album directory: {album_dir}")

    shadir_abs: str | None = None
    if shadir:
        shadir_abs = os.path.abspath(os.path.expanduser(shadir))
    elif db_path:
        raw = _shadir_from_database(db_path)
        if raw:
            shadir_abs = os.path.abspath(os.path.expanduser(raw))
    if not shadir_abs:
        sh = _shadup_helpers()
        found = sh.find_shadir(album_dir)
        if found:
            shadir_abs = os.path.abspath(found)

    if not shadir_abs or not os.path.isdir(shadir_abs):
        raise ImportTagsError(
            "cannot resolve sha store directory; pass --shadir, or --db "
            "(with shadir in meta), or place .shadup/.shadir above the album"
        )

    stored = [p for p in paths if _symlink_resolves_under_shadir(p, shadir_abs)]
    if not stored:
        raise ImportTagsError(
            f"no symlink into sha store {shadir_abs!r} under {album_dir!r} "
            f"(run shadup store on this tree first)"
        )
    # Link inode mtime (``lstat``); ``getmtime`` follows symlinks to the blob.
    stored.sort(key=lambda p: (os.lstat(p).st_mtime, os.path.basename(p)))
    return stored[0]


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


def _expand_db_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _shadup_base(
    shadup_cli: str | None, shadir: str | None, db: str | None
) -> list[str]:
    cmd = list(_shadup_argv(shadup_cli))
    if shadir:
        cmd.extend(["--shadir", shadir])
    if db:
        cmd.extend(["--db", db])
    return cmd


def _existing_tags_for_path(
    shadup_cli: str | None,
    shadir: str | None,
    db: str | None,
    rel_path: str,
) -> list[str]:
    cmd = _shadup_base(shadup_cli, shadir, db) + ["ls", rel_path]
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
    shadup_cli: str | None,
    shadir: str | None,
    db: str | None,
    args: Sequence[str],
    *,
    cwd: str,
) -> None:
    cmd = _shadup_base(shadup_cli, shadir, db) + list(args)
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
            "Per directory: run metatool export-json, then shadup tag-add on the "
            "earliest stored file (symlink into the sha store). Fails if the album "
            "has no such file. Use --dryrun to print DB effects without writing."
        )
    )
    p.add_argument(
        "--reset",
        action="store_true",
        help="Remove existing shadup tags on the target file before adding",
    )
    p.add_argument(
        "--dryrun",
        action="store_true",
        help="Print tag-rm / tag-add and resulting tags; do not change the database",
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
        help=(
            "Optional store root passed to shadup; overrides meta.shadir when "
            "combined with --db (same as shadup)"
        ),
    )
    p.add_argument(
        "--db",
        default=os.environ.get("IMPORTTAGS_DB"),
        metavar="PATH",
        help=(
            "SQLite DB for shadup; when set without --shadir, symlink checks use "
            "shadir from DB meta ($IMPORTTAGS_DB)"
        ),
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
    db_opt: str | None = args.db or None
    if db_opt:
        db_opt = _expand_db_path(db_opt)

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
        try:
            target = pick_target_file(album_dir, shadir_opt, db_path=db_opt)
        except ImportTagsError as e:
            raise SystemExit(f"importtags: {e}") from e
        try:
            rel = os.path.relpath(target, cwd)
        except ValueError:
            rel = target
        if args.dryrun:
            current = _existing_tags_for_path(args.shadup, shadir_opt, db_opt, rel)
            if args.reset:
                resulting = sorted(set(tags))
            else:
                resulting = sorted(set(current) | set(tags))
            print(f"[dry-run] album={album_dir}", file=sys.stdout)
            print(f"  path={rel}", file=sys.stdout)
            if args.reset:
                print(
                    f"  would tag-rm: {json.dumps(current)}",
                    file=sys.stdout,
                )
            print(
                f"  would tag-add: {json.dumps(tags)}",
                file=sys.stdout,
            )
            print(
                f"  resulting tags (after): {json.dumps(resulting)}",
                file=sys.stdout,
            )
            continue

        if args.reset:
            current = _existing_tags_for_path(args.shadup, shadir_opt, db_opt, rel)
            if current:
                _run_shadup(
                    args.shadup,
                    shadir_opt,
                    db_opt,
                    ["tag-rm", rel, *current],
                    cwd=cwd,
                )
        _run_shadup(
            args.shadup,
            shadir_opt,
            db_opt,
            ["tag-add", rel, *tags],
            cwd=cwd,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

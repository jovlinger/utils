#!/usr/bin/env python3
"""Ingest files/dirs into /mnt/sdb2/music/flac via shadup.py.

Observable contract (matches deprecated/shasrv_old/ingest.sh):
- payloads under data/XX/<sha256>
- browse tree under files/<dest_prefix>/<rel>
- one line per file on stderr: "Doing: files/<dest_prefix>/<rel>"
- source file removed only on successful ingest
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

STORE_ROOT = Path(os.environ.get("SHASRV_STORE_ROOT", "/mnt/sdb2/music/flac"))
DATA_DIR = STORE_ROOT / "data"
FILES_DIR = STORE_ROOT / "files"
DB_PATH = Path(os.environ.get("SHASRV_DB", str(Path.home() / "Music/shasrv/shadup.db")))
SHADUP_PY = Path(__file__).resolve().parent / "shadup.py"


def err(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def version_key(path_value: str) -> list[object]:
    parts = re.split(r"(\d+)", path_value)
    return [int(p) if p.isdigit() else p for p in parts]


def rewrite_symlink_relative(link_path: Path) -> Path:
    if not link_path.is_symlink():
        raise RuntimeError(f"expected symlink after store: {link_path}")
    absolute_target = link_path.resolve()
    link_parent_real = os.path.realpath(str(link_path.parent))
    target_real = os.path.realpath(str(absolute_target))
    relative_target = os.path.relpath(target_real, link_parent_real)
    link_path.unlink()
    os.symlink(relative_target, str(link_path))
    return absolute_target


def store_with_shadup(path_value: Path) -> None:
    cmd = [
        sys.executable,
        str(SHADUP_PY),
        "--store",
        str(path_value),
        "--shadir",
        str(DATA_DIR),
        "--db",
        str(DB_PATH),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)


def prune_empty_dirs(root: Path) -> None:
    for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
        try:
            Path(dirpath).rmdir()
        except OSError:
            pass


def iter_rel_files_sorted(root: Path) -> list[Path]:
    return sorted(
        [p.relative_to(root) for p in root.rglob("*") if p.is_file()],
        key=lambda p: version_key(str(p)),
    )


def ingest_file(src: Path, src_root: Path, dest_prefix: str) -> None:
    rel = src.relative_to(src_root)
    dst = FILES_DIR / dest_prefix / rel if dest_prefix else FILES_DIR / rel
    print(
        f"Doing: files/{dest_prefix + '/' if dest_prefix else ''}{rel}", file=sys.stderr
    )
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(src, dst)
        store_with_shadup(dst)
        payload = rewrite_symlink_relative(dst)
        try:
            payload.chmod(0o644)
        except OSError:
            pass
        src.unlink()
    except Exception as exc:
        err(f"ingest failed for {src}: {exc}")
        try:
            if dst.exists() or dst.is_symlink():
                dst.unlink()
        except OSError:
            pass


def ingest_dir(src_dir: Path) -> None:
    dest_prefix = src_dir.name
    dest_root = FILES_DIR / dest_prefix
    rel_files = iter_rel_files_sorted(src_dir)
    copied_dests: list[Path] = []

    try:
        for rel in rel_files:
            src = src_dir / rel
            dst = dest_root / rel
            print(f"Doing: files/{dest_prefix}/{rel}", file=sys.stderr)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied_dests.append(dst)

        # Delegate walking/storage to shadup.py.
        store_with_shadup(dest_root)

        for dst in copied_dests:
            payload = rewrite_symlink_relative(dst)
            try:
                payload.chmod(0o644)
            except OSError:
                pass

        for rel in rel_files:
            try:
                (src_dir / rel).unlink()
            except OSError:
                pass
        prune_empty_dirs(src_dir)
    except Exception as exc:
        err(f"ingest failed for {src_dir}: {exc}")
        for dst in copied_dests:
            try:
                if dst.exists() or dst.is_symlink():
                    dst.unlink()
            except OSError:
                pass


def walk_arg(arg: str) -> None:
    path = Path(arg).resolve()
    if path.is_file():
        src_root = path.parent
        ingest_file(path, src_root, src_root.name)
        return
    if path.is_dir():
        ingest_dir(path)
        return
    err(f"not found: {arg}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        err(f"usage: {Path(argv[0]).name} <file-or-dir> [...]")
        return 2
    if not DATA_DIR.is_dir() or not FILES_DIR.is_dir():
        err(f"store layout missing under {STORE_ROOT}")
        return 1
    if not SHADUP_PY.is_file():
        err(f"missing shadup.py at {SHADUP_PY}")
        return 1
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for arg in argv[1:]:
        walk_arg(arg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

#!/usr/bin/env python3
"""Ingest files/dirs into /mnt/sdb2/music/flac via shadup.py.

Observable contract (matches deprecated/shasrv_old/ingest.sh):
- payloads under <store-root>/data/XX/<sha256> (``--shadir`` is the store root, not ``data/``)
- browse tree under files/<dest_prefix>/<rel>
- one line per file on stderr: "Doing: files/<dest_prefix>/<rel>"
- source file removed only after sha256(source) matches payload in data/ and files/ link
- release helper extensions (.sfv, .nfo, .url; case-insensitive) skipped by suffix/basename
- AppleDouble/resource-fork sidecars matching ``._*`` skipped by basename glob
- preflight scan ensures source directories are writable for post-ingest removal
"""

from __future__ import annotations

import errno
import fnmatch
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

STORE_ROOT = Path(os.environ.get("SHASRV_STORE_ROOT", "/mnt/sdb2/music/flac"))
DATA_DIR = STORE_ROOT / "data"
FILES_DIR = STORE_ROOT / "files"
DB_PATH = Path(os.environ.get("SHASRV_DB", str(Path.home() / "Music/shasrv/shadup.db")))
SHADUP_PY = Path(__file__).resolve().parent / "shadup.py"
# Skipped by file extension (e.g. release.sfv, release.nfo, folder.url, or basename ".sfv").
INGEST_SKIP_EXTENSIONS = frozenset({".sfv", ".nfo", ".url"})
# Skipped when basename matches glob (``*`` is wildcard; leading ``.`` is literal).
INGEST_SKIP_GLOB_PATTERNS = ("._*",)
# Directory mode applied during preflight when removal would otherwise fail.
SOURCE_DIR_WRITABLE_MODE = stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO


def err(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def _write_probe(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    os.close(fd)
    path.unlink()


def iter_source_dirs(root: Path) -> list[Path]:
    """Directories that must be writable to unlink ingested files under root."""
    if root.is_file():
        return [root.parent]
    return sorted(
        {root, *(path for path in root.rglob("*") if path.is_dir())},
        key=lambda path: version_key(str(path)),
    )


def removal_blocked_dirs(root: Path) -> list[Path]:
    return [path for path in iter_source_dirs(root) if not os.access(path, os.W_OK)]


def _chmod_dirs_writable(dirs: list[Path]) -> list[Path]:
    """Try to chmod blocked dirs; return those still not writable."""
    still_blocked: list[Path] = []
    for path in dirs:
        try:
            os.chmod(path, SOURCE_DIR_WRITABLE_MODE)
        except OSError:
            still_blocked.append(path)
            continue
        if not os.access(path, os.W_OK):
            still_blocked.append(path)
    return still_blocked


def _sudo_chmod_dirs_writable(root: Path) -> None:
    if os.geteuid() == 0:
        for path in removal_blocked_dirs(root):
            os.chmod(path, SOURCE_DIR_WRITABLE_MODE)
        return
    cmd = [
        "sudo",
        "find",
        str(root),
        "-type",
        "d",
        "-exec",
        "chmod",
        "a+rwx",
        "{}",
        "+",
    ]
    subprocess.run(cmd, check=True)


def ensure_source_removable(root: Path) -> None:
    """Preflight: ingest deletes sources only when parent dirs are writable."""
    blocked = removal_blocked_dirs(root)
    if not blocked:
        return
    print(
        f"Preflight: fixing source permissions under {root} "
        f"({len(blocked)} director(y/ies) not writable)",
        file=sys.stderr,
    )
    blocked = _chmod_dirs_writable(blocked)
    if blocked:
        try:
            _sudo_chmod_dirs_writable(root)
        except (OSError, subprocess.CalledProcessError) as exc:
            err(
                f"cannot chmod source tree for removal under {root}: {exc} "
                f"(try: sudo chown -R {os.getenv('USER', 'you')}:{os.getenv('USER', 'you')} {root})"
            )
            raise SystemExit(1) from exc
        blocked = removal_blocked_dirs(root)
    if blocked:
        err(
            "cannot obtain write access to remove sources after ingest: "
            f"{blocked[0]} — fix ownership/permissions under {root}"
        )
        raise SystemExit(1)


def verify_store_ready() -> None:
    """Fail before mutating sources if the store cannot accept writes."""
    probes = (
        ("files", FILES_DIR / ".ingest-write-probe"),
        ("data", DATA_DIR / "00" / ".ingest-write-probe"),
    )
    for area, probe in probes:
        try:
            _write_probe(probe)
        except OSError as exc:
            if exc.errno == errno.EROFS:
                err(
                    f"cannot write to {area}/ ({probe.parent}): filesystem is "
                    f"read-only — use ~/ingest.sh (remounts {STORE_ROOT} rw), "
                    "not ingest.py directly"
                )
            elif exc.errno in (errno.EACCES, errno.EPERM):
                err(
                    f"cannot write to {area}/ ({probe.parent}): permission denied "
                    f"— fix ownership/permissions under {STORE_ROOT}"
                )
            else:
                err(f"cannot write to {area}/ ({probe.parent}): {exc}")
            raise SystemExit(1) from exc


def version_key(path_value: str) -> list[object]:
    parts = re.split(r"(\d+)", path_value)
    return [int(p) if p.isdigit() else p for p in parts]


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def payload_path(digest: str) -> Path:
    return DATA_DIR / digest[:2] / digest


def verify_ingested(src: Path, link: Path) -> None:
    """Raise if source bytes are not stored under data/ and linked from link."""
    if not src.is_file():
        raise RuntimeError(f"source missing or not a file: {src}")
    digest = sha256_file(src)
    payload = payload_path(digest)
    if not payload.is_file():
        raise RuntimeError(
            f"payload missing at {payload} (sha256 {digest}) for source {src}"
        )
    if sha256_file(payload) != digest:
        raise RuntimeError(f"payload digest mismatch at {payload}")
    if not link.is_symlink():
        raise RuntimeError(f"expected symlink at {link}, found {link.stat().st_mode:#o}")
    if link.resolve() != payload.resolve():
        raise RuntimeError(
            f"link {link} -> {link.resolve()} does not point at payload {payload}"
        )


def remove_source_if_verified(src: Path, link: Path) -> None:
    verify_ingested(src, link)
    try:
        src.unlink()
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EPERM):
            parent = src.parent
            raise PermissionError(
                f"cannot remove source {src} (permission denied on {parent}) "
                f"— re-run ingest after fixing ownership/permissions"
            ) from exc
        raise


def already_ingested(src: Path, link: Path) -> bool:
    try:
        verify_ingested(src, link)
    except (OSError, RuntimeError):
        return False
    return True


def file_extension_lower(rel: Path) -> str:
    """Lowercase extension for case-insensitive blacklist matching."""
    if rel.suffix:
        return rel.suffix.lower()
    # Basenames like ".sfv" have no Path.suffix; the whole name is the extension.
    return rel.name.lower()


def has_skipped_extension(rel: Path) -> bool:
    """True when rel should not be ingested (.sfv / .nfo / .url; any case)."""
    ext = file_extension_lower(rel)
    if ext in INGEST_SKIP_EXTENSIONS:
        return True
    return rel.name.lower() in INGEST_SKIP_EXTENSIONS


def has_skipped_basename_glob(rel: Path) -> bool:
    """True when basename matches an ingest skip glob (e.g. AppleDouble ``._*``)."""
    name = rel.name
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in INGEST_SKIP_GLOB_PATTERNS)


def should_skip_ingest(rel: Path) -> bool:
    """True when rel should not be ingested (extensions, globs, etc.)."""
    return has_skipped_extension(rel) or has_skipped_basename_glob(rel)


def iter_skipped_files(root: Path) -> list[Path]:
    return sorted(
        [
            p.relative_to(root)
            for p in root.rglob("*")
            if p.is_file() and should_skip_ingest(p.relative_to(root))
        ],
        key=lambda p: version_key(str(p)),
    )


def skip_ingest_path(src: Path, dst: Path) -> None:
    """Leave source in place; drop any stale copy under files/ from a prior run."""
    print(f"Skipping: {src}", file=sys.stderr)
    try:
        if dst.exists() or dst.is_symlink():
            dst.unlink()
    except OSError:
        pass


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
        "-v",
        "--shadir",
        str(STORE_ROOT),
        "--db",
        str(DB_PATH),
        "store",
        str(path_value),
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
        [
            p.relative_to(root)
            for p in root.rglob("*")
            if p.is_file() and not should_skip_ingest(p.relative_to(root))
        ],
        key=lambda p: version_key(str(p)),
    )


def ingest_file(src: Path, src_root: Path, dest_prefix: str) -> None:
    rel = src.relative_to(src_root)
    dst = FILES_DIR / dest_prefix / rel if dest_prefix else FILES_DIR / rel
    if should_skip_ingest(rel):
        skip_ingest_path(src, dst)
        return
    print(
        f"Doing: files/{dest_prefix + '/' if dest_prefix else ''}{rel}", file=sys.stderr
    )
    dst.parent.mkdir(parents=True, exist_ok=True)
    if already_ingested(src, dst):
        try:
            remove_source_if_verified(src, dst)
        except Exception as exc:
            err(f"ingest failed for {src}: {exc}")
        return
    try:
        shutil.copy2(src, dst)
        store_with_shadup(dst)
        payload = rewrite_symlink_relative(dst)
        try:
            payload.chmod(0o644)
        except OSError:
            pass
        remove_source_if_verified(src, dst)
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
    pending: list[Path] = []

    try:
        for rel in iter_skipped_files(src_dir):
            skip_ingest_path(src_dir / rel, dest_root / rel)

        for rel in rel_files:
            src = src_dir / rel
            dst = dest_root / rel
            print(f"Doing: files/{dest_prefix}/{rel}", file=sys.stderr)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if already_ingested(src, dst):
                remove_source_if_verified(src, dst)
                continue
            shutil.copy2(src, dst)
            copied_dests.append(dst)
            pending.append(rel)

        if not pending:
            prune_empty_dirs(src_dir)
            return

        # Delegate walking/storage to shadup.py.
        store_with_shadup(dest_root)

        for rel in pending:
            dst = dest_root / rel
            payload = rewrite_symlink_relative(dst)
            try:
                payload.chmod(0o644)
            except OSError:
                pass

        for rel in rel_files:
            src = src_dir / rel
            if not src.exists():
                continue
            dst = dest_root / rel
            remove_source_if_verified(src, dst)
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
        ensure_source_removable(path)
        src_root = path.parent
        ingest_file(path, src_root, src_root.name)
        return
    if path.is_dir():
        ensure_source_removable(path)
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
    verify_store_ready()
    for arg in argv[1:]:
        walk_arg(arg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

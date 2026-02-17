"""Deduplicate files by sha256 into a shared store with symlinks."""

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from typing import Callable, Iterator, TypeVar

T = TypeVar("T")

HASH_RE = re.compile(r"^[0-9a-f]{64}$")

DB_NAME = ".shadup.db"
VERBOSITY = 0
OUTPUT_MODE = "pretty"
LSHASH_DELIM = "|"


def out(msg: str, level: int, kind: str = "status", **kwargs: object) -> None:
    """Print when verbosity is high enough."""
    if OUTPUT_MODE == "machine" and kind != "data":
        return
    if VERBOSITY >= level:
        if kwargs:
            msg = msg.format(**kwargs)
        print(msg)


def out_csv(fields: list[str]) -> None:
    """Write a CSV line for machine-readable output."""
    writer = csv.writer(sys.stdout)
    writer.writerow(fields)


def _format_pretty_path(path: str) -> str:
    needs_quote = any(
        ch.isspace() or ord(ch) < 32 or ord(ch) == 127 or ord(ch) > 127 for ch in path
    )
    if needs_quote:
        return json.dumps(path, ensure_ascii=False)
    return path


def _emit_lspath_machine(entries: list[tuple[str, str, bool]]) -> None:
    for path, shasum, deleted in entries:
        out_csv([path, shasum, "1" if deleted else "0"])


def _emit_lspath_pretty(
    entries: list[tuple[str, str, bool]], show_deleted: bool
) -> None:
    formatted = [(_format_pretty_path(path), shasum, deleted) for path, shasum, deleted in entries]
    max_len = max(len(path) for path, _shasum, _deleted in formatted)
    for path, shasum, deleted in formatted:
        if show_deleted:
            out(
                "{path} {deleted} {shasum}",
                0,
                path=path.ljust(max_len),
                deleted="X" if deleted else ".",
                shasum=shasum,
                kind="data",
            )
        else:
            out("{path} {shasum}", 0, path=path.ljust(max_len), shasum=shasum, kind="data")


def _emit_lshash_machine(
    grouped: dict[str, list[tuple[str, bool]]], show_deleted: bool
) -> None:
    for shasum in sorted(grouped):
        paths = []
        for path, deleted in sorted(grouped[shasum]):
            if show_deleted:
                paths.append(f"{path}:{'X' if deleted else '.'}")
            else:
                paths.append(path)
        out_csv([shasum, LSHASH_DELIM.join(paths)])


def _emit_lshash_pretty(
    grouped: dict[str, list[tuple[str, bool]]], show_deleted: bool
) -> None:
    for shasum in sorted(grouped):
        out(shasum, 0, kind="data")
        for path, deleted in sorted(grouped[shasum]):
            path = _format_pretty_path(path)
            if show_deleted:
                out(f"  {path} {'X' if deleted else '.'}", 0, kind="data")
            else:
                out(f"  {path}", 0, kind="data")


def normalize_argv(argv: list[str]) -> list[str]:
    """Move global flags before mode flags.

    >>> normalize_argv(["--ls", "--recursive", "foo"])
    ['--recursive', '--ls', 'foo']
    >>> normalize_argv(["--skip-dotfiles=false", "--extract", "a"])
    ['--skip-dotfiles=false', '--extract', 'a']
    >>> normalize_argv(["--extract", "a", "--show-deleted"])
    ['--show-deleted', '--extract', 'a']
    """
    global_flags = {"--recursive", "--show-deleted", "-v"}
    global_with_value = {"--skip-dotfiles", "--paranoia"}
    extracted: list[str] = []
    remaining: list[str] = []
    idx = 0
    while idx < len(argv):
        arg = argv[idx]
        if arg in global_flags:
            extracted.append(arg)
            idx += 1
            continue
        if arg in global_with_value:
            extracted.append(arg)
            if idx + 1 < len(argv):
                extracted.append(argv[idx + 1])
                idx += 2
            else:
                idx += 1
            continue
        if arg.startswith("--skip-dotfiles=") or arg.startswith("--paranoia="):
            extracted.append(arg)
            idx += 1
            continue
        remaining.append(arg)
        idx += 1
    return extracted + remaining


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for store/extract modes."""

    def parse_bool(value: str) -> bool:
        """Parse a CLI boolean value."""
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
        raise argparse.ArgumentTypeError(f"invalid boolean: {value!r}")

    parser = argparse.ArgumentParser(
        description="Store files by sha256 and replace with symlinks, or extract back."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--store",
        nargs="+",
        metavar="DIR",
        help="Directories to store files from",
    )
    mode.add_argument(
        "--extract",
        nargs="+",
        metavar="DIR",
        help="Prefix paths to extract (relative to cwd used at store time)",
    )
    mode.add_argument(
        "--lspath",
        "--ls",
        nargs="*",
        metavar="PATH",
        dest="lspath",
        help="List stored file paths with sha256 hashes",
    )
    mode.add_argument(
        "--lshash",
        nargs="*",
        metavar="HASH",
        help="List stored file paths grouped by sha256 hashes",
    )
    mode.add_argument(
        "--rmpath",
        nargs="+",
        metavar="PATH",
        dest="rmpath",
        help="Mark stored entries as deleted (same prefixes as extract).",
    )
    mode.add_argument(
        "--rmhash",
        nargs="+",
        metavar="HASH",
        dest="rmhash",
        help="Mark all entries with matching shasums as deleted",
    )
    mode.add_argument(
        "--dedup",
        nargs="+",
        metavar="DIR",
        help="Replace files with existing shadir links without storing",
    )
    mode.add_argument(
        "--fixlinks",
        nargs="+",
        metavar="DIR",
        help="Fix broken symlink targets under directories",
    )
    parser.add_argument(
        "--shadir",
        help="Directory to store files by sha256",
    )
    parser.add_argument(
        "--db",
        help="Path to SQLite database (default: <shadir>/.shadup.db)",
    )
    parser.add_argument(
        "--skip-dotfiles",
        type=parse_bool,
        default=True,
        metavar="BOOL",
        help="Skip files and directories starting with '.' (default: true)",
    )
    parser.add_argument(
        "--mindup",
        type=int,
        default=1,
        metavar="N",
        help="Minimum duplicate count for lspath/lshash filtering (default: 1)",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Recurse into child paths for list/delete operations",
    )
    parser.add_argument(
        "-d",
        "--show-deleted",
        action="store_true",
        help="Include deleted entries in db operations",
    )
    parser.add_argument(
        "--paranoia",
        type=int,
        default=0,
        metavar="N",
        help="With --fixlinks: 0=no extra checks, 1=target exists, 2=1+sha256 verify",
    )
    parser.add_argument(
        "-v",
        action="count",
        default=0,
        help="Increase verbosity (can be repeated)",
    )
    return parser.parse_args(normalize_argv(sys.argv[1:]))


def sha256_file(path: str) -> str:
    """Return the sha256 hex digest for a file path."""
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def is_under_dir(path: str, parent: str) -> bool:
    """Return True if path is within parent directory.

    >>> is_under_dir("/a/b/c", "/a/b")
    True
    >>> is_under_dir("/a/b", "/a/b")
    True
    >>> is_under_dir("/a/b", "/a/b/c")
    False
    """
    try:
        return os.path.commonpath([path, parent]) == parent
    except ValueError:
        return False


def ensure_store_path(shadir: str, digest: str) -> str:
    """Ensure shadir subdirectory exists and return digest path."""
    subdir = os.path.join(shadir, digest[:2])
    os.makedirs(subdir, exist_ok=True)
    return os.path.join(subdir, digest)


def find_shadir(start_dir: str) -> str | None:
    """Search for .shadup or .shadir from start_dir up to home or /."""
    current = os.path.abspath(start_dir)
    home = os.path.abspath(os.path.expanduser("~"))
    stop_at = home if is_under_dir(current, home) else os.path.sep
    while True:
        for name in (".shadup", ".shadir"):
            candidate = os.path.join(current, name)
            if os.path.isdir(candidate):
                return candidate
        if current == stop_at or current == os.path.sep:
            break
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def normalize_hash_arg(shadir: str, value: str) -> str | None:
    """Normalize a hash value or resolve a symlink to a hash file."""
    raw = value.strip()
    if not raw:
        return None
    raw_lower = raw.lower()
    if HASH_RE.match(raw_lower):
        return raw_lower
    resolved_path = raw
    if os.path.islink(raw):
        resolved = os.path.realpath(raw)
        base = os.path.basename(resolved).lower()
        if HASH_RE.match(base) and is_under_dir(resolved, shadir):
            return base
        resolved_path = resolved
    if os.path.isfile(resolved_path):
        try:
            return sha256_file(resolved_path)
        except OSError:
            return None
    return None


def open_db(shadir: str, db_path: str | None = None) -> sqlite3.Connection:
    """Open shadir sqlite db and ensure schema.
    If db_path is given, use it; otherwise use <shadir>/.shadup.db.
    """
    if db_path is None:
        db_path = os.path.join(shadir, DB_NAME)
    else:
        db_path = os.path.abspath(db_path)
    db_dir = os.path.dirname(db_path)
    os.makedirs(db_dir, exist_ok=True)
    os.makedirs(shadir, exist_ok=True)
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    out("db {db_path} size {db_size}", 0, db_path=db_path, db_size=db_size)
    conn = sqlite3.connect(db_path)
    # Two steps ensure a re-stored file is reactivated even if the row existed
    # (INSERT IGNORE doesn't change deleted=1 rows).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stored_files (
            shasum TEXT NOT NULL,
            root TEXT NOT NULL,
            root_rel TEXT NOT NULL,
            dirpath TEXT NOT NULL,
            filename TEXT NOT NULL,
            deleted INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS stored_files_unique_rel
        ON stored_files(shasum, root_rel, dirpath, filename)
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS stored_files_shasum_idx ON stored_files(shasum)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS stored_files_dirpath_idx ON stored_files(dirpath)"
    )
    return conn


def store_digest(path: str, digest: str, shadir: str) -> tuple[str, bool] | None:
    """Move file to shadir, replace it with a symlink, return (path, existed)."""
    if os.path.islink(path) or not os.path.isfile(path):
        return None

    dest = ensure_store_path(shadir, digest)
    existed_already = os.path.exists(dest)

    if os.path.abspath(path) == os.path.abspath(dest):
        # Explicit exception instead of assert to keep the guard under -O.
        raise AssertionError(f"source equals destination: {path}")

    if existed_already:
        os.unlink(path)
    else:
        # shutil.move is an atomic rename on same filesystem and falls back
        # to copy+remove across filesystems.
        shutil.move(path, dest)

    abs_target = os.path.abspath(dest)
    os.symlink(abs_target, path)
    return dest, existed_already


def ensure_directory(path: str) -> None:
    """Ensure directory exists or raise if a file blocks it."""
    if os.path.exists(path) and not os.path.isdir(path):
        raise RuntimeError(f"extract directory is a file: {path}")
    try:
        os.makedirs(path, exist_ok=True)
    except NotADirectoryError as exc:
        raise RuntimeError(f"extract path has non-directory component: {path}") from exc


def _normalize_extract_prefixes(prefixes: list[str]) -> tuple[list[str], list[str]]:
    normalized = []
    abs_prefixes: list[str] = []
    for prefix in prefixes:
        if os.path.isabs(prefix):
            abs_prefixes.append(os.path.abspath(prefix))
            continue
        normalized.append(os.path.normpath(prefix))
        abs_prefixes.append(os.path.abspath(prefix))
    return normalized, abs_prefixes


def _fetch_extract_rows(
    conn: sqlite3.Connection, show_deleted: bool
) -> list[tuple[str, str, str, str, str]]:
    if show_deleted:
        return conn.execute(
            "SELECT shasum, root, root_rel, dirpath, filename FROM stored_files"
        ).fetchall()
    return conn.execute(
        """
        SELECT shasum, root, root_rel, dirpath, filename
        FROM stored_files
        WHERE deleted = 0
        """
    ).fetchall()


def _matches_prefix(target_rel: str, normalized_prefixes: list[str]) -> bool:
    return any(
        target_rel == prefix or target_rel.startswith(prefix + os.sep)
        for prefix in normalized_prefixes
    )


def _prepare_extract_target(dest_path: str, store_path: str) -> bool:
    if os.path.isdir(dest_path):
        raise RuntimeError(f"extract target is a directory: {dest_path}")
    if os.path.exists(dest_path):
        if os.path.islink(dest_path):
            os.unlink(dest_path)
        elif os.path.samefile(dest_path, store_path):
            return False
        elif os.path.isfile(dest_path):
            os.unlink(dest_path)
    return True


def _link_or_copy(store_path: str, dest_path: str, dest_dir: str) -> int:
    store_stat = os.stat(store_path)
    size = store_stat.st_size
    if store_stat.st_dev == os.stat(dest_dir).st_dev:
        try:
            os.link(store_path, dest_path)
            out(
                "hardlink {dest_path} <- {store_path}",
                2,
                dest_path=dest_path,
                store_path=store_path,
            )
        except OSError:
            shutil.copy2(store_path, dest_path)
            out(
                "copy {dest_path} <- {store_path}",
                2,
                dest_path=dest_path,
                store_path=store_path,
            )
    else:
        shutil.copy2(store_path, dest_path)
        out(
            "copy {dest_path} <- {store_path}",
            2,
            dest_path=dest_path,
            store_path=store_path,
        )
    return size


def _restore_orphan_symlink(abs_prefix: str, shadir_real: str) -> int:
    if not os.path.islink(abs_prefix):
        return 0
    resolved = os.path.realpath(abs_prefix)
    if not (is_under_dir(resolved, shadir_real) and os.path.isfile(resolved)):
        return 0
    store_stat = os.stat(resolved)
    size = store_stat.st_size
    os.unlink(abs_prefix)
    if store_stat.st_dev == os.stat(os.path.dirname(abs_prefix)).st_dev:
        try:
            os.link(resolved, abs_prefix)
        except OSError:
            shutil.copy2(resolved, abs_prefix)
    else:
        shutil.copy2(resolved, abs_prefix)
    out(
        "extracted {dest_path} <- {store_path}",
        1,
        dest_path=abs_prefix,
        store_path=resolved,
    )
    return size


def extract_from_db(
    conn: sqlite3.Connection, shadir: str, prefixes: list[str], show_deleted: bool
) -> int:
    """Extract files listed in db that match any path prefix."""
    normalized_prefixes, abs_prefixes = _normalize_extract_prefixes(prefixes)
    shadir_real = os.path.realpath(shadir)
    extracted_bytes = 0
    seen_paths: set[str] = set()
    rows = _fetch_extract_rows(conn, show_deleted)
    for shasum, root, root_rel, dirpath, filename in rows:
        root_path = os.path.abspath(root)
        dest_dir = os.path.join(root_path, dirpath)
        dest_path = os.path.join(dest_dir, filename)
        if dest_path in seen_paths:
            continue
        target_rel = os.path.normpath(os.path.join(root_rel, dirpath, filename))
        if not _matches_prefix(target_rel, normalized_prefixes):
            continue
        store_path = os.path.join(shadir, shasum[:2], shasum)
        if not os.path.isfile(store_path):
            out(
                "skip missing target for {dest_path} -> {store_path}",
                0,
                dest_path=dest_path,
                store_path=store_path,
            )
            continue
        ensure_directory(dest_dir)
        if not _prepare_extract_target(dest_path, store_path):
            seen_paths.add(dest_path)
            continue
        size = _link_or_copy(store_path, dest_path, dest_dir)
        extracted_bytes += size
        seen_paths.add(dest_path)
        out(
            "extracted {dest_path} <- {store_path}",
            1,
            dest_path=dest_path,
            store_path=store_path,
        )
    for abs_prefix in abs_prefixes:
        if abs_prefix in seen_paths:
            continue
        restored = _restore_orphan_symlink(abs_prefix, shadir_real)
        if restored:
            extracted_bytes += restored
            seen_paths.add(abs_prefix)
    return extracted_bytes


def list_db_entries(
    conn: sqlite3.Connection, show_deleted: bool
) -> list[tuple[str, str, bool]]:
    """Return stored (path, shasum, deleted) entries as normalized relative paths."""
    if show_deleted:
        rows = conn.execute(
            "SELECT shasum, root_rel, dirpath, filename, deleted FROM stored_files"
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT shasum, root_rel, dirpath, filename, deleted
            FROM stored_files
            WHERE deleted = 0
            """
        ).fetchall()
    entries: list[tuple[str, str, bool]] = []
    for shasum, root_rel, dirpath, filename, deleted in rows:
        path = os.path.normpath(os.path.join(root_rel, dirpath, filename))
        entries.append((path, shasum, bool(deleted)))
    return entries


def list_children(
    conn: sqlite3.Connection, prefixes: list[str], recursive: bool, show_deleted: bool
) -> list[tuple[str, str, bool]]:
    """Return (path, shasum, deleted) entries under prefixes, optionally recursively."""
    entries = list_db_entries(conn, show_deleted)
    if not prefixes:
        return sorted(set(entries))

    normalized = []
    for prefix in prefixes:
        if os.path.isabs(prefix):
            continue
        normalized.append(os.path.normpath(prefix))
    results: dict[str, tuple[str, bool]] = {}
    for path, shasum, deleted in entries:
        for prefix in normalized:
            if path == prefix or path.startswith(prefix + os.sep):
                if recursive:
                    results[path] = (shasum, deleted)
                    break
                results[path] = (shasum, deleted)
                break
    return sorted(
        (path, shasum, deleted) for path, (shasum, deleted) in results.items()
    )


def walk_files(root: str, shadir: str, skip_dotfiles: bool) -> Iterator[str]:
    """Yield file paths under root, skipping the sha store and dotfiles."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if is_under_dir(os.path.abspath(dirpath), shadir):
            dirnames[:] = []
            continue

        if skip_dotfiles:
            dirnames[:] = [name for name in dirnames if not name.startswith(".")]

        for name in filenames:
            if skip_dotfiles and name.startswith("."):
                continue
            full_path = os.path.join(dirpath, name)
            if is_under_dir(os.path.abspath(full_path), shadir):
                continue
            yield full_path


def map_walk_files(
    root: str, shadir: str, skip_dotfiles: bool, mapper: Callable[[str], T]
) -> Iterator[T]:
    """Return iterator of mapper results over walked files."""
    max_workers = min(32, (os.cpu_count() or 1) + 4)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        for result in executor.map(mapper, walk_files(root, shadir, skip_dotfiles)):
            yield result


def walk_symlinks(
    root: str, shadir: str, skip_dotfiles: bool, recursive: bool
) -> Iterator[str]:
    """Yield symlink paths under root, skipping the sha store and dotfiles."""
    abs_root = os.path.abspath(root)
    if os.path.islink(abs_root):
        yield abs_root
        return
    if os.path.isfile(abs_root):
        return
    if not os.path.isdir(abs_root):
        raise SystemExit(f"fixlinks root not found: {root}")

    if not recursive:
        with os.scandir(abs_root) as entries:
            for entry in entries:
                name = entry.name
                if skip_dotfiles and name.startswith("."):
                    continue
                full_path = os.path.join(abs_root, name)
                if is_under_dir(os.path.abspath(full_path), shadir):
                    continue
                if os.path.islink(full_path):
                    yield full_path
        return

    for dirpath, dirnames, filenames in os.walk(abs_root, followlinks=False):
        if is_under_dir(os.path.abspath(dirpath), shadir):
            dirnames[:] = []
            continue
        if skip_dotfiles:
            dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for name in filenames:
            if skip_dotfiles and name.startswith("."):
                continue
            full_path = os.path.join(dirpath, name)
            if is_under_dir(os.path.abspath(full_path), shadir):
                continue
            if os.path.islink(full_path):
                yield full_path


def _resolve_link_target(link_path: str) -> str:
    target = os.readlink(link_path)
    if os.path.isabs(target):
        return os.path.abspath(target)
    return os.path.abspath(os.path.join(os.path.dirname(link_path), target))


def _lookup_db_hash(
    conn: sqlite3.Connection, root_rel: str, rel_dir: str, filename: str
) -> str | None:
    row = conn.execute(
        """
        SELECT shasum
        FROM stored_files
        WHERE root_rel = ? AND dirpath = ? AND filename = ? AND deleted = 0
        ORDER BY rowid DESC
        LIMIT 1
        """,
        (root_rel, rel_dir, filename),
    ).fetchone()
    if not row:
        return None
    value = row[0].lower()
    return value if HASH_RE.match(value) else None


def _set_fixed_link_in_db(
    conn: sqlite3.Connection,
    digest: str,
    abs_root: str,
    root_rel: str,
    rel_dir: str,
    filename: str,
) -> None:
    conn.execute(
        """
        UPDATE stored_files
        SET deleted = 1
        WHERE root_rel = ? AND dirpath = ? AND filename = ? AND shasum <> ? AND deleted = 0
        """,
        (root_rel, rel_dir, filename, digest),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO stored_files
        (shasum, root, root_rel, dirpath, filename, deleted)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (digest, abs_root, root_rel, rel_dir, filename),
    )
    conn.execute(
        """
        UPDATE stored_files
        SET deleted = 0
        WHERE shasum = ? AND root_rel = ? AND dirpath = ? AND filename = ?
        """,
        (digest, root_rel, rel_dir, filename),
    )


def handle_fixlinks(
    conn: sqlite3.Connection,
    roots: list[str],
    shadir: str,
    skip_dotfiles: bool,
    recursive: bool,
    paranoia: int,
) -> None:
    """Repair symlinks to canonical shadir targets and update DB entries."""
    fixed = 0
    checked = 0
    shadir_abs = os.path.abspath(shadir)
    store_cwd = os.getcwd()
    for root in roots:
        abs_root = os.path.abspath(root)
        root_rel = os.path.relpath(abs_root, store_cwd)
        root_is_file = os.path.isfile(abs_root) or os.path.islink(abs_root)
        for link_path in walk_symlinks(abs_root, shadir_abs, skip_dotfiles, recursive):
            checked += 1
            if root_is_file:
                rel_dir = ""
            else:
                rel_dir = os.path.relpath(os.path.dirname(link_path), abs_root)
                if rel_dir == ".":
                    rel_dir = ""
            filename = os.path.basename(link_path)

            try:
                current_target = _resolve_link_target(link_path)
            except OSError as exc:
                out("skip unreadable symlink {path}: {exc}", 0, path=link_path, exc=exc)
                continue

            digest = os.path.basename(current_target).lower()
            if not HASH_RE.match(digest):
                db_digest = _lookup_db_hash(conn, root_rel, rel_dir, filename)
                if db_digest:
                    digest = db_digest
                else:
                    out("skip no digest for {path}", 0, path=link_path)
                    continue

            canonical_target = os.path.join(shadir_abs, digest[:2], digest)
            target_exists = os.path.isfile(canonical_target)
            target_hash_ok = True
            if paranoia >= 1 and not target_exists:
                out("missing target {path} -> {target}", 0, path=link_path, target=canonical_target)
                continue
            if paranoia >= 2 and target_exists:
                actual = sha256_file(canonical_target)
                if actual != digest:
                    target_hash_ok = False
                    out(
                        "hash mismatch target {target} expected {expected} got {actual}",
                        0,
                        target=canonical_target,
                        expected=digest,
                        actual=actual,
                    )
                    continue

            needs_fix = os.path.abspath(current_target) != os.path.abspath(canonical_target)
            if not needs_fix and paranoia == 0:
                continue
            if not needs_fix and paranoia > 0 and target_exists and target_hash_ok:
                continue

            os.unlink(link_path)
            os.symlink(os.path.abspath(canonical_target), link_path)
            _set_fixed_link_in_db(conn, digest, abs_root, root_rel, rel_dir, filename)
            fixed += 1
            out("fixed {path} -> {target}", 1, path=link_path, target=canonical_target)

    out("checked links: {checked}", 0, checked=checked)
    out("fixed links: {fixed}", 0, fixed=fixed)


def compute_digest(path: str) -> tuple[str, str, int] | None:
    """Return (path, sha256, size) for a regular file, else None."""
    if os.path.islink(path) or not os.path.isfile(path):
        return None
    try:
        size = os.stat(path).st_size
        return path, sha256_file(path), size
    except OSError as exc:
        out("skip unreadable {path}: {exc}", 0, path=path, exc=exc)
        return None


def _record_stored_file(
    conn: sqlite3.Connection,
    digest: str,
    abs_root: str,
    root_rel: str,
    rel_dir: str,
    filename: str,
    dest: str,
    existed_already: bool,
) -> None:
    verb = "linked" if existed_already else "stored"
    out("{verb} {path} -> {dest}", 1, verb=verb, path=filename, dest=dest)
    conn.execute(
        """
        INSERT OR IGNORE INTO stored_files
        (shasum, root, root_rel, dirpath, filename, deleted)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (digest, abs_root, root_rel, rel_dir, filename),
    )
    conn.execute(
        """
        UPDATE stored_files
        SET deleted = 0
        WHERE shasum = ? AND root_rel = ? AND dirpath = ? AND filename = ?
        """,
        (digest, root_rel, rel_dir, filename),
    )


def handle_store(
    conn: sqlite3.Connection, root: str, shadir: str, skip_dotfiles: bool
) -> None:
    """Store files under root into shadir and replace with symlinks."""
    stored_bytes = 0
    skipped_bytes = 0
    abs_root = os.path.abspath(root)
    store_cwd = os.getcwd()
    root_rel = os.path.relpath(abs_root, store_cwd)
    if os.path.isfile(abs_root):
        digest_result = compute_digest(abs_root)
        if digest_result is None:
            out("stored bytes: {stored_bytes}", 0, stored_bytes=stored_bytes)
            out(
                "skipped bytes (already stored): {skipped_bytes}",
                0,
                skipped_bytes=skipped_bytes,
            )
            return
        path, digest, size = digest_result
        store_result = store_digest(path, digest, shadir)
        if store_result:
            dest, existed_already = store_result
            rel_dir = ""
            filename = os.path.basename(path)
            _record_stored_file(
                conn,
                digest,
                abs_root,
                root_rel,
                rel_dir,
                filename,
                dest,
                existed_already,
            )
            if existed_already:
                skipped_bytes += size
            else:
                stored_bytes += size
        out("stored bytes: {stored_bytes}", 0, stored_bytes=stored_bytes)
        out(
            "skipped bytes (already stored): {skipped_bytes}",
            0,
            skipped_bytes=skipped_bytes,
        )
        return
    for digest_result in map_walk_files(root, shadir, skip_dotfiles, compute_digest):
        if digest_result is None:
            continue
        path, digest, size = digest_result
        store_result = store_digest(path, digest, shadir)
        if store_result:
            dest, existed_already = store_result
            rel_dir = os.path.relpath(os.path.dirname(path), abs_root)
            filename = os.path.basename(path)
            _record_stored_file(
                conn,
                digest,
                abs_root,
                root_rel,
                rel_dir,
                filename,
                dest,
                existed_already,
            )
            if existed_already:
                skipped_bytes += size
            else:
                stored_bytes += size
    out("stored bytes: {stored_bytes}", 0, stored_bytes=stored_bytes)
    out(
        "skipped bytes (already stored): {skipped_bytes}",
        0,
        skipped_bytes=skipped_bytes,
    )


def handle_dedup(
    conn: sqlite3.Connection, root: str, shadir: str, skip_dotfiles: bool
) -> None:
    """Replace files with existing shadir links without storing or db updates."""
    linked = 0
    abs_root = os.path.abspath(root)
    store_cwd = os.getcwd()
    root_rel = os.path.relpath(abs_root, store_cwd)
    for digest_result in map_walk_files(root, shadir, skip_dotfiles, compute_digest):
        if digest_result is None:
            continue
        path, digest, _size = digest_result
        dest = os.path.join(shadir, digest[:2], digest)
        if not os.path.exists(dest):
            continue
        rel_dir = os.path.relpath(os.path.dirname(path), abs_root)
        filename = os.path.basename(path)
        dup_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM stored_files
            WHERE shasum = ?
              AND deleted = 0
              AND NOT (root_rel = ? AND dirpath = ? AND filename = ?)
            """,
            (digest, root_rel, rel_dir, filename),
        ).fetchone()[0]
        out("dup_count {path} {dup_count}", 2, path=path, dup_count=dup_count)
        if dup_count <= 0:
            continue
        parent_dir = os.path.dirname(path)
        dedup_dir = os.path.join(parent_dir, ".dedup")
        if os.path.exists(dedup_dir) and not os.path.isdir(dedup_dir):
            raise RuntimeError(f"dedup path is a file: {dedup_dir}")
        os.makedirs(dedup_dir, exist_ok=True)
        dedup_path = os.path.join(dedup_dir, filename)
        if os.path.lexists(dedup_path):
            if os.path.isdir(dedup_path):
                raise RuntimeError(f"dedup target is a directory: {dedup_path}")
            os.unlink(dedup_path)
        abs_target = os.path.abspath(dest)
        os.symlink(abs_target, dedup_path)
        os.unlink(path)
        linked += 1
        out("linked {path} -> {dest}", 1, path=path, dest=dest)
    out("linked files: {linked}", 0, linked=linked)


def handle_extract(
    conn: sqlite3.Connection, prefixes: list[str], shadir: str, show_deleted: bool
) -> None:
    """Extract files from the db that match prefix paths."""
    extracted_bytes = extract_from_db(conn, shadir, prefixes, show_deleted=show_deleted)
    out("extracted bytes: {extracted_bytes}", 0, extracted_bytes=extracted_bytes)



def handle_ls(
    conn: sqlite3.Connection,
    prefixes: list[str],
    shadir: str,
    recursive: bool,
    show_deleted: bool,
    mindup: int,
) -> None:
    """Print list entries under prefixes."""
    entries = list_children(
        conn, prefixes, recursive=recursive, show_deleted=show_deleted
    )
    if mindup > 1 and entries:
        grouped: dict[str, list[str]] = {}
        for path, shasum, _deleted in entries:
            grouped.setdefault(shasum, []).append(path)
        dup_shasums = {shasum for shasum, paths in grouped.items() if len(paths) > 1}
        dir_counts: dict[str, int] = {}
        for path, shasum, _deleted in entries:
            if shasum not in dup_shasums:
                continue
            dirpath = os.path.dirname(path)
            dir_counts[dirpath] = dir_counts.get(dirpath, 0) + 1
        allowed_dirs = {dirpath for dirpath, count in dir_counts.items() if count >= mindup}
        entries = [entry for entry in entries if os.path.dirname(entry[0]) in allowed_dirs]
    if not entries:
        return
    if OUTPUT_MODE == "machine":
        _emit_lspath_machine(entries)
        return
    _emit_lspath_pretty(entries, show_deleted)


def handle_lshash(
    conn: sqlite3.Connection,
    hashes: list[str],
    shadir: str,
    show_deleted: bool,
    mindup: int,
) -> None:
    """Print list entries grouped by sha256 hash."""
    entries = list_db_entries(conn, show_deleted)
    if hashes:
        normalized = {value for value in (normalize_hash_arg(shadir, h) for h in hashes) if value}
        entries = [entry for entry in entries if entry[1] in normalized]
    if not entries:
        return
    grouped: dict[str, list[tuple[str, bool]]] = {}
    for path, shasum, deleted in entries:
        grouped.setdefault(shasum, []).append((path, deleted))
    if mindup > 1:
        grouped = {
            shasum: paths
            for shasum, paths in grouped.items()
            if len(paths) >= mindup
        }
        if not grouped:
            return
    if OUTPUT_MODE == "machine":
        _emit_lshash_machine(grouped, show_deleted)
        return
    _emit_lshash_pretty(grouped, show_deleted)


def normalize_prefixes(prefixes: list[str]) -> list[str]:
    """Normalize relative prefixes and drop absolute paths.

    >>> normalize_prefixes(["a/b", "/abs", "c"])
    ['a/b', 'c']
    """
    normalized = []
    for prefix in prefixes:
        if os.path.isabs(prefix):
            continue
        normalized.append(os.path.normpath(prefix))
    return normalized


def delete_from_db(
    conn: sqlite3.Connection,
    shadir: str,
    prefixes: list[str],
    recursive: bool,
    show_deleted: bool,
) -> int:
    """Mark stored entries as deleted and return count."""
    normalized = normalize_prefixes(prefixes)
    if not normalized:
        return 0

    if show_deleted:
        rows = conn.execute(
            "SELECT shasum, root_rel, dirpath, filename FROM stored_files"
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT shasum, root_rel, dirpath, filename
            FROM stored_files
            WHERE deleted = 0
            """
        ).fetchall()

    target_rows: list[tuple[str, str, str, str]] = []
    for shasum, root_rel, dirpath, filename in rows:
        target_rel = os.path.normpath(os.path.join(root_rel, dirpath, filename))
        for prefix in normalized:
            if recursive:
                if target_rel == prefix or target_rel.startswith(prefix + os.sep):
                    target_rows.append((shasum, root_rel, dirpath, filename))
                    break
            else:
                if target_rel == prefix:
                    target_rows.append((shasum, root_rel, dirpath, filename))
                    break

    if not recursive:
        exact_matches = {
            os.path.normpath(os.path.join(r, d, f)) for _, r, d, f in target_rows
        }
        for prefix in normalized:
            if prefix in exact_matches:
                continue
            has_descendants = any(
                row_path.startswith(prefix + os.sep)
                for row_path in (
                    os.path.normpath(os.path.join(r, d, f)) for _, r, d, f in rows
                )
            )
            if has_descendants:
                out(
                    "skip directory prefix without --recursive: {prefix}",
                    0,
                    prefix=prefix,
                )

    if not target_rows:
        return 0

    out("delete entries {count}", 2, count=len(target_rows))
    conn.executemany(
        """
        UPDATE stored_files
        SET deleted = 1
        WHERE shasum = ? AND root_rel = ? AND dirpath = ? AND filename = ?
        """,
        target_rows,
    )
    return len(target_rows)


def delete_by_hashes(
    conn: sqlite3.Connection, shasums: list[str], shadir: str
) -> int:
    """Mark all entries with matching shasums as deleted and return count."""
    normalized = [value for value in (normalize_hash_arg(shadir, h) for h in shasums) if value]
    if not normalized:
        return 0
    placeholders = ",".join("?" for _ in normalized)
    count = conn.execute(
        f"SELECT COUNT(*) FROM stored_files WHERE shasum IN ({placeholders})",
        normalized,
    ).fetchone()[0]
    conn.execute(
        f"UPDATE stored_files SET deleted = 1 WHERE shasum IN ({placeholders})",
        normalized,
    )
    return count


def handle_del(
    conn: sqlite3.Connection,
    prefixes: list[str],
    shadir: str,
    recursive: bool,
    show_deleted: bool,
) -> None:
    """Delete db entries matching prefixes."""
    deleted = delete_from_db(
        conn,
        shadir,
        prefixes,
        recursive=recursive,
        show_deleted=show_deleted,
    )
    out("deleted entries: {deleted}", 0, deleted=deleted)


def handle_rmhash(conn: sqlite3.Connection, shasums: list[str], shadir: str) -> None:
    """Delete db entries matching shasums."""
    deleted = delete_by_hashes(conn, shasums, shadir)
    out("deleted entries: {deleted}", 0, deleted=deleted)


def main() -> int:
    """Entry point for command execution."""
    args = parse_args()
    global VERBOSITY
    VERBOSITY = args.v
    global OUTPUT_MODE
    OUTPUT_MODE = "pretty" if sys.stdout.isatty() else "machine"
    if args.shadir:
        shadir = os.path.abspath(args.shadir)
    else:
        found = find_shadir(os.getcwd())
        if not found:
            raise SystemExit(
                "--shadir is required when no .shadup/.shadir directory is found"
            )
        shadir = found
    cwd = os.path.abspath(os.curdir)
    if is_under_dir(cwd, shadir):
        raise SystemExit(f"cwd must not be inside shadir: cwd={cwd} shadir={shadir}")
    if args.lspath is not None and args.recursive:
        raise SystemExit("--lspath/--ls does not accept --recursive")
    if args.rmhash and args.recursive:
        raise SystemExit("--rmhash does not accept --recursive")
    if args.paranoia < 0 or args.paranoia > 2:
        raise SystemExit("--paranoia must be 0, 1, or 2")
    if args.paranoia and not args.fixlinks:
        raise SystemExit("--paranoia is only valid with --fixlinks")
    if args.mindup < 1:
        raise SystemExit("--mindup must be >= 1")
    if args.mindup != 1 and args.lspath is None and args.lshash is None:
        raise SystemExit("--mindup is only valid with --lspath/--ls or --lshash")
    db_path = os.path.abspath(args.db) if args.db else None
    with open_db(shadir, db_path) as conn:
        if args.store:
            for root in args.store:
                out("store {root}", 1, root=root)
                handle_store(conn, os.path.abspath(root), shadir, args.skip_dotfiles)
            return 0
        if args.extract:
            for prefix in args.extract:
                out("extract {prefix}", 1, prefix=prefix)
            handle_extract(conn, args.extract, shadir, show_deleted=args.show_deleted)
            return 0
        if args.lspath is not None:
            for prefix in args.lspath:
                out("lspath {prefix}", 1, prefix=prefix)
            handle_ls(
                conn,
                args.lspath,
                shadir,
                recursive=args.recursive,
                show_deleted=args.show_deleted,
                mindup=args.mindup,
            )
            return 0
        if args.lshash is not None:
            for shasum in args.lshash:
                out("lshash {shasum}", 1, shasum=shasum)
            handle_lshash(
                conn,
                args.lshash,
                shadir,
                show_deleted=args.show_deleted,
                mindup=args.mindup,
            )
            return 0
        if args.rmpath:
            for prefix in args.rmpath:
                out("rmpath {prefix}", 1, prefix=prefix)
            handle_del(
                conn,
                args.rmpath,
                shadir,
                recursive=args.recursive,
                show_deleted=args.show_deleted,
            )
            return 0
        if args.rmhash:
            for shasum in args.rmhash:
                out("rmhash {shasum}", 1, shasum=shasum)
            handle_rmhash(conn, args.rmhash, shadir)
            return 0
        if args.fixlinks:
            for root in args.fixlinks:
                out("fixlinks {root}", 1, root=root)
            handle_fixlinks(
                conn,
                [os.path.abspath(root) for root in args.fixlinks],
                shadir,
                args.skip_dotfiles,
                recursive=args.recursive,
                paranoia=args.paranoia,
            )
            return 0
        for root in args.dedup:
            out("dedup {root}", 1, root=root)
            handle_dedup(conn, os.path.abspath(root), shadir, args.skip_dotfiles)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

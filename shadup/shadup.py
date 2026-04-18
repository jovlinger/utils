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
# Per-tag folder name under ``_tags`` that collects directory mirrors with an
# empty computed tag set (see :func:`plan_refresh_extracted_tag_mirrors`).
NOTAGS_DIR_NAME = "NOTAGS"
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


def _emit_lspath_machine(
    entries: list[tuple[str, str, list[str], bool]],
) -> None:
    for path, shasum, tags, deleted in entries:
        out_csv([path, shasum, json.dumps(tags), "1" if deleted else "0"])


def _emit_lspath_pretty(
    entries: list[tuple[str, str, list[str], bool]], show_deleted: bool
) -> None:
    formatted = [
        (_format_pretty_path(path), shasum, tags, deleted)
        for path, shasum, tags, deleted in entries
    ]
    max_path = max(len(path) for path, _s, _t, _d in formatted)
    tag_strs = [json.dumps(tags, sort_keys=True) for _p, _s, tags, _d in formatted]
    max_tags = max(len(t) for t in tag_strs) if tag_strs else 0
    for (path, shasum, tags, deleted), tstr in zip(formatted, tag_strs, strict=True):
        if show_deleted:
            out(
                "{path} {tags} {deleted} {shasum}",
                0,
                path=path.ljust(max_path),
                tags=tstr.ljust(max_tags),
                deleted="X" if deleted else ".",
                shasum=shasum,
                kind="data",
            )
        else:
            out(
                "{path} {tags} {shasum}",
                0,
                path=path.ljust(max_path),
                tags=tstr.ljust(max_tags),
                shasum=shasum,
                kind="data",
            )


def _emit_ls_alltags_machine(rows: list[tuple[str, list[str]]]) -> None:
    for path, tags in rows:
        out_csv([path, json.dumps(tags)])


def _emit_ls_alltags_pretty(rows: list[tuple[str, list[str]]]) -> None:
    formatted = [(_format_pretty_path(path), tags) for path, tags in rows]
    max_path = max(len(p) for p, _t in formatted) if formatted else 0
    tag_strs = [json.dumps(tags, sort_keys=True) for _p, tags in formatted]
    max_tags = max(len(t) for t in tag_strs) if tag_strs else 0
    for (path, tags), tstr in zip(formatted, tag_strs, strict=True):
        out(
            "{path} {tags}",
            0,
            path=path.ljust(max_path),
            tags=tstr.ljust(max_tags),
            kind="data",
        )


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


def _parse_bool(value: str) -> bool:
    """Parse a CLI boolean value."""
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean: {value!r}")


def _positive_int(value: str) -> int:
    """Accept integers >= 1 for ``--mindup``."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1: {value!r}")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Build the AWS-style ``shadup [global] <action> [action-opts]`` parser."""
    parser = argparse.ArgumentParser(
        prog="shadup",
        description="Store files by sha256 and replace with symlinks, or extract back.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Shadir discovery: without --shadir, searches upward from the current "
            "working directory. At each ancestor directory, looks for an existing "
            "subdirectory named .shadup, then .shadir (in that order). The walk "
            "stops at $HOME when cwd is under your home directory, otherwise at "
            "the filesystem root. If neither name is found, you must pass "
            "--shadir. When --shadir is set, that store path is created if it "
            "does not exist (on first database open).\n\n"
            "Database: defaults to <shadir>/.shadup.db unless --db is given. "
            "The database file's parent directory is created if missing; the DB "
            "file is created on first open.\n\n"
            "check action: with no --shadir/--db, exit 0 if a store is found and "
            "<shadir>/.shadup.db exists, else exit 1; prints the DB path and "
            "cheap aggregate stats. With --shadir and/or --db, open (creating) "
            "the DB, print path and stats, and exit 0."
        ),
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
        "-v",
        action="count",
        default=0,
        help="Increase verbosity (can be repeated)",
    )

    sub = parser.add_subparsers(dest="action", required=True, metavar="ACTION")

    p_store = sub.add_parser("store", help="Store files by sha256 under directories")
    p_store.add_argument(
        "dirs", nargs="+", metavar="DIR", help="Directories (or files) to store"
    )
    p_store.add_argument(
        "--skip-dotfiles",
        type=_parse_bool,
        default=True,
        metavar="BOOL",
        help="Skip files and directories starting with '.' (default: true)",
    )

    p_extract = sub.add_parser(
        "extract", help="Extract files back to their original paths"
    )
    p_extract.add_argument(
        "prefixes",
        nargs="+",
        metavar="DIR",
        help="Prefix paths to extract (relative to cwd at store time)",
    )
    p_extract.add_argument(
        "-d", "--show-deleted", action="store_true", help="Include deleted entries"
    )

    p_ls = sub.add_parser(
        "ls",
        aliases=["lspath"],
        help="List stored file paths with sha256 hashes and tags",
    )
    p_ls.add_argument(
        "prefixes",
        nargs="*",
        metavar="PATH",
        help="Optional path prefixes to filter by",
    )
    p_ls.add_argument(
        "-d", "--show-deleted", action="store_true", help="Include deleted entries"
    )
    p_ls.add_argument(
        "--mindup",
        type=_positive_int,
        default=1,
        metavar="N",
        help="Minimum duplicate count for filtering (default: 1)",
    )
    p_ls.add_argument(
        "--alltags",
        action="store_true",
        help=(
            "List directories under files/ with recursive computed tag sets "
            "(union over immediate children). Default: direct DB tags per file row."
        ),
    )

    p_lshash = sub.add_parser("lshash", help="List stored file paths grouped by sha256")
    p_lshash.add_argument(
        "hashes",
        nargs="*",
        metavar="HASH",
        help="Optional sha256 hashes (or symlinks to them) to filter by",
    )
    p_lshash.add_argument(
        "-d", "--show-deleted", action="store_true", help="Include deleted entries"
    )
    p_lshash.add_argument(
        "--mindup",
        type=_positive_int,
        default=1,
        metavar="N",
        help="Minimum duplicate count for filtering (default: 1)",
    )

    p_rmpath = sub.add_parser(
        "rmpath", help="Mark stored entries as deleted by path prefix"
    )
    p_rmpath.add_argument(
        "prefixes", nargs="+", metavar="PATH", help="Path prefixes to mark deleted"
    )
    p_rmpath.add_argument(
        "-r", "--recursive", action="store_true", help="Recurse into child paths"
    )
    p_rmpath.add_argument(
        "-d",
        "--show-deleted",
        action="store_true",
        help="Include already-deleted entries in selection",
    )

    p_rmhash = sub.add_parser(
        "rmhash", help="Mark all entries with matching sha256 as deleted"
    )
    p_rmhash.add_argument(
        "hashes", nargs="+", metavar="HASH", help="sha256 hashes (or symlinks to them)"
    )

    p_dedup = sub.add_parser(
        "dedup", help="Replace files with existing shadir links without storing"
    )
    p_dedup.add_argument(
        "dirs", nargs="+", metavar="DIR", help="Directories to scan for duplicates"
    )
    p_dedup.add_argument(
        "--skip-dotfiles",
        type=_parse_bool,
        default=True,
        metavar="BOOL",
        help="Skip files and directories starting with '.' (default: true)",
    )

    p_fixlinks = sub.add_parser(
        "fixlinks", help="Fix broken symlink targets under directories"
    )
    p_fixlinks.add_argument(
        "dirs", nargs="+", metavar="DIR", help="Directories to scan for symlinks to fix"
    )
    p_fixlinks.add_argument(
        "-r", "--recursive", action="store_true", help="Recurse into subdirectories"
    )
    p_fixlinks.add_argument(
        "--paranoia",
        type=int,
        default=0,
        choices=(0, 1, 2),
        help="0=no extra checks, 1=target exists, 2=1+sha256 verify",
    )
    p_fixlinks.add_argument(
        "--skip-dotfiles",
        type=_parse_bool,
        default=True,
        metavar="BOOL",
        help="Skip files and directories starting with '.' (default: true)",
    )

    p_reindex = sub.add_parser(
        "reindex-files",
        help="Rebuild DB entries by scanning symlinks under a files/ tree",
    )
    p_reindex.add_argument(
        "dir",
        nargs="?",
        default=None,
        metavar="DIR",
        help="Root of files/ tree (default: <parent-of-shadir>/files)",
    )
    p_reindex.add_argument(
        "--skip-dotfiles",
        type=_parse_bool,
        default=True,
        metavar="BOOL",
        help="Skip files and directories starting with '.' (default: true)",
    )

    sub.add_parser(
        "check",
        help=(
            "Verify shadir discovery and DB. Without --shadir/--db: exit 0 if "
            "store + default DB exist. With either: open (creating) the DB and "
            "print path + aggregate stats."
        ),
    )

    p_tadd = sub.add_parser(
        "tag-add", help="Add tags to a stored file identified by path"
    )
    p_tadd.add_argument(
        "path",
        metavar="PATH",
        help="Path to a stored file (symlink into shadir) or a regular file",
    )
    p_tadd.add_argument("tags", nargs="+", metavar="TAG", help="Tags to add")

    p_trm = sub.add_parser(
        "tag-rm", help="Remove tags from a stored file identified by path"
    )
    p_trm.add_argument(
        "path",
        metavar="PATH",
        help="Path to a stored file (symlink into shadir) or a regular file",
    )
    p_trm.add_argument("tags", nargs="+", metavar="TAG", help="Tags to remove")

    sub.add_parser(
        "refresh-extracted-tags",
        help="Rebuild _tags/ symlinks under files/ from filesystem + DB tags",
    )

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the AWS-style ``shadup <action>`` interface."""
    return build_parser().parse_args(argv)


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


def expand_path(path: str) -> str:
    """Expand ~ / ~user and normalize to an absolute path."""
    return os.path.abspath(os.path.expanduser(path))


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


def resolve_path_to_shasum(shadir: str, path: str) -> str | None:
    """Resolve a filesystem path to its stored sha256 digest.

    Accepts a symlink whose target is ``<shadir>/xx/<digest>`` (the shape
    produced by ``--store``) or a regular file, which is hashed on the fly.
    Raw hash strings are intentionally rejected here; use ``--rmhash`` or
    ``--lshash`` for hash-addressed operations.
    """
    if not path:
        return None
    if os.path.islink(path):
        resolved = os.path.realpath(path)
        base = os.path.basename(resolved).lower()
        if HASH_RE.match(base) and is_under_dir(resolved, shadir):
            return base
        if os.path.isfile(resolved):
            try:
                return sha256_file(resolved)
            except OSError:
                return None
        return None
    if os.path.isfile(path):
        try:
            return sha256_file(path)
        except OSError:
            return None
    return None


def resolve_db_path(shadir: str, db_path: str | None = None) -> str:
    """Return absolute path to the SQLite DB (default: <shadir>/.shadup.db)."""
    if db_path is None:
        return os.path.join(shadir, DB_NAME)
    return expand_path(db_path)


def fetch_check_stats(conn: sqlite3.Connection) -> tuple[int, int, int, int]:
    """Return cheap aggregates: active rows, distinct active hashes, deleted rows, total rows."""
    try:
        row = conn.execute(
            """
            SELECT
              SUM(CASE WHEN deleted = 0 THEN 1 ELSE 0 END),
              COUNT(DISTINCT CASE WHEN deleted = 0 THEN shasum END),
              SUM(CASE WHEN deleted = 1 THEN 1 ELSE 0 END),
              COUNT(*)
            FROM stored_files
            """
        ).fetchone()
    except sqlite3.OperationalError:
        return (0, 0, 0, 0)
    if not row or row[3] is None:
        return (0, 0, 0, 0)
    active, distinct_h, deleted, total = row
    return (
        int(active or 0),
        int(distinct_h or 0),
        int(deleted or 0),
        int(total or 0),
    )


def emit_check_report(conn: sqlite3.Connection, shadir: str, db_path: str) -> None:
    """Print resolved DB path, cheap table aggregates, and check ok line."""
    active, distinct_h, deleted, total = fetch_check_stats(conn)
    out("check db {db_path}", 0, db_path=db_path, kind="data")
    out(
        "check stats: active_entries {active} distinct_hashes {distinct_h} "
        "deleted_entries {deleted} total_rows {total}",
        0,
        active=active,
        distinct_h=distinct_h,
        deleted=deleted,
        total=total,
        kind="data",
    )
    out("check ok: shadir {shadir}", 0, shadir=shadir, kind="data")


def open_db(shadir: str, db_path: str | None = None) -> sqlite3.Connection:
    """Open shadir sqlite db and ensure schema.
    If db_path is given, use it; otherwise use <shadir>/.shadup.db.
    """
    db_path = resolve_db_path(shadir, db_path)
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
    # sha_tags stores a JSON list of opaque tag strings keyed by sha256 hash.
    # Many hashes can share the same tag; one hash can carry many tags.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sha_tags (
            shasum TEXT NOT NULL PRIMARY KEY,
            tags TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    return conn


# ---------------------------------------------------------------------------
# Tag helpers
# ---------------------------------------------------------------------------


def get_tags(conn: sqlite3.Connection, shasum: str) -> list[str]:
    """Return the tags for a sha256 hash, or [] if none."""
    row = conn.execute(
        "SELECT tags FROM sha_tags WHERE shasum = ?", (shasum,)
    ).fetchone()
    if not row:
        return []
    return json.loads(row[0])


def set_tags(conn: sqlite3.Connection, shasum: str, tags: list[str]) -> None:
    """Replace the tag list for a sha256 hash."""
    conn.execute(
        """
        INSERT INTO sha_tags (shasum, tags) VALUES (?, ?)
        ON CONFLICT(shasum) DO UPDATE SET tags = excluded.tags
        """,
        (shasum, json.dumps(sorted(set(tags)))),
    )


def add_tags(conn: sqlite3.Connection, shasum: str, tags: list[str]) -> None:
    """Add tags to a sha256 hash (no-op for already-present tags)."""
    current = get_tags(conn, shasum)
    set_tags(conn, shasum, list(set(current) | set(tags)))


def remove_tags(conn: sqlite3.Connection, shasum: str, tags: list[str]) -> None:
    """Remove tags from a sha256 hash (no-op for absent tags)."""
    current = get_tags(conn, shasum)
    set_tags(conn, shasum, [t for t in current if t not in tags])


# ---------------------------------------------------------------------------
# Tag command handlers
# ---------------------------------------------------------------------------


def handle_tag_add(
    conn: sqlite3.Connection, shadir: str, path_arg: str, tags: list[str]
) -> None:
    """Add tags to the stored file at *path_arg*."""
    shasum = resolve_path_to_shasum(shadir, path_arg)
    if not shasum:
        raise SystemExit(f"cannot resolve path to stored file: {path_arg!r}")
    add_tags(conn, shasum, tags)
    conn.commit()
    out(
        "tags for {shasum}: {tags}",
        0,
        shasum=shasum,
        tags=json.dumps(get_tags(conn, shasum)),
        kind="data",
    )


def handle_tag_rm(
    conn: sqlite3.Connection, shadir: str, path_arg: str, tags: list[str]
) -> None:
    """Remove tags from the stored file at *path_arg*."""
    shasum = resolve_path_to_shasum(shadir, path_arg)
    if not shasum:
        raise SystemExit(f"cannot resolve path to stored file: {path_arg!r}")
    remove_tags(conn, shasum, tags)
    conn.commit()
    out(
        "tags for {shasum}: {tags}",
        0,
        shasum=shasum,
        tags=json.dumps(get_tags(conn, shasum)),
        kind="data",
    )


def _parent_dir_key(dir_key: str) -> str:
    """Parent POSIX directory key; empty if ``dir_key`` has a single segment."""
    if not dir_key or "/" not in dir_key:
        return ""
    return "/".join(dir_key.split("/")[:-1])


def _allocate_flat_link_basename(taken: set[str], logical_base: str) -> str:
    """First free name among ``base``, ``base(2)``, ``base(3)``, … and mark it taken."""
    if logical_base not in taken:
        taken.add(logical_base)
        return logical_base
    n = 2
    while True:
        cand = f"{logical_base}({n})"
        if cand not in taken:
            taken.add(cand)
            return cand
        n += 1


def _plan_flat_mirrors_for_tag(
    tag: str, subset: set[str]
) -> list[tuple[str, str, str]]:
    """BFS per top-level component; ``taken`` basenames are shared across components."""
    from collections import deque

    roots = sorted(d for d in subset if "/" not in d)
    taken: set[str] = set()
    rows: list[tuple[str, str, str]] = []
    for root in roots:
        dq: deque[str] = deque([root])
        while dq:
            dk = dq.popleft()
            logical_base = dk.split("/")[-1]
            name = _allocate_flat_link_basename(taken, logical_base)
            rows.append((tag, name, dk))
            children = sorted(
                (d for d in subset if _parent_dir_key(d) == dk),
                reverse=True,
            )
            dq.extend(children)
    return rows


def plan_refresh_extracted_tag_mirrors(
    tags_by_dir: dict[str, frozenset[str]],
) -> list[tuple[str, str, str]]:
    """Plan flat per-tag symlinks: ``(tag_or_NOTAGS, link_basename, dir_key)`` rows.

    Rules:

    * For every tag ``t`` present on any directory, include directories whose
      computed set contains ``t`` and walk them top-down BFS per top-level
      component. Siblings are emitted **descending by dir_key** (so ``a/b``
      appears before ``a/a``).
    * Within a tag folder, duplicate basenames are disambiguated with
      ``(2)``, ``(3)``, … (shared across top-level components under the tag).
    * Directories whose computed set is empty go under
      :data:`NOTAGS_DIR_NAME` with the same BFS + disambiguation rules.
    * The root directory (``dir_key = ""``) is **never** mirrored.
    * Tags iterate in ``sorted`` order; :data:`NOTAGS_DIR_NAME` is emitted last.
    """
    rows: list[tuple[str, str, str]] = []
    all_tags: set[str] = set()
    for ts in tags_by_dir.values():
        all_tags |= set(ts)
    for tag in sorted(all_tags):
        subset = {dk for dk, ts in tags_by_dir.items() if dk and tag in ts}
        rows.extend(_plan_flat_mirrors_for_tag(tag, subset))
    empty_dirs = {dk for dk, ts in tags_by_dir.items() if dk and not ts}
    if empty_dirs:
        rows.extend(_plan_flat_mirrors_for_tag(NOTAGS_DIR_NAME, empty_dirs))
    return rows


def _stored_relpath_to_shasum(
    conn: sqlite3.Connection, files_root_abs: str
) -> dict[str, str]:
    """Map ``dirpath/filename`` POSIX relpath under ``files_root`` → shasum."""
    out_map: dict[str, str] = {}
    for shasum, root, dirpath, filename in conn.execute(
        "SELECT shasum, root, dirpath, filename FROM stored_files WHERE deleted = 0"
    ):
        if os.path.abspath(root) != files_root_abs:
            continue
        rel = (
            os.path.join(dirpath, filename).replace(os.sep, "/")
            if dirpath
            else filename
        )
        rel = rel.lstrip("/")
        out_map[rel] = shasum
    return out_map


def _compute_tags_by_dir(
    conn: sqlite3.Connection, files_root_abs: str
) -> dict[str, frozenset[str]]:
    """Recursive dir_key → tag set under *files_root_abs* (includes ``""`` for root)."""
    file_shasum = _stored_relpath_to_shasum(conn, files_root_abs)
    shasum_tags: dict[str, frozenset[str]] = {}

    def tags_for(shasum: str) -> frozenset[str]:
        cached = shasum_tags.get(shasum)
        if cached is None:
            cached = frozenset(get_tags(conn, shasum))
            shasum_tags[shasum] = cached
        return cached

    acc: dict[str, set[str]] = {"": set()}
    for dirpath_abs, dirnames, filenames in os.walk(files_root_abs, topdown=True):
        dirnames[:] = [d for d in dirnames if d != "_tags"]
        rel_dir = os.path.relpath(dirpath_abs, files_root_abs)
        dir_key = "" if rel_dir in (".", "") else rel_dir.replace(os.sep, "/")
        acc.setdefault(dir_key, set())
        for fn in filenames:
            rel_file = f"{dir_key}/{fn}" if dir_key else fn
            shasum = file_shasum.get(rel_file)
            if shasum is None:
                continue
            acc[dir_key] |= set(tags_for(shasum))

    ordered = sorted(
        acc.keys(),
        key=lambda k: (-(len(k.split("/")) if k else 0), k),
    )
    for dk in ordered:
        if not dk:
            continue
        acc[_parent_dir_key(dk)] |= acc[dk]

    return {dk: frozenset(ts) for dk, ts in acc.items()}


def _dir_list_path_for_key(files_root_rel: str, dir_key: str) -> str:
    """Path string for --ls output (POSIX slashes), same style as stored paths."""
    fk = dir_key.replace(os.sep, "/")
    fr = files_root_rel.replace(os.sep, "/")
    if not fk:
        return fr
    return f"{fr}/{fk}"


def _path_matches_ls_prefixes(list_path: str, prefixes: list[str]) -> bool:
    """Same inclusion rule as :func:`list_children` for stored paths."""
    if not prefixes:
        return True
    norm = list_path.replace(os.sep, "/")
    for prefix in prefixes:
        if os.path.isabs(prefix):
            continue
        p = os.path.normpath(prefix).replace(os.sep, "/")
        if norm == p or norm.startswith(p + "/"):
            return True
    return False


def handle_ls_alltags(
    conn: sqlite3.Connection, prefixes: list[str], shadir: str
) -> None:
    """Print each directory under files/ with recursively computed tag sets."""
    files_root_abs = os.path.abspath(os.path.join(os.path.dirname(shadir), "files"))
    if not os.path.isdir(files_root_abs):
        return
    files_root_rel = os.path.relpath(files_root_abs, os.getcwd())
    tags_by_dir = _compute_tags_by_dir(conn, files_root_abs)
    normalized = normalize_prefixes(prefixes)
    if prefixes and not normalized:
        return
    use_prefixes = normalized

    rows: list[tuple[str, list[str]]] = []
    for dir_key in sorted(tags_by_dir.keys()):
        list_path = _dir_list_path_for_key(files_root_rel, dir_key)
        if not _path_matches_ls_prefixes(list_path, use_prefixes):
            continue
        rows.append((list_path, sorted(tags_by_dir[dir_key])))

    if not rows:
        return
    if OUTPUT_MODE == "machine":
        _emit_ls_alltags_machine(rows)
        return
    _emit_ls_alltags_pretty(rows)


def handle_refresh_extracted_tags(conn: sqlite3.Connection, shadir: str) -> None:
    """Rebuild ``files/_tags`` with flat per-tag symlinks.

    Two passes:

    1. **Bottom-up** walk of ``files/``: build ``dir_key → frozenset(tags)`` by
       unioning each file's DB tags into its directory and propagating to
       ancestors.
    2. **Top-down** via :func:`plan_refresh_extracted_tag_mirrors`: create
       ``files/_tags/<tag>/<basename[(n)]>`` → ``<files>/<dir_key>`` symlinks.
    """
    files_root = os.path.abspath(os.path.join(os.path.dirname(shadir), "files"))
    out("refresh-extracted-tags files_root {files_root}", 1, files_root=files_root)
    if not os.path.isdir(files_root):
        raise SystemExit(
            f"refresh-extracted-tags: files root not a directory: {files_root}"
        )

    tags_root = os.path.join(files_root, "_tags")
    if os.path.lexists(tags_root):
        shutil.rmtree(tags_root)

    tags_by_dir = _compute_tags_by_dir(conn, files_root)
    rows = plan_refresh_extracted_tag_mirrors(tags_by_dir)

    for tag, name, dir_key in rows:
        link = os.path.join(files_root, "_tags", tag, name)
        target = os.path.join(files_root, *dir_key.split("/"))
        parent = os.path.dirname(link)
        os.makedirs(parent, exist_ok=True)
        if os.path.lexists(link):
            os.unlink(link)
        rel_target = os.path.relpath(target, parent)
        os.symlink(rel_target, link)
        out(
            "refresh-extracted-tags mirror {tag}/{name} -> {dir_key}",
            2,
            tag=tag,
            name=name,
            dir_key=dir_key,
        )
    os.makedirs(tags_root, exist_ok=True)
    out(
        "refresh-extracted-tags mirrors {count}",
        0,
        count=len(rows),
    )


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

    def mapper_with_progress(path: str) -> T:
        try:
            return mapper(path)
        finally:
            print(".", end="", flush=True, file=sys.stderr)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        for result in executor.map(
            mapper_with_progress, walk_files(root, shadir, skip_dotfiles)
        ):
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
                out(
                    "missing target {path} -> {target}",
                    0,
                    path=link_path,
                    target=canonical_target,
                )
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

            needs_fix = os.path.abspath(current_target) != os.path.abspath(
                canonical_target
            )
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
    alltags: bool,
) -> None:
    """Print list entries under prefixes (direct DB tags per file unless *alltags*)."""
    if alltags:
        handle_ls_alltags(conn, prefixes, shadir)
        return
    entries = list_children(
        conn, prefixes, recursive=recursive, show_deleted=show_deleted
    )
    tagged: list[tuple[str, str, list[str], bool]] = [
        (path, shasum, sorted(get_tags(conn, shasum)), deleted)
        for path, shasum, deleted in entries
    ]
    if mindup > 1 and tagged:
        grouped: dict[str, list[str]] = {}
        for path, shasum, _tags, _deleted in tagged:
            grouped.setdefault(shasum, []).append(path)
        dup_shasums = {shasum for shasum, paths in grouped.items() if len(paths) > 1}
        dir_counts: dict[str, int] = {}
        for path, shasum, _tags, _deleted in tagged:
            if shasum not in dup_shasums:
                continue
            dirpath = os.path.dirname(path)
            dir_counts[dirpath] = dir_counts.get(dirpath, 0) + 1
        allowed_dirs = {
            dirpath for dirpath, count in dir_counts.items() if count >= mindup
        }
        tagged = [row for row in tagged if os.path.dirname(row[0]) in allowed_dirs]
    if not tagged:
        return
    if OUTPUT_MODE == "machine":
        _emit_lspath_machine(tagged)
        return
    _emit_lspath_pretty(tagged, show_deleted)


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
        normalized = {
            value for value in (normalize_hash_arg(shadir, h) for h in hashes) if value
        }
        entries = [entry for entry in entries if entry[1] in normalized]
    if not entries:
        return
    grouped: dict[str, list[tuple[str, bool]]] = {}
    for path, shasum, deleted in entries:
        grouped.setdefault(shasum, []).append((path, deleted))
    if mindup > 1:
        grouped = {
            shasum: paths for shasum, paths in grouped.items() if len(paths) >= mindup
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


def delete_by_hashes(conn: sqlite3.Connection, shasums: list[str], shadir: str) -> int:
    """Mark all entries with matching shasums as deleted and return count."""
    normalized = [
        value for value in (normalize_hash_arg(shadir, h) for h in shasums) if value
    ]
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


def handle_reindex_files(
    conn: sqlite3.Connection, shadir: str, files_root: str, skip_dotfiles: bool
) -> None:
    """Rebuild/refresh DB entries from a files/ symlink tree."""
    abs_files_root = os.path.abspath(files_root)
    if not os.path.isdir(abs_files_root):
        raise SystemExit(f"--reindex-files directory not found: {files_root}")
    shadir_abs = os.path.abspath(shadir)
    store_cwd = os.getcwd()
    root_rel = os.path.relpath(abs_files_root, store_cwd)
    scanned = 0
    indexed = 0
    for dirpath, dirnames, filenames in os.walk(abs_files_root, followlinks=False):
        if skip_dotfiles:
            dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for name in filenames:
            if skip_dotfiles and name.startswith("."):
                continue
            link_path = os.path.join(dirpath, name)
            if not os.path.islink(link_path):
                continue
            scanned += 1
            target = os.path.realpath(link_path)
            digest = os.path.basename(target).lower()
            if not HASH_RE.match(digest):
                out(
                    "skip non-hash symlink {path} -> {target}",
                    1,
                    path=link_path,
                    target=target,
                )
                continue
            if not is_under_dir(target, shadir_abs):
                out(
                    "skip target outside shadir {path} -> {target}",
                    1,
                    path=link_path,
                    target=target,
                )
                continue
            if not os.path.isfile(target):
                out(
                    "skip missing target {path} -> {target}",
                    0,
                    path=link_path,
                    target=target,
                )
                continue
            rel_dir = os.path.relpath(os.path.dirname(link_path), abs_files_root)
            if rel_dir == ".":
                rel_dir = ""
            conn.execute(
                """
                INSERT OR IGNORE INTO stored_files
                (shasum, root, root_rel, dirpath, filename, deleted)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (digest, abs_files_root, root_rel, rel_dir, name),
            )
            conn.execute(
                """
                UPDATE stored_files
                SET deleted = 0
                WHERE shasum = ? AND root_rel = ? AND dirpath = ? AND filename = ?
                """,
                (digest, root_rel, rel_dir, name),
            )
            indexed += 1
    out("reindexed symlinks scanned: {count}", 0, count=scanned)
    out("reindexed entries active: {count}", 0, count=indexed)


def handle_check(args: argparse.Namespace) -> int:
    """Verify shadir discovery; optionally open DB (see ``check`` help)."""
    if args.shadir:
        shadir = expand_path(args.shadir)
    else:
        found = find_shadir(os.getcwd())
        if not found:
            print(
                "check failed: no .shadup/.shadir found from cwd",
                file=sys.stderr,
            )
            return 1
        shadir = found
    init_db = args.shadir is not None or args.db is not None
    user_db = expand_path(args.db) if args.db else None
    resolved = resolve_db_path(shadir, user_db)
    if init_db:
        with open_db(shadir, user_db) as conn:
            emit_check_report(conn, shadir, resolved)
        return 0

    if not os.path.isfile(resolved):
        print(
            f"check failed: database not found: {resolved}",
            file=sys.stderr,
        )
        return 1
    with sqlite3.connect(resolved) as conn:
        emit_check_report(conn, shadir, resolved)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``shadup [global-opts] <action> [action-opts]``."""
    args = parse_args(argv)
    global VERBOSITY
    VERBOSITY = args.v
    global OUTPUT_MODE
    OUTPUT_MODE = "pretty" if sys.stdout.isatty() else "machine"

    if args.action == "check":
        return handle_check(args)

    if args.shadir:
        shadir = expand_path(args.shadir)
    else:
        found = find_shadir(os.getcwd())
        if not found:
            raise SystemExit(
                "--shadir is required when no .shadup/.shadir directory is found"
            )
        shadir = found
    # The cwd-inside-shadir guard is only meaningful for operations that walk
    # the user's working tree (``store``) or write files back into it
    # (``extract``). Read-only / DB-only actions may run from inside shadir.
    if args.action in ("store", "extract"):
        cwd = os.path.abspath(os.curdir)
        if is_under_dir(cwd, shadir):
            raise SystemExit(
                f"cwd must not be inside shadir for {args.action}: "
                f"cwd={cwd} shadir={shadir}"
            )

    db_path = expand_path(args.db) if args.db else None
    with open_db(shadir, db_path) as conn:
        return dispatch_action(conn, shadir, args)


def dispatch_action(
    conn: sqlite3.Connection, shadir: str, args: argparse.Namespace
) -> int:
    """Dispatch *args.action* to the corresponding ``handle_*`` function."""
    action = args.action
    if action == "store":
        for root in args.dirs:
            out("store {root}", 1, root=root)
            handle_store(conn, expand_path(root), shadir, args.skip_dotfiles)
        return 0
    if action == "extract":
        for prefix in args.prefixes:
            out("extract {prefix}", 1, prefix=prefix)
        handle_extract(conn, args.prefixes, shadir, show_deleted=args.show_deleted)
        return 0
    if action in ("ls", "lspath"):
        for prefix in args.prefixes:
            out("lspath {prefix}", 1, prefix=prefix)
        handle_ls(
            conn,
            args.prefixes,
            shadir,
            recursive=False,
            show_deleted=args.show_deleted,
            mindup=args.mindup,
            alltags=args.alltags,
        )
        return 0
    if action == "lshash":
        for shasum in args.hashes:
            out("lshash {shasum}", 1, shasum=shasum)
        handle_lshash(
            conn,
            args.hashes,
            shadir,
            show_deleted=args.show_deleted,
            mindup=args.mindup,
        )
        return 0
    if action == "rmpath":
        for prefix in args.prefixes:
            out("rmpath {prefix}", 1, prefix=prefix)
        handle_del(
            conn,
            args.prefixes,
            shadir,
            recursive=args.recursive,
            show_deleted=args.show_deleted,
        )
        return 0
    if action == "rmhash":
        for shasum in args.hashes:
            out("rmhash {shasum}", 1, shasum=shasum)
        handle_rmhash(conn, args.hashes, shadir)
        return 0
    if action == "dedup":
        for root in args.dirs:
            out("dedup {root}", 1, root=root)
            handle_dedup(conn, expand_path(root), shadir, args.skip_dotfiles)
        return 0
    if action == "fixlinks":
        for root in args.dirs:
            out("fixlinks {root}", 1, root=root)
        handle_fixlinks(
            conn,
            [expand_path(root) for root in args.dirs],
            shadir,
            args.skip_dotfiles,
            recursive=args.recursive,
            paranoia=args.paranoia,
        )
        return 0
    if action == "reindex-files":
        if args.dir is None:
            files_root = os.path.join(os.path.dirname(shadir), "files")
        else:
            files_root = expand_path(args.dir)
        out("reindex-files {files_root}", 1, files_root=files_root)
        handle_reindex_files(conn, shadir, files_root, args.skip_dotfiles)
        return 0
    if action == "tag-add":
        handle_tag_add(conn, shadir, args.path, args.tags)
        return 0
    if action == "tag-rm":
        handle_tag_rm(conn, shadir, args.path, args.tags)
        return 0
    if action == "refresh-extracted-tags":
        out("refresh-extracted-tags", 1)
        handle_refresh_extracted_tags(conn, shadir)
        return 0
    raise SystemExit(f"unknown action: {action}")


if __name__ == "__main__":
    raise SystemExit(main())

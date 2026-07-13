"""SQLite storage for branch-bound todo tickets under a single todo directory."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import struct
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

JsonDict = Dict[str, Any]

HOME_TODO_DIR_NAME: str = ".todo"
SCHEMA_VERSION: int = 5
_RESOLVED_TODO_DIR: Optional[Path] = None


def repo_identity_from_url(url: str) -> Optional[str]:
    """Canonical ``host/owner/name`` identity from a git remote URL, or None.

    Normalizes the common shapes (``https://host/o/n(.git)``,
    ``git@host:o/n(.git)``, ``ssh://git@host/o/n``) to one stable string so the
    same repo resolves identically across machines, users, and worktrees. Lives
    here (not in todo.py) so the schema migration can reuse it.
    """
    u = url.strip().removesuffix(".git")
    if not u:
        return None
    match = re.match(r"\A[\w.+-]+@([^:/]+):(.+)\Z", u)  # scp-like: git@host:owner/name
    if not match:
        match = re.match(r"\A[a-zA-Z][\w+.-]*://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+)\Z", u)
    if not match:
        return None
    host, path = match.group(1), match.group(2).strip("/")
    if not path:
        return None
    return f"{host.lower()}/{path}"


class TodoDbError(Exception):
    """User-facing todo database error."""


def reset_todo_dir() -> None:
    """Clear cached todo directory (tests only)."""
    global _RESOLVED_TODO_DIR
    _RESOLVED_TODO_DIR = None


def main_checkout_root(start: Optional[Path] = None) -> Optional[Path]:
    """Return the repo's MAIN checkout root for *start*, or None when not in a repo.

    Anchored on the repo's primary working tree, NOT the current linked worktree,
    so every worktree of a repo shares ONE todo store in the core checkout.
    ``git worktree list`` always lists the main worktree first. (Bare / no-checkout
    hosting is out of scope.)
    """
    cwd: Path = start or Path.cwd()
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree ") :].strip())
    return None


def _home_todo_dir() -> Path:
    return Path.home() / HOME_TODO_DIR_NAME


def _todo_dir_candidates(git_root: Optional[Path]) -> List[Path]:
    """Ordered todo directory candidates for one CLI invocation."""
    candidates: List[Path] = []
    todo_dir_env = os.environ.get("TODO_DIR")
    if todo_dir_env:
        candidates.append(Path(todo_dir_env))
    if git_root is not None:
        candidates.append(git_root / HOME_TODO_DIR_NAME)
    candidates.append(_home_todo_dir())
    return candidates


def _default_todo_dir(git_root: Optional[Path]) -> Path:
    """Directory to create when no sqlite.db exists in any candidate."""
    todo_dir_env = os.environ.get("TODO_DIR")
    if todo_dir_env:
        return Path(todo_dir_env)
    if git_root is not None:
        return git_root / HOME_TODO_DIR_NAME
    return _home_todo_dir()


def _candidate_is_populated(candidate: Path) -> bool:
    """True when *candidate* already holds a todo store worth selecting.

    A directory with ``sqlite.db`` (sqlite backend) or ``config.json`` (explicit
    backend choice, e.g. file:// storage) counts. An empty ``.todo`` does not,
    so search can fall through to a home store that still has a db.
    """
    return (candidate / "sqlite.db").is_file() or (candidate / "config.json").is_file()


def resolve_todo_dir(git_root: Optional[Path] = None) -> Path:
    """Resolve the todo directory once per process.

    Search order: ``$TODO_DIR``, ``<main-checkout-root>/.todo/``, ``$HOME/.todo/``.
    The repo anchor is the MAIN checkout root (not the current worktree), so all
    worktrees of a repo share one store. The first candidate that already holds
    a store (``sqlite.db`` or ``config.json``) wins; otherwise the default create
    location is the first entry in that list that applies (``$TODO_DIR``, else
    main-checkout ``.todo``, else home). All paths (db, worktrees, storage)
    live under the chosen directory for the rest of the call.
    """
    global _RESOLVED_TODO_DIR
    if _RESOLVED_TODO_DIR is not None:
        return _RESOLVED_TODO_DIR
    root = git_root if git_root is not None else main_checkout_root()
    for candidate in _todo_dir_candidates(root):
        if _candidate_is_populated(candidate):
            _RESOLVED_TODO_DIR = candidate.resolve()
            return _RESOLVED_TODO_DIR
    _RESOLVED_TODO_DIR = _default_todo_dir(root).resolve()
    return _RESOLVED_TODO_DIR


def todo_dir() -> Path:
    """Return the resolved todo directory for this process."""
    return resolve_todo_dir()


def db_path() -> Path:
    """Return path to the todo sqlite database."""
    return todo_dir() / "sqlite.db"


def worktrees_dir() -> Path:
    """Return worktree root under the resolved todo directory."""
    return todo_dir() / "worktrees"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connection(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """Open a sqlite connection with migrations applied."""
    db = path or db_path()
    conn = _connect(db)
    try:
        migrate(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate(conn: sqlite3.Connection) -> None:
    """Apply schema migrations idempotently."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
    )
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    current = int(row["version"]) if row else 0
    if current < 1:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id TEXT PRIMARY KEY,
                repo_path TEXT NOT NULL,
                branch TEXT NOT NULL,
                data TEXT NOT NULL,
                update_dt TEXT NOT NULL,
                UNIQUE(repo_path, branch)
            );
            CREATE INDEX IF NOT EXISTS idx_tickets_repo_branch
                ON tickets(repo_path, branch);
            CREATE INDEX IF NOT EXISTS idx_tickets_id_prefix
                ON tickets(substr(id, 1, 8));
            CREATE TABLE IF NOT EXISTS embeddings (
                ticket_id TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                field_path TEXT NOT NULL,
                embedder TEXT NOT NULL,
                vector BLOB NOT NULL,
                PRIMARY KEY (ticket_id, field_path, embedder)
            );
            """
        )
    if current < 2:
        conn.execute("DROP TABLE IF EXISTS catalog")
    if current < 3:
        _normalize_repo_identities(conn)
    if current < 4:
        # Per-TODO advisory locks: one row per held ticket, carrying the holder
        # pid and an expiry so a crashed holder's lock becomes stealable.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS locks (
                ticket_id TEXT PRIMARY KEY,
                pid INTEGER NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )
    if current < 5:
        # Soft-delete tombstone: a row moved here (verbatim, minus the embeddings
        # that cascade away) is removed from `tickets` but retained for manual
        # recovery. No recovery command exists yet -- restore by hand if needed.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS deleted_tickets (
                id TEXT PRIMARY KEY,
                repo_path TEXT NOT NULL,
                branch TEXT NOT NULL,
                data TEXT NOT NULL,
                update_dt TEXT NOT NULL
            )
            """
        )
    if current < SCHEMA_VERSION:
        if row is None:
            conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
        else:
            conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))


def _normalize_repo_identities(conn: sqlite3.Connection) -> None:
    """Rewrite each ticket's ``repo_path`` from an absolute path to the stable
    ``host/owner/name`` identity, derived from the ticket's own
    ``Scope.git_url``. Path-based keys were machine/user/worktree specific and
    broke repo-scoped lookups when the db moved; the remote URL is stable. Rows
    without a usable ``git_url`` (e.g. local-only repos) are left untouched.
    """
    for row in conn.execute("SELECT id, repo_path, data FROM tickets").fetchall():
        try:
            data = json.loads(str(row["data"]))
        except (json.JSONDecodeError, TypeError):
            continue
        scope = data.get("Scope") if isinstance(data, dict) else None
        url = scope.get("git_url") if isinstance(scope, dict) else None
        identity = repo_identity_from_url(url) if isinstance(url, str) and url else None
        if identity and identity != row["repo_path"]:
            conn.execute(
                "UPDATE tickets SET repo_path = ? WHERE id = ?", (identity, row["id"])
            )


def pack_vector(values: Sequence[float]) -> bytes:
    """Pack floats into a little-endian blob."""
    return struct.pack(f"<{len(values)}f", *values)


def unpack_vector(blob: bytes) -> List[float]:
    """Unpack a little-endian float blob."""
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


def put_ticket(conn: sqlite3.Connection, repo_path: str, branch: str, ticket: JsonDict) -> None:
    """Insert or replace a ticket row."""
    ticket_id = str(ticket["Id"])
    update_dt = str(ticket.get("update_dt", ""))
    payload = json.dumps(ticket, sort_keys=True)
    conn.execute(
        """
        INSERT INTO tickets(id, repo_path, branch, data, update_dt)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            repo_path=excluded.repo_path,
            branch=excluded.branch,
            data=excluded.data,
            update_dt=excluded.update_dt
        """,
        (ticket_id, repo_path, branch, payload, update_dt),
    )


def hard_delete_ticket(conn: sqlite3.Connection, ticket_id: str) -> bool:
    """Permanently delete a ticket row; its embeddings cascade away. True if a
    row was removed."""
    cur = conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
    return cur.rowcount > 0


def soft_delete_ticket(conn: sqlite3.Connection, ticket_id: str) -> bool:
    """Move a ticket row to `deleted_tickets` (verbatim) and drop it from
    `tickets`; its embeddings cascade away. True if a row was moved."""
    conn.execute(
        """
        INSERT OR REPLACE INTO deleted_tickets(id, repo_path, branch, data, update_dt)
        SELECT id, repo_path, branch, data, update_dt FROM tickets WHERE id = ?
        """,
        (ticket_id,),
    )
    cur = conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
    return cur.rowcount > 0


def get_ticket_by_repo_branch(
    conn: sqlite3.Connection, repo_path: str, branch: str
) -> Optional[JsonDict]:
    """Load a ticket by repo path and branch name."""
    row = conn.execute(
        "SELECT data FROM tickets WHERE repo_path = ? AND branch = ?",
        (repo_path, branch),
    ).fetchone()
    if row is None:
        return None
    parsed: Any = json.loads(str(row["data"]))
    if not isinstance(parsed, dict):
        return None
    return parsed


def find_tickets_by_id_prefix(conn: sqlite3.Connection, query: str) -> List[Tuple[str, str, JsonDict]]:
    """Return (repo_path, branch, ticket) for id prefix matches."""
    rows = conn.execute("SELECT repo_path, branch, data FROM tickets").fetchall()
    matches: List[Tuple[str, str, JsonDict]] = []
    for row in rows:
        parsed: Any = json.loads(str(row["data"]))
        if not isinstance(parsed, dict):
            continue
        ticket_id = str(parsed.get("Id", ""))
        if not ticket_id:
            continue
        if ticket_id == query or ticket_id.startswith(query):
            matches.append((str(row["repo_path"]), str(row["branch"]), parsed))
        elif len(query) >= 4 and ticket_id.startswith(query):
            matches.append((str(row["repo_path"]), str(row["branch"]), parsed))
    return matches


def list_tickets(conn: sqlite3.Connection) -> List[JsonDict]:
    """Return every known ticket as {id, repo, branch, summary, update_dt}, insertion order."""
    rows = conn.execute(
        "SELECT id, repo_path, branch, data, update_dt FROM tickets ORDER BY rowid"
    ).fetchall()
    result: List[JsonDict] = []
    for row in rows:
        parsed: Any = json.loads(str(row["data"]))
        summary_obj = parsed.get("Summary") if isinstance(parsed, dict) else None
        summary = summary_obj.get("raw", "") if isinstance(summary_obj, dict) else ""
        result.append(
            {
                "id": str(row["id"]),
                "repo": str(row["repo_path"]),
                "branch": str(row["branch"]),
                "summary": summary,
                "update_dt": str(row["update_dt"]),
            }
        )
    return result


def put_embedding(
    conn: sqlite3.Connection,
    ticket_id: str,
    field_path: str,
    embedder: str,
    vector: Sequence[float],
) -> None:
    """Store or replace an embedding vector."""
    conn.execute(
        """
        INSERT INTO embeddings(ticket_id, field_path, embedder, vector)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(ticket_id, field_path, embedder) DO UPDATE SET
            vector=excluded.vector
        """,
        (ticket_id, field_path, embedder, pack_vector(vector)),
    )


def clear_embeddings(
    conn: sqlite3.Connection, ticket_id: str, field_path: Optional[str] = None
) -> None:
    """Delete stored vectors for a ticket, or just one field when given."""
    if field_path is None:
        conn.execute("DELETE FROM embeddings WHERE ticket_id = ?", (ticket_id,))
    else:
        conn.execute(
            "DELETE FROM embeddings WHERE ticket_id = ? AND field_path = ?",
            (ticket_id, field_path),
        )


def existing_embeddings(conn: sqlite3.Connection, ticket_id: str) -> set:
    """Return the set of ``(field_path, embedder)`` vectors stored for a ticket."""
    rows = conn.execute(
        "SELECT field_path, embedder FROM embeddings WHERE ticket_id = ?",
        (ticket_id,),
    ).fetchall()
    return {(str(row["field_path"]), str(row["embedder"])) for row in rows}


def all_embeddings(
    conn: sqlite3.Connection, embedder: str
) -> List[Tuple[str, str, List[float]]]:
    """Return (ticket_id, field_path, vector) for an embedder."""
    rows = conn.execute(
        "SELECT ticket_id, field_path, vector FROM embeddings WHERE embedder = ?",
        (embedder,),
    ).fetchall()
    result: List[Tuple[str, str, List[float]]] = []
    for row in rows:
        result.append((str(row["ticket_id"]), str(row["field_path"]), unpack_vector(bytes(row["vector"]))))
    return result


def ticket_ids_for_repo(conn: sqlite3.Connection, repo_path: str) -> List[str]:
    """Return all ticket ids registered for a repo."""
    rows = conn.execute(
        "SELECT id FROM tickets WHERE repo_path = ?", (repo_path,)
    ).fetchall()
    return [str(row["id"]) for row in rows]

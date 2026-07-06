"""SQLite storage for branch-bound todo tickets under a single todo directory."""

from __future__ import annotations

import json
import os
import sqlite3
import struct
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

JsonDict = Dict[str, Any]

HOME_TODO_DIR_NAME: str = ".todo"
SCHEMA_VERSION: int = 2
_RESOLVED_TODO_DIR: Optional[Path] = None


class TodoDbError(Exception):
    """User-facing todo database error."""


def reset_todo_dir() -> None:
    """Clear cached todo directory (tests only)."""
    global _RESOLVED_TODO_DIR
    _RESOLVED_TODO_DIR = None


def _optional_git_root(start: Optional[Path] = None) -> Optional[Path]:
    """Return git toplevel for *start*, or None when not in a repo."""
    cwd: Path = start or Path.cwd()
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


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


def resolve_todo_dir(git_root: Optional[Path] = None) -> Path:
    """Resolve the todo directory once per process.

    Search order: ``$TODO_DIR``, ``$(gitroot)/.todo/``, ``$HOME/.todo/``.
    The first candidate containing ``sqlite.db`` wins; otherwise the default
    create location is the first entry in that list that applies (``$TODO_DIR``,
    else repo-local ``.todo``, else home). All paths (db, worktrees)
    live under the chosen directory for the rest of the call.
    """
    global _RESOLVED_TODO_DIR
    if _RESOLVED_TODO_DIR is not None:
        return _RESOLVED_TODO_DIR
    root = git_root if git_root is not None else _optional_git_root()
    for candidate in _todo_dir_candidates(root):
        db_file = candidate / "sqlite.db"
        if db_file.is_file():
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
    if current < SCHEMA_VERSION:
        if row is None:
            conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
        else:
            conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))


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

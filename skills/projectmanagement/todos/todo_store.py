"""Data-access layer for todo tickets: a swappable store in front of storage.

Ticket persistence goes through a `TodoStore` so the backend can be retargeted.
The backend is chosen **only** by ``<todo_dir>/config.json`` via the
``todo_storage`` DSN:

  {"todo_storage": "sqlite://$TODOBASEDIR/sqlite.db"}  -> SqliteTodoStore
  {"todo_storage": "file://$TODOBASEDIR/storage"}      -> JsonDirTodoStore

The path part is shell-expanded: ``$TODOBASEDIR`` / ``${TODOBASEDIR}`` resolve
to ``todo basedir`` (the resolved ``.todo`` dir), ``~`` and other ``$VAR`` are
expanded too.

If ``config.json`` is missing, one is created from the on-disk layout (first
match wins): ``sqlite.db`` -> sqlite DSN, ``storage/`` -> file DSN, else the
default sqlite DSN. Legacy flat keys (``store`` / ``tickets_dir``) are migrated
into a DSN when ``todo_storage`` is absent so every basedir ends with an
explicit ``todo_storage``.

Each todo is one ``<ID>.json`` file on the JSON backend. Embeddings live inside
the ticket JSON (stamped per field), so both backends carry them. The sqlite
``embeddings`` table is only a derived search index -- ``has_vector_index`` marks
the store that maintains it (sqlite); the JSON backend reports False, so the
write path skips the index mirror.

Concurrency: each store exposes ``lock(ticket_id)``, a per-TODO advisory lock
(sqlite ``locks`` row or a ``<ID>.lock`` sidecar file), carrying the holder pid
and an expiry so a crashed holder never blocks forever (stealable after
``lock_ttl``). Callers hold it only around the write of a single ticket, so at
most one lock is held per process at a time -- lock-ordering deadlock is
therefore impossible. ``lock`` polls for ``lock_grace`` seconds, then raises
``LockTimeout``. ``force_unlock_all`` (used by ``doctor``) clears every lock.
Both timings come from ``config.json`` (``lock_grace`` / ``lock_ttl``).
"""

from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import todo_db

JsonDict = Dict[str, Any]

DEFAULT_SQLITE_DSN = "sqlite://$TODOBASEDIR/sqlite.db"
DEFAULT_STORAGE_DSN = "file://$TODOBASEDIR/storage"

# Advisory-lock timings (seconds), overridable via config.json.
DEFAULT_LOCK_GRACE = 30.0  # how long an acquirer polls before giving up (ERETRY)
DEFAULT_LOCK_TTL = 15.0  # how long a held lock stays valid before it is stealable
_POLL_INTERVAL = 0.1

# Ticket JSON field name -> embeddings-table field_path (shared by both backends).
_EMBED_FIELD_PATHS: Tuple[Tuple[str, str], ...] = (
    ("Summary", "Summary.raw"),
    ("Body", "Body.raw"),
)


def _inline_embeddings(todo: JsonDict) -> List[Tuple[str, str, List[List[float]]]]:
    """Collect ``(field_path, embedder, chunks)`` stamped into a ticket's JSON."""
    out: List[Tuple[str, str, List[List[float]]]] = []
    for field_name, field_path in _EMBED_FIELD_PATHS:
        obj = todo.get(field_name)
        if not isinstance(obj, dict):
            continue
        for key, val in obj.items():
            if key == "raw" or not isinstance(val, list) or not val:
                continue
            if isinstance(val[0], list):
                out.append((field_path, str(key), val))  # type: ignore[arg-type]
    return out


def _repo_from_todo(todo: JsonDict) -> str:
    scope = todo.get("Scope")
    url = scope.get("git_url") if isinstance(scope, dict) else None
    if isinstance(url, str) and url:
        return todo_db.repo_identity_from_url(url) or ""
    return ""


class TodoStoreError(Exception):
    """Store configuration error (e.g. a malformed todo_storage DSN)."""


class LockTimeout(Exception):
    """A per-TODO lock could not be acquired within the grace period."""


class TodoStore(ABC):
    """Abstract ticket store. Repo/branch identify a ticket; Id is its key."""

    # Whether this store maintains a derived embeddings search index (sqlite).
    # Vectors themselves live in the ticket JSON on every backend.
    has_vector_index: bool = False

    def __init__(self, *, grace: float = DEFAULT_LOCK_GRACE, ttl: float = DEFAULT_LOCK_TTL) -> None:
        self._grace = grace
        self._ttl = ttl

    @abstractmethod
    def get(self, repo: str, branch: str) -> Optional[JsonDict]:
        """Return the ticket for (repo, branch), or None."""

    @abstractmethod
    def put(self, repo: str, branch: str, todo: JsonDict) -> None:
        """Insert or replace a ticket."""

    @abstractmethod
    def find_by_id_prefix(self, query: str) -> List[Tuple[str, str, JsonDict]]:
        """Return ``(repo, branch, todo)`` for every ticket whose Id starts with *query*."""

    @abstractmethod
    def list_all(self) -> List[JsonDict]:
        """Return every ticket in the store, unscoped."""

    @abstractmethod
    def list_located(self) -> List[Tuple[str, str, JsonDict]]:
        """Return ``(repo, branch, todo)`` for every ticket in the store."""

    @abstractmethod
    def delete(self, todo: JsonDict, *, hard: bool) -> bool:
        """Remove *todo* from the store. ``hard`` permanently deletes it; a soft
        delete keeps a recoverable tombstone (no recovery tool exists yet).
        Returns True if the todo was present and removed."""

    # -- embeddings (ticket JSON on every backend; derived index when available) --

    @abstractmethod
    def embeddings_for_ticket(
        self, ticket_id: str
    ) -> List[Tuple[str, str, List[List[float]]]]:
        """Return ``(field_path, embedder, chunks)`` for one ticket."""

    @abstractmethod
    def all_embeddings(
        self, embedder: str
    ) -> List[Tuple[str, str, List[List[float]]]]:
        """Return ``(ticket_id, field_path, chunks)`` for one embedder across tickets."""

    @abstractmethod
    def put_embedding(
        self,
        ticket_id: str,
        field_path: str,
        embedder: str,
        vectors: List[List[float]],
    ) -> None:
        """Persist a vector for the derived index (no-op when there is no index)."""

    @abstractmethod
    def clear_embeddings(self, ticket_id: str, field_path: Optional[str] = None) -> None:
        """Clear derived-index vectors for a ticket (no-op when there is no index)."""

    # -- per-TODO advisory locking -----------------------------------------

    @abstractmethod
    def _try_acquire(self, ticket_id: str, ttl: float) -> bool:
        """Atomically claim *ticket_id* (stealing an expired lock); True on success."""

    @abstractmethod
    def _release(self, ticket_id: str) -> None:
        """Release *ticket_id* if this process still holds it."""

    @abstractmethod
    def force_unlock_all(self) -> int:
        """Drop every lock unconditionally (recovery); return how many were cleared."""

    @contextmanager
    def lock(
        self, ticket_id: str, *, grace: Optional[float] = None, ttl: Optional[float] = None
    ) -> Iterator[None]:
        """Hold an exclusive lock on one TODO for the enclosed write.

        Polls up to *grace* seconds, stealing a lock whose holder died (expired
        past *ttl*); raises ``LockTimeout`` if it cannot acquire in time. Hold
        this only around the write of a single ticket -- never nest it around
        another ticket's write -- so no more than one lock is ever held at a
        time and lock ordering can never deadlock.
        """
        grace = self._grace if grace is None else grace
        ttl = self._ttl if ttl is None else ttl
        deadline = time.monotonic() + grace
        while not self._try_acquire(ticket_id, ttl):
            if time.monotonic() >= deadline:
                raise LockTimeout(
                    f"could not acquire lock for {ticket_id[:8]} within {grace:g}s"
                )
            time.sleep(_POLL_INTERVAL)
        try:
            yield
        finally:
            self._release(ticket_id)


class SqliteTodoStore(TodoStore):
    """Default backend: delegates to the todo_db sqlite storage."""

    has_vector_index = True

    def __init__(self, db_path: Optional[Path] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # None -> todo_db resolves the default db_path(); a DSN supplies an explicit file.
        self.db_path = db_path

    def get(self, repo: str, branch: str) -> Optional[JsonDict]:
        with todo_db.connection(self.db_path) as conn:
            return todo_db.get_ticket_by_repo_branch(conn, repo, branch)

    def put(self, repo: str, branch: str, todo: JsonDict) -> None:
        with todo_db.connection(self.db_path) as conn:
            todo_db.put_ticket(conn, repo, branch, todo)

    def find_by_id_prefix(self, query: str) -> List[Tuple[str, str, JsonDict]]:
        with todo_db.connection(self.db_path) as conn:
            return todo_db.find_tickets_by_id_prefix(conn, query)

    def list_all(self) -> List[JsonDict]:
        return [todo for _repo, _branch, todo in self.list_located()]

    def list_located(self) -> List[Tuple[str, str, JsonDict]]:
        with todo_db.connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT repo_path, branch, data FROM tickets ORDER BY rowid"
            ).fetchall()
        out: List[Tuple[str, str, JsonDict]] = []
        for row in rows:
            parsed = json.loads(str(row["data"]))
            if isinstance(parsed, dict) and parsed.get("Id"):
                out.append((str(row["repo_path"]), str(row["branch"]), parsed))
        return out

    def delete(self, todo: JsonDict, *, hard: bool) -> bool:
        ticket_id = str(todo["Id"])
        with todo_db.connection(self.db_path) as conn:
            if hard:
                return todo_db.hard_delete_ticket(conn, ticket_id)
            return todo_db.soft_delete_ticket(conn, ticket_id)

    def embeddings_for_ticket(
        self, ticket_id: str
    ) -> List[Tuple[str, str, List[List[float]]]]:
        with todo_db.connection(self.db_path) as conn:
            return todo_db.embeddings_for_ticket(conn, ticket_id)

    def all_embeddings(
        self, embedder: str
    ) -> List[Tuple[str, str, List[List[float]]]]:
        with todo_db.connection(self.db_path) as conn:
            return todo_db.all_embeddings(conn, embedder)

    def put_embedding(
        self,
        ticket_id: str,
        field_path: str,
        embedder: str,
        vectors: List[List[float]],
    ) -> None:
        with todo_db.connection(self.db_path) as conn:
            todo_db.put_embedding(conn, ticket_id, field_path, embedder, vectors)

    def clear_embeddings(self, ticket_id: str, field_path: Optional[str] = None) -> None:
        with todo_db.connection(self.db_path) as conn:
            todo_db.clear_embeddings(conn, ticket_id, field_path)

    def _try_acquire(self, ticket_id: str, ttl: float) -> bool:
        now = time.time()
        expires = now + ttl
        pid = os.getpid()
        with todo_db.connection(self.db_path) as conn:
            # Atomic: insert if absent, else steal only when the current lock has
            # expired. The statement runs in one write transaction, so no other
            # process interleaves between the upsert and the ownership check.
            conn.execute(
                """
                INSERT INTO locks(ticket_id, pid, expires_at) VALUES (?, ?, ?)
                ON CONFLICT(ticket_id) DO UPDATE SET pid=excluded.pid, expires_at=excluded.expires_at
                  WHERE locks.expires_at <= ?
                """,
                (ticket_id, pid, expires, now),
            )
            row = conn.execute(
                "SELECT pid FROM locks WHERE ticket_id = ?", (ticket_id,)
            ).fetchone()
        return row is not None and int(row["pid"]) == pid

    def _release(self, ticket_id: str) -> None:
        with todo_db.connection(self.db_path) as conn:
            conn.execute(
                "DELETE FROM locks WHERE ticket_id = ? AND pid = ?", (ticket_id, os.getpid())
            )

    def force_unlock_all(self) -> int:
        with todo_db.connection(self.db_path) as conn:
            count = int(conn.execute("SELECT COUNT(*) FROM locks").fetchone()[0])
            conn.execute("DELETE FROM locks")
            return count


class JsonDirTodoStore(TodoStore):
    """A directory of ``<ID>.json`` files, one per todo (embeddings included)."""

    has_vector_index = False

    def __init__(self, directory: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, ticket_id: str) -> Path:
        return self.dir / f"{ticket_id}.json"

    def _load(self, path: Path) -> Optional[JsonDict]:
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) and parsed.get("Id") else None

    def _all(self) -> List[JsonDict]:
        return [t for t in (self._load(p) for p in sorted(self.dir.glob("*.json"))) if t]

    def get(self, repo: str, branch: str) -> Optional[JsonDict]:
        for todo in self._all():
            if str(todo.get("Branch") or "") == branch:
                return todo
        return None

    def put(self, repo: str, branch: str, todo: JsonDict) -> None:
        ticket_id = str(todo["Id"])
        path = self._path(ticket_id)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(todo, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)

    def find_by_id_prefix(self, query: str) -> List[Tuple[str, str, JsonDict]]:
        out: List[Tuple[str, str, JsonDict]] = []
        for todo in self._all():
            if str(todo.get("Id") or "").startswith(query):
                out.append((_repo_from_todo(todo), str(todo.get("Branch") or ""), todo))
        return out

    def list_all(self) -> List[JsonDict]:
        return self._all()

    def list_located(self) -> List[Tuple[str, str, JsonDict]]:
        return [
            (_repo_from_todo(todo), str(todo.get("Branch") or ""), todo)
            for todo in self._all()
        ]

    def delete(self, todo: JsonDict, *, hard: bool) -> bool:
        path = self._path(str(todo["Id"]))
        if not path.exists():
            return False
        if hard:
            path.unlink()
        else:
            # soft delete: <id>.json -> <id>.deleted (kept for manual recovery)
            path.replace(path.with_suffix(".deleted"))
        return True

    def embeddings_for_ticket(
        self, ticket_id: str
    ) -> List[Tuple[str, str, List[List[float]]]]:
        todo = self._load(self._path(ticket_id))
        return _inline_embeddings(todo) if todo else []

    def all_embeddings(
        self, embedder: str
    ) -> List[Tuple[str, str, List[List[float]]]]:
        out: List[Tuple[str, str, List[List[float]]]] = []
        for todo in self._all():
            tid = str(todo.get("Id") or "")
            if not tid:
                continue
            for field_path, name, chunks in _inline_embeddings(todo):
                if name == embedder:
                    out.append((tid, field_path, chunks))
        return out

    def put_embedding(
        self,
        ticket_id: str,
        field_path: str,
        embedder: str,
        vectors: List[List[float]],
    ) -> None:
        # Vectors live in the ticket JSON and are written by put(); no derived index.
        return None

    def clear_embeddings(self, ticket_id: str, field_path: Optional[str] = None) -> None:
        return None

    def _lock_path(self, ticket_id: str) -> Path:
        return self.dir / f"{ticket_id}.lock"

    def _lock_expired(self, path: Path, now: float) -> bool:
        try:
            expires = float(path.read_text(encoding="ascii").split()[1])
        except (OSError, ValueError, IndexError):
            return True  # unreadable/garbage lock file -> treat as stale
        return now >= expires

    def _try_acquire(self, ticket_id: str, ttl: float) -> bool:
        now = time.time()
        path = self._lock_path(ticket_id)
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            # Only remove a lock whose holder has expired; the next poll then
            # races for it via O_EXCL, so a single winner is chosen atomically.
            if self._lock_expired(path, now):
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
            return False
        try:
            os.write(fd, f"{os.getpid()} {now + ttl}".encode("ascii"))
        finally:
            os.close(fd)
        return True

    def _release(self, ticket_id: str) -> None:
        path = self._lock_path(ticket_id)
        try:
            holder = int(path.read_text(encoding="ascii").split()[0])
        except (OSError, ValueError, IndexError):
            return
        if holder == os.getpid():
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def force_unlock_all(self) -> int:
        count = 0
        for path in self.dir.glob("*.lock"):
            try:
                path.unlink()
                count += 1
            except FileNotFoundError:
                pass
        return count


def _load_config(base: Path) -> JsonDict:
    """Read ``<todo_dir>/config.json``; empty dict when absent or unreadable."""
    try:
        parsed = json.loads((base / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_config(base: Path, config: JsonDict) -> None:
    """Persist ``config.json`` under *base* (creates the directory if needed)."""
    base.mkdir(parents=True, exist_ok=True)
    (base / "config.json").write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _float_config(config: JsonDict, key: str, default: float) -> float:
    """Read a float config value, falling back to *default* on absence/garbage."""
    try:
        return float(config[key])
    except (KeyError, TypeError, ValueError):
        return default


def _expand_todo_base(path: str, base: Path) -> str:
    """Expand ``$TODOBASEDIR`` (the resolved todo dir), ``~`` and other env vars."""
    base_s = str(base)
    substituted = path.replace("${TODOBASEDIR}", base_s).replace("$TODOBASEDIR", base_s)
    return os.path.expanduser(os.path.expandvars(substituted))


def _infer_storage_dsn(base: Path, config: JsonDict) -> str:
    """Resolve a todo_storage DSN from config keys or on-disk layout."""
    dsn = config.get("todo_storage")
    if isinstance(dsn, str) and dsn.strip():
        return dsn.strip()
    # Legacy flat keys (promoted to a DSN the next time config is written).
    kind = str(config.get("store", "")).strip().lower()
    if kind == "json":
        tickets_dir = config.get("tickets_dir")
        if isinstance(tickets_dir, str) and tickets_dir.strip():
            return f"file://{tickets_dir.strip()}"
        return "file://$TODOBASEDIR/tickets"
    if kind == "sqlite":
        return DEFAULT_SQLITE_DSN
    # Layout detection when config is absent or has no usable storage key.
    if (base / "sqlite.db").is_file():
        return DEFAULT_SQLITE_DSN
    if (base / "storage").is_dir():
        return DEFAULT_STORAGE_DSN
    return DEFAULT_SQLITE_DSN


def _store_from_dsn(dsn: str, base: Path, *, grace: float, ttl: float) -> TodoStore:
    """Build a store from a ``scheme://path`` todo_storage DSN."""
    scheme, sep, rest = dsn.partition("://")
    if not sep:
        raise TodoStoreError(f"invalid todo_storage DSN (expected scheme://path): {dsn!r}")
    scheme = scheme.strip().lower()
    target = Path(_expand_todo_base(rest, base))
    if scheme == "sqlite":
        return SqliteTodoStore(db_path=target, grace=grace, ttl=ttl)
    if scheme == "file":
        return JsonDirTodoStore(target, grace=grace, ttl=ttl)
    raise TodoStoreError(f"unknown todo_storage scheme {scheme!r} (want sqlite:// or file://)")


_STORE: Optional[TodoStore] = None


def get_store() -> TodoStore:
    """Return the process-wide ticket store, chosen only from ``config.json``.

    Missing ``todo_storage`` is filled in (and written) from legacy keys or the
    on-disk layout (``sqlite.db``, else ``storage/``, else sqlite default).
    """
    global _STORE
    if _STORE is not None:
        return _STORE
    base = todo_db.todo_dir()
    config = _load_config(base)
    dsn = _infer_storage_dsn(base, config)
    if config.get("todo_storage") != dsn:
        # Config missing or lacked an explicit DSN -- persist the resolved one.
        written = {k: v for k, v in config.items() if k not in ("store", "tickets_dir")}
        written["todo_storage"] = dsn
        _write_config(base, written)
        config = written
    grace = _float_config(config, "lock_grace", DEFAULT_LOCK_GRACE)
    ttl = _float_config(config, "lock_ttl", DEFAULT_LOCK_TTL)
    _STORE = _store_from_dsn(dsn, base, grace=grace, ttl=ttl)
    return _STORE


def reset_store() -> None:
    """Drop the cached store (tests that switch backends mid-process)."""
    global _STORE
    _STORE = None

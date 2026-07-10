"""Data-access layer for todo tickets: a swappable store in front of storage.

Ticket persistence goes through a `TodoStore` so the backend can be retargeted.
The backend is chosen by ``<todo_dir>/config.json``, defaulting to
``DEFAULT_STORE`` when the file is absent or unreadable. The preferred key is a
DSN string under ``todo_storage``:

  {"todo_storage": "sqlite://$TODOBASEDIR/sqlite.db"}  -> SqliteTodoStore
  {"todo_storage": "file://$TODOBASEDIR/tickets"}      -> JsonDirTodoStore

The path part is shell-expanded: ``$TODOBASEDIR`` / ``${TODOBASEDIR}`` resolve
to ``todo basedir`` (the resolved ``.todo`` dir), ``~`` and other ``$VAR`` are
expanded too. The legacy flat keys are still honored when ``todo_storage`` is
absent:

  {"store": "sqlite"}                      -> SqliteTodoStore
  {"store": "json"}                        -> JsonDirTodoStore at <todo_dir>/tickets
  {"store": "json", "tickets_dir": "..."}  -> JsonDirTodoStore at that dir

Each todo is one ``<ID>.json`` file on the JSON backend. Embeddings live inside
the ticket JSON (stamped per field), so both backends carry them. The sqlite
``embeddings`` table is only a derived search index -- ``has_vector_index`` marks
the store that maintains it (sqlite); the JSON backend reports False, so the
write path skips the index mirror and vector search yields nothing there until
JSON-native search lands.

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

DEFAULT_STORE = "sqlite"

# Advisory-lock timings (seconds), overridable via config.json.
DEFAULT_LOCK_GRACE = 30.0  # how long an acquirer polls before giving up (ERETRY)
DEFAULT_LOCK_TTL = 15.0  # how long a held lock stays valid before it is stealable
_POLL_INTERVAL = 0.1


class TodoStoreError(Exception):
    """Store configuration error (e.g. a malformed todo_storage DSN)."""


class LockTimeout(Exception):
    """A per-TODO lock could not be acquired within the grace period."""


class TodoStore(ABC):
    """Abstract ticket store. Repo/branch identify a ticket; Id is its key."""

    # Whether this store maintains the sqlite embeddings search index. The
    # embedding vectors themselves live in the ticket JSON on every backend.
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
    def delete(self, todo: JsonDict, *, hard: bool) -> bool:
        """Remove *todo* from the store. ``hard`` permanently deletes it; a soft
        delete keeps a recoverable tombstone (no recovery tool exists yet).
        Returns True if the todo was present and removed."""

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
        with todo_db.connection(self.db_path) as conn:
            rows = conn.execute("SELECT data FROM tickets ORDER BY rowid").fetchall()
        todos: List[JsonDict] = []
        for row in rows:
            parsed = json.loads(str(row["data"]))
            if isinstance(parsed, dict) and parsed.get("Id"):
                todos.append(parsed)
        return todos

    def delete(self, todo: JsonDict, *, hard: bool) -> bool:
        ticket_id = str(todo["Id"])
        with todo_db.connection(self.db_path) as conn:
            if hard:
                return todo_db.hard_delete_ticket(conn, ticket_id)
            return todo_db.soft_delete_ticket(conn, ticket_id)

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
                scope = todo.get("Scope")
                url = scope.get("git_url") if isinstance(scope, dict) else None
                repo = todo_db.repo_identity_from_url(url) if isinstance(url, str) and url else ""
                out.append((repo or "", str(todo.get("Branch") or ""), todo))
        return out

    def list_all(self) -> List[JsonDict]:
        return self._all()

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


def _load_config() -> JsonDict:
    """Read ``<todo_dir>/config.json``; empty dict when absent or unreadable."""
    try:
        parsed = json.loads((todo_db.todo_dir() / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _float_config(config: JsonDict, key: str, default: float) -> float:
    """Read a float config value, falling back to *default* on absence/garbage."""
    try:
        return float(config[key])
    except (KeyError, TypeError, ValueError):
        return default


def _expand_todo_base(path: str) -> str:
    """Expand ``$TODOBASEDIR`` (the resolved todo dir), ``~`` and other env vars."""
    base = str(todo_db.todo_dir())
    substituted = path.replace("${TODOBASEDIR}", base).replace("$TODOBASEDIR", base)
    return os.path.expanduser(os.path.expandvars(substituted))


def _store_from_dsn(dsn: str, *, grace: float, ttl: float) -> TodoStore:
    """Build a store from a ``scheme://path`` todo_storage DSN."""
    scheme, sep, rest = dsn.partition("://")
    if not sep:
        raise TodoStoreError(f"invalid todo_storage DSN (expected scheme://path): {dsn!r}")
    scheme = scheme.strip().lower()
    target = Path(_expand_todo_base(rest))
    if scheme == "sqlite":
        return SqliteTodoStore(db_path=target, grace=grace, ttl=ttl)
    if scheme == "file":
        return JsonDirTodoStore(target, grace=grace, ttl=ttl)
    raise TodoStoreError(f"unknown todo_storage scheme {scheme!r} (want sqlite:// or file://)")


_STORE: Optional[TodoStore] = None


def get_store() -> TodoStore:
    """Return the process-wide ticket store, chosen from ``<todo_dir>/config.json``."""
    global _STORE
    if _STORE is not None:
        return _STORE
    config = _load_config()
    grace = _float_config(config, "lock_grace", DEFAULT_LOCK_GRACE)
    ttl = _float_config(config, "lock_ttl", DEFAULT_LOCK_TTL)
    dsn = config.get("todo_storage")
    if isinstance(dsn, str) and dsn.strip():
        _STORE = _store_from_dsn(dsn, grace=grace, ttl=ttl)
        return _STORE
    # Back-compat: the pre-DSN flat keys, honored only when todo_storage is absent.
    kind = str(config.get("store", DEFAULT_STORE)).strip().lower()
    if kind == "json":
        tickets_dir = config.get("tickets_dir")
        directory = Path(tickets_dir) if tickets_dir else (todo_db.todo_dir() / "tickets")
        _STORE = JsonDirTodoStore(directory, grace=grace, ttl=ttl)
    else:
        _STORE = SqliteTodoStore(grace=grace, ttl=ttl)
    return _STORE


def reset_store() -> None:
    """Drop the cached store (tests that switch backends mid-process)."""
    global _STORE
    _STORE = None

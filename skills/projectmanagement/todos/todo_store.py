"""Data-access layer for todo tickets: a swappable store in front of storage.

Ticket persistence goes through a `TodoStore` so the backend can be retargeted.
The backend is chosen by ``<todo_dir>/config.json`` (key ``store``), defaulting
to ``DEFAULT_STORE`` when the file is absent or unreadable:

  {"store": "sqlite"}                      -> SqliteTodoStore (todo_db backend)
  {"store": "json"}                        -> JsonDirTodoStore at <todo_dir>/tickets
  {"store": "json", "tickets_dir": "..."}  -> JsonDirTodoStore at that dir

Each todo is one ``<ID>.json`` file on the JSON backend. Embeddings live inside
the ticket JSON (stamped per field), so both backends carry them. The sqlite
``embeddings`` table is only a derived search index -- ``has_vector_index`` marks
the store that maintains it (sqlite); the JSON backend reports False, so the
write path skips the index mirror and vector search yields nothing there until
JSON-native search lands.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import todo_db

JsonDict = Dict[str, Any]

DEFAULT_STORE = "sqlite"


class TodoStore(ABC):
    """Abstract ticket store. Repo/branch identify a ticket; Id is its key."""

    # Whether this store maintains the sqlite embeddings search index. The
    # embedding vectors themselves live in the ticket JSON on every backend.
    has_vector_index: bool = False

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


class SqliteTodoStore(TodoStore):
    """Default backend: delegates to the todo_db sqlite storage."""

    has_vector_index = True

    def get(self, repo: str, branch: str) -> Optional[JsonDict]:
        with todo_db.connection() as conn:
            return todo_db.get_ticket_by_repo_branch(conn, repo, branch)

    def put(self, repo: str, branch: str, todo: JsonDict) -> None:
        with todo_db.connection() as conn:
            todo_db.put_ticket(conn, repo, branch, todo)

    def find_by_id_prefix(self, query: str) -> List[Tuple[str, str, JsonDict]]:
        with todo_db.connection() as conn:
            return todo_db.find_tickets_by_id_prefix(conn, query)

    def list_all(self) -> List[JsonDict]:
        with todo_db.connection() as conn:
            rows = conn.execute("SELECT data FROM tickets ORDER BY rowid").fetchall()
        todos: List[JsonDict] = []
        for row in rows:
            parsed = json.loads(str(row["data"]))
            if isinstance(parsed, dict) and parsed.get("Id"):
                todos.append(parsed)
        return todos


class JsonDirTodoStore(TodoStore):
    """A directory of ``<ID>.json`` files, one per todo (embeddings included)."""

    has_vector_index = False

    def __init__(self, directory: Path) -> None:
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
                repo = str(scope.get("path_to_project") or "") if isinstance(scope, dict) else ""
                out.append((repo, str(todo.get("Branch") or ""), todo))
        return out

    def list_all(self) -> List[JsonDict]:
        return self._all()


def _load_config() -> JsonDict:
    """Read ``<todo_dir>/config.json``; empty dict when absent or unreadable."""
    try:
        parsed = json.loads((todo_db.todo_dir() / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


_STORE: Optional[TodoStore] = None


def get_store() -> TodoStore:
    """Return the process-wide ticket store, chosen from ``<todo_dir>/config.json``."""
    global _STORE
    if _STORE is not None:
        return _STORE
    config = _load_config()
    kind = str(config.get("store", DEFAULT_STORE)).strip().lower()
    if kind == "json":
        tickets_dir = config.get("tickets_dir")
        directory = Path(tickets_dir) if tickets_dir else (todo_db.todo_dir() / "tickets")
        _STORE = JsonDirTodoStore(directory)
    else:
        _STORE = SqliteTodoStore()
    return _STORE


def reset_store() -> None:
    """Drop the cached store (tests that switch backends mid-process)."""
    global _STORE
    _STORE = None

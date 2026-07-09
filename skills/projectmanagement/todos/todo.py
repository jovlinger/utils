#!/usr/bin/env python3
"""AWS-style CLI for branch-bound todo tickets (sqlite-backed; legacy JSON import)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Sequence

import todo_db
import todo_store
import todo_embed
import todo_web

JsonDict = Dict[str, Any]

LEGACY_JSON_ENV = "TODO_USE_JSON"

# Local-first: remote polling is feature-flagged off for now. Flip to True to
# re-enable best-effort fetch on read once multi-agent sync is wanted.
FETCH_ENABLED: bool = False

VALID_STATES = frozenset(
    {"init", "working", "userneeded", "stopped", "done", "merged", "waiting", "N/a"}
)
STOPWORDS = frozenset({"a", "an", "the", "to", "from", "for", "and", "or", "in", "on", "of"})


class TodoError(Exception):
    """User-facing todo CLI error."""


def repo_root(start: Optional[Path] = None) -> Path:
    """Return git toplevel for *start* (default cwd)."""
    cwd: Path = start or Path.cwd()
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise TodoError(f"not a git repository: {cwd}")
    return Path(result.stdout.strip())


def utc_now() -> str:
    """Return current UTC time as RFC3339 Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a git command in *root*."""
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        # *root* may be an unreachable working directory; treat it as a normal
        # git failure rather than crashing.
        result = subprocess.CompletedProcess(
            ["git", *args], returncode=1, stdout="", stderr=str(exc)
        )
    if check and result.returncode != 0:
        detail: str = (result.stderr or result.stdout or "").strip()
        raise TodoError(f"git {' '.join(args)} failed: {detail}")
    return result


def git_fetch_if_remote(root: Path) -> None:
    """Best-effort fetch when a remote exists; never fatal."""
    if not FETCH_ENABLED:
        return
    remotes: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "remote"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    if not remotes.stdout.strip():
        return
    fetched: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "fetch", "--quiet"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if fetched.returncode != 0:
        print("todo.py: fetch failed; using cached refs", file=sys.stderr)


def list_branch_refs(root: Path) -> List[str]:
    """Short names for local branches and remote-tracking branches."""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [
            "git",
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/heads",
            "refs/remotes",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    refs: List[str] = []
    for line in result.stdout.splitlines():
        ref: str = line.strip()
        if not ref or ref.endswith("/HEAD"):
            continue
        refs.append(ref)
    return refs


def branch_exists(root: Path, name: str) -> bool:
    """Return True when a local branch *name* exists."""
    result = run_git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{name}", check=False)
    return result.returncode == 0


def normalize_todo_schema(todo: JsonDict) -> JsonDict:
    """Migrate legacy field names (Chunks, Subtickets) to WorkItems, Subtodos.

    Also migrates the singular ``Parent`` dict to a ``Parent`` list of
    ``{Id, Branch}`` refs. Element 0 is the structural (fork) parent used for the
    log diff base and merge; later entries are context-only references added by
    ``init --parent``.
    """
    if "Chunks" in todo and "WorkItems" not in todo:
        todo["WorkItems"] = todo.pop("Chunks")
    if "Subtickets" in todo and "Subtodos" not in todo:
        todo["Subtodos"] = todo.pop("Subtickets")
    parent = todo.get("Parent")
    if isinstance(parent, dict):
        todo["Parent"] = [parent]
    # Absolute project paths are machine-specific and no longer stored: the repo
    # name identifies the repo and CWD is the concrete location on this machine.
    scope = todo.get("Scope")
    if isinstance(scope, dict):
        scope.pop("path_to_project", None)
    return todo


def use_sqlite() -> bool:
    """Return True when tickets are stored in sqlite (default)."""
    return os.environ.get(LEGACY_JSON_ENV) != "1"


# Canonical repo identity lives in todo_db so the schema migration can reuse it.
repo_identity_from_url = todo_db.repo_identity_from_url


_REPO_KEY_CACHE: Dict[str, str] = {}


def repo_key(root: Path) -> str:
    """Stable repo identity for sqlite keys.

    Derived from the origin remote (``host/owner/name``) so it survives moving
    the db between machines/users and collapses git worktrees (which share the
    origin) onto their repo. Falls back to the gitroot basename when there is no
    identifiable origin remote. Cached per resolved root for the process, since
    it shells out to git.
    """
    resolved = str(root.resolve())
    cached = _REPO_KEY_CACHE.get(resolved)
    if cached is not None:
        return cached
    url = git_url_for_repo(root)
    key = (repo_identity_from_url(url) if url else None) or Path(resolved).name
    _REPO_KEY_CACHE[resolved] = key
    return key


def read_todo_at_ref(root: Path, ref: str) -> Optional[JsonDict]:
    """Return parsed ticket from sqlite or legacy git ref TODO.json."""
    if use_sqlite():
        ticket = todo_store.get_store().get(repo_key(root), ref)
        if ticket is not None:
            return normalize_todo_schema(ticket)
    try:
        show: subprocess.CompletedProcess[str] = subprocess.run(
            ["git", "show", f"{ref}:TODO.json"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        # *root* recorded on another machine and absent here: ticket unavailable.
        return None
    if show.returncode != 0:
        return None
    try:
        parsed: Any = json.loads(show.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return normalize_todo_schema(parsed)


def read_todo_worktree(root: Path) -> Optional[JsonDict]:
    """Return parsed ticket for the current branch from sqlite or legacy file."""
    branch = current_branch(root)
    if branch and use_sqlite():
        ticket = todo_store.get_store().get(repo_key(root), branch)
        if ticket is not None:
            return normalize_todo_schema(ticket)
    path: Path = root / "TODO.json"
    if not path.is_file():
        return None
    if use_sqlite():
        return None
    try:
        parsed: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return normalize_todo_schema(parsed)


def read_todo_required(root: Path) -> JsonDict:
    """Return parsed ticket from the worktree or raise."""
    _, todo = read_todo_current_branch(root)
    return todo


# (Summary/Body field name, its stored field_path) pairs we embed.
_EMBED_FIELDS: tuple[tuple[str, str], ...] = (
    ("Summary", "Summary.raw"),
    ("Body", "Body.raw"),
)


def _is_vector(value: Any) -> bool:
    """True for an embedding-like list: >2 numbers, no bools."""
    return (
        isinstance(value, list)
        and len(value) > 2
        and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in value)
    )


def _raw_of(todo: Optional[JsonDict], field_name: str) -> Optional[str]:
    """Return a non-empty ``todo[field_name]['raw']`` string, else None."""
    if not isinstance(todo, dict):
        return None
    obj = todo.get(field_name)
    if isinstance(obj, dict):
        raw = obj.get("raw")
        if isinstance(raw, str) and raw.strip():
            return raw
    return None


def _changed_raw_fields(
    old: Optional[JsonDict], new: JsonDict
) -> List[tuple[str, str]]:
    """Return the (field_name, field_path) pairs whose raw text differs."""
    changed: List[tuple[str, str]] = []
    for field_name, field_path in _EMBED_FIELDS:
        if _raw_of(new, field_name) != _raw_of(old, field_name):
            changed.append((field_name, field_path))
    return changed


def _strip_field_vectors(todo: JsonDict, field_name: str) -> None:
    """Drop stamped embedding vectors from a Summary/Body field in place."""
    obj = todo.get(field_name)
    if isinstance(obj, dict):
        for key in [k for k, v in obj.items() if k != "raw" and _is_vector(v)]:
            del obj[key]


def _json_embeddings_present(todo: JsonDict) -> set:
    """(field_path, fingerprint) pairs already stamped into the ticket JSON."""
    present: set = set()
    for field_name, field_path in _EMBED_FIELDS:
        obj = todo.get(field_name)
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key != "raw" and _is_vector(value):
                    present.add((field_path, key))
    return present


def _cheap_embedding_rows(
    todo: JsonDict, existing: set
) -> List[tuple[str, str, List[float]]]:
    """Stamp missing cheap vectors into the ticket JSON; return rows to store.

    ``existing`` is the set of ``(field_path, fingerprint)`` already in the db.
    Stamps ``todo`` in place so ``put_ticket`` serializes the vectors; the caller
    must ``put_embedding`` the returned rows *after* ``put_ticket`` (the FK needs
    the ticket row first). Degrades to fewer/no rows if a cheap embedder fails,
    so a broken embedder never blocks the save.
    """
    rows: List[tuple[str, str, List[float]]] = []
    try:
        embedders = todo_embed.cheap_embedders()
    except (ValueError, RuntimeError):
        return rows
    for embedder in embedders:
        try:
            fingerprint = embedder.fingerprint()
        except (ValueError, RuntimeError):
            continue
        for field_name, field_path in _EMBED_FIELDS:
            raw = _raw_of(todo, field_name)
            if raw is None or (field_path, fingerprint) in existing:
                continue
            try:
                vec = embedder.embed(raw)
            except (ValueError, RuntimeError):
                continue
            todo[field_name][fingerprint] = vec
            rows.append((field_path, fingerprint, vec))
    return rows


def write_todo_worktree(root: Path, todo: JsonDict, *, no_clear: bool = False) -> None:
    """Persist ticket to sqlite (default) or legacy TODO.json.

    On sqlite: when a raw field changed, its stored vectors are cleared (all
    embedders) so stale expensive vectors do not linger -- unless ``no_clear``,
    which keeps them (for semantically trivial edits). Cheap embedders are then
    re-populated eagerly; expensive ones are left for lazy backfill at search.
    """
    normalize_todo_schema(todo)
    todo["update_dt"] = utc_now()
    branch = str(todo.get("Branch") or current_branch(root) or "")
    if not branch:
        raise TodoError("todo missing Branch")
    if use_sqlite():
        ticket_id = str(todo["Id"])
        store = todo_store.get_store()
        old = store.get(repo_key(root), branch)
        changed = [] if no_clear else list(_changed_raw_fields(old, todo))
        for field_name, _field_path in changed:
            _strip_field_vectors(todo, field_name)
        # Embeddings live in the todo JSON: stamp missing cheap vectors here (any
        # backend) so the store serializes them. The sqlite embeddings table is
        # only a derived search index, mirrored when the store keeps one.
        rows = _cheap_embedding_rows(todo, _json_embeddings_present(todo))
        # Lock only the write: the read + embedding computation above run
        # unlocked; the per-TODO lock is held just long enough to persist this
        # one ticket (and mirror its vectors) so concurrent writers of the same
        # ticket cannot interleave. The mirror uses the store's own db so a
        # relocated (DSN) sqlite file is never split-brained against the default.
        with store.lock(ticket_id):
            store.put(repo_key(root), branch, todo)
            if store.has_vector_index:
                with todo_db.connection(getattr(store, "db_path", None)) as conn:
                    for _field_name, field_path in changed:
                        todo_db.clear_embeddings(conn, ticket_id, field_path)
                    for field_path, fingerprint, vec in rows:
                        todo_db.put_embedding(conn, ticket_id, field_path, fingerprint, vec)
        return
    path: Path = root / "TODO.json"
    tmp: Path = root / "TODO.json.tmp"
    tmp.write_text(json.dumps(todo, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def commit_todo(root: Path, message: str) -> None:
    """Record a todo change commit (empty when sqlite-only)."""
    if use_sqlite():
        run_git(root, "commit", "--allow-empty", "-m", message, check=False)
        return
    if not (root / "TODO.json").is_file():
        raise TodoError("TODO.json missing; nothing to commit")
    run_git(root, "add", "TODO.json")
    run_git(root, "commit", "-m", message, check=False)


def head_sha(root: Path) -> Optional[str]:
    """Return the current HEAD commit sha, or None when there is no commit."""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def current_branch(root: Path) -> Optional[str]:
    """Return short name of the checked-out branch, if any."""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    name: str = result.stdout.strip()
    return name or None


def is_self_selector(selector: str) -> bool:
    """Return True when *selector* names the current branch's todo."""
    return selector in {"self", "curr"}


def read_todo_current_branch(root: Path) -> tuple[str, JsonDict]:
    """Return the todo bound to the checked-out branch."""
    branch: Optional[str] = current_branch(root)
    if not branch:
        raise TodoError("detached HEAD; self/curr requires a checked-out branch")
    worktree = read_todo_worktree(root)
    if worktree is not None:
        return f"worktree:{branch}", worktree
    todo = read_todo_at_ref(root, branch)
    if todo is None:
        raise TodoError(f"no todo found on current branch {branch!r}")
    return branch, todo


def id_matches(ticket_id: str, query: str) -> bool:
    """True when *query* selects ticket *ticket_id* (exact or prefix)."""
    if ticket_id == query:
        return True
    if ticket_id.startswith(query):
        return True
    return False


def branch_name_hint(query: str) -> str:
    """Leading token used in Branch naming (first eight id chars)."""
    token: str = query.split("-", 1)[0]
    return token[:8]


def candidate_refs(refs: Sequence[str], query: str) -> List[str]:
    """Narrow branch refs using the id prefix convention when possible."""
    hint: str = branch_name_hint(query)
    if len(hint) < 2:
        return list(refs)
    narrowed: List[str] = [ref for ref in refs if hint in ref]
    return narrowed if narrowed else list(refs)


def kebab_branch_name(ticket_id: str, summary: str) -> str:
    """Build Branch label from id prefix and summary words."""
    words: List[str] = re.sub(r"[^a-zA-Z0-9\s]", " ", summary.lower()).split()
    slug_words: List[str] = [word for word in words if word not in STOPWORDS][:4]
    slug: str = "-".join(slug_words) if slug_words else "ticket"
    branch: str = f"{ticket_id[:8]}-{slug}"
    return branch[:32]


def current_state_name(todo: JsonDict) -> Optional[str]:
    """Return the single State key, if well-formed."""
    state = todo.get("State")
    if not isinstance(state, dict) or len(state) != 1:
        return None
    return next(iter(state.keys()))


def set_state(
    todo: JsonDict,
    state: str,
    *,
    note: Optional[str] = None,
    last_commit: Optional[str] = None,
    merged_into: Optional[str] = None,
    owner: Optional[str] = None,
) -> None:
    """Replace State with a single-key object."""
    if state not in VALID_STATES:
        raise TodoError(f"invalid state {state!r}")
    value: JsonDict = {}
    if state == "working" and owner:
        value["owner"] = owner
    if state in {"userneeded", "stopped"} and note:
        value["note"] = note
    if state == "done" and last_commit:
        value["last_commit"] = last_commit
    if state == "merged":
        if merged_into:
            value["merged_into"] = merged_into
    todo["State"] = {state: value}


def git_url_for_repo(root: Path) -> Optional[str]:
    """Best-effort origin URL for Scope.git_url."""
    result = run_git(root, "remote", "get-url", "origin", check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def build_ticket_skeleton(
    root: Path,
    ticket_id: str,
    branch: str,
    summary: str,
    body: str,
    ac: str,
    *,
    path_from_root: Optional[str] = None,
    parent: Optional[List[JsonDict]] = None,
    work_items: Optional[List[JsonDict]] = None,
    agent_type: Optional[str] = None,
    session_id: Optional[str] = None,
) -> JsonDict:
    """Construct a fresh TODO.json object."""
    now = utc_now()
    scope: JsonDict = {
        "branch": branch,
    }
    remote = git_url_for_repo(root)
    if remote:
        scope["git_url"] = remote
    if path_from_root:
        scope["path_from_root"] = path_from_root
    ticket: JsonDict = {
        "Id": ticket_id,
        "Branch": branch,
        "create_dt": now,
        "update_dt": now,
        "State": {"init": {}},
        "Scope": scope,
        "Summary": {"raw": summary},
        "Body": {"raw": body},
        "AC": ac,
    }
    if work_items is not None:
        ticket["WorkItems"] = work_items
    if parent is not None:
        ticket["Parent"] = parent
    if agent_type or session_id:
        agent: JsonDict = {}
        if agent_type:
            agent["type"] = agent_type
        if session_id:
            agent["session_id"] = session_id
        ticket["Agent"] = agent
    return ticket


# --- WorkItem model: typed items, cursor, and invariants -------------------
#
# A WorkItem is either not-done freetext (kind "task") or one of three typed
# done kinds, each produced by the command that performs that work:
#   - "code"          local coding; carries a `sha` (invariant #1)
#   - "merge_subtodo" a merged subtodo; carries `subtodo_id` and a `sha`
#   - "start_subtodo" a fired subtodo; carries `subtodo_id`, no sha
# The cursor is the first not-done item (derived). Working proceeds by marking
# the cursor done and advancing; the index never decreases though the list may
# grow (invariant #3). A todo is done when nothing is not-done (invariant #7).

WORKITEM_TASK = "task"
WORKITEM_CODE = "code"
WORKITEM_MERGE_SUBTODO = "merge_subtodo"
WORKITEM_START_SUBTODO = "start_subtodo"
WORKITEM_DONE_KINDS = frozenset(
    {WORKITEM_CODE, WORKITEM_MERGE_SUBTODO, WORKITEM_START_SUBTODO}
)
WORKITEM_KINDS = WORKITEM_DONE_KINDS | {WORKITEM_TASK}


def workitem_kind(item: JsonDict) -> str:
    """Best-effort kind for a work item, tolerating legacy shapes."""
    kind = item.get("kind")
    if isinstance(kind, str) and kind:
        return kind
    return WORKITEM_CODE if item.get("done") else WORKITEM_TASK


def workitem_is_done(item: JsonDict) -> bool:
    """True when a work item is complete (a done kind or the legacy done flag)."""
    if item.get("done"):
        return True
    return workitem_kind(item) in WORKITEM_DONE_KINDS


def cursor_index(todo: JsonDict) -> Optional[int]:
    """Index of the current work item -- the first not-done one, or None if none."""
    items = todo.get("WorkItems") or []
    for index, item in enumerate(items):
        if isinstance(item, dict) and not workitem_is_done(item):
            return index
    return None


def cursor_summary(todo: JsonDict) -> str:
    """Summary text of the cursor work item, or '' when there is no open item."""
    index = cursor_index(todo)
    if index is None:
        return ""
    item = todo["WorkItems"][index]
    return str(item.get("summary") or "") if isinstance(item, dict) else ""


def is_done(todo: JsonDict) -> bool:
    """A todo is done when it has no not-yet-done work items (invariant #7)."""
    return cursor_index(todo) is None


def next_action(todo: JsonDict) -> JsonDict:
    """Deterministic next mechanical step for the cursor, where the tool can tell.

    Mechanism only: it maps the cursor item's execution hints (or the empty
    cursor) to the exact command that advances the loop. It does NOT make policy
    calls -- whether a plain task should instead become a subtodo, or be split
    because it is too coarse -- which stay with the agent and the skill's
    dispatch table. A plain freetext task with no execution hints defaults to
    work-item-done, the common local-coding completion.
    """
    index = cursor_index(todo)
    if index is None:
        return {
            "action": "finish",
            "command": 'todo.py set-state done --actual-summary="..."',
            "note": "run doctor first (must be ok); synthesize ActualSummary from the done WorkItems",
        }
    item = todo["WorkItems"][index]
    execution = item.get("execution") if isinstance(item, dict) else None
    execution = execution if isinstance(execution, dict) else {}
    primitive = execution.get("primitive")
    wait_for = [w[:8] for w in (execution.get("wait_for") or []) if isinstance(w, str)]
    subtodo_id = execution.get("subtodo_id")
    child = subtodo_id[:8] if isinstance(subtodo_id, str) and subtodo_id else "<child-id>"
    ids = " ".join(wait_for) or "<child-id>..."
    if primitive == "add-subtodo":
        return {"action": "add-subtodo", "command": "todo.py add-subtodo --summary=..."}
    if primitive in (WORKITEM_MERGE_SUBTODO, "merge-subtodo"):
        return {"action": "merge-subtodo", "command": f"todo.py merge-subtodo {child}"}
    if primitive == "wait-and-merge" or (wait_for and execution.get("mode") == "barrier"):
        return {"action": "wait-and-merge", "command": f"todo.py wait-and-merge {ids}"}
    if primitive == "wait-for" or wait_for:
        return {"action": "wait-for", "command": f"todo.py wait-for {ids}"}
    return {"action": "work-item-done", "command": "todo.py work-item-done"}


def last_sha(todo: JsonDict) -> Optional[str]:
    """Sha of the last work item -- the last branch commit (invariant #6), if any."""
    items = todo.get("WorkItems") or []
    if not items or not isinstance(items[-1], dict):
        return None
    sha = items[-1].get("sha")
    return sha if isinstance(sha, str) and sha else None


def code_workitem(sha: str, summary: str = "", message: str = "") -> JsonDict:
    """Build a done 'code' work item.

    `summary` is the high-level step description (carries over from the cursor task).
    `message` is the full commit message recorded at `sha`, so the WorkItems trail is
    self-describing (what actually changed -- e.g. tests added) without resolving shas."""
    item = {"kind": WORKITEM_CODE, "summary": summary, "sha": sha, "done": True}
    if message:
        item["message"] = message
    return item


def start_subtodo_workitem(subtodo_id: str, summary: str = "") -> JsonDict:
    """Build a done 'start_subtodo' work item (no sha)."""
    return {
        "kind": WORKITEM_START_SUBTODO,
        "summary": summary,
        "subtodo_id": subtodo_id,
        "done": True,
    }


def merge_subtodo_workitem(subtodo_id: str, sha: str, summary: str = "") -> JsonDict:
    """Build a done 'merge_subtodo' work item."""
    return {
        "kind": WORKITEM_MERGE_SUBTODO,
        "summary": summary,
        "subtodo_id": subtodo_id,
        "sha": sha,
        "done": True,
    }


def mark_cursor_done(todo: JsonDict, done_item: JsonDict) -> int:
    """Convert the cursor (first not-done) item into *done_item*, or append it when
    the plan has no open item. The cursor's freetext summary carries over as the
    item's high-level description unless *done_item* already set one. Returns the
    affected index."""
    items = list(todo.get("WorkItems") or [])
    index = cursor_index(todo)
    if index is None:
        items.append(done_item)
        index = len(items) - 1
    else:
        if not done_item.get("summary"):
            done_item["summary"] = items[index].get("summary", "")
        items[index] = done_item
    todo["WorkItems"] = items
    return index


def find_todos_by_id(root: Path, query: str) -> List[tuple[str, JsonDict]]:
    """Locate tickets whose Id matches *query* via sqlite or git refs."""
    matches: List[tuple[str, JsonDict]] = []
    seen_ids: set[str] = set()

    if use_sqlite():
        for repo_path, branch, todo in todo_store.get_store().find_by_id_prefix(query):
            ticket_id = str(todo.get("Id", ""))
            if ticket_id and ticket_id not in seen_ids:
                loc = f"{repo_path}:{branch}" if repo_path != repo_key(root) else branch
                matches.append((loc, todo))
                seen_ids.add(ticket_id)
        if matches:
            return matches

    branch: Optional[str] = current_branch(root)
    worktree: Optional[JsonDict] = read_todo_worktree(root)
    if worktree is not None:
        ticket_id: str = str(worktree.get("Id", ""))
        if ticket_id and id_matches(ticket_id, query):
            loc: str = f"worktree:{branch or 'detached'}"
            matches.append((loc, worktree))
            seen_ids.add(ticket_id)

    refs: List[str] = candidate_refs(list_branch_refs(root), query)
    for ref in refs:
        todo: Optional[JsonDict] = read_todo_at_ref(root, ref)
        if todo is None:
            continue
        ticket_id = str(todo.get("Id", ""))
        if not ticket_id or not id_matches(ticket_id, query):
            continue
        if ticket_id in seen_ids:
            continue
        matches.append((ref, todo))
        seen_ids.add(ticket_id)
    return matches


def resolve_ticket_by_id(root: Path, query: str) -> tuple[str, JsonDict]:
    """Return a unique (location, ticket) pair for *query*."""
    if len(query) < 4:
        raise TodoError("id prefix must be at least 4 hex chars")
    matches = find_todos_by_id(root, query)
    if not matches:
        raise TodoError(f"no todo found for id {query!r}")
    if len(matches) > 1:
        locations: str = ", ".join(loc for loc, _ in matches)
        raise TodoError(f"ambiguous id {query!r}; matches on: {locations}")
    loc, ticket = matches[0]
    # Complain when the resolved todo lives in a different repo than the CWD.
    current = repo_key(root)
    other = loc.rsplit(":", 1)[0]
    if ":" in loc and other not in {"worktree", current} and "/" in other:
        print(
            f"todo: {query!r} lives in {other}, not the current repo {current}",
            file=sys.stderr,
        )
    return matches[0]


def resolve_ticket_by_selector(root: Path, selector: str) -> tuple[str, JsonDict]:
    """Return the ticket selected by id prefix or self/curr."""
    if is_self_selector(selector):
        return read_todo_current_branch(root)
    return resolve_ticket_by_id(root, selector)


def mint_id(root: Path, attempts: int = 1000) -> str:
    """Mint a fresh ticket Id with no 8-hex prefix clash in the repo or db."""
    for _ in range(attempts):
        ticket_id: str = hashlib.sha256(uuid.uuid1().bytes).hexdigest()
        if not find_todos_by_id(root, ticket_id[:8]):
            return ticket_id
    raise TodoError("could not mint a collision-free Id")


def import_json_ticket(root: Path, ticket: JsonDict, *, branch: Optional[str] = None) -> JsonDict:
    """Load one ticket dict into sqlite for *root*."""
    normalize_todo_schema(ticket)
    branch_name = branch or str(ticket.get("Branch") or "")
    if not branch_name:
        raise TodoError("ticket missing Branch")
    ticket["Branch"] = branch_name
    scope = dict(ticket.get("Scope") or {})
    scope.pop("path_to_project", None)
    scope["branch"] = branch_name
    remote = git_url_for_repo(root)
    if remote:
        scope.setdefault("git_url", remote)
    ticket["Scope"] = scope
    ticket.setdefault("create_dt", utc_now())
    ticket.setdefault("update_dt", utc_now())
    ticket.setdefault("State", {"init": {}})
    write_todo_worktree(root, ticket)
    return ticket


def import_all_json_refs(root: Path) -> int:
    """Import every TODO.json found on git refs in *root* into sqlite."""
    count = 0
    for ref in list_branch_refs(root):
        todo = read_todo_at_ref_legacy(root, ref)
        if todo is None:
            continue
        import_json_ticket(root, todo, branch=ref.split("/", 1)[-1] if ref.startswith("origin/") else ref)
        count += 1
    return count


def read_todo_at_ref_legacy(root: Path, ref: str) -> Optional[JsonDict]:
    """Read TODO.json from git only (ignore sqlite)."""
    show: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "show", f"{ref}:TODO.json"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if show.returncode != 0:
        return None
    try:
        parsed: Any = json.loads(show.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return normalize_todo_schema(parsed)


# Reciprocal-rank-fusion constant; larger flattens the contribution curve.
_RRF_K = 60


def _rrf_fuse(rankings: List[Dict[str, float]]) -> Dict[str, float]:
    """Reciprocal rank fusion: sum 1/(k+rank) across rankers, scale-free."""
    fused: Dict[str, float] = {}
    for scores in rankings:
        ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        for rank, (tid, _score) in enumerate(ordered, start=1):
            fused[tid] = fused.get(tid, 0.0) + 1.0 / (_RRF_K + rank)
    return fused


def search_tickets(
    root: Path,
    query: str,
    *,
    limit: int = 20,
    embedder_names: Optional[Sequence[str]] = None,
    dry_run: bool = False,
) -> List[JsonDict]:
    """Rank tickets by reciprocal-rank fusion over the chosen embedders + lexical.

    ``embedder_names`` defaults to every non-hidden embedder. A requested
    embedder that cannot be instantiated or run raises ``TodoError`` (choose
    ``--embedder`` explicitly). Unless ``dry_run``, vectors missing for a chosen
    embedder are computed and stored (lazy backfill) before ranking; a ticket
    still missing a vector simply does not contribute to that ranker.
    """
    names = list(embedder_names) if embedder_names else todo_embed.default_embedder_names()
    embedders: List[tuple[str, todo_embed.Embedder]] = []
    for name in names:
        try:
            embedders.append((name, todo_embed.get_embedder(name)))
        except (ValueError, RuntimeError) as exc:
            raise TodoError(
                f"embedder {name!r} unavailable: {exc}; "
                f"choose --embedder explicitly (e.g. --embedder hash)"
            ) from exc

    query_tokens = set(query.lower().split())
    with todo_db.connection() as conn:
        rows = conn.execute("SELECT data FROM tickets").fetchall()
        tickets: Dict[str, JsonDict] = {}
        raws: Dict[str, Dict[str, str]] = {}
        for row in rows:
            parsed: Any = json.loads(str(row["data"]))
            if not isinstance(parsed, dict):
                continue
            ticket_id = str(parsed.get("Id", ""))
            if not ticket_id:
                continue
            tickets[ticket_id] = parsed
            raws[ticket_id] = {
                field_path: raw
                for field_name, field_path in _EMBED_FIELDS
                if (raw := _raw_of(parsed, field_name)) is not None
            }

        rankings: List[Dict[str, float]] = []
        for name, embedder in embedders:
            fingerprint = embedder.fingerprint()
            try:
                query_vec = embedder.embed(query)
            except (ValueError, RuntimeError) as exc:
                raise TodoError(f"embedder {name!r} failed: {exc}") from exc
            stored = {
                (tid, field): vec
                for tid, field, vec in todo_db.all_embeddings(conn, fingerprint)
            }
            if not dry_run:
                for tid, field_raws in raws.items():
                    for field_path, raw in field_raws.items():
                        if (tid, field_path) in stored:
                            continue
                        try:
                            vec = embedder.embed(raw)
                        except (ValueError, RuntimeError) as exc:
                            raise TodoError(f"embedder {name!r} failed: {exc}") from exc
                        todo_db.put_embedding(conn, tid, field_path, fingerprint, vec)
                        stored[(tid, field_path)] = vec
            scores: Dict[str, float] = {}
            for tid in tickets:
                best = 0.0
                for field_path in ("Summary.raw", "Body.raw"):
                    vec = stored.get((tid, field_path))
                    if vec is not None:
                        best = max(best, todo_embed.cosine_similarity(query_vec, vec))
                if best > 0.0:
                    scores[tid] = best
            rankings.append(scores)

        lexical: Dict[str, float] = {}
        for tid in tickets:
            text = " ".join(raws[tid].values()).lower()
            score = 0.0
            if query.lower() in text:
                score += 1.0
            for token in query_tokens:
                if token and token in text:
                    score += 0.1
            if score > 0.0:
                lexical[tid] = score
        rankings.append(lexical)

    fused = _rrf_fuse(rankings)
    ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    return [tickets[tid] for tid, _score in ranked[:limit]]


def _prompt_section(todo: JsonDict) -> str:
    """Render one todo as a titled Summary/Body block for the prompt chain."""
    tid = str(todo.get("Id", ""))[:8]
    summary_obj = todo.get("Summary")
    summary = summary_obj.get("raw", "") if isinstance(summary_obj, dict) else ""
    body_obj = todo.get("Body")
    body = body_obj.get("raw", "") if isinstance(body_obj, dict) else ""
    header = f"===== {summary} [{tid}] =====".strip()
    return f"{header}\n{body}".rstrip()


def build_prompt_chain(root: Path, selector: str) -> str:
    """Concatenate a todo and its parent chain into one startup prompt.

    Walks the ``Parent`` list up (context references included), depth-first, so
    the farthest ancestors' 'why' comes first and the target's own body is last.
    De-duplicates shared ancestors, is cycle-safe, and notes any parent that
    cannot be resolved in this db rather than dropping it silently. Read-only:
    parents are resolved from the db with no branch checkout.
    """
    _loc, target = resolve_ticket_by_selector(root, selector)
    sections: List[str] = []
    seen: set[str] = set()

    def visit(todo: JsonDict) -> None:
        tid = str(todo.get("Id", ""))
        if tid and tid in seen:
            return
        if tid:
            seen.add(tid)
        for ref in todo.get("Parent") or []:
            if not isinstance(ref, dict):
                continue
            parent_id = str(ref.get("Id", ""))
            if not parent_id:
                continue
            try:
                _pl, parent = resolve_ticket_by_id(root, parent_id)
            except TodoError:
                sections.append(f"===== [parent {parent_id[:8]} not found] =====")
                continue
            visit(parent)
        sections.append(_prompt_section(todo))

    visit(target)
    return "\n\n".join(sections)


def load_json_file(path: Path) -> JsonDict:
    """Load a JSON object from *path*."""
    try:
        parsed: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TodoError(f"could not read JSON from {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise TodoError(f"expected JSON object in {path}")
    return parsed


def parse_jsonpath(path_str: str) -> List[Any]:
    """Parse a dot-separated JSON path (optional ``$.`` prefix); numeric segments index lists."""
    path_str = path_str.strip()
    if path_str.startswith("$."):
        path_str = path_str[2:]
    elif path_str == "$":
        raise TodoError("jsonpath must name a field, not the root object")
    elif path_str.startswith("$"):
        path_str = path_str[1:].lstrip(".")
    if not path_str:
        raise TodoError("jsonpath is empty")
    segments: List[Any] = []
    for part in path_str.split("."):
        if part.isdigit():
            segments.append(int(part))
        else:
            segments.append(part)
    return segments


def get_at_path(root: JsonDict, path_str: str) -> Any:
    """Return the value at *path_str* within *root*."""
    current: Any = root
    for key in parse_jsonpath(path_str):
        if isinstance(key, int):
            if not isinstance(current, list):
                raise TodoError(f"expected list at segment {key!r}")
            current = current[key]
        else:
            if not isinstance(current, dict):
                raise TodoError(f"expected object at segment {key!r}")
            current = current[key]
    return current


def print_json_value(value: Any) -> None:
    """Print a JSON value in a script-friendly form."""
    if isinstance(value, (dict, list)):
        json.dump(value, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    elif isinstance(value, (bool, int, float)) or value is None:
        json.dump(value, sys.stdout)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(f"{value}\n")


def set_at_path(root: JsonDict, path_str: str, value: Any) -> None:
    """Set the value at *path_str* within *root*, creating missing object keys."""
    keys = parse_jsonpath(path_str)
    current: Any = root
    for index, key in enumerate(keys[:-1]):
        next_key = keys[index + 1]
        if isinstance(key, int):
            if not isinstance(current, list):
                raise TodoError(f"expected list at segment {key!r}")
            current = current[key]
        else:
            if not isinstance(current, dict):
                raise TodoError(f"expected object at segment {key!r}")
            nested = current.get(key)
            if not isinstance(nested, (dict, list)):
                current[key] = [] if isinstance(next_key, int) else {}
                nested = current[key]
            current = nested
    last = keys[-1]
    if isinstance(last, int):
        if not isinstance(current, list):
            raise TodoError(f"expected list at final segment {last!r}")
        current[last] = value
    else:
        if not isinstance(current, dict):
            raise TodoError(f"expected object at final segment {last!r}")
        current[last] = value


# Subtodos[].State for a child-declared informational back-link: a follow-only
# link (HATEOAS) inserted by `init --parent` and repaired by `doctor`, distinct
# from a tracked subtodo the parent must merge. Excluded from merge-completeness.
SUBTODO_STATE_INFO = "INFO"


def subtodo_entry_from_child(child: JsonDict) -> JsonDict:
    """Build a parent Subtodos row from a child todo."""
    return {
        "Id": child["Id"],
        "Branch": child.get("Branch", ""),
        "Summary": child.get("Summary", {}).get("raw", ""),
        "State": current_state_name(child) or "init",
    }


def info_backlink_entry(child: JsonDict) -> JsonDict:
    """A parent Subtodos row for a child-declared informational back-link.

    `State` is INFO (follow-only, not a mergeable subtodo); `Summary` is a
    best-effort copy of the child's summary that doctor refreshes when sweeping.
    """
    summary_obj = child.get("Summary")
    summary = summary_obj.get("raw", "") if isinstance(summary_obj, dict) else ""
    return {
        "Id": str(child["Id"]),
        "Branch": str(child.get("Branch", "")),
        "Summary": summary,
        "State": SUBTODO_STATE_INFO,
    }


def upsert_info_backlink(parent: JsonDict, child: JsonDict) -> bool:
    """Ensure *parent*'s Subtodos carries an INFO back-link to *child*.

    Returns True when the parent changed. Never downgrades a real (tracked)
    subtodo entry to INFO -- if the child is already listed as a mergeable
    subtodo it is left untouched; an existing INFO entry gets its best-effort
    Summary/Branch refreshed.
    """
    entry = info_backlink_entry(child)
    subtodos: List[JsonDict] = list(parent.get("Subtodos") or [])
    for existing in subtodos:
        if existing.get("Id") == entry["Id"]:
            if existing.get("State") != SUBTODO_STATE_INFO:
                return False  # a real tracked subtodo -- do not clobber it
            if (
                existing.get("Summary") == entry["Summary"]
                and existing.get("Branch") == entry["Branch"]
            ):
                return False
            existing["Summary"] = entry["Summary"]
            existing["Branch"] = entry["Branch"]
            parent["Subtodos"] = subtodos
            return True
    subtodos.append(entry)
    parent["Subtodos"] = subtodos
    return True


def reestablish_backlinks(root: Path, child: JsonDict, *, dry_run: bool = False) -> List[str]:
    """Make each of *child*'s `Parent` refs point back at the child.

    For every parent the child references, ensure the parent's Subtodos carries
    an INFO back-link to this child (so a reader can follow parent -> child, not
    just child -> parent). Returns human descriptions of the back-links added or
    refreshed; writes them unless *dry_run*.

    Best-effort and sqlite-only: unresolvable and cross-repo parents are skipped
    (a write keys by the current repo, so persisting another repo's parent would
    misfile it), and legacy JSON mode -- where a write targets the current
    branch's file -- makes no changes.
    """
    if not use_sqlite():
        return []
    child_id = str(child.get("Id") or "")
    current = repo_key(root)
    repairs: List[str] = []
    seen: set = set()
    for ref in child.get("Parent") or []:
        if not isinstance(ref, dict):
            continue
        parent_id = str(ref.get("Id") or "")
        if not parent_id or parent_id in seen:
            continue
        seen.add(parent_id)
        try:
            loc, parent = resolve_ticket_by_id(root, parent_id)
        except TodoError:
            continue
        parent_repo = loc.rsplit(":", 1)[0] if ":" in loc else ""
        if parent_repo and parent_repo not in ("worktree", current):
            continue  # cross-repo parent: cannot safely persist here
        if str(parent.get("Id") or "") == child_id:
            continue  # never self-link
        if upsert_info_backlink(parent, child):
            repairs.append(f"parent {parent_id[:8]} <- INFO back-link {child_id[:8]}")
            if not dry_run:
                write_todo_worktree(root, parent)
    return repairs


def upsert_subtodo(parent: JsonDict, child: JsonDict) -> None:
    """Insert or refresh a Subtodos entry on *parent*."""
    entry = subtodo_entry_from_child(child)
    subtodos: List[JsonDict] = list(parent.get("Subtodos") or [])
    for index, existing in enumerate(subtodos):
        if existing.get("Id") == entry["Id"]:
            subtodos[index] = entry
            parent["Subtodos"] = subtodos
            return
    subtodos.append(entry)
    parent["Subtodos"] = subtodos


def update_subtodo_state(parent: JsonDict, child_id: str, state: str) -> None:
    """Set Subtodos[].State for *child_id* on *parent*."""
    subtodos: List[JsonDict] = list(parent.get("Subtodos") or [])
    found = False
    for entry in subtodos:
        if entry.get("Id") == child_id:
            entry["State"] = state
            found = True
            break
    if not found:
        raise TodoError(f"child Id {child_id[:8]} not listed in parent Subtodos")
    parent["Subtodos"] = subtodos


def apply_ticket_path(
    root: Path,
    selector: str,
    jsonpath: str,
    value: Any,
    *,
    stay: bool = False,
    no_commit: bool = False,
    no_clear: bool = False,
) -> Any:
    """Set *jsonpath* to an already-parsed *value* on a selected ticket."""
    origin_branch = current_branch(root)
    target_branch: Optional[str] = None
    if is_self_selector(selector):
        read_todo_current_branch(root)
    else:
        _, located = resolve_ticket_by_id(root, selector)
        target_branch = checkout_todo_branch(root, located)
    try:
        todo = read_todo_required(root)
        set_at_path(todo, jsonpath, value)
        write_todo_worktree(root, todo, no_clear=no_clear)
        if not no_commit:
            commit_todo(root, f"chore(todo): update {jsonpath}")
        return get_at_path(todo, jsonpath)
    finally:
        if (
            target_branch
            and origin_branch
            and origin_branch != target_branch
            and not stay
        ):
            run_git(root, "checkout", origin_branch, check=False)


def checkout_todo_branch(root: Path, todo: JsonDict) -> str:
    """Checkout the branch carrying *todo*; return the branch name."""
    branch = str(todo.get("Branch") or "")
    if not branch:
        raise TodoError("todo missing Branch")
    if not branch_exists(root, branch):
        raise TodoError(f"branch {branch!r} does not exist locally")
    run_git(root, "checkout", branch)
    return branch


def merge_subtodo(
    root: Path,
    child_selector: str,
    *,
    merged_into: Optional[str] = None,
    last_commit: Optional[str] = None,
) -> JsonDict:
    """Mark a child todo merged and update the checked-out parent."""
    parent_branch = current_branch(root)
    if not parent_branch:
        raise TodoError("detached HEAD; checkout parent branch first")
    parent = read_todo_required(root)
    _, child = resolve_ticket_by_selector(root, child_selector)
    child_id = str(child["Id"])
    child_branch = str(child.get("Branch") or "")
    if not child_branch:
        raise TodoError("child ticket missing Branch")
    child_state = current_state_name(child)
    if child_state not in {"done", "merged"}:
        raise TodoError(
            f"child {child_id[:8]} is {child_state!r}; expected done before merge-subtodo"
        )

    merge_target = merged_into or parent_branch
    run_git(root, "checkout", child_branch)
    child_worktree = read_todo_required(root)
    set_state(child_worktree, "merged", merged_into=merge_target, last_commit=last_commit)
    write_todo_worktree(root, child_worktree)
    commit_todo(root, f"chore(todo): merged into {merge_target}")

    # Prefer the child's ActualSummary (how the work actually panned out) over
    # its planned Summary for the merge message and work item node; fall back to
    # Summary.raw for children that never recorded one.
    child_summary = ""
    if isinstance(child.get("Summary"), dict):
        child_summary = str(child["Summary"].get("raw", ""))
    child_actual = str(child.get("ActualSummary") or "").strip()
    merge_message = child_actual or child_summary
    merge_subject = f"merge subtodo {child_id[:8]}"
    if merge_message:
        merge_subject += f": {_summary_snippet(merge_message)}"

    run_git(root, "checkout", parent_branch)
    parent = read_todo_required(root)
    update_subtodo_state(parent, child_id, "merged")
    write_todo_worktree(root, parent)
    # Marker commit first, then record its sha on the parent's cursor item as a
    # typed merge_subtodo done item. Keeping the workitem sha == HEAD upholds
    # "the last workitem is the last commit to the branch" (#6).
    commit_todo(root, f"chore(todo): {merge_subject}")
    merge_sha = head_sha(root) or ""
    index = mark_cursor_done(parent, merge_subtodo_workitem(child_id, merge_sha, summary=""))
    if not parent["WorkItems"][index].get("summary"):
        parent["WorkItems"][index]["summary"] = merge_subject
    write_todo_worktree(root, parent)
    return {"child": child_id, "State": "merged", "merged_into": merge_target, "sha": merge_sha}


def wait_for_state(
    root: Path,
    selectors: Sequence[str],
    *,
    target_state: str = "done",
    timeout: float = 300.0,
    interval: float = 5.0,
) -> List[str]:
    """Poll selected todos until each reaches *target_state*."""
    deadline = time.monotonic() + timeout
    remaining: List[str] = list(selectors)
    while True:
        still_waiting: List[str] = []
        for selector in remaining:
            _, todo = resolve_ticket_by_selector(root, selector)
            state = current_state_name(todo)
            if state != target_state:
                still_waiting.append(selector)
        if not still_waiting:
            return list(selectors)
        if time.monotonic() >= deadline:
            waiting = ", ".join(still_waiting)
            raise TodoError(f"timed out waiting for {target_state}: {waiting}")
        remaining = still_waiting
        sleep_for = min(interval, max(0.0, deadline - time.monotonic()))
        if sleep_for:
            time.sleep(sleep_for)


ALLOWED_TOP_LEVEL_FIELDS = frozenset(
    {
        "AC",
        "ActualSummary",
        "Agent",
        "BaseSha",
        "Body",
        "Branch",
        "Id",
        "Parent",
        "Scope",
        "State",
        "Subtodos",
        "Summary",
        "WorkItems",
        "create_dt",
        "update_dt",
    }
)
REQUIRED_TOP_LEVEL_FIELDS = frozenset({"Branch", "Id", "State", "Summary"})


def commit_exists(root: Path, sha: str) -> bool:
    """True when *sha* resolves to a commit in this repo (best effort)."""
    return run_git(root, "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0


def workitem_findings(todo: JsonDict) -> List[str]:
    """Hard findings for the WorkItems invariants (#1, #3, #6, #7)."""
    findings: List[str] = []
    items = todo.get("WorkItems")
    if items is None:
        return findings
    if not isinstance(items, list):
        return ["WorkItems must be a list"]
    seen_not_done = False
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue  # structural shape reported by wait_graph_findings
        kind = item.get("kind")
        if kind is not None and kind not in WORKITEM_KINDS:
            findings.append(f"WorkItems.{index}.kind {kind!r} is not valid")
        if not workitem_is_done(item):
            seen_not_done = True
            continue
        # done items must form a prefix -- none after a not-done item (#3)
        if seen_not_done:
            findings.append(f"WorkItems.{index} is done but follows a not-done item")
        k = workitem_kind(item)
        if k in (WORKITEM_CODE, WORKITEM_MERGE_SUBTODO) and not (
            isinstance(item.get("sha"), str) and item.get("sha")
        ):
            findings.append(f"WorkItems.{index} {k} item is missing a sha")
        if k in (WORKITEM_MERGE_SUBTODO, WORKITEM_START_SUBTODO) and not (
            isinstance(item.get("subtodo_id"), str) and item.get("subtodo_id")
        ):
            findings.append(f"WorkItems.{index} {k} item is missing subtodo_id")
    # a done todo must not end in start_subtodo -- it must be a code/merge commit (#6)
    if items and is_done(todo):
        last = items[-1]
        if isinstance(last, dict) and workitem_kind(last) == WORKITEM_START_SUBTODO:
            findings.append(
                "last work item is start_subtodo; a done todo must end in a code or merge commit (#6)"
            )
    return findings


TERMINAL_PARENT_STATES = ("done", "merged")


def unmerged_subtodos(todo: JsonDict) -> List[str]:
    """Describe each Subtodos entry not yet 'merged' on the parent record.

    Merge state is bookkept locally on the parent's Subtodos[].State (set by
    merge-subtodo), so this needs no child branch: it catches a child spawned
    via start_subtodo and never merged, including one that terminated in
    userneeded/stopped. Returns one label per unmerged child; the caller
    decides severity from the parent's own state.
    """
    subtodos = todo.get("Subtodos")
    if not isinstance(subtodos, list):
        return []
    labels: List[str] = []
    for index, entry in enumerate(subtodos):
        if not isinstance(entry, dict):
            continue
        state = entry.get("State")
        if state in ("merged", SUBTODO_STATE_INFO):
            continue  # merged, or a follow-only INFO back-link (not a subtodo)
        child_id = entry.get("Id")
        short = child_id[:8] if isinstance(child_id, str) and child_id else "?"
        labels.append(f"Subtodos.{index}.Id {short} is {state or 'unset'}, not merged")
    return labels


def doctor_findings(root: Path, selector: str) -> List[str]:
    """Return hard doctor findings for the selected todo (shape invariants)."""
    _, todo = resolve_ticket_by_selector(root, selector)
    findings: List[str] = []
    unknown = sorted(set(todo) - ALLOWED_TOP_LEVEL_FIELDS)
    if unknown:
        findings.append(f"unknown top-level fields: {', '.join(unknown)}")
    missing = sorted(field for field in REQUIRED_TOP_LEVEL_FIELDS if field not in todo)
    if missing:
        findings.append(f"missing required fields: {', '.join(missing)}")
    state = todo.get("State")
    if not isinstance(state, dict) or len(state) != 1:
        findings.append("State must be an object with exactly one key")
    else:
        state_name = next(iter(state.keys()))
        if state_name not in VALID_STATES:
            findings.append(f"invalid State {state_name!r}")
    summary = todo.get("Summary")
    if summary is not None and (
        not isinstance(summary, dict) or not isinstance(summary.get("raw"), str)
    ):
        findings.append("Summary.raw must be a string")
    subtodos = todo.get("Subtodos")
    if subtodos is not None:
        if not isinstance(subtodos, list):
            findings.append("Subtodos must be a list")
        else:
            for index, entry in enumerate(subtodos):
                if not isinstance(entry, dict):
                    findings.append(f"Subtodos.{index} must be an object")
                    continue
                child_id = entry.get("Id")
                if not isinstance(child_id, str) or not child_id:
                    findings.append(f"Subtodos.{index}.Id must be a string")
    # A done/merged parent must not leave any spawned subtodo unmerged
    # (parent synthesis last). While the parent is still working this is a soft
    # warning instead -- see doctor_warnings.
    parent_state = current_state_name(todo)
    if parent_state in TERMINAL_PARENT_STATES:
        for label in unmerged_subtodos(todo):
            findings.append(
                f"parent is {parent_state} but {label} "
                "(all subtodos must merge before the parent finishes)"
            )
    findings.extend(workitem_findings(todo))
    findings.extend(wait_graph_findings(root, todo))
    return findings


def doctor_warnings(root: Path, selector: str) -> List[str]:
    """Return soft doctor warnings that need an absent subbranch or other repo to
    verify. These never fail doctor, so transitional and cross-repo todos (where
    not every subbranch is available) do not hard-fail."""
    _, todo = resolve_ticket_by_selector(root, selector)
    warnings: List[str] = []
    base = todo.get("BaseSha")
    if isinstance(base, str) and base and not commit_exists(root, base):
        warnings.append(f"BaseSha {base[:8]} not found in this repo")
    subtodos = todo.get("Subtodos")
    if isinstance(subtodos, list):
        for index, entry in enumerate(subtodos):
            if not isinstance(entry, dict):
                continue
            child_id = entry.get("Id")
            if isinstance(child_id, str) and child_id:
                try:
                    resolve_ticket_by_selector(root, child_id[:8])
                except TodoError:
                    warnings.append(f"Subtodos.{index}.Id {child_id[:8]} not discoverable here")
    items = todo.get("WorkItems") or []
    if isinstance(items, list):
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            sha = item.get("sha")
            if isinstance(sha, str) and sha and not commit_exists(root, sha):
                warnings.append(f"WorkItems.{index}.sha {sha[:8]} not found in this repo")
            sub = item.get("subtodo_id")
            if isinstance(sub, str) and sub:
                try:
                    resolve_ticket_by_selector(root, sub[:8])
                except TodoError:
                    warnings.append(f"WorkItems.{index}.subtodo_id {sub[:8]} not discoverable here")
    # Surface unmerged subtodos while the parent is still open; once the parent
    # is done/merged this escalates to a hard finding (see doctor_findings).
    if current_state_name(todo) not in TERMINAL_PARENT_STATES:
        for label in unmerged_subtodos(todo):
            warnings.append(f"{label} (merge or waive before marking the parent done)")
    return warnings


def wait_graph_findings(root: Path, todo: JsonDict) -> List[str]:
    """Return findings for WorkItems wait_for references."""
    ticket_id = str(todo.get("Id") or "")
    findings: List[str] = []
    wait_targets: List[str] = []
    work_items = todo.get("WorkItems") or []
    if not isinstance(work_items, list):
        findings.append("WorkItems must be a list")
        return findings
    for index, item in enumerate(work_items):
        if not isinstance(item, dict):
            findings.append(f"WorkItems.{index} must be an object")
            continue
        execution = item.get("execution")
        if execution is None:
            continue
        if not isinstance(execution, dict):
            findings.append(f"WorkItems.{index}.execution must be an object")
            continue
        wait_for = execution.get("wait_for") or []
        if not isinstance(wait_for, list):
            findings.append(f"WorkItems.{index}.execution.wait_for must be a list")
            continue
        for child_selector in wait_for:
            if not isinstance(child_selector, str):
                findings.append(f"WorkItems.{index}.execution.wait_for entries must be strings")
                continue
            if ticket_id and id_matches(ticket_id, child_selector):
                findings.append(f"WorkItems.{index} waits on itself")
                continue
            try:
                resolve_ticket_by_selector(root, child_selector)
            except TodoError as exc:
                findings.append(f"WorkItems.{index} wait target not discoverable: {exc}")
                continue
            wait_targets.append(child_selector)
    findings.extend(wait_cycle_findings(root, ticket_id, wait_targets))
    return findings


def wait_targets_for_todo(todo: JsonDict) -> List[str]:
    """Return wait_for selectors from a todo's WorkItems."""
    targets: List[str] = []
    work_items = todo.get("WorkItems") or []
    if not isinstance(work_items, list):
        return targets
    for item in work_items:
        if not isinstance(item, dict):
            continue
        execution = item.get("execution")
        if not isinstance(execution, dict):
            continue
        wait_for = execution.get("wait_for") or []
        if not isinstance(wait_for, list):
            continue
        targets.extend(target for target in wait_for if isinstance(target, str))
    return targets


def wait_cycle_findings(root: Path, root_id: str, targets: Sequence[str]) -> List[str]:
    """Return dependency-cycle findings reachable from *root_id*."""
    if not root_id:
        return []
    findings: List[str] = []
    visited: set[str] = set()

    def visit(selector: str, stack: List[str]) -> None:
        """Depth-first traversal through discoverable wait_for targets."""
        try:
            _, child = resolve_ticket_by_selector(root, selector)
        except TodoError:
            return
        child_id = str(child.get("Id") or selector)
        if child_id in stack:
            cycle = stack[stack.index(child_id) :] + [child_id]
            findings.append("wait dependency cycle: " + " -> ".join(item[:8] for item in cycle))
            return
        if child_id in visited:
            return
        visited.add(child_id)
        for child_target in wait_targets_for_todo(child):
            visit(child_target, stack + [child_id])

    for target in targets:
        visit(target, [root_id])
    return findings


class TodoSubCommand(ABC):
    """Base for argparse-backed todo subcommands."""

    command_names: ClassVar[Sequence[str]] = ()
    doc_short: ClassVar[str] = ""
    doc_long: ClassVar[str] = ""

    def __init__(self, args: argparse.Namespace) -> None:
        """Copy parsed argparse fields onto the command object."""
        self.args = args
        for name, value in vars(args).items():
            if name != "command_cls":
                setattr(self, name, value)

    def __getattr__(self, name: str) -> Any:
        """Expose argparse fields as dynamic command attributes."""
        return getattr(self.args, name)

    @classmethod
    def register(cls, subparsers: argparse._SubParsersAction) -> None:
        """Attach this command class to the main argparse subparser collection."""
        for name in cls.command_names:
            parser: argparse.ArgumentParser = subparsers.add_parser(
                name,
                help=cls.doc_short,
                description=cls.doc_long,
            )
            cls.configure_parser(parser)
            parser.set_defaults(command_cls=cls)

    @classmethod
    @abstractmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register command-specific argparse fields."""

    @abstractmethod
    def do(self) -> int:
        """Execute the parsed command."""

    def root(self) -> Path:
        """Resolve the repo root from the current directory's gitroot.

        There is no --repo flag: cd to the target repo/worktree before invoking.
        repo_root() hard-errors if CWD is not a git repo.
        """
        return repo_root()


class MintCommand(TodoSubCommand):
    command_names = ("mint",)
    doc_short: ClassVar[str] = "Mint todo Id"
    doc_long: ClassVar[str] = (
        "Mint creates a new TODO identifier. It hashes a uuid1 value into the canonical "
        "64-character lowercase hex Id stored in TODO.json. Before returning the value, it checks "
        "existing branch and worktree todos for an 8-hex prefix collision. It prints only the Id so "
        "callers can capture it directly."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register mint arguments."""

    def do(self) -> int:
        """Print a collision-free todo Id."""
        print(mint_id(self.root()))
        return 0


_READ_FIRST_FIELDS = ("Id", "Summary", "Body")
_READ_LAST_FIELDS = ("Subtodos", "WorkItems")


def _ordered_subdict(value: JsonDict) -> JsonDict:
    """Order a Summary/Body dict as raw first, then remaining keys sorted."""
    out: JsonDict = {}
    if "raw" in value:
        out["raw"] = value["raw"]
    for key in sorted(k for k in value if k != "raw"):
        out[key] = value[key]
    return out


def order_ticket_fields(todo: JsonDict) -> JsonDict:
    """Return the ticket with Id/Summary/Body first and Subtodos/WorkItems last.

    Remaining fields keep a stable alphabetical order in the middle. Summary and
    Body are ordered so their raw text leads.
    """
    first = [k for k in _READ_FIRST_FIELDS if k in todo]
    last = [k for k in _READ_LAST_FIELDS if k in todo]
    fixed = set(_READ_FIRST_FIELDS) | set(_READ_LAST_FIELDS)
    middle = sorted(k for k in todo if k not in fixed)
    ordered: JsonDict = {}
    for key in first + middle + last:
        value = todo[key]
        if key in ("Summary", "Body") and isinstance(value, dict):
            ordered[key] = _ordered_subdict(value)
        else:
            ordered[key] = value
    return ordered


def elide_embedding_vectors(obj: Any) -> Any:
    """Recursively shorten embedding-like numeric lists to [first, last].

    An embedding is a list of more than two numbers (never bools). Shortening to
    the first and last elements keeps the output valid JSON while dropping the
    bulk of the vector. Other structures pass through unchanged.
    """
    if isinstance(obj, dict):
        return {k: elide_embedding_vectors(v) for k, v in obj.items()}
    if isinstance(obj, list):
        if len(obj) > 2 and all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in obj
        ):
            return [obj[0], obj[-1]]
        return [elide_embedding_vectors(x) for x in obj]
    return obj


class ReadCommand(TodoSubCommand):
    command_names = ("read",)
    doc_short: ClassVar[str] = "Print todo JSON"
    doc_long: ClassVar[str] = (
        "Read locates a TODO by full Id, by an unambiguous prefix of at least four hex "
        "characters, or by self/curr for the checked-out branch. It searches the current worktree "
        "first, then local and cached remote refs. Legacy field names are normalized and fields are "
        "ordered Id/Summary/Body first, Subtodos/WorkItems last. By default embedding vectors are "
        "elided to their first and last element; pass -v/--verbose to print them in full. The "
        "command prints the selected todo as formatted JSON to stdout."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register read arguments."""
        parser.add_argument("selector", help="todo selector: self, curr, Id prefix, or full digest")
        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help="print embedding vectors in full instead of eliding them",
        )

    def do(self) -> int:
        """Print the todo selected by selector."""
        root = self.root()
        git_fetch_if_remote(root)
        _, todo = resolve_ticket_by_selector(root, self.selector)
        normalize_todo_schema(todo)
        payload: Any = order_ticket_fields(todo)
        if not self.verbose:
            payload = elide_embedding_vectors(payload)
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0


class GetJsonPathCommand(TodoSubCommand):
    command_names = ("get-json-path",)
    doc_short: ClassVar[str] = "Print a JSON path value"
    doc_long: ClassVar[str] = (
        "Get-json-path locates a todo by selector and prints one internal dot-path value as JSON. "
        "It is the low-level read primitive for scripts that should not inspect TODO.json directly."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register get-json-path arguments."""
        parser.add_argument("selector", help="todo selector: self, curr, Id prefix, or full digest")
        parser.add_argument("jsonpath", help="dot path, e.g. Body.raw or WorkItems.0.summary")

    def do(self) -> int:
        """Print a selected path value."""
        root = self.root()
        _, todo = resolve_ticket_by_selector(root, self.selector)
        print_json_value(get_at_path(todo, self.jsonpath))
        return 0


class JqCommand(TodoSubCommand):
    command_names = ("jq",)
    doc_short: ClassVar[str] = "Run jq against todo"
    doc_long: ClassVar[str] = (
        "Jq locates a todo by selector, feeds the normalized todo JSON to the jq binary, and "
        "prints jq's stdout. This keeps all TODO.json access behind todo.py while preserving jq "
        "filter behavior."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register jq arguments."""
        parser.add_argument("selector", help="todo selector: self, curr, Id prefix, or full digest")
        parser.add_argument("filter", help="jq filter to run against the selected todo")

    def do(self) -> int:
        """Run jq over a selected ticket."""
        root = self.root()
        _, todo = resolve_ticket_by_selector(root, self.selector)
        payload = json.dumps(todo)
        try:
            result = subprocess.run(
                ["jq", self.filter],
                input=payload,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise TodoError("jq binary not found") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise TodoError(f"jq failed: {detail}")
        sys.stdout.write(result.stdout)
        return 0


class InitCommand(TodoSubCommand):
    command_names = ("init",)
    doc_short: ClassVar[str] = "Create todo branch"
    doc_long: ClassVar[str] = (
        "Init starts a new branch-bound TODO. It mints or accepts an Id, derives or accepts "
        "the branch name, writes the initial TODO.json skeleton, and commits it by default. It "
        "refuses to create a second TODO.json on a branch that already has one. It can optionally "
        "return to the parent branch after creating the todo branch. Pass --parent <id> "
        "(repeatable) to record parent/context todos on this one; the child points at the parent "
        "(walk up via 'todo.py prompt <id>' to see WHY), and the parent gets a follow-only INFO "
        "back-link in its Subtodos so a reader can follow parent -> child too. The INFO link is "
        "not a tracked subtodo -- it carries no merge obligation. For the full subtodo lifecycle "
        "(merge bookkeeping), use add-subtodo from the parent branch."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register init arguments."""
        parser.add_argument("--summary", required=True, help="Summary.raw")
        parser.add_argument("--body", default="", help="Body.raw")
        parser.add_argument("--ac", default="", help="acceptance criteria")
        parser.add_argument("--id", help="use pre-minted Id instead of minting")
        parser.add_argument("--branch", help="override Branch name")
        parser.add_argument("--path-from-root", help="Scope.path_from_root")
        parser.add_argument(
            "--parent",
            action="append",
            metavar="PARENT_ID",
            help="parent/context todo Id (repeatable); one-way reference for context",
        )
        parser.add_argument("--agent-type", help="agent type that created this todo (e.g. claude, cursor)")
        parser.add_argument("--session-id", help="agent session id that created this todo")
        parser.add_argument("--no-commit", action="store_true", help="skip git commit")
        parser.add_argument(
            "--stay-on-parent",
            action="store_true",
            help="return to previous branch after init (for child-style flows)",
        )

    def do(self) -> int:
        """Mint Id, create branch, write TODO.json, and optionally commit."""
        root = self.root()
        if read_todo_worktree(root) is not None:
            raise TodoError("todo already exists on current branch; resume it instead of init")

        ticket_id: str = self.id or mint_id(root)
        branch: str = self.branch or kebab_branch_name(ticket_id, self.summary)
        if branch_exists(root, branch):
            raise TodoError(f"branch {branch!r} already exists")

        agent_type = self.agent_type or os.environ.get("TODO_AGENT_TYPE")
        session_id = self.session_id or os.environ.get("TODO_SESSION_ID")
        parents: Optional[List[JsonDict]] = None
        if self.parent:
            parents = []
            for parent_id in self.parent:
                _loc, ptodo = resolve_ticket_by_id(root, parent_id)
                parents.append(
                    {"Id": str(ptodo["Id"]), "Branch": str(ptodo.get("Branch", ""))}
                )
        ticket = build_ticket_skeleton(
            root,
            ticket_id,
            branch,
            self.summary,
            self.body or "",
            self.ac or "",
            path_from_root=self.path_from_root,
            parent=parents,
            agent_type=agent_type,
            session_id=session_id,
        )

        parent_branch = current_branch(root)
        run_git(root, "checkout", "-b", branch)
        base = head_sha(root)  # branch's initial sha (invariant #5)
        if base:
            ticket["BaseSha"] = base
        write_todo_worktree(root, ticket)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): init ticket {ticket_id[:8]}")
        # Make the --parent references bidirectional: give each parent a
        # follow-only INFO back-link to this child (best-effort, same-repo).
        reestablish_backlinks(root, ticket, dry_run=False)
        if self.stay_on_parent and parent_branch:
            run_git(root, "checkout", parent_branch)
        print(json.dumps({"Id": ticket_id, "Branch": branch}, indent=2))
        return 0


class AddSubtodoCommand(TodoSubCommand):
    command_names = ("add-subtodo",)
    doc_short: ClassVar[str] = "Create child todo"
    doc_long: ClassVar[str] = (
        "Add-subtodo creates a child TODO from the current parent todo branch. It can "
        "load the child todo from JSON or build one from summary, body, and acceptance criteria. "
        "The command creates and commits the child branch, then returns to the parent branch. It "
        "registers the child in the parent's Subtodos list so later merge bookkeeping can find it."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register add-subtodo arguments."""
        parser.add_argument("--from-json", help="seed todo JSON (Id, Branch, fields)")
        parser.add_argument("--summary", help="Summary.raw when not using --from-json")
        parser.add_argument("--body", default="", help="Body.raw")
        parser.add_argument("--ac", default="", help="acceptance criteria")
        parser.add_argument("--id", help="pre-minted child Id")
        parser.add_argument("--branch", help="override Branch name")
        parser.add_argument("--path-from-root", help="Scope.path_from_root")

    def do(self) -> int:
        """Create a child branch + TODO.json from the current parent todo."""
        root = self.root()
        parent_branch = current_branch(root)
        if not parent_branch:
            raise TodoError("detached HEAD; checkout a parent branch first")

        parent = read_todo_required(root)
        if self.from_json:
            child_spec = load_json_file(Path(self.from_json))
        else:
            if not self.summary:
                raise TodoError("--summary is required unless --from-json is set")
            ticket_id = self.id or mint_id(root)
            branch = self.branch or kebab_branch_name(ticket_id, self.summary)
            child_spec = build_ticket_skeleton(
                root,
                ticket_id,
                branch,
                self.summary,
                self.body or "",
                self.ac or "",
                path_from_root=self.path_from_root,
                parent=[{"Id": parent["Id"], "Branch": parent_branch}],
                work_items=[],
            )

        child_id = str(child_spec.get("Id") or "")
        if not child_id:
            raise TodoError("child ticket must include Id")
        raw_summary = child_spec.get("Summary", {}).get("raw", "child")
        child_branch = str(child_spec.get("Branch") or kebab_branch_name(child_id, raw_summary))
        child_spec["Branch"] = child_branch
        child_spec["Parent"] = [{"Id": parent["Id"], "Branch": parent_branch}]
        scope = dict(child_spec.get("Scope") or {})
        scope["branch"] = child_branch
        scope.pop("path_to_project", None)
        remote = git_url_for_repo(root)
        if remote:
            scope.setdefault("git_url", remote)
        child_spec["Scope"] = scope
        if "create_dt" not in child_spec:
            child_spec["create_dt"] = utc_now()
        child_spec.setdefault("State", {"init": {}})

        if branch_exists(root, child_branch):
            raise TodoError(f"branch {child_branch!r} already exists")

        run_git(root, "checkout", "-b", child_branch)
        base = head_sha(root)  # child branch's initial sha (invariant #5)
        if base:
            child_spec["BaseSha"] = base
        write_todo_worktree(root, child_spec)
        commit_todo(root, f"chore(todo): init subtodo {child_id[:8]}")
        run_git(root, "checkout", parent_branch)

        upsert_subtodo(parent, child_spec)
        # Firing the subtodo completes the parent's cursor work item as a typed
        # start_subtodo done item and advances the cursor (invariants #1, #3).
        index = mark_cursor_done(parent, start_subtodo_workitem(child_id, summary=""))
        if not parent["WorkItems"][index].get("summary"):
            parent["WorkItems"][index]["summary"] = (
                f"start subtodo {child_id[:8]}: {_summary_snippet(raw_summary)}"
            )
        write_todo_worktree(root, parent)
        commit_todo(root, f"chore(todo): register subtodo {child_id[:8]} on parent")

        print(json.dumps({"Id": child_id, "Branch": child_branch, "Parent": parent_branch}, indent=2))
        return 0


class SetStateCommand(TodoSubCommand):
    command_names = ("set-state",)
    doc_short: ClassVar[str] = "Set todo state"
    doc_long: ClassVar[str] = (
        "Set-state replaces the current todo's State object with one of the supported workflow "
        "states. State-specific metadata such as owner, note, last commit, or merged-into can be "
        "recorded with the transition. --actual-summary records how the work actually panned out "
        "(vs the planned Summary); when this todo is later merged into a parent, that text becomes "
        "the merge commit subject and the parent's merge_subtodo work item summary. The command "
        "updates TODO.json and commits the change by default. It prints the new State object for "
        "confirmation."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register set-state arguments."""
        parser.add_argument(
            "state",
            choices=sorted(VALID_STATES - {"waiting", "N/a"}),
            help="new state",
        )
        parser.add_argument("--note", help="note for userneeded/stopped")
        parser.add_argument("--last-commit", help="last commit message for done/merged")
        parser.add_argument("--merged-into", help="parent branch name for merged")
        parser.add_argument("--owner", help="owner for working")
        parser.add_argument(
            "--actual-summary",
            help="ActualSummary: how the work actually panned out; reused as the merge "
            "message when this todo is merged into its parent",
        )
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Transition State on the current branch TODO.json."""
        root = self.root()
        todo = read_todo_required(root)
        set_state(
            todo,
            self.state,
            note=self.note,
            last_commit=self.last_commit,
            merged_into=self.merged_into,
            owner=self.owner,
        )
        if self.actual_summary is not None:
            todo["ActualSummary"] = self.actual_summary
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): state -> {self.state}")
        print(json.dumps(todo["State"], indent=2))
        return 0


class SetCommand(TodoSubCommand):
    command_names = ("set",)
    doc_short: ClassVar[str] = "Patch todo fields"
    doc_long: ClassVar[str] = (
        "Set edits the current branch's todo fields without changing branches. It updates "
        "Summary.raw, Body.raw, and/or AC. To replace WorkItems or any other JSON path from a file "
        "or stdin, use set-json-path. The command requires at least one field change and commits "
        "by default."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register set arguments."""
        parser.add_argument("--summary")
        parser.add_argument("--body")
        parser.add_argument("--ac")
        parser.add_argument("--no-commit", action="store_true")
        parser.add_argument(
            "--no-clear",
            action="store_true",
            help="keep existing embedding vectors even though raw text changed "
            "(for semantically trivial edits)",
        )

    def do(self) -> int:
        """Patch Summary/Body/AC on the current branch."""
        root = self.root()
        todo = read_todo_required(root)
        changed = False
        if self.summary is not None:
            todo.setdefault("Summary", {})["raw"] = self.summary
            changed = True
        if self.body is not None:
            todo.setdefault("Body", {})["raw"] = self.body
            changed = True
        if self.ac is not None:
            todo["AC"] = self.ac
            changed = True
        if not changed:
            raise TodoError("pass at least one of --summary, --body, --ac")
        write_todo_worktree(root, todo, no_clear=self.no_clear)
        if not self.no_commit:
            commit_todo(root, "chore(todo): update ticket fields")
        return 0


class WorkItemAddCommand(TodoSubCommand):
    command_names = ("work-item-add",)
    doc_short: ClassVar[str] = "Append work item"
    doc_long: ClassVar[str] = (
        "Work-item-add appends a new open WorkItems entry to the current todo. The entry stores "
        "the provided summary and starts with done set to false. Existing work items keep their "
        "order and content. The command writes TODO.json and commits by default."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-add arguments."""
        parser.add_argument("--summary", required=True)
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Append a not-done task work item to the current todo."""
        root = self.root()
        todo = read_todo_required(root)
        work_items: List[JsonDict] = list(todo.get("WorkItems") or [])
        work_items.append({"kind": WORKITEM_TASK, "summary": self.summary, "done": False})
        todo["WorkItems"] = work_items
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): add work item: {_summary_snippet(self.summary)}")
        return 0


class WorkItemDoneCommand(TodoSubCommand):
    command_names = ("work-item-done",)
    doc_short: ClassVar[str] = "Complete cursor work item as code"
    doc_long: ClassVar[str] = (
        "Work-item-done completes the current (cursor) work item as a typed 'code' item and "
        "advances the cursor. Its post-condition is a fully committed branch. If the tree is clean "
        "it records the branch's most recent commit, or a --sha that must match HEAD (mismatch "
        "exits 1). If the tree is dirty it commits all updates and new files (git add -A) and "
        "records the new HEAD sha; the commit message is -m when given, else the work item's "
        "summary. It adds no bookkeeping commit, so the recorded sha stays the branch HEAD "
        "(invariant #6). --summary overrides the item's high-level description (defaults to the "
        "cursor task's summary)."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-done arguments."""
        parser.add_argument("-m", "--message", help="commit message for a dirty tree (defaults to the work item summary)")
        parser.add_argument("--sha", help="commit sha for a clean tree; must equal HEAD")
        parser.add_argument("--summary", help="override the work item's high-level description")

    def do(self) -> int:
        """Complete the cursor work item as code (invariant #1).

        Post-condition: the branch is fully committed. A clean tree records the
        current HEAD; a dirty tree commits all updates and new files first."""
        root = self.root()
        todo = read_todo_required(root)
        dirty = bool(run_git(root, "status", "--porcelain", check=False).stdout.strip())
        if dirty:
            if self.sha:
                raise TodoError("--sha is not allowed with a dirty tree; a new commit will be made")
            message = self.message or self.summary or cursor_summary(todo) or "work-item-done"
            run_git(root, "add", "-A")
            run_git(root, "commit", "-m", message)
            sha = head_sha(root)
        else:
            head = head_sha(root)
            if not head:
                raise TodoError("no commits on branch; cannot record a code work item")
            if self.sha and self.sha != head:
                raise TodoError(
                    f"--sha {self.sha[:8]} does not match HEAD {head[:8]}; "
                    "commit your work or pass the current HEAD"
                )
            sha = head
        # Capture the full commit message recorded at `sha` so the WorkItem node itself
        # says what changed (e.g. which test files were added), not just the task summary.
        commit_message = run_git(root, "log", "-1", "--format=%B", str(sha), check=False).stdout.strip()
        item = code_workitem(str(sha), summary=self.summary or "", message=commit_message)
        index = mark_cursor_done(todo, item)
        write_todo_worktree(root, todo)
        summary = todo["WorkItems"][index].get("summary", "")
        print(
            json.dumps(
                {"index": index, "kind": WORKITEM_CODE, "sha": sha, "summary": summary, "message": commit_message},
                indent=2,
            )
        )
        return 0


class WorkItemReadCommand(TodoSubCommand):
    command_names = ("work-item-read",)
    doc_short: ClassVar[str] = "Read the cursor work item"
    doc_long: ClassVar[str] = (
        "Work-item-read prints the current work item -- the cursor, which is the first not-done "
        "item -- with its index, plus whether the todo is done. Index is null when there is no "
        "open item. It also emits a 'next' object: the deterministic mechanical command to advance "
        "the loop ({action, command}), including the finish sequence when the todo is done. 'next' "
        "is a mechanism hint, not policy -- a plain task defaults to work-item-done, but the agent "
        "may instead split it or turn it into a subtodo per the skill's dispatch table."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-read arguments."""
        parser.add_argument("selector", nargs="?", default="self", help="todo selector (default: self)")

    def do(self) -> int:
        """Print the cursor work item for the selected todo."""
        root = self.root()
        _, todo = resolve_ticket_by_selector(root, self.selector)
        normalize_todo_schema(todo)
        index = cursor_index(todo)
        items = todo.get("WorkItems") or []
        item = items[index] if index is not None else None
        print(
            json.dumps(
                {
                    "index": index,
                    "item": item,
                    "is_done": is_done(todo),
                    "next": next_action(todo),
                },
                indent=2,
            )
        )
        return 0


class WorkItemInsertCommand(TodoSubCommand):
    command_names = ("work-item-insert",)
    doc_short: ClassVar[str] = "Insert a task at the cursor"
    doc_long: ClassVar[str] = (
        "Work-item-insert adds a not-done task at the cursor so it becomes the current item, "
        "pushing the existing frontier down (used to explode a step into finer steps). It appends "
        "when the todo has no open item. Writes and commits by default."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-insert arguments."""
        parser.add_argument("--summary", required=True)
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Insert a not-done task at the cursor."""
        root = self.root()
        todo = read_todo_required(root)
        items: List[JsonDict] = list(todo.get("WorkItems") or [])
        new_item = {"kind": WORKITEM_TASK, "summary": self.summary, "done": False}
        index = cursor_index(todo)
        if index is None:
            items.append(new_item)
            index = len(items) - 1
        else:
            items.insert(index, new_item)
        todo["WorkItems"] = items
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): insert work item: {_summary_snippet(self.summary)}")
        print(json.dumps({"index": index, "summary": self.summary}, indent=2))
        return 0


class WorkItemReplaceCommand(TodoSubCommand):
    command_names = ("work-item-replace",)
    doc_short: ClassVar[str] = "Replace the cursor work item"
    doc_long: ClassVar[str] = (
        "Work-item-replace rewrites the current (cursor) task's freetext summary, leaving it "
        "not-done. Errors when there is no open item. Writes and commits by default."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-replace arguments."""
        parser.add_argument("--summary", required=True)
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Replace the cursor task's summary."""
        root = self.root()
        todo = read_todo_required(root)
        index = cursor_index(todo)
        if index is None:
            raise TodoError("no open work item to replace")
        items: List[JsonDict] = list(todo.get("WorkItems") or [])
        items[index] = {"kind": WORKITEM_TASK, "summary": self.summary, "done": False}
        todo["WorkItems"] = items
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): replace work item: {_summary_snippet(self.summary)}")
        print(json.dumps({"index": index, "summary": self.summary}, indent=2))
        return 0


class WorkItemDeleteCommand(TodoSubCommand):
    command_names = ("work-item-delete",)
    doc_short: ClassVar[str] = "Delete the cursor work item"
    doc_long: ClassVar[str] = (
        "Work-item-delete removes the current (cursor) not-done item. Done items are the "
        "committed history of the todo and are never the cursor, so they are never deleted here. "
        "Errors when there is no open item. Writes and commits by default."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-delete arguments."""
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Delete the cursor work item."""
        root = self.root()
        todo = read_todo_required(root)
        index = cursor_index(todo)
        if index is None:
            raise TodoError("no open work item to delete")
        items: List[JsonDict] = list(todo.get("WorkItems") or [])
        removed = items.pop(index)
        todo["WorkItems"] = items
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(
                root,
                f"chore(todo): delete work item: {_summary_snippet(removed.get('summary', ''))}",
            )
        print(json.dumps({"deleted_index": index, "summary": removed.get("summary", "")}, indent=2))
        return 0


class IsDoneCommand(TodoSubCommand):
    command_names = ("is-done",)
    doc_short: ClassVar[str] = "Report todo completion"
    doc_long: ClassVar[str] = (
        "Is-done reports whether the selected todo has no not-yet-done work items (invariant #7). "
        "It prints a small JSON object and exits 0 when done, 1 when not done, for use as a shell "
        "predicate."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register is-done arguments."""
        parser.add_argument("selector", nargs="?", default="self", help="todo selector (default: self)")

    def do(self) -> int:
        """Print and return the todo's done state."""
        root = self.root()
        _, todo = resolve_ticket_by_selector(root, self.selector)
        normalize_todo_schema(todo)
        done = is_done(todo)
        print(json.dumps({"id": str(todo.get("Id", ""))[:8], "is_done": done}, indent=2))
        return 0 if done else 1


class LastShaCommand(TodoSubCommand):
    command_names = ("last-sha",)
    doc_short: ClassVar[str] = "Print the last work item sha"
    doc_long: ClassVar[str] = (
        "Last-sha prints the sha of the selected todo's last work item, which is the last commit "
        "on its branch (invariant #6). Errors when the todo has no completed code/merge tail."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register last-sha arguments."""
        parser.add_argument("selector", nargs="?", default="self", help="todo selector (default: self)")

    def do(self) -> int:
        """Print the last work item's sha."""
        root = self.root()
        _, todo = resolve_ticket_by_selector(root, self.selector)
        normalize_todo_schema(todo)
        sha = last_sha(todo)
        if not sha:
            raise TodoError("no work item sha (todo has no completed code/merge tail)")
        print(sha)
        return 0


class SetJsonPathCommand(TodoSubCommand):
    command_names = ("set-json-path",)
    doc_short: ClassVar[str] = "Set a JSON path from stdin or file"
    doc_long: ClassVar[str] = (
        "Set-json-path sets any JSON path on a selected todo (e.g. WorkItems, Body.raw, "
        "WorkItems.0.summary) to a value read as JSON from --file, or from stdin by default. The "
        "input must be valid JSON. It checks out the target branch for a non-self selector, writes, "
        "and commits by default, returning to the previous branch unless --stay. This is the "
        "general way to replace WorkItems or seed a whole plan."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register set-json-path arguments."""
        parser.add_argument("selector", help="todo selector: self, curr, Id prefix, or full digest")
        parser.add_argument("jsonpath", help="dot path, e.g. WorkItems or Body.raw")
        parser.add_argument("--file", help="read the JSON value from this file (default: stdin)")
        parser.add_argument(
            "--stay",
            action="store_true",
            help="remain on the target branch after the write (default: return to previous branch)",
        )
        parser.add_argument("--no-commit", action="store_true")
        parser.add_argument(
            "--no-clear",
            action="store_true",
            help="keep existing embedding vectors even if this changes Summary.raw/"
            "Body.raw (for semantically trivial edits)",
        )

    def do(self) -> int:
        """Set a JSON path from a file or stdin."""
        root = self.root()
        if self.file is not None:
            try:
                text = Path(self.file).read_text(encoding="utf-8")
            except OSError as exc:
                raise TodoError(f"could not read {self.file}: {exc}") from exc
        else:
            text = sys.stdin.read()
        if not text.strip():
            raise TodoError("no JSON value provided (use --file or pipe a value via stdin)")
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TodoError(f"input is not valid JSON: {exc}") from exc
        updated = apply_ticket_path(
            root,
            self.selector,
            self.jsonpath,
            value,
            stay=self.stay,
            no_commit=self.no_commit,
            no_clear=self.no_clear,
        )
        print_json_value(updated)
        return 0


class MergeSubtodoCommand(TodoSubCommand):
    command_names = ("merge-subtodo",)
    doc_short: ClassVar[str] = "Record child merge"
    doc_long: ClassVar[str] = (
        "Merge-subtodo records that a child todo has been merged into its parent. It verifies "
        "the child todo is done or already merged, checks out the child branch, and marks the "
        "child State as merged. It then returns to the parent branch and updates the parent's "
        "Subtodos entry for that child. The command prints a small JSON merge summary."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register merge-subtodo arguments."""
        parser.add_argument("child_id", help="child todo Id prefix")
        parser.add_argument("--merged-into", help="parent branch name")
        parser.add_argument("--last-commit", help="optional merge commit message")

    def do(self) -> int:
        """Mark a child todo merged after parent absorbed its branch."""
        root = self.root()
        result = merge_subtodo(
            root,
            self.child_id,
            merged_into=self.merged_into,
            last_commit=self.last_commit,
        )
        print(json.dumps(result, indent=2))
        return 0


class WaitForCommand(TodoSubCommand):
    command_names = ("wait-for",)
    doc_short: ClassVar[str] = "Wait for todo state"
    doc_long: ClassVar[str] = (
        "Wait-for polls selected child todos until each reaches the requested state, done by "
        "default. Children signal progress by using set-state through todo.py; this command keeps "
        "the parent behind the same read interface instead of inspecting TODO.json directly."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register wait-for arguments."""
        parser.add_argument("selectors", nargs="+", help="todo selectors to wait on")
        parser.add_argument("--state", default="done", choices=sorted(VALID_STATES), help="target state")
        parser.add_argument("--timeout", type=float, default=300.0, help="seconds before failing")
        parser.add_argument("--interval", type=float, default=5.0, help="seconds between polls")

    def do(self) -> int:
        """Wait for selected todos to reach a state."""
        root = self.root()
        waited = wait_for_state(
            root,
            self.selectors,
            target_state=self.state,
            timeout=self.timeout,
            interval=self.interval,
        )
        print(json.dumps({"State": self.state, "selectors": waited}, indent=2))
        return 0


class WaitAndMergeCommand(TodoSubCommand):
    command_names = ("wait-and-merge",)
    doc_short: ClassVar[str] = "Wait and merge children"
    doc_long: ClassVar[str] = (
        "Wait-and-merge waits for child todos to reach done, then records each merge using the "
        "same merge-subtodo bookkeeping command. It is the barrier primitive for parent work items."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register wait-and-merge arguments."""
        parser.add_argument("child_ids", nargs="+", help="child todo selectors to merge")
        parser.add_argument("--timeout", type=float, default=300.0, help="seconds before failing")
        parser.add_argument("--interval", type=float, default=5.0, help="seconds between polls")
        parser.add_argument("--merged-into", help="parent branch name")
        parser.add_argument("--last-commit", help="optional merge commit message")

    def do(self) -> int:
        """Wait for children to be done, then merge them."""
        root = self.root()
        wait_for_state(
            root,
            self.child_ids,
            target_state="done",
            timeout=self.timeout,
            interval=self.interval,
        )
        results = [
            merge_subtodo(
                root,
                child_id,
                merged_into=self.merged_into,
                last_commit=self.last_commit,
            )
            for child_id in self.child_ids
        ]
        print(json.dumps({"merged": results}, indent=2))
        return 0


def _doctor_one(root: Path, selector: str, *, dry_run: bool) -> JsonDict:
    """Audit one todo and (unless dry_run) repair its parent back-links.

    Repair walks the audited todo's `Parent` refs and re-establishes a
    follow-only INFO back-link on each parent -- healing links that were
    one-way (legacy `init --parent`) or lost, and refreshing INFO summaries.
    """
    _loc, todo = resolve_ticket_by_selector(root, selector)
    findings = doctor_findings(root, selector)
    warnings = doctor_warnings(root, selector)
    repairs = reestablish_backlinks(root, todo, dry_run=dry_run)
    return {
        "id": str(todo.get("Id", ""))[:8],
        "ok": not findings,
        "findings": findings,
        "warnings": warnings,
        "repairs": repairs,
    }


class DoctorCommand(TodoSubCommand):
    command_names = ("doctor",)
    doc_short: ClassVar[str] = "Audit and repair todo health"
    doc_long: ClassVar[str] = (
        "Doctor audits a todo -- selector resolution, top-level schema, State shape, Subtodos "
        "references, and wait-graph sanity -- and repairs parent back-links: for each of the "
        "todo's --parent references it re-establishes a follow-only INFO back-link in the parent's "
        "Subtodos (best-effort, same-repo, sqlite only). Repair runs by default; pass --dry-run to "
        "audit and report intended repairs without writing. Repair also clears every stale per-TODO "
        "lock left by a crashed writer (reported as 'unlocked'). Pass --all to sweep the whole corpus "
        "instead of a single selector. Exit 1 when any hard finding is present."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register doctor arguments."""
        parser.add_argument(
            "selector",
            nargs="?",
            default="self",
            help="todo selector to audit (default: self; ignored with --all)",
        )
        parser.add_argument(
            "--all",
            dest="sweep_all",
            action="store_true",
            help="sweep every todo in the corpus instead of one selector",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="audit and report intended back-link repairs without writing",
        )

    def do(self) -> int:
        """Audit (and unless --dry-run, repair) one todo or the whole corpus."""
        root = self.root()
        # Clearing stale per-TODO locks is part of repair: a crashed writer can
        # leave a lock behind, so doctor drops them all (recovery escape hatch).
        # --dry-run only reports; it never mutates.
        unlocked = 0
        if not self.dry_run and use_sqlite():
            unlocked = todo_store.get_store().force_unlock_all()
        if self.sweep_all:
            if not use_sqlite():
                raise TodoError("--all requires the db store (unset TODO_USE_JSON)")
            ids = [str(t.get("Id", "")) for t in todo_store.get_store().list_all()]
            results = [_doctor_one(root, tid, dry_run=self.dry_run) for tid in ids if tid]
            ok = all(r["ok"] for r in results)
            print(
                json.dumps(
                    {
                        "ok": ok,
                        "dry_run": self.dry_run,
                        "unlocked": unlocked,
                        "audited": len(results),
                        "results": results,
                    },
                    indent=2,
                )
            )
            return 0 if ok else 1
        result = _doctor_one(root, self.selector, dry_run=self.dry_run)
        print(
            json.dumps(
                {
                    "ok": result["ok"],
                    "dry_run": self.dry_run,
                    "unlocked": unlocked,
                    "findings": result["findings"],
                    "warnings": result["warnings"],
                    "repairs": result["repairs"],
                },
                indent=2,
            )
        )
        return 0 if result["ok"] else 1


def _summary_snippet(text: str, limit: int = 60) -> str:
    """Collapse whitespace and truncate to a one-line commit subject."""
    s = " ".join(str(text).split())
    return s if len(s) <= limit else s[: limit - 3] + "..."


def _short_dt(value: str) -> str:
    """Trim an RFC3339 'Z' timestamp to 'YYYY-MM-DD HH:MM'."""
    return value.replace("T", " ")[:16] if value else ""


def _ticket_oneline(ticket: JsonDict, timestamps: bool = False) -> str:
    """Render '<Id[0:8]> [<dt>] <summary>  [<state>]' for the graph."""
    tid: str = str(ticket.get("Id", ""))[:8] or "????????"
    summary_obj = ticket.get("Summary")
    summary: str = summary_obj.get("raw", "") if isinstance(summary_obj, dict) else ""
    state: str = current_state_name(ticket) or "?"
    if timestamps:
        ts = _short_dt(str(ticket.get("update_dt") or ticket.get("create_dt") or ""))
        return f"{tid} {ts} {summary}  [{state}]"
    return f"{tid} {summary}  [{state}]"


def _entry_as_ticket(entry: JsonDict) -> JsonDict:
    """Minimal ticket built from a parent Subtodos row (used when the child file is unreachable)."""
    return {
        "Id": entry.get("Id", ""),
        "Summary": {"raw": entry.get("Summary", "")},
        "State": {str(entry.get("State", "init")): {}},
        "Subtodos": [],
    }


def _load_child_ticket(repo: Path, entry: JsonDict) -> Optional[JsonDict]:
    """Load a full child ticket via the Subtodos entry's Branch (O(1), no ref scan); fall back
    to a sqlite id-prefix lookup. None if neither resolves (caller uses the entry snapshot)."""
    branch = str(entry.get("Branch", ""))
    if branch:
        todo = read_todo_at_ref(repo, branch)
        if todo is not None:
            return todo
    cid = str(entry.get("Id", ""))
    if len(cid) >= 4 and use_sqlite():
        with todo_db.connection() as conn:
            for _repo_path, _branch, todo in todo_db.find_tickets_by_id_prefix(conn, cid[:8]):
                return todo
    return None


def _ticket_commits(repo: Path, ticket: JsonDict, timestamps: bool = False) -> List[str]:
    """Commit one-liners on a ticket's branch (its frequentcommit trail), newest first.

    Base = the Parent's branch for a subtodo, else the first of dev/main/master that
    exists. Returns [] when the branch or base cannot be resolved -- never dumps full
    history. This is the only place log reads git, and only under -v.
    """
    branch = str(ticket.get("Branch", ""))
    if not branch or not branch_exists(repo, branch):
        return []
    base: Optional[str] = None
    parents = ticket.get("Parent") or []
    primary = parents[0] if isinstance(parents, list) and parents else None
    if isinstance(primary, dict) and primary.get("Branch"):
        base = str(primary["Branch"])
    else:
        for cand in ("dev", "main", "master"):
            if branch_exists(repo, cand):
                base = cand
                break
    if not base or not branch_exists(repo, base):
        return []
    fmt = "%h %cd %s" if timestamps else "%h %s"
    cmd = ["git", "log", f"--format={fmt}"]
    env = None
    if timestamps:
        # UTC, to match the node's stored update_dt (RFC3339 Z) -- no mixed zones.
        cmd.append("--date=format-local:%Y-%m-%d %H:%M")
        env = {**os.environ, "TZ": "UTC0"}
    cmd.append(f"{base}..{branch}")
    result = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, check=False, env=env)
    if result.returncode != 0:
        return []
    return result.stdout.splitlines()


def render_ticket_graph(
    repo: Path,
    ticket: JsonDict,
    rails: List[bool],
    lines: List[str],
    seen: set[str],
    verbose: bool = False,
    timestamps: bool = False,
) -> None:
    """Append git-graph --oneline style lines for *ticket* and its Subtodos subtree.

    The graph STRUCTURE is derived purely from TODO.json: children are read by their
    Subtodos-entry Branch in *repo* (O(1), no ref scan). With *verbose*, each node also
    lists its branch commits (read from git via _ticket_commits). With *timestamps*, node
    lines carry the ticket update time and commit lines carry the commit date. The whole
    subtree shares *repo* because add-subtodo creates child branches in the parent's repo.
    """
    gutter: str = "".join("| " if open_rail else "  " for open_rail in rails)
    lines.append(f"{gutter}* {_ticket_oneline(ticket, timestamps)}")
    tid: str = str(ticket.get("Id", ""))
    if tid and tid in seen:
        return
    if tid:
        seen.add(tid)
    subs: List[JsonDict] = list(ticket.get("Subtodos") or [])
    if verbose:
        cont = gutter + ("| " if subs else "  ")
        for commit in _ticket_commits(repo, ticket, timestamps):
            lines.append(f"{cont}{commit}")
    for index, entry in enumerate(subs):
        is_last: bool = index == len(subs) - 1
        child = _load_child_ticket(repo, entry) or _entry_as_ticket(entry)
        render_ticket_graph(repo, child, rails + [not is_last], lines, seen, verbose, timestamps)


def discover_all_tickets(root: Path) -> Dict[str, JsonDict]:
    """Map Id -> ticket for every discoverable ticket in sqlite or git refs."""
    tickets: Dict[str, JsonDict] = {}
    if use_sqlite():
        with todo_db.connection() as conn:
            rows = conn.execute(
                "SELECT data FROM tickets WHERE repo_path = ?", (repo_key(root),)
            ).fetchall()
            for row in rows:
                parsed: Any = json.loads(str(row["data"]))
                if isinstance(parsed, dict) and parsed.get("Id"):
                    tickets[str(parsed["Id"])] = normalize_todo_schema(parsed)
        if tickets:
            return tickets
    worktree = read_todo_worktree(root)
    if worktree is not None and worktree.get("Id"):
        tickets[str(worktree["Id"])] = worktree
    for ref in list_branch_refs(root):
        ticket = read_todo_at_ref(root, ref)
        if ticket is None:
            continue
        tid = str(ticket.get("Id", ""))
        if tid and tid not in tickets:
            tickets[tid] = ticket
    return tickets


def forest_roots(root: Path) -> List[JsonDict]:
    """Discoverable tickets with no Parent (graph roots), ordered by create_dt."""
    tickets = discover_all_tickets(root)
    roots = [t for t in tickets.values() if not t.get("Parent")]
    roots.sort(key=lambda t: str(t.get("create_dt", "")))
    return roots


class LogCommand(TodoSubCommand):
    command_names = ("log",)
    doc_short: ClassVar[str] = "Show todo graph (oneline, from TODO.json)"
    doc_long: ClassVar[str] = (
        "Log renders the todo graph derived from TODO.json Subtodos relationships in "
        "git-log --graph --oneline style: one line per todo as "
        "'* <Id[0:8]> <summary>  [<state>]', with vertical rails for the subtodo tree. The "
        "graph is read entirely from TODO.json files through todo.py's own readers, never "
        "from git history. Selector is self/curr or a 4+ hex Id prefix (default self); --all "
        "renders every discoverable todo as a forest."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register log arguments."""
        parser.add_argument(
            "selector",
            nargs="?",
            default="self",
            help="todo selector: self, curr, or 4+ hex Id prefix (default: self)",
        )
        parser.add_argument(
            "--all",
            dest="all_tickets",
            action="store_true",
            help="render every discoverable todo as a forest",
        )
        parser.add_argument(
            "-n",
            "--max-count",
            type=int,
            default=None,
            help="limit the number of todo lines printed",
        )
        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help="under each todo, list its branch commits (the frequentcommit trail)",
        )
        parser.add_argument(
            "-t",
            "--timestamps",
            action="store_true",
            help="show timestamps: todo update time on nodes, commit date on -v commit lines",
        )

    def do(self) -> int:
        """Render the ticket graph from TODO.json (no git log)."""
        root = self.root()
        if self.all_tickets:
            roots = forest_roots(root)
            if not roots:
                raise TodoError("no TODO.json tickets found in this repo")
        else:
            _loc, ticket = resolve_ticket_by_selector(root, self.selector)
            roots = [ticket]
        lines: List[str] = []
        seen: set[str] = set()
        for ticket in roots:
            render_ticket_graph(
                root, ticket, [], lines, seen, self.verbose, self.timestamps
            )
        if self.max_count is not None:
            lines = lines[: self.max_count]
        # Truncate to terminal width on a TTY to avoid wrapping; leave full lines when
        # piped/redirected so downstream tools (grep, etc.) get complete output.
        width = shutil.get_terminal_size((80, 24)).columns if sys.stdout.isatty() else None
        if width and width > 3:
            lines = [ln if len(ln) <= width else ln[: width - 3] + "..." for ln in lines]
        print("\n".join(lines))
        return 0


class WebCommand(TodoSubCommand):
    command_names = ("web",)
    doc_short: ClassVar[str] = "Serve todo viewer"
    doc_long: ClassVar[str] = (
        "Web serves a viewer for a todo. Above a movable split it shows the todo's Id, Summary, "
        "Body, work items (horizontal boxes) and subtodos (horizontal boxes). Clicking a work "
        "item shows its full commit message and diff below the split and highlights any subtodo "
        "it references; clicking a subtodo highlights the work items that reference it and shows "
        "a read-only rendition below the split. With a selector (self, curr, or 4+ hex Id prefix) "
        "the printed URL opens straight onto that todo; without one the page is a vector search "
        "(the same ranking as 'todo search') over every todo, showing update-time and State "
        "columns, with an empty query listing all."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register web viewer arguments."""
        parser.add_argument(
            "selector",
            nargs="?",
            default=None,
            help="todo selector: self, curr, or 4+ hex Id prefix (default: search page)",
        )
        parser.add_argument("--host", default="127.0.0.1", help="bind host")
        parser.add_argument("--port", type=int, default=8765, help="bind port")
        parser.add_argument(
            "--dump-html",
            action="store_true",
            help="print the rendered HTML and exit instead of starting a server",
        )

    def do(self) -> int:
        """Serve or print the todo web viewer."""
        root = self.root()

        def resolve_todo(selector: str) -> tuple[Path, JsonDict]:
            """Resolve an ?id= selector to (repo_root, todo) for the viewer.

            The concrete repo is always the CWD; git failures for a todo whose
            commits are not present here render as 'diff unavailable'.
            """
            try:
                ticket = resolve_ticket_by_selector(root, selector)[1]
            except TodoError as exc:
                raise todo_web.TodoWebError(str(exc)) from exc
            return root, ticket

        def list_todos() -> List[JsonDict]:
            """Every todo in the store -- no repo scoping, no filtering."""
            if not use_sqlite():
                return list(discover_all_tickets(root).values())
            return [normalize_todo_schema(t) for t in todo_store.get_store().list_all()]

        def search_rows(query: str) -> List[JsonDict]:
            """Structured rows for the viewer's search box.

            A non-empty query runs the same vector search as `todo search`
            (rank order preserved); an empty query lists every todo. Rows carry
            state/update-time so the page can render the -tu/-s columns.
            """
            if query.strip():
                try:
                    return run_search(root, query)
                except TodoError as exc:
                    raise todo_web.TodoWebError(str(exc)) from exc
            return [todo_row(todo) for todo in list_todos()]

        initial_id: Optional[str] = None
        if self.selector is not None:
            _, ticket = resolve_ticket_by_selector(root, self.selector)
            initial_id = str(ticket.get("Id") or "") or None

        try:
            if self.dump_html:
                if initial_id is not None:
                    todo_root, ticket = resolve_todo(initial_id)
                    print(todo_web.render_todo_page(todo_root, ticket))
                else:
                    print(todo_web.render_search_page(root, search_rows("")))
            else:
                todo_web.serve(
                    root,
                    host=self.host,
                    port=self.port,
                    initial_id=initial_id,
                    resolver=resolve_todo,
                    searcher=search_rows,
                )
        except todo_web.TodoWebError as exc:
            raise TodoError(str(exc)) from exc
        return 0


class ImportJsonCommand(TodoSubCommand):
    command_names = ("import-json",)
    doc_short: ClassVar[str] = "Import legacy TODO.json into sqlite"
    doc_long: ClassVar[str] = (
        "Import-json loads todo JSON into the resolved todo sqlite db. Use --from-json for one file "
        "or --scan-refs to import every TODO.json on git refs in the current repo."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register import-json arguments."""
        parser.add_argument("--from-json", help="path to one TODO.json object")
        parser.add_argument("--branch", help="branch name override")
        parser.add_argument(
            "--scan-refs",
            action="store_true",
            help="import all TODO.json blobs from git refs",
        )

    def do(self) -> int:
        """Import legacy JSON ticket(s) into sqlite."""
        root = self.root()
        if self.scan_refs:
            count = import_all_json_refs(root)
            print(json.dumps({"imported": count}, indent=2))
            return 0
        if not self.from_json:
            raise TodoError("--from-json or --scan-refs is required")
        ticket = load_json_file(Path(self.from_json))
        imported = import_json_ticket(root, ticket, branch=self.branch)
        print(json.dumps({"Id": imported.get("Id"), "Branch": imported.get("Branch")}, indent=2))
        return 0


class _ColumnAction(argparse.Action):
    """Append a display column key to the shared 'columns' list in CLI order.

    Each -s/-t/-tc/-tu flag records its column key as it is encountered on the
    command line, so the selected columns render leftmost in argument order.
    """

    def __call__(self, parser, namespace, values, option_string=None):  # type: ignore[override]
        columns = list(getattr(namespace, self.dest, None) or [])
        columns.append(self.const)
        setattr(namespace, self.dest, columns)


def _add_column_args(parser: argparse.ArgumentParser) -> None:
    """Register the -s/-t/-tc/-tu display-column flags on *parser*.

    -s -> State, -t/-tc -> create time, -tu -> update time. Repeatable; the
    columns render leftmost in the order the flags are given.
    """
    parser.add_argument(
        "-s", dest="columns", const="state", nargs=0, action=_ColumnAction,
        help="show State column",
    )
    parser.add_argument(
        "-t", "-tc", dest="columns", const="ctime", nargs=0, action=_ColumnAction,
        help="show create-time column",
    )
    parser.add_argument(
        "-tu", dest="columns", const="utime", nargs=0, action=_ColumnAction,
        help="show update-time column",
    )


def _column_value(todo: JsonDict, key: str) -> str:
    """String value for a display-column *key* on *todo*."""
    if key == "state":
        return current_state_name(todo) or ""
    if key == "ctime":
        return str(todo.get("create_dt", "") or "")
    if key == "utime":
        return str(todo.get("update_dt", "") or "")
    return ""


def todo_row(todo: JsonDict) -> JsonDict:
    """Structured, JSON-serializable summary of a todo for ls/search/web.

    The single place list-style field extraction happens; callers (CLI line
    formatting, the web viewer's templates) render from these named fields
    rather than re-reading the raw todo, so there is one source of truth.
    """
    full = str(todo.get("Id", ""))
    summary = todo.get("Summary")
    summary = summary.get("raw", "") if isinstance(summary, dict) else str(summary or "")
    return {
        "id": full,
        "short": full[:8],
        "summary": summary,
        "state": _column_value(todo, "state"),
        "ctime": _column_value(todo, "ctime"),
        "utime": _column_value(todo, "utime"),
    }


def _format_row_line(row: JsonDict, columns: Sequence[str]) -> str:
    """'<cols>  <id[:8]>  <summary>' with selected columns leftmost, in order."""
    fields = [str(row.get(key, "")) for key in columns]
    fields.append(str(row.get("short", "")))
    fields.append(str(row.get("summary", "")))
    return "  ".join(fields)


def run_search(
    root: Path,
    query: str,
    *,
    limit: int = 20,
    embedder_names: Optional[Sequence[str]] = None,
    dry_run: bool = False,
) -> List[JsonDict]:
    """Ranked search as structured rows (relevance-rank order preserved).

    Shared by the 'search' subcommand and the web viewer so both go through the
    same vector-search backend without duplicating it.
    """
    hits = search_tickets(
        root, query, limit=limit, embedder_names=embedder_names, dry_run=dry_run
    )
    return [todo_row(todo) for todo in hits]


class SearchCommand(TodoSubCommand):
    command_names = ("search",)
    doc_short: ClassVar[str] = "Vector search todos"
    doc_long: ClassVar[str] = (
        "Search ranks todos by reciprocal-rank fusion over one or more embedders "
        "plus lexical overlap. --embedder takes a comma list (default: all "
        "non-hidden embedders; see the 'embedders' command). A requested embedder "
        "that is unavailable errors -- pick one explicitly. Missing vectors are "
        "backfilled and stored before ranking unless --dry-run; a ticket with no "
        "vector for an embedder just does not contribute to that embedder's rank. "
        "-s/-t/-tc/-tu add State/create-time/update-time columns (leftmost, in flag "
        "order); results stay in relevance-rank order."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register search arguments."""
        parser.add_argument("query", help="search phrase or keywords")
        parser.add_argument("-n", "--limit", type=int, default=20, help="max results")
        parser.add_argument(
            "--embedder",
            help="comma list of embedders (default: all non-hidden, e.g. hash,apple)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="rank against existing vectors only; do not backfill/store any",
        )
        _add_column_args(parser)

    def do(self) -> int:
        """Print ranked ticket search hits."""
        root = self.root()
        names: Optional[List[str]] = None
        if self.embedder:
            names = [part.strip() for part in self.embedder.split(",") if part.strip()]
        rows = run_search(
            root, self.query, limit=self.limit, embedder_names=names, dry_run=self.dry_run
        )
        columns = self.columns or []
        for row in rows:
            print(_format_row_line(row, columns))
        return 0


class EmbeddersCommand(TodoSubCommand):
    command_names = ("embedders",)
    doc_short: ClassVar[str] = "List selectable embedders"
    doc_long: ClassVar[str] = (
        "Embedders lists the embedders selectable via 'search --embedder'. The "
        "listed (non-hidden) set is also the default when --embedder is omitted. "
        "'cheap' embedders are auto-populated on every write; the rest are "
        "backfilled lazily at search time. Hidden test/opt-in embedders (e.g. st) "
        "are usable by exact name but not listed."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """No arguments."""

    def do(self) -> int:
        """Print one line per non-hidden embedder: name and cost."""
        for key, cheap, hidden in todo_embed.list_embedders():
            if hidden:
                continue
            print(f"{key}\t{'cheap' if cheap else 'expensive'}")
        return 0


class PromptCommand(TodoSubCommand):
    command_names = ("prompt",)
    doc_short: ClassVar[str] = "Print a todo + its parent chain as one startup prompt"
    doc_long: ClassVar[str] = (
        "Prompt concatenates the Summary/Body of a todo and its Parent chain "
        "(context references from init --parent included), farthest ancestors "
        "first and the target last, so a fresh agent with zero context reads WHY "
        "down to WHAT before starting. Read-only: it resolves parents from the db "
        "without checking out branches. Selector is self/curr or a 4+ hex Id "
        "prefix (default self)."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register prompt arguments."""
        parser.add_argument(
            "selector",
            nargs="?",
            default="self",
            help="todo selector: self, curr, or 4+ hex Id prefix (default self)",
        )

    def do(self) -> int:
        """Print the parent-chain startup prompt for the selected todo."""
        root = self.root()
        print(build_prompt_chain(root, self.selector))
        return 0


class LsCommand(TodoSubCommand):
    command_names = ("ls",)
    doc_short: ClassVar[str] = "List known todo ids and summaries"
    doc_long: ClassVar[str] = (
        "Ls prints one line per todo known to the resolved todo directory, as '<id[0:8]>  "
        "<summary>'. Where-to-find-it only; use 'read <id>' for full todo content. -s adds a "
        "State column, -t/-tc a create-time column, -tu an update-time column; selected columns "
        "print leftmost in the order the flags are given. With any column flag the rows sort "
        "ascending by the leftmost selected column (oldest first for times); otherwise insertion "
        "order."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register ls arguments."""
        _add_column_args(parser)

    def do(self) -> int:
        """Print '<cols>  <id>  <summary>' for every known todo."""
        if not use_sqlite():
            raise TodoError("ls requires the db store (unset TODO_USE_JSON)")
        columns = self.columns or []
        rows = [todo_row(todo) for todo in todo_store.get_store().list_all()]
        if columns:
            rows.sort(key=lambda row: str(row.get(columns[0], "")))
        for row in rows:
            print(_format_row_line(row, columns))
        return 0


class BaseDirCommand(TodoSubCommand):
    command_names = ("basedir",)
    doc_short: ClassVar[str] = "Print the todo base directory"
    doc_long: ClassVar[str] = (
        "Basedir prints the resolved todo base directory for this invocation -- where "
        "config.json, the ticket store (json files or sqlite.db), and worktrees live. "
        "Resolution order: $TODO_DIR, <main-checkout-root>/.todo, $HOME/.todo. The repo "
        "anchor is the repo's MAIN checkout root, not the current worktree, so all "
        "worktrees of a repo share one store."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Basedir takes no arguments."""

    def do(self) -> int:
        """Print the resolved todo base directory."""
        print(todo_db.todo_dir())
        return 0


class RepoDirCommand(TodoSubCommand):
    command_names = ("repodir",)
    doc_short: ClassVar[str] = "Print the repo directory a todo lives in"
    doc_long: ClassVar[str] = (
        "Repodir prints the concrete repo directory for the selected todo on this machine: "
        "the repo's MAIN checkout root (not the current worktree). Absolute paths are never "
        "stored -- the todo's repo name only identifies the repo (and warns if the CWD is a "
        "different one). Selector is self/curr or a 4+ hex Id prefix (default self)."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register repodir arguments."""
        parser.add_argument(
            "selector",
            nargs="?",
            default="self",
            help="todo selector: self, curr, or 4+ hex Id prefix (default: self)",
        )

    def do(self) -> int:
        """Print the repo's main checkout root for the selected todo."""
        root = self.root()
        resolve_ticket_by_selector(root, self.selector)  # validates id; warns on repo mismatch
        print(todo_db.main_checkout_root() or root)
        return 0


COMMAND_CLASSES: Sequence[type[TodoSubCommand]] = (
    MintCommand,
    LogCommand,
    WebCommand,
    LsCommand,
    BaseDirCommand,
    RepoDirCommand,
    ReadCommand,
    GetJsonPathCommand,
    JqCommand,
    InitCommand,
    AddSubtodoCommand,
    SetStateCommand,
    SetCommand,
    WorkItemAddCommand,
    WorkItemDoneCommand,
    WorkItemReadCommand,
    WorkItemInsertCommand,
    WorkItemReplaceCommand,
    WorkItemDeleteCommand,
    IsDoneCommand,
    LastShaCommand,
    SetJsonPathCommand,
    MergeSubtodoCommand,
    WaitForCommand,
    WaitAndMergeCommand,
    DoctorCommand,
    ImportJsonCommand,
    SearchCommand,
    EmbeddersCommand,
    PromptCommand,
)


TOP_LEVEL_EPILOG = """\
Repo & todo identity:
  gitroot      `git rev-parse --show-toplevel`: the CURRENT working tree (a
               linked worktree when in one). Used for git operations.
  main checkout root
               the repo's PRIMARY working tree (first `git worktree list` entry).
               The STORAGE anchor: the todo store lives at <it>/.todo/, so all
               worktrees of a repo share one store. Git ops still use gitroot.
  TODO branch  a git repo branch that carries a todo in sqlite.
  todo dir     resolved once per invocation: $TODO_DIR, else
               <main-checkout-root>/.todo, else ~/.todo (first with sqlite.db
               wins; same dir for db and worktrees).
  FQT          fully-qualified todo = repo-root + todo_id (the branch name is a
               git-storage artifact, so repo-root + branch-name is an accepted
               fallback for todos written on dev/master).

Repo selection:
  The repo root is the CURRENT directory's gitroot; there is no --repo flag.
  `cd` into the target repo or worktree before invoking. todo.py hard-errors if
  CWD is not a git repo. Find other checkouts with `git worktree list`; new
  worktrees go under <todo-dir>/worktrees/<repo-path>/<branch> by convention.
"""


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argparse parser."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="todo.py",
        description=(
            "Branch-bound todo CLI (sqlite-backed). Repo root is the current "
            "directory's gitroot (cd to the target repo; no --repo flag); "
            "hard-errors if CWD is not a git repo."
        ),
        epilog=TOP_LEVEL_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub: argparse._SubParsersAction = parser.add_subparsers(
        dest="command",
        required=True,
    )

    for command_cls in COMMAND_CLASSES:
        command_cls.register(sub)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point."""
    parser: argparse.ArgumentParser = build_parser()
    args: argparse.Namespace = parser.parse_args(argv)
    try:
        command: TodoSubCommand = args.command_cls(args)
        return int(command.do())
    except todo_store.LockTimeout as exc:
        # EX_TEMPFAIL: transient per-TODO lock contention. The caller should
        # retry rather than treat this as a hard failure.
        print(f"todo.py: ERETRY: {exc}", file=sys.stderr)
        return 75
    except todo_store.TodoStoreError as exc:
        print(f"todo.py: {exc}", file=sys.stderr)
        return 1
    except TodoError as exc:
        print(f"todo.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

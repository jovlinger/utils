#!/usr/bin/env python3
"""AWS-style CLI for branch-bound TODO.json tickets."""

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
import todo_web

JsonDict = Dict[str, Any]

# Re-export for callers that import from todo.py.
worktrees_dir = todo_db.worktrees_dir
db_path = todo_db.db_path

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
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
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
    """Migrate legacy field names (Chunks, Subtickets) to WorkItems, Subtodos."""
    if "Chunks" in todo and "WorkItems" not in todo:
        todo["WorkItems"] = todo.pop("Chunks")
    if "Subtickets" in todo and "Subtodos" not in todo:
        todo["Subtodos"] = todo.pop("Subtickets")
    return todo


def read_todo_at_ref(root: Path, ref: str) -> Optional[JsonDict]:
    """Return parsed TODO.json from *ref*, or None if missing or invalid."""
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


def read_todo_worktree(root: Path) -> Optional[JsonDict]:
    """Return parsed worktree TODO.json when present."""
    path: Path = root / "TODO.json"
    if not path.is_file():
        return None
    try:
        parsed: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return normalize_todo_schema(parsed)


def read_todo_required(root: Path) -> JsonDict:
    """Return parsed TODO.json from the worktree or raise."""
    todo = read_todo_worktree(root)
    if todo is None:
        raise TodoError("TODO.json not found on current branch")
    return todo


def write_todo_worktree(root: Path, todo: JsonDict) -> None:
    """Atomically write TODO.json in the worktree."""
    normalize_todo_schema(todo)
    todo["update_dt"] = utc_now()
    path: Path = root / "TODO.json"
    tmp: Path = root / "TODO.json.tmp"
    tmp.write_text(json.dumps(todo, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


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
        raise TodoError(f"no TODO.json found on current branch {branch!r}")
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
    parent: Optional[JsonDict] = None,
    work_items: Optional[List[JsonDict]] = None,
    agent_type: Optional[str] = None,
    session_id: Optional[str] = None,
) -> JsonDict:
    """Construct a fresh TODO.json object."""
    now = utc_now()
    scope: JsonDict = {
        "path_to_project": str(root),
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


def commit_todo(root: Path, message: str) -> None:
    """Stage and commit TODO.json on the current branch."""
    if not (root / "TODO.json").is_file():
        raise TodoError("TODO.json missing; nothing to commit")
    run_git(root, "add", "TODO.json")
    run_git(root, "commit", "-m", message, check=False)


def catalog_path() -> Path:
    """Path of the append-only todo catalog (override with $TODO_CATALOG_PATH)."""
    override = os.environ.get("TODO_CATALOG_PATH")
    return Path(override) if override else Path.home() / ".todo" / "catalog.txt"


def catalog_line(repo: Path, ticket: JsonDict) -> str:
    """One catalog row: repo(30) id(10) branch(30) summary -- where to find a todo, not its content."""
    rid: str = str(ticket.get("Id", ""))[:8]
    branch: str = str(ticket.get("Branch", ""))
    summary_obj = ticket.get("Summary")
    summary: str = summary_obj.get("raw", "") if isinstance(summary_obj, dict) else ""
    summary = " ".join(summary.split())[:60]
    return f"{str(repo):<30} {rid:<10} {branch:<30} {summary}"


def append_catalog(repo: Path, ticket: JsonDict) -> None:
    """Append a row to the catalog (append-only; best-effort -- never fails the caller)."""
    try:
        path = catalog_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(catalog_line(repo, ticket) + "\n")
    except OSError as exc:
        print(f"todo.py: catalog append failed: {exc}", file=sys.stderr)


def parse_catalog() -> List[JsonDict]:
    """Read catalog rows as {repo, id, branch, summary} dicts (empty if no catalog)."""
    path = catalog_path()
    rows: List[JsonDict] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 3)  # repo/id/branch have no spaces; summary is the rest
        if len(parts) < 3:
            continue
        rows.append(
            {
                "repo": parts[0],
                "id": parts[1],
                "branch": parts[2],
                "summary": parts[3] if len(parts) > 3 else "",
            }
        )
    return rows


def catalog_matches(query: str) -> List[tuple[str, JsonDict]]:
    """Resolve *query* via the catalog -- read each matching repo:branch directly.

    Fast path: it avoids scanning every git ref and works across repos. Rows whose
    repo/branch no longer resolve are skipped silently.
    """
    found: List[tuple[str, JsonDict]] = []
    seen: set[str] = set()
    for row in parse_catalog():
        cid = str(row.get("id", ""))
        if not cid or not (cid.startswith(query) or query.startswith(cid)):
            continue
        repo = Path(str(row.get("repo", "")))
        if not repo.is_dir():
            continue
        todo = read_todo_at_ref(repo, str(row.get("branch", "")))
        if todo is None:
            continue
        tid = str(todo.get("Id", ""))
        if tid and id_matches(tid, query) and tid not in seen:
            found.append((f"{repo}:{row.get('branch', '')}", todo))
            seen.add(tid)
    return found


def find_todos_by_id(root: Path, query: str) -> List[tuple[str, JsonDict]]:
    """Locate TODO.json blobs whose Id matches *query*: current worktree, then the
    catalog (fast, cross-repo), and only then a full ref scan of the current repo."""
    matches: List[tuple[str, JsonDict]] = []
    seen_ids: set[str] = set()

    branch: Optional[str] = current_branch(root)
    worktree: Optional[JsonDict] = read_todo_worktree(root)
    if worktree is not None:
        ticket_id: str = str(worktree.get("Id", ""))
        if ticket_id and id_matches(ticket_id, query):
            loc: str = f"worktree:{branch or 'detached'}"
            matches.append((loc, worktree))
            seen_ids.add(ticket_id)

    # Fast path: the catalog says exactly where catalogued todos live, so we can
    # answer without the expensive all-refs scan (and across repos). Only short-
    # circuit when the catalog actually answers -- a bare worktree match still
    # needs the ref scan so cross-branch ambiguity is detected.
    cat = catalog_matches(query)
    if cat:
        for loc, todo in cat:
            tid = str(todo.get("Id", ""))
            if tid and tid not in seen_ids:
                matches.append((loc, todo))
                seen_ids.add(tid)
        return matches

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
        raise TodoError(f"no TODO.json found for id {query!r}")
    if len(matches) > 1:
        locations: str = ", ".join(loc for loc, _ in matches)
        raise TodoError(f"ambiguous id {query!r}; matches on: {locations}")
    return matches[0]


def resolve_ticket_by_selector(root: Path, selector: str) -> tuple[str, JsonDict]:
    """Return the ticket selected by id prefix or self/curr."""
    if is_self_selector(selector):
        return read_todo_current_branch(root)
    return resolve_ticket_by_id(root, selector)


def mint_id(root: Path, attempts: int = 1000) -> str:
    """Mint a fresh ticket Id with no 8-hex prefix clash in the repo."""
    for _ in range(attempts):
        ticket_id: str = hashlib.sha256(uuid.uuid1().bytes).hexdigest()
        if not find_todos_by_id(root, ticket_id[:8]):
            return ticket_id
    raise TodoError("could not mint a collision-free Id")


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


def parse_update_value(raw: Optional[str], *, from_stdin: bool) -> Any:
    """Parse a CLI or stdin value for ``update`` (JSON when unambiguous, else string)."""
    if from_stdin:
        text = sys.stdin.read()
        if not text:
            raise TodoError("stdin value is empty")
        stripped = text.strip()
        if stripped.startswith(("{", "[")):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise TodoError(f"stdin is not valid JSON: {exc}") from exc
        return text.rstrip("\n")
    if raw is None:
        raise TodoError("value is required unless reading from stdin with '-'")
    if raw == "-":
        return parse_update_value(None, from_stdin=True)
    if raw.startswith(("{", "[")):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TodoError(f"value is not valid JSON: {exc}") from exc
    if raw in {"true", "false", "null"}:
        return json.loads(raw)
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    return raw


def subtodo_entry_from_child(child: JsonDict) -> JsonDict:
    """Build a parent Subtodos row from a child todo."""
    return {
        "Id": child["Id"],
        "Branch": child.get("Branch", ""),
        "Summary": child.get("Summary", {}).get("raw", ""),
        "State": current_state_name(child) or "init",
    }


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


def update_ticket_path(
    root: Path,
    selector: str,
    jsonpath: str,
    raw_value: str,
    *,
    stay: bool = False,
    no_commit: bool = False,
) -> Any:
    """Set *jsonpath* on a selected ticket and return the updated value."""
    origin_branch = current_branch(root)
    target_branch: Optional[str] = None
    if is_self_selector(selector):
        read_todo_current_branch(root)
    else:
        _, located = resolve_ticket_by_id(root, selector)
        target_branch = checkout_todo_branch(root, located)
    try:
        todo = read_todo_required(root)
        value = parse_update_value(raw_value, from_stdin=(raw_value == "-"))
        set_at_path(todo, jsonpath, value)
        write_todo_worktree(root, todo)
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

    run_git(root, "checkout", parent_branch)
    parent = read_todo_required(root)
    update_subtodo_state(parent, child_id, "merged")
    write_todo_worktree(root, parent)
    commit_todo(root, f"chore(todo): subtodo {child_id[:8]} merged")
    return {"child": child_id, "State": "merged", "merged_into": merge_target}


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
        "Agent",
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


def doctor_findings(root: Path, selector: str) -> List[str]:
    """Return doctor findings for the selected todo."""
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
                    continue
                try:
                    resolve_ticket_by_selector(root, child_id[:8])
                except TodoError as exc:
                    findings.append(f"Subtodos.{index}.Id not discoverable: {exc}")
    findings.extend(wait_graph_findings(root, todo))
    return findings


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
    doc_short: ClassVar[str] = "Mint ticket Id"
    doc_long: ClassVar[str] = (
        "Mint creates a new TODO ticket identifier. It hashes a uuid1 value into the canonical "
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


class ReadCommand(TodoSubCommand):
    command_names = ("read",)
    doc_short: ClassVar[str] = "Print ticket JSON"
    doc_long: ClassVar[str] = (
        "Read locates a TODO ticket by full Id, by an unambiguous prefix of at least four hex "
        "characters, or by self/curr for the checked-out branch. It searches the current worktree "
        "first, then local and cached remote refs. Legacy field names are normalized in the output. "
        "The command prints the selected ticket as formatted JSON to stdout."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register read arguments."""
        parser.add_argument("selector", help="ticket selector: self, curr, Id prefix, or full digest")

    def do(self) -> int:
        """Print the todo selected by selector."""
        root = self.root()
        git_fetch_if_remote(root)
        _, todo = resolve_ticket_by_selector(root, self.selector)
        normalize_todo_schema(todo)
        json.dump(todo, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0


class ReadPathCommand(TodoSubCommand):
    command_names = ("read-path",)
    doc_short: ClassVar[str] = "Print ticket path"
    doc_long: ClassVar[str] = (
        "Read-path locates a ticket by selector and prints one internal dot-path value. It is the "
        "low-level read primitive for scripts that should not inspect TODO.json directly."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register read-path arguments."""
        parser.add_argument("selector", help="ticket selector: self, curr, Id prefix, or full digest")
        parser.add_argument("jsonpath", help="dot path, e.g. Body.raw or WorkItems.0.summary")

    def do(self) -> int:
        """Print a selected path value."""
        root = self.root()
        _, todo = resolve_ticket_by_selector(root, self.selector)
        print_json_value(get_at_path(todo, self.jsonpath))
        return 0


class JqCommand(TodoSubCommand):
    command_names = ("jq",)
    doc_short: ClassVar[str] = "Run jq against ticket"
    doc_long: ClassVar[str] = (
        "Jq locates a ticket by selector, feeds the normalized ticket JSON to the jq binary, and "
        "prints jq's stdout. This keeps all TODO.json access behind todo.py while preserving jq "
        "filter behavior."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register jq arguments."""
        parser.add_argument("selector", help="ticket selector: self, curr, Id prefix, or full digest")
        parser.add_argument("filter", help="jq filter to run against the selected ticket")

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
    doc_short: ClassVar[str] = "Create ticket branch"
    doc_long: ClassVar[str] = (
        "Init starts a new branch-bound TODO ticket. It mints or accepts an Id, derives or accepts "
        "the branch name, writes the initial TODO.json skeleton, and commits it by default. It "
        "refuses to create a second TODO.json on a branch that already has one. It can optionally "
        "return to the parent branch after creating the ticket branch."
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
            raise TodoError("TODO.json already exists on current branch; resume it instead of init")

        ticket_id: str = self.id or mint_id(root)
        branch: str = self.branch or kebab_branch_name(ticket_id, self.summary)
        if branch_exists(root, branch):
            raise TodoError(f"branch {branch!r} already exists")

        agent_type = self.agent_type or os.environ.get("TODO_AGENT_TYPE")
        session_id = self.session_id or os.environ.get("TODO_SESSION_ID")
        ticket = build_ticket_skeleton(
            root,
            ticket_id,
            branch,
            self.summary,
            self.body or "",
            self.ac or "",
            path_from_root=self.path_from_root,
            agent_type=agent_type,
            session_id=session_id,
        )

        parent_branch = current_branch(root)
        run_git(root, "checkout", "-b", branch)
        write_todo_worktree(root, ticket)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): init ticket {ticket_id[:8]}")
        append_catalog(root, ticket)
        if self.stay_on_parent and parent_branch:
            run_git(root, "checkout", parent_branch)
        print(json.dumps({"Id": ticket_id, "Branch": branch}, indent=2))
        return 0


class AddSubtodoCommand(TodoSubCommand):
    command_names = ("add-subtodo", "add-child")
    doc_short: ClassVar[str] = "Create child ticket"
    doc_long: ClassVar[str] = (
        "Add-subtodo creates a child TODO ticket from the current parent ticket branch. It can "
        "load the child ticket from JSON or build one from summary, body, and acceptance criteria. "
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
                parent={"Id": parent["Id"], "Branch": parent_branch},
                work_items=[],
            )

        child_id = str(child_spec.get("Id") or "")
        if not child_id:
            raise TodoError("child ticket must include Id")
        raw_summary = child_spec.get("Summary", {}).get("raw", "child")
        child_branch = str(child_spec.get("Branch") or kebab_branch_name(child_id, raw_summary))
        child_spec["Branch"] = child_branch
        child_spec["Parent"] = {"Id": parent["Id"], "Branch": parent_branch}
        scope = dict(child_spec.get("Scope") or {})
        scope["branch"] = child_branch
        scope.setdefault("path_to_project", str(root))
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
        write_todo_worktree(root, child_spec)
        commit_todo(root, f"chore(todo): init subtodo {child_id[:8]}")
        run_git(root, "checkout", parent_branch)

        upsert_subtodo(parent, child_spec)
        write_todo_worktree(root, parent)
        commit_todo(root, f"chore(todo): register subtodo {child_id[:8]} on parent")

        print(json.dumps({"Id": child_id, "Branch": child_branch, "Parent": parent_branch}, indent=2))
        return 0


class SetStateCommand(TodoSubCommand):
    command_names = ("set-state",)
    doc_short: ClassVar[str] = "Set ticket state"
    doc_long: ClassVar[str] = (
        "Set-state replaces the current ticket's State object with one of the supported workflow "
        "states. State-specific metadata such as owner, note, last commit, or merged-into can be "
        "recorded with the transition. The command updates TODO.json and commits the change by "
        "default. It prints the new State object for confirmation."
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
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): state -> {self.state}")
        print(json.dumps(todo["State"], indent=2))
        return 0


class SetCommand(TodoSubCommand):
    command_names = ("set",)
    doc_short: ClassVar[str] = "Patch ticket fields"
    doc_long: ClassVar[str] = (
        "Set edits the current branch's ticket fields without changing branches. It can update "
        "Summary.raw, Body.raw, AC, or replace WorkItems from a JSON array file. The deprecated "
        "chunks-file option is treated as a WorkItems replacement for compatibility. The command "
        "requires at least one field change and commits by default."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register set arguments."""
        parser.add_argument("--summary")
        parser.add_argument("--body")
        parser.add_argument("--ac")
        parser.add_argument("--work-items-file", help="replace WorkItems with JSON array from file")
        parser.add_argument("--chunks-file", help="deprecated alias for --work-items-file")
        parser.add_argument("--no-commit", action="store_true")

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
        if self.work_items_file is not None:
            work_items_path = Path(self.work_items_file)
            try:
                work_items_payload: Any = json.loads(work_items_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise TodoError(f"could not read JSON from {work_items_path}: {exc}") from exc
            if not isinstance(work_items_payload, list):
                raise TodoError("--work-items-file must contain a JSON array")
            todo["WorkItems"] = work_items_payload
            changed = True
        elif self.chunks_file is not None:
            chunks_path = Path(self.chunks_file)
            try:
                chunks_payload: Any = json.loads(chunks_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise TodoError(f"could not read JSON from {chunks_path}: {exc}") from exc
            if not isinstance(chunks_payload, list):
                raise TodoError("--chunks-file must contain a JSON array")
            todo["WorkItems"] = chunks_payload
            changed = True
        if not changed:
            raise TodoError("pass at least one of --summary, --body, --ac, --work-items-file, --chunks-file")
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, "chore(todo): update ticket fields")
        return 0


class WorkItemAddCommand(TodoSubCommand):
    command_names = ("work-item-add", "chunk-add")
    doc_short: ClassVar[str] = "Append work item"
    doc_long: ClassVar[str] = (
        "Work-item-add appends a new open WorkItems entry to the current ticket. The entry stores "
        "the provided summary and starts with done set to false. Existing work items keep their "
        "order and content. The command writes TODO.json and commits by default."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-add arguments."""
        parser.add_argument("--summary", required=True)
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Append a work item to the current todo."""
        root = self.root()
        todo = read_todo_required(root)
        work_items: List[JsonDict] = list(todo.get("WorkItems") or [])
        work_items.append({"summary": self.summary, "done": False})
        todo["WorkItems"] = work_items
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(root, f"chore(todo): add work item: {_summary_snippet(self.summary)}")
        return 0


class WorkItemDoneCommand(TodoSubCommand):
    command_names = ("work-item-done", "chunk-done")
    doc_short: ClassVar[str] = "Complete work item"
    doc_long: ClassVar[str] = (
        "Work-item-done marks one WorkItems entry complete on the current ticket. With no index, "
        "it selects the first item whose done field is not true. With an index, it updates that "
        "specific zero-based item and errors if the index is out of range. The command writes "
        "TODO.json and commits by default."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register work-item-done arguments."""
        parser.add_argument("--index", type=int, help="work item index (default: first open)")
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Mark a work item done (default: first open item)."""
        root = self.root()
        todo = read_todo_required(root)
        work_items: List[JsonDict] = list(todo.get("WorkItems") or [])
        if not work_items:
            raise TodoError("no WorkItems on todo")
        index = self.index if self.index is not None else next(
            (idx for idx, item in enumerate(work_items) if not item.get("done")),
            None,
        )
        if index is None:
            raise TodoError("no open work items to mark done")
        if index < 0 or index >= len(work_items):
            raise TodoError(f"work item index out of range: {index}")
        work_items[index]["done"] = True
        todo["WorkItems"] = work_items
        write_todo_worktree(root, todo)
        if not self.no_commit:
            commit_todo(
                root,
                f"chore(todo): done work item {index}: "
                f"{_summary_snippet(work_items[index].get('summary', ''))}",
            )
        return 0


class UpdateCommand(TodoSubCommand):
    command_names = ("update", "set-path")
    doc_short: ClassVar[str] = "Update ticket path"
    doc_long: ClassVar[str] = (
        "Update/set-path edits a JSON path on a ticket selected by Id, unambiguous Id prefix, or "
        "self/curr. It checks out the branch that carries a non-current target ticket, parses the "
        "value as JSON when appropriate, and writes the updated TODO.json. By default it returns "
        "to the original branch after the edit. It prints the updated value so scripts can confirm "
        "the patch."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register update arguments."""
        parser.add_argument("selector", help="ticket selector: self, curr, Id prefix, or full digest")
        parser.add_argument("jsonpath", help="dot path, e.g. Body.raw or WorkItems.0.summary")
        parser.add_argument(
            "value",
            help="new value (JSON literal or string); use - to read from stdin",
        )
        parser.add_argument(
            "--stay",
            action="store_true",
            help="remain on the target branch after update (default: return to previous branch)",
        )
        parser.add_argument("--no-commit", action="store_true")

    def do(self) -> int:
        """Set a JSON path on the selected todo."""
        root = self.root()
        updated = update_ticket_path(
            root,
            self.selector,
            self.jsonpath,
            self.value,
            stay=self.stay,
            no_commit=self.no_commit,
        )
        print_json_value(updated)
        return 0


class MergeSubtodoCommand(TodoSubCommand):
    command_names = ("merge-subtodo", "merge-child")
    doc_short: ClassVar[str] = "Record child merge"
    doc_long: ClassVar[str] = (
        "Merge-subtodo records that a child ticket has been merged into its parent. It verifies "
        "the child ticket is done or already merged, checks out the child branch, and marks the "
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
    doc_short: ClassVar[str] = "Wait for ticket state"
    doc_long: ClassVar[str] = (
        "Wait-for polls selected child tickets until each reaches the requested state, done by "
        "default. Children signal progress by using set-state through todo.py; this command keeps "
        "the parent behind the same read interface instead of inspecting TODO.json directly."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register wait-for arguments."""
        parser.add_argument("selectors", nargs="+", help="ticket selectors to wait on")
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
        "Wait-and-merge waits for child tickets to reach done, then records each merge using the "
        "same merge-subtodo bookkeeping command. It is the barrier primitive for parent work items."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register wait-and-merge arguments."""
        parser.add_argument("child_ids", nargs="+", help="child ticket selectors to merge")
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


class DoctorCommand(TodoSubCommand):
    command_names = ("doctor",)
    doc_short: ClassVar[str] = "Audit ticket health"
    doc_long: ClassVar[str] = (
        "Doctor performs a read-only audit of a selected ticket. It validates selector resolution, "
        "top-level schema, State shape, Subtodos references, and basic wait graph sanity."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register doctor arguments."""
        parser.add_argument(
            "selector",
            nargs="?",
            default="self",
            help="ticket selector to audit (default: self)",
        )

    def do(self) -> int:
        """Audit a selected todo."""
        root = self.root()
        findings = doctor_findings(root, self.selector)
        print(json.dumps({"ok": not findings, "findings": findings}, indent=2))
        return 1 if findings else 0
        return 0


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


def _ticket_repo(ticket: JsonDict, default: Path) -> Path:
    """Repo a ticket (and its subtodo tree) lives in -- Scope.path_to_project, else *default*."""
    scope = ticket.get("Scope")
    if isinstance(scope, dict) and scope.get("path_to_project"):
        return Path(str(scope["path_to_project"]))
    return default


def _load_child_ticket(repo: Path, entry: JsonDict) -> Optional[JsonDict]:
    """Load a full child ticket via the Subtodos entry's Branch (O(1), no ref scan); fall back
    to a catalog lookup by Id. None if neither resolves (caller uses the entry snapshot)."""
    branch = str(entry.get("Branch", ""))
    if branch:
        todo = read_todo_at_ref(repo, branch)
        if todo is not None:
            return todo
    cid = str(entry.get("Id", ""))
    if len(cid) >= 4:
        for _loc, todo in catalog_matches(cid[:8]):
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
    parent = ticket.get("Parent")
    if isinstance(parent, dict) and parent.get("Branch"):
        base = str(parent["Branch"])
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
    """Map Id -> ticket for every discoverable TODO.json (worktree + branch refs)."""
    tickets: Dict[str, JsonDict] = {}
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
    doc_short: ClassVar[str] = "Show ticket graph (oneline, from TODO.json)"
    doc_long: ClassVar[str] = (
        "Log renders the ticket graph derived from TODO.json Subtodos relationships in "
        "git-log --graph --oneline style: one line per ticket as "
        "'* <Id[0:8]> <summary>  [<state>]', with vertical rails for the subtodo tree. The "
        "graph is read entirely from TODO.json files through todo.py's own readers, never "
        "from git history. Selector is self/curr or a 4+ hex Id prefix (default self); --all "
        "renders every discoverable ticket as a forest."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register log arguments."""
        parser.add_argument(
            "selector",
            nargs="?",
            default="self",
            help="ticket selector: self, curr, or 4+ hex Id prefix (default: self)",
        )
        parser.add_argument(
            "--all",
            dest="all_tickets",
            action="store_true",
            help="render every discoverable ticket as a forest",
        )
        parser.add_argument(
            "-n",
            "--max-count",
            type=int,
            default=None,
            help="limit the number of ticket lines printed",
        )
        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help="under each ticket, list its branch commits (the frequentcommit trail)",
        )
        parser.add_argument(
            "-t",
            "--timestamps",
            action="store_true",
            help="show timestamps: ticket update time on nodes, commit date on -v commit lines",
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
                _ticket_repo(ticket, root), ticket, [], lines, seen, self.verbose, self.timestamps
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
    command_names = ("web", "web-viewer")
    doc_short: ClassVar[str] = "Serve todo postmortem viewer"
    doc_long: ClassVar[str] = (
        "Web serves a two-pane viewer for a todo graph. The top pane walks "
        "the root todo, subtodos, and their branch commits. The bottom pane shows the selected "
        "commit diff in unified or pre/post form. It can be used during active work or as a "
        "postmortem review after the branch effort finishes."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Register web viewer arguments."""
        parser.add_argument(
            "selector",
            nargs="?",
            default="self",
            help="root todo selector: self, curr, or 4+ hex Id prefix (default: self)",
        )
        parser.add_argument("--host", default="127.0.0.1", help="bind host")
        parser.add_argument("--port", type=int, default=8765, help="bind port")
        parser.add_argument("--commit", help="selected commit hash")
        parser.add_argument(
            "--mode",
            choices=("unified", "prepost"),
            default="unified",
            help="initial diff mode",
        )
        parser.add_argument(
            "--dump-html",
            action="store_true",
            help="print the rendered HTML and exit instead of starting a server",
        )

    def do(self) -> int:
        """Serve or print the todo postmortem web viewer."""
        root = self.root()
        _, ticket = resolve_ticket_by_selector(root, self.selector)
        try:
            if self.dump_html:
                print(
                    todo_web.render_page(
                        root,
                        ticket,
                        selected_commit=self.commit,
                        mode=self.mode,
                    )
                )
            else:
                todo_web.serve(root, ticket, host=self.host, port=self.port)
        except todo_web.TodoWebError as exc:
            raise TodoError(str(exc)) from exc
        return 0


class ListCommand(TodoSubCommand):
    command_names = ("list",)
    doc_short: ClassVar[str] = "List catalog rows (~/.todo/catalog.txt)"
    doc_long: ClassVar[str] = (
        "List prints the append-only todo catalog (repo, id, branch, summary) -- the registry of "
        "where todos live, written on init. Where-to-find-it only; use 'read <id>' for ticket "
        "content. Path override: $TODO_CATALOG_PATH."
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """No arguments."""

    def do(self) -> int:
        """Print all catalog rows."""
        path = catalog_path()
        if not path.is_file():
            print(f"todo.py: no catalog at {path}", file=sys.stderr)
            return 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                print(line)
        return 0


COMMAND_CLASSES: Sequence[type[TodoSubCommand]] = (
    MintCommand,
    LogCommand,
    WebCommand,
    ListCommand,
    ReadCommand,
    ReadPathCommand,
    JqCommand,
    InitCommand,
    AddSubtodoCommand,
    SetStateCommand,
    SetCommand,
    WorkItemAddCommand,
    WorkItemDoneCommand,
    UpdateCommand,
    MergeSubtodoCommand,
    WaitForCommand,
    WaitAndMergeCommand,
    DoctorCommand,
)


TOP_LEVEL_EPILOG = """\
Repo & todo identity:
  gitroot      `git rev-parse --show-toplevel`: the local clone dir.
  repo root    the local directory where a repo is checked out (= gitroot). A
               repo can be cloned many times on one or many machines, so the
               same todo may exist in several checkouts; the repo root says
               WHICH checkout a branch lives in.
  TODO branch  a git repo whose gitroot holds a TODO.json.
  FQT          fully-qualified todo = repo-root + todo_id (the branch name is a
               git-storage artifact, so repo-root + branch-name is an accepted
               fallback for todos written on dev/master).

Repo selection:
  The repo root is the CURRENT directory's gitroot; there is no --repo flag.
  `cd` into the target repo or worktree before invoking. todo.py hard-errors if
  CWD is not a git repo. Find other checkouts with `git worktree list`; new
  worktrees go under {worktrees_root}/<repo-path>/<branch> by convention
  (`todo_db.worktrees_dir()`; override with $TODO_WORKTREES_DIR).
""".format(worktrees_root=todo_db.worktrees_dir())


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argparse parser."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="todo.py",
        description=(
            "Branch-bound TODO.json ticket CLI. Repo root is the current "
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
    except TodoError as exc:
        print(f"todo.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
